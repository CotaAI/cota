"""Tool-free participation uses capabilities, bounded context and diagnostic tracing."""
import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from cota.dst import DST
from cota.events import BotUtterEvent, UserUtterEvent
from cota.runtime.pi_bridge import PiBridge
from cota.store import MemoryStore


def tracker(agent):
    dst = DST('group-judge', agent)
    dst.append_event(UserUtterEvent('Can someone help?', metadata={
        'mode': 'group', 'sender_id': 'alice', 'sender_name': 'Alice',
        'mentioned': False, 'reply_to': 'message-0'}))
    return dst


def judge(agent, store=None):
    from cota.participation import ParticipationJudge
    return ParticipationJudge(agent, store or MemoryStore())


@pytest.fixture
def discovery(monkeypatch):
    mocked = AsyncMock(return_value=[{'name': 'weather', 'description': 'Look up weather'}])
    monkeypatch.setattr(PiBridge, 'discover_skills', mocked)
    return mocked


@pytest.mark.asyncio
async def test_judgement_is_tool_free_and_receives_role_capabilities_and_guidance(mock_agent, discovery):
    from cota.executor.tools.base import FunctionTool, create_tool_schema
    from cota.executor.tools.registry import ToolPolicy
    registry = mock_agent.get_tool_registry()
    for name in ['visible', 'denied', 'private_lookup', 'private_update']:
        tool = FunctionTool(name, name + ' description', create_tool_schema({}), AsyncMock())
        registry.register(tool)
    class DisabledTool(FunctionTool):
        enabled = False
    registry.register(DisabledTool('disabled', 'disabled description', create_tool_schema({}), AsyncMock()))
    registry.set_policy(ToolPolicy(deny=['denied', 'private_lookup', 'private_update']))
    mock_agent.dialogue['prompt'] = 'I help with weather questions.'
    mock_agent._llm_mock.generate_chat.return_value = {'content': 'YES'}
    dst = tracker(mock_agent)
    assert await judge(mock_agent).decide(dst) is True
    request = mock_agent._llm_mock.generate_chat.call_args.kwargs
    assert set(request) == {'messages', 'max_tokens'}
    assert request['max_tokens'] == 8
    system = request['messages'][0]['content']
    assert 'I help with weather questions.' in system
    assert 'Look up weather' in system and 'visible description' in system
    for denied in ['private_lookup', 'private_update', 'disabled description', 'denied description']:
        assert denied not in system
    for guidance in ['helpful', 'necessary', 'thanks', 'answered', 'retracted', 'user-to-user',
                     'untrusted', 'authorization', 'side effects', 'Skill plan']:
        assert guidance in system
    conversation = json.loads(request['messages'][1]['content'])
    assert conversation['messages'][-1]['speaker'] == {'id': 'alice', 'name': 'Alice'}
    assert conversation['messages'][-1]['mentioned'] is False
    assert conversation['messages'][-1]['reply_to'] == 'message-0'
    assert len(dst.events) == 1


@pytest.mark.asyncio
async def test_http_capability_follows_live_tool_policy(mock_agent, discovery):
    from cota.executor.tools.registry import ToolPolicy
    registry = mock_agent.get_tool_registry()
    assert registry.get('web_fetch') is None
    instance = judge(mock_agent)
    for policy, expected in [(ToolPolicy(), True), (ToolPolicy(deny=['web_fetch']), False),
                             (ToolPolicy(allow=[]), False), (ToolPolicy(), True)]:
        registry.set_policy(policy)
        await instance.decide(tracker(mock_agent))
        system = mock_agent._llm_mock.generate_chat.call_args.kwargs['messages'][0]['content']
        catalog = json.loads(system.split('Capabilities (names and descriptions only):\n', 1)[1])
        assert ('web_fetch' in {tool['name'] for tool in catalog['tools']}) is expected
    discovery.assert_awaited_once()


