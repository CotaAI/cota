"""Tool registry and loader for PiAgentRuntime.

Optional Python/process adapters only. Shipped HTTP is a Pi AgentTool.
Access policy also applies to that externally defined tool.
"""

import logging
import asyncio
from typing import Dict, Optional, List, Set
import re

from .base import Tool
from cota.executor.environment import NATIVE_TOOLS

logger = logging.getLogger(__name__)


# =============================================================================
# Tool groups for optional adapters and the HTTP package
# =============================================================================

TOOL_GROUPS: Dict[str, List[str]] = {
    "group:network": ["http_request"],
    "group:all": [],
}

def _expand_groups(names: List[str]) -> Set[str]:
    """Expand group references in a list of names.

    E.g., ["group:network", "lookup"] -> {"http_request", "lookup"}
    """
    result = set()
    for name in names:
        if name.startswith("group:"):
            if name not in TOOL_GROUPS:
                raise ValueError(f'Unknown tool group: {name}')
            group_tools = TOOL_GROUPS[name]
            result.update(group_tools)
        else:
            result.add(name)
    return result


# =============================================================================
# Tool Policy
# =============================================================================

class ToolPolicy:
    """Tool access policy using allow/deny lists.

    - deny wins over allow
    - Supports group shortcuts (e.g., "group:network")
    - None allow = allow all

    Example:
        # Allow only network tools
        policy = ToolPolicy(allow=["group:network"])

        # Disable HTTP
        policy = ToolPolicy(deny=["http_request"])

        # Permit HTTP only
        policy = ToolPolicy(allow=["http_request"])
    """

    def __init__(
        self,
        allow: Optional[List[str]] = None,
        deny: Optional[List[str]] = None
    ):
        # group:all must also cover tools registered after policy construction.
        self.allow_all = allow is not None and 'group:all' in allow
        self.deny_all = deny is not None and 'group:all' in deny
        self.allow = _expand_groups(allow) if allow is not None else None
        self.deny = _expand_groups(deny) if deny else set()

    def is_allowed(self, tool: "Tool") -> bool:
        """Check if a tool is allowed by this policy.

        Args:
            tool: Python tool instance or the name of a Pi tool
        """
        tool_name = tool if isinstance(tool, str) else tool.name

        # Deny wins
        if self.deny_all or tool_name in self.deny:
            return False

        # If allow is set, tool must be in allow list
        if self.allow is not None and not self.allow_all:
            return tool_name in self.allow

        return True


# =============================================================================
# Tool Registry
# =============================================================================

class ToolRegistry:
    """Registry for managing tools.

    Example:
        registry = ToolRegistry()
        registry.set_policy(ToolPolicy(deny=["http_request"]))
        tools = registry.get_allowed_tools()
    """

    def __init__(self):
        self._tools: Dict[str, Tool] = {}
        self._policy: Optional[ToolPolicy] = None
        self._process_tools = {}
        self._process_lock = asyncio.Lock()

    def register(self, tool: Tool) -> None:
        """Register an application tool without replacing any existing capability."""
        self._check_registration(tool.name, tool.parameters)
        self._tools[tool.name] = tool
        logger.debug(f"Registered tool: {tool.name}")

    def _check_registration(self, name, parameters):
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', name):
            raise ValueError('Invalid tool name')
        if name in NATIVE_TOOLS | {'http_request'}:
            raise ValueError(f'Tool name {name} is reserved for Pi tools')
        if name in self._tools:
            raise ValueError(f'Tool {name} is already registered')
        if not isinstance(parameters, dict):
            raise ValueError(f'Tool {name} must provide a parameter schema')

    def validate(self):
        """Check references after application setup, before starting a model run."""
        if self._policy is not None:
            referenced = (self._policy.allow or set()) | self._policy.deny
            unknown = referenced - (self._tools.keys() | {'http_request'})
            if unknown:
                raise ValueError(f'Unknown configured tools: {", ".join(sorted(unknown))}')

    def get(self, name: str) -> Optional[Tool]:
        """Get tool by name."""
        return self._tools.get(name)

    def list_tools(self) -> List[Tool]:
        """List all tools."""
        return list(self._tools.values())

    def list_tool_names(self) -> List[str]:
        """List all tool names."""
        return list(self._tools.keys())

    def set_policy(self, policy: ToolPolicy) -> None:
        """Set access policy."""
        self._policy = policy

    def is_allowed(self, name: str) -> bool:
        """Apply the same policy to Pi tools supplied outside the Python registry."""
        return self._policy is None or self._policy.is_allowed(name)

    def get_allowed_tools(self) -> List[Tool]:
        """Get enabled tools allowed by the Bot policy, independent of Skill reads."""
        tools = self.list_tools()
        if self._policy:
            tools = [t for t in tools if self._policy.is_allowed(t)]
        tools = [t for t in tools if t.enabled]
        return tools

    async def connect_process(self, client) -> List[str]:
        """Register an explicit tool server during Bot setup and own its shutdown.

        Remote tools follow normal ToolPolicy and cannot replace existing tools.
        """
        async with self._process_lock:
            return await self._connect_process(client)

    async def _connect_process(self, client):
        from .proxy import ProxyTool
        if client._registry_owner is not None:
            raise ValueError('Tool process is already registered')
        # Claim before the first await, including across different registries.
        client._registry_owner = self
        try:
            schemas = await client.start()
            tools, names = [], set()
            for schema in schemas:
                name = schema.get('name') if isinstance(schema, dict) else None
                self._check_registration(name, schema.get('parameters') if isinstance(schema, dict) else None)
                if name in names:
                    raise ValueError(f'Tool {name} is already registered')
                names.add(name)
                tools.append(ProxyTool(schema, client))
            # No await between validation and registration: no partial exposure.
            for tool in tools:
                self.register(tool)
            self._process_tools[client] = tools
            return [tool.name for tool in tools]
        except BaseException:
            try:
                await client.shutdown()
            finally:
                client._registry_owner = None
            raise

    async def disconnect_process(self, client) -> None:
        """Remove only this process's tools, allowing an explicit replacement."""
        async with self._process_lock:
            await self._disconnect_process(client)

    async def _disconnect_process(self, client):
        if client not in self._process_tools:
            return
        try:
            await client.shutdown()
        finally:
            for tool in self._process_tools.pop(client):
                if self._tools.get(tool.name) is tool:
                    self._tools.pop(tool.name)
            client._registry_owner = None

    async def cleanup(self) -> None:
        """Cleanup all tools."""
        for tool in list(self._tools.values()):
            try:
                await tool.cleanup()
            except Exception as e:
                logger.error(f"Error cleaning up tool {tool.name}: {e}")
        async with self._process_lock:
            for client in list(self._process_tools):
                try:
                    await self._disconnect_process(client)
                except Exception:
                    logger.exception('Error closing tool process')
