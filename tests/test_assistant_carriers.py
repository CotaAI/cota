"""Assistant decisions live on bot/tool events; diagnostics are optional."""

import pytest

from cota.dst import DST
from cota.events import Event, UserUtterEvent
from cota.runtime.pi_runtime import PiAgentRuntime
from cota.snapshots import make_snapshot
from cota.store import MemoryStore, SQLStore
from tests.test_pi_runtime import call


@pytest.mark.asyncio
@pytest.mark.parametrize('debug', [False, True])
@pytest.mark.parametrize('backend', ['memory', 'sqlite'])
async def test_two_calls_share_one_durable_message_and_restore(mock_agent, tmp_path, debug, backend):
    store = MemoryStore() if backend == 'memory' else SQLStore(db=str(tmp_path / 'events.db'))
    if debug:
        store.enable_debug_log(tmp_path / 'debug.log')
    dst = DST('s', mock_agent)
    dst.append_event(UserUtterEvent('read twice'))
    path = mock_agent.skill_file('SearchWeb')
    mock_agent._llm_mock.generate_chat.side_effect = [
        {'content': 'Read two resources.', 'tool_calls': [call('read', {'path': path}, 'a'), call('read', {'path': path}, 'b')]},
        {'content': 'done'}, {'content': 'continued'},
    ]
    checkpoints = []
    async def save(tracker):
        assert DST.from_events('s', tracker.events).state_dict() == tracker.state_dict()
        await store.save(tracker)
        checkpoints.append(make_snapshot(tracker))
    try:
        await PiAgentRuntime(mock_agent, dst, 's', checkpoint=save, store=store).run()
        assert not any(e.type == 'model_response' for e in dst.events)
        starts = [e for e in dst.events if e.type == 'tool_started']
        assert len(starts) == 2
        owner, follower = starts
        assert [b['id'] for b in owner.payload['llm']['message']['content'] if b['type'] == 'toolCall'] == ['a', 'b']
        assert follower.payload['llm_event_id'] == owner.event_id
        assert 'llm' not in follower.payload
        assert [m['role'] for m in dst.context_messages] == ['user', 'assistant', 'toolResult', 'toolResult', 'assistant']
        assert dst.context_messages[1]['cotaEventId'] == owner.event_id
        assert dst.context_messages[1]['content'][0]['text'] == 'Read two resources.'
        bots = [e for e in dst.events if e.type == 'bot_utter']
        assert [e.text for e in bots] == ['Read two resources.', 'done']
        assert bots[0].payload['llm_event_id'] == owner.event_id
        assert 'llm' not in bots[0].payload
        assert 'message' not in bots[-1].payload['llm']
        assert dst.context_messages[-1]['cotaEventId'] == bots[-1].event_id
        detail = await store.model_debug('s', owner.payload['llm']['request_id'])
        assert bool(detail) == debug
        if debug:
            assert detail['event_id'] == owner.event_id
            assert detail['request']['messages'][0]['role'] == 'system'
        for snapshot in checkpoints:
            assert DST.from_events('s', dst.events, snapshot=snapshot).state_dict() == dst.state_dict()
        resumed = await store.load('s', mock_agent)
        resumed.append_event(UserUtterEvent('continue'))
        await PiAgentRuntime(mock_agent, resumed, 's', checkpoint=store.save, store=store).run()
        assert [m['role'] for m in mock_agent._llm_mock.generate_chat.call_args.kwargs['messages']] == ['system','user','assistant','tool','tool','assistant','user']
    finally:
        if backend == 'sqlite':
            store.engine.dispose()


@pytest.mark.asyncio
async def test_complete_proposal_saved_before_first_read_can_execute(mock_agent):
    dst = DST('s', mock_agent)
    dst.append_event(UserUtterEvent('read'))
    mock_agent._llm_mock.generate_chat.return_value = {'tool_calls': [
        call('read', {'path': mock_agent.skill_file('SearchWeb')}, 'a'),
        call('read', {'path': mock_agent.skill_file('SearchWeb')}, 'b')]}
    store = MemoryStore()
    async def stop(tracker):
        await store.save(tracker)
        if any(e.type == 'tool_started' for e in tracker.events):
            raise OSError('checkpoint stopped before external effect')
    with pytest.raises(OSError, match='checkpoint stopped'):
        await PiAgentRuntime(mock_agent, dst, 's', checkpoint=stop).run()
    saved = await store.load('s')
    starts = [e for e in saved.events if e.type == 'tool_started']
    assert len(starts) == 1
    assert len(starts[0].payload['llm']['message']['content']) == 2
    assert list(saved.execution['pending_tools']) == ['a']
    assert not any(e.type == 'tool_result' for e in saved.events)


