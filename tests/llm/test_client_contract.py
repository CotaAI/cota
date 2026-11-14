"""Adapter contracts use concrete LLM wrappers and fake provider transports."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from cota.llm.custom import CustomHttpClient
from cota.llm.llm import LLM
from cota.llm.openai import OpenAIClient, OpenAIRAGClient


@pytest.mark.asyncio
async def test_unused_custom_context_and_repeated_close_never_allocate_session():
    with patch('cota.llm.custom.aiohttp.ClientSession') as factory:
        async with CustomHttpClient('test-key', 'https://example.invalid', 'test') as client:
            pass
        await client.close()
        factory.assert_not_called()


@pytest.mark.asyncio
async def test_custom_close_closes_existing_session_once():
    client = CustomHttpClient('test-key', 'https://example.invalid', 'test')
    session = SimpleNamespace(closed=False, close=AsyncMock())
    client._session = session
    await client.close()
    await client.close()
    session.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_custom_tool_only_response_preserves_structured_calls():
    client = CustomHttpClient('test-key', 'https://example.invalid', 'test')
    calls = [{'id': 'one', 'type': 'function', 'function': {'name': 'lookup', 'arguments': '{}'}}]
    reply = SimpleNamespace(raise_for_status=Mock(), json=AsyncMock(return_value={'tool_calls': calls}))
    context = AsyncMock()
    context.__aenter__.return_value = reply
    client._session = SimpleNamespace(closed=False, post=Mock(return_value=context), close=AsyncMock())
    result = await client.generate_chat([{'role': 'user', 'content': 'hello'}])
    assert result['tool_calls'] == calls and result['content'] == ''
    await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('client_type', [OpenAIClient, OpenAIRAGClient])
async def test_openai_adapter_preserves_calls_finish_reason_and_optional_settings(client_type):
    extra = {'knowledge_id': 'kb'} if client_type is OpenAIRAGClient else {}
    client = client_type('test-key', 'https://example.invalid', 'gpt-5', thinking='disabled', **extra)
    call = SimpleNamespace(id='id', function=SimpleNamespace(name='lookup', arguments='{"n":1}'))
    provider = AsyncMock(return_value=SimpleNamespace(choices=[SimpleNamespace(
        message=SimpleNamespace(content=None, tool_calls=[call]), finish_reason='tool_calls')]))
    client.client.chat.completions.create = provider
    try:
        result = await client.generate_chat([{'role': 'user', 'content': 'hi'}], max_tokens=123,
            tools=[{'type': 'function', 'function': {'name': 'lookup'}}], tool_choice='auto')
        request = provider.call_args.kwargs
        assert request['max_completion_tokens'] == 123 and 'max_tokens' not in request
        assert 'temperature' not in request
        assert request['extra_body'] == {'thinking': {'type': 'disabled'}}
        assert request['tool_choice'] == 'auto'
        assert result == {'content': '', 'finish_reason': 'tool_calls', 'tool_calls': [
            {'id': 'id', 'type': 'function', 'function': {'name': 'lookup', 'arguments': '{"n":1}'}}]}
    finally:
        await client.client.close()


@pytest.mark.asyncio
async def test_agent_cleanup_closes_unique_models_even_when_tools_fail():
    from cota.agent import Agent
    llm = SimpleNamespace(close=AsyncMock())
    agent = Agent(llms={'one': llm, 'alias': llm})
    agent._tool_registry = SimpleNamespace(cleanup=AsyncMock(side_effect=RuntimeError('tool cleanup')))
    with pytest.raises(RuntimeError, match='tool cleanup'):
        await agent.cleanup()
    llm.close.assert_awaited_once()
