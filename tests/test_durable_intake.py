"""Accepted direct messages survive scheduling and retain causal turn context."""
import asyncio
from unittest.mock import AsyncMock

import pytest

from cota import Application
from cota.channels.events import InboundMessage
from cota.inputs import input_event_id
from cota.store import SQLStore


async def test_accepted_inputs_durable_and_each_run_has_causal_context(mock_agent):
    mock_agent.cleanup = AsyncMock()
    entered, release = asyncio.Event(), asyncio.Event()
    seen = []
    async def model(**kwargs):
        seen.append(kwargs['messages'])
        if len(seen) == 1:
            entered.set()
            await release.wait()
        return {'content': 'reply' + str(len(seen))}
    mock_agent._llm_mock.generate_chat.side_effect = model
    async with Application(mock_agent) as app:
        callback = AsyncMock()
        first = await app.submit_message(InboundMessage('application', 'a', 's', 'one',
            message_id='1', session_key_override='s'), on_reply=callback)
        assert await app.store.event_by_id('s', input_event_id('1')) is not None
        await asyncio.wait_for(entered.wait(), 5)
        second = await asyncio.wait_for(app.submit(user_id='b', session_id='s', text='two', message_id='2'), 1)
        assert await app.store.event_by_id('s', input_event_id('2')) is not None
        duplicate = await app.submit(user_id='b', session_id='s', text='two', message_id='2')
        assert duplicate.duplicate and duplicate.future is second.future
        release.set()
        await asyncio.gather(first.wait(), second.wait())
        assert [[m['content'] for m in call if m['role'] == 'user'] for call in seen] == [['one'], ['one', 'two']]
        assert [m['role'] for m in seen[1]] == ['system', 'user', 'assistant', 'user']
        reply = callback.await_args.args[0]
        canonical = await app.store.event_by_id('s', reply['event_id'])
        assert reply['sequence'] == canonical['sequence']


@pytest.mark.parametrize('sql', [False, True])
async def test_recent_pages_and_summary_are_bounded(mock_agent, tmp_path, sql):
    mock_agent.cleanup = AsyncMock()
    if sql:
        mock_agent.store = SQLStore(db=str(tmp_path / 'page.db'))
    async with Application(mock_agent) as app:
        for i in range(3):
            await (await app.submit(user_id='a', session_id='s', text=str(i))).wait()
        app.store.load = AsyncMock(side_effect=AssertionError('must not hydrate history'))
        latest = await app.message_page('s', limit=3)
        assert [m['text'] for m in latest['messages']] == ['hello', '2', 'hello']
        assert all(isinstance(m['timestamp'], float) for m in latest['messages'])
        assert latest['has_more']
        older = await app.message_page('s', before=latest['cursor'], limit=3)
        assert [m['text'] for m in older['messages']] == ['0', 'hello', '1']
        assert not older['has_more']
        summary = await app.conversation_summary('s', after=0, exclude_sender='a')
        assert summary['unread'] == 3
        assert summary['last_message'] == latest['messages'][-1]
        assert summary['last_active'] == latest['messages'][-1]['timestamp']


async def test_restart_dispatches_unstarted_inputs_in_bounded_fifo(mock_agent, tmp_path):
    mock_agent.cleanup = AsyncMock()
    database = str(tmp_path / 'restart.db')
    mock_agent.store = SQLStore(db=database)
    async with Application(mock_agent) as original:
        original.runner._pump = lambda: None  # crash boundary: persisted, not started
        for i in range(4):
            await original.submit(user_id='a', session_id='s', text=str(i), message_id=str(i))
    mock_agent.store = SQLStore(db=database)
    seen, completed = [], asyncio.Event()
    async def model(**kwargs):
        seen.append([m['content'] for m in kwargs['messages'] if m['role'] == 'user'][-1])
        if len(seen) == 4:
            completed.set()
        return {'content': 'done'}
    mock_agent._llm_mock.generate_chat.side_effect = model
    async with Application(mock_agent, concurrency=1, max_pending=1) as restarted:
        await asyncio.wait_for(completed.wait(), 10)
        assert seen == ['0', '1', '2', '3']
        assert restarted.runner._pending <= 1