def test_model_response_is_removed():
    with pytest.raises(ValueError, match='Unknown event type'):
        Event('model_response', {'request_id': 'q', 'request_sequence': 1, 'purpose': 'dialogue', 'message': {'role': 'assistant','content': []}})


@pytest.mark.asyncio
async def test_final_text_has_durable_model_carrier_and_is_replayed(mock_agent, tmp_path):
    from unittest.mock import AsyncMock
    dst, store = DST('s', mock_agent), MemoryStore()
    store.enable_debug_log(tmp_path / 'debug.log')
    dst.append_event(UserUtterEvent('say hello'))
    mock_agent._llm_mock.generate_chat.side_effect = [
        {'content': 'hello'}, {'content': 'next reply'},
    ]
    runtime = PiAgentRuntime(mock_agent, dst, 's', checkpoint=store.save, store=store)
    callback = AsyncMock()
    runtime.set_channel_callback(callback)
    await runtime.run()
    callback.assert_awaited_once()
    bot = next(e for e in dst.events if e.type == 'bot_utter')
    assert bot.text == 'hello'
    assert bot.payload['llm']['request_id']
    assert [m['role'] for m in dst.context_messages] == ['user', 'assistant']
    assert dst.context_messages[-1]['cotaEventId'] == bot.event_id
    records = await store.model_debug_headers('s')
    assert len(records) == 1
    final = await store.model_debug('s', records[0]['request_id'])
    assert final['response']['content'] == 'hello' and final['event_id'] == bot.event_id
    resumed = await store.load('s', mock_agent)
    resumed.append_event(UserUtterEvent('next'))
    await PiAgentRuntime(mock_agent, resumed, 's', checkpoint=store.save).run()
    messages = mock_agent._llm_mock.generate_chat.call_args.kwargs['messages']
    assert [m['content'] for m in messages if m['role'] == 'assistant'] == ['hello']


def carrier_fixture():
    dst = DST('s', None)
    dst.append_event(Event('run_started', {}, run_id='r'))
    origin = {'request_id': 'q', 'request_sequence': 1, 'stop_reason': 'toolUse',
              'message': {'stop_reason': 'toolUse', 'content': [
                  {'type': 'toolCall', 'id': 'a', 'name': 'lookup', 'arguments': {'city': 'Beijing'}},
                  {'type': 'toolCall', 'id': 'b', 'name': 'lookup', 'arguments': {'city': 'Shanghai'}}]}}
    owner = Event('tool_started', {'tool_call_id': 'a', 'tool': 'lookup', 'arguments': {'city': 'Beijing'}, 'llm': origin}, run_id='r')
    dst.append_event(owner)
    return dst, owner


@pytest.mark.parametrize('change', [
    {'tool_call_id': 'foreign'}, {'tool': 'different'}, {'arguments': {}},
    {'llm_event_id': 'missing'},
])
def test_tool_follower_must_match_original_batch(change):
    dst, owner = carrier_fixture()
    payload = {'tool_call_id': 'b', 'tool': 'lookup', 'arguments': {'city': 'Shanghai'}, 'llm_event_id': owner.event_id, **change}
    before = dst.as_dict()
    with pytest.raises(ValueError):
        dst.append_event(Event('tool_started', payload, run_id='r'))
    assert dst.as_dict() == before


def test_carrier_references_cannot_cross_runs_or_forge_request_identity():
    dst, owner = carrier_fixture()
    with pytest.raises(ValueError, match='own run'):
        dst.append_event(Event('tool_started', {'tool_call_id': 'b', 'tool': 'lookup', 'arguments': {'city': 'Shanghai'},
                                               'llm_event_id': owner.event_id}, run_id='elsewhere'))
    from cota.events import BotUtterEvent
    with pytest.raises(ValueError, match='assistant carrier'):
        dst.append_event(BotUtterEvent('forged', llm={'request_id': 'q', 'request_sequence': 2, 'stop_reason': 'stop'}, run_id='r'))
    with pytest.raises(ValueError, match='own run'):
        dst.append_event(BotUtterEvent('wrong source', tool_event_id=owner.event_id, run_id='elsewhere'))


