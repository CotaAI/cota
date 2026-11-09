"""Stable facts, sequence and conservative per-run trace projections."""
from copy import deepcopy

import pytest

from cota.dst import DST
from cota.events import Event, UserUtterEvent, BotUtterEvent, ToolResultEvent
from tests.resource_fixtures import skill_result


def test_envelope_native_values_and_detachment():
    for value in (None, False, 0, '', [], {}):
        event = ToolResultEvent('exec', result=value, tool_call_id='call')
        data = event.as_dict()
        assert data['type'] == 'tool_result'
        assert set(data) == {'schema_version', 'event_id', 'sequence', 'timestamp', 'run_id', 'type', 'source', 'payload'}
        assert data['payload']['result'] == value
        assert Event.from_dict(data).as_dict() == data
    event = ToolResultEvent('exec', result={'content': []}, tool_call_id='call')
    saved = event.as_dict()
    saved['payload']['result']['content'].append('mutated')
    assert event.payload['result']['content'] == []


@pytest.mark.parametrize('bad', [
    {'type': 'user_utter', 'text': 'legacy'},
    {'schema_version': 2, 'type': 'user_utter', 'payload': {'text': 'future'}},
])
def test_reject_unsupported_event_envelopes(bad):
    with pytest.raises(ValueError):
        Event.from_dict(bad)


def test_sequence_identity_run_and_snapshot_validation(dst, mock_agent):
    dst.append_event(Event('run_started', {}, run_id='old'))
    user = UserUtterEvent('next')
    dst.append_event(user)
    assert user.run_id is None
    dst.append_event(Event('run_finished', {'status': 'completed'}))
    dst.append_event(Event('run_started', {}, run_id='new'))
    read = skill_result('weather')
    dst.append_event(read)
    assert read.run_id == 'new'
    assert dst.active_skill == 'weather'
    assert [e.sequence for e in dst.events] == [1, 2, 3, 4, 5]
    with pytest.raises(ValueError, match='duplicate'):
        dst.append_event(Event.from_dict(read.as_dict()))
    saved = dst.as_dict()
    assert DST.from_events(saved['session_id'], saved['events'], agent=mock_agent, revision=saved['revision']).as_dict() == saved
    for change in ('version', 'sequence', 'identity'):
        broken = deepcopy(saved)
        if change == 'version': broken['events'][0]['schema_version'] = 2
        if change == 'sequence': broken['events'][1]['sequence'] = 1
        if change == 'identity': broken['events'][1]['event_id'] = broken['events'][0]['event_id']
        with pytest.raises(ValueError):
            DST.from_events(broken['session_id'], broken['events'], agent=mock_agent, revision=broken['revision'])


def test_trace_multiple_reads_interrupted_call_and_native_result(dst):
    user = UserUtterEvent('compare')
    dst.append_event(user)
    dst.append_event(Event('run_started', {'input_event_id': user.event_id, 'previous_run_id': None, 'engine': 'pi', 'engine_version': '1'}, run_id='r'))
    dst.append_event(skill_result('a', run_id='r'))
    dst.append_event(skill_result('b', run_id='r'))
    dst.append_event(Event('tool_started', {'tool_call_id': 'complete', 'tool': 'read', 'arguments': {}}, run_id='r'))
    result = Event('tool_result', {'tool_call_id': 'complete', 'tool': 'read', 'result': {}, 'content': [], 'status': 'success'}, run_id='r')
    dst.append_event(result)
    dst.append_event(Event('tool_started', {'tool_call_id': 'unfinished', 'tool': 'pay', 'arguments': {}}, run_id='r'))
    dst.append_event(Event('run_finished', {'status': 'interrupted', 'error_type': None}, run_id='r'))
    trace = dst.trace('r')
    assert trace['status'] == 'interrupted'
    assert trace['input_event_id'] == user.event_id
    assert [e['payload']['resource']['skill'] for e in trace['skills']] == ['a', 'b']
    complete, unfinished = trace['calls'][-2:]
    assert complete['result'] == {} and complete['content'] == []
    assert complete['finished'] is True and complete['status'] == 'success'
    assert unfinished['status'] == 'pending' and unfinished['finished'] is False
    assert all('skill' not in call for call in trace['calls'])


def test_result_is_terminal_without_another_end_event(dst):
    dst.append_event(ToolResultEvent('pay', result=False, tool_call_id='c', run_id='r'))
    call = dst.trace('r')['calls'][0]
    assert call['finished'] is True
    assert call['status'] == 'success'


def test_event_payload_and_envelope_validation():
    valid = UserUtterEvent('hi').as_dict()
    for key, value in [('payload', []), ('type', 'unknown'), ('sequence', -1), ('event_id', ''), ('timestamp', 'now'), ('run_id', 4)]:
        bad = dict(valid, **{key: value})
        with pytest.raises(ValueError): Event.from_dict(bad)
    with pytest.raises(ValueError): Event('tool_started', {'tool_call_id': 'c'})
    with pytest.raises(ValueError): Event('user_utter', {'text': []})


