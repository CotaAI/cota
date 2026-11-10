from cota.events.tool import result_content
"""Real Node/Pi loop with deterministic Python model and tool callbacks."""
import asyncio
from unittest.mock import AsyncMock

import pytest
from cota.events.resources import skill_read_name

from cota.events import Event, UserUtterEvent
from tests.resource_fixtures import skill_result
from cota.dst import DST
from cota.store import MemoryStore, SQLStore
from cota.runtime.pi_runtime import PiAgentRuntime, RunInProgress
from cota.executor.tools.base import FunctionTool, create_tool_schema


def call(name, arguments, id=None):
    import json
    from uuid import uuid4
    id = id or uuid4().hex
    return {'id': id, 'type': 'function', 'function': {'name': name, 'arguments': json.dumps(arguments)}}


def make_runtime(agent, store, dst):
    return PiAgentRuntime(agent=agent, dst=dst, session_id=dst.session_id,
                          checkpoint=store.save, max_iterations=5)


@pytest.mark.asyncio
async def test_full_tool_trace_and_context_survive_new_runtime(mock_agent, tmp_path):
    store = SQLStore(db=str(tmp_path / 'pi.db'))
    dst = DST('s', mock_agent)
    dst.append_event(UserUtterEvent('search'))
    mock_agent._llm_mock.generate_chat.side_effect = [
        {'tool_calls': [call('read', {'path': mock_agent.skill_file('SearchWeb')})]},
        {'content': 'answer'}, {'content': 'followup'},
    ]
    await make_runtime(mock_agent, store, dst).run()
    stored = await store.export_session('s')
    results = [e['payload'] for e in stored['events'] if e['type'] == 'tool_result']
    assert results and result_content(results[0])
    assert any(m['role'] == 'toolResult' for m in stored['context_messages'])
    assert stored['execution']['status'] == 'completed'
    assert dst.active_skill == 'SearchWeb'
    assert any(skill_read_name(e) for e in dst.events)
    restored = await store.load('s', agent=mock_agent)
    restored.append_event(UserUtterEvent('continue'))
    await make_runtime(mock_agent, store, restored).run()
    messages = mock_agent._llm_mock.generate_chat.call_args.kwargs['messages']
    assert any(m.get('role') == 'tool' for m in messages)
    assert any(m.get('content') == 'answer' for m in messages)
    assert [e['payload']['text'] for e in await store.history('s')] == ['search', 'answer', 'continue', 'followup']
    store.engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize('backend', ['memory', 'sqlite'])
async def test_plain_question_completes_and_next_input_starts_new_run(mock_agent, tmp_path, backend):
    store = MemoryStore() if backend == 'memory' else SQLStore(db=str(tmp_path / 'question.db'))
    dst = DST('s', mock_agent)
    dst.append_event(UserUtterEvent('weather'))
    mock_agent._llm_mock.generate_chat.side_effect = [
        {'content': 'which city?'}, {'content': 'Beijing is sunny'},
    ]
    await make_runtime(mock_agent, store, dst).run()
    first_run = dst.execution['run_id']
    assert dst.execution['status'] == 'completed'
    assert dst.latest_bot_text() == 'which city?'
    assert dst.execution['pending_tools'] == {}
    assert not any(e.type == 'tool_result' for e in dst.events)
    snapshot = await store.snapshot('s')
    assert snapshot['state'] == dst.state_dict()
    assert snapshot['last_sequence'] == len(dst.events)
    assert DST.from_events('s', dst.events).state_dict() == dst.state_dict()
    # A saved answer does not prove that the final run checkpoint completed.
    answer_index = next(i for i, e in enumerate(dst.events) if e.type == 'bot_utter')
    incomplete = DST.from_events('s', dst.events[:answer_index + 1], mock_agent)
    assert incomplete.execution['status'] == 'running'
    with pytest.raises(RunInProgress):
        await make_runtime(mock_agent, store, incomplete).run()
    restored = await store.load('s', agent=mock_agent)
    before = restored.as_dict()
    await make_runtime(mock_agent, store, restored).run()
    assert restored.as_dict() == before
    assert mock_agent._llm_mock.generate_chat.await_count == 1
    restored.append_event(UserUtterEvent('Beijing'))
    await make_runtime(mock_agent, store, restored).run()
    assert restored.execution['run_id'] != first_run
    assert restored.execution['status'] == 'completed'
    assert restored.latest_bot_text() == 'Beijing is sunny'
    assert mock_agent._llm_mock.generate_chat.await_count == 2
    assert [e['payload']['text'] for e in await store.history('s')] == ['weather', 'which city?', 'Beijing', 'Beijing is sunny']
    if backend == 'sqlite':
        store.engine.dispose()


