"""File-driven knowledge base: auto-discovered, BM25-indexed, optional LLM rerank."""
from .index import KnowledgeIndex
from .tool import KnowledgeTool

__all__ = ['KnowledgeIndex', 'KnowledgeTool']