def test_trace_retains_resource_and_diagnostics_without_skill_ownership(dst):
    resource = ToolResultEvent('read', result='reference', resource={'kind': 'reference', 'skill': 'a', 'path': '/skills/a/ref.txt'}, run_id='r')
    context = ToolResultEvent('read', result=[], run_id='r')
    dst.append_event(resource)
    dst.append_event(context)
    trace = dst.trace('r')
    assert trace['resources'] == [resource.as_dict(), context.as_dict()]
    assert trace['events'] == [resource.as_dict(), context.as_dict()]
    assert trace['skills'] == []


@pytest.mark.asyncio
async def test_public_server_does_not_expose_execution_routes(mock_agent):
    from cota.server import create_app
    from cota.store import MemoryStore
    mock_agent.store = MemoryStore()
    app = create_app(agent=mock_agent)
    assert not any(fragment in route.path for route in app.router.routes
                   for fragment in ('trace', 'tracker', 'workspace', 'debug_log'))


@pytest.mark.asyncio
async def test_authorized_chat_projection_excludes_execution_state(mock_agent, tmp_path):
    from cota.server import create_app
    from cota.store import MemoryStore
    mock_agent.store = MemoryStore()
    app = create_app(agent=mock_agent)
    app.ctx.web_service.access.key_path = tmp_path / "web.key"
    service = app.ctx.web_service
    guest = await service.access.create_guest()
    session = await service.access.create_conversation(guest['user_id'])
    dst = DST(session, mock_agent)
    dst.append_event(UserUtterEvent('weather'))
    dst.append_event(Event('run_started', {'input_event_id': dst.latest_user_event.event_id}, run_id='r'))
    dst.append_event(BotUtterEvent('Which city?'))
    dst.append_event(Event('run_finished', {'status': 'completed'}))
    await mock_agent.store.save(dst)
    data = await service.history(guest['user_id'], session)
    assert [message['text'] for message in data['messages']] == ['weather', 'Which city?']
    assert set(data) == {'messages', 'cursor', 'through', 'has_more'}
    assert 'execution' not in data and 'events' not in data
    with pytest.raises(PermissionError):
        await service.history('different-user', session)


def test_replay_rejects_mutated_sequence_and_duplicate_identity(dst):
    dst.append_event(UserUtterEvent('one'))
    dst.append_event(UserUtterEvent('two'))
    altered = [e.as_dict() for e in dst.events]
    altered[1]['sequence'] = 4
    with pytest.raises(ValueError, match='sequence'):
        DST.from_events(dst.session_id, altered)
    altered[1]['sequence'] = 2
    altered[1]['event_id'] = altered[0]['event_id']
    with pytest.raises(ValueError, match='duplicate'):
        DST.from_events(dst.session_id, altered)


@pytest.mark.parametrize('value', [{1: 'numeric key'}, {'x': (1, 2)}, {'x': float('nan')}])
def test_non_json_native_payloads_are_rejected(value):
    with pytest.raises(ValueError, match='JSON'):
        ToolResultEvent('read', result=value)


def test_bot_is_trace_output_without_delivery_projection(dst):
    bot = BotUtterEvent('hello', run_id='r')
    dst.append_event(bot)
    before = bot.as_dict()
    assert dst.trace('r')['outputs'] == [before]
    assert 'deliveries' not in dst.trace('r')
    with pytest.raises(ValueError, match='Unknown event type'):
        Event('message_delivery', {'event_id': bot.event_id, 'status': 'delivered'}, run_id='r')


def test_duplicate_tool_callbacks_rejected(dst):
    for kind in ('tool_started', 'tool_result'):
        payload = {'tool': 'exec', 'tool_call_id': 'c', 'result': None, 'content': [], 'status': 'success'}
        if kind == 'tool_started':
            payload = {'tool': 'exec', 'tool_call_id': 'c', 'arguments': {}}
        dst.append_event(Event(kind, payload, run_id='r'))
        with pytest.raises(ValueError, match='duplicate'):
            dst.append_event(Event(kind, payload, run_id='r'))


def test_stable_public_result_name_and_closed_run_statuses():
    import cota.events as events
    assert hasattr(events, 'ToolResultEvent')
    assert not hasattr(events, 'ToolCallEvent')
    for status in ('completed', 'failed', 'interrupted', 'limited'):
        assert Event('run_finished', {'status': status}).payload['status'] == status
    with pytest.raises(ValueError, match='status'):
        Event('run_finished', {'status': 'made_up'})


def test_reading_convenience_metadata_and_trace_does_not_mutate_facts(dst):
    event = ToolResultEvent('read', result=[], run_id='r')
    dst.append_event(event)
    before = event.as_dict()
    assert event.metadata == {}
    trace = dst.trace('r')
    trace['events'][0]['payload']['result'].append('mutate')
    assert event.as_dict() == before


def test_malformed_discriminators_raise_validation_errors():
    data = UserUtterEvent('x').as_dict()
    with pytest.raises(ValueError):
        Event.from_dict(dict(data, type=[]))
    with pytest.raises(ValueError):
        Event('run_finished', {'status': []})


