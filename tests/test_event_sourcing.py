"""Live reducers and reconstruction must agree at every durable event boundary."""
from copy import deepcopy
from unittest.mock import Mock

import pytest
from cota.events.resources import skill_read_name
import sqlalchemy as sa

from cota.dst import DST
from cota.events import Event, UserUtterEvent
from tests.resource_fixtures import skill_result
from cota.store import MemoryStore, SQLStore, StoreConflict


def replay(dst):
    return DST.from_events(dst.session_id, [e.as_dict() for e in dst.events], agent=None)


def test_all_state_changes_are_replayable_at_every_prefix():
    dst = DST('s', None, user_id='alice')
    memory = Mock()
    memory.get_all.return_value = {'city': '北京', 'nested': {'a': [1]}}
    operations = [
        lambda: dst.load_user_context(memory),
        lambda: dst.append_event(UserUtterEvent('查订单', timestamp=10)),
        lambda: dst.append_event(Event('run_started', {}, run_id='r')),
        lambda: dst.append_event(skill_result('orders')),
        lambda: dst.append_event(Event('tool_started', {'tool_call_id': 'c', 'tool': 'lookup', 'arguments': {'id': 42}})),
        lambda: dst.append_event(Event('run_finished', {'status': 'completed'})),
        lambda: dst.append_event(UserUtterEvent('继续')),
        lambda: dst.append_event(Event('run_started', {}, run_id='next')),
    ]
    assert replay(dst).state_dict() == dst.state_dict()
    for operation in operations:
        before = len(dst.events)
        operation()
        assert len(dst.events) > before
        assert replay(dst).state_dict() == dst.state_dict()
        assert dst.updated_at == dst.events[-1].timestamp
    assert dst.execution['status'] == 'running' and dst.active_skill == 'orders'
    memory.get_all.assert_called_once()


def test_state_values_are_detached_and_explicit_updates_are_events():
    dst = DST('s', None)
    value = {'nested': [1]}
    dst.update_user('alice', {'preference': value})
    value['nested'].append(2)
    dst.get_user_pref('preference')['nested'].append(3)
    dst.append_event(Event('run_started', {}, run_id='r'))
    dst.context_messages.append({'role': 'user'})
    assert dst.get_user_pref('preference') == {'nested': [1]}
    assert dst.context_messages == []
    assert replay(dst).state_dict() == dst.state_dict()


def test_apply_event_is_used_for_both_live_and_replay(monkeypatch):
    applied = []
    original = DST.apply_event
    def spy(self, event):
        applied.append(event.event_id)
        return original(self, event)
    monkeypatch.setattr(DST, 'apply_event', spy)
    dst = DST('s', None)
    dst.update_user('alice', {'city': '北京'})
    live_ids = applied[:]
    applied.clear()
    assert replay(dst).state_dict() == dst.state_dict()
    assert applied == live_ids


@pytest.fixture(params=['memory', 'sqlite'])
def event_store(request, tmp_path):
    store = (MemoryStore(snapshot_interval=5) if request.param == 'memory'
             else SQLStore(db=str(tmp_path / 'events.db'), snapshot_interval=5))
    yield store
    if hasattr(store, 'engine'):
        store.engine.dispose()


@pytest.mark.asyncio
async def test_snapshot_threshold_boundary_and_suffix_replay(event_store, monkeypatch):
    dst = DST('s', None)
    dst.append_event(UserUtterEvent('first'))
    await event_store.save(dst)
    assert await event_store.snapshot('s') is None
    for value in range(4):
        dst.append_event(UserUtterEvent(f'message {value + 2}'))
    await event_store.save(dst)
    snapshot = await event_store.snapshot('s')
    assert snapshot['last_sequence'] == 5 and 'events' not in snapshot['state']
    dst.append_event(UserUtterEvent('after snapshot'))
    await event_store.save(dst)
    calls = []
    original = DST.apply_event
    def spy(self, event):
        calls.append(event.sequence)
        return original(self, event)
    monkeypatch.setattr(DST, 'apply_event', spy)
    loaded = await event_store.load('s', agent=None)
    assert loaded.state_dict() == dst.state_dict()
    assert calls == [6]
    assert loaded.revision == dst.revision
    dst.append_event(Event('run_finished', {'status': 'completed'}, run_id='r'))
    await event_store.save(dst)
    assert (await event_store.snapshot('s'))['last_sequence'] == 7
    assert replay(dst).state_dict() == dst.state_dict()


