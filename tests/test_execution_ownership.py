"""Local recovery requires exclusive ownership, not a stale timestamp."""
import asyncio
import os
from pathlib import Path
import subprocess
import sys

import pytest

from cota.dst import DST
from cota.events import Event, UserUtterEvent
from cota.runtime.pi_runtime import RunInProgress
from cota.store import MemoryStore, SQLStore
from tests.test_run_recovery import partial_batch


pytestmark = pytest.mark.skipif(os.name != 'posix', reason='Local ownership uses POSIX descriptor locks')


@pytest.fixture(params=['memory', 'sqlite'])
def store(request, tmp_path):
    value = MemoryStore() if request.param == 'memory' else SQLStore(db=str(tmp_path / 'sessions.db'))
    yield value
    if isinstance(value, SQLStore):
        value.engine.dispose()


async def abandoned(store):
    dst = partial_batch()
    # Ownership is part of the original start fact, not a mutable heartbeat.
    facts = [event.as_dict() for event in dst.events]
    with store.execution_guard(dst.session_id) as guard:
        facts[1]['payload']['executor'] = guard.identity
        dst = DST.from_events(dst.session_id, [Event.from_dict(fact) for fact in facts])
        await store.save(dst)
    return dst


async def test_reconcile_only_appends_terminal_fact_and_preserves_unknown_results(store):
    original = await abandoned(store)
    await store.ensure_input_admissible(original.session_id)
    restored = await store.load(original.session_id)
    assert restored.execution['status'] == 'interrupted'
    assert restored.as_dict()['events'][:-1] == original.as_dict()['events']
    assert restored.events[-1].type == 'run_finished'
    assert restored.events[-1].payload['error_type'] == 'ExecutorExited'
    assert restored.execution['pending_tools'] == original.execution['pending_tools']
    assert sum(event.type == 'tool_result' for event in restored.events) == 1
    assert restored.context_messages[-1]['cotaRecovery']
    assert 'outcome is unknown' in restored.context_messages[-1]['content'][0]['text']
    await store.ensure_input_admissible(original.session_id)
    assert (await store.load(original.session_id)).as_dict() == restored.as_dict()
    assert DST.from_events(original.session_id, restored.events).state_dict() == restored.state_dict()


async def test_active_owner_prevents_reconciliation(store):
    original = await abandoned(store)
    with store.execution_guard(original.session_id):
        with pytest.raises(RunInProgress):
            await store.ensure_input_admissible(original.session_id)
    assert (await store.load(original.session_id)).as_dict() == original.as_dict()


async def test_reopening_sqlite_recovers_same_local_scope(tmp_path):
    first = SQLStore(db=str(tmp_path / 'sessions.db'))
    second = SQLStore(db=str(tmp_path / 'sessions.db'))
    try:
        original = await abandoned(first)
        with first.execution_guard(original.session_id):
            with pytest.raises(RunInProgress):
                await second.ensure_input_admissible(original.session_id)
            with second.execution_guard('different-session'):
                pass
        await second.ensure_input_admissible(original.session_id)
        assert (await first.load(original.session_id)).execution['status'] == 'interrupted'
    finally:
        first.engine.dispose()
        second.engine.dispose()


@pytest.mark.parametrize('owner', [None, {'host': 'another-host', 'scope': 'another-store'}])
async def test_unverified_owner_is_never_presumed_dead(store, owner):
    dst = DST('unverified', None)
    dst.append_event(UserUtterEvent('hello'))
    dst.append_event(Event('run_started', {'input_event_id': dst.latest_user_event.event_id,
        **({'executor': owner} if owner else {})}, run_id='old'))
    await store.save(dst)
    with pytest.raises(RunInProgress):
        await store.ensure_input_admissible(dst.session_id)
    assert (await store.load(dst.session_id)).execution['status'] == 'running'


async def test_reads_do_not_reconcile_or_start_work(store):
    dst = await abandoned(store)
    assert (await store.load(dst.session_id)).execution['status'] == 'running'
    assert (await store.execution_progress(dst.session_id))['status'] == 'running'
    assert len(await store.events(dst.session_id)) == len(dst.events)


