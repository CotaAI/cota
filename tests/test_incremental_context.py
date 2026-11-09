"""Core facts reconstruct context independently of request diagnostics."""
import pytest
from cota.dst import DST
from cota.events import Event, UserUtterEvent, BotUtterEvent
from cota.snapshots import make_snapshot
from cota.store import MemoryStore, SQLStore
from cota.runtime.pi_runtime import PiAgentRuntime
from tests.test_pi_runtime import call


def test_user_and_visible_bot_are_projected_without_full_context_events():
    dst = DST('s', None)
    dst.append_event(UserUtterEvent('hi', event_id='u', timestamp=1))
    dst.append_event(BotUtterEvent('hello', timestamp=2))
    assert [m['role'] for m in dst.context_messages] == ['user', 'assistant']
    assert dst.context_messages[0]['cotaEventId'] == 'u'
    assert DST.from_events('s', dst.events).context_messages == dst.context_messages


@pytest.mark.asyncio
@pytest.mark.parametrize('debug', [False, True])
@pytest.mark.parametrize('backend', ['memory', 'sqlite'])
async def test_real_pi_incremental_recovery_and_debug_parity(mock_agent, tmp_path, debug, backend):
    store = MemoryStore() if backend == 'memory' else SQLStore(db=str(tmp_path / 'facts.db'))
    mock_agent.store = store
    if debug:
        store.enable_debug_log(tmp_path / 'execution.log')
    dst = DST('s', mock_agent)
    dst.append_event(UserUtterEvent('read skill'))
    mock_agent._llm_mock.generate_chat.side_effect = [
        {'tool_calls': [call('read', {'path': mock_agent.skill_file('SearchWeb')}, 'read-1')]},
        {'content': 'done'}, {'content': 'next'},
    ]
    await PiAgentRuntime(mock_agent, dst, 's', checkpoint=store.save).run()
    forbidden = {'execution_updated', 'context_prepared', 'model_request', 'model_provider_request', 'model_response'}
    assert not forbidden.intersection(e.type for e in dst.events)
    assert all('messages' not in e.payload for e in dst.events)
    assert 'messages' not in dst.execution
    assert [m['role'] for m in dst.context_messages] == ['user', 'assistant', 'toolResult', 'assistant']
    assert not any(m['role'] == 'system' for m in dst.context_messages)
    outputs = [e for e in dst.events if e.payload.get('llm')]
    assert [e.type for e in outputs] == ['tool_started', 'bot_utter']
    assert [e.payload['llm']['request_sequence'] for e in outputs] == [1, 2]
    request_id = outputs[0].payload['llm']['request_id']
    detail = await store.model_debug('s', request_id)
    assert bool(detail) == debug
    if debug:
        assert detail['request']['messages'][0]['role'] == 'system'
    plain = DST.from_events('s', dst.events, mock_agent)
    assert plain.state_dict() == dst.state_dict()
    saved = await store.load('s', mock_agent)
    assert saved.state_dict() == plain.state_dict()
    saved.append_event(UserUtterEvent('continue'))
    await PiAgentRuntime(mock_agent, saved, 's', checkpoint=store.save).run()
    assert [m['role'] for m in saved.context_messages] == ['user', 'assistant', 'toolResult', 'assistant', 'user', 'assistant']
    assert DST.from_events('s', saved.events, mock_agent, snapshot=make_snapshot(dst)).state_dict() == saved.state_dict()
    if backend == 'sqlite':
        store.engine.dispose()


def test_repeated_compaction_replays_exact_boundaries_and_snapshot_suffix():
    dst = DST('s', None)
    dst.append_event(UserUtterEvent('old'))
    dst.append_event(BotUtterEvent('answer'))
    dst.append_event(UserUtterEvent('current'))
    dst.append_event(Event('run_started', {}, run_id='one'))
    before = make_snapshot(dst)
    first = Event('context_compaction', {'summary': 'first summary',
        'replaced_message_ids': [m['cotaEventId'] for m in dst.context_messages[:2]]})
    dst.append_event(first)
    dst.append_event(Event('run_finished', {'status': 'completed'}))
    dst.append_event(UserUtterEvent('new'))
    dst.append_event(Event('run_started', {}, run_id='two'))
    dst.append_event(Event('context_compaction', {'summary': 'second summary',
        'replaced_message_ids': [m['cotaEventId'] for m in dst.context_messages[:2]]}))
    assert 'second summary' in dst.context_messages[0]['content']
    assert len(dst.context_messages) == 2
    assert DST.from_events('s', dst.events).state_dict() == dst.state_dict()
    assert DST.from_events('s', dst.events, snapshot=before).state_dict() == dst.state_dict()
    original = dst.as_dict()
    with pytest.raises(ValueError, match='exact current context prefix'):
        dst.append_event(Event('context_compaction', {'summary': 'bad', 'replaced_message_ids': ['missing']}))
    assert dst.as_dict() == original


@pytest.mark.asyncio
async def test_diagnostic_storage_failure_does_not_fail_bot(mock_agent, tmp_path, monkeypatch):
    store = MemoryStore()
    mock_agent.store = store
    store.enable_debug_log(tmp_path / 'execution.log')
    async def fail(*args):
        raise OSError('diagnostic storage unavailable')
    monkeypatch.setattr(store, '_save_model_debug', fail)
    dst = DST('s', mock_agent)
    dst.append_event(UserUtterEvent('hello'))
    await PiAgentRuntime(mock_agent, dst, 's', checkpoint=store.save).run()
    assert dst.execution['status'] == 'completed'
    assert (await store.load('s')).context_messages == dst.context_messages


@pytest.mark.asyncio
async def test_debug_records_are_separate_and_survive_sql_reopen(tmp_path):
    path = str(tmp_path / 'store.sqlite')
    store = SQLStore(db=path)
    store.enable_debug_log(tmp_path / 'execution.log')
    record = {'request_id': 'q', 'run_id': 'r', 'purpose': 'dialogue', 'status': 'running',
              'started_at': 1, 'request': {'messages': [{'role': 'system', 'content': 'prompt'}]}}
    await store.save_model_debug('s', 'q', record)
    assert await store.events('s') == []
    assert await store.model_debug('other', 'q') is None
    store.engine.dispose()
    reopened = SQLStore(db=path)
    try:
        assert await reopened.model_debug('s', 'q') == record
        assert (await reopened.model_debug_headers('s'))[0]['status'] == 'running'
        assert await reopened.load('s') is None
    finally:
        reopened.engine.dispose()
