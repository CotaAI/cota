import asyncio
from unittest.mock import AsyncMock

import pytest

from cota.channels.events import InboundMessage
from cota.channels.runner import ChannelRunner
from cota.message.message import Message
from cota.processor import Processor
from cota.store import MemoryStore, SQLStore


def inbound(message_id='same', **changes):
    values = dict(channel='feishu', sender_id='u', chat_id='room', content='hello',
                  session_key_override='shared', message_id=message_id)
    values.update(changes)
    return InboundMessage(**values)


def test_default_message_ids_are_unique_and_explicit_ids_survive():
    values = [inbound(None), inbound(None), Message(), Message(message_id=None)]
    assert all(isinstance(value.message_id, str) and value.message_id for value in values)
    assert len({value.message_id for value in values}) == 4
    assert Message(message_id='external').as_dict()['message_id'] == 'external'
    assert inbound('external').message_id == 'external'


@pytest.mark.parametrize('invalid', ['', ' ', 1, False])
def test_invalid_explicit_message_ids_are_rejected(invalid):
    with pytest.raises(ValueError):
        inbound(invalid)
    with pytest.raises(ValueError):
        Message(message_id=invalid)


async def test_runner_deduplicates_across_channels_even_when_full(mock_agent):
    store = mock_agent.store = MemoryStore()
    runner = ChannelRunner({}, mock_agent, max_pending=1)
    await runner.start()
    release = asyncio.Event()
    async def wait_for_release(_):
        await release.wait()
    handler = AsyncMock(side_effect=wait_for_release)
    try:
        first = await runner.submit(inbound(), handler)
        duplicate = await runner.submit(inbound(channel='web'), handler)
        assert duplicate is first
        assert (await store.input_receipt('shared', 'same'))['status'] in ('queued', 'running')
        with pytest.raises(ValueError, match='message_id'):
            await runner.submit(inbound(content='changed'), handler)
        with pytest.raises(asyncio.QueueFull):
            await runner.submit(inbound('second'), handler)
        assert await store.input_receipt('shared', 'second') is None
        release.set()
        await first
        handler.assert_awaited_once()
    finally:
        await runner.stop()


async def test_direct_sdk_and_channel_share_durable_identity(mock_agent):
    store = MemoryStore()
    processor = Processor(mock_agent, store)
    processor._create_runtime = AsyncMock(side_effect=RuntimeError('startup failed'))
    with pytest.raises(RuntimeError, match='startup failed'):
        await processor.handle_message(Message(session_id='shared', sender_id='u', receiver='bot',
                                               text='hello', message_id='same'))
    assert (await store.input_receipt('shared', 'same'))['status'] == 'interrupted'
    duplicate = Processor(mock_agent, store)
    duplicate._create_runtime = AsyncMock()
    callback = AsyncMock()
    duplicate.set_input_callback(callback)
    assert await duplicate.handle_inbound_message(inbound()) == 'interrupted'
    duplicate._create_runtime.assert_not_called()
    callback.assert_not_called()
    assert len([e for e in await store.history('shared') if e['type'] == 'user_utter']) == 1
    for changes in ({'sender_id': 'other'}, {'content': 'changed'}, {'media': ['image']}):
        with pytest.raises(ValueError, match='message_id'):
            await duplicate.handle_inbound_message(inbound(**changes))


async def test_committed_input_survives_store_restart_without_replay(mock_agent, tmp_path):
    path = str(tmp_path / 'inputs.db')
    store = SQLStore(dialect='sqlite', db=path)
    processor = Processor(mock_agent, store)
    processor._create_runtime = AsyncMock(side_effect=RuntimeError('startup failed'))
    with pytest.raises(RuntimeError):
        await processor.handle_inbound_message(inbound())
    reopened = SQLStore(dialect='sqlite', db=path)
    assert (await reopened.input_receipt('shared', 'same'))['status'] == 'interrupted'
    duplicate = Processor(mock_agent, reopened)
    duplicate._create_runtime = AsyncMock()
    assert await duplicate.handle_inbound_message(inbound()) == 'interrupted'
    duplicate._create_runtime.assert_not_called()