@pytest.mark.parametrize('kind,payload', [
    ('tool_started', {'tool_call_id': 'c', 'tool': 'exec'}),
    ('tool_started', {'tool_call_id': 'c', 'tool': 'exec', 'arguments': None}),
    ('tool_result', {'tool_call_id': 'c', 'tool': 'exec'}),
    ('tool_result', {'tool_call_id': 'c', 'tool': 'exec', 'arguments': {}, 'raw_result': None, 'is_error': False}),
    ('tool_result', {'tool_call_id': 'c', 'tool': 'exec', 'arguments': {}, 'model_result': {'content': []}, 'is_error': False}),
    ('tool_result', {'tool_call_id': 'c', 'tool': 'exec', 'arguments': {}, 'raw_result': None, 'model_result': {'content': []}}),
])
def test_tool_phase_required_fields(kind, payload):
    with pytest.raises(ValueError):
        Event(kind, payload)


@pytest.mark.parametrize('key,value', [('status', 'false'), ('status', 0), ('duration_ms', -1), ('duration_ms', True), ('duration_ms', '10')])
def test_tool_phase_optional_values_are_typed(key, value):
    with pytest.raises(ValueError):
        ToolResultEvent('exec', tool_call_id='c', **{key: value})


def test_call_phases_cannot_change_tool_identity(dst):
    from cota.trace import build_trace
    started = Event('tool_started', {'tool_call_id': 'c', 'tool': 'a', 'arguments': {}}, run_id='r')
    dst.append_event(started)
    changed = Event('tool_result', {'tool_call_id': 'c', 'tool': 'b', 'result': None, 'content': [], 'status': 'success'}, run_id='r')
    with pytest.raises(ValueError, match='tool identity'):
        dst.append_event(changed)
    with pytest.raises(ValueError, match='tool identity'):
        build_trace([started, changed], 'r')


def test_result_rejects_redundant_outcomes_and_marks_blocked(dst):
    result = ToolResultEvent('exec', result='denied', status='blocked', tool_call_id='c', run_id='r')
    for key, value in [('is_error', True), ('executed', False), ('arguments', {}), ('model_result', {})]:
        with pytest.raises(ValueError, match='Unexpected tool_result'):
            Event('tool_result', {**result.payload, key: value}, run_id='r')
    dst.append_event(result)
    assert dst.trace('r')['calls'][0]['status'] == 'blocked'


@pytest.mark.parametrize('outcome', ['failed', 'blocked', 'reference', 'unclassified'])
def test_failed_or_auxiliary_reads_are_not_skill_evidence(dst, outcome):
    resource = {'kind': 'reference' if outcome == 'reference' else 'skill',
                'skill': 's', 'path': '/skills/s/SKILL.md'}
    result = ToolResultEvent('read', result='data', tool_call_id='c', run_id='r', resource=None if outcome == 'unclassified' else resource, status='blocked' if outcome == 'blocked' else 'error' if outcome == 'failed' else 'success')
    dst.append_event(result)
    dst.append_event(Event('tool_started', {'tool_call_id': 'use', 'tool': 'exec', 'arguments': {}}, run_id='r'))
    assert dst.trace('r')['skills'] == []
    assert dst.trace('r')['resources'] == [result.as_dict()]


def test_run_start_references_are_validated(dst):
    user = UserUtterEvent('hello')
    bot = BotUtterEvent('old', run_id='old')
    dst.append_event(user)
    dst.append_event(bot)
    for payload in ({'input_event_id': 'missing'}, {'input_event_id': bot.event_id}, {'previous_run_id': 'missing'}, {'previous_run_id': 'new'}):
        with pytest.raises(ValueError):
            dst.append_event(Event('run_started', payload, run_id='new'))
    dst.append_event(Event('run_started', {'input_event_id': user.event_id, 'previous_run_id': 'old'}, run_id='new'))


def test_resource_cannot_claim_another_tool():
    with pytest.raises(ValueError, match='read tool'):
        ToolResultEvent('exec', result='data', resource={'kind': 'skill', 'skill': 's', 'path': '/skills/s/SKILL.md'})


@pytest.mark.parametrize('kind', ['tool_progress', 'annotation', 'skill_annotation', 'policy_annotation', 'model_error'])
def test_removed_event_types_rejected_on_replay(kind):
    data = UserUtterEvent('old data').as_dict()
    data['type'] = kind
    with pytest.raises(ValueError, match='Unknown event type'):
        DST.from_events('old', [data])


def test_cross_run_skill_history_has_no_unused_annotation_or_progress_fields(dst):
    read = skill_result('a', run_id='old')
    dst.append_event(read)
    dst.append_event(Event('tool_started', {'tool_call_id': 'c', 'tool': 'exec', 'arguments': {}}, run_id='new'))
    trace = dst.trace('new')
    assert trace['skills'] == []
    assert trace['skill_history'] == [read.as_dict()]
    assert 'annotations' not in trace and 'skill_annotations' not in trace
    assert 'policy_annotations' not in trace
    assert all('progress' not in call for call in trace['calls'])
