from cota.events.tool import result_content
"""Trace facts must match the real Pi loop and survive its failure boundaries."""
import asyncio
from unittest.mock import AsyncMock

import pytest
from cota.events.resources import skill_read_name

from cota.dst import DST
from cota.events import UserUtterEvent
from cota.executor.tools.base import FunctionTool, create_tool_schema
from cota.runtime.pi_runtime import PiAgentRuntime
from cota.store import MemoryStore
from tests.test_pi_runtime import call


@pytest.mark.asyncio
async def test_run_trace_has_one_result_per_call_and_no_last_read_ownership(mock_agent):
    mock_agent.add_skill('travel', 'Use travel instructions.')
    effect = AsyncMock(return_value={'success': True, 'value': []})
    mock_agent.get_tool_registry().register(FunctionTool('effect', 'effect', create_tool_schema({}), effect))
    mock_agent._llm_mock.generate_chat.side_effect = [
        {'tool_calls': [call('read', {'path': mock_agent.skill_file('SearchWeb'), 'limit': 2}, 's')]},
        {'tool_calls': [call('read', {'path': mock_agent.skill_file('travel')}, 't')]},
        {'tool_calls': [call('effect', {}, 'e')]}, {'content': 'done'},
    ]
    dst, store = DST('trace', mock_agent), MemoryStore()
    dst.append_event(UserUtterEvent('combine'))
    await PiAgentRuntime(mock_agent, dst, 'trace', checkpoint=store.save).run()
    kinds = [e.type for e in dst.events]
    assert kinds.count('run_started') == kinds.count('run_finished') == 1
    assert kinds.count('tool_result') == 3
    assert 'tool_finished' not in kinds
    results = [e for e in dst.events if e.type == 'tool_result']
    assert all(e.payload['duration_ms'] >= 0 and e.payload['status'] == 'success' for e in results)
    assert dst.execution['pending_tools'] == {}
    reads = [e for e in dst.events if skill_read_name(e)]
    assert [e.payload['resource']['skill'] for e in reads] == ['SearchWeb', 'travel']
    assert reads[0].payload['resource']['range']['limit'] == 2
    assert reads[0].payload['resource']['hash'].startswith('sha256:')
    effect_result = next(e for e in dst.events if e.type == 'tool_result' and e.payload['tool'] == 'effect')
    assert 'skill' not in effect_result.payload
    assert effect_result.payload['result']['value'] == []
    assert not any(e.type == 'execution' for e in dst.events)


@pytest.mark.asyncio
@pytest.mark.parametrize('tool,args', [('missing', {}), ('read', {}), ('read', {'path': {}})])
async def test_pi_rejected_call_has_one_durable_result(mock_agent, tool, args):
    mock_agent._llm_mock.generate_chat.side_effect = [
        {'tool_calls': [call(tool, args, 'rejected')]}, {'content': 'cannot execute'},
    ]
    dst, store = DST('rejected', mock_agent), MemoryStore()
    dst.append_event(UserUtterEvent('go'))
    await PiAgentRuntime(mock_agent, dst, dst.session_id, checkpoint=store.save).run()
    results = [e for e in dst.events if e.type == 'tool_result']
    assert len(results) == 1
    result = results[0]
    assert result.payload['status'] in ('error', 'blocked')
    assert result.payload['status'] == 'blocked'
    assert 'arguments' not in result.payload
    assert dst.trace(dst.execution['run_id'])['calls'][0]['arguments'] == args
    assert dst.execution['pending_tools'] == {}
    messages = [m for m in dst.context_messages if m['role'] == 'toolResult']
    assert len(messages) == 1 and messages[0]['cotaResultEventId'] == result.event_id
    assert (await store.load(dst.session_id)).state_dict() == dst.state_dict()
    assert dst.trace(dst.execution['run_id'])['calls'][0]['status'] == 'blocked'