async def test_terminal_receipt_for_older_input_and_fresh_runner_skips_model(mock_agent):
    store = mock_agent.store = MemoryStore()
    processor = Processor(mock_agent, store)
    assert await processor.handle_inbound_message(inbound('first')) == 'completed'
    assert await processor.handle_inbound_message(inbound('second', content='next')) == 'completed'
    receipt = await store.input_receipt('shared', 'first')
    assert receipt['status'] == 'completed' and receipt['run_id']
    assert receipt['input_event_id'] != (await store.input_receipt('shared', 'second'))['input_event_id']
    runner = ChannelRunner({}, mock_agent)
    await runner.start()
    handler = AsyncMock()
    try:
        result = await runner.submit(inbound('first', channel='web'), handler)
        assert await result == 'completed'
        handler.assert_not_called()
        assert mock_agent._llm_mock.generate_chat.await_count == 2
    finally:
        await runner.stop()


async def test_queue_receipts_do_not_append_future_input_to_model_context(mock_agent):
    store = mock_agent.store = MemoryStore()
    runner = ChannelRunner({}, mock_agent, concurrency=1)
    await runner.start()
    entered, release = asyncio.Event(), asyncio.Event()

    async def model(**kwargs):
        entered.set()
        await release.wait()
        return {'content': 'done'}

    mock_agent._llm_mock.generate_chat.side_effect = model

    async def process(message):
        return await Processor(mock_agent, store).handle_inbound_message(message)

    try:
        first = await runner.submit(inbound('first'), process)
        await asyncio.wait_for(entered.wait(), 10)
        second = await runner.submit(inbound('second', content='future'), process)
        assert (await store.input_receipt('shared', 'first'))['status'] == 'running'
        assert (await store.input_receipt('shared', 'second'))['status'] == 'queued'
        assert [event['payload']['text'] for event in await store.history('shared')] == ['hello']
        second.cancel()
        release.set()
        assert await first == 'completed'
        await asyncio.sleep(0)
        assert await store.input_receipt('shared', 'second') is None
        assert mock_agent._llm_mock.generate_chat.await_count == 1
    finally:
        release.set()
        await runner.stop()


async def test_bus_conflict_does_not_stop_intake(mock_agent):
    mock_agent.store = MemoryStore()
    runner = ChannelRunner({}, mock_agent)
    entered = asyncio.Event()
    async def process(message):
        entered.set()
        await asyncio.Event().wait()
    mock_agent.create_processor = lambda **kwargs: type('P', (), {'handle_inbound_message': staticmethod(process)})()
    await runner.start()
    try:
        await runner.message_bus.publish_inbound(inbound())
        await entered.wait()
        await runner.message_bus.publish_inbound(inbound(content='conflict'))
        await asyncio.sleep(.01)
        assert not runner._processor_task.done()
    finally:
        await runner.stop()


def test_oversized_message_id_is_rejected():
    with pytest.raises(ValueError, match='message_id'):
        inbound('x' * 256)
    with pytest.raises(ValueError, match='message_id'):
        Message(message_id='x' * 256)


async def test_orphan_run_rejects_new_input_before_recording(mock_agent):
    from cota.dst import DST
    from cota.events import Event, UserUtterEvent
    from cota.runtime.pi_runtime import RunInProgress
    store = mock_agent.store = MemoryStore()
    dst = DST('shared', mock_agent)
    dst.append_event(UserUtterEvent('old'))
    dst.append_event(Event('run_started', {'input_event_id': dst.latest_user_event.event_id}, run_id='orphan'))
    await store.save(dst)
    with pytest.raises(RunInProgress):
        await Processor(mock_agent, store).handle_inbound_message(inbound())
    assert [e['payload']['text'] for e in await store.history('shared')] == ['old']
    runner = ChannelRunner({}, mock_agent)
    await runner.start()
    try:
        with pytest.raises(RunInProgress):
            await runner.submit(inbound(), AsyncMock())
        assert await store.input_receipt('shared', 'same') is None
    finally:
        await runner.stop()


