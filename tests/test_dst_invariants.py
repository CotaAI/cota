"""Regression coverage for live-state isolation and trustworthy reconstruction."""

import pytest

from cota.dst import DST
from cota.events import Event, UserUtterEvent, ToolResultEvent
from tests.resource_fixtures import skill_result
from cota.snapshots import make_snapshot
from cota.store import MemoryStore


def begin(dst, run):
    dst.append_event(UserUtterEvent(run))
    dst.append_event(Event('run_started', {'input_event_id': dst.latest_user_event.event_id}, run_id=run))


def facts(dst):
    return [e.as_dict() for e in dst.events]


@pytest.mark.asyncio
async def test_late_old_run_observations_are_trace_only_and_replay_identically():
    dst = DST('s', None)
    begin(dst, 'old')
    dst.append_event(Event('tool_started', {'tool_call_id': 'c', 'tool': 'read', 'arguments': {}}, run_id='old'))
    dst.append_event(Event('run_finished', {'status': 'interrupted'}))
    begin(dst, 'new')
    dst.append_event(skill_result('current', run_id='new'))
    dst.append_event(Event('tool_started', {'tool_call_id': 'c', 'tool': 'read', 'arguments': {}}, run_id='new'))
    expected = dst.execution
    dst.append_event(skill_result('late-old-skill', run_id='old'))
    dst.append_event(ToolResultEvent('read', tool_call_id='c', run_id='old', content=[]))
    dst.append_event(Event('run_finished', {'status': 'completed'}, run_id='old'))
    assert dst.execution == expected
    assert dst.active_skill == 'current'
    assert dst.trace('old')['calls'][0]['finished']
    assert dst.trace('old')['status'] == 'completed'
    assert DST.from_events('s', facts(dst)).state_dict() == dst.state_dict()
    store = MemoryStore()
    await store.save(dst)
    assert (await store.load('s')).state_dict() == dst.state_dict()


@pytest.mark.parametrize('kind,payload', [
    ('execution_reset', {'reason': 'old reset'}),
])
def test_removed_reset_event_is_rejected_without_mutation(kind, payload):
    dst = DST('s', None)
    begin(dst, 'new')
    before = dst.as_dict()
    with pytest.raises(ValueError, match='Unknown event type'):
        dst.append_event(Event(kind, payload, run_id='old'))
    assert dst.as_dict() == before


def test_running_run_cannot_overlap_or_reuse_identity():
    dst = DST('s', None)
    begin(dst, 'r')
    before = dst.as_dict()
    with pytest.raises(ValueError, match='still running'):
        dst.append_event(Event('run_started', {}, run_id='other'))
    assert dst.as_dict() == before
    dst.append_event(Event('run_finished', {'status': 'failed'}))
    with pytest.raises(ValueError, match='run_id'):
        dst.append_event(Event('run_started', {}, run_id='r'))




def test_snapshot_is_bound_to_full_event_prefix():
    dst = DST('s', None)
    dst.update_user('alice', {'city': '北京'})
    dst.append_event(UserUtterEvent('hello'))
    snapshot = make_snapshot(dst)
    altered = facts(dst)
    altered[0]['payload']['context']['city'] = '上海'
    restored = DST.from_events('s', altered, snapshot=snapshot)
    assert restored.get_user_pref('city') == '上海'
    assert restored.state_dict() == DST.from_events('s', altered).state_dict()


def test_snapshot_with_removed_pause_field_is_discarded():
    from cota.snapshots import digest, usable_snapshot
    dst = DST('s', None)
    begin(dst, 'r')
    dst.append_event(Event('run_finished', {'status': 'completed'}))
    snapshot = make_snapshot(dst)
    snapshot['schema_version'] = DST.STATE_VERSION - 1
    snapshot['state']['paused_state'] = {'question': 'stale'}
    snapshot.pop('checksum')
    snapshot['checksum'] = digest(snapshot)
    assert not usable_snapshot(snapshot, 's', dst.events)
    restored = DST.from_events('s', facts(dst), snapshot=snapshot)
    assert restored.state_dict() == dst.state_dict()
    assert 'paused_state' not in restored.state_dict()