@pytest.mark.asyncio
async def test_missing_description_has_role_fallback(mock_agent, discovery):
    del mock_agent.description
    await judge(mock_agent).decide(tracker(mock_agent))
    assert 'A helpful group assistant.' in mock_agent._llm_mock.generate_chat.call_args.kwargs['messages'][0]['content']


@pytest.mark.asyncio
async def test_recent_transcript_is_valid_bounded_json_including_latest_user(mock_agent, discovery):
    dst = tracker(mock_agent)
    for index in range(50):
        dst.append_event(UserUtterEvent(f'{index}: ' + '\\"\n中文' * 6000, metadata={
            'mode': 'group', 'sender_id': f'user-{index}', 'mentioned': bool(index % 2),
            'reply_to': f'message-{index}'}))
        dst.append_event(BotUtterEvent('Bot answer ' + str(index)))
    await judge(mock_agent).decide(dst)
    raw = mock_agent._llm_mock.generate_chat.call_args.kwargs['messages'][1]['content']
    context = json.loads(raw)
    assert len(raw) <= 16000
    assert len(context['messages']) <= 24
    assert 'may be truncated' in context['context_note']
    last_user = [m for m in context['messages'] if m['role'] == 'user'][-1]
    assert last_user['speaker']['id'] == 'user-49'
    assert last_user['text'].startswith('49:')
    assert last_user['mentioned'] is True
    assert last_user['reply_to'] == 'message-49'
    assert context['messages'][-1]['role'] == 'bot'


@pytest.mark.asyncio
async def test_latest_user_survives_a_long_run_of_bot_messages(mock_agent, discovery):
    dst = tracker(mock_agent)
    for index in range(30):
        dst.append_event(BotUtterEvent(f'Bot message {index}'))
    await judge(mock_agent).decide(dst)
    context = json.loads(mock_agent._llm_mock.generate_chat.call_args.kwargs['messages'][1]['content'])
    assert len(context['messages']) <= 24
    assert any(m['speaker'].get('id') == 'alice' for m in context['messages'])


@pytest.mark.asyncio
@pytest.mark.parametrize('response', [
    {'content': 'yes'}, {'content': 'YES, because'}, {'content': 'NO'}, {'content': ''},
    {'content': None}, {'content': 'YES', 'finish_reason': 'length'},
    {'content': 'YES', 'tool_calls': [{'function': {'name': 'do_something'}}]},
    None, 'YES',
])
async def test_invalid_or_negative_responses_fail_closed(mock_agent, discovery, response):
    mock_agent._llm_mock.generate_chat.return_value = response
    assert await judge(mock_agent).decide(tracker(mock_agent)) is False


@pytest.mark.asyncio
async def test_catalog_is_singleflight_and_cached_for_judge_lifetime(mock_agent, discovery):
    entered, release = asyncio.Event(), asyncio.Event()
    async def discover(*args):
        entered.set()
        await release.wait()
        return [{'name': 'weather', 'description': 'Look up weather'}]
    discovery.side_effect = discover
    instance = judge(mock_agent)
    decisions = [asyncio.create_task(instance.decide(tracker(mock_agent))) for _ in range(5)]
    await entered.wait()
    release.set()
    await asyncio.gather(*decisions)
    await instance.decide(tracker(mock_agent))
    discovery.assert_awaited_once_with(mock_agent.config_path, mock_agent.skill_paths)


@pytest.mark.asyncio
async def test_catalog_failure_fails_closed_without_model_and_retries_later(mock_agent, discovery, caplog):
    discovery.side_effect = [RuntimeError('SECRET_PATH'), []]
    instance = judge(mock_agent)
    assert await instance.decide(tracker(mock_agent)) is False
    mock_agent._llm_mock.generate_chat.assert_not_awaited()
    assert 'SECRET_PATH' not in caplog.text
    await instance.decide(tracker(mock_agent))
    assert discovery.await_count == 2
    mock_agent._llm_mock.generate_chat.assert_awaited_once()


