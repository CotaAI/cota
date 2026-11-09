"""Trusted execution context and committed-message publication regressions."""
import asyncio
import threading
from unittest.mock import AsyncMock

import pytest

from cota.channels.events import InboundMessage
from cota.channels.queue import MessageBus
from cota.dst import DST
from cota.executor.user_memory import MemoryUserMemory, SQLUserMemory, create_user_memory
from cota.processor import Processor
from cota.store import MemoryStore
from tests.test_pi_runtime import call


@pytest.mark.asyncio
async def test_publication_observes_committed_message_and_stable_ids(mock_agent):
    store, bus = MemoryStore(), MessageBus()
    mock_agent._llm_mock.generate_chat.return_value = {'content': 'visible'}
    published = []
    async def publish(message):
        committed = await store.history(message.session_id)
        event = next(e for e in committed if e['event_id'] == message.event_id)
        assert event['sequence'] == message.sequence
        assert event['payload']['text'] == message.content == 'visible'
        assert 'delivered' not in event['payload']['metadata']
        published.append(message)
    bus.publish_outbound = publish
    await Processor(mock_agent, store, bus).handle_inbound_message(InboundMessage(
        channel='web', chat_id='room', sender_id='alice', content='hello', message_id='input-1'))
    assert len(published) == 1
    saved = await store.history('web:room')
    assert saved[0]['payload']['metadata']['message_id'] == 'input-1'


@pytest.mark.asyncio
async def test_failed_save_never_publishes(mock_agent):
    class FailingStore(MemoryStore):
        async def save(self, tracker):
            if any(event.type == 'bot_utter' for event in tracker.events):
                raise OSError('disk full')
            await super().save(tracker)
    store, bus = FailingStore(), MessageBus()
    bus.publish_outbound = AsyncMock()
    mock_agent._llm_mock.generate_chat.return_value = {'content': 'must not escape'}
    with pytest.raises(OSError, match='disk full'):
        await Processor(mock_agent, store, bus).handle_inbound_message(InboundMessage(
            channel='web', chat_id='room', sender_id='alice', content='hello'))
    bus.publish_outbound.assert_not_awaited()
    assert not any(event['type'] == 'bot_utter' for event in await store.history('web:room'))


@pytest.mark.asyncio
async def test_failed_transport_does_not_repeat_reply_or_model(mock_agent):
    store, bus = MemoryStore(), MessageBus()
    bus.publish_outbound = AsyncMock(side_effect=OSError('socket disconnected'))
    mock_agent._llm_mock.generate_chat.return_value = {'content': 'saved answer'}
    await Processor(mock_agent, store, bus).handle_inbound_message(InboundMessage(
        channel='web', chat_id='room', sender_id='alice', content='hello'))
    assert mock_agent._llm_mock.generate_chat.await_count == 1
    bus.publish_outbound.assert_awaited_once()
    assert [e['payload']['text'] for e in await store.history('web:room')] == ['hello', 'saved answer']
    assert (await store.export_session('web:room'))['execution']['status'] == 'completed'


@pytest.mark.asyncio
@pytest.mark.parametrize('sql', [False, True])
async def test_simultaneous_users_have_private_tools_and_memory(mock_agent, tmp_path, sql):
    memory = SQLUserMemory(db=str(tmp_path / 'memory.db')) if sql else MemoryUserMemory()
    mock_agent.user_memory = memory
    for user in ('alice', 'bob'):
        await memory.aset(user, 'color', user + '_private_color')
    store = MemoryStore()
    entered, release = asyncio.Event(), asyncio.Event()
    active = 0
    async def model(**kwargs):
        nonlocal active
        messages = kwargs['messages']
        user = next(m['content'] for m in messages if m['role'] == 'user')
        active += 1
        if active == 2:
            entered.set()
        await release.wait()
        system = messages[0]['content']
        assert user + '_private_color' in system
        other = 'bob' if user == 'alice' else 'alice'
        assert other + '_private_color' not in system
        return {'content': user}
    mock_agent._llm_mock.generate_chat.side_effect = model
    async def run(user):
        await Processor(mock_agent, store).handle_inbound_message(InboundMessage(
            channel='web', chat_id=user, sender_id=user, content=user))
    tasks = [asyncio.create_task(run(user)) for user in ('alice', 'bob')]
    try:
        await asyncio.wait_for(entered.wait(), 10)
    finally:
        release.set()
    await asyncio.gather(*tasks)
    assert await memory.aget('alice', 'color') == 'alice_private_color'
    assert await memory.aget('bob', 'color') == 'bob_private_color'
    if sql:
        memory._engine.dispose()


