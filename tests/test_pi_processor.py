import asyncio
from unittest.mock import AsyncMock
import pytest
from cota.processor import Processor
from cota.store import MemoryStore
from cota.events import Event, BotUtterEvent, UserUtterEvent
from tests.resource_fixtures import skill_result
from cota.dst import DST
from cota.message.message import Message
from cota.channels.events import InboundMessage
from cota.channels.queue import MessageBus


def message(text='hello', session='s'):
    return Message(text=text, session_id=session, sender_id='u', receiver='bot')


@pytest.mark.asyncio
async def test_default_runtime_is_pi_and_input_is_saved_before_model(mock_agent):
    store = MemoryStore()
    async def respond(**kw):
        stored = await store.export_session('s')
        assert next(e for e in stored['events'] if e['type'] == 'user_utter')['payload']['text'] == 'hello'
        assert stored['execution']['engine'] == 'pi'
        return {'content': 'hi'}
    mock_agent._llm_mock.generate_chat.side_effect = respond
    await Processor(mock_agent, store).handle_message(message())
    assert (await store.export_session('s'))['execution']['status'] == 'completed'


@pytest.mark.asyncio
async def test_bus_question_is_delivered_without_repeating_previous_answer(mock_agent):
    store = MemoryStore()
    dst = DST('web:room', mock_agent)
    dst.append_event(UserUtterEvent('previous'))
    dst.append_event(BotUtterEvent('old answer'))
    await store.save(dst)
    bus = MessageBus()
    mock_agent._llm_mock.generate_chat.return_value = {'content': 'city?'}
    await Processor(mock_agent, store, bus).handle_inbound_message(InboundMessage(
        channel='web', chat_id='room', sender_id='u', content='weather'))
    outbound = await bus.consume_outbound(timeout=1)
    assert outbound.content == 'city?'


@pytest.mark.asyncio
async def test_same_session_turns_are_serialized(mock_agent):
    store = MemoryStore()
    entered, release = asyncio.Event(), asyncio.Event()
    count = 0
    async def respond(**kw):
        nonlocal count
        count += 1
        if count == 1:
            entered.set()
            await release.wait()
        return {'content': f'answer {count}'}
    mock_agent._llm_mock.generate_chat.side_effect = respond
    a = asyncio.create_task(Processor(mock_agent, store).handle_message(message('one')))
    await asyncio.wait_for(entered.wait(), 10)
    b = asyncio.create_task(Processor(mock_agent, store).handle_message(message('two')))
    await asyncio.sleep(.05)
    assert count == 1
    release.set()
    await asyncio.gather(a, b)
    assert [e['payload']['text'] for e in await store.history('s')] == ['one', 'answer 1', 'two', 'answer 2']


@pytest.mark.asyncio
async def test_bus_reply_after_skill_read_sent_once_and_recorded(mock_agent):
    store = MemoryStore()
    dst = DST('web:room', mock_agent)
    dst.append_event(Event('run_started', {}, run_id='prior-read'))
    dst.append_event(skill_result('SearchWeb'))
    dst.append_event(Event('run_finished', {'status': 'completed'}))
    await store.save(dst)
    bus = MessageBus()
    mock_agent._llm_mock.generate_chat.side_effect = [
        {'content': 'sent once'}]
    await Processor(mock_agent, store, bus).handle_inbound_message(InboundMessage(
        channel='web', chat_id='room', sender_id='u', content='go'))
    assert (await bus.consume_outbound(timeout=1)).content == 'sent once'
    with pytest.raises(asyncio.TimeoutError):
        await bus.consume_outbound(timeout=.01)
    assert [e['payload']['text'] for e in await store.history('web:room')] == ['go', 'sent once']


@pytest.mark.asyncio
async def test_model_failure_is_visible_but_state_remains_failed(mock_agent):
    store = MemoryStore()
    mock_agent._llm_mock.generate_chat.side_effect = RuntimeError('API timeout')
    channel = type('Channel', (), {'send_response': AsyncMock()})()
    await Processor(mock_agent, store).handle_message(message(), channel)
    stored = await store.export_session('s')
    assert stored['execution']['status'] == 'failed'
    assert '错误' in (await store.history('s'))[-1]['payload']['text']
    channel.send_response.assert_awaited_once()


@pytest.mark.asyncio
async def test_legacy_channel_metadata_is_retained_in_store(mock_agent):
    store = MemoryStore()
    incoming = message()
    incoming.metadata = {'platform_message_id': 'm1', 'attachments': [{'url': 'https://example.test/a.png'}]}
    await Processor(mock_agent, store).handle_message(incoming)
    user = (await store.history('s'))[0]
    assert user['payload']['metadata']['channel_metadata'] == incoming.metadata


@pytest.mark.asyncio
async def test_channel_send_preserves_bot_without_appending_delivery_event(mock_agent):
    store = MemoryStore()
    before = []
    async def send(session_id, response):
        saved = await store.export_session(session_id)
        before.extend(e for e in saved['events'] if e['type'] == 'bot_utter')
    channel = type('Channel', (), {'send_response': staticmethod(send)})()
    await Processor(mock_agent, store).handle_message(message(), channel)
    saved = await store.export_session('s')
    assert [e for e in saved['events'] if e['type'] == 'bot_utter'] == before
    assert len(before) == 1
    assert not any(e['type'] == 'message_delivery' for e in saved['events'])


@pytest.mark.asyncio
async def test_bus_final_reply_is_sent_once_without_delivery_event(mock_agent):
    store, bus = MemoryStore(), MessageBus()
    mock_agent._llm_mock.generate_chat.return_value = {'content': 'hello back'}
    await Processor(mock_agent, store, bus).handle_inbound_message(InboundMessage(
        channel='web', chat_id='room', sender_id='u', content='hello'))
    assert (await bus.consume_outbound(timeout=1)).content == 'hello back'
    with pytest.raises(asyncio.TimeoutError):
        await bus.consume_outbound(timeout=.01)
    saved = await store.export_session('web:room')
    assert [e['payload']['text'] for e in saved['events'] if e['type'] == 'bot_utter'] == ['hello back']
    assert not any(e['type'] == 'message_delivery' for e in saved['events'])


@pytest.mark.asyncio
async def test_observed_messages_between_runs_are_included(mock_agent):
    store = MemoryStore()
    processor = Processor(mock_agent, store)
    await processor.handle_message(message('first'))
    observed = message('room observation')
    observed.receiver = 'other_user'
    await processor.handle_message(observed)
    await processor.handle_message(message('what happened?'))
    model_messages = mock_agent._llm_mock.generate_chat.call_args.kwargs['messages']
    user_texts = [m['content'] for m in model_messages if m['role'] == 'user']
    assert user_texts == ['first', 'room observation', 'what happened?']


@pytest.mark.asyncio
async def test_public_entrypoints_accept_keyword_arguments(mock_agent):
    store = MemoryStore()
    processor = Processor(mock_agent, store)
    await processor.handle_message(message=message())
    await processor.handle_inbound_message(inbound=InboundMessage(
        channel='web', sender_id='u', chat_id='room', content='hello'))
    await processor.handle_session(session_id='s')
