"""Resource identity belongs to the actual tool result, not a second event."""
import pytest

from cota.dst import DST
from cota.events import Event, UserUtterEvent
from cota.runtime.pi_runtime import PiAgentRuntime
from cota.store import MemoryStore, SQLStore
from tests.test_pi_runtime import call


@pytest.mark.asyncio
@pytest.mark.parametrize('backend', ['memory', 'sqlite'])
async def test_reads_are_single_results_with_compact_resources(mock_agent, tmp_path, backend):
    from pathlib import Path
    skill = Path(mock_agent.skill_file('SearchWeb'))
    reference = skill.parent / 'reference.txt'
    reference.write_text('one\ntwo\nthree')
    mock_agent._llm_mock.generate_chat.side_effect = [
        {'tool_calls': [call('read', {'path': str(skill)}, 'skill')]},
        {'tool_calls': [call('read', {'path': str(reference), 'offset': 2, 'limit': 1}, 'reference')]},
        {'tool_calls': [call('read', {'path': str(skill.parent / 'missing.txt')}, 'failed')]},
        {'content': 'done'},
    ]
    store = MemoryStore() if backend == 'memory' else SQLStore(db=str(tmp_path / 'reads.db'))
    dst = DST('resources', mock_agent)
    dst.append_event(UserUtterEvent('read'))
    runtime = PiAgentRuntime(mock_agent, dst, dst.session_id, checkpoint=store.save)
    await runtime.run()
    assert not any(e.type in ('skill_read', 'resource_read') for e in dst.events)
    results = [e for e in dst.events if e.type == 'tool_result']
    assert len(results) == 3
    resource = results[0].payload['resource']
    assert set(resource) == {'kind', 'skill', 'path', 'hash'}
    assert resource['kind'] == 'skill' and resource['skill'] == 'SearchWeb'
    assert resource['hash'].startswith('sha256:')
    assert results[1].payload['resource']['kind'] == 'reference'
    assert results[1].payload['resource']['range'] == {'offset': 2, 'limit': 1}
    assert results[2].payload['status'] == 'error'
    assert 'resource' not in results[2].payload
    assert dst.active_skill == 'SearchWeb'
    assert (await runtime._policy_guidance(dst.context_messages))[1] == ['SearchWeb']
    assert (await runtime._policy_guidance([]))[1] == []
    other_results = [m for m in dst.context_messages if m.get('cotaResultEventId') != results[0].event_id]
    assert (await runtime._policy_guidance(other_results))[1] == []
    headers = await store.event_headers(dst.session_id)
    header = next(h for h in headers if h['event_id'] == results[0].event_id)
    assert header['summary']['resource_skill'] == 'SearchWeb'
    assert header['summary']['resource_kind'] == 'skill'
    assert 'hash' not in header['summary'] and 'payload' not in header
    trace = dst.trace(dst.execution['run_id'])
    assert [e['event_id'] for e in trace['skills']] == [results[0].event_id]
    assert len(trace['calls']) == 3
    assert [e['event_id'] for e in trace['resources']] == [e.event_id for e in results[1:]]
    assert (await store.load(dst.session_id)).state_dict() == dst.state_dict()
    assert DST.from_events(dst.session_id, dst.events).state_dict() == dst.state_dict()
    if backend == 'sqlite':
        store.engine.dispose()


@pytest.mark.parametrize('kind', ['skill_read', 'resource_read'])
def test_old_read_events_are_removed(kind):
    with pytest.raises(ValueError, match='Unknown event type'):
        Event(kind, {'skill': 'weather'})


@pytest.mark.parametrize('changes', [
    {'kind': 'other'}, {'skill': ''}, {'path': None}, {'hash': 'invalid'},
    {'range': {}}, {'range': {'offset': '2'}}, {'range': {'truncated': False}},
    {'range': {'offset': float('inf')}}, {'skill_path': '/duplicate'}, {'content': 'duplicate text'},
])
def test_resource_contract_keeps_only_core_typed_fields(changes):
    from cota.events import ToolResultEvent
    resource = {'kind': 'skill', 'skill': 'weather', 'path': '/skills/weather/SKILL.md', **changes}
    with pytest.raises(ValueError):
        ToolResultEvent('read', result='SOP', resource=resource)


def test_tool_output_alone_cannot_claim_skill_read():
    from cota.events import ToolResultEvent
    from cota.events.resources import skill_read_name
    event = ToolResultEvent('exec', result={'resource': {'kind': 'skill', 'skill': 'weather'}})
    assert 'resource' not in event.payload
    assert skill_read_name(event) is None
