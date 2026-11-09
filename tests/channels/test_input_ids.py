import pytest
from cota.channels.queue import MessageBus
from cota.channels.web.base import WebChannel


@pytest.mark.asyncio
async def test_channel_preserves_platform_id_and_generates_when_missing():
    bus = MessageBus()
    channel = WebChannel({'allow_from':['*']}, bus)
    await channel._handle_message('u', 'room', 'hello', metadata={'message_id': 42})
    assert (await bus.consume_inbound()).message_id == '42'
    await channel._handle_message('u', 'room', 'hello', message_id='provided')
    assert (await bus.consume_inbound()).message_id == 'provided'
    await channel._handle_message('u', 'room', 'hello')
    first = (await bus.consume_inbound()).message_id
    await channel._handle_message('u', 'room', 'hello')
    second = (await bus.consume_inbound()).message_id
    assert first and second and first != second
