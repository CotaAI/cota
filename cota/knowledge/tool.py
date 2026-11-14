"""search_knowledge tool: atomic knowledge retrieval for Pi runtime."""
import logging

from cota.executor.tools.base import Tool, create_tool_schema

logger = logging.getLogger(__name__)


class KnowledgeTool(Tool):
    """BM25 knowledge search with optional LLM rerank/navigate.

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

        rerank = self._index.manifest.rerank
        try:
            if rerank == 'false':
                result = self._index.search(query)
            else:
                llm = self._resolve_llm()
                if rerank == 'navigate':
                    result = await self._index.search_with_navigate(query, llm)
                else:
                    result = await self._index.search_with_rerank(query, llm)
        except Exception as e:
            logger.error(f'Knowledge search failed: {e}')
            return {'content': [{'type': 'text', 'text': f'知识库检索失败：{e}'}],
                    'details': {}, 'isError': True}

        if not result:
            return {'content': [{'type': 'text', 'text': '未找到相关知识。'}], 'details': {}}

        return {'content': [{'type': 'text', 'text': result}], 'details': {}}

    def _resolve_llm(self):
        llm_name = self._index.manifest.llm
        return self._agent.llm_instance(llm_name)