@pytest.mark.parametrize('name,value', [
    ('events', []), ('latest_user_event', None), ('latest_bot_event', None),
    ('created_at', 0), ('updated_at', 0), ('active_skill', 'weather'), ('execution', {}),
])
def test_derived_public_fields_cannot_be_assigned(name, value):
    dst = DST('s', None)
    dst.append_event(UserUtterEvent('hello'))
    with pytest.raises(AttributeError):
        setattr(dst, name, value)


def test_event_history_and_latest_message_do_not_expose_mutable_facts():
    dst = DST('s', None)
    dst.append_event(UserUtterEvent('hello', metadata={'nested': [1]}))
    before = dst.as_dict()
    with pytest.raises((AttributeError, TypeError)):
        dst.events.clear()
    dst.events[0].payload['text'] = 'edited'
    dst.events[0].metadata['nested'].append(2)
    dst.latest_user_event.payload['text'] = 'edited'
    assert dst.as_dict() == before
    assert dst.latest_user_text() == 'hello'


def test_closed_run_late_observations_do_not_reopen_its_execution():
    dst = DST('s', None)
    begin(dst, 'r')
    dst.append_event(Event('run_finished', {'status': 'completed'}, run_id='r'))
    expected = dst.execution
    dst.append_event(Event('tool_started', {'tool_call_id': 'late', 'tool': 'read', 'arguments': {}}, run_id='r'))
    dst.append_event(skill_result('late', run_id='r'))
    with pytest.raises(ValueError, match='already finished'):
        dst.append_event(Event('run_finished', {'status': 'completed'}, run_id='r'))
    assert dst.execution == expected
    assert dst.active_skill is None
    assert len(dst.events) == 5





@pytest.mark.parametrize('kind,payload', [
    ('execution_updated', {'changes': {}}),
    ('tool_finished', {'tool_call_id': 'c', 'tool': 'read', 'is_error': False}),
    ('pause_updated', {'state': {'question': 'old'}}),
    ('context_prepared', {}),
    ('model_request', {}),
    ('model_provider_request', {}),
    ('skill_marked', {'skill': 'weather'}),
    ('execution_replaced', {'execution': {}}),
])
def test_removed_event_types_are_rejected(kind, payload):
    with pytest.raises(ValueError, match='Unknown event type'):
        Event(kind, payload)








@pytest.mark.parametrize('version', [7, DST.STATE_VERSION])
def test_snapshot_with_removed_session_vars_is_discarded(version):
    from cota.snapshots import digest, usable_snapshot
    dst = DST('s', None)
    dst.update_user('alice', {'city': '北京'})
    dst.append_event(UserUtterEvent('hello'))
    snapshot = make_snapshot(dst)
    snapshot['schema_version'] = version
    snapshot['state']['session_vars'] = {'stale': True}
    snapshot.pop('checksum')
    snapshot['checksum'] = digest(snapshot)
    assert not usable_snapshot(snapshot, 's', dst.events)
    restored = DST.from_events('s', facts(dst), snapshot=snapshot)
    assert restored.state_dict() == dst.state_dict()
    assert 'session_vars' not in restored.as_dict()
    assert all(not hasattr(restored, name) for name in ('session_vars', 'set_var', 'get_var', 'del_var'))


@pytest.mark.parametrize('kind', ['session_var_set', 'session_var_deleted'])
def test_removed_variable_events_cannot_be_loaded(kind):
    raw = UserUtterEvent('old').as_dict()
    raw.update(type=kind, sequence=1, payload={'key': 'city', 'value': '北京'})
    with pytest.raises(ValueError, match='Unknown event type'):
        DST.from_events('old', [raw])
