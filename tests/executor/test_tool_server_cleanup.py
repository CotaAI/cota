"""All tool-server exit paths release resources exactly once."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from cota.executor.tool_servers.tool_server_base import BaseToolServer


@pytest.mark.parametrize("reason", ["eof", "shutdown", "failure", "cancel"])
async def test_server_exit_runs_cleanup_once(monkeypatch, reason):
    cleanup = AsyncMock()
    entered = asyncio.Event()

    async def block(*args):
        entered.set()
        await asyncio.Event().wait()

    messages = iter([{"method": "execute", "params": {"tool": "block"}, "id": 1}, None])

    def read():
        if reason == "eof":
            return None
        if reason == "shutdown":
            return {"method": "shutdown", "id": 1}
        if reason == "failure":
            raise RuntimeError("input failed")
        return next(messages)

    server = BaseToolServer()
    server.on_cleanup(cleanup)
    server.register_tool("block", "", {}, block)
    monkeypatch.setattr(server, "_read_message", read)
    monkeypatch.setattr(server, "_write_message", lambda message: None)
    run = server._run_async()
    task = asyncio.create_task(run)
    if reason == "cancel":
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    elif reason == "failure":
        with pytest.raises(RuntimeError, match="input failed"):
            await task
    else:
        await task
    cleanup.assert_awaited_once()


async def test_cancel_during_shutdown_still_finishes_all_cleanup(
    monkeypatch
):
    entered, release = asyncio.Event(), asyncio.Event()
    first_calls = 0

    async def first():
        nonlocal first_calls
        first_calls += 1
        entered.set()
        await release.wait()

    second = AsyncMock()
    server = BaseToolServer()
    server.on_cleanup(first)
    server.on_cleanup(second)
    monkeypatch.setattr(
        server, "_read_message", lambda: {"method": "shutdown", "id": 1}
    )
    monkeypatch.setattr(server, "_write_message", lambda msg: None)
    run = server._run_async()
    task = asyncio.create_task(run)
    await entered.wait()
    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert first_calls == 1
    second.assert_awaited_once()
