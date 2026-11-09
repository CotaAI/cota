import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import anyio
import pytest

from cota.executor.mcp import MCPClientWrapper
from cota.executor.mcp_pool import MCPConnectionPool
from cota.executor.mcp_remote import RemoteMCPClient


@pytest.fixture(params=["stdio", "remote"])
def client(request, monkeypatch):
    module = (
        "cota.executor.mcp" if request.param == "stdio" else "cota.executor.mcp_remote"
    )
    state = SimpleNamespace(
        entered=False, closed=False, transport_closed=False, fail=False, block=False
    )

    @asynccontextmanager
    async def transport(*args, **kwargs):
        async with anyio.create_task_group():
            try:
                yield (None, None)
            finally:
                state.transport_closed = True

    class Session:
        def __init__(self, *args):
            pass

        async def __aenter__(self):
            self.task = asyncio.current_task()
            state.entered = True
            return self

        async def __aexit__(self, *args):
            assert asyncio.current_task() is self.task
            state.closed = True

        async def initialize(self):
            assert state.entered, "ClientSession context must start receive loop"
            if state.fail:
                raise ValueError("initialization failed")
            if state.block:
                await asyncio.Event().wait()

        async def call_tool(self, *args):
            return SimpleNamespace(
                content=[SimpleNamespace(text="hello")], isError=False
            )

    monkeypatch.setattr(module + ".ClientSession", Session)
    monkeypatch.setattr(
        module + (".stdio_client" if request.param == "stdio" else ".sse_client"),
        transport,
    )
    instance = (
        MCPClientWrapper(None)
        if request.param == "stdio"
        else RemoteMCPClient("http://device.local")
    )
    return instance, state


async def connect(client):
    if isinstance(client, MCPClientWrapper):
        await client.ensure_connected()
    else:
        await client.connect()


async def test_session_context_and_transport_share_lifetime_owner(client):
    instance, state = client
    await asyncio.create_task(connect(instance))
    assert state.entered and not state.closed
    await asyncio.create_task(instance.close())
    assert state.closed and state.transport_closed


async def test_failed_initialization_closes_session_and_transport(client):
    instance, state = client
    state.fail = True
    with pytest.raises(ValueError, match="initialization failed"):
        await connect(instance)
    assert state.closed and state.transport_closed


async def test_cancelled_connection_cleans_up(client):
    instance, state = client
    state.block = True
    task = asyncio.create_task(connect(instance))
    for _ in range(20):
        await asyncio.sleep(0)
        if state.entered:
            break
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert state.closed and state.transport_closed


async def test_remote_text_content_uses_text(client):
    instance, _state = client
    if not isinstance(instance, RemoteMCPClient):
        return
    try:
        assert (await instance.call_tool("hello", {}))["content"] == ["hello"]
    finally:
        await instance.close()


async def test_pool_reconnects_when_credentials_rotate(monkeypatch):
    class Client:
        def __init__(self, endpoint_url, auth_token):
            self.endpoint_url, self.auth_token = endpoint_url, auth_token
            self.connected = False
            self.last_used = 0

        async def connect(self):
            self.connected = True

        async def close(self):
            self.connected = False

    monkeypatch.setattr("cota.executor.mcp_pool.RemoteMCPClient", Client)
    pool = MCPConnectionPool()
    first = await pool.get_or_create("alice", "http://device", "old")
    second = await pool.get_or_create("alice", "http://device", "new")
    assert second is not first
    assert not first.connected
    await pool.close_all()


async def test_real_sdk_stdio_receive_loop_and_cross_task_close(tmp_path):
    import sys

    from mcp import StdioServerParameters

    server = tmp_path / "server.py"
    server.write_text(
        'from mcp.server.fastmcp import FastMCP\nm=FastMCP("test")\n@m.tool()\ndef hello() -> str:\n    return "hello"\nm.run(transport="stdio")\n'
    )
    instance = MCPClientWrapper(
        StdioServerParameters(command=sys.executable, args=[str(server)])
    )
    try:
        tools = await asyncio.wait_for(asyncio.create_task(instance.list_tools()), 10)
        assert [tool["name"] for tool in tools] == ["hello"]
        result = await asyncio.wait_for(instance.call_tool("hello", {}), 5)
        assert result["content"][0].text == "hello"
    finally:
        await asyncio.wait_for(asyncio.create_task(instance.close()), 5)