@pytest.mark.asyncio
async def test_policy_does_not_rewrite_user_input(mock_agent):
    store = MemoryStore()
    dst = DST('s', mock_agent)
    dst.append_event(UserUtterEvent('hello'))
    from cota.policy import PolicyCatalog, AllPolicy
    mock_agent.policy = AllPolicy(PolicyCatalog([{'name': 'reference', 'steps': [{'user': 'Applicable request'}, {'bot': [{'thought': 'business guidance'}, {'skills': ['SearchWeb']}]}]}]))
    await make_runtime(mock_agent, store, dst).run()
    messages = mock_agent._llm_mock.generate_chat.call_args.kwargs['messages']
    assert [m['content'] for m in messages if m['role'] == 'user'] == ['hello']
    assert 'business guidance' in messages[0]['content']
    output = next(e for e in dst.events if e.type == 'bot_utter' and e.payload.get('llm'))
    assert output.payload['llm']['policy']['policies'][0]['name'] == 'reference'
    assert 'business guidance' not in str(dst.context_messages)


@pytest.mark.asyncio
async def test_checkpoint_failure_stops_before_side_effect(mock_agent):
    store = MemoryStore()
    dst = DST('s', mock_agent)
    dst.append_event(UserUtterEvent('go'))
    effect = AsyncMock(return_value={'ok': True})
    mock_agent._tool_registry.register(FunctionTool('effect', 'effect', create_tool_schema({}), effect))
    mock_agent._llm_mock.generate_chat.return_value = {'tool_calls': [call('effect', {})]}
    async def checkpoint(tracker):
        if any(e.type == 'tool_started' and e.payload.get('llm') for e in tracker.events):
            raise OSError('disk full')
        await store.save(tracker)
    runtime = PiAgentRuntime(agent=mock_agent, dst=dst, session_id='s', checkpoint=checkpoint)
    with pytest.raises(OSError, match='disk full'):
        await runtime.run()
    effect.assert_not_awaited()


@pytest.mark.asyncio
async def test_running_run_is_not_presumed_abandoned(mock_agent):
    store = MemoryStore()
    dst = DST('s', mock_agent)
    dst.append_event(Event('run_started', {'engine': 'pi'}, run_id='old'))
    dst.append_event(UserUtterEvent('retry'))
    with pytest.raises(RunInProgress):
        await make_runtime(mock_agent, store, dst).run()
    mock_agent._llm_mock.generate_chat.assert_not_awaited()


@pytest.mark.asyncio
async def test_reply_callbacks_are_isolated_and_visible_in_history(mock_agent):
    store = MemoryStore()
    a, b = DST('a', mock_agent), DST('b', mock_agent)
    for dst in (a, b):
        dst.append_event(Event('run_started', {}, run_id='prior-read'))
        dst.append_event(skill_result('SearchWeb'))
        dst.append_event(Event('run_finished', {'status': 'completed'}))
        dst.append_event(UserUtterEvent('reply'))
    ra, rb = make_runtime(mock_agent, store, a), make_runtime(mock_agent, store, b)
    ca, cb = AsyncMock(), AsyncMock()
    ra.set_channel_callback(ca)
    rb.set_channel_callback(cb)
    mock_agent._llm_mock.generate_chat.side_effect = [
        {'content': 'for a'},
    ]
    await ra.run()
    ca.assert_awaited_once()
    cb.assert_not_awaited()
    assert [e['payload']['text'] for e in await store.history('a')] == ['reply', 'for a']


@pytest.mark.asyncio
async def test_cancelled_model_call_records_interruption(mock_agent):
    store = MemoryStore()
    dst = DST('s', mock_agent)
    dst.append_event(UserUtterEvent('go'))
    started = asyncio.Event()
    async def model(**kwargs):
        started.set()
        await asyncio.Event().wait()
    mock_agent._llm_mock.generate_chat.side_effect = model
    task = asyncio.create_task(make_runtime(mock_agent, store, dst).run())
    await asyncio.wait_for(started.wait(), 10)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert (await store.export_session('s'))['execution']['status'] == 'interrupted'


