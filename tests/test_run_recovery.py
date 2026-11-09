"""End runs without reset; repair protocol context without inventing tool facts."""
from copy import deepcopy
from unittest.mock import AsyncMock
import asyncio

import pytest

from cota.dst import DST
from cota.events import Event, UserUtterEvent, ToolResultEvent
from cota.events.resources import skill_read_name
from cota.policy import PolicyContext
from cota.runtime.pi_runtime import PiAgentRuntime
from cota.executor.tools.base import FunctionTool, create_tool_schema
from cota.snapshots import make_snapshot
from cota.store import MemoryStore, SQLStore
from tests.test_pi_runtime import call


def partial_batch(agent=None):
    dst = DST('recovery', agent)
    dst.append_event(UserUtterEvent('process the tasks'))
    dst.append_event(Event('run_started', {'input_event_id': dst.latest_user_event.event_id}, run_id='old'))
    blocks = [
        {'type': 'toolCall', 'id': 'done', 'name': 'lookup', 'arguments': {}},
        {'type': 'toolCall', 'id': 'missing', 'name': 'read', 'arguments': {'path': 'skills/weather/SKILL.md'}},
        {'type': 'toolCall', 'id': 'tail', 'name': 'create_order', 'arguments': {}},
    ]
    owner = Event('tool_started', {
        'tool_call_id': 'done', 'tool': 'lookup', 'arguments': {},
        'llm': {'request_id': 'request-old', 'request_sequence': 1, 'stop_reason': 'toolUse',
                'message': {'content': blocks, 'stop_reason': 'toolUse'}},
    }, run_id='old')
    dst.append_event(owner)
    dst.append_event(ToolResultEvent('lookup', result={'order_id': '123'}, tool_call_id='done'))
    dst.append_event(Event('tool_started', {
        'tool_call_id': 'missing', 'tool': 'read', 'arguments': blocks[1]['arguments'],
        'llm_event_id': owner.event_id,
    }, run_id='old'))
    return dst


@pytest.mark.parametrize('status', ['failed', 'interrupted', 'limited'])
@pytest.mark.parametrize('input_before_finish', [False, True])
def test_terminal_projection_keeps_results_and_closes_entire_batch(status, input_before_finish):
    dst = partial_batch()
    original = dst.as_dict()['events']
    real_result = deepcopy(dst.context_messages[-1])
    if input_before_finish:
        dst.append_event(UserUtterEvent('continue'))
    snapshot = make_snapshot(dst)
    dst.append_event(Event('run_finished', {'status': status}))
    if not input_before_finish:
        dst.append_event(UserUtterEvent('continue'))
    messages = dst.context_messages
    assert [m['role'] for m in messages] == ['user', 'assistant', 'toolResult', 'toolResult', 'toolResult', 'user']
    assert messages[2] == real_result
    notices = messages[3:5]
    assert [m['toolCallId'] for m in notices] == ['missing', 'tail']
    assert all(m['cotaRecovery'] and 'cotaResultEventId' not in m for m in notices)
    assert all('outcome is unknown' in m['content'][0]['text'] for m in notices)
    assert len({m['cotaEventId'] for m in messages}) == len(messages)
    assert list(dst.execution['pending_tools']) == ['missing']
    assert dst.trace('old')['calls'][1]['status'] == 'pending'
    assert len([e for e in dst.events if e.type == 'tool_result']) == 1
    assert dst.as_dict()['events'][:len(original)] == original
    for cache in (None, snapshot, make_snapshot(dst)):
        assert DST.from_events(dst.session_id, dst.events, snapshot=cache).state_dict() == dst.state_dict()
    context = PolicyContext.from_runtime(messages, dst, ['weather'], [], max_chars=16000)
    inferred = [o for o in context.observations if o.get('source') == 'runtime']
    assert len(inferred) == 2
    assert all(o['outcome'] == 'unknown' and 'event_id' not in o for o in inferred)
    assert not any(skill_read_name(e) for e in dst.events)


