"""OpenAI compatible LLM clients."""

import logging
from typing import List, Dict, Text, Optional, Any, Union

from .base import LLMClient

logger = logging.getLogger(__name__)


class OpenAIClient(LLMClient):
    """Standard OpenAI compatible client."""
    
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
            
            # Handle response - always return consistent dictionary format
            result = {
                "content": response.choices[0].message.content
            }
            
            # Add tool_calls if they exist
            if tools and response.choices[0].message.tool_calls:
                result["tool_calls"] = [
                    {
                        "function": {
                            "name": tool_call.function.name,
                            "arguments": tool_call.function.arguments
                        }
                    }
                    for tool_call in response.choices[0].message.tool_calls
                ]
            
            return result
                
        except Exception as e:
            logger.error(f"Request failed: {e}")
            raise


class OpenAIRAGClient(LLMClient):
    """OpenAI client with RAG (Retrieval-Augmented Generation) support."""
    
    def __init__(self, api_key: Text, base_url: Text, model: Text, knowledge_id: Text, rag_prompt: Optional[Text] = None):
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
            # Build RAG tool
            rag_tool = {
                "type": "retrieval",
                "retrieval": {
                    "knowledge_id": self.knowledge_id
                }
            }
            if self.rag_prompt:
                rag_tool["retrieval"]["prompt_template"] = self.rag_prompt
            
            # Prepare tools list starting with RAG tool
            request_tools = [rag_tool]
            
            # Add additional tools if provided
            if tools:
                request_tools.extend(tools)
            
            # Build request parameters
            request_params = {
                "model": self.model,
                "messages": messages,
                "max_tokens": max_tokens,
                "response_format": response_format,
                "tools": request_tools
            }
            
            if tool_choice:
                request_params["tool_choice"] = tool_choice
            
            response = self.client.chat.completions.create(**request_params)
            
            # Handle response - always return consistent dictionary format
            result = {
                "content": response.choices[0].message.content
            }
            
            # Add tool_calls if they exist
            if response.choices[0].message.tool_calls:
                result["tool_calls"] = [
                    {
                        "function": {
                            "name": tool_call.function.name,
                            "arguments": tool_call.function.arguments
                        }
                    }
                    for tool_call in response.choices[0].message.tool_calls
                ]
            
            return result
                
        except Exception as e:
            logger.error(f"Request failed: {e}")
            raise
