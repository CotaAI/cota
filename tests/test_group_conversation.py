import asyncio
from unittest.mock import AsyncMock

import pytest

from cota.application import Application
from cota.config import validate_bot_config
from cota.channels.events import InboundMessage
from cota.dst import DST
from cota.store import MemoryStore, SQLStore


@pytest.mark.parametrize('mode', ['direct', 'group'])
@pytest.mark.parametrize('response', ['passive', 'proactive'])
def test_dialogue_modes(mode, response):
    validate_bot_config({'dialogue': {'mode': mode, 'response': response}})


@pytest.mark.parametrize('settings', [{'mode': 'agent'}, {'response': 'always'}, {'mode': True}])
def test_bad_dialogue_modes(settings):
    with pytest.raises(ValueError):
        validate_bot_config({'dialogue': settings})


def group_app(agent, store=None, response='passive'):
    agent.dialogue.update(mode='group', response=response)
    agent.cleanup = AsyncMock()
    if store is not None:
        agent.store = store
    app = Application(agent)
    app.group.debounce_seconds = .01
    app.group.judgement_interval = .02
    return app


async def test_passive_history_then_mention_with_speaker_context(mock_agent):
    async with group_app(mock_agent) as app:
        first = await app.submit(user_id='alice', session_id='group', text='去杭州', message_id='a')
        assert (await first.wait())['receipt']['status'] == 'recorded'
        mock_agent._llm_mock.generate_chat.assert_not_awaited()
        second = await app.submit(user_id='bob', session_id='group', text='明天下午', message_id='b')
        await second.wait()
        mention = await app.submit(user_id='alice', session_id='group', text='查天气', message_id='c', mentioned=True)
        result = await mention.wait()
        assert result['receipt']['status'] == 'completed'
        request = mock_agent._llm_mock.generate_chat.call_args.kwargs
        text = str(request['messages'])
        assert all(s in text for s in ('alice', 'bob', '去杭州', '明天下午', '查天气'))
        events = await app.store.history('group', include_execution=True)
        assert len([e for e in events if e['type'] == 'run_started']) == 1
        history = await app.history('group')
        assert history['messages'][0]['sender_id'] == 'alice'
        duplicate = await app.submit(user_id='alice', session_id='group', text='查天气', message_id='c', mentioned=True)
        assert duplicate.duplicate
        assert await duplicate.wait() == result
        assert mock_agent._llm_mock.generate_chat.await_count == 1
        with pytest.raises(ValueError, match='message_id'):
            await app.submit(user_id='alice', session_id='group', text='查天气', message_id='c', mentioned=False)


@pytest.mark.parametrize('sql', [False, True])
async def test_group_receives_during_model_without_changing_its_context(mock_agent, tmp_path, sql):
    store = SQLStore(dialect='sqlite', db=str(tmp_path/'group.db')) if sql else MemoryStore()
    entered, release = asyncio.Event(), asyncio.Event()
    async def model(**kwargs):
        entered.set()
        await release.wait()
        return {'content': 'answer'}
    mock_agent._llm_mock.generate_chat.side_effect = model
    async with group_app(mock_agent, store) as app:
        first = await app.submit(user_id='alice', session_id='g', text='first', message_id='1', mentioned=True)
        await asyncio.wait_for(entered.wait(), 10)
        try:
            second = await asyncio.wait_for(app.submit(user_id='bob', session_id='g', text='later', message_id='2'), 1)
            assert (await second.wait())['receipt']['status'] == 'recorded'
            assert 'later' in str((await app.history('g'))['messages'])
        finally:
            release.set()
        await first.wait()
        assert 'later' not in str(mock_agent._llm_mock.generate_chat.call_args.kwargs['messages'])
        events = await store.history('g', include_execution=True)
        assert [e['sequence'] for e in events] == list(range(1, len(events)+1))
        loaded = await store.load('g', agent=mock_agent)
        replayed = DST.from_events('g', events, agent=mock_agent, run_metadata=loaded.run_metadata)
        assert replayed.state_dict() == loaded.state_dict()
        assert [m['text'] for m in (await app.history('g'))['messages']] == ['first', 'later', 'answer']


