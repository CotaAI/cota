"""search_knowledge tool: atomic knowledge retrieval for Pi runtime."""
import logging

from cota.executor.tools.base import Tool, create_tool_schema

logger = logging.getLogger(__name__)


class KnowledgeTool(Tool):
    """BM25 knowledge search with optional embedding-based hybrid retrieval.

    Registered automatically when a Bot has a knowledge/ directory with KNOWLEDGE.md.
    Each invocation is one atomic tool event — internal retrieval steps are invisible.
    """

    def __init__(self, index, agent):
        self._index = index
        self._agent = agent

    @property
    def name(self):
        return 'search_knowledge'

    @property
    def internal(self):
        return True

    @property
    def description(self):
        return f'搜索知识库。{self._index.manifest.description}'

    @property
    def parameters(self):
        return create_tool_schema(
            properties={'query': {'type': 'string', 'description': '搜索关键词或问题'}},
            required=['query'],
        )

    async def execute(self, **kwargs):
        query = kwargs.get('query', '')
        if not query or not query.strip():
            return {'content': [{'type': 'text', 'text': '请提供搜索关键词。'}],
                    'details': {}, 'isError': True}

        try:
            if self._index.manifest.embedding and self._index._vector is not None:
                emb_client = self._resolve_embedding_client()
                try:
                    result, result_count = await self._index.search_with_embedding(query, emb_client)
                except Exception as e:
                    logger.warning(f'Embedding search failed, falling back to BM25: {e}')
                    result, result_count = self._index.search(query)
            else:
                result, result_count = self._index.search(query)
        except Exception as e:
            logger.error(f'Knowledge search failed: {e}')
            return {'content': [{'type': 'text', 'text': f'知识库检索失败：{e}'}],
                    'details': {}, 'isError': True}

        if not result:
            return {'content': [{'type': 'text', 'text': '未找到相关知识。'}], 'details': {'hits': 0}}

        return {'content': [{'type': 'text', 'text': result}], 'details': {'hits': result_count}}

    def _resolve_embedding_client(self):
        emb_name = self._index.manifest.embedding
        return self._agent.embedding_client(emb_name)
