"""Remote MCP Client — connect to user devices via SSE transport.

Unlike MCPClientWrapper (stdio, local subprocess), this connects to a
remote MCP Server running on the user's own device over HTTP/SSE.

Key differences from mcp.py MCPClientWrapper:
  - Transport: SSE (HTTP) instead of stdio
  - Lifecycle: managed by MCPConnectionPool, not by a single executor
  - Auth: optional bearer token per user
"""

import logging

from .mcp_lifecycle import MCPSessionOwner
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    from mcp import ClientSession
    from mcp.client.sse import sse_client
    MCP_SSE_AVAILABLE = True
except ImportError:
    MCP_SSE_AVAILABLE = False
    logger.debug("MCP SSE client not available (uv pip install mcp)")


class RemoteMCPClient:
    """Connect to a remote MCP Server via SSE transport.

    Usage::

        client = RemoteMCPClient("https://device.example.com:8080/mcp")
        await client.connect()
        tools = await client.list_tools()
        result = await client.call_tool("open_browser", {"url": "..."})
        await client.close()
    """

    def __init__(
        self,
        endpoint_url: str,
        auth_token: Optional[str] = None,
        timeout: float = 10,
        sse_read_timeout: float = 300,
    ) -> None:
        if not MCP_SSE_AVAILABLE:
            raise ImportError(
                "MCP SSE client is required. Install with: uv pip install mcp (or pip install mcp)"
            )
        self.endpoint_url = endpoint_url
        self.auth_token = auth_token
        self.timeout = timeout
        self.sse_read_timeout = sse_read_timeout

        self._owner = MCPSessionOwner()
        self.last_used: float = time.monotonic()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Establish transport and session contexts under one lifetime owner."""
        headers = {"Authorization": f"Bearer {self.auth_token}"} if self.auth_token else None
        await self._owner.start(
            lambda: sse_client(
                url=self.endpoint_url, headers=headers, timeout=self.timeout,
                sse_read_timeout=self.sse_read_timeout,
            ),
            ClientSession,
        )
        self.last_used = time.monotonic()

    async def close(self) -> None:
        await self._owner.close()

    @property
    def connected(self) -> bool:
        return self._owner.connected

    async def _ensure_connected(self) -> ClientSession:
        await self.connect()
        return self._owner.session

    async def list_tools(self) -> List[Dict[str, Any]]:
        """List tools exposed by the remote MCP Server."""
        session = await self._ensure_connected()
        result = await session.list_tools()
        tools = []
        for tool in result.tools:
            tools.append({
                "name": tool.name,
                "description": tool.description or "",
                "inputSchema": tool.inputSchema if hasattr(tool, "inputSchema") else {},
            })
        return tools

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Call a tool on the remote MCP Server."""
        session = await self._ensure_connected()
        result = await session.call_tool(tool_name, arguments)

        # Normalise content to list of text strings
        content_items = result.content if hasattr(result, "content") else []
        texts = []
        for item in content_items:
            if isinstance(item, dict):
                texts.append(item.get("text", str(item)))
            else:
                texts.append(getattr(item, "text", str(item)))

        return {
            "content": texts,
            "isError": getattr(result, "isError", False),
        }
