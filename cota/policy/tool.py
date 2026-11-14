"""policy_guidance tool: structured policy retrieval for Pi runtime."""
import logging

from cota.executor.tools.base import Tool, create_tool_schema

logger = logging.getLogger(__name__)


class PolicyTool(Tool):
    """BM25 policy search returning structured guidance with labeled thoughts.

    Registered automatically when a Bot has a policy/ directory with POLICY.md.
    """

    def __init__(self, index):
        self._index = index

    @property
    def name(self):
        return 'policy_guidance'

    @property
    def internal(self):
        return True

    @property
    def description(self):
        return f'查阅业务策略指导。{self._index.manifest.description}'

    @property
    def parameters(self):
        return create_tool_schema(
            properties={'scenario': {'type': 'string', 'description': '当前业务场景描述或关键词'}},
            required=['scenario'],
        )

    async def execute(self, **kwargs):
        scenario = kwargs.get('scenario', '')
        if not scenario or not scenario.strip():
            return {'content': [{'type': 'text', 'text': '请提供业务场景描述。'}],
                    'details': {}, 'isError': True}

        try:
            result = self._index.search(scenario)
        except Exception as e:
            logger.error(f'Policy search failed: {e}')
            return {'content': [{'type': 'text', 'text': f'策略检索失败：{e}'}],
                    'details': {}, 'isError': True}

        if not result:
            return {'content': [{'type': 'text', 'text': '未找到相关业务策略。'}], 'details': {}}

        return {'content': [{'type': 'text', 'text': result}], 'details': {}}
