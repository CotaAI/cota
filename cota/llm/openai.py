"""OpenAI-compatible adapters sharing request, response and resource handling."""
import logging
from typing import Any, Dict, List, Optional, Text

from .base import LLMClient
from .observation import (provider_request, provider_response, provider_transport,
                          provider_attempt_started, provider_headers_received)
from .limits import DEFAULT_TIMEOUT_SECONDS, DEFAULT_MAX_RETRIES

logger = logging.getLogger(__name__)


class OpenAIClient(LLMClient):
    def __init__(self, api_key: Text, base_url: Text, model: Text, thinking: Optional[Text] = None,
                 timeout_seconds=DEFAULT_TIMEOUT_SECONDS, max_retries=DEFAULT_MAX_RETRIES):
        from openai import AsyncOpenAI, DefaultAsyncHttpxClient
        self.timeout_seconds, self.max_retries = timeout_seconds, max_retries
        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=timeout_seconds,
            max_retries=max_retries, http_client=DefaultAsyncHttpxClient(event_hooks={
                'request': [provider_attempt_started], 'response': [provider_headers_received]}))
        self.model, self.thinking = model, thinking
        self._uses_completion_tokens = any(
            name in model.lower() for name in ('gpt-4o', 'gpt-5', 'o1', 'o3', 'kimi', 'moonshot'))

    def _request_tools(self, tools):
        return tools

    async def generate_chat(self, messages: List[Dict[Text, Text]], max_tokens: int = 500,
                            response_format: Optional[Dict[Text, Text]] = None,
                            tools: Optional[List[Dict[Text, Any]]] = None,
                            tool_choice: Optional[str] = None,
                            temperature: Optional[float] = None) -> Dict[Text, Any]:
        request = {'model': self.model, 'messages': messages,
                   'response_format': response_format or {'type': 'text'}}
        request['max_completion_tokens' if self._uses_completion_tokens else 'max_tokens'] = max_tokens
        request_tools = self._request_tools(tools)
        if request_tools:
            request['tools'] = request_tools
            if tool_choice:
                request['tool_choice'] = tool_choice
        if temperature is not None:
            request['temperature'] = temperature
        if self.thinking:
            request['extra_body'] = {'thinking': {'type': self.thinking}}
        provider_transport(timeout_seconds=self.timeout_seconds, max_retries=self.max_retries)
        await provider_request(request)
        response = await self.client.chat.completions.create(**request)
        provider_response(response)
        choice = response.choices[0]
        reason = getattr(choice, 'finish_reason', None)
        result = {'content': choice.message.content or '', 'finish_reason': reason}
        usage = getattr(response, 'usage', None)
        if usage is not None:
            prompt = getattr(usage, 'prompt_tokens', 0) or 0
            output = getattr(usage, 'completion_tokens', 0) or 0
            cached = getattr(getattr(usage, 'prompt_tokens_details', None), 'cached_tokens', 0) or 0
            result['usage'] = {'input': max(0, prompt - cached), 'output': output,
                              'cacheRead': cached, 'cacheWrite': 0,
                              'totalTokens': getattr(usage, 'total_tokens', None) or prompt + output,
                              'cost': {'input': 0, 'output': 0, 'cacheRead': 0, 'cacheWrite': 0, 'total': 0}}
        if choice.message.tool_calls:
            result['tool_calls'] = [
                {'id': call.id, 'type': 'function',
                 'function': {'name': call.function.name, 'arguments': call.function.arguments}}
                for call in choice.message.tool_calls]
        if reason == 'length':
            logger.warning('LLM response truncated at token limit %s', max_tokens)
            if 'tool_calls' not in result:
                result['content'] += '\n\n[WARNING: Response was truncated due to token limit. The output may be incomplete.]'
        return result

    async def close(self):
        await self.client.close()


class OpenAIRAGClient(OpenAIClient):
    """Provider-side retrieval augments the same function-tool request contract."""
    def __init__(self, api_key: Text, base_url: Text, model: Text, knowledge_id: Text,
                 rag_prompt: Optional[Text] = None, thinking: Optional[Text] = None,
                 timeout_seconds=DEFAULT_TIMEOUT_SECONDS, max_retries=DEFAULT_MAX_RETRIES):
        super().__init__(api_key, base_url, model, thinking, timeout_seconds, max_retries)
        self.knowledge_id, self.rag_prompt = knowledge_id, rag_prompt

    def _request_tools(self, tools):
        retrieval = {'knowledge_id': self.knowledge_id}
        if self.rag_prompt:
            retrieval['prompt_template'] = self.rag_prompt
        return [{'type': 'retrieval', 'retrieval': retrieval}, *(tools or [])]