@pytest.mark.asyncio
async def test_snapshot_missing_corrupt_or_future_version_falls_back(event_store):
    dst = DST('s', None, user_id='a')
    dst.update_user('alice', {'city': '北京'})
    dst.append_event(Event('run_finished', {'status': 'completed'}, run_id='r'))
    await event_store.save(dst)
    original = await event_store.snapshot('s')
    for broken in (None, {**original, 'schema_version': 999},
                   {**original, 'state': {'broken': True}}):
        if isinstance(event_store, MemoryStore):
            if broken is None:
                event_store.snapshots.pop('s', None)
            else:
                event_store.snapshots['s'] = deepcopy(broken)
        else:
            import json
            table = event_store.SQLSnapshot.__table__
            with event_store.engine.begin() as conn:
                conn.execute(table.delete().where(table.c.session_id == 's'))
                if broken is not None:
                    conn.execute(table.insert().values(session_id='s', data=json.dumps(broken),
                                                       last_sequence=broken['last_sequence']))
        loaded = await event_store.load('s', agent=None)
        assert loaded.state_dict() == dst.state_dict()
        assert loaded.revision == dst.revision


@pytest.mark.asyncio
async def test_sql_has_one_row_per_event_and_no_session_blob(tmp_path):
    store = SQLStore(db=str(tmp_path / 'rows.db'))
    try:
        dst = DST('s', None)
        dst.update_user('alice', {'city': '北京'})
        dst.append_event(UserUtterEvent('hi'))
        await store.save(dst)
        dst.update_user('alice', {'city': '上海'})
        await store.save(dst)
        with store.engine.connect() as conn:
            assert conn.scalar(sa.select(sa.func.count()).select_from(store.SQLEvent)) == 3
        assert 'data' not in store.SQLSession.__table__.c
        assert [e['sequence'] for e in await store.events('s', after_sequence=1)] == [2, 3]
    finally:
        store.engine.dispose()


@pytest.mark.asyncio
async def test_explicit_integer_event_time_survives_sql_roundtrip(event_store):
    dst = DST('integer-time', None)
    dst.append_event(UserUtterEvent('hi', timestamp=123))
    await event_store.save(dst)
    loaded = await event_store.load(dst.session_id)
    assert loaded.state_dict() == dst.state_dict()
    assert loaded.as_dict() == dst.as_dict()


@pytest.mark.asyncio
async def test_real_pi_every_checkpoint_reconstructs_and_resume_has_no_duplicate_effects(mock_agent, event_store):
    from cota.runtime.pi_runtime import PiAgentRuntime
    from tests.test_pi_runtime import call
    dst = DST('pi-replay', mock_agent, user_id='alice')
    dst.append_event(UserUtterEvent('weather'))
    checkpoints = []
    async def checkpoint(tracker):
        expected = tracker.state_dict()
        assert replay(tracker).state_dict() == expected
        await event_store.save(tracker)
        assert (await event_store.load(tracker.session_id)).state_dict() == expected
        checkpoints.append(deepcopy(expected))
    mock_agent._llm_mock.generate_chat.side_effect = [
        {'tool_calls': [call('read', {'path': mock_agent.skill_file('SearchWeb')})]},
        {'content': '哪个城市？'},
        {'content': '晴天'},
    ]
    await PiAgentRuntime(mock_agent, dst, dst.session_id, checkpoint=checkpoint).run()
    assert dst.execution['status'] == 'completed'
    assert dst.latest_bot_text() == '哪个城市？'
    snapshot = await event_store.snapshot(dst.session_id)
    assert snapshot['last_sequence'] == len(dst.events)
    assert any(s['execution'].get('pending_tools') for s in checkpoints)
    assert any(s['active_skill'] == 'SearchWeb' for s in checkpoints)
    # State above is reconstructed solely from events. Resuming a persisted
    # session also carries its immutable resource provenance (as Store.load does).
    restored = DST.from_events(dst.session_id, dst.events, mock_agent,
                               revision=dst.revision, run_metadata=dst.run_metadata)
    restored.append_event(UserUtterEvent('北京'))
    await PiAgentRuntime(mock_agent, restored, dst.session_id, checkpoint=checkpoint).run()
    assert restored.execution['status'] == 'completed'
    assert restored.latest_bot_text() == '晴天'
    assert mock_agent._llm_mock.generate_chat.await_count == 3
    assert len([e for e in restored.events if skill_read_name(e)]) == 1


@pytest.mark.asyncio
async def test_processor_get_tracker_does_not_refresh_persisted_context(mock_agent, event_store):
    from cota.processor import Processor
    dst = DST('read-only', mock_agent, user_id='alice')
    memory = Mock()
    memory.get_all.return_value = {'city': '北京'}
    dst.load_user_context(memory)
    await event_store.save(dst)
    mock_agent.user_memory = Mock()
    mock_agent.user_memory.get_all.side_effect = AssertionError('recovery must not read live user memory')
    restored = await Processor(mock_agent, event_store).get_tracker(dst.session_id)
    assert restored.state_dict() == dst.state_dict()
    mock_agent.user_memory.get_all.assert_not_called()


