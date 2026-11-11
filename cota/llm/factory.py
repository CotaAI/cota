"""LLM client factory for creating appropriate client instances."""

from typing import Dict
import re

from .base import LLMClient
from .openai import OpenAIClient, OpenAIRAGClient
from .custom import CustomHttpClient
from .limits import request_limits


def endpoint_value(config, key):
    """Read a literal model setting; never substitute process credentials."""
    value = config.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'请在 endpoints.yml 中填写模型服务的 {key}')
    if re.fullmatch(r'\$\{[^{}]+\}', value):
        raise ValueError(f'endpoints.yml 的 {key} 不支持环境变量引用，请直接填写实际值')
    return value


class LLMClientFactory:
    """Factory class for creating LLM client instances based on configuration."""
    
    @staticmethod
    def create_client(config: Dict) -> LLMClient:
        """Create appropriate LLM client based on configuration.
        
        Args:
            config: Configuration dictionary containing client type and parameters
            
        Returns:
            LLMClient instance
            
        Raises:
            ValueError: If client type is not supported
        """
        client_type = config.get('type', 'openai')
        
        api_key = endpoint_value(config, 'key')
        base_url = endpoint_value(config, 'apibase')
        model = endpoint_value(config, 'model')
        timeout, retries = request_limits(config)
        
        if client_type == 'openai':
            thinking = config.get('thinking')
            return OpenAIClient(
                api_key=api_key,
                base_url=base_url,
                model=model,
                thinking=thinking, timeout_seconds=timeout, max_retries=retries,
            )
        elif client_type == 'openai-rag':
            knowledge_id = config['knowledge_id']
            rag_prompt = config.get('rag_prompt')
            thinking = config.get('thinking')
            return OpenAIRAGClient(
                api_key=api_key,
                base_url=base_url,
                model=model,
                knowledge_id=knowledge_id,
                rag_prompt=rag_prompt,
                thinking=thinking, timeout_seconds=timeout, max_retries=retries,
            )
        elif client_type == 'custom':
            extra_config = {
                k: v for k, v in config.items() 
                if k not in ['type', 'key', 'apibase', 'model', 'vision', 'context_window',
                             'timeout_seconds', 'max_retries']
            }
            return CustomHttpClient(
                api_key=api_key,
                base_url=base_url,
                model=model,
                **extra_config
            )
        else:
            raise ValueError(f"Unsupported client type: {client_type}")
