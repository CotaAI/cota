"""Detached execution checkpoints merge into the live conversation journal."""
import asyncio
from copy import deepcopy

import pytest

from cota.dst import DST
from cota.events import BotUtterEvent, Event, ToolResultEvent, UserUtterEvent
from cota.store import MemoryStore, SQLStore, StoreConflict


@pytest.fixture(params=['memory', 'sqlite'])
def store(request, tmp_path):
    value = MemoryStore() if request.param == 'memory' else SQLStore(db=str(tmp_path / 'groups.db'))
    yield value
    if isinstance(value, SQLStore):
        value.engine.dispose()


def start_branch():
    dst = DST('group', None)
    user = UserUtterEvent('first question')
    dst.append_event(user)
    dst.append_event(Event('run_started', {'input_event_id': user.event_id}, run_id='run'))
    return dst


@pytest.mark.asyncio
async def test_append_conversation_event_serializes_detached_inputs(store):
    first, second = UserUtterEvent('first'), UserUtterEvent('second')
    results = await asyncio.gather(
        store.append_conversation_event('group', first),
        store.append_conversation_event('group', second),
    )
    assert sorted(e['sequence'] for e in results) == [1, 2]
    assert first.sequence is None and second.sequence is None
    results[0]['payload']['text'] = 'caller mutation'
    first.payload['text'] = 'producer mutation'
    saved = await store.events('group')
    assert {e['payload']['text'] for e in saved} == {'first', 'second'}


@pytest.mark.asyncio
async def test_save_execution_creates_journal_and_is_idempotent(store):
    branch = start_branch()
    branch.record_run_skills('run', ['weather'])
    before = branch.as_dict()
    committed = await store.save_execution(branch)
    original = await store.export_session('group')
    assert committed == {event['event_id']: event for event in original['events']}
    assert await store.save_execution(branch) == committed
    assert await store.export_session('group') == original
    assert branch.as_dict() == before
    assert await store.run_metadata('group', 'run') == {'available_skills': ['weather']}


@pytest.mark.asyncio
async def test_execution_checkpoint_retains_interleaved_input_and_atomic_delivery(store):
    branch = start_branch()
    await store.save(branch)
    incoming = await store.append_conversation_event('group', UserUtterEvent('next question'))
    target = {'channel': 'feishu', 'scope': 'bot', 'chat_id': 'group'}
    execution_events = [
        Event('tool_started', {'tool_call_id': 'call', 'tool': 'weather', 'arguments': {}}, run_id='run'),
        ToolResultEvent('weather', 'sunny', tool_call_id='call', run_id='run'),
        BotUtterEvent('It is sunny', run_id='run'),
        Event('run_finished', {'status': 'completed'}, run_id='run'),
    ]
    for event in execution_events:
        branch.append_event(event)
        before = branch.as_dict()
        committed = await store.save_execution(branch, delivery_target=target)
        assert branch.as_dict() == before
        assert incoming['event_id'] not in committed
        assert committed[event.event_id]['sequence'] == event.sequence + 1
        assert await store.save_execution(branch, delivery_target=target) == committed

    canonical = await store.load('group')
    events = [event.as_dict() for event in canonical.events]
    assert [e['sequence'] for e in events] == list(range(1, len(events) + 1))
    assert len({e['event_id'] for e in events}) == len(events) == 7
    assert canonical.latest_user_text() == 'next question'
    assert branch.latest_user_text() == 'first question'
    assert all(message.get('content') != 'next question' for message in branch.context_messages)
    replay = DST.from_events('group', events, run_metadata=canonical.run_metadata)
    assert replay.state_dict() == canonical.state_dict()
    reply = execution_events[2]
    delivery = await store.delivery('group', reply.event_id)
    assert delivery['sequence'] == committed[reply.event_id]['sequence'] == 6
    assert await store.due_deliveries({'feishu': 'bot'}, now=1) == [delivery]


@pytest.mark.asyncio
async def test_execution_rejects_changed_persisted_fact_atomically(store):
    branch = start_branch()
    await store.save(branch)
    original = await store.export_session('group')
    changed = deepcopy(original['events'])
    changed[0]['payload']['text'] = 'rewritten input'
    branch = DST.from_events('group', changed)
    branch.append_event(BotUtterEvent('must not commit', run_id='run'))
    with pytest.raises(StoreConflict, match='event'):
        await store.save_execution(branch)
    assert await store.export_session('group') == original


@pytest.mark.asyncio
async def test_execution_merges_metadata_but_rejects_rewriting_existing_run(store):
    branch = start_branch()
    await store.save(branch)
    canonical = await store.load('group')
    canonical.record_run_skills('run', ['weather'])
    await store.save(canonical)
    branch.append_event(BotUtterEvent('reply', run_id='run'))
    await store.save_execution(branch)
    assert await store.run_metadata('group', 'run') == {'available_skills': ['weather']}
    original = await store.export_session('group')
    branch.record_run_skills('run', ['different'])
    with pytest.raises(StoreConflict, match='metadata'):
        await store.save_execution(branch)
    assert await store.export_session('group') == original


@pytest.mark.asyncio
async def test_execution_invalid_delivery_target_commits_nothing(store):
    branch = start_branch()
    branch.append_event(BotUtterEvent('reply', run_id='run'))
    with pytest.raises(ValueError, match='delivery_target'):
        await store.save_execution(branch, delivery_target={'channel': 'feishu'})
    assert await store.load('group') is None