@pytest.mark.asyncio
@pytest.mark.parametrize('backend', ['memory', 'sqlite'])
@pytest.mark.parametrize('status', ['failed', 'interrupted'])
async def test_new_input_runs_without_reexecuting_old_batch(mock_agent, tmp_path, backend, status):
    store = MemoryStore() if backend == 'memory' else SQLStore(db=str(tmp_path / 'recovery.db'))
    try:
        dst = partial_batch(mock_agent)
        dst.append_event(Event('run_finished', {'status': status}))
        await store.save(dst)
        recovered = await store.load(dst.session_id, mock_agent)
        before = recovered.as_dict()
        await PiAgentRuntime(mock_agent, recovered, dst.session_id, checkpoint=store.save).run()
        mock_agent._llm_mock.generate_chat.assert_not_awaited()
        assert recovered.as_dict() == before  # no implicit retry of the same input
        recovered.append_event(UserUtterEvent('What happened?'))
        effect = AsyncMock(return_value={'success': True})
        mock_agent.get_tool_registry().register(FunctionTool('create_order', 'create order', create_tool_schema({}), effect))
        mock_agent._llm_mock.generate_chat.return_value = {'content': 'The previous outcome needs checking.'}
        await PiAgentRuntime(mock_agent, recovered, dst.session_id, checkpoint=store.save).run()
        request = mock_agent._llm_mock.generate_chat.call_args.kwargs['messages']
        assert [m['role'] for m in request] == ['system', 'user', 'assistant', 'tool', 'tool', 'tool', 'user']
        assert [m['tool_call_id'] for m in request if m['role'] == 'tool'] == ['done', 'missing', 'tail']
        assert '123' in request[3]['content']
        assert all('outcome is unknown' in m['content'] for m in request[4:6])
        effect.assert_not_awaited()
        assert recovered.execution['status'] == 'completed'
        assert recovered.execution['pending_tools'] == {}
        assert len([e for e in recovered.events if e.type == 'tool_result']) == 1
        assert (await store.load(dst.session_id)).state_dict() == recovered.state_dict()
    finally:
        if isinstance(store, SQLStore):
            store.engine.dispose()


@pytest.mark.asyncio
async def test_cancelled_tool_does_not_run_again_when_user_continues(mock_agent):
    store, entered = MemoryStore(), asyncio.Event()
    effects = []
    async def effect():
        effects.append('submitted')
        entered.set()
        await asyncio.Event().wait()
    mock_agent.get_tool_registry().register(FunctionTool('effect', 'effect', create_tool_schema({}), effect))
    mock_agent._llm_mock.generate_chat.return_value = {'tool_calls': [call('effect', {}, 'c')]}
    dst = DST('cancelled-tool', mock_agent)
    dst.append_event(UserUtterEvent('submit'))
    task = asyncio.create_task(PiAgentRuntime(mock_agent, dst, dst.session_id, checkpoint=store.save).run())
    await asyncio.wait_for(entered.wait(), 10)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    saved = await store.load(dst.session_id, mock_agent)
    assert saved.execution['status'] == 'interrupted'
    assert not any(e.type == 'tool_result' for e in saved.events)
    assert saved.context_messages[-1]['cotaRecovery']
    saved.append_event(UserUtterEvent('check the status'))
    mock_agent._llm_mock.generate_chat.return_value = {'content': 'The outcome is unknown; check the external state.'}
    await PiAgentRuntime(mock_agent, saved, saved.session_id, checkpoint=store.save).run()
    assert effects == ['submitted']
    assert saved.execution['status'] == 'completed'


def test_recovery_notices_can_be_compacted_and_replayed():
    dst = partial_batch()
    dst.append_event(Event('run_finished', {'status': 'interrupted'}))
    prefix = make_snapshot(dst)
    ids = [m['cotaEventId'] for m in dst.context_messages]
    dst.append_event(UserUtterEvent('next task'))
    dst.append_event(Event('run_started', {'input_event_id': dst.latest_user_event.event_id}, run_id='new'))
    dst.append_event(Event('context_compaction', {'summary': 'Order 123 was found; other outcomes remain unknown.',
                                                'replaced_message_ids': ids}))
    assert len(dst.context_messages) == 2
    assert DST.from_events(dst.session_id, dst.events, snapshot=prefix).state_dict() == dst.state_dict()
    assert DST.from_events(dst.session_id, dst.events).state_dict() == dst.state_dict()


def test_old_snapshot_without_recovery_projection_is_rebuilt():
    from cota.snapshots import digest
    dst = partial_batch()
    dst.append_event(Event('run_finished', {'status': 'interrupted'}))
    snapshot = make_snapshot(dst)
    snapshot['schema_version'] = 8
    snapshot['state']['context_messages'] = [
        m for m in snapshot['state']['context_messages'] if not m.get('cotaRecovery')]
    snapshot.pop('checksum')
    snapshot['checksum'] = digest(snapshot)
    restored = DST.from_events(dst.session_id, dst.events, snapshot=snapshot)
    assert restored.state_dict() == dst.state_dict()
