"""Stable application contract over the existing scheduler and event store."""
import asyncio
from unittest.mock import AsyncMock

import pytest

import cota
from cota.channels.events import InboundMessage
from cota.store import MemoryStore


def application(agent, **kwargs):
    assert hasattr(cota, 'Application'), 'Application must be a public SDK export'
    agent.cleanup = AsyncMock()
    return cota.Application(agent, **kwargs)


async def test_receipts_deduplicate_and_wait_is_scoped_to_one_input(mock_agent):
    app = application(mock_agent)
    async with app:
        first = await app.submit(user_id='alice', session_id='room', text='first', message_id='one')
        result = await first.wait()
        assert result['receipt']['status'] == 'completed'
        second = await app.submit(user_id='bob', session_id='room', text='second', message_id='two')
        await second.wait()
        duplicate = await app.submit(user_id='alice', session_id='room', text='first', message_id='one')
        assert duplicate.duplicate is True
        assert await duplicate.wait() == result
        assert [m['text'] for m in result['messages']] == ['first', 'hello']
        assert all(set(m) == {'type', 'session_id', 'event_id', 'sequence', 'role', 'text', 'message_id', 'timestamp'}
                   for m in result['messages'])
        with pytest.raises(ValueError, match='message_id'):
            await app.submit(user_id='bob', session_id='room', text='first', message_id='one')
        elsewhere = await app.submit(user_id='alice', session_id='elsewhere', text='first', message_id='one')
        assert not elsewhere.duplicate
        await elsewhere.wait()
        assert app.store is app.runner.store is mock_agent.store
    mock_agent.cleanup.assert_awaited_once()
    await app.close()
    mock_agent.cleanup.assert_awaited_once()
    with pytest.raises(RuntimeError):
        await app.start()


async def test_fifo_concurrency_cancelled_wait_and_duplicate_callbacks(mock_agent):
    app = application(mock_agent, concurrency=2)
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []
    async def model(**kwargs):
        user = [m['content'] for m in kwargs['messages'] if m['role'] == 'user'][-1]
        calls.append(user)
        if len(calls) == 2:
            entered.set()
        await release.wait()
        return {'content': 'done'}
    mock_agent._llm_mock.generate_chat.side_effect = model
    on_input, on_reply = AsyncMock(), AsyncMock()
    async with app:
        inbound = InboundMessage('web', 'alice', 'room', 'first', message_id='one')
        first = await app.submit_message(inbound, on_input=on_input, on_reply=on_reply)
        duplicate = await app.submit_message(inbound, on_input=on_input, on_reply=on_reply)
        second = await app.submit(user_id='bob', session_id='web:room', text='second')
        other = await app.submit(user_id='alice', session_id='elsewhere', text='other')
        await asyncio.wait_for(entered.wait(), 10)
        assert set(calls) == {'first', 'other'}
        assert (await second.receipt())['status'] == 'queued'
        waiting = asyncio.create_task(first.wait())
        await asyncio.sleep(0)
        waiting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiting
        assert not first.future.cancelled()
        release.set()
        await asyncio.gather(duplicate.wait(), second.wait(), other.wait())
        on_input.assert_awaited_once()
        on_reply.assert_awaited_once()
        assert len(calls) == 3 and calls[-1] == 'second'


async def test_history_is_bounded_and_projection_only(mock_agent):
    async with application(mock_agent) as app:
        submission = await app.submit(user_id='alice', session_id='room', text='hello')
        await submission.wait()
        messages, cursor = [], 0
        page = await app.history('room', limit=1)
        through = page['through']
        while True:
            messages.extend(page['messages'])
            cursor = page['cursor']
            if not page['has_more']:
                break
            page = await app.history('room', after=cursor, limit=1, until=through)
        assert [m['role'] for m in messages] == ['user', 'bot']
        assert cursor == through
        for kwargs in ({'limit': 0}, {'limit': 501}, {'after': -1}, {'after': True},
                       {'until': -1}, {'until': True}, {'after': through + 1}):
            with pytest.raises(ValueError):
                await app.history('room', **kwargs)


@pytest.mark.parametrize('changes', [{'user_id': ''}, {'session_id': ' '}, {'user_id': 'x' * 256},
                                    {'session_id': 1}, {'text': ''}, {'text': 'x' * 32769}])
async def test_submit_validates_public_inputs(mock_agent, changes):
    async with application(mock_agent) as app:
        with pytest.raises(ValueError):
            await app.submit(**dict(dict(user_id='alice', session_id='room', text='hello'), **changes))


async def test_precommit_failure_does_not_accept_or_schedule_input(mock_agent):
    class FailingStore(MemoryStore):
        async def save(self, tracker):
            raise OSError('storage unavailable')
    mock_agent.store = FailingStore()
    async with application(mock_agent) as app:
        with pytest.raises(OSError, match='storage unavailable'):
            await app.submit(user_id='alice', session_id='room', text='hello', message_id='failed')
        assert await app.receipt('room', 'failed') is None
        assert app.runner._pending == 0
        mock_agent._llm_mock.generate_chat.assert_not_awaited()


