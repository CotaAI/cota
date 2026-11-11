"""Execution phases are bounded read projections, never heartbeat facts."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from cota.debug.inspector import Inspector
from cota.dst import DST
from cota.events import Event, UserUtterEvent, ToolResultEvent
from cota.store import MemoryStore, SQLStore
from cota.runtime.pi_runtime import PiAgentRuntime
from cota.processor import Processor


@pytest.fixture(params=['memory', 'sqlite'])
def store(request, tmp_path):
    value = MemoryStore() if request.param == 'memory' else SQLStore(db=str(tmp_path / 'progress.db'))
    value.enable_debug_log(tmp_path / 'execution.log')
    yield value
    if isinstance(value, SQLStore):
        value.engine.dispose()


@pytest.mark.asyncio
async def test_debug_progress_tracks_model_tool_compaction_and_terminal_without_replay(store):
    dst = DST('s', None)
    dst.append_event(UserUtterEvent('hello', timestamp=10))
    dst.append_event(Event('run_started', {}, run_id='r', timestamp=11))
    await store.save(dst)
    inspector = Inspector(SimpleNamespace(name='test', store=store, workspace_path='/tmp'), 's')
    with patch.object(store, 'load', side_effect=AssertionError('no replay during polling')):
        assert (await inspector.info())['progress']['phase'] == 'preparing'
        record = {'request_id': 'q', 'run_id': 'r', 'purpose': 'dialogue', 'status': 'running', 'started_at': 12}
        await store.save_model_debug('s', 'q', record)
        assert (await inspector.info())['progress']['phase'] == 'model'
        await store.save_model_debug('s', 'q', {'status': 'completed'})
        dst.append_event(Event('tool_started', {'tool': 'bash', 'tool_call_id': 'c', 'arguments': {}}, timestamp=13))
        await store.save(dst)
        info = await inspector.info()
        assert info['progress']['phase'] == 'tool'
        assert info['progress']['tool'] == 'bash'
        assert info['progress']['since'] == 13
        dst.append_event(ToolResultEvent('bash', 'done', tool_call_id='c', timestamp=14))
        await store.save(dst)
        await store.save_model_debug('s', 'summary', {**record, 'request_id': 'summary', 'purpose': 'compaction', 'started_at': 15})
        assert (await inspector.info())['progress']['phase'] == 'compaction'
        dst.append_event(Event('run_finished', {'status': 'limited'}, timestamp=16))
        await store.save(dst)
        result = (await inspector.info())['progress']
        assert result['phase'] == result['status'] == 'limited'
        assert result['duration_seconds'] == 5
    assert len(await store.events('s')) == 5


@pytest.mark.asyncio
async def test_limit_reply_describes_decision_limit_and_retains_context(mock_agent):
    dst = DST('s', mock_agent)
    dst.append_event(UserUtterEvent('continue book'))
    runtime = PiAgentRuntime(mock_agent, dst, 's', max_iterations=100)
    runtime._finish_at_limit()
    text = dst.latest_bot_text()
    assert '100' in text and '模型决策' in text
    assert '继续' in text and '重新描述' not in text
    assert dst.latest_user_text() == 'continue book'


@pytest.mark.asyncio
@pytest.mark.parametrize('native', [False, True])
async def test_total_timeout_is_visible_without_turning_failure_into_completion(mock_agent, native):
    from cota.runtime.pi_runtime import ModelCallError
    processor = Processor(mock_agent, store=MemoryStore())
    processor.dst = DST('s', mock_agent)
    processor.dst.append_event(UserUtterEvent('book'))
    processor.dst.append_event(Event('run_started', {}, run_id='r'))
    processor.dst.append_event(Event('run_finished', {'status': 'failed', 'error_type': 'TimeoutError'}, run_id='r'))
    error = ModelCallError('provider private details', error_type='TimeoutError') if native else TimeoutError('provider private details')
    runtime = SimpleNamespace(run=AsyncMock(side_effect=error),
                              publish_committed=AsyncMock(), _service_mode=True)
    await processor._run_runtime(runtime)
    assert processor.dst.execution['status'] == 'failed'
    assert '超时' in processor.dst.latest_bot_text()
    assert 'provider private' not in processor.dst.latest_bot_text()
    from cota.conversation import message_record
    public = message_record('s', processor.dst.events[-1].as_dict())
    assert public['text'] == processor.dst.latest_bot_text()
    runtime.publish_committed.assert_awaited_once()


@pytest.mark.asyncio
async def test_late_old_run_terminal_does_not_hide_current_run(store):
    dst = DST('late', None)
    dst.append_event(UserUtterEvent('old'))
    dst.append_event(Event('run_started', {}, run_id='old'))
    dst.append_event(Event('run_finished', {'status': 'interrupted'}, run_id='old'))
    dst.append_event(UserUtterEvent('new'))
    dst.append_event(Event('run_started', {}, run_id='new'))
    dst.append_event(Event('run_finished', {'status': 'completed'}, run_id='old'))
    await store.save(dst)
    result = await store.execution_progress('late')
    assert result['run_id'] == 'new'
    assert result['status'] == 'running'


@pytest.mark.asyncio
async def test_native_provider_timeout_classification_survives_runtime_boundary(mock_agent):
    from cota.runtime.pi_bridge import PiModelError
    from cota.runtime.pi_runtime import ModelCallError
    dst = DST('s', mock_agent)
    runtime = PiAgentRuntime(mock_agent, dst, 's')
    runtime._models.last_error_type = 'TimeoutError'
    runtime._run = AsyncMock(side_effect=PiModelError('private upstream details'))
    with pytest.raises(ModelCallError) as caught:
        await runtime.run()
    assert caught.value.error_type == 'TimeoutError'
