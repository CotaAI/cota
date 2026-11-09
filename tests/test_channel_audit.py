"""Regressions for connection lifecycle, bounded replay, and shell shutdown."""
import asyncio
import json
import os
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from cota.channels.queue import MessageBus
from cota.channels.web.transport import Connection, WebSocketTransport


class Socket:
    def __init__(self, *, slow=False):
        self.incoming = asyncio.Queue()
        self.incoming.put_nowait(json.dumps({'type': 'resume', 'token': 'token', 'session_id': 'room'}))
        self.frames = []
        self.sending = asyncio.Event()
        self.release = asyncio.Event()
        if not slow:
            self.release.set()
        self.closed = False

    async def recv(self):
        return await self.incoming.get()

    async def send(self, raw):
        if self.closed:
            raise ConnectionError('socket closed')
        self.sending.set()
        await self.release.wait()
        self.frames.append(json.loads(raw))

    async def close(self):
        self.closed = True
        self.incoming.put_nowait(None)


async def transport_for(**overrides):
    transport = WebSocketTransport({}, MessageBus())
    service = SimpleNamespace(authenticate=AsyncMock(return_value='alice'), authorize=AsyncMock(),
        history=AsyncMock(return_value={'messages': [], 'through': 0, 'has_more': False}),
        submit=AsyncMock(return_value={'status': 'queued'}))
    for name, value in overrides.items():
        setattr(service, name, value)
    transport.bind(service)
    await transport.start()
    return transport


async def eventually(predicate):
    async with asyncio.timeout(2):
        while not predicate():
            await asyncio.sleep(.001)


@pytest.mark.asyncio
async def test_slow_history_replay_does_not_block_live_peer_and_preserves_order():
    messages = [{'type': 'message', 'sequence': i} for i in range(1, 501)]
    transport = await transport_for(history=AsyncMock(return_value={
        'messages': messages, 'through': 500, 'has_more': False}))
    transport.service.application = SimpleNamespace(history=AsyncMock(return_value={
        'messages': [{'type': 'message', 'sequence': 501}], 'through': 501,
        'cursor': 501, 'has_more': False}))
    slow = Socket(slow=True)
    handler = asyncio.create_task(transport.handle(slow))
    fast = Connection(Socket())
    transport._connections['room'] = {fast}
    try:
        await slow.sending.wait()
        await asyncio.sleep(.02)  # Replay now fills its bounded output queue.
        live = {'type': 'message', 'sequence': 501}
        await asyncio.wait_for(transport.publish('room', live), .2)
        assert fast.queue.get_nowait() == live
        slow.release.set()
        await eventually(lambda: live in slow.frames)
        assert slow.frames == messages + [{'type': 'ready', 'session_id': 'room', 'cursor': 500}, live]
        transport.service.application.history.assert_awaited_once_with('room', after=500, until=501, limit=500)
    finally:
        handler.cancel()
        await asyncio.gather(handler, return_exceptions=True)
        await transport.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize('stage', ['authenticate', 'history'])
