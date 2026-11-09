import pytest

from cota.executor.tool_servers.tool_server_base import BaseToolServer


@pytest.mark.parametrize("value", [[1, False, None], False, None, 7])
async def test_tool_server_preserves_json_types(value, monkeypatch):
    server = BaseToolServer()
    server.register_tool("value", "", {}, lambda: value)
    sent = []
    monkeypatch.setattr(server, "_write_message", sent.append)
    await server._handle_execute({"tool": "value"}, 1)
    assert sent[0]["result"] == value
