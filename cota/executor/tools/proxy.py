"""Expose a tool-process capability through the same interface as a Python tool."""
from .base import Tool


class ProxyTool(Tool):
    """ToolRegistry owns the client lifecycle; this object only forwards calls."""

    def __init__(self, schema, client):
        self._schema = schema
        self._client = client

    @property
    def name(self):
        return self._schema['name']

    @property
    def description(self):
        return self._schema.get('description', '')

    @property
    def parameters(self):
        return self._schema['parameters']

    @property
    def category(self):
        return 'proxy'

    async def execute(self, **kwargs):
        return await self._client.execute_tool(self.name, kwargs)