async def test_private_memory_is_neither_loaded_nor_exposed_as_tools(mock_agent):
    memory = AsyncMock()
    memory.aget_all.return_value = {'secret': 'PRIVATE_PERSONAL_FACT'}
    mock_agent.user_memory = memory
    async with group_app(mock_agent) as app:
        await (await app.submit(user_id='alice', session_id='g', text='hello', mentioned=True)).wait()
        memory.aget_all.assert_not_awaited()
        request = mock_agent._llm_mock.generate_chat.call_args.kwargs
        assert 'PRIVATE_PERSONAL_FACT' not in str(request)
        names = [t['function']['name'] for t in request['tools']]
        assert not {'memory_read', 'memory_write'} & set(names)
        assert (await app.store.load('g', mock_agent)).user_context == {}


async def test_queued_mentions_keep_their_own_trigger_and_future_input_is_not_exposed(mock_agent):
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []
    async def model(**kwargs):
        calls.append(kwargs['messages'])
        if len(calls) == 1:
            entered.set()
            await release.wait()
        return {'content': 'answer'}
    mock_agent._llm_mock.generate_chat.side_effect = model
    async with group_app(mock_agent) as app:
        a = await app.submit(user_id='alice', session_id='g', text='first', message_id='a', mentioned=True)
        await asyncio.wait_for(entered.wait(), 10)
        try:
            b = await app.submit(user_id='bob', session_id='g', text='second', message_id='b', mentioned=True)
            c = await app.submit(user_id='carol', session_id='g', text='future-message', message_id='c')
            assert (await c.wait())['receipt']['status'] == 'recorded'
        finally:
            release.set()
        assert (await a.wait())['receipt']['status'] == 'completed'
        assert (await b.wait())['receipt']['status'] == 'completed'
        assert len(calls) == 2 and 'future-message' not in str(calls)
        assert 'second' not in str(calls[0]) and 'second' in str(calls[1])
        history = await app.store.history('g', include_execution=True)
        runs = [e for e in history if e['type'] == 'run_started']
        assert runs[0]['payload']['input_event_id'] != runs[1]['payload']['input_event_id']
        replay = DST.from_events('g', history, agent=mock_agent,
                                 run_metadata=(await app.store.load('g', mock_agent)).run_metadata)
        assert replay.context_messages[-1]['role'] == 'user'
        assert 'future-message' in replay.context_messages[-1]['content']


@pytest.mark.parametrize('judgement', ['NO', 'YES', 'maybe'])
async def test_proactive_judgement_does_not_run_tools_unless_selected(mock_agent, judgement):
    mock_agent._llm_mock.generate_chat.side_effect = [{'content': judgement}, {'content': 'helpful answer'}]
    async with group_app(mock_agent, response='proactive') as app:
        result = await (await app.submit(user_id='alice', session_id='g', text='help', message_id='p')).wait()
        assert result['receipt']['status'] == ('completed' if judgement == 'YES' else 'recorded')
        requests = list(mock_agent._llm_mock.generate_chat.call_args_list)
        assert len(requests) == (2 if judgement == 'YES' else 1)
        assert 'tools' not in requests[0].kwargs
        # Duplicates never reevaluate. Only an actual reply starts speech cooldown.
        await (await app.submit(user_id='alice', session_id='g', text='help', message_id='p')).wait()
        assert mock_agent._llm_mock.generate_chat.await_count == len(requests)
        mock_agent._llm_mock.generate_chat.side_effect = None
        mock_agent._llm_mock.generate_chat.return_value = {'content': 'NO'}
        await (await app.submit(user_id='bob', session_id='g', text='more')).wait()
        assert mock_agent._llm_mock.generate_chat.await_count == len(requests) + (judgement != 'YES')


