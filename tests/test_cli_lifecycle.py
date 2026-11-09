"""CLI resource handling, with no real tunnel process or network requests."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from cota import __main__ as cli


@pytest.mark.parametrize('cert,key', [('cert.pem', None), (None, 'key.pem')])
def test_partial_tls_configuration_is_rejected(cert, key):
    with pytest.raises(ValueError, match='together'):
        cli.create_server_config(SimpleNamespace(host='localhost', port=5005, debug=False,
                                                ssl_cert=cert, ssl_key=key))


async def test_tunnel_drains_output_after_url_and_reaps_process(monkeypatch):
    consumed = []
    async def output():
        for line in (b'https://demo.lhr.life\n', b'later output\n'):
            consumed.append(line)
            yield line
    process = SimpleNamespace(stdout=output(), returncode=None,
                              terminate=Mock(), wait=AsyncMock(), kill=Mock())
    monkeypatch.setattr(asyncio, 'create_subprocess_exec', AsyncMock(return_value=process))
    listeners = {}
    def listener(name):
        def register(fn):
            listeners[name] = fn
            return fn
        return register
    app = SimpleNamespace(ctx=SimpleNamespace(), listener=listener)
    cli._register_tunnel_listener(app, 5005)
    await listeners['after_server_start'](app, None)
    await asyncio.sleep(0)
    await listeners['after_server_stop'](app, None)
    assert len(consumed) == 2
    assert app.ctx.tunnel_url == 'https://demo.lhr.life'
    process.terminate.assert_called_once()
    process.wait.assert_awaited_once()
    assert app.ctx.tunnel_watcher.done()


async def test_tunnel_stop_kills_process_that_ignores_termination(monkeypatch):
    process = SimpleNamespace(returncode=None, terminate=Mock(), kill=Mock(),
                              wait=AsyncMock(side_effect=[TimeoutError, None]))
    listeners = {}
    app = SimpleNamespace(ctx=SimpleNamespace(tunnel_process=process),
        listener=lambda name: lambda fn: listeners.setdefault(name, fn))
    cli._register_tunnel_listener(app, 5005)
    await listeners['after_server_stop'](app, None)
    process.kill.assert_called_once()
    assert process.wait.await_count == 2
