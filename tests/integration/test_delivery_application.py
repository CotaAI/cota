"""SQLite restart resends an existing reply without rerunning Pi."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from cota.application import Application
from cota.channels.events import InboundMessage
from cota.store import SQLStore
from tests.test_delivery_dispatcher import until


def channel(send, scope='cli_test'):
    return SimpleNamespace(durable_delivery=True, delivery_scope=scope, send=send,
                           start=AsyncMock(), stop=AsyncMock(), is_running=True)


def application(agent, send, scope='cli_test'):
    app = Application(agent, channel_limits={'delivery_poll_interval': .005,
                      'delivery_shutdown_timeout': .03, 'send_timeout': 1})
    async def configure(manager): manager.channels['feishu'] = channel(send, scope)
    return app, configure


async def test_reopen_database_recovers_committed_reply_without_model_execution(mock_agent, tmp_path):
    db = str(tmp_path/'deliveries.db')
    mock_agent.store = SQLStore(db=db)
    mock_agent.cleanup = AsyncMock()
    entered = asyncio.Event()
    async def blocked(message):
        entered.set()
        await asyncio.Event().wait()
    app, configure = application(mock_agent, blocked)
    await app.start(configure)
    incoming = InboundMessage('feishu', 'alice', 'chat', 'hello', message_id='input1')
    try:
        result = await (await app.submit_message(incoming)).wait()
        assert result['receipt']['status'] == 'completed'
        identity = next(m['event_id'] for m in result['messages'] if m['role'] == 'bot')
        await asyncio.wait_for(entered.wait(), 5)
    finally:
        await app.close()
    count = mock_agent._llm_mock.generate_chat.call_count
    mock_agent.store.engine.dispose()
    mock_agent.store = SQLStore(db=db)
    sent = []
    async def send(message): sent.append(message)
    restarted, configure = application(mock_agent, send)
    await restarted.start(configure)
    try:
        async def done():
            row = await restarted.delivery_status(incoming.session_key, identity)
            return row is not None and row['status'] == 'delivered'
        await until(done)
        assert [(m.chat_id, m.event_id, m.content) for m in sent] == [('chat', identity, 'hello')]
        assert mock_agent._llm_mock.generate_chat.call_count == count
        duplicate = await restarted.submit_message(incoming)
        assert duplicate.duplicate
        await duplicate.wait()
        assert mock_agent._llm_mock.generate_chat.call_count == count
        assert not await restarted.retry_delivery(incoming.session_key, identity)
        events = await restarted.store.events(incoming.session_key)
        assert not any('delivery' in e['type'] for e in events)
    finally:
        await restarted.close()
        restarted.store.engine.dispose()


async def test_explicit_reply_callback_and_sdk_input_do_not_enqueue_delivery(mock_agent):
    mock_agent.cleanup = AsyncMock()
    async def send(message): raise AssertionError('must not send')
    app, configure = application(mock_agent, send)
    await app.start(configure)
    try:
        callback = AsyncMock()
        first = await app.submit_message(InboundMessage('feishu', 'alice', 'chat', 'hi'), on_reply=callback)
        second = await app.submit(user_id='alice', session_id='sdk', text='hello')
        for submission in (first, second):
            result = await submission.wait()
            for message in result['messages']:
                if message['role'] == 'bot':
                    assert await app.delivery_status(submission.session_id, message['event_id']) is None
        callback.assert_awaited_once()
    finally:
        await app.close()
