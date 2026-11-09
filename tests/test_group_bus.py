"""Channel intake stays independent of bounded group execution retries."""
import asyncio
from unittest.mock import AsyncMock

import pytest

from cota.application import Application
from cota.channels.events import InboundMessage
from cota.store import MemoryStore, SQLStore


def message(identity, *, mentioned=True):
    return InboundMessage('application', 'alice', 'group', identity,
        session_key_override='group', message_id=identity, mentioned=mentioned,
        conversation_type='group')


async def receipt_with_status(app, identity, status, timeout=3):
    async def wait():
        while True:
            receipt = await app.receipt('group', identity)
            if receipt and receipt['status'] == status:
                return receipt
            await asyncio.sleep(.01)
    return await asyncio.wait_for(wait(), timeout)


@pytest.mark.parametrize('sql', [False, True])
async def test_capacity_blocked_bus_mention_does_not_block_ordinary_input(mock_agent, tmp_path, sql):
    mock_agent.dialogue.update(mode='group', response='passive')
    mock_agent.cleanup = AsyncMock()
    mock_agent.store = SQLStore(db=str(tmp_path/'bus.db')) if sql else MemoryStore()
    entered, release = asyncio.Event(), asyncio.Event()
    requests = []
    async def model(**kwargs):
        requests.append(kwargs['messages'])
        if len(requests) == 1:
            entered.set()
            await release.wait()
        return {'content': 'answer'}
    mock_agent._llm_mock.generate_chat.side_effect = model
    try:
        async with Application(mock_agent, max_pending=1) as app:
            bus = app.runner.message_bus
            await bus.publish_inbound(message('active-X'))
            await asyncio.wait_for(entered.wait(), 10)
            try:
                await bus.publish_inbound(message('queued-A'))
                await receipt_with_status(app, 'queued-A', 'recorded')
                await bus.publish_inbound(message('queued-A'))
                await asyncio.wait_for(bus.publish_inbound(message('late-B', mentioned=False)), 1)
                await receipt_with_status(app, 'late-B', 'recorded', timeout=1)
                assert len(requests) == 1
            finally:
                release.set()
            await receipt_with_status(app, 'active-X', 'completed')
            await receipt_with_status(app, 'queued-A', 'completed')
            assert len(requests) == 2
            assert 'queued-A' in str(requests[1])
            assert 'late-B' not in str(requests[1])
            history = (await app.history('group'))['messages']
            assert len([row for row in history if row['message_id'] == 'queued-A']) == 1
            assert len([row for row in history if row['role'] == 'bot']) == 2
    finally:
        if sql:
            mock_agent.store.engine.dispose()


async def test_deferred_bus_retry_is_bounded_and_preserves_mention_order(mock_agent):
    mock_agent.dialogue.update(mode='group', response='passive')
    mock_agent.cleanup = AsyncMock()
    entered, release = asyncio.Event(), asyncio.Event()
    requests = []
    async def model(**kwargs):
        requests.append(kwargs['messages'])
        if len(requests) == 1:
            entered.set()
            await release.wait()
        return {'content': 'answer'}
    mock_agent._llm_mock.generate_chat.side_effect = model
    async with Application(mock_agent, max_pending=1) as app:
        bus = app.runner.message_bus
        await bus.publish_inbound(message('active-X'))
        await asyncio.wait_for(entered.wait(), 10)
        try:
            await bus.publish_inbound(message('queued-A'))
            await receipt_with_status(app, 'queued-A', 'recorded')
            await bus.publish_inbound(message('queued-C'))
            await receipt_with_status(app, 'queued-C', 'recorded')
            assert len(app.runner._deferred_inputs) == 1
            assert app.runner._retry_task is not None and not app.runner._retry_task.done()
            assert app.runner._pending == 1
        finally:
            release.set()
        await receipt_with_status(app, 'queued-C', 'completed')
        assert len(requests) == 3
        assert 'queued-A' in str(requests[1]) and 'queued-C' not in str(requests[1])
        assert 'queued-C' in str(requests[2])
        assert not app.runner._deferred_inputs


async def test_shutdown_cancels_deferred_retry_without_replaying_recorded_mention(mock_agent):
    mock_agent.dialogue.update(mode='group', response='passive')
    mock_agent.cleanup = AsyncMock()
    entered, release = asyncio.Event(), asyncio.Event()
    async def model(**kwargs):
        entered.set()
        await release.wait()
        return {'content': 'answer'}
    mock_agent._llm_mock.generate_chat.side_effect = model
    app = Application(mock_agent, max_pending=1)
    app.runner.shutdown_timeout = .1
    await app.start()
    try:
        await app.runner.message_bus.publish_inbound(message('active-X'))
        await asyncio.wait_for(entered.wait(), 10)
        await app.runner.message_bus.publish_inbound(message('queued-A'))
        await receipt_with_status(app, 'queued-A', 'recorded')
        await asyncio.wait_for(app.close(), 2)
        assert app.runner._processor_task.done()
        assert app.runner._retry_task.done()
        assert not app.runner._deferred_inputs
        assert not app.runner._active and app.runner._pending == 0
        assert (await app.receipt('group', 'queued-A'))['status'] == 'recorded'
        async with Application(mock_agent, max_pending=1) as reopened:
            assert (await reopened.receipt('group', 'queued-A'))['status'] == 'recorded'
            assert mock_agent._llm_mock.generate_chat.await_count == 1
    finally:
        release.set()
        await app.close()
