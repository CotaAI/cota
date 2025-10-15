"""LLM (Large Language Model) module for COTA.

This module provides a unified interface for interacting with various
language model providers including OpenAI-compatible APIs.
"""

from .llm import LLM
from .base import LLMClient
from .factory import LLMClientFactory
from .openai import OpenAIClient, OpenAIRAGClient
from .custom import CustomHttpClient

__all__ = [
    'LLM',
    'LLMClient', 
    'LLMClientFactory',
    'OpenAIClient',
    'OpenAIRAGClient', 
    'CustomHttpClient'
]
