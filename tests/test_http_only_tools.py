"""Service tools remain HTTP/resource read; personal adds explicit file delivery."""
import importlib.util

import pytest

from cota.dst import DST
from cota.events import UserUtterEvent
from cota.runtime.pi_runtime import PiAgentRuntime
from cota.store import MemoryStore
from tests.test_pi_runtime import call

REMOVED = ('ask_user', 'reply_user', 'notify', 'async_task', 'scheduler', 'mcp_client', 'user_memory')


def test_removed_tool_modules_are_gone():
    for name in REMOVED:
        assert importlib.util.find_spec('cota.executor.tools.' + name) is None


@pytest.mark.asyncio
async def test_service_offers_http_and_resource_read_only(mock_agent):
    dst = DST('s', mock_agent)
    dst.append_event(UserUtterEvent('hello'))
    await PiAgentRuntime(mock_agent, dst, 's').run()
    tools = mock_agent._llm_mock.generate_chat.call_args.kwargs['tools']
    assert {t['function']['name'] for t in tools} == {'http_request', 'read'}


@pytest.mark.asyncio
async def test_http_pi_error_result_and_followup_are_durable(mock_agent):
    mock_agent._llm_mock.generate_chat.side_effect = [
        {'tool_calls': [call('http_request', {'url': 'http://127.0.0.1/private'}, 'h')]},
        {'content': '无法访问该地址。'},
    ]
    store = MemoryStore()
    dst = DST('s', mock_agent)
    dst.append_event(UserUtterEvent('fetch'))
    await PiAgentRuntime(mock_agent, dst, 's', checkpoint=store.save).run()
    result = next(e for e in dst.events if e.type == 'tool_result')
    assert result.payload['status'] != 'success'
    assert dst.latest_bot_text() == '无法访问该地址。'
    restored = await store.load('s', agent=mock_agent)
    assert restored.context_messages == dst.context_messages
    assert restored.state_dict() == dst.state_dict()


@pytest.mark.asyncio
@pytest.mark.parametrize('policy', [{'allow': []}, {'deny': ['http_request']}])
async def test_http_configuration_disables_schema_and_hallucinated_call(mock_agent, policy):
    from cota.executor.tools import ToolPolicy
    mock_agent.get_tool_registry().set_policy(ToolPolicy(**policy))
    mock_agent._llm_mock.generate_chat.side_effect = [
        {'tool_calls': [call('http_request', {'url': 'http://127.0.0.1/private'}, 'h')]},
        {'content': 'No network capability'},
    ]
    dst = DST('s', mock_agent)
    dst.append_event(UserUtterEvent('fetch'))
    await PiAgentRuntime(mock_agent, dst, 's').run()
    for request in mock_agent._llm_mock.generate_chat.call_args_list:
        assert 'http_request' not in {t['function']['name'] for t in request.kwargs['tools']}
    assert next(e for e in dst.events if e.type == 'tool_result').payload['status'] == 'blocked'


@pytest.mark.asyncio
async def test_http_permission_revocation_is_checked_after_model_call(mock_agent):
    from cota.executor.tools import ToolPolicy
    async def model(**kwargs):
        if mock_agent._llm_mock.generate_chat.await_count == 1:
            assert 'http_request' in {t['function']['name'] for t in kwargs['tools']}
            mock_agent.get_tool_registry().set_policy(ToolPolicy(deny=['http_request']))
            return {'tool_calls': [call('http_request', {'url': 'http://127.0.0.1/private'}, 'h')]}
        return {'content': 'Revoked'}
    mock_agent._llm_mock.generate_chat.side_effect = model
    dst = DST('s', mock_agent)
    dst.append_event(UserUtterEvent('fetch'))
    await PiAgentRuntime(mock_agent, dst, 's').run()
    result = next(e for e in dst.events if e.type == 'tool_result')
    assert result.payload['status'] == 'blocked'  # No HTTP execute / address check ran.
    assert dst.latest_bot_text() == 'Revoked'


@pytest.mark.parametrize('key', ['allow', 'deny'])
def test_unknown_configured_tool_fails_before_run(mock_agent, key):
    from cota.executor.tools import ToolPolicy
    mock_agent.get_tool_registry().set_policy(ToolPolicy(**{key: ['http_requset']}))
    dst = DST('invalid-config', mock_agent)
    with pytest.raises(ValueError, match='Unknown configured tools.*http_requset'):
        PiAgentRuntime(mock_agent, dst, dst.session_id)
    assert not dst.events
    mock_agent._llm_mock.generate_chat.assert_not_called()


@pytest.mark.parametrize('key', ['allow', 'deny'])
def test_unknown_group_fails_at_config_validation(key):
    from cota.config import validate_bot_config
    with pytest.raises(ValueError, match='Unknown tool group'):
        validate_bot_config({'tools': {key: ['group:netwrok']}})
