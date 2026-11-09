"""Shell owns debug lifetime; failures must not prevent message processing."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from cota.channels.cmdline import CmdlineChannel
from cota.channels.queue import MessageBus
from cota.channels.events import InboundMessage
from cota.dst import DST
from cota.store import MemoryStore


@pytest.mark.asyncio
@pytest.mark.parametrize('exit_input', ['/stop', None])
async def test_channel_exit_is_awaitable_not_system_exit(monkeypatch, exit_input):
    def read():
        if exit_input is None:
            raise EOFError()
        return exit_input
    monkeypatch.setattr('builtins.input', read)
    bus = MessageBus()
    channel = CmdlineChannel({}, bus)
    assert channel.session_key.startswith('cmdline:')
    await channel.start()
    await asyncio.wait_for(channel.wait_closed(), 2)
    assert not channel._running
    await channel.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize('debug,failure', [(False, False), (True, False), (True, True)])
async def test_shell_debug_lifecycle_and_failure_isolation(monkeypatch, tmp_path, debug, failure):
    from cota import __main__ as cli
    from cota.debug.server import DebugServer
    processed = asyncio.Event()
    state = {}
    class Channel:
        session_key = 'cmdline:test'
        def __init__(self, config, bus, debug):
            self.bus = bus
        async def start(self):
            await self.bus.publish_inbound(InboundMessage('cmdline', 'u', 'test', 'hello'))
        async def wait_closed(self):
            await asyncio.wait_for(processed.wait(), 2)
        async def stop(self):
            state['channel_closed'] = True
        async def send(self, msg):
            pass
        def flush_output(self):
            pass
    agent = SimpleNamespace(store=MemoryStore(), workspace_path=str(tmp_path), name='test', cleanup=AsyncMock())
    processor = SimpleNamespace(dst=None)
    async def handle(message):
        processor.dst = DST(message.session_key, None)
        if debug and not failure:
            assert state['inspector'].live_tracker() is processor.dst
        processed.set()
    processor.handle_inbound_message = handle
    agent.create_processor = Mock(return_value=processor)
    async def start(viewer):
        state['inspector'] = viewer.inspector
        if failure:
            raise OSError('bind failed')
        return 'http://127.0.0.1:1234/debug/'
    async def close(viewer):
        state['debug_closed'] = True
    monkeypatch.setattr(cli.Agent, 'load_from_path', Mock(return_value=agent))
    monkeypatch.setattr(cli.cmdline, 'Cmdline', Channel)
    monkeypatch.setattr(cli, '_start_scheduler', AsyncMock(return_value=None))
    monkeypatch.setattr(DebugServer, 'start', start)
    monkeypatch.setattr(DebugServer, 'close', close)
    await asyncio.wait_for(cli.shell(SimpleNamespace(config=str(tmp_path), debug=debug)), 3)
    assert processed.is_set() and state['channel_closed']
    assert state.get('debug_closed', False) == debug
    assert ('inspector' in state) == debug
    agent.cleanup.assert_awaited_once()


def test_debug_does_not_override_explicit_console_log_level(monkeypatch):
    from cota import __main__ as cli
    monkeypatch.setattr(cli, 'shell', AsyncMock())
    logging = Mock()
    monkeypatch.setattr(cli, 'configure_logging', logging)
    args = cli.create_argument_parser().parse_args(['shell', '--debug', '--log', 'WARNING'])
    args.func(args)
    import logging as standard_logging
    logging.assert_called_once_with(standard_logging.WARNING)


@pytest.mark.asyncio
async def test_shell_rejects_group_before_opening_terminal(monkeypatch):
    from cota import __main__ as cli
    agent = SimpleNamespace(dialogue={'mode': 'group'}, cleanup=AsyncMock())
    monkeypatch.setattr(cli.Agent, 'load_from_path', lambda **kwargs: agent)
    monkeypatch.setattr(cli, 'configure_execution_logging', lambda *args: None)
    def unexpected_channel(**kwargs):
        raise AssertionError('Group shell must be rejected before opening input')
    monkeypatch.setattr(cli.cmdline, 'Cmdline', unexpected_channel)
    with pytest.raises(ValueError, match='direct'):
        await cli.shell(SimpleNamespace(config='.', debug=False))
    agent.cleanup.assert_awaited_once()
