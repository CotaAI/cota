"""Thin Python-callable adapters for Pi; no built-in tools or execution loop."""

import logging
import asyncio
from copy import copy
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List, Callable

logger = logging.getLogger(__name__)


def create_tool_schema(
    properties: Dict[str, Any],
    required: Optional[List[str]] = None,
    description: Optional[str] = None
) -> Dict[str, Any]:
    """Create OpenAI-compatible JSON Schema for tool parameters.
    
    Args:
        properties: Dict of parameter definitions
        required: List of required parameter names
        description: Optional schema description
        
    Returns:
        JSON Schema dict
    """
    schema = {
        "type": "object",
        "properties": properties,
        "required": required or []
    }
    if description:
        schema["description"] = description
    return schema


class Tool(ABC):
    """Adapter for explicitly registered Python callables.
    
    Tools are the building blocks that LLM can use to interact with
    the external world. Each tool should:
    1. Have a clear, specific purpose
    2. Define its parameters using JSON Schema
    3. Handle errors gracefully
    4. Return structured results
    
    Example:
        class MyTool(Tool):
            @property
            def name(self) -> str:
                return "my_tool"
            
            @property
            def description(self) -> str:
                return "Does something useful"
            
            @property
            def parameters(self) -> Dict[str, Any]:
                return create_tool_schema(
                    properties={"input": {"type": "string"}},
                    required=["input"]
                )
            
            async def execute(self, **kwargs) -> Dict[str, Any]:
                return {"content": [{"type": "text", "text": "done"}], "details": {}}
    """
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Unique tool name (used in LLM function calls)."""
        pass
    
    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description for LLM to understand the tool's purpose."""
        pass
    
    @property
    @abstractmethod
    def parameters(self) -> Dict[str, Any]:
        """JSON Schema defining the tool's parameters."""
        pass
    
    @property
    def category(self) -> str:
        """Tool category for grouping (core, web, browser, etc.)."""
        return "general"
    
    @property
    def enabled(self) -> bool:
        """Whether this tool is enabled by default."""
        return True

    _service_mode: bool = False

    def bind_service_mode(self, enabled: bool) -> None:
        """Enable or disable service mode for this tool.

        In service mode, tools must reject operations that could expose
        server-local resources (file paths, shell commands, etc.).
        """
        self._service_mode = enabled

    def for_execution(self, user_id: Optional[str], service_mode: bool = False) -> "Tool":
        """Bind a private tool view; clients and resource ownership stay shared."""
        bound = copy(self)
        if hasattr(bound, "bind_user"):
            bound.bind_user(user_id)
        bound.bind_service_mode(service_mode)
        return bound

    @property
    def requires(self) -> List[str]:
        """List of required dependencies (for documentation)."""
        return []
    
    @abstractmethod
    async def execute(self, **kwargs) -> Any:
        """Execute the tool with given parameters.
        
        Args:
            **kwargs: Parameters as defined in the parameters schema
            
        Returns:
            Pi result (content/details/isError) or JSON-serializable application data
        """
        pass
    
    async def cleanup(self) -> None:
        """Clean up any resources held by the tool."""
        pass
    
    def to_openai_schema(self) -> Dict[str, Any]:
        """Convert to OpenAI function calling format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters
            }
        }
    
    def __repr__(self) -> str:
        return f"<Tool {self.name}>"


class ToolWrapper:
    """Wraps a Tool instance for use with PiAgentRuntime.
    
    Handles async/sync execution and result normalization.
    """
    
    def __init__(self, tool: Tool):
        self.tool = tool
    
    @property
    def name(self) -> str:
        return self.tool.name
    
    @property
    def description(self) -> str:
        return self.tool.description
    
    @property
    def parameters(self) -> Dict[str, Any]:
        return self.tool.parameters
    
    async def __call__(self, **kwargs) -> Any:
        """Execute a tool, preserving native values for the execution record.

        Native Pi result objects pass through. Application data is serialized
        by the runtime; this adapter defines no separate result protocol.
        """
        try:
            result = await self.tool.execute(**kwargs)
            
            return result
                
        except Exception as e:
            logger.error(f"Tool {self.name} execution failed: {e}")
            return {"content": [{"type": "text", "text": str(e)}], "details": {}, "isError": True}


class FunctionTool(Tool):
    """Create a tool from a simple function.
    
    Useful for quick tool creation without subclassing.
    
    Example:
        async def my_handler(x: int, y: int) -> Dict:
            return {"sum": x + y}
        
        tool = FunctionTool(
            name="add",
            description="Add two numbers",
            parameters=create_tool_schema(
                properties={
                    "x": {"type": "integer"},
                    "y": {"type": "integer"}
                },
                required=["x", "y"]
            ),
            handler=my_handler
        )
    """
    
    def __init__(
        self,
        name: str,
        description: str,
        parameters: Dict[str, Any],
        handler: Callable,
        category: str = "general"
    ):
        self._name = name
        self._description = description
        self._parameters = parameters
        self._handler = handler
        self._category = category
    
    @property
    def name(self) -> str:
        return self._name
    
    @property
    def description(self) -> str:
        return self._description
    
    @property
    def parameters(self) -> Dict[str, Any]:
        return self._parameters
    
    @property
    def category(self) -> str:
        return self._category
    
    async def execute(self, **kwargs) -> Any:
        if asyncio.iscoroutinefunction(self._handler):
            return await self._handler(**kwargs)
        else:
            return self._handler(**kwargs)
