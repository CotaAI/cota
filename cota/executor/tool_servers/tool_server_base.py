"""Base class for explicitly configured process tool servers.

A ToolServer runs in a deployment-selected Python environment and exposes tools
via JSON-RPC 2.0 over stdin/stdout. The main cota process communicates
with it through SubprocessToolClient.

The server implementation uses the Python standard library. Importing it via
the cota package requires Cota to be available in the chosen environment.
A standalone server may implement the same JSON-lines protocol without Cota.

Usage in a custom tool_server.py:

    from cota.executor.tool_servers.tool_server_base import BaseToolServer

    server = BaseToolServer()

    @server.tool(
        name="fetch_data",
        description="Fetch data from an API endpoint",
        parameters={
            "type": "object",
            "properties": {"url": {"type": "string", "description": "API endpoint URL"}},
            "required": ["url"]
        }
    )
    async def fetch_data(url: str):
        # ... your implementation ...
        return {"success": True, "data": "..."}

    if __name__ == "__main__":
        server.run()
"""

import sys
import json
import asyncio
import logging
import traceback
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class ToolDefinition:
    """Internal representation of a registered tool."""

    def __init__(
        self,
        name: str,
        description: str,
        parameters: Dict[str, Any],
        handler: Callable,
    ):
        self.name = name
        self.description = description
        self.parameters = parameters
        self.handler = handler
        self._is_async = asyncio.iscoroutinefunction(handler)

    def to_schema(self) -> Dict[str, Any]:
        """Convert to OpenAI-compatible tool schema."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }

    async def execute(self, **kwargs) -> Any:
        """Execute the handler."""
        if self._is_async:
            return await self.handler(**kwargs)
        else:
            return self.handler(**kwargs)


class BaseToolServer:
    """Base tool server that communicates via JSON-RPC 2.0 over stdin/stdout.

    Lifecycle:
    1. Main process sends {"method": "initialize"} → server returns tool schemas
    2. Main process sends {"method": "execute", "params": {"tool": ..., "arguments": ...}}
       → server executes and returns result
    3. Main process sends {"method": "shutdown"} → server cleans up and exits

    All log/debug output goes to stderr (never stdout, which is reserved for JSON-RPC).
    """

    def __init__(self):
        self._tools: Dict[str, ToolDefinition] = {}
        self._cleanup_handlers: List[Callable] = []
        self._cleanup_task = None
        self._running = False

    # =========================================================================
    # Tool registration
    # =========================================================================

    def tool(
        self,
        name: str,
        description: str,
        parameters: Dict[str, Any],
    ) -> Callable:
        """Decorator to register a tool handler.

        Args:
            name: Tool name (used in LLM function calls)
            description: Human-readable description
            parameters: JSON Schema for parameters

        Returns:
            Decorator function

        Example:
            @server.tool("my_tool", "Does something", {"type": "object", ...})
            async def my_tool(arg1: str):
                return {"result": arg1}
        """
        def decorator(func: Callable) -> Callable:
            self._tools[name] = ToolDefinition(
                name=name,
                description=description,
                parameters=parameters,
                handler=func,
            )
            return func
        return decorator

    def register_tool(
        self,
        name: str,
        description: str,
        parameters: Dict[str, Any],
        handler: Callable,
    ) -> None:
        """Register a tool handler directly (non-decorator style).

        Args:
            name: Tool name
            description: Human-readable description
            parameters: JSON Schema for parameters
            handler: The function to call
        """
        self._tools[name] = ToolDefinition(
            name=name,
            description=description,
            parameters=parameters,
            handler=handler,
        )

    def on_cleanup(self, handler: Callable) -> None:
        """Register a cleanup handler called on shutdown.

        Args:
            handler: Async or sync function to call during shutdown
        """
        self._cleanup_handlers.append(handler)

    # =========================================================================
    # JSON-RPC message I/O (sync, via stdin/stdout)
    # =========================================================================

    @staticmethod
    def _read_message() -> Optional[Dict[str, Any]]:
        """Read one JSON-RPC message from stdin.

        Returns:
            Parsed message dict, or None on EOF
        """
        try:
            line = sys.stdin.readline()
        except (EOFError, KeyboardInterrupt):
            return None

        if not line:
            return None

        try:
            return json.loads(line.strip())
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON from stdin: {e}")
            return None

    @staticmethod
    def _write_message(msg: Dict[str, Any]) -> None:
        """Write one JSON-RPC message to stdout."""
        sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
        sys.stdout.flush()

    def _send_result(self, result: Any, id: int) -> None:
        """Send a successful JSON-RPC response."""
        self._write_message({
            "jsonrpc": "2.0",
            "result": result,
            "id": id,
        })

    def _send_error(self, code: int, message: str, id: Optional[int] = None) -> None:
        """Send an error JSON-RPC response."""
        msg: Dict[str, Any] = {
            "jsonrpc": "2.0",
            "error": {"code": code, "message": message},
        }
        if id is not None:
            msg["id"] = id
        self._write_message(msg)

    # =========================================================================
    # Request dispatch
    # =========================================================================

    async def _handle_initialize(self, id: int) -> None:
        """Handle the 'initialize' request — return tool schemas."""
        schemas = [t.to_schema() for t in self._tools.values()]
        self._send_result({"tools": schemas}, id)

    async def _handle_execute(self, params: Dict[str, Any], id: int) -> None:
        """Handle the 'execute' request — run a tool and return result."""
        tool_name = params.get("tool", "")
        arguments = params.get("arguments", {})

        tool = self._tools.get(tool_name)
        if not tool:
            self._send_error(
                -32601,
                f"Unknown tool: {tool_name}",
                id,
            )
            return

        try:
            result = await tool.execute(**arguments)
            self._send_result(result, id)
        except Exception as e:
            logger.error(f"Tool {tool_name} failed: {e}\n{traceback.format_exc()}")
            self._send_result(
                {"success": False, "error": str(e)},
                id,
            )

    async def _cleanup_once(self) -> None:
        """Release server resources once, on every exit path."""
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(self._cleanup())
        await asyncio.shield(self._cleanup_task)

    async def _cleanup(self) -> None:
        for handler in self._cleanup_handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler()
                else:
                    handler()
            except Exception as e:
                logger.error(f"Cleanup handler failed: {e}")

    async def _handle_shutdown(self, id: int) -> None:
        """Handle the shutdown request after releasing resources."""
        await self._cleanup_once()
        self._send_result({"ok": True}, id)
        self._running = False

    async def _dispatch(self, msg: Dict[str, Any]) -> None:
        """Dispatch a single JSON-RPC request."""
        method = msg.get("method", "")
        params = msg.get("params", {})
        msg_id = msg.get("id")

        if method == "initialize":
            await self._handle_initialize(msg_id)
        elif method == "execute":
            await self._handle_execute(params, msg_id)
        elif method == "shutdown":
            await self._handle_shutdown(msg_id)
        else:
            self._send_error(-32601, f"Unknown method: {method}", msg_id)

    # =========================================================================
    # Main loop
    # =========================================================================

    async def _run_async(self) -> None:
        """Async main loop: read stdin, dispatch, repeat."""
        self._running = True
        logger.info(
            f"ToolServer started with {len(self._tools)} tools: "
            f"{list(self._tools.keys())}"
        )

        try:
            while self._running:
                msg = await asyncio.get_event_loop().run_in_executor(
                    None, self._read_message
                )
                if msg is None:
                    logger.info("ToolServer received EOF, shutting down")
                    break
                await self._dispatch(msg)

        finally:
            self._running = False
            await self._cleanup_once()
            logger.info("ToolServer stopped")

    def run(self) -> None:
        """Start the tool server main loop (blocking).

        This is the entry point for skill tool_server.py scripts.
        It reads JSON-RPC messages from stdin and writes responses to stdout.
        All logging goes to stderr.

        Example:
            server = BaseToolServer()
            # ... register tools ...
            server.run()
        """
        # Configure logging to stderr (stdout is for JSON-RPC only)
        logging.basicConfig(
            stream=sys.stderr,
            level=logging.INFO,
            format="[ToolServer] %(levelname)s %(message)s",
        )

        try:
            asyncio.run(self._run_async())
        except KeyboardInterrupt:
            logger.info("ToolServer interrupted")
        except Exception as e:
            logger.error(f"ToolServer crashed: {e}\n{traceback.format_exc()}")
            sys.exit(1)