async def test_child_keeps_ownership_after_parent_closes_descriptor(store):
    with store.execution_guard('session') as guard:
        child = subprocess.Popen([sys.executable, '-c', 'import sys; sys.stdin.read()'],
                                 stdin=subprocess.PIPE, pass_fds=(guard.fd,))
    try:
        with pytest.raises(RunInProgress):
            with store.execution_guard('session'):
                pass
    finally:
        child.communicate(timeout=5)
    with store.execution_guard('session'):
        pass


async def test_new_explicit_input_continues_without_replaying_unknown_tool(mock_agent, store):
    from unittest.mock import AsyncMock
    from cota.application import Application
    from cota.executor.tools.base import FunctionTool, create_tool_schema
    dst = await abandoned(store)
    mock_agent.cleanup = AsyncMock()
    effect = AsyncMock()
    mock_agent.get_tool_registry().register(FunctionTool('create_order', 'create order', create_tool_schema({}), effect))
    mock_agent._llm_mock.generate_chat.return_value = {'content': 'The prior lookup found order 123; check the unknown operation first.'}
    mock_agent.store = store
    async with Application(mock_agent, channels=[]) as app:
        assert (await store.load(dst.session_id)).execution['status'] == 'running'
        submission = await app.submit(user_id='alice', session_id=dst.session_id, text='continue')
        receipt = await asyncio.wait_for(submission.wait(), 15)
    assert receipt['receipt']['status'] == 'completed'
    effect.assert_not_awaited()
    request = mock_agent._llm_mock.generate_chat.call_args.kwargs['messages']
    assert '123' in str(request)
    assert 'outcome is unknown' in str(request)
    saved = await store.load(dst.session_id)
    finishes = [event for event in saved.events if event.type == 'run_finished']
    assert [event.payload['status'] for event in finishes] == ['interrupted', 'completed']
    start = next(event for event in reversed(saved.events) if event.type == 'run_started')
    with store.execution_guard(dst.session_id) as guard:
        assert start.payload['executor'] == guard.identity


async def test_cmdline_processor_recovers_before_recording_new_input(mock_agent, store):
    from cota.processor import Processor
    from cota.message import Message
    dst = await abandoned(store)
    processor = Processor(mock_agent, store)
    await processor.handle_message(Message(text='continue', session_id=dst.session_id, sender_id='alice', receiver='bot'))
    saved = await store.load(dst.session_id)
    assert saved.execution['status'] == 'completed'
    terminal = next(e for e in saved.events if e.type == 'run_finished')
    latest_input = saved.latest_user_event
    assert terminal.sequence < latest_input.sequence
    assert terminal.payload['error_type'] == 'ExecutorExited'


async def test_duplicate_original_input_does_not_recover_or_run_again(mock_agent, store):
    from cota.processor import Processor
    from cota.message import Message
    from cota.inputs import input_event_id
    message = Message(text='start', session_id='duplicate', sender_id='alice', message_id='original', receiver='bot')
    dst = DST(message.session_id, mock_agent)
    dst.append_event(UserUtterEvent(message.text, event_id=input_event_id(message.message_id), metadata={
        'message_id': message.message_id, 'sender': 'user', 'sender_id': 'alice', 'media': [], 'execute': True}))
    with store.execution_guard(dst.session_id) as guard:
        dst.append_event(Event('run_started', {'input_event_id': dst.latest_user_event.event_id,
                                              'executor': guard.identity}, run_id='old'))
        await store.save(dst)
    await Processor(mock_agent, store).handle_message(message)
    assert (await store.load(dst.session_id)).as_dict() == dst.as_dict()
    mock_agent._llm_mock.generate_chat.assert_not_awaited()


async def test_failed_recovery_commit_does_not_allow_new_execution(store, monkeypatch):
    from unittest.mock import AsyncMock
    dst = await abandoned(store)
    monkeypatch.setattr(store, 'save', AsyncMock(side_effect=OSError('disk full')))
    with pytest.raises(OSError, match='disk full'):
        await store.ensure_input_admissible(dst.session_id)
    assert (await store.load(dst.session_id)).as_dict() == dst.as_dict()


async def test_stale_recovery_cannot_duplicate_terminal_fact(store):
    from cota.store import StoreConflict
    dst = await abandoned(store)
    stale = await store.load(dst.session_id)
    await store.ensure_input_admissible(dst.session_id)
    with pytest.raises(StoreConflict):
        await store.recover_interrupted_run(stale)
    saved = await store.load(dst.session_id)
    assert sum(event.type == 'run_finished' for event in saved.events) == 1


