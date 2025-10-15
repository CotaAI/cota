"""Main LLM class for high-level language model operations."""

from typing import List, Dict, Text, Optional, Any

from .factory import LLMClientFactory


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
        self.client = LLMClientFactory.create_client(config)

    async def generate_chat(
        self, 
        messages: List[Dict[Text, Text]], 
        max_tokens: int = 500,
        response_format: Dict[Text, Text] = {"type": "text"},
        tools: Optional[List[Dict[Text, Any]]] = None,
        tool_choice: Optional[str] = None
    ) -> Dict[Text, Any]:
        """Generate chat completion using the configured client.
        
        Args:
            messages: List of message dictionaries
            max_tokens: Maximum tokens to generate
            response_format: Response format specification
            tools: Optional list of available tools
            tool_choice: Optional tool choice specification
            
        Returns:
            Dict containing the response from the language model
        """
        return await self.client.generate_chat(
            messages, 
            max_tokens, 
            response_format,
            tools,
            tool_choice
        )