async def test_group_mode_change_requires_new_session(mock_agent):
    mock_agent.cleanup = AsyncMock()
    app = Application(mock_agent)
    async with app:
        await (await app.submit(user_id='a', session_id='s', text='direct')).wait()
        mock_agent.dialogue['mode'] = 'group'
        with pytest.raises(ValueError, match='new session'):
            await app.submit(user_id='a', session_id='s', text='group')


async def test_direct_context_stays_plain(mock_agent):
    mock_agent.cleanup = AsyncMock()
    async with Application(mock_agent) as app:
        await (await app.submit(user_id='alice', session_id='s', text='plain text')).wait()
    users = [m for m in mock_agent._llm_mock.generate_chat.call_args.kwargs['messages'] if m['role'] == 'user']
    assert users == [{'role': 'user', 'content': 'plain text'}]


async def test_input_during_tool_keeps_protocol_valid_and_reply_sequence_canonical(mock_agent):
    from cota.executor.tools.base import FunctionTool
    from tests.test_pi_runtime import call
    entered, release = asyncio.Event(), asyncio.Event()
    async def slow():
        entered.set()
        await release.wait()
        return {'value': 'tool-result'}
    mock_agent._tool_registry.register(FunctionTool('slow', 'slow', {'type': 'object', 'properties': {}}, slow))
    mock_agent._llm_mock.generate_chat.side_effect = [
        {'tool_calls': [call('slow', {})]}, {'content': 'done'}, {'content': 'next answer'}]
    callback = AsyncMock()
    async with group_app(mock_agent) as app:
        first = await app.submit_message(InboundMessage('web', 'alice', 'g', 'start', mentioned=True), on_reply=callback)
        await asyncio.wait_for(entered.wait(), 10)
        try:
            await asyncio.wait_for(app.submit(user_id='bob', session_id='web:g', text='during-tool'), 1)
        finally:
            release.set()
        assert (await first.wait())['receipt']['status'] == 'completed'
        sent = callback.call_args.args[0]
        actual = await app.store.event_by_id('web:g', sent['event_id'])
        assert sent['sequence'] == actual['sequence']
        second_request = mock_agent._llm_mock.generate_chat.call_args_list[1].kwargs['messages']
        assert 'during-tool' not in str(second_request)
        await (await app.submit(user_id='bob', session_id='web:g', text='followup', mentioned=True)).wait()
        messages = mock_agent._llm_mock.generate_chat.call_args.kwargs['messages']
        assert 'during-tool' in str(messages)
        tool_index = next(i for i, m in enumerate(messages) if m.get('tool_calls'))
        assert messages[tool_index+1]['role'] == 'tool'
        assert 'without a recorded result' not in str(messages)


async def test_recorded_messages_survive_reopen_and_no_model_is_replayed(mock_agent, tmp_path):
    db = str(tmp_path/'restart.db')
    async with group_app(mock_agent, SQLStore(dialect='sqlite', db=db)) as app:
        await (await app.submit(user_id='alice', session_id='g', text='background', message_id='m')).wait()
    async with group_app(mock_agent, SQLStore(dialect='sqlite', db=db)) as app:
        result = await (await app.submit(user_id='alice', session_id='g', text='background', message_id='m')).wait()
        assert result['receipt']['status'] == 'recorded'
        mock_agent._llm_mock.generate_chat.assert_not_awaited()
        await (await app.submit(user_id='bob', session_id='g', text='help', mentioned=True)).wait()
        assert 'background' in str(mock_agent._llm_mock.generate_chat.call_args.kwargs['messages'])


async def test_proactive_failure_is_recorded_and_mention_bypasses_cooldown(mock_agent):
    mock_agent._llm_mock.generate_chat.side_effect = [RuntimeError('offline'), {'content': 'mention answer'}]
    async with group_app(mock_agent, response='proactive') as app:
        result = await (await app.submit(user_id='a', session_id='g', text='help')).wait()
        assert result['receipt']['status'] == 'recorded'
        result = await (await app.submit(user_id='a', session_id='g', text='explicit help', mentioned=True)).wait()
        assert result['receipt']['status'] == 'completed'
        assert mock_agent._llm_mock.generate_chat.await_count == 2


