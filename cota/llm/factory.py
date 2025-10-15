"""LLM client factory for creating appropriate client instances."""

from typing import Dict

from .base import LLMClient
from .openai import OpenAIClient, OpenAIRAGClient
from .custom import CustomHttpClient


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
        
        # Extract common parameters
        api_key = config['key']
        base_url = config['apibase']
        model = config['model']
        
        if client_type == 'openai':
            return OpenAIClient(
                api_key=api_key,
                base_url=base_url,
                model=model
            )
        elif client_type == 'openai-rag':
            knowledge_id = config['knowledge_id']
            rag_prompt = config.get('rag_prompt')
            return OpenAIRAGClient(
                api_key=api_key,
                base_url=base_url,
                model=model,
                knowledge_id=knowledge_id,
                rag_prompt=rag_prompt
            )
        elif client_type == 'custom':
            extra_config = {
                k: v for k, v in config.items() 
                if k not in ['type', 'key', 'apibase', 'model']
            }
            return CustomHttpClient(
                api_key=api_key,
                base_url=base_url,
                model=model,
                **extra_config
            )
        else:
            raise ValueError(f"Unsupported client type: {client_type}")