async def test_shutdown_observer_sees_final_receipt(mock_agent):
    store = mock_agent.store = MemoryStore()
    entered, cancelled, cleanup = asyncio.Event(), asyncio.Event(), asyncio.Event()
    async def run(message):
        from cota.dst import DST
        from cota.events import UserUtterEvent
        from cota.inputs import input_event_id
        dst = DST('shared', mock_agent)
        dst.append_event(UserUtterEvent(message.content, metadata={'message_id': message.message_id,
            'sender_id': message.sender_id}, event_id=input_event_id(message.message_id)))
        await store.save(dst)
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
            await cleanup.wait()
    runner = ChannelRunner({}, mock_agent)
    await runner.start()
    first = await runner.submit(inbound(), run)
    await entered.wait()
    stopping = asyncio.create_task(runner.stop())
    await cancelled.wait()
    try:
        assert not first.done(), 'Result must wait for executor cleanup'
    finally:
        cleanup.set()
        await stopping
    assert first.cancelled()
    assert (await store.input_receipt('shared', 'same'))['status'] == 'interrupted'


async def test_receiver_execution_intent_conflicts_and_empty_identity_roundtrips(mock_agent):
    store = MemoryStore()
    processor = Processor(mock_agent, store)
    message = Message(session_id='s', sender_id='', text='observed', message_id='observed')
    assert await processor.handle_message(message) == 'completed'
    assert await processor.handle_message(message) == 'completed'
    with pytest.raises(ValueError, match='message_id'):
        await processor.handle_message(Message(session_id='s', sender_id='', text='observed',
                                               receiver='bot', message_id='observed'))


async def test_stop_cleans_task_cancelled_before_first_instruction(mock_agent):
    store = mock_agent.store = MemoryStore()
    runner = ChannelRunner({}, mock_agent)
    await runner.start()
    result = await runner.submit(inbound(), AsyncMock())
    await runner.stop()
    assert result.cancelled()
    assert await store.input_receipt('shared', 'same') is None
    assert runner._pending == 0


@pytest.mark.parametrize('legacy', [True, False])
async def test_proxy_mode_cannot_bypass_identified_input_execution(mock_agent, legacy):
    mock_agent.dialogue['use_proxy_user'] = True
    store = MemoryStore()
    processor = Processor(mock_agent, store)
    with pytest.raises(ValueError, match='proxy.*identified'):
        if legacy:
            await processor.handle_message(Message(session_id='shared', receiver='bot', text='hello'))
        else:
            await processor.handle_inbound_message(inbound())
    mock_agent._llm_mock.generate_chat.assert_not_called()
    assert await store.history('shared') == []


async def test_receipt_lookup_during_commit_does_not_disappear(mock_agent):
    from cota.dst import DST
    from cota.events import UserUtterEvent
    from cota.inputs import input_event_id
    store = MemoryStore()
    message = inbound()
    store.claim_input(message)
    read_started, finish_read = asyncio.Event(), asyncio.Event()
    original = store._input_event
    async def delayed_read(session_id, message_id):
        value = await original(session_id, message_id)
        if not read_started.is_set():
            read_started.set()
            await finish_read.wait()
        return value
    store._input_event = delayed_read
    query = asyncio.create_task(store.input_receipt('shared', 'same'))
    await read_started.wait()
    dst = DST('shared', mock_agent)
    dst.append_event(UserUtterEvent('hello', metadata={'message_id': 'same', 'sender_id': 'u'},
                                   event_id=input_event_id('same')))
    await store.save(dst)
    store.finish_input(message)
    finish_read.set()
    assert (await query)['status'] == 'interrupted'