@pytest.mark.asyncio
async def test_model_failure_fails_closed_and_cancellation_propagates(mock_agent, discovery):
    instance = judge(mock_agent)
    mock_agent._llm_mock.generate_chat.side_effect = RuntimeError('provider down')
    assert await instance.decide(tracker(mock_agent)) is False
    mock_agent._llm_mock.generate_chat.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await instance.decide(tracker(mock_agent))


@pytest.mark.asyncio
async def test_timeout_covers_discovery_and_fails_closed(mock_agent, discovery):
    instance = judge(mock_agent)
    instance.timeout_seconds = .01
    discovery.side_effect = lambda *args: None
    async def never(*args):
        await asyncio.Event().wait()
    discovery.side_effect = never
    assert await instance.decide(tracker(mock_agent)) is False
    mock_agent._llm_mock.generate_chat.assert_not_awaited()


@pytest.mark.asyncio
async def test_real_pi_catalog_does_not_leak_sop_bodies(mock_agent):
    mock_agent.add_skill('weather', 'TOP_SECRET_SOP')
    await judge(mock_agent).decide(tracker(mock_agent))
    system = mock_agent._llm_mock.generate_chat.call_args.kwargs['messages'][0]['content']
    assert 'Instructions for weather' in system
    assert 'TOP_SECRET_SOP' not in system
    assert 'Use the available tools to search the web.' not in system


def test_discovery_honors_configured_pi_node(mock_agent):
    mock_agent.dialogue['pi_node'] = '/deployment/private/node'
    assert judge(mock_agent)._bridge.node == '/deployment/private/node'


@pytest.mark.asyncio
@pytest.mark.parametrize("allow_http", [True, False])
async def test_large_capabilities_are_bounded_metadata_json_with_omission_counts(mock_agent, discovery, allow_http):
    from cota.executor.tools.base import FunctionTool, create_tool_schema
    from cota.executor.tools.registry import ToolPolicy
    skills = [{'name': f'skill-{i}', 'description': '\\"\n中文' * 4000,
               'body': 'SECRET_SOP_BODY'} for i in range(300)]
    discovery.return_value = skills
    registry = mock_agent.get_tool_registry()
    registry.set_policy(ToolPolicy(deny=[] if allow_http else ['web_fetch']))
    for index in range(300):
        registry.register(FunctionTool(f'tool-{index}', '\\"\n中文' * 4000,
                                       create_tool_schema({}), AsyncMock()))
    # An oversized name must not be presented as a different, truncated tool.
    registry.register(FunctionTool('tool-' + 'x' * 20000, 'Oversized tool name',
                                   create_tool_schema({}), AsyncMock()))
    await judge(mock_agent).decide(tracker(mock_agent))
    system = mock_agent._llm_mock.generate_chat.call_args.kwargs['messages'][0]['content']
    raw = system.split('Capabilities (names and descriptions only):\n', 1)[1]
    catalog = json.loads(raw)
    assert len(raw) <= 12000
    assert catalog['skills'] and catalog['tools']
    assert catalog['omitted']['skills'] == len(skills) - len(catalog['skills']) > 0
    allowed_names = {tool.name for tool in registry.get_allowed_tools()}
    if allow_http:
        allowed_names.add('web_fetch')
    assert catalog['omitted']['tools'] == len(allowed_names) - len(catalog['tools']) > 0
    assert 'may be truncated' in catalog['context_note']
    assert all(set(item) == {'name', 'description'}
               for key in ('skills', 'tools') for item in catalog[key])
    assert 'SECRET_SOP_BODY' not in system
    assert all(item['name'] in allowed_names for item in catalog['tools'])


@pytest.mark.parametrize('attributes', [{}, {'dialogue': None}])
def test_constructor_accepts_minimal_agent_without_dialogue(attributes):
    from types import SimpleNamespace
    instance = judge(SimpleNamespace(**attributes))
    assert instance._bridge.node is None