def test_pi_end_acknowledges_result_without_rewriting_it():
    from cota.events import Event
    from cota.runtime.pi_trace import PiTraceRecorder
    dst = DST('ack', None)
    dst.append_event(Event('run_started', {}, run_id='r'))
    dst.append_event(Event('tool_started', {'tool': 'exec', 'tool_call_id': 'c', 'arguments': {}}))
    trace = PiTraceRecorder(dst)
    model = {'content': [{'type': 'text', 'text': 'done'}], 'details': {'value': True}, 'isError': False}
    result = trace.result('c', 'exec', {}, {'value': True}, model)
    assert dst.execution['pending_tools'] == {}
    before = dst.as_dict()
    end = {'type': 'tool_execution_end', 'toolName': 'exec', 'toolCallId': 'c',
           'result': model, 'isError': False, 'durationMs': 42}
    assert trace.observe(end) is None
    assert trace.observe(end) is None
    assert dst.as_dict() == before
    assert DST.from_events(dst.session_id, dst.events).state_dict() == dst.state_dict()
    assert dst.trace('r')['calls'][0]['result_event_id'] == result.event_id


def test_pi_end_records_an_executed_failure_without_a_prior_result():
    from cota.events import Event
    from cota.runtime.pi_trace import PiTraceRecorder
    dst = DST('failure-end', None)
    dst.append_event(Event('run_started', {}, run_id='r'))
    dst.append_event(Event('tool_started', {'tool': 'exec', 'tool_call_id': 'c', 'arguments': {'x': 1}}))
    trace = PiTraceRecorder(dst)
    end = {'type': 'tool_execution_end', 'toolName': 'exec', 'toolCallId': 'c',
           'result': {'content': [{'type': 'text', 'text': 'execution failed'}], 'details': {}},
           'isError': True, 'durationMs': 0}
    result = trace.observe(end)
    assert result.type == 'tool_result'
    assert result.payload['status'] != 'blocked'  # zero duration still means entered execute
    assert dst.trace('r')['calls'][0]['arguments'] == {'x': 1}
    assert result.payload['result'] == 'execution failed'
    assert result.payload['status'] == 'error'
    assert dst.execution['pending_tools'] == {}
    assert dst.trace('r')['calls'][0]['status'] == 'error'
    before = dst.as_dict()
    assert trace.observe(end) is None
    assert dst.as_dict() == before


@pytest.mark.parametrize('change', ['content', 'details', 'error', 'tool', 'call'])
def test_pi_end_cannot_change_a_committed_result(change):
    from copy import deepcopy
    from cota.events import Event
    from cota.runtime.pi_trace import PiTraceRecorder
    dst = DST('mismatch', None)
    dst.append_event(Event('run_started', {}, run_id='r'))
    dst.append_event(Event('tool_started', {'tool': 'exec', 'tool_call_id': 'c', 'arguments': {}}))
    trace = PiTraceRecorder(dst)
    model = {'content': [], 'details': {'value': True}, 'isError': False}
    trace.result('c', 'exec', {}, {}, model)
    before = dst.as_dict()
    end = {'type': 'tool_execution_end', 'toolName': 'exec', 'toolCallId': 'c',
           'result': deepcopy(model), 'isError': False}
    if change == 'content':
        end['result']['content'] = [{'type': 'text', 'text': 'changed'}]
    elif change == 'details':
        end['result']['details']['value'] = 1  # bool/int must not compare equal
    elif change == 'error':
        end['isError'] = True
    elif change == 'tool':
        end['toolName'] = 'other'
    else:
        end['toolCallId'] = 'other'
    with pytest.raises(ValueError, match='Pi tool end'):
        trace.observe(end)
    assert dst.as_dict() == before


@pytest.mark.asyncio
async def test_native_pi_error_result_is_preserved_in_trace_and_context(mock_agent):
    native = {'content': [{'type': 'text', 'text': 'Screen unavailable'}],
              'details': {'reason': 'permission'}, 'isError': True}
    handler = AsyncMock(return_value=native)
    mock_agent.get_tool_registry().register(FunctionTool('screen', 'screen', create_tool_schema({}), handler))
    mock_agent._llm_mock.generate_chat.side_effect = [
        {'tool_calls': [call('screen', {}, 'screen')]}, {'content': 'failed'},
    ]
    dst = DST('image', mock_agent)
    dst.append_event(UserUtterEvent('look'))
    await PiAgentRuntime(mock_agent, dst, 'image').run()
    result = next((e for e in dst.events if e.type == 'tool_result'), None)
    assert result is not None
    assert result.payload['status'] == 'error'
    assert result_content(result.payload) == native['content']
    assert result.payload['result'] == native
    message = next(m for m in dst.context_messages if m['role'] == 'toolResult')
    assert message['content'] == native['content']
    assert message['isError'] is True