async def test_queued_proactive_messages_coalesce(mock_agent):
    mock_agent._llm_mock.generate_chat.return_value = {'content': 'NO'}
    async with group_app(mock_agent, response='proactive') as app:
        submissions = [await app.submit(user_id='a', session_id='g', text=f'message {i}') for i in range(5)]
        await asyncio.gather(*(s.wait() for s in submissions))
        assert mock_agent._llm_mock.generate_chat.await_count == 1
        assert len((await app.history('g'))['messages']) == 5


async def test_full_execution_queue_keeps_group_receiving_and_mention_retry_is_safe(mock_agent):
    entered, release = asyncio.Event(), asyncio.Event()
    async def model(**kwargs):
        entered.set()
        await release.wait()
        return {'content': 'done'}
    mock_agent._llm_mock.generate_chat.side_effect = model
    mock_agent.dialogue['mode'] = 'group'
    mock_agent.cleanup = AsyncMock()
    async with Application(mock_agent, max_pending=1) as app:
        first = await app.submit(user_id='a', session_id='g', text='start', mentioned=True)
        await asyncio.wait_for(entered.wait(), 10)
        try:
            await (await app.submit(user_id='b', session_id='g', text='ordinary')).wait()
            with pytest.raises(asyncio.QueueFull):
                await app.submit(user_id='b', session_id='g', text='next', message_id='next', mentioned=True)
            assert (await app.receipt('g', 'next'))['status'] == 'recorded'
        finally:
            release.set()
        await first.wait()
        await (await app.submit(user_id='b', session_id='g', text='next', message_id='next', mentioned=True)).wait()
        messages = (await app.history('g'))['messages']
        assert len([m for m in messages if m['message_id'] == 'next']) == 1
        assert mock_agent._llm_mock.generate_chat.await_count == 2


@pytest.mark.parametrize('sql', [False, True])
async def test_compaction_merges_with_concurrent_input_and_replays(mock_agent, tmp_path, sql):
    store = SQLStore(dialect='sqlite', db=str(tmp_path/'compact.db'), snapshot_interval=2) if sql else MemoryStore(snapshot_interval=2)
    mock_agent._llm_mock.context_window = 5000
    mock_agent.dialogue.update(prompt='Help the group.', compaction={'reserve_tokens': 1000, 'keep_recent_tokens': 1000})
    compacted = False
    async with group_app(mock_agent, store) as app:
        async def model(**kwargs):
            nonlocal compacted
            if 'context summarization assistant' in kwargs['messages'][0]['content']:
                compacted = True
                await app.submit(user_id='bob', session_id='g', text='concurrent-during-summary')
                return {'content': 'Alice discussed the trip; preserve Alice as the speaker.'}
            assert 'concurrent-during-summary' not in str(kwargs['messages'])
            return {'content': 'answer'}
        mock_agent._llm_mock.generate_chat.side_effect = model
        for i in range(6):
            await (await app.submit(user_id='alice', session_id='g', text=f'topic{i} ' + 'x'*2500)).wait()
        result = await (await app.submit(user_id='alice', session_id='g', text='please help', mentioned=True)).wait()
        assert result['receipt']['status'] == 'completed'
        assert compacted
        loaded = await store.load('g', agent=mock_agent)
        facts = await store.history('g', include_execution=True)
        replayed = DST.from_events('g', facts, agent=mock_agent, run_metadata=loaded.run_metadata)
        assert replayed.state_dict() == loaded.state_dict()
        assert 'concurrent-during-summary' in loaded.context_messages[-1]['content']
        assert 'speaker' in str(mock_agent._llm_mock.generate_chat.call_args_list[0].kwargs['messages'])


