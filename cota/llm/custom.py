"""Custom HTTP LLM client."""

import aiohttp
import logging
from typing import List, Dict, Text, Optional, Any

from .base import LLMClient
from .observation import provider_request, provider_response

logger = logging.getLogger(__name__)


class CustomHttpClient(LLMClient):
    """Custom HTTP client that passes all config parameters to the HTTP endpoint.
    
    This client provides maximum flexibility by forwarding all configuration
    parameters to the HTTP endpoint, allowing the endpoint to decide how to
    handle RAG, authentication, and other custom features.
    """
    
    def __init__(self, api_key: Text, base_url: Text, model: Text, **kwargs):
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        # Store all additional config parameters for flexible passing to HTTP endpoint
        self.extra_config = kwargs
        self._session: Optional[aiohttp.ClientSession] = None

    @property
    def session(self) -> aiohttp.ClientSession:
        """Lazy-init aiohttp session (requires a running event loop)."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def generate_chat(
        self, 
        messages: List[Dict[Text, Text]], 
        max_tokens: int = 500,
        response_format: Optional[Dict[Text, Text]] = None,
        tools: Optional[List[Dict[Text, Any]]] = None,
        tool_choice: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> Dict[Text, Any]:
        response_format = response_format or {"type": "text"}
        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json'
        }
        
        # Build request data with core parameters
        data = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "response_format": response_format
        }
        
        # Add all extra config parameters (knowledge_id, rag_prompt, etc.)
        # Let the HTTP endpoint decide how to handle them
        data.update(self.extra_config)
        if temperature is not None:
            data['temperature'] = temperature
        
        # If tools are provided, add them to request data
        if tools:
            data["tools"] = tools
            if tool_choice:
                data["tool_choice"] = tool_choice
        
        await provider_request(data)
        async with self.session.post(self.base_url, json=data, headers=headers) as response:
            response.raise_for_status()
            response_data = await response.json()
            provider_response(response_data)
            
            # Ensure consistent return format - if response is a string, wrap it in a dict
            if isinstance(response_data, str):
                return {"content": response_data}
            elif isinstance(response_data, dict) and 'tool_calls' in response_data:
                return {'content': '', **response_data}
            elif isinstance(response_data, dict) and "content" not in response_data:
                # If it's a dict but doesn't have content field, assume the whole response is content
                return {"content": str(response_data)}
            else:
                # If it's already a dict with content field, return as is
                return response_data

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def close(self):
        session, self._session = self._session, None
        if session is not None and not session.closed:
            await session.close()