async def test_recovery_never_repeats_started_run_or_tools(mock_agent, tmp_path):
    from cota.events import Event
    mock_agent.cleanup = AsyncMock()
    database = str(tmp_path / 'started.db')
    mock_agent.store = SQLStore(db=database)
    async with Application(mock_agent) as original:
        original.runner._pump = lambda: None
        await original.submit(user_id='a', session_id='blocked', text='started', message_id='1')
        await original.submit(user_id='a', session_id='blocked', text='queued', message_id='2')
        await original.submit(user_id='a', session_id='other', text='safe', message_id='3')
        tracker = await original.store.load('blocked')
        tracker.append_event(Event('run_started', {'input_event_id': input_event_id('1')}, run_id='old'))
        tracker.append_event(Event('tool_started', {'tool_call_id': 'call', 'tool': 'effect', 'arguments': {}}, run_id='old'))
        await original.store.save(tracker)
    mock_agent.store = SQLStore(db=database)
    completed = asyncio.Event()
    async def model(**kwargs):
        assert [m['content'] for m in kwargs['messages'] if m['role'] == 'user'] == ['safe']
        completed.set()
        return {'content': 'done'}
    mock_agent._llm_mock.generate_chat.side_effect = model
    async with Application(mock_agent) as restarted:
        await asyncio.wait_for(completed.wait(), 10)
        assert (await restarted.receipt('blocked', '1'))['status'] == 'interrupted'
        assert (await restarted.receipt('blocked', '2'))['status'] == 'recorded'
        mock_agent._llm_mock.generate_chat.assert_awaited_once()


async def test_capacity_reserved_while_durable_commit_is_in_flight(mock_agent):
    from cota.store import MemoryStore
    entered, release = asyncio.Event(), asyncio.Event()
    class SlowStore(MemoryStore):
        async def save(self, tracker, delivery_target=None):
            if tracker.session_id == 'first' and tracker.revision == 0:
                entered.set()
                await release.wait()
            return await super().save(tracker, delivery_target=delivery_target)
    mock_agent.store = SlowStore()
    mock_agent.cleanup = AsyncMock()
    async with Application(mock_agent, max_pending=1) as app:
        accepting = asyncio.create_task(app.submit(user_id='a', session_id='first', text='one', message_id='1'))
        await asyncio.wait_for(entered.wait(), 2)
        try:
            with pytest.raises(asyncio.QueueFull):
                await app.submit(user_id='b', session_id='second', text='two', message_id='2')
            assert await app.store.event_by_id('second', input_event_id('2')) is None
            assert app.runner._pending == 1
        finally:
            release.set()
        await (await accepting).wait()


async def test_completed_duplicate_receipt_bypasses_unstarted_backlog(mock_agent):
    from cota.events import UserUtterEvent
    mock_agent.cleanup = AsyncMock()
    entered, release = asyncio.Event(), asyncio.Event()
    async with Application(mock_agent, max_pending=1) as app:
        original = await app.submit(user_id='a', session_id='s', text='done', message_id='1')
        await original.wait()
        async def model(**kwargs):
            entered.set()
            await release.wait()
            return {'content': 'other'}
        mock_agent._llm_mock.generate_chat.side_effect = model
        other = await app.submit(user_id='b', session_id='other', text='hold')
        await asyncio.wait_for(entered.wait(), 5)
        await app.store.append_conversation_event('s', UserUtterEvent(
            event_id=input_event_id('2'), text='unstarted', metadata={
                'sender_id': 'a', 'message_id': '2', 'accepted': True}), agent=mock_agent)
        try:
            duplicate = await app.submit(user_id='a', session_id='s', text='done', message_id='1')
            assert duplicate.duplicate
            assert (await duplicate.wait())['receipt']['status'] == 'completed'
        finally:
            release.set()
        await other.wait()
