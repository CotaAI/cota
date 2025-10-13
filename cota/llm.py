import aiohttp
import json
import logging
from abc import ABC, abstractmethod
from typing import List, Dict, Text, Optional, Any

from cota.constant import (
    RAG_PROMPT_TEMPLATE
)

logger = logging.getLogger(__name__)


class LLMClient(ABC):
    @abstractmethod
    async def generate_chat(
        self, 
        messages: List[Dict[Text, Text]], 
        max_tokens: int = 500,
        response_format: Dict[Text, Text] = {"type": "text"},
        tools: Optional[List[Dict[Text, Any]]] = None,
        tool_choice: Optional[str] = None
    ) -> Dict[Text, Any]:
        pass


class OpenAIClient(LLMClient):
    def __init__(self, api_key: Text, base_url: Text, model: Text):
        from openai import OpenAI
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = model

    async def generate_chat(
        self, 
        messages: List[Dict[Text, Text]], 
        max_tokens: int = 500,
        response_format: Dict[Text, Text] = {"type": "text"},
        tools: Optional[List[Dict[Text, Any]]] = None,
        tool_choice: Optional[str] = None
    ) -> Dict[Text, Any]:
        try:
            # Build request parameters
            request_params = {
                "model": self.model,
                "messages": messages,
                "max_tokens": max_tokens,
                "response_format": response_format
            }
            
            # If tools are provided, add them to request parameters
            if tools:
                request_params["tools"] = tools
                if tool_choice:
                    request_params["tool_choice"] = tool_choice
            
            response = self.client.chat.completions.create(**request_params)
            
            # Handle response
            if tools and response.choices[0].message.tool_calls:
                return {
                    "content": response.choices[0].message.content,
                    "tool_calls": [
                        {
                            "function": {
                                "name": tool_call.function.name,
                                "arguments": tool_call.function.arguments
                            }
                        }
                        for tool_call in response.choices[0].message.tool_calls
                    ]
                }
            else:
                return response.choices[0].message.content
                
        except Exception as e:
            logger.error(f"Request failed: {e}")
            raise


class CustomHttpClient(LLMClient):
    def __init__(self, api_key: Text, base_url: Text, model: Text):
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.session = aiohttp.ClientSession()

    async def generate_chat(
        self, 
        messages: List[Dict[Text, Text]], 
        max_tokens: int = 500,
        response_format: Dict[Text, Text] = {"type": "text"},
        tools: Optional[List[Dict[Text, Any]]] = None,
        tool_choice: Optional[str] = None
    ) -> Dict[Text, Any]:
        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json'
        }
        
        # Build request data
        data = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "response_format": response_format
        }
        
        # If tools are provided, add them to request data
        if tools:
            data["tools"] = tools
            if tool_choice:
                data["tool_choice"] = tool_choice
        
        async with self.session.post(self.base_url, json=data, headers=headers) as response:
            response.raise_for_status()
            response_data = await response.json()
            return response_data


class OpenAIRAGClient(LLMClient):
    def __init__(self, api_key: Text, base_url: Text, model: Text, knowledge_id: Text, rag_prompt: Text):
        from openai import OpenAI
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = model
        self.knowledge_id = knowledge_id
        self.rag_prompt = rag_prompt
        
    async def generate_chat(
        self, 
        messages: List[Dict[Text, Text]], 
        max_tokens: int = 500,
        response_format: Dict[Text, Text] = {"type": "text"},
        tools: Optional[List[Dict[Text, Any]]] = None,
        tool_choice: Optional[str] = None
    ) -> Dict[Text, Any]:
        try:
            # Build request parameters
            request_params = {
                "model": self.model,
                "messages": messages,
                "max_tokens": max_tokens,
                "tools": [
                    {
                        "type": "retrieval",
                        "retrieval": {
                            "knowledge_id": self.knowledge_id,
                            "prompt_template": rag_prompt
                        }
                    }
                ]
            }
            
            # If additional tools are provided, add them to request parameters
            if tools:
                request_params["tools"].extend(tools)
                if tool_choice:
                    request_params["tool_choice"] = tool_choice
            
            response = self.client.chat.completions.create(**request_params)
            
            # Handle response
            if tools and response.choices[0].message.tool_calls:
                return {
                    "content": response.choices[0].message.content,
                    "tool_calls": [
                        {
                            "function": {
                                "name": tool_call.function.name,
                                "arguments": tool_call.function.arguments
                            }
                        }
                        for tool_call in response.choices[0].message.tool_calls
                    ]
                }
            else:
                return {
                    "content": response.choices[0].message.content
                }
                
        except Exception as e:
            logger.error(f"Request failed: {e}")
            raise


class CustomHttpRAGClient(LLMClient):
    def __init__(self, api_key: Text, base_url: Text, model: Text, knowledge_id: Text):
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.knowledge_id = knowledge_id
        self.session = aiohttp.ClientSession()

    async def generate_chat(
        self, 
        messages: List[Dict[Text, Text]], 
        max_tokens: int = 500,
        response_format: Dict[Text, Text] = {"type": "text"},
        tools: Optional[List[Dict[Text, Any]]] = None,
        tool_choice: Optional[str] = None
    ) -> Dict[Text, Any]:
        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json'
        }
        
        # Build request data
        data = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "response_format": response_format,
            "knowledge_id": self.knowledge_id
        }
        
        # If tools are provided, add them to request data
        if tools:
            data["tools"] = tools
            if tool_choice:
                data["tool_choice"] = tool_choice
        
        async with self.session.post(self.base_url, json=data, headers=headers) as response:
            response.raise_for_status()
            response_data = await response.json()
            return response_data


class LLMClientFactory:
    @staticmethod
    def create_client(config: Dict) -> LLMClient:
        userag = config.get('userag')
        apitype = config.get('apitype')
        if apitype == 'openai' and userag == True:
            return OpenAIRAGClient(
                api_key=config['key'], 
                base_url=config['apibase'], 
                model=config['model'], 
                knowledge_id=config['knowledge_id']
            )
        elif apitype == 'custom' and userag == True:
            return CustomHttpRAGClient(
                api_key=config['key'], 
                base_url=config['apibase'], 
                model=config['model'],
                knowledge_id=config['knowledge_id']
            )
        elif apitype == 'openai':
            return OpenAIClient(
                api_key=config['key'], 
                base_url=config['apibase'], 
                model=config['model']
            )
        elif apitype == 'custom':
            return CustomHttpClient(
                api_key=config['key'], 
                base_url=config['apibase'], 
                model=config['model']
            )
        else:
            raise ValueError(f"Unsupported API type: {apitype}")


class LLM:
    def __init__(self, config: Dict):
        self.client = LLMClientFactory.create_client(config)

    async def generate_chat(
        self, 
        messages: List[Dict[Text, Text]], 
        max_tokens: int = 500,
        response_format: Dict[Text, Text] = {"type": "text"},
        tools: Optional[List[Dict[Text, Any]]] = None,
        tool_choice: Optional[str] = None
    ) -> Dict[Text, Any]:
        return await self.client.generate_chat(
            messages, 
            max_tokens, 
            response_format,
            tools,
            tool_choice
        )