@pytest.mark.asyncio
async def test_result_checkpoint_failure_stops_later_tools_and_preserves_pending(mock_agent):
    effect = AsyncMock(return_value={'success': True})
    mock_agent.get_tool_registry().register(FunctionTool('effect', 'effect', create_tool_schema({}), effect))
    mock_agent._llm_mock.generate_chat.return_value = {'tool_calls': [call('effect', {}, 'a'), call('effect', {}, 'b')]}
    dst, store = DST('failure', mock_agent), MemoryStore()
    dst.append_event(UserUtterEvent('go'))
    async def checkpoint(tracker):
        if any(e.type == 'tool_result' for e in tracker.events):
            raise OSError('result save failed')
        await store.save(tracker)
    with pytest.raises(OSError, match='result save failed'):
        await PiAgentRuntime(mock_agent, dst, 'failure', checkpoint=checkpoint).run()
    assert effect.await_count == 1
    stored = await store.export_session('failure')
    assert stored['execution']['status'] == 'running'
    assert 'a' in stored['execution']['pending_tools']


@pytest.mark.asyncio
async def test_cancelled_run_records_terminal_status_without_fabricating_tool_result(mock_agent):
    started = asyncio.Event()
    async def effect():
        started.set()
        await asyncio.Event().wait()
    mock_agent.get_tool_registry().register(FunctionTool('effect', 'effect', create_tool_schema({}), effect))
    mock_agent._llm_mock.generate_chat.return_value = {'tool_calls': [call('effect', {}, 'a')]}
    dst, store = DST('cancel', mock_agent), MemoryStore()
    dst.append_event(UserUtterEvent('go'))
    task = asyncio.create_task(PiAgentRuntime(mock_agent, dst, 'cancel', checkpoint=store.save).run())
    await asyncio.wait_for(started.wait(), 10)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not any(e.type == 'tool_result' for e in dst.events)
    terminal = [e for e in dst.events if e.type == 'run_finished']
    assert len(terminal) == 1 and terminal[0].payload['status'] == 'interrupted'


@pytest.mark.asyncio
async def test_duplicate_call_id_cannot_merge_two_external_effects(mock_agent):
    effect = AsyncMock(return_value={'success': True})
    mock_agent.get_tool_registry().register(FunctionTool('effect', 'effect', create_tool_schema({}), effect))
    mock_agent._llm_mock.generate_chat.side_effect = [
        {'tool_calls': [call('effect', {}, 'duplicate')]},
        {'tool_calls': [call('effect', {}, 'duplicate')]}, {'content': 'done'},
    ]
    dst = DST('duplicate', mock_agent)
    dst.append_event(UserUtterEvent('go'))
    with pytest.raises(ValueError, match='Duplicate tool call'):
        await PiAgentRuntime(mock_agent, dst, 'duplicate').run()
    assert effect.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('value', [None, False, 0, '', [], {}])
async def test_runtime_preserves_native_tool_return_before_model_formatting(mock_agent, value):
    effect = AsyncMock(return_value=value)
    mock_agent.get_tool_registry().register(FunctionTool('native', 'native', create_tool_schema({}), effect))
    mock_agent._llm_mock.generate_chat.side_effect = [
        {'tool_calls': [call('native', {}, 'native')]}, {'content': 'done'},
    ]
    dst = DST('native', mock_agent)
    dst.append_event(UserUtterEvent('go'))
    await PiAgentRuntime(mock_agent, dst, 'native').run()
    result = next(e for e in dst.events if e.type == 'tool_result')
    assert result.payload['result'] == value
    assert type(result.payload['result']) is type(value)


@pytest.mark.asyncio
async def test_final_checkpoint_failure_can_be_committed_before_new_input_runs(mock_agent):
    dst, store = DST('final-save', mock_agent), MemoryStore()
    dst.append_event(UserUtterEvent('go'))
    async def checkpoint(tracker):
        if tracker.execution.get('status') == 'completed':
            raise OSError('final save failed')
        await store.save(tracker)
    with pytest.raises(OSError, match='final save failed'):
        await PiAgentRuntime(mock_agent, dst, dst.session_id, checkpoint=checkpoint).run()
    assert dst.execution['status'] == 'failed'
    dst.append_event(UserUtterEvent('retry'))
    assert (await store.export_session(dst.session_id))['execution']['status'] == 'running'
    await PiAgentRuntime(mock_agent, dst, dst.session_id, checkpoint=store.save).run()
    saved = await store.load(dst.session_id)
    assert saved.execution['status'] == 'completed'
    assert any(e.type == 'run_finished' and e.payload['status'] == 'failed' for e in saved.events)