@pytest.mark.asyncio
async def test_compaction_preserves_raw_events_and_reuses_projection(mock_agent):
    from cota.events import BotUtterEvent
    store = MemoryStore()
    dst = DST('s', mock_agent)
    history = []
    for n in range(2):
        question = f'old {n} ' + 'x' * 4000
        dst.append_event(UserUtterEvent(question))
        dst.append_event(BotUtterEvent('old answer'))
        history += [{'role': 'user', 'content': question}, {'role': 'assistant', 'content': 'old answer'}]
    original_ids = [e.event_id for e in dst.events]
    dst.append_event(Event('run_started', {'engine': 'pi', 'input_event_id': dst.latest_user_event.event_id}, run_id='previous-run'))
    dst.append_event(Event('run_finished', {'status': 'completed'}))
    dst.append_event(UserUtterEvent('current'))
    mock_agent._llm_mock.context_window = 3000
    mock_agent.dialogue['compaction'] = {'reserve_tokens': 1000, 'keep_recent_tokens': 300}
    mock_agent._llm_mock.generate_chat.side_effect = [{'content': 'historical facts'}, {'content': 'done'}]
    rt = PiAgentRuntime(agent=mock_agent, dst=dst, session_id='s', prompt='sys', checkpoint=store.save)
    await rt.run()
    assert [e.event_id for e in dst.events[:4]] == original_ids
    assert len(dst.events[0].text) > 4000
    projected = str(dst.context_messages)
    assert 'historical facts' in projected
    assert 'old 0 ' + 'x' * 4000 not in projected
    assert any(e.type == 'context_compaction' for e in dst.events)


@pytest.mark.asyncio
async def test_model_failure_ends_run_and_propagates(mock_agent):
    store = MemoryStore()
    dst = DST('s', mock_agent)
    dst.append_event(UserUtterEvent('go'))
    mock_agent._llm_mock.generate_chat.side_effect = RuntimeError('model unavailable')
    with pytest.raises(RuntimeError, match='model unavailable'):
        await make_runtime(mock_agent, store, dst).run()
    assert (await store.export_session('s'))['execution']['status'] == 'failed'


@pytest.mark.asyncio
async def test_tool_policy_is_enforced_at_execution_boundary(mock_agent):
    from cota.executor.tools.registry import ToolPolicy
    store = MemoryStore()
    dst = DST('s', mock_agent)
    dst.append_event(UserUtterEvent('go'))
    effect = AsyncMock(return_value={'ok': True})
    mock_agent._tool_registry.register(FunctionTool('effect', 'effect', create_tool_schema({}), effect))
    mock_agent._tool_registry.set_policy(ToolPolicy(deny=['effect']))
    mock_agent._llm_mock.generate_chat.side_effect = [{'tool_calls': [call('effect', {})]}, {'content': 'denied'}]
    await make_runtime(mock_agent, store, dst).run()
    effect.assert_not_awaited()
    assert any(m.get('isError') for m in dst.context_messages)


@pytest.mark.asyncio
async def test_native_pi_tool_result_reaches_model_as_image(mock_agent):
    data = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jK1sAAAAASUVORK5CYII='
    handler = AsyncMock(return_value={
        'content': [{'type': 'image', 'data': data, 'mimeType': 'image/png'}],
        'details': {'source': 'screen'},
    })
    mock_agent._tool_registry.register(FunctionTool('screen', 'screen', create_tool_schema({}), handler))
    mock_agent._tool_registry.register(FunctionTool('noop', 'noop', create_tool_schema({}), AsyncMock(return_value={})))
    mock_agent._llm_mock.generate_chat.side_effect = [
        {'tool_calls': [call('screen', {}), call('noop', {}, 'tc2')]}, {'content': 'I see the image'},
    ]
    dst = DST('s', mock_agent)
    dst.append_event(UserUtterEvent('look'))
    await make_runtime(mock_agent, MemoryStore(), dst).run()
    messages = mock_agent._llm_mock.generate_chat.call_args.kwargs['messages']
    assert any(m['role'] == 'user' and isinstance(m['content'], list) and
               m['content'][0].get('image_url', {}).get('url') == 'data:image/png;base64,' + data for m in messages)
    tool_indices = [i for i, m in enumerate(messages) if m['role'] == 'tool']
    image_index = next(i for i, m in enumerate(messages) if m['role'] == 'user' and isinstance(m['content'], list))
    assert image_index > max(tool_indices)