async def test_service_failures_are_public_safe_and_durable(mock_agent):
    mock_agent._llm_mock.generate_chat.side_effect = RuntimeError('provider api key secret')
    async with application(mock_agent) as app:
        submission = await app.submit(user_id='alice', session_id='room', text='hello')
        result = await submission.wait()
        assert result['receipt']['status'] == 'failed'
        assert result['receipt']['error'] == 'execution_failed'
        assert 'secret' not in str(result)
        assert result['messages'][-1]['role'] == 'bot'
        events = await app.store.history('room')
        assert 'secret' not in events[-1]['payload']['text']
        duplicate = await app.submit(user_id='alice', session_id='room', text='hello', message_id=submission.message_id)
        assert (await duplicate.wait()) == result
        mock_agent._llm_mock.generate_chat.assert_awaited_once()


async def test_plain_question_completes_and_followup_has_its_own_receipt(mock_agent):
    mock_agent._llm_mock.generate_chat.side_effect = [
        {'content': 'a question'}, {'content': 'first answer'},
    ]
    async with application(mock_agent) as app:
        submission = await app.submit(user_id='alice', session_id='room', text='hello')
        result = await submission.wait()
        assert result['receipt']['status'] == 'completed'
        assert [m['text'] for m in result['messages']] == ['hello', 'a question']
        followup = await app.submit(user_id='alice', session_id='room', text='my reply')
        followup_result = await followup.wait()
        assert followup_result['receipt']['status'] == 'completed'
        assert followup_result['receipt']['message_id'] != result['receipt']['message_id']
        assert [m['text'] for m in followup_result['messages']] == ['my reply', 'first answer']
        assert await submission.wait() == result


async def test_platform_intake_uses_application_service_mode(mock_agent, monkeypatch):
    modes, finished = [], asyncio.Event()
    from cota.processor import Processor
    async def handle(self, inbound):
        modes.append(self.service_mode)
        finished.set()
    monkeypatch.setattr(Processor, 'handle_recorded_message', handle)
    async with application(mock_agent) as app:
        await app.runner.message_bus.publish_inbound(InboundMessage('feishu', 'alice', 'chat', 'hello'))
        await asyncio.wait_for(finished.wait(), 5)
    assert modes == [True]


async def test_callback_failure_cannot_change_committed_result(mock_agent):
    callback = AsyncMock(side_effect=RuntimeError('transport disconnected'))
    async with application(mock_agent) as app:
        submission = await app.submit_message(InboundMessage('web', 'alice', 'room', 'hello'),
                                              on_input=callback, on_reply=callback)
        result = await submission.wait()
        assert result['receipt']['status'] == 'completed'
        assert [m['text'] for m in result['messages']] == ['hello', 'hello']
        assert callback.await_count == 2


async def test_start_and_cleanup_are_once_even_when_startup_fails(mock_agent):
    app = application(mock_agent)
    configure = AsyncMock(side_effect=RuntimeError('startup failed'))
    with pytest.raises(RuntimeError, match='startup failed'):
        await app.start(configure=configure)
    await app.close()
    mock_agent.cleanup.assert_awaited_once()
    with pytest.raises(RuntimeError, match='closed'):
        await app.start()


async def test_receipt_requires_explicit_message_identity(mock_agent):
    async with application(mock_agent) as app:
        with pytest.raises(ValueError, match='message_id'):
            await app.receipt('room', None)


async def test_sdk_replies_do_not_route_to_channels_and_explicit_callback_still_runs(mock_agent):
    async with application(mock_agent) as app:
        app.runner.message_bus.publish_outbound = AsyncMock()
        submission = await app.submit(user_id='alice', session_id='room', text='hello')
        result = await submission.wait()
        assert result['messages'][-1]['text'] == 'hello'
        app.runner.message_bus.publish_outbound.assert_not_awaited()
        callback = AsyncMock()
        observed = await app.submit_message(InboundMessage('application', 'alice', 'room', 'again'),
                                            on_reply=callback)
        await observed.wait()
        callback.assert_awaited_once()
        app.runner.message_bus.publish_outbound.assert_not_awaited()


async def test_cancelled_close_keeps_teardown_alive_and_can_be_awaited_again(mock_agent):
    app = application(mock_agent)
    await app.start()
    stopping, release, stopped = asyncio.Event(), asyncio.Event(), asyncio.Event()
    stop_all = app.runner.channel_manager.stop_all
    async def stop_channels():
        stopping.set()
        await release.wait()
        await stop_all()
        stopped.set()
    app.runner.channel_manager.stop_all = stop_channels
    closing = asyncio.create_task(app.close())
    await stopping.wait()
    closing.cancel()
    with pytest.raises(asyncio.CancelledError):
        await closing
    with pytest.raises(RuntimeError, match='not accepting'):
        await app.submit(user_id='alice', session_id='room', text='too late')
    release.set()
    await app.close()
    assert stopped.is_set(), 'Caller cancellation must not abandon channel cleanup'
    assert app.runner.message_bus.is_closed
    mock_agent.cleanup.assert_awaited_once()


async def test_repeated_start_cancellation_does_not_abandon_cleanup(mock_agent):
    app = application(mock_agent)
    configuring, cleaning, release, cleaned = (asyncio.Event() for _ in range(4))
    async def configure(_manager):
        configuring.set()
        await asyncio.Event().wait()
    async def cleanup():
        cleaning.set()
        await release.wait()
        cleaned.set()
    mock_agent.cleanup.side_effect = cleanup
    starting = asyncio.create_task(app.start(configure=configure))
    await configuring.wait()
    starting.cancel()
    await cleaning.wait()
    starting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await starting
    release.set()
    await app.close()
    assert cleaned.is_set(), 'Startup cancellation must leave owned cleanup alive'
    mock_agent.cleanup.assert_awaited_once()