@pytest.mark.asyncio
async def test_processor_context_load_does_not_block_event_loop(mock_agent):
    started, release = threading.Event(), threading.Event()
    class SlowMemory(MemoryUserMemory):
        def get_all(self, user_id):
            started.set()
            assert release.wait(5)
            return {'owner': user_id}
    mock_agent.user_memory = SlowMemory()
    processor = Processor(mock_agent, MemoryStore())
    processor.dst = DST('s', mock_agent)
    task = asyncio.create_task(processor._load_user_context('alice'))
    try:
        assert await asyncio.to_thread(started.wait, 2)
        assert not task.done()
    finally:
        release.set()
    await task
    assert processor.dst.user_context == {'owner': 'alice'}


@pytest.mark.asyncio
async def test_sql_memory_in_memory_database_survives_worker_threads():
    memory = SQLUserMemory(db=':memory:')
    await asyncio.gather(*(memory.aset(str(i), 'key', i) for i in range(20)))
    values = await asyncio.gather(*(memory.aget(str(i), 'key') for i in range(20)))
    assert values == list(range(20))


def test_configured_sql_memory_failure_does_not_fall_back(monkeypatch):
    def fail(**kwargs):
        raise OSError('database unavailable')
    monkeypatch.setattr('cota.executor.user_memory.SQLUserMemory', fail)
    with pytest.raises(OSError, match='database unavailable'):
        create_user_memory({'base_store': {'type': 'sql'}})


@pytest.mark.asyncio
async def test_web_cannot_force_a_hidden_scheduler_tool(mock_agent):
    store = MemoryStore()
    mock_agent._llm_mock.generate_chat.side_effect = [
        {'tool_calls': [call('scheduler', {'action': 'add', 'name': 'reminder'})]},
        {'content': 'Scheduled delivery is unavailable'}]
    await Processor(mock_agent, store).handle_inbound_message(InboundMessage(
        channel='web', chat_id='room', sender_id='alice', content='schedule reminder'))
    saved = await store.export_session('web:room')
    result = next(e for e in saved['events'] if e['type'] == 'tool_result')
    assert result['payload']['status'] == 'blocked'


@pytest.mark.asyncio
@pytest.mark.parametrize('callback_fails', [False, True])
async def test_input_callback_observes_commit_before_model_and_is_fail_safe(mock_agent, callback_fails):
    store = MemoryStore()
    processor = Processor(mock_agent, store)
    order = []
    async def committed(event):
        saved = await store.event_by_id('web:room', event['event_id'])
        assert saved == event
        assert event['type'] == 'user_utter'
        assert event['payload']['metadata']['message_id'] == 'message-1'
        order.append('input')
        event['payload']['text'] = 'tampered callback copy'
        if callback_fails:
            raise OSError('socket closed')
    async def model(**kwargs):
        assert order == ['input']
        assert processor.dst.latest_user_event.text == 'hello'
        order.append('model')
        return {'content': 'answer'}
    processor.set_input_callback(committed)
    mock_agent._llm_mock.generate_chat.side_effect = model
    await processor.handle_inbound_message(InboundMessage(
        channel='web', chat_id='room', sender_id='alice', content='hello', message_id='message-1'))
    assert order == ['input', 'model']
    assert (await store.export_session('web:room'))['execution']['status'] == 'completed'