async def test_remote_sql_backend_cannot_prove_local_executor_exit():
    from types import SimpleNamespace
    store = MemoryStore()
    dst = await abandoned(store)
    store.engine = SimpleNamespace(dialect=SimpleNamespace(name='mysql'))
    with pytest.raises(RunInProgress, match='cannot be verified'):
        await store.ensure_input_admissible(dst.session_id)
    assert (await store.load(dst.session_id)).execution['status'] == 'running'


@pytest.mark.parametrize('identity', [None, [], {}, {'host': 'h'}, {'host': 'h', 'scope': 1},
                                    {'host': '', 'scope': 's'}, {'host': 'h', 'scope': 's', 'pid': 123}])
def test_executor_identity_requires_a_complete_local_binding(identity):
    with pytest.raises(ValueError, match='executor'):
        Event('run_started', {'executor': identity}, run_id='r')


@pytest.mark.parametrize('database', [None, '', ':memory:'])
def test_ephemeral_sqlite_retains_instance_scoped_ownership(database):
    store = SQLStore(db=database)
    other = SQLStore(db=database)
    try:
        with store.execution_guard('s'):
            with other.execution_guard('s'):
                pass
            with pytest.raises(RunInProgress):
                with store.execution_guard('s'):
                    pass
    finally:
        store.engine.dispose()
        other.engine.dispose()


async def test_killed_python_cannot_release_surviving_node_ownership(tmp_path):
    """Actual pipes/processes: a worker surviving supervisor death blocks takeover."""
    import json
    worker = tmp_path / 'holding-worker.mjs'
    ready = tmp_path / 'worker-ready.json'
    worker.write_text('''import fs from 'node:fs';
import readline from 'node:readline';
const input = readline.createInterface({input: process.stdin});
input.once('line', () => fs.writeFileSync(process.argv[2], JSON.stringify({pid: process.pid})));
setInterval(() => {}, 1000);
'''.replace('process.argv[2]', json.dumps(str(ready))))
    database = tmp_path / 'sessions.db'
    coordinator = tmp_path / 'coordinator.py'
    coordinator.write_text('''import asyncio, sys
from types import SimpleNamespace
from cota.runtime import pi_bridge
from cota.runtime.pi_distribution import resolve_runtime
from cota.store import SQLStore
from cota.dst import DST
from cota.events import Event, UserUtterEvent
runtime = resolve_runtime()
pi_bridge.resolve_runtime = lambda node: SimpleNamespace(node=runtime.node, worker=sys.argv[2])
async def main():
    store = SQLStore(db=sys.argv[1])
    with store.execution_guard('crashed') as guard:
        dst = DST('crashed', None)
        dst.append_event(UserUtterEvent('work'))
        dst.append_event(Event('run_started', {'input_event_id': dst.latest_user_event.event_id,
                                              'executor': guard.identity}, run_id='old'))
        await store.save(dst)
        bridge = pi_bridge.PiBridge(timeout=60)
        bridge.execution_fd = guard.fd
        await bridge.run({}, None)
asyncio.run(main())
''')
    owner = subprocess.Popen([sys.executable, str(coordinator), str(database), str(worker)],
                             cwd=Path(__file__).resolve().parents[1], stderr=subprocess.PIPE)
    worker_pid, store = None, None
    try:
        async with asyncio.timeout(10):
            while not ready.exists():
                if owner.poll() is not None:
                    pytest.fail(owner.stderr.read().decode())
                await asyncio.sleep(.02)
        worker_pid = json.loads(ready.read_text())['pid']
        owner.kill()
        await asyncio.to_thread(owner.wait, 5)
        store = SQLStore(db=str(database))
        with pytest.raises(RunInProgress):
            await store.ensure_input_admissible('crashed')
        os.kill(worker_pid, 15)
        async with asyncio.timeout(5):
            while True:
                try:
                    await store.ensure_input_admissible('crashed')
                    break
                except RunInProgress:
                    await asyncio.sleep(.02)
        assert (await store.load('crashed')).execution['status'] == 'interrupted'
    finally:
        if owner.poll() is None:
            owner.kill()
        await asyncio.to_thread(owner.wait, 5)
        owner.stderr.close()
        if worker_pid:
            try:
                os.kill(worker_pid, 9)
            except ProcessLookupError:
                pass
        if store:
            store.engine.dispose()
