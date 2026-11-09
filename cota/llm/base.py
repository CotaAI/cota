"""Base classes for LLM clients."""

import logging
from abc import ABC, abstractmethod
from typing import List, Dict, Text, Optional, Any

logger = logging.getLogger(__name__)


class LLMClient(ABC):
    """Abstract base class for all LLM clients."""
    
    @abstractmethod
    async def generate_chat(
        self, 
        messages: List[Dict[Text, Text]], 
        max_tokens: int = 500,
        response_format: Optional[Dict[Text, Text]] = None,
        tools: Optional[List[Dict[Text, Any]]] = None,
        tool_choice: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> Dict[Text, Any]:
        """Generate chat completion response.
        
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
        pass

    async def close(self):
        """Release owned connections; adapters without resources need no cleanup."""