@pytest.mark.asyncio
@pytest.mark.parametrize('debug', [False, True])
async def test_auxiliary_models_have_no_core_response_and_request_numbers_do_not_collide(tmp_path, debug):
    from cota.llm.observation import model_trace, model_purpose, observe_model_call
    from cota.runtime.pi_trace import PiTraceRecorder
    from unittest.mock import AsyncMock
    dst, store = DST('s', None), MemoryStore()
    dst.append_event(Event('run_started', {}, run_id='r'))
    if debug:
        store.enable_debug_log(tmp_path / 'debug.log')
    recorder = PiTraceRecorder(dst, store)
    async def save():
        await store.save(dst)
    with model_trace(recorder, save):
        with model_purpose('policy'):
            await observe_model_call(AsyncMock(return_value={'content': 'selection'}), {})
        with model_purpose('policy_embedding'):
            assert await observe_model_call(AsyncMock(return_value=[[0.1, 0.2]]), {}) == [[0.1, 0.2]]
        response = await observe_model_call(AsyncMock(return_value={'content': 'hello'}), {})
    event = recorder.observe_assistant(response['_cota_message'])
    await save()
    await recorder.link_model_debug(event)
    assert [e.type for e in dst.events] == ['run_started', 'bot_utter']
    assert event.payload['llm']['request_sequence'] == 3
    assert len(await store.model_debug_headers('s')) == (3 if debug else 0)
    assert DST.from_events('s', dst.events).state_dict() == dst.state_dict()


def test_tool_bot_nullable_metadata_replays_and_is_not_duplicated():
    dst, owner = carrier_fixture()
    dst.append_event(Event('bot_utter', {'text': 'visible', 'metadata': None, 'tool_event_id': owner.event_id}, run_id='r'))
    assert DST.from_events('s', dst.events).state_dict() == dst.state_dict()
    assert len(dst.context_messages) == 1
    assert dst.events[-1].metadata == {}


def test_later_proposed_call_cannot_drop_its_carrier_link():
    dst, owner = carrier_fixture()
    with pytest.raises(ValueError, match='original assistant carrier'):
        dst.append_event(Event('tool_started', {'tool_call_id': 'b', 'tool': 'lookup', 'arguments': {'city': 'Shanghai'}}, run_id='r'))


@pytest.mark.asyncio
@pytest.mark.parametrize('fail_checkpoint', [False, True])
async def test_public_commentary_commits_before_effects_and_is_never_duplicated(mock_agent, fail_checkpoint):
    from cota.executor.tools import FunctionTool
    store, dst = MemoryStore(), DST('commentary', mock_agent)
    dst.append_event(UserUtterEvent('do the work'))
    published, effects = [], []

    async def publish(message):
        saved = await store.event_by_id(dst.session_id, message['event_id'])
        assert saved['payload']['text'] == message['text']
        published.append(message['text'])

    async def effect():
        assert published == ['I will check both resources.']
        effects.append(True)
        return 'checked'

    mock_agent.get_tool_registry().register(FunctionTool('check', 'check', {'type': 'object', 'properties': {}}, effect))
    mock_agent._llm_mock.generate_chat.side_effect = [
        {'content': 'I will check both resources.', 'tool_calls': [call('check', {}, 'a'), call('check', {}, 'b')]},
        {'content': 'All done.'},
    ]

    async def save(tracker):
        if fail_checkpoint and any(e.type == 'tool_started' for e in tracker.events):
            raise OSError('checkpoint unavailable')
        await store.save(tracker)

    runtime = PiAgentRuntime(mock_agent, dst, dst.session_id, checkpoint=save, store=store)
    runtime.set_channel_callback(publish)
    if fail_checkpoint:
        with pytest.raises(OSError, match='checkpoint unavailable'):
            await runtime.run()
        assert not published and not effects
        assert not any(e['type'] == 'bot_utter' for e in (await store.export_session(dst.session_id))['events'])
    else:
        await runtime.run()
        assert published == ['I will check both resources.', 'All done.']
        assert len(effects) == 2
        restored = await store.load(dst.session_id, mock_agent)
        assert restored.context_messages == dst.context_messages
        assert sum('I will check both resources.' in str(m) for m in restored.context_messages) == 1
        progress = next(e for e in dst.events if e.type == 'bot_utter')
        assert [e['payload']['text'] for e in await store.history(dst.session_id)] == [
            'do the work', 'I will check both resources.', 'All done.']
        from cota.events import BotUtterEvent
        with pytest.raises(ValueError, match='Duplicate bot commentary'):
            dst.append_event(BotUtterEvent(progress.text, llm_event_id=progress.payload['llm_event_id'], run_id=progress.run_id))
        with pytest.raises(ValueError, match='carrier text'):
            dst.append_event(BotUtterEvent('forged', llm_event_id=progress.payload['llm_event_id'], run_id=progress.run_id))