@pytest.mark.asyncio
async def test_policy_changed_after_schema_marks_call_blocked(mock_agent):
    from cota.executor.tools.registry import ToolPolicy
    effect = AsyncMock(return_value={'success': True})
    registry = mock_agent.get_tool_registry()
    registry.register(FunctionTool('effect', 'effect', create_tool_schema({}), effect))
    count = 0
    async def respond(**kwargs):
        nonlocal count
        count += 1
        if count == 1:
            registry.set_policy(ToolPolicy(deny=['effect']))
            return {'tool_calls': [call('effect', {}, 'denied')]}
        return {'content': 'denied'}
    mock_agent._llm_mock.generate_chat.side_effect = respond
    dst = DST('policy-change', mock_agent)
    dst.append_event(UserUtterEvent('go'))
    await PiAgentRuntime(mock_agent, dst, dst.session_id).run()
    effect.assert_not_awaited()
    view = dst.trace(dst.execution['run_id'])
    assert view['calls'][0]['status'] == 'blocked'
    assert 'executed' not in view['calls'][0]


def test_pi_progress_does_not_create_durable_events():
    from cota.events import Event
    from cota.runtime.pi_trace import PiTraceRecorder
    dst = DST('progress', None)
    dst.append_event(Event('run_started', {}, run_id='r'))
    dst.append_event(Event('tool_started', {'tool': 'exec', 'tool_call_id': 'c', 'arguments': {}}))
    recorder = PiTraceRecorder(dst)
    before = dst.as_dict()
    assert recorder.observe({'type': 'tool_execution_update', 'toolCallId': 'c',
                             'toolName': 'exec', 'partialResult': {'content': []}}) is None
    assert dst.as_dict() == before
    result = recorder.result('c', 'exec', {}, 'done', {'content': [{'type': 'text', 'text': 'done'}]})
    assert dst.execution['pending_tools'] == {}
    assert dst.trace('r')['calls'][0]['result_event_id'] == result.event_id
    assert DST.from_events(dst.session_id, dst.events).state_dict() == dst.state_dict()


@pytest.mark.asyncio
@pytest.mark.parametrize('schema_type,requested,effective', [('number', '1', 1), ('boolean', 'true', True)])
async def test_pi_coercion_checkpoints_effective_arguments_and_preserves_proposal(mock_agent, schema_type, requested, effective):
    import json
    store, dst = MemoryStore(), DST('coercion', mock_agent)
    dst.append_event(UserUtterEvent('go'))
    observed = []
    async def effect(n):
        starts = [e for e in await store.events(dst.session_id) if e['type'] == 'tool_started']
        observed.append((n, starts[-1]['payload']['arguments']))
        return {'success': True, 'value': n}
    mock_agent.get_tool_registry().register(FunctionTool('effect', 'effect',
        create_tool_schema({'n': {'type': schema_type}}, required=['n']), effect))
    mock_agent._llm_mock.generate_chat.side_effect = [
        {'tool_calls': [call('effect', {'n': requested}, 'coerced')]}, {'content': 'done'}]
    await PiAgentRuntime(mock_agent, dst, dst.session_id, checkpoint=store.save).run()
    assert len(observed) == 1 and type(observed[0][0]) is type(effective)
    assert observed[0] == (effective, {'n': effective})
    start = next(e for e in dst.events if e.type == 'tool_started')
    assert start.payload['requested_arguments'] == {'n': requested}
    proposal = next(b for b in start.payload['llm']['message']['content'] if b['type'] == 'toolCall')
    assert proposal['arguments'] == {'n': requested}
    assert len([e for e in dst.events if e.type == 'tool_result']) == 1
    assert not dst.execution['pending_tools'] and dst.execution['status'] == 'completed'
    request = mock_agent._llm_mock.generate_chat.call_args.kwargs['messages']
    assistant = next(m for m in request if m.get('tool_calls'))
    assert json.loads(assistant['tool_calls'][0]['function']['arguments']) == {'n': requested}
    assert (await store.load(dst.session_id)).state_dict() == dst.state_dict()


