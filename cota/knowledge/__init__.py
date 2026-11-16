"""File-driven knowledge base: auto-discovered, BM25-indexed, optional embedding hybrid search."""
from .index import KnowledgeIndex
from .tool import KnowledgeTool

__all__ = ['KnowledgeIndex', 'KnowledgeTool']