@pytest.mark.asyncio
async def test_sql_rollback_does_not_publish_events_or_snapshot(tmp_path):
    store = SQLStore(db=str(tmp_path / 'rollback.db'), snapshot_interval=1)
    dst = DST('s', None)
    dst.append_event(UserUtterEvent('message 1'))
    await store.save(dst)
    previous = await store.export_session('s')
    snapshot = await store.snapshot('s')
    dst.append_event(UserUtterEvent('message 2'))
    def fail_snapshot(conn, cursor, statement, params, context, executemany):
        if statement.startswith('INSERT INTO session_snapshots'):
            raise RuntimeError('snapshot write failed')
    sa.event.listen(store.engine, 'before_cursor_execute', fail_snapshot)
    try:
        with pytest.raises(RuntimeError, match='snapshot write failed'):
            await store.save(dst)
        assert await store.export_session('s') == previous
        assert await store.snapshot('s') == snapshot
        assert dst.revision == previous['revision']
    finally:
        sa.event.remove(store.engine, 'before_cursor_execute', fail_snapshot)
        store.engine.dispose()


@pytest.mark.asyncio
async def test_two_sql_instances_reject_stale_writer(tmp_path):
    path = str(tmp_path / 'shared.db')
    a, b = SQLStore(db=path, snapshot_interval=1), SQLStore(db=path, snapshot_interval=1)
    try:
        dst = DST('s', None)
        dst.append_event(UserUtterEvent('message 1'))
        await a.save(dst)
        stale = await b.load('s')
        dst.append_event(UserUtterEvent('message 2'))
        await a.save(dst)
        stale.append_event(UserUtterEvent('message 3'))
        with pytest.raises(StoreConflict):
            await b.save(stale)
        assert (await b.load('s')).state_dict() == dst.state_dict()
        assert (await b.snapshot('s'))['last_sequence'] == len(dst.events)
    finally:
        a.engine.dispose()
        b.engine.dispose()


@pytest.mark.parametrize('changes', [
    {'messages': None}, {'pending_tools': []}, {'pending_tools': {'c': None}},
    {'status': 'unknown'}, {'run_id': 42},
])
def test_invalid_execution_updates_are_rejected_before_state_changes(changes):
    dst = DST('s', None)
    before = dst.as_dict()
    with pytest.raises(ValueError):
        dst.append_event(Event('run_started', changes, run_id='invalid'))
    assert dst.as_dict() == before


@pytest.mark.asyncio
@pytest.mark.parametrize('status', ['completed', 'limited', 'failed', 'interrupted'])
async def test_every_run_terminal_status_saves_snapshot_once(event_store, status):
    dst = DST('boundary', None)
    dst.append_event(UserUtterEvent('hello'))
    dst.append_event(Event('run_started', {'input_event_id': dst.latest_user_event.event_id}, run_id='r'))
    await event_store.save(dst)
    assert await event_store.snapshot(dst.session_id) is None
    dst.append_event(Event('run_finished', {'status': status}, run_id='r'))
    await event_store.save(dst)
    saved = await event_store.snapshot(dst.session_id)
    assert saved['state']['execution']['status'] == status
    await event_store.save(dst)
    assert await event_store.snapshot(dst.session_id) == saved
    assert (await event_store.load(dst.session_id)).state_dict() == replay(dst).state_dict()


@pytest.mark.asyncio
async def test_bypassing_state_events_is_rejected(event_store):
    dst = DST('private-mutation', None)
    dst.update_user('alice', {'city': '北京'})
    await event_store.save(dst)
    dst._user_context['city'] = '上海'
    with pytest.raises(ValueError, match='produced by events'):
        await event_store.save(dst)
    assert (await event_store.load(dst.session_id)).get_user_pref('city') == '北京'


@pytest.mark.asyncio
async def test_snapshot_cannot_hide_missing_events(event_store):
    dst = DST('missing-event', None)
    dst.append_event(UserUtterEvent('hello'))
    dst.append_event(Event('run_finished', {'status': 'completed'}, run_id='r'))
    await event_store.save(dst)
    assert await event_store.snapshot(dst.session_id)
    if isinstance(event_store, MemoryStore):
        event_store.event_rows[dst.session_id].pop(0)
    else:
        table = event_store.SQLEvent.__table__
        with event_store.engine.begin() as conn:
            conn.execute(table.delete().where(table.c.session_id == dst.session_id, table.c.sequence == 1))
    with pytest.raises(ValueError, match='event stream'):
        await event_store.load(dst.session_id)
@pytest.mark.parametrize('extra', [{'reason': 'network'}, {'tokens_before': -1}, {'tokens_before': True}])
def test_compaction_diagnostics_are_validated(extra):
    with pytest.raises(ValueError, match='compaction|tokens_before'):
        Event('context_compaction', {'summary': 'older facts', 'replaced_message_ids': ['u'], **extra}).validate()