@pytest.mark.asyncio
async def test_json_number_roundtrip_does_not_change_assistant_origin(mock_agent):
    store, dst = MemoryStore(), DST('numeric-json', mock_agent)
    dst.append_event(UserUtterEvent('go'))
    effect = AsyncMock(return_value={'success': True})
    mock_agent.get_tool_registry().register(FunctionTool('effect', 'effect',
        create_tool_schema({'n': {'type': 'number'}}, required=['n']), effect))
    mock_agent._llm_mock.generate_chat.side_effect = [
        {'tool_calls': [call('effect', {'n': 1.0}, 'roundtrip')]}, {'content': 'done'}]
    await PiAgentRuntime(mock_agent, dst, dst.session_id, checkpoint=store.save).run()
    effect.assert_awaited_once_with(n=1)
    assert dst.execution['status'] == 'completed'
    assert 'requested_arguments' not in next(e for e in dst.events if e.type == 'tool_started').payload


@pytest.mark.asyncio
async def test_pi_acknowledges_integral_float_tool_result_without_rewriting_it(mock_agent):
    dst = DST('float-result', mock_agent)
    dst.append_event(UserUtterEvent('go'))
    tool = FunctionTool('effect', 'effect', create_tool_schema({}), AsyncMock(return_value={'value': 1.0}))
    mock_agent.get_tool_registry().register(tool)
    mock_agent._llm_mock.generate_chat.side_effect = [
        {'tool_calls': [call('effect', {}, 'effect')]}, {'content': 'done'}]
    await PiAgentRuntime(mock_agent, dst, dst.session_id).run()
    result = next(e for e in dst.events if e.type == 'tool_result')
    assert type(result.payload['result']['value']) is float
    assert dst.execution['status'] == 'completed'


def test_result_acknowledgement_distinguishes_booleans_from_numbers():
    from cota.runtime.pi_trace import reply_digest
    assert reply_digest({'details': {'n': 1.0}}) == reply_digest({'details': {'n': 1}})
    assert reply_digest({'details': {'n': True}}) != reply_digest({'details': {'n': 1}})


async def test_coerced_batch_follower_retains_original_proposal(mock_agent):
    effect = AsyncMock(return_value={'success': True})
    mock_agent.get_tool_registry().register(FunctionTool('effect', 'effect',
        create_tool_schema({'n': {'type': 'number'}}, required=['n']), effect))
    mock_agent._llm_mock.generate_chat.side_effect = [
        {'tool_calls': [call('effect', {'n': '1'}, 'first'), call('effect', {'n': '2'}, 'second')]},
        {'content': 'done'}]
    dst, store = DST('coerced-batch', mock_agent), MemoryStore()
    dst.append_event(UserUtterEvent('go'))
    await PiAgentRuntime(mock_agent, dst, dst.session_id, checkpoint=store.save).run()
    first, second = [event for event in dst.events if event.type == 'tool_started']
    assert second.payload['llm_event_id'] == first.event_id
    assert second.payload['arguments'] == {'n': 2}
    assert second.payload['requested_arguments'] == {'n': '2'}
    assert effect.await_count == 2
    assert (await store.load(dst.session_id)).state_dict() == dst.state_dict()


async def test_failed_coerced_start_checkpoint_prevents_side_effect(mock_agent):
    effect = AsyncMock(return_value={'success': True})
    mock_agent.get_tool_registry().register(FunctionTool('effect', 'effect',
        create_tool_schema({'n': {'type': 'number'}}, required=['n']), effect))
    mock_agent._llm_mock.generate_chat.return_value = {'tool_calls': [call('effect', {'n': '1'}, 'first')]}
    dst, store = DST('start-failure', mock_agent), MemoryStore()
    dst.append_event(UserUtterEvent('go'))
    async def checkpoint(tracker):
        if any(event.type == 'tool_started' for event in tracker.events):
            raise OSError('start save failed')
        await store.save(tracker)
    with pytest.raises(OSError, match='start save failed'):
        await PiAgentRuntime(mock_agent, dst, dst.session_id, checkpoint=checkpoint).run()
    effect.assert_not_awaited()
    assert not any(event['type'] == 'tool_started' for event in await store.events(dst.session_id))
