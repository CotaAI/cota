"""Main LLM class for high-level language model operations."""

import asyncio
from typing import List, Dict, Text, Optional, Any

from .factory import LLMClientFactory
from .observation import observe_model_call
from .limits import request_limits


class LLM:
    """High-level interface for language model operations.
    
    This class provides a unified interface for interacting with various
    language models through different client implementations.
    """
    
    def __init__(self, config: Dict):
        """Initialize LLM with configuration.
        
        Args:
            config: Configuration dictionary containing client type and parameters
        """
        self.timeout_seconds, self.max_retries = request_limits(config)
        self.supports_images = config.get('vision', False)
        if type(self.supports_images) is not bool:
            raise ValueError('endpoints.yml llms.<name>.vision must be boolean')
        self.context_window = config.get('context_window')
        if self.context_window is not None and (type(self.context_window) is not int or self.context_window < 2):
            raise ValueError('endpoints.yml llms.<name>.context_window must be an integer greater than 1')
        self.client = LLMClientFactory.create_client(config)
        self.name = config.get('model')

    def pi_provider(self):
        """Resolve an ordinary endpoint for Pi; never serialize it into traces.

        Python-specific custom/RAG adapters deliberately retain their own model
        transport. They are not silently treated as compatible streaming APIs.
        """
        from .openai import OpenAIClient
        if type(self.client) is not OpenAIClient:
            return None
        return {'apiKey': self.client.client.api_key, 'baseUrl': str(self.client.client.base_url),
                'model': self.client.model, 'thinking': self.client.thinking,
                'vision': self.supports_images, 'timeoutSeconds': self.timeout_seconds,
                'maxRetries': self.max_retries}

    async def generate_chat(
        self, 
        messages: List[Dict[Text, Text]], 
        max_tokens: int = 500,
        response_format: Optional[Dict[Text, Text]] = None,
        tools: Optional[List[Dict[Text, Any]]] = None,
        tool_choice: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> Dict[Text, Any]:
        """Generate chat completion using the configured client.
        
        Args:
            messages: List of message dictionaries
            max_tokens: Maximum tokens to generate
            response_format: Response format specification
            tools: Optional list of available tools
            tool_choice: Optional tool choice specification
            
        Returns:
            Dict: Always returns a dictionary with the following structure:
            - "content": str - The generated text content
            - "tool_calls": List[Dict] (optional) - List of tool calls if tools were used
        """
        response_format = response_format or {"type": "text"}
        request = {
            'messages': messages, 'max_tokens': max_tokens,
            'response_format': response_format, 'tools': tools, 'tool_choice': tool_choice,
        }
        if temperature is not None:
            request['temperature'] = temperature
        return await observe_model_call(self._generate_chat, request, llm=self.name)

    async def _generate_chat(self, **request):
        # HTTP read timeouts measure inactivity, not total time. A provider may
        # keep a queued request alive indefinitely with whitespace or heartbeats.
        deadline = asyncio.timeout(self.timeout_seconds)
        try:
            async with deadline:
                return await self.client.generate_chat(**request)
        except TimeoutError:
            if deadline.expired():
                raise TimeoutError(f'Model request exceeded total timeout of {self.timeout_seconds:g} seconds') from None
            raise

    async def close(self):
        await self.client.close()
