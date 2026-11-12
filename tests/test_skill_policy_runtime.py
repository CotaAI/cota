"""Pi request preparation consumes Skill policies, not Action predictions."""

import pytest
from cota.agent import Agent
from cota.events import Event, UserUtterEvent
from tests.resource_fixtures import skill_result
from cota.dst import DST
from cota.runtime.pi_runtime import PiAgentRuntime
from cota.store import MemoryStore
from tests.test_pi_runtime import call


@pytest.mark.parametrize('config', [
    {'actions': {}}, {'skills': {}}, {'policies': [{'type': 'match'}]},
    {'dialogue': {'promt': 'typo'}}, {'tools': {'allow': 'web_fetch'}},
    {'policy': {'type': 'trigger'}}, {'dialogue': {'prompt': '{{action_descriptions}}'}},
    {'dialogue': {'max_iterations': 0}}, {'unknown': True},
])
def test_obsolete_or_invalid_bot_contract_fails_before_loading_resources(tmp_path, config):
    import yaml
    (tmp_path / 'agent.yml').write_text(yaml.safe_dump(config))
    (tmp_path / 'endpoints.yml').write_text('{}')
    with pytest.raises(ValueError):
        Agent.load_from_path(str(tmp_path))


@pytest.mark.asyncio
async def test_ordered_thoughts_reach_before_read_after_result_and_resume(mock_agent):
    from cota.policy import PolicyCatalog, AllPolicy
    from cota.executor.tools.base import FunctionTool, create_tool_schema
    from unittest.mock import AsyncMock
    value = {'name': '搜索示例', 'steps': [
        {'user': 'EXAMPLE_ONLY_USER'},
        {'bot': [{'thought': 'SELECT_THOUGHT: 使用搜索能力'}, {'skills': ['SearchWeb']},
                 {'result': 'EXAMPLE_ONLY_RESULT: 查询失败，无有效搜索结果'},
                 {'thought': 'REPLY_THOUGHT: 查询失败时明确说明，不编造'}, {'reply': 'EXAMPLE_ONLY_REPLY'}]},
        {'user': 'FUTURE_EXAMPLE_USER'},
    ]}
    mock_agent.policy = AllPolicy(PolicyCatalog([value]))
    mock_agent._tool_registry.register(FunctionTool('lookup', 'lookup', create_tool_schema({}),
        AsyncMock(return_value={'content': [{'type': 'text', 'text': 'lookup timeout'}], 'details': {}, 'isError': True})))
    dst = DST('s', mock_agent)
    dst.append_event(UserUtterEvent('original user request'))
    mock_agent._llm_mock.generate_chat.side_effect = [
        {'tool_calls': [call('read', {'path': mock_agent.skill_file('SearchWeb')}, 'read-1')]},
        {'tool_calls': [call('lookup', {}, 'lookup-1')]},
        {'content': 'Retry?'},
        {'content': 'done'},
    ]
    store = MemoryStore()
    await PiAgentRuntime(mock_agent, dst, 's', checkpoint=store.save).run()
    requests = mock_agent._llm_mock.generate_chat.call_args_list
    for request in requests:
        system = request.kwargs['messages'][0]['content']
        assert system.index('SELECT_THOUGHT') < system.index('Skills: SearchWeb') < system.index('EXAMPLE_ONLY_RESULT') < system.index('REPLY_THOUGHT')
        assert 'Result（示例结果条件）: EXAMPLE_ONLY_RESULT' in system
        assert 'EXAMPLE_ONLY_RESULT' not in str(request.kwargs['messages'][1:])
        assert not any(m.get('content') in ('EXAMPLE_ONLY_USER', 'EXAMPLE_ONLY_REPLY', 'FUTURE_EXAMPLE_USER')
                       for m in request.kwargs['messages'][1:])
    assert any('lookup timeout' in str(m.get('content')) for m in requests[2].kwargs['messages'] if m['role'] == 'tool')
    restored = (await store.load('s', agent=mock_agent))
    restored.append_event(UserUtterEvent('No'))
    await PiAgentRuntime(mock_agent, restored, 's', checkpoint=store.save).run()
    assert 'REPLY_THOUGHT' in mock_agent._llm_mock.generate_chat.call_args.kwargs['messages'][0]['content']
    contexts = [e.payload['llm']['policy'] for e in restored.events if e.payload.get('llm')]
    assert len(contexts) == 4
    assert contexts[0]['policies'][0]['name'] == value['name']
    assert contexts[0]['read_skills'] == []
    assert contexts[1]['read_skills'] == ['SearchWeb']
    assert [e.text for e in restored.events if e.type == 'user_utter'] == ['original user request', 'No']
    assert 'EXAMPLE_ONLY_RESULT' not in str(restored.context_messages[1:])
    # Policy provenance now lives on the carrier; business content stays clean.
    assert all('EXAMPLE_ONLY_RESULT' not in str({k: v for k, v in e.payload.items() if k != 'llm'})
               for e in restored.events if e.type in ('user_utter', 'bot_utter', 'tool_call', 'tool_result'))


