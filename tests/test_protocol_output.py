"""Real Pi/bridge output rejection, durable facts and unmodified diagnostics."""
import pytest

from cota.dst import DST
from cota.events import UserUtterEvent
from cota.executor.tools.base import FunctionTool
from cota.runtime.pi_runtime import PiAgentRuntime
from cota.store import MemoryStore

DSML = '<｜｜DSML｜｜ calls>\n<｜｜DSML｜｜ invoke name="work">\n</｜｜DSML｜｜ calls>'


@pytest.mark.asyncio
@pytest.mark.parametrize('mode,expected_requests,expected_status', [
    ('recover', 10, 'limited'), ('repeat', 10, 'limited'), ('early', 1, 'failed')])
async def test_real_pi_rejects_protocol_without_delivery_or_tool_execution(
        mock_agent, tmp_path, mode, expected_requests, expected_status):
    effects, requests = [], []
    def work():
        effects.append('saved')
        return 'saved'
    mock_agent.get_tool_registry().register(FunctionTool('work', 'Save work',
        {'type': 'object', 'properties': {}}, work))
    async def respond(**parameters):
        requests.append(parameters)
        n = len(requests)
        if mode != 'early' and n <= 8:
            return {'tool_calls': [{'id': f'work-{n}', 'type': 'function',
                                   'function': {'name': 'work', 'arguments': '{}'}}]}
        return {'content': '已保存八项结果，附件尚未发送。' if mode == 'recover' and n == 10 else DSML}
    mock_agent._llm_mock.generate_chat.side_effect = respond
    store = MemoryStore()
    store.enable_debug_log(tmp_path / 'debug.log')
    dst = DST('protocol-test', mock_agent)
    dst.append_event(UserUtterEvent('Continue the existing work'))
    runtime = PiAgentRuntime(mock_agent, dst, dst.session_id, max_iterations=10,
                             checkpoint=store.save, store=store)
    await runtime.run()
    assert len(requests) == expected_requests
    assert len(effects) == (0 if mode == 'early' else 8)
    assert dst.execution['status'] == expected_status
    replies = [e.text for e in dst.events if e.type == 'bot_utter']
    assert len(replies) == 1 and 'DSML' not in replies[0]
    if mode == 'recover':
        assert replies == ['已保存八项结果，附件尚未发送。']
    else:
        assert '模型' in replies[0] and '已停止' in replies[0]
    if mode != 'early':
        assert requests[-1]['tool_choice'] == 'none'
        assert 'tools' not in requests[-1]
        assert 'DSML' not in str(requests[-1]['messages'])
    diagnostics = [await store.model_debug(dst.session_id, row['request_id'])
                   for row in await store.model_debug_headers(dst.session_id)]
    rejected = [d for d in diagnostics if d['status'] == 'rejected']
    assert len(rejected) == (2 if mode == 'repeat' else 1)
    assert all(d['response']['content'] == DSML and d['error_type'] == 'ToolProtocolText' for d in rejected)
    assert 'DSML' not in str(dst.context_messages)
    assert (await store.load(dst.session_id, mock_agent)).state_dict() == dst.state_dict()


@pytest.mark.asyncio
@pytest.mark.parametrize('debug', [False, True])
async def test_native_rejection_keeps_original_provider_response_and_next_decision(tmp_path, debug):
    from unittest.mock import AsyncMock
    from cota.events import Event
    from cota.runtime.pi_models import PiModelObserver
    from cota.runtime.pi_trace import PiTraceRecorder
    store, dst = MemoryStore(), DST('native-rejected', None)
    if debug:
        store.enable_debug_log(tmp_path / 'native.log')
    dst.append_event(Event('run_started', {}, run_id='r'))
    trace = PiTraceRecorder(dst, store)
    observer = PiModelObserver(trace, AsyncMock())
    raw = {'role': 'assistant', 'content': [{'type': 'text', 'text': DSML}],
           'stopReason': 'stop', 'timestamp': 1, 'model': 'test'}
    request = await observer.begin({'purpose': 'dialogue', 'model': 'test'})
    await observer.complete({'request_id': request['request_id'], 'message': raw, 'duration_ms': 1})
    await trace.reject_output()
    assert trace._pending_model is None and len(dst.events) == 1
    diagnostic = await store.model_debug(dst.session_id, request['request_id'])
    if debug:
        assert diagnostic['status'] == 'rejected'
        assert diagnostic['provider_response'] == raw
        assert diagnostic['response']['content'] == DSML
    else:
        assert diagnostic is None
    raw = {**raw, 'content': [{'type': 'text', 'text': '工作已保留，尚未完成。'}]}
    request = await observer.begin({'purpose': 'dialogue', 'model': 'test'})
    await observer.complete({'request_id': request['request_id'], 'message': raw, 'duration_ms': 1})
    event = trace.observe_assistant(raw)
    assert event.text == '工作已保留，尚未完成。'
    with pytest.raises(ValueError, match='uncommitted'):
        await trace.reject_output()
