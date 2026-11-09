"""Stdio MCP transport; agent execution is handled by Pi Core."""
from __future__ import annotations

import logging

from .mcp_lifecycle import MCPSessionOwner
from typing import Dict, Optional, List

logger = logging.getLogger(__name__)

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False
    logger.warning(
        "MCP SDK not available. Please install it with: pip install mcp"
    )


class MCPClientWrapper:
    """MCP客户端包装类，管理MCP服务器连接和工具调用"""

    def __init__(self, server_params: StdioServerParameters):
        """
        初始化MCP客户端包装器

        Args:
            server_params: MCP服务器参数
        """
        self.server_params = server_params
        self._owner = MCPSessionOwner()

    async def ensure_connected(self) -> ClientSession:
        """Start and retain the transport and session in their owner task."""
        return await self._owner.start(
            lambda: stdio_client(self.server_params), ClientSession
        )

    async def list_tools(self) -> List[Dict]:
        """列出所有可用的工具"""
        session = await self.ensure_connected()
        try:
            result = await session.list_tools()
            tools = []
            for tool in result.tools:
                tools.append({
                    "name": tool.name,
                    "description": tool.description or "",
                    "inputSchema": tool.inputSchema if hasattr(tool, 'inputSchema') else {}
                })
            return tools
        except Exception as e:
            logger.error(f"获取工具列表失败: {e}")
            raise

    async def list_prompts(self) -> List[Dict]:
        """列出所有可用的prompts"""
        session = await self.ensure_connected()
        try:
            result = await session.list_prompts()
            prompts = []
            for prompt in result.prompts:
                prompts.append({
                    "name": prompt.name,
                    "description": prompt.description or "",
                    "arguments": prompt.arguments if hasattr(prompt, 'arguments') else []
                })
            return prompts
        except Exception as e:
            logger.error(f"获取prompts列表失败: {e}")
            raise

    async def call_tool(self, tool_name: str, arguments: Dict) -> Dict:
        """调用MCP工具"""
        session = await self.ensure_connected()
        try:
            result = await session.call_tool(tool_name, arguments)
            return {
                "content": result.content if hasattr(result, 'content') else [],
                "isError": result.isError if hasattr(result, 'isError') else False
            }
        except Exception as e:
            logger.error(f"调用工具 {tool_name} 失败: {e}")
            raise

    async def get_prompt(self, prompt_name: str, arguments: Optional[Dict] = None) -> Dict:
        """获取MCP prompt"""
        session = await self.ensure_connected()
        try:
            result = await session.get_prompt(prompt_name, arguments or {})
            return {
                "messages": result.messages if hasattr(result, 'messages') else [],
                "description": result.description if hasattr(result, 'description') else ""
            }
        except Exception as e:
            logger.error(f"获取prompt {prompt_name} 失败: {e}")
            raise

    async def close(self):
        """Close both contexts in the task which entered them."""
        await self._owner.close()
