"""Real Pi Skill components: composition, observational trace and durable reads."""
from unittest.mock import AsyncMock

import pytest
from cota.events.resources import skill_read_name

from cota.events import Event, UserUtterEvent
from tests.resource_fixtures import skill_result
from cota.dst import DST
from cota.runtime.pi_runtime import PiAgentRuntime
from cota.store import MemoryStore
from tests.test_pi_runtime import call


def make_skills(tmp_path, agent):
    root = tmp_path / 'skills'
    for name in ('weather', 'travel'):
        folder = root / name
        folder.mkdir(parents=True)
        (folder / 'SKILL.md').write_text(
            f'---\nname: {name}\ndescription: {name} instructions\n---\n{name.upper()}_SOP\n', encoding='utf-8')
    agent.skill_paths = [str(root)]
    agent.config_path = str(tmp_path)
    return root


@pytest.mark.asyncio
async def test_active_skill_is_only_a_serialized_trace_label(mock_agent):
    dst = DST('trace', mock_agent)
    dst.append_event(Event('run_started', {}, run_id='prior-read'))
    dst.append_event(skill_result('SearchWeb'))
    dst.append_event(Event('run_finished', {'status': 'completed'}))
    dst.append_event(UserUtterEvent('hello'))
    store = MemoryStore()
    runtime = PiAgentRuntime(mock_agent, dst, 'trace', checkpoint=store.save)
    with_label = runtime._get_tools_schema()
    empty = PiAgentRuntime(mock_agent, DST('empty', mock_agent), 'empty')
    assert empty._get_tools_schema() == with_label
    await runtime.run()
    assert dst.active_skill == 'SearchWeb'
    system = mock_agent._llm_mock.generate_chat.call_args.kwargs['messages'][0]['content']
    assert '<active_skill' not in system
    assert 'Use exec to run curl commands.' not in system
    assert (await store.load('trace', agent=mock_agent)).active_skill == 'SearchWeb'


@pytest.mark.asyncio
async def test_two_skills_can_be_read_and_recovered_without_activation(mock_agent, tmp_path):
    root = make_skills(tmp_path, mock_agent)
    dst = DST('compose', mock_agent)
    dst.append_event(UserUtterEvent('weather and travel'))
    store = MemoryStore()
    mock_agent._llm_mock.generate_chat.side_effect = [
        {'tool_calls': [call('read', {'path': str(root / 'weather/SKILL.md')}, 'w')]},
        {'tool_calls': [call('read', {'path': str(root / 'travel/SKILL.md')}, 't')]},
        {'content': 'which city?'},
        {'content': 'combined answer'},
    ]
    await PiAgentRuntime(mock_agent, dst, 'compose', checkpoint=store.save).run()
    assert dst.execution['status'] == 'completed'
    assert dst.active_skill == 'travel'
    reads = [e for e in dst.events if skill_read_name(e)]
    assert [e.skill for e in reads] == ['weather', 'travel']
    assert not any(e.type in ('skill_activate', 'skill_paused', 'skill_complete') for e in dst.events)
    restored = (await store.load('compose', agent=mock_agent))
    assert not any(e.type == 'skills_loaded' for e in restored.events)
    assert restored.run_metadata[restored.execution['run_id']] == {'available_skills': ['travel', 'weather'], 'deploy': 'personal', 'environment': {'type': 'none'}}
    restored.append_event(UserUtterEvent('Beijing'))
    await PiAgentRuntime(mock_agent, restored, 'compose', checkpoint=store.save).run()
    messages = mock_agent._llm_mock.generate_chat.call_args.kwargs['messages']
    results = [m.get('content', '') for m in messages if m['role'] == 'tool']
    assert any('WEATHER_SOP' in result for result in results)
    assert any('TRAVEL_SOP' in result for result in results)
    assert restored.active_skill == 'travel'
    assert 'WEATHER_SOP' not in messages[0]['content']
    assert 'TRAVEL_SOP' not in messages[0]['content']


@pytest.mark.asyncio
async def test_read_trace_must_be_saved_before_next_model_call(mock_agent, tmp_path):
    root = make_skills(tmp_path, mock_agent)
    dst = DST('durable', mock_agent)
    dst.append_event(UserUtterEvent('read'))
    mock_agent._llm_mock.generate_chat.side_effect = [
        {'tool_calls': [call('read', {'path': str(root / 'weather/SKILL.md')})]},
        {'content': 'must not run'},
    ]
    async def fail_on_read(tracker):
        if any(skill_read_name(e) for e in tracker.events):
            raise OSError('read trace unavailable')
    with pytest.raises(OSError, match='read trace unavailable'):
        await PiAgentRuntime(mock_agent, dst, 'durable', checkpoint=fail_on_read).run()
    assert mock_agent._llm_mock.generate_chat.await_count == 1


@pytest.mark.asyncio
async def test_business_tool_cannot_shadow_pi_resource_reader(mock_agent, tmp_path):
    from cota.executor.tools.base import FunctionTool, create_tool_schema
    make_skills(tmp_path, mock_agent)
    handler = AsyncMock(return_value={'success': True})
    with pytest.raises(ValueError, match='read.*reserved'):
        mock_agent.get_tool_registry().register(FunctionTool('read', 'business read', create_tool_schema({}), handler))
    handler.assert_not_awaited()
    mock_agent._llm_mock.generate_chat.assert_not_awaited()