async def test_unfinished_group_run_after_restart_is_interrupted_not_recorded(mock_agent, tmp_path):
    from cota.events import Event
    from cota.inputs import input_event_id
    db = str(tmp_path/'unfinished.db')
    store = SQLStore(dialect='sqlite', db=db)
    async with group_app(mock_agent, store) as app:
        await (await app.submit(user_id='a', session_id='g', text='background', message_id='m')).wait()
        tracker = await store.load('g', mock_agent)
        tracker.append_event(Event('run_started', {'input_event_id': input_event_id('m'), 'mode': 'group',
                                                   'reason': 'proactive', 'context_through': 1}, run_id='unfinished'))
        await store.save(tracker)
    reopened = SQLStore(dialect='sqlite', db=db)
    receipt = await reopened.input_receipt('g', 'm')
    assert receipt['status'] == 'interrupted'
    assert receipt['run_id'] == 'unfinished'


async def test_retry_recorded_mention_after_a_newer_completed_run(mock_agent):
    entered, release = asyncio.Event(), asyncio.Event()
    async def model(**kwargs):
        entered.set()
        await release.wait()
        return {'content': 'done'}
    mock_agent.dialogue['mode'] = 'group'
    mock_agent.cleanup = AsyncMock()
    mock_agent._llm_mock.generate_chat.side_effect = model
    async with Application(mock_agent, max_pending=1) as app:
        first = await app.submit(user_id='x', session_id='g', text='first', mentioned=True)
        await asyncio.wait_for(entered.wait(), 10)
        try:
            with pytest.raises(asyncio.QueueFull):
                await app.submit(user_id='a', session_id='g', text='older question', message_id='a', mentioned=True)
        finally:
            release.set()
        await first.wait()
        await (await app.submit(user_id='b', session_id='g', text='newer question', message_id='b', mentioned=True)).wait()
        retried = await app.submit(user_id='a', session_id='g', text='older question', message_id='a', mentioned=True)
        result = await retried.wait()
        assert result['receipt']['status'] == 'completed'
        assert mock_agent._llm_mock.generate_chat.await_count == 3
        users = [m for m in mock_agent._llm_mock.generate_chat.call_args.kwargs['messages'] if m['role'] == 'user']
        assert 'older question' in users[-1]['content']


async def test_group_pre_run_failure_is_visible_in_submission(mock_agent, monkeypatch):
    from cota.processor import Processor
    async def fail(*args, **kwargs):
        raise RuntimeError('private provider setup error')
    monkeypatch.setattr(Processor, '_create_runtime', fail)
    async with group_app(mock_agent) as app:
        result = await (await app.submit(user_id='a', session_id='g', text='help', mentioned=True)).wait()
        assert result['receipt']['status'] == 'failed'
        assert result['receipt']['error'] == 'execution_failed'
        assert 'private provider' not in str(result)
        assert len((await app.history('g'))['messages']) == 1


async def test_multiple_late_retries_keep_current_trigger_last(mock_agent):
    entered, release = asyncio.Event(), asyncio.Event()
    async def model(**kwargs):
        entered.set()
        await release.wait()
        return {'content': 'done'}
    mock_agent.dialogue['mode'] = 'group'
    mock_agent.cleanup = AsyncMock()
    mock_agent._llm_mock.generate_chat.side_effect = model
    async with Application(mock_agent, max_pending=1) as app:
        first = await app.submit(user_id='x', session_id='g', text='first', mentioned=True)
        await asyncio.wait_for(entered.wait(), 10)
        try:
            for letter in ('a', 'b'):
                with pytest.raises(asyncio.QueueFull):
                    await app.submit(user_id=letter, session_id='g', text=f'question {letter}', message_id=letter, mentioned=True)
        finally:
            release.set()
        await first.wait()
        await (await app.submit(user_id='c', session_id='g', text='question c', mentioned=True)).wait()
        for letter in ('a', 'b'):
            result = await (await app.submit(user_id=letter, session_id='g', text=f'question {letter}', message_id=letter, mentioned=True)).wait()
            assert result['receipt']['status'] == 'completed'
            users = [m for m in mock_agent._llm_mock.generate_chat.call_args.kwargs['messages'] if m['role'] == 'user']
            assert f'question {letter}' in users[-1]['content']


