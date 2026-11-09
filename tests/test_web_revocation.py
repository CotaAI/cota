import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from cota.channels.queue import MessageBus
from cota.channels.web.transport import WebSocketTransport, Connection


@pytest.mark.asyncio
async def test_queued_frames_reauthorize_before_delivery():
    transport = WebSocketTransport({}, MessageBus())
    permitted = True
    async def authorize(user, session):
        if not permitted:
            raise PermissionError('Removed')
    transport.bind(SimpleNamespace(authorize=authorize, authenticate=AsyncMock(return_value='alice')))
    socket = SimpleNamespace(send=AsyncMock(), close=AsyncMock())
    connection = Connection(socket, user_id='alice', session_id='room', token='valid')
    connection.queue.put_nowait({'type': 'message', 'text': 'queued before removal'})
    permitted = False
    await asyncio.wait_for(transport._send_loop(connection), 1)
    socket.send.assert_awaited_once()
    assert json.loads(socket.send.call_args.args[0])['code'] == 'unauthorized'
    socket.close.assert_awaited()


@pytest.mark.asyncio
async def test_expired_live_credentials_cannot_receive_queued_history():
    transport = WebSocketTransport({}, MessageBus())
    service = SimpleNamespace(authorize=AsyncMock(), authenticate=AsyncMock(side_effect=PermissionError('Expired')))
    transport.bind(service)
    socket = SimpleNamespace(send=AsyncMock(), close=AsyncMock())
    connection = Connection(socket, user_id='alice', session_id='room', token='expired')
    connection.queue.put_nowait({'type': 'ready', 'cursor': 10})
    await asyncio.wait_for(transport._send_loop(connection), 1)
    assert all(json.loads(call.args[0]).get('code') == 'unauthorized' for call in socket.send.call_args_list)


@pytest.mark.asyncio
async def test_revoked_member_cannot_submit_on_existing_connection():
    transport = WebSocketTransport({}, MessageBus())
    allowed = True
    async def authorize(user, session):
        if not allowed:
            raise PermissionError('Removed')
    calls = 0
    async def receive():
        nonlocal calls, allowed
        calls += 1
        if calls == 1:
            return json.dumps({'type': 'resume', 'token': 'valid', 'session_id': 'room'})
        allowed = False
        return json.dumps({'type': 'send', 'message_id': 'after-removal', 'text': 'blocked'})
    service = SimpleNamespace(authenticate=AsyncMock(return_value='alice'), authorize=authorize,
        history=AsyncMock(return_value={'messages': [], 'through': 0, 'has_more': False}), submit=AsyncMock())
    transport.bind(service)
    await transport.start()
    socket = SimpleNamespace(recv=receive, send=AsyncMock(), close=AsyncMock())
    await asyncio.wait_for(transport.handle(socket), 1)
    service.submit.assert_not_awaited()
    assert not transport._connections
    await transport.stop()


@pytest.mark.asyncio
async def test_subscription_limit_error_is_delivered_for_unsubscribed_room():
    transport = WebSocketTransport({}, MessageBus())
    transport.bind(SimpleNamespace(authorize=AsyncMock(), authenticate=AsyncMock(return_value='alice')))
    delivered = asyncio.Event()
    async def send(raw):
        delivered.set()
    socket = SimpleNamespace(send=send, close=AsyncMock())
    connection = Connection(socket, user_id='alice', session_id='one', token='valid',
                            sessions={'one'}, managed=True)
    connection.queue.put_nowait({'type': 'error', 'code': 'busy', 'session_id': 'two'})
    task = asyncio.create_task(transport._send_loop(connection))
    try:
        await asyncio.wait_for(delivered.wait(), .1)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
