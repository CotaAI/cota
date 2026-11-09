"""Mounted Web adapter contracts; end-to-end sockets live in test_web_app_integration."""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from cota.channels.events import OutboundMessage
from cota.channels.queue import MessageBus
from cota.channels.web.base import WebChannel
from cota.channels.web.transport import Connection, TransportFactory, WebSocketTransport
from cota.dst import DST
from cota.events import BotUtterEvent
from cota.store import MemoryStore


@pytest.mark.parametrize('kind', ['sse', 'socketio', 'unknown'])
def test_unimplemented_transports_are_explicit(kind):
    with pytest.raises(ValueError, match='websocket'):
        TransportFactory.create(kind, {}, MessageBus())


@pytest.mark.asyncio
async def test_mounted_lifecycle_requires_service():
    channel = WebChannel({}, MessageBus())
    with pytest.raises(RuntimeError, match='mounted'):
        await channel.start()
    service = SimpleNamespace()
    channel.get_transport().bind(service)
    await channel.start()
    assert channel.is_running
    assert service.transport is channel.get_transport()
    await channel.stop()
    assert not channel.is_running


@pytest.mark.asyncio
async def test_live_reply_uses_committed_event_not_untrusted_outbound_text():
    store = MemoryStore()
    dst = DST('session', agent=None)
    dst.append_event(BotUtterEvent(text='persisted'))
    await store.save(dst)
    event = dst.events[-1]
    transport = WebSocketTransport({}, MessageBus())
    transport.bind(SimpleNamespace(store=store))
    socket = SimpleNamespace(send=AsyncMock(), close=AsyncMock())
    connection = Connection(socket)
    transport._connections['session'] = {connection}
    await transport.send(OutboundMessage('web', 'session', 'changed', event_id=event.event_id,
                                        sequence=event.sequence, session_id='session'))
    frame = connection.queue.get_nowait()
    assert frame['text'] == 'persisted'
    assert frame['event_id'] == event.event_id
    with pytest.raises(ValueError, match='committed'):
        await transport.send(OutboundMessage('web', 'session', 'uncommitted'))


@pytest.mark.asyncio
async def test_slow_connection_does_not_stall_other_connection():
    transport = WebSocketTransport({}, MessageBus())
    slow = Connection(SimpleNamespace(close=AsyncMock()), queue=asyncio.Queue(maxsize=1))
    slow.sender = asyncio.create_task(asyncio.sleep(30))
    fast = Connection(SimpleNamespace(close=AsyncMock()))
    slow.queue.put_nowait({'old': True})
    transport._connections['session'] = {slow, fast}
    await asyncio.wait_for(transport.publish('session', {'type':'message'}), .1)
    assert fast.queue.get_nowait() == {'type':'message'}
    assert slow not in transport._connections['session']
    await asyncio.gather(slow.sender, return_exceptions=True)


@pytest.mark.asyncio
async def test_unauthorized_resume_never_registers_connection():
    transport = WebSocketTransport({}, MessageBus())
    transport.bind(SimpleNamespace(authenticate=AsyncMock(side_effect=PermissionError('invalid'))))
    await transport.start()
    socket = SimpleNamespace(recv=AsyncMock(return_value=json.dumps({'type':'resume','token':'bad'})),
                             send=AsyncMock(), close=AsyncMock())
    await transport.handle(socket)
    assert not transport._connections
    assert json.loads(socket.send.call_args.args[0])['code'] == 'unauthorized'
    await transport.stop()


@pytest.mark.asyncio
async def test_multiple_subscriptions_replay_then_live_and_unsubscribe():
    transport = WebSocketTransport({'max_subscriptions': 2}, MessageBus())
    async def history(user, sid, **kwargs):
        if kwargs.get('after') == 1:
            return {'messages': [{'type': 'message', 'session_id': sid, 'sequence': 2, 'text': 'live'}],
                    'through': 2, 'cursor': 2, 'has_more': False}
        await transport.publish(sid, {'type': 'message', 'session_id': sid, 'sequence': 2, 'text': 'live'})
        return {'messages': [{'type': 'message', 'session_id': sid, 'sequence': 1, 'text': 'history'}],
                'through': 1, 'cursor': 1, 'has_more': False}
    transport.bind(SimpleNamespace(authorize=AsyncMock(), history=history,
        application=SimpleNamespace(history=lambda sid, **kw: history('alice', sid, **kw))))
    connection = Connection(SimpleNamespace(), user_id='alice', session_id='one')
    await transport.subscribe(connection, 'one')
    await transport.subscribe(connection, 'two')
    frames = []
    while not connection.queue.empty():
        frames.append(connection.queue.get_nowait())
    assert [(f['session_id'], f['type']) for f in frames] == [
        ('one', 'message'), ('one', 'ready'), ('one', 'message'),
        ('two', 'message'), ('two', 'ready'), ('two', 'message')]
    with pytest.raises(asyncio.QueueFull):
        await transport.subscribe(connection, 'three')
    await transport.unsubscribe(connection, 'one')
    await transport.publish('one', {'type': 'message', 'session_id': 'one'})
    assert connection.queue.empty()
    assert 'one' not in transport._connections


@pytest.mark.asyncio
async def test_connection_capacity_rejects_before_reading_credentials():
    transport = WebSocketTransport({'max_connections': 1}, MessageBus())
    transport.bind(SimpleNamespace())
    await transport.start()
    transport._handlers.add(object())
    socket = SimpleNamespace(recv=AsyncMock(), send=AsyncMock(), close=AsyncMock())
    await transport.handle(socket)
    socket.recv.assert_not_awaited()
    socket.close.assert_awaited()
    assert json.loads(socket.send.call_args.args[0])['code'] == 'busy'
    transport._handlers.clear()
    await transport.stop()


@pytest.mark.asyncio
async def test_live_prefix_repair_does_not_wait_for_subscriber_auth_backend():
    transport = WebSocketTransport({}, MessageBus())
    async def stalled_authorized_history(*args, **kwargs):
        await asyncio.Event().wait()
    message = {'type': 'message', 'session_id': 'room', 'sequence': 2, 'text': 'saved'}
    service = SimpleNamespace(history=AsyncMock(side_effect=stalled_authorized_history),
        application=SimpleNamespace(history=AsyncMock(return_value={
            'messages': [message], 'cursor': 2, 'through': 2, 'has_more': False})))
    transport.bind(service)
    connection = Connection(SimpleNamespace(), user_id='alice', session_id='room',
                            managed=True, sessions={'room'}, cursors={'room': 0})
    transport._connections['room'] = {connection}
    await asyncio.wait_for(transport.publish('room', message), .1)
    assert connection.queue.get_nowait() == message
    service.history.assert_not_awaited()