async def test_proactive_judgement_debug_record_has_no_fake_run(mock_agent, tmp_path):
    store = MemoryStore()
    store.enable_debug_log(str(tmp_path/'debug.jsonl'))
    mock_agent._llm_mock.generate_chat.return_value = {'content': 'NO'}
    async with group_app(mock_agent, store, response='proactive') as app:
        await (await app.submit(user_id='a', session_id='g', text='hello')).wait()
        records = await store.model_debug_headers('g')
        assert len(records) == 1
        diagnostic = await store.model_debug('g', records[0]['request_id'])
        assert diagnostic['purpose'] == 'participation'
        assert diagnostic['run_id'] is None
        assert diagnostic['response']['content'] == 'NO'
        assert 'hello' in str(diagnostic['request'])
        assert [e['type'] for e in await store.history('g', include_execution=True)] == ['user_utter']


def test_execution_view_retains_previous_runs_context_boundary(mock_agent):
    from cota.events import Event, UserUtterEvent
    from cota.group import execution_view
    tracker = DST('g', mock_agent)
    for identity in ('old-trigger', 'retry-trigger', 'context-boundary'):
        tracker.append_event(UserUtterEvent(text=identity, event_id=identity,
            metadata={'mode': 'group', 'sender_id': 'alice'}))
    tracker.append_event(Event('run_started', {'mode': 'group', 'reason': 'mention',
        'input_event_id': 'old-trigger', 'context_input_id': 'context-boundary', 'context_through': 3}, run_id='old-run'))
    tracker.append_event(Event('run_finished', {'status': 'completed'}))
    view, through, boundary = execution_view(tracker, 'retry-trigger')
    assert boundary == 'context-boundary'
    assert through == 3
    assert any(e.event_id == 'context-boundary' for e in view.events)


async def test_proactive_judgement_sees_previous_bot_answers(mock_agent):
    mock_agent._llm_mock.generate_chat.side_effect = [{'content': 'already answered weather'}, {'content': 'NO'}]
    async with group_app(mock_agent, response='proactive') as app:
        app.group.cooldown_seconds = 0
        await (await app.submit(user_id='a', session_id='g', text='weather?', mentioned=True)).wait()
        await (await app.submit(user_id='b', session_id='g', text='thanks')).wait()
        judgement = mock_agent._llm_mock.generate_chat.call_args.kwargs['messages']
        assert 'already answered weather' in str(judgement)
        assert 'bot' in str(judgement)


async def test_proactive_supports_bot_without_description_or_custom_prompt(mock_agent):
    mock_agent.description = None
    mock_agent.dialogue.pop('prompt', None)
    mock_agent._llm_mock.generate_chat.return_value = {'content': 'NO'}
    async with group_app(mock_agent, response='proactive') as app:
        result = await (await app.submit(user_id='a', session_id='g', text='hello')).wait()
        assert result['receipt']['status'] == 'recorded'
        mock_agent._llm_mock.generate_chat.assert_awaited_once()


async def test_file_loaded_default_bot_can_start_application(tmp_path, monkeypatch):
    from cota.agent import Agent
    monkeypatch.setattr('cota.agent.create_user_memory', lambda _: None)
    (tmp_path/'agent.yml').write_text('system:\n  name: default-mode\n')
    (tmp_path/'endpoints.yml').write_text('{}')
    agent = Agent.load_from_path(str(tmp_path))
    assert agent.dialogue['mode'] == 'direct'
    assert agent.dialogue['response'] == 'passive'
    async with Application(agent) as app:
        assert app._started