async def test_stop_cancels_handlers_blocked_before_replay_registration(stage):
    entered, release = asyncio.Event(), asyncio.Event()
    async def blocked(*args, **kwargs):
        entered.set()
        await release.wait()
        return 'alice' if stage == 'authenticate' else {'messages': [], 'through': 0, 'has_more': False}
    transport = await transport_for(**{stage: blocked})
    socket = Socket()
    handler = asyncio.create_task(transport.handle(socket))
    try:
        await entered.wait()
        await asyncio.wait_for(transport.stop(), .5)
        assert handler.done(), 'stop must own handlers before authentication/history finishes'
        release.set()
        await asyncio.sleep(0)
        assert not transport._connections
        assert socket.closed
    finally:
        handler.cancel()
        await asyncio.gather(handler, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize('error,code', [(RuntimeError('secret database password'), 'internal_error'),
                                      (PermissionError('secret auth endpoint'), 'unauthorized')])
@pytest.mark.parametrize('stage', ['authenticate', 'history'])
async def test_handshake_errors_never_expose_adapter_details(error, code, stage):
    async def fail(*args, **kwargs):
        await asyncio.sleep(0)
        raise error
    transport = await transport_for(**{stage: fail})
    socket = Socket()
    try:
        await transport.handle(socket)
        assert socket.frames and socket.frames[0]['code'] == code
        assert 'secret' not in json.dumps(socket.frames)
    finally:
        await transport.stop()


@pytest.mark.asyncio
async def test_submit_internal_error_is_sanitized_and_connection_survives():
    transport = await transport_for(submit=AsyncMock(side_effect=RuntimeError('secret database password')))
    socket = Socket()
    handler = asyncio.create_task(transport.handle(socket))
    try:
        await eventually(lambda: socket.frames)
        socket.incoming.put_nowait(json.dumps({'type': 'send', 'message_id': 'one', 'text': 'hi'}))
        await eventually(lambda: any(frame.get('type') == 'error' for frame in socket.frames))
        error = next(frame for frame in socket.frames if frame['type'] == 'error')
        assert error['code'] == 'internal_error'
        assert 'secret' not in json.dumps(socket.frames)
        assert not handler.done()
    finally:
        handler.cancel()
        await asyncio.gather(handler, return_exceptions=True)
        await transport.stop()


@pytest.mark.parametrize('partial_input', [b'', b'no newline yet'])
def test_cmdline_stop_exits_with_stdin_pipe_still_open(partial_input):
    script = '''
import asyncio
from cota.channels.cmdline import CmdlineChannel
from cota.channels.queue import MessageBus
async def main():
    channel = CmdlineChannel({}, MessageBus())
    await channel.start()
    await asyncio.sleep(.05)
    await channel.stop()
asyncio.run(main())
'''
    process = subprocess.Popen([sys.executable, '-c', script], stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        process.stdin.write(partial_input)
        process.stdin.flush()
        process.wait(timeout=5)
        assert process.returncode == 0, process.stderr.read().decode()
    except subprocess.TimeoutExpired:
        pytest.fail('Blocked stdin worker prevented asyncio.run/process shutdown')
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate()


@pytest.mark.asyncio
async def test_chat_state_inherits_each_agent_config_path_and_explicit_override(tmp_path, monkeypatch):
    from cota.store import MemoryStore
    from cota.webapp import create_app
    monkeypatch.chdir(tmp_path)
    def agent(path):
        return SimpleNamespace(name='Bot', dialogue={}, store=MemoryStore(), config_path=path)
    first = create_app(agent(tmp_path / 'first'))
    second = create_app(agent(tmp_path / 'second'))
    override = create_app(agent(tmp_path / 'ignored'), config_path=tmp_path / 'explicit')
    accesses = [app.ctx.web_service.access for app in (first, second, override)]
    assert [access.registry.path for access in accesses] == [
        tmp_path / name / '.cota' / 'chat.sqlite3' for name in ('first', 'second', 'explicit')]
    guest = await accesses[0].create_guest('Alice')
    assert await accesses[0].authenticate(guest['token']) == guest['user_id']
    with pytest.raises(PermissionError):
        await accesses[1].authenticate(guest['token'])
    assert not (tmp_path / '.cota').exists()
    assert not (tmp_path / 'ignored').exists()


@pytest.mark.asyncio
async def test_replay_live_buffer_is_bounded_and_overflow_disconnects_only_slow_peer():
    transport = await transport_for(history=AsyncMock(return_value={
        'messages': [{'type': 'message', 'sequence': i} for i in range(1, 501)],
        'through': 500, 'has_more': False}))
    slow = Socket(slow=True)
    handler = asyncio.create_task(transport.handle(slow))
    fast = Connection(Socket())
    transport._connections['room'] = {fast}
    try:
        await slow.sending.wait()
        slow_connection = next(c for c in transport._connections['room'] if c is not fast)
        for sequence in range(501, 631):
            frame = {'type': 'message', 'sequence': sequence}
            await asyncio.wait_for(transport.publish('room', frame), .2)
            assert fast.queue.get_nowait() == frame
        await eventually(handler.done)
        assert slow.closed
        assert slow_connection.pending.qsize() <= 128
        assert slow_connection.queue.qsize() <= 128
        assert transport._connections['room'] == {fast}
    finally:
        handler.cancel()
        await asyncio.gather(handler, return_exceptions=True)
        await transport.stop()


@pytest.mark.asyncio
async def test_publication_during_history_snapshot_and_pages_is_delivered_after_ready():
    transport = await transport_for()
    async def history(user, session, **kwargs):
        if kwargs['after'] == 0:
            await transport.publish('room', {'type': 'message', 'sequence': 2})
            return {'messages': [{'type': 'message', 'sequence': 1}], 'through': 2,
                    'cursor': 1, 'has_more': True}
        assert kwargs['until'] == 2
        await transport.publish('room', {'type': 'message', 'sequence': 3})
        return {'messages': [{'type': 'message', 'sequence': 2}], 'through': 2,
                'cursor': 2, 'has_more': False}
    transport.service.history = history
    transport.service.application = SimpleNamespace(history=AsyncMock(return_value={
        'messages': [{'type': 'message', 'sequence': 3}], 'through': 3,
        'cursor': 3, 'has_more': False}))
    socket = Socket()
    handler = asyncio.create_task(transport.handle(socket))
    try:
        await eventually(lambda: len(socket.frames) == 4)
        assert socket.frames == [
            {'type': 'message', 'sequence': 1}, {'type': 'message', 'sequence': 2},
            {'type': 'ready', 'session_id': 'room', 'cursor': 2},
            {'type': 'message', 'sequence': 3}]
        # The replay already delivered sequence 2; its delayed notification is
        # suppressed, and only the next durable prefix is queried.
        transport.service.application.history.assert_awaited_once_with('room', after=2, until=3, limit=500)
    finally:
        handler.cancel()
        await asyncio.gather(handler, return_exceptions=True)
        await transport.stop()


@pytest.mark.asyncio
async def test_stop_cancels_replay_and_sender_with_full_output_queue():
    transport = await transport_for(history=AsyncMock(return_value={
        'messages': [{'type': 'message', 'sequence': i} for i in range(1, 501)],
        'through': 500, 'has_more': False}))
    socket = Socket(slow=True)
    handler = asyncio.create_task(transport.handle(socket))
    try:
        await socket.sending.wait()
        connection = next(iter(transport._connections['room']))
        await eventually(connection.queue.full)
        await asyncio.wait_for(transport.stop(), .5)
        assert handler.done() and connection.sender.done()
        assert not transport._handlers and not transport._connections
        assert socket.closed
    finally:
        handler.cancel()
        await asyncio.gather(handler, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize('kind,code', [('ApplicationUnavailable', 'not_ready'), ('QueueFull', 'busy'),
                                     ('InputConflict', 'invalid_request'), ('RunInProgress', 'run_in_progress'),
                                     ('ValueError', 'invalid_request')])
async def test_submit_errors_have_stable_public_classification(kind, code):
    from cota.application import ApplicationUnavailable
    from cota.inputs import InputConflict
    from cota.runtime.pi_runtime import RunInProgress
    exceptions = {'ApplicationUnavailable': ApplicationUnavailable, 'QueueFull': asyncio.QueueFull,
                  'InputConflict': InputConflict, 'RunInProgress': RunInProgress, 'ValueError': ValueError}
    transport = await transport_for(submit=AsyncMock(side_effect=exceptions[kind]('known failure')))
    socket = Socket()
    handler = asyncio.create_task(transport.handle(socket))
    try:
        await eventually(lambda: socket.frames)
        socket.incoming.put_nowait(json.dumps({'type': 'send', 'message_id': 'one', 'text': 'hi'}))
        await eventually(lambda: any(frame.get('type') == 'error' for frame in socket.frames))
        error = next(frame for frame in socket.frames if frame['type'] == 'error')
        assert error['code'] == code
        assert error['message_id'] == 'one'
    finally:
        handler.cancel()
        await asyncio.gather(handler, return_exceptions=True)
        await transport.stop()


@pytest.mark.asyncio
async def test_cmdline_pipe_preserves_unicode_and_multiple_buffered_lines(monkeypatch):
    from cota.channels.cmdline import CmdlineChannel
    read_fd, write_fd = os.pipe()
    channel = CmdlineChannel({}, MessageBus())
    with os.fdopen(read_fd, encoding='utf-8') as stdin:
        monkeypatch.setattr(sys, 'stdin', stdin)
        try:
            os.write(write_fd, '你好\nsecond line\n'.encode('utf-8'))
            assert await asyncio.wait_for(channel._read_input(), .5) == '你好'
            assert await asyncio.wait_for(channel._read_input(), .5) == 'second line'
            os.write(write_fd, b'trailing without newline')
            os.close(write_fd)
            write_fd = None
            assert await asyncio.wait_for(channel._read_input(), .5) == 'trailing without newline'
            with pytest.raises(EOFError):
                await channel._read_input()
        finally:
            if write_fd is not None:
                os.close(write_fd)


@pytest.mark.asyncio
@pytest.mark.parametrize('disconnect', ['cancel', 'eof'])
async def test_stop_does_not_interrupt_handler_already_closing_socket(disconnect):
    class ClosingSocket(Socket):
        def __init__(self):
            super().__init__()
            self.closing = asyncio.Event()
            self.allow_close = asyncio.Event()

        async def close(self):
            self.closing.set()
            await self.allow_close.wait()
            await super().close()

    transport = await transport_for()
    socket = ClosingSocket()
    handler = asyncio.create_task(transport.handle(socket))
    stopping = None
    try:
        await eventually(lambda: bool(socket.frames))
        if disconnect == 'cancel':
            handler.cancel()
        else:
            socket.incoming.put_nowait(None)
        await asyncio.wait_for(socket.closing.wait(), .5)
        assert not transport._connections
        stopping = asyncio.create_task(transport.stop())
        await asyncio.sleep(0)
        socket.allow_close.set()
        await asyncio.wait_for(stopping, .5)
        assert socket.closed
        assert handler.done()
        assert not transport._handlers and not transport._connections
        assert not transport._closing_handlers
    finally:
        socket.allow_close.set()
        if stopping is not None:
            await asyncio.gather(stopping, return_exceptions=True)
        handler.cancel()
        await asyncio.gather(handler, return_exceptions=True)