@pytest.mark.asyncio
async def test_historical_read_without_retained_content_does_not_guide_policy(mock_agent):
    dst = DST('s', mock_agent)
    dst.append_event(Event('run_started', {}, run_id='prior-read'))
    dst.append_event(skill_result('SearchWeb'))
    dst.append_event(Event('context_compaction', {
        'summary': 'Historical search instructions were read.',
        'replaced_message_ids': [m['cotaEventId'] for m in dst.context_messages],
    }))
    dst.append_event(Event('run_finished', {'status': 'completed'}))
    dst.append_event(UserUtterEvent('hello'))
    await PiAgentRuntime(mock_agent, dst, 's').run()
    assert [e for e in dst.events if e.payload.get('llm')][-1].payload['llm']['policy']['read_skills'] == []


def test_removed_action_helpers_and_renamed_tool_servers():
    from pathlib import Path
    import cota
    root = Path(cota.__file__).parent
    assert not (root / 'dpl').exists()
    assert not (root / 'executor' / 'skills').exists()
    from cota.executor.tool_servers import BaseToolServer
    from cota.executor.tools import ToolRegistry
    assert BaseToolServer
    assert ToolRegistry().list_tools() == []


@pytest.mark.asyncio
async def test_knowledge_uses_named_model_without_action_routing(mock_agent):
    from cota.knowledge.llm_knowledge import LLMKnowledge
    provider = LLMKnowledge({'llm': 'default'})
    assert await provider.retrieve('question', {'agent': mock_agent}) == 'hello'


@pytest.mark.asyncio
async def test_execution_policy_requires_exact_retained_read_result(mock_agent):
    from cota.policy import PolicyCatalog, AllPolicy
    mock_agent.policy = AllPolicy(PolicyCatalog([{'name': 'execute', 'steps': [{'bot': [{'thought': 'check the source'}, {'skills': ['SearchWeb']}]}]}]))
    dst = DST('s', mock_agent)
    dst.append_event(UserUtterEvent('search'))
    mock_agent._llm_mock.generate_chat.side_effect = [
        {'tool_calls': [call('read', {'path': mock_agent.skill_file('SearchWeb')}, 'shared-id')]},
        {'content': 'done'},
    ]
    runtime = PiAgentRuntime(mock_agent, dst, 's')
    await runtime.run()
    retained = [m for m in dst.context_messages if m['role'] == 'toolResult']
    result_event = next(e for e in dst.events if e.type == 'tool_result' and e.tool == 'read')
    assert retained[0]['cotaResultEventId'] == result_event.event_id
    assert (await runtime._policy_guidance(retained))[1] == ['SearchWeb']
    # Tool call IDs may repeat across runs; a different tool must not inherit the read.
    unrelated = [{'role': 'toolResult', 'toolCallId': 'shared-id', 'toolName': 'web_fetch',
                  'content': [{'type': 'text', 'text': 'not a read'}], 'isError': False}]
    assert (await runtime._policy_guidance(unrelated))[1] == []
    assert (await runtime._policy_guidance([]))[1] == []


@pytest.mark.asyncio
async def test_compaction_recomputes_priority_without_claiming_business_completion(mock_agent):
    from cota.policy import PolicyCatalog, AllPolicy
    values = [
        {'name': 'general', 'steps': [{'bot': [{'thought': 'GENERAL_RULE'}]}]},
        {'name': 'search', 'steps': [{'bot': [{'skills': ['SearchWeb']}, {'thought': 'READ_PRIORITY_RULE ' + 'x' * 2000}]}]},
    ]
    mock_agent.policy = AllPolicy(PolicyCatalog(values, max_policies=1))
    dst = DST('s', mock_agent)
    dst.append_event(UserUtterEvent('search'))
    mock_agent._llm_mock.generate_chat.side_effect = [
        {'tool_calls': [call('read', {'path': mock_agent.skill_file('SearchWeb')})]}, {'content': 'done'},
    ]
    runtime = PiAgentRuntime(mock_agent, dst, 's')
    await runtime.run()
    assert 'READ_PRIORITY_RULE' in mock_agent._llm_mock.generate_chat.call_args.kwargs['messages'][0]['content']
    runtime._system_prompt = 'base'
    mock_agent._llm_mock.generate_chat.side_effect = [{'content': 'summary'}]
    dst.append_event(UserUtterEvent('x' * 3000))
    dst.append_event(UserUtterEvent('new request'))
    dst.append_event(Event('run_started', {}, run_id='next'))
    messages = dst.context_messages
    # The worker supplies its native schemas on every prepare, including after
    # compaction. Reuse the real Pi schema observed in the preceding request.
    native_tools = [tool for tool in mock_agent._llm_mock.generate_chat.call_args.kwargs['tools']
                    if tool['function']['name'] == 'read']
    extensions = [tool for tool in mock_agent._llm_mock.generate_chat.call_args.kwargs['tools']
                  if tool['function']['name'] == 'web_fetch']
    # Pi chooses the boundary; Cota validates and commits the prefix, then
    # recomputes Policy against the restored projection.
    ids = [m['cotaEventId'] for m in messages[:-1]]
    restored = await runtime._handle_request('compact', {
        'summary': 'summary', 'replaced_message_ids': ids, 'first_kept_id': messages[-1]['cotaEventId'],
    })
    prepared = await runtime._prepare({'messages': restored['messages'], 'nativeTools': native_tools, 'extensionTools': extensions})
    assert any(e.type == 'context_compaction' for e in dst.events)
    assert 'READ_PRIORITY_RULE' not in prepared['messages'][0]['content']
    assert 'GENERAL_RULE' in prepared['messages'][0]['content']
    assert runtime._trace.policy['read_skills'] == []
