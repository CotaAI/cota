"""Runtime commits validate new facts; load/export retain whole-journal checks."""
from unittest.mock import patch

import pytest

from cota.dst import DST
from cota.events import UserUtterEvent, BotUtterEvent, Event
from cota.store import MemoryStore, SQLStore


@pytest.fixture(params=['memory', 'sqlite'])
def store(request, tmp_path):
    value = MemoryStore() if request.param == 'memory' else SQLStore(db=str(tmp_path / 'incremental.db'))
    yield value
    if isinstance(value, SQLStore):
        value.engine.dispose()


@pytest.mark.asyncio
async def test_no_change_keeps_revision_and_updated_at(store):
    dst = DST('s', None)
    dst.append_event(UserUtterEvent('hello'))
    await store.save(dst)
    metadata = await store.session_metadata('s')
    await store.save(dst)
    assert await store.session_metadata('s') == metadata
    assert dst.revision == metadata['revision']


@pytest.mark.asyncio
async def test_append_does_not_export_or_replay_full_history(store):
    dst = DST('s', None)
    dst.append_event(UserUtterEvent('large evidence'))
    await store.save(dst)
    dst.append_event(BotUtterEvent('next'))
    with patch.object(DST, 'as_dict', side_effect=AssertionError('full export')), \
         patch.object(DST, 'from_events', side_effect=AssertionError('full replay')):
        await store.save(dst)
        await store.save(dst)
    restored = await store.load('s')
    assert restored.state_dict() == dst.state_dict()
    assert len(restored.events) == 2


@pytest.mark.asyncio
async def test_canonical_event_hash_unchanged_by_incremental_commits(store):
    from cota.snapshots import digest
    dst = DST('s', None)
    for text in ('北京', '工具内容', 'done'):
        dst.append_event(UserUtterEvent(text))
        await store.save(dst)
        metadata = await store.session_metadata('s')
        assert metadata['events_hash'] == digest([e.as_dict() for e in dst.events])
    await store.save(dst)
    dst = await store.load('s')
    dst.append_event(BotUtterEvent('resumed'))
    await store.save(dst)
    assert (await store.load('s')).state_dict() == dst.state_dict()


@pytest.mark.asyncio
async def test_execution_checkpoints_reuse_validated_canonical_journal(store):
    branch = DST('s', None)
    user = UserUtterEvent('hello')
    branch.append_event(user)
    branch.append_event(Event('run_started', {'input_event_id': user.event_id}, run_id='r'))
    await store.save_execution(branch)
    branch.append_event(BotUtterEvent('one', run_id='r'))
    with patch.object(DST, 'as_dict', side_effect=AssertionError('full export')), \
         patch.object(DST, 'from_events', side_effect=AssertionError('full replay')):
        await store.save_execution(branch)
        await store.save_execution(branch)
    # A newly received input invalidates the cached canonical revision.
    incoming = await store.append_conversation_event('s', UserUtterEvent('later'))
    branch.append_event(BotUtterEvent('two', run_id='r'))
    await store.save_execution(branch)
    events = await store.events('s')
    assert incoming['event_id'] in [e['event_id'] for e in events]
    assert [e['sequence'] for e in events] == list(range(1, 6))
    assert (await store.load('s')).latest_user_text() == 'later'


def test_internal_context_and_facts_cannot_bypass_incremental_hashes():
    dst = DST('sealed', None)
    dst.append_event(UserUtterEvent('original', metadata={'nested': [1]}))
    with pytest.raises(TypeError, match='immutable'):
        dst._context_messages[0]['content'] = 'invented state'
    with pytest.raises(TypeError, match='immutable'):
        dst._events[0].payload['metadata']['nested'].append(2)
    with pytest.raises(TypeError, match='immutable'):
        dst._events[0].timestamp = 99
    # External copies remain ordinary mutable JSON/Event values.
    event = dst.events[0]
    event.payload['metadata']['nested'].append(2)
    event.timestamp = 99
    context = dst.context_messages
    context[0]['content'] = 'external edit'
    assert dst.latest_user_text() == 'original'
    assert dst.events[0].payload['metadata']['nested'] == [1]


@pytest.mark.asyncio
async def test_execution_cursor_only_acknowledges_facts_captured_before_save():
    import asyncio
    store = MemoryStore()
    branch = DST('race', None)
    branch.append_event(UserUtterEvent('hello'))
    branch.append_event(Event('run_started', {}, run_id='r'))
    entered, release = asyncio.Event(), asyncio.Event()
    original = store.save
    async def gated(dst, **kwargs):
        entered.set()
        await release.wait()
        await original(dst, **kwargs)
    store.save = gated
    task = asyncio.create_task(store.save_execution(branch))
    await entered.wait()
    branch.append_event(BotUtterEvent('during SQL await', run_id='r'))
    release.set()
    await task
    store.save = original
    await store.save_execution(branch)
    assert [event['payload']['text'] for event in await store.history('race')] == ['hello', 'during SQL await']
