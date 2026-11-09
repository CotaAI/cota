"""Tests for cota.llm — LLM, LLMClientFactory"""

import pytest
from unittest.mock import AsyncMock
from cota.llm.llm import LLM
from cota.llm.factory import LLMClientFactory
from cota.llm.openai import OpenAIClient, OpenAIRAGClient
from cota.llm.custom import CustomHttpClient


_BASE_CONFIG = {
    "model": "test-model",
    "type": "openai",
    "key": "sk-test",
    "apibase": "https://api.test.com/v1",
}


class TestLLMClientFactory:

    def test_create_openai_client(self):
        client = LLMClientFactory.create_client(_BASE_CONFIG)
        assert isinstance(client, OpenAIClient)

    def test_create_openai_rag_client(self):
        config = {**_BASE_CONFIG, "type": "openai-rag", "knowledge_id": "k1"}
        client = LLMClientFactory.create_client(config)
        assert isinstance(client, OpenAIRAGClient)

    def test_create_custom_client(self):
        config = {**_BASE_CONFIG, "type": "custom"}
        client = LLMClientFactory.create_client(config)
        assert isinstance(client, CustomHttpClient)

    def test_create_unsupported_raises(self):
        config = {**_BASE_CONFIG, "type": "unsupported"}
        with pytest.raises(ValueError, match="Unsupported"):
            LLMClientFactory.create_client(config)

    def test_missing_key_raises(self):
        config = {"model": "m", "type": "openai", "apibase": "http://x"}
        with pytest.raises(ValueError, match='endpoints.yml'):
            LLMClientFactory.create_client(config)

    def test_default_type_is_openai(self):
        config = {"model": "m", "key": "k", "apibase": "http://x"}
        client = LLMClientFactory.create_client(config)
        assert isinstance(client, OpenAIClient)


class TestLLM:

    def test_init_creates_client(self):
        llm = LLM(_BASE_CONFIG)
        assert llm.client is not None

    @pytest.mark.asyncio
    async def test_generate_chat(self):
        llm = LLM(_BASE_CONFIG)
        llm.client.generate_chat = AsyncMock(
            return_value={"content": "Hello!", "tool_calls": []}
        )
        result = await llm.generate_chat(
            messages=[{"role": "user", "content": "Hi"}],
            max_tokens=100,
        )
        assert result["content"] == "Hello!"
        llm.client.generate_chat.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_generate_chat_with_tools(self):
        llm = LLM(_BASE_CONFIG)
        llm.client.generate_chat = AsyncMock(
            return_value={
                "content": "",
                "tool_calls": [{"function": {"name": "exec", "arguments": "{}"}}],
            }
        )
        tools = [{"type": "function", "function": {"name": "exec"}}]
        result = await llm.generate_chat(
            messages=[{"role": "user", "content": "run ls"}],
            tools=tools,
        )
        assert len(result["tool_calls"]) == 1

    @pytest.mark.asyncio
    async def test_generate_chat_default_format(self):
        llm = LLM(_BASE_CONFIG)
        llm.client.generate_chat = AsyncMock(return_value={"content": "ok"})
        await llm.generate_chat(messages=[{"role": "user", "content": "test"}])

        call_args = llm.client.generate_chat.call_args
        assert call_args.kwargs["response_format"] == {"type": "text"}


class TestOpenAIClient:

    def test_init(self):
        client = OpenAIClient(
            api_key="sk-test",
            base_url="https://api.test.com/v1",
            model="gpt-4",
        )
        assert client.model == "gpt-4"

    def test_init_with_thinking(self):
        client = OpenAIClient(
            api_key="sk-test",
            base_url="https://api.test.com/v1",
            model="gpt-4",
            thinking={"budget_tokens": 1000},
        )
        assert client.thinking == {"budget_tokens": 1000}
