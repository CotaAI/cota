"""Core facts and optional diagnostics have separate persistence."""
import asyncio
import json
import logging
from unittest.mock import AsyncMock

import pytest

from cota.events import Event, UserUtterEvent
from cota.dst import DST
from cota.runtime.pi_runtime import PiAgentRuntime
from cota.store import MemoryStore, SQLStore


@pytest.mark.asyncio
@pytest.mark.parametrize('debug', [False, True])
async def test_request_saved_before_model_and_debug_only_changes_output(mock_agent, tmp_path, debug, caplog):
    store = MemoryStore()
    if debug:
        store.enable_debug_log(tmp_path / 'execution.log')
    dst = DST('chat', mock_agent)
    dst.append_event(UserUtterEvent('private question'))
    async def respond(**kwargs):
        saved = await store.export_session('chat')
        assert saved['context_messages'][-1]['content'] == 'private question'
        records = await store.model_debug_headers('chat')
        assert bool(records) == debug
        if debug:
            record = await store.model_debug('chat', records[0]['request_id'])
            assert record['request']['messages'] == kwargs['messages']
            assert record['request']['tools'] == kwargs['tools']
        return {'content': 'private answer'}
    mock_agent._llm_mock.generate_chat.side_effect = respond
    with caplog.at_level(logging.INFO, logger='cota.execution'):
        await PiAgentRuntime(mock_agent, dst, 'chat', checkpoint=store.save).run()
    events = (await store.export_session('chat'))['events']
    reply = next(e for e in events if e['type'] == 'bot_utter' and e['payload'].get('llm'))
    assert reply['payload']['llm']['request_id']
    assert not any(e['type'] in ('model_request', 'model_provider_request', 'context_prepared', 'execution_updated', 'model_response') for e in events)
    assert reply['payload']['llm']['duration_ms'] >= 0
    assert 'private question' not in caplog.text and 'private answer' not in caplog.text
    if debug:
        log = (tmp_path / 'execution.log').read_text()
        assert 'private question' in log and 'private answer' in log
        assert reply['event_id'] in log and 'session=chat' in log
        assert log.count('event=' + reply['event_id']) == 1
    else:
        assert not (tmp_path / 'execution.log').exists()


@pytest.mark.asyncio
async def test_model_request_checkpoint_failure_prevents_network(mock_agent):
    dst = DST('failed-save', mock_agent)
    dst.append_event(UserUtterEvent('go'))
    async def fail(tracker):
        if any(e.type == 'run_started' for e in tracker.events):
            raise OSError('cannot save request')
    with pytest.raises(OSError, match='cannot save request'):
        await PiAgentRuntime(mock_agent, dst, dst.session_id, checkpoint=fail).run()
    mock_agent._llm_mock.generate_chat.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('debug', [False, True])
async def test_provider_failure_is_logged_and_ends_run_without_fake_tool(mock_agent, tmp_path, debug, caplog):
    dst, store = DST('error', mock_agent), MemoryStore()
    if debug:
        store.enable_debug_log(tmp_path / 'execution.log')
    dst.append_event(UserUtterEvent('private question'))
    mock_agent._llm_mock.generate_chat.side_effect = RuntimeError('provider down')
    with caplog.at_level(logging.ERROR, logger='cota.llm.observation'):
        with pytest.raises(Exception, match='provider down'):
            await PiAgentRuntime(mock_agent, dst, dst.session_id, checkpoint=store.save).run()
    saved = await store.export_session(dst.session_id)
    assert [e['type'] for e in saved['events']] == ['user_utter', 'run_started', 'run_finished']
    assert saved['execution']['status'] == 'failed'
    assert 'provider down' in saved['events'][-1]['payload']['error']
    logs = [r for r in caplog.records if r.name == 'cota.llm.observation']
    assert len(logs) == 1 and logs[0].exc_info[0] is RuntimeError
    assert 'session=error' in logs[0].message and 'purpose=dialogue' in logs[0].message
    assert 'provider down' in caplog.text and 'private question' not in caplog.text
    headers = await store.model_debug_headers(dst.session_id)
    assert bool(headers) == debug
    if debug:
        record = await store.model_debug(dst.session_id, headers[0]['request_id'])
        assert record['status'] == 'failed' and record['error_type'] == 'RuntimeError'
        assert record['request_id'] in logs[0].message
        assert record['request']['messages'] and 'event_id' not in record
    assert (await store.load(dst.session_id)).state_dict() == dst.state_dict()


@pytest.mark.asyncio
async def test_sql_debug_logs_only_committed_new_events(tmp_path):
    store = SQLStore(dialect='sqlite', db=str(tmp_path / 'db.sqlite'))
    path = tmp_path / 'execution.log'
    store.enable_debug_log(path)
    dst = DST('sql', None)
    dst.append_event(UserUtterEvent('hello'))
    try:
        await store.save(dst)
        await store.save(dst)
        assert path.read_text().count('event=' + dst.events[0].event_id) == 1
        stale = DST('sql', None)
        stale.append_event(UserUtterEvent('uncommitted'))
        with pytest.raises(Exception):
            await store.save(stale)
        assert 'uncommitted' not in path.read_text()
    finally:
        store.engine.dispose()


@pytest.mark.asyncio
async def test_real_provider_parameters_responses_and_concurrent_purposes(tmp_path):
    import httpx
    from openai import AsyncOpenAI
    from cota.llm import LLM
    from cota.llm.observation import model_trace, model_purpose
    from cota.runtime.pi_trace import PiTraceRecorder
    from cota.events import Event

    wire = {}
    async def respond(request):
        body = json.loads(request.content)
        sid = body['messages'][0]['content']
        wire[sid] = body
        await asyncio.sleep(0)
        return httpx.Response(200, json={
            'id': sid, 'object': 'chat.completion', 'created': 1, 'model': body['model'],
            'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': sid}, 'finish_reason': 'stop'}],
            'usage': {'prompt_tokens': 4, 'completion_tokens': 1, 'total_tokens': 5},
        })

    llm = LLM({'key': 'secret-not-in-trace', 'apibase': 'https://model.example/v1',
               'model': 'gpt-5-test', 'thinking': 'disabled'})
    original = llm.client.client
    llm.client.client = AsyncOpenAI(api_key='secret-not-in-trace', base_url='https://model.example/v1',
                                    http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)))
    await original.close()
    store = MemoryStore()
    store.enable_debug_log(tmp_path / 'execution.log')
    async def run(sid, purpose):
        dst = DST(sid, None)
        dst.append_event(Event('run_started', {}, run_id=sid))
        async def checkpoint():
            await store.save(dst)
        with model_trace(PiTraceRecorder(dst, store), checkpoint), model_purpose(purpose):
            await llm.generate_chat(messages=[{'role': 'user', 'content': sid}], max_tokens=77)
        return dst
    try:
        trackers = await asyncio.gather(run('policy-chat', 'policy'), run('summary-chat', 'compaction'))
    finally:
        await llm.client.client.close()
    for dst, purpose in zip(trackers, ['policy', 'compaction']):
        events = (await store.export_session(dst.session_id))['events']
        assert [e['type'] for e in events] == ['run_started']
        headers = await store.model_debug_headers(dst.session_id)
        assert len(headers) == 1
        record = await store.model_debug(dst.session_id, headers[0]['request_id'])
        assert record['purpose'] == purpose
        assert record['request_sequence'] == 1
        assert record['status'] == 'completed'
        params = dict(record['request'])
        params.update(params.pop('extra_body'))
        assert params == wire[dst.session_id]
        assert params['max_completion_tokens'] == 77 and 'max_tokens' not in params
        assert record['provider_response']['usage']['total_tokens'] == 5
        assert all(e['run_id'] == dst.session_id for e in events)
    assert 'secret-not-in-trace' not in (tmp_path / 'execution.log').read_text()


@pytest.mark.asyncio
async def test_debug_projection_failure_does_not_fail_committed_save(tmp_path, caplog):
    store = MemoryStore()
    store.enable_debug_log(tmp_path / 'execution.log')
    def broken(*args):
        raise OSError('disk full')
    store._debug_log.write = broken
    dst = DST('committed', None)
    dst.append_event(UserUtterEvent('hello'))
    await store.save(dst)
    assert (await store.export_session('committed'))['events'][0]['payload']['text'] == 'hello'
    assert 'events remain in Store' in caplog.text


@pytest.mark.asyncio
async def test_cancelled_model_is_logged_and_scope_does_not_leak(tmp_path, caplog):
    from cota.llm.observation import model_trace, observe_model_call
    from cota.runtime.pi_trace import PiTraceRecorder
    dst, store = DST('cancelled', None), MemoryStore()
    store.enable_debug_log(tmp_path / 'execution.log')
    dst.append_event(Event('run_started', {}, run_id='r'))
    started = asyncio.Event()
    async def wait(**kwargs):
        started.set()
        await asyncio.Event().wait()
    async def checkpoint():
        await store.save(dst)
    async def run():
        with model_trace(PiTraceRecorder(dst, store), checkpoint):
            await observe_model_call(wait, {'messages': []})
    task = asyncio.create_task(run())
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    saved = await store.export_session('cancelled')
    assert [e['type'] for e in saved['events']] == ['run_started']
    assert 'interrupted session=cancelled' in caplog.text
    headers = await store.model_debug_headers('cancelled')
    record = await store.model_debug('cancelled', headers[0]['request_id'])
    assert record['status'] == 'interrupted'
    assert record['error_type'] == 'CancelledError'
    await observe_model_call(AsyncMock(return_value={}), {'messages': []})
    assert [e.type for e in dst.events] == ['run_started']


@pytest.mark.asyncio
async def test_debug_shell_prints_reply_even_if_turn_flush_already_happened(capsys):
    from cota.channels.cmdline import CmdlineChannel
    from cota.channels.events import OutboundMessage
    from cota.channels.queue import MessageBus
    channel = CmdlineChannel({}, MessageBus(), debug=True)
    channel.flush_output()
    capsys.readouterr()
    await channel.send(OutboundMessage(channel='cmdline', chat_id='chat', content='ready'))
    assert 'Bot: ready' in capsys.readouterr().err


@pytest.mark.asyncio
async def test_invalid_provider_response_is_retained_on_parse_failure(tmp_path):
    from cota.llm.observation import model_trace, observe_model_call, provider_response
    from cota.runtime.pi_trace import PiTraceRecorder
    dst, store = DST('parse-error', None), MemoryStore()
    store.enable_debug_log(tmp_path / 'execution.log')
    dst.append_event(Event('run_started', {}, run_id='r'))
    async def checkpoint():
        await store.save(dst)
    async def broken(**kwargs):
        provider_response({'choices': [], 'usage': {'total_tokens': 1}})
        raise ValueError('missing choice')
    with model_trace(PiTraceRecorder(dst, store), checkpoint):
        with pytest.raises(ValueError, match='missing choice'):
            await observe_model_call(broken, {'messages': []})
    assert [e['type'] for e in (await store.export_session(dst.session_id))['events']] == ['run_started']
    headers = await store.model_debug_headers(dst.session_id)
    record = await store.model_debug(dst.session_id, headers[0]['request_id'])
    assert record['provider_response']['choices'] == []
    assert record['status'] == 'failed' and record['error_type'] == 'ValueError'


@pytest.mark.asyncio
async def test_auxiliary_model_failure_can_fall_back_without_execution_event(tmp_path, caplog):
    from types import SimpleNamespace
    from cota.llm.observation import model_trace, model_purpose, observe_model_call
    from cota.runtime.pi_trace import PiTraceRecorder
    from cota.policy import train_policy, load_policy, PolicyServices
    from tests.test_trainable_policy import setup_bot, context
    config = setup_bot(tmp_path, 'model', {'llm': 'judge'})
    await train_policy(tmp_path, config)
    policy = load_policy(tmp_path, config)
    dst, store = DST('fallback', None), MemoryStore()
    dst.append_event(Event('run_started', {}, run_id='r'))
    async def checkpoint():
        await store.save(dst)
    async def failing_model(**request):
        return await observe_model_call(AsyncMock(side_effect=ConnectionError('network unavailable')), request, llm='judge')
    with model_trace(PiTraceRecorder(dst, store), checkpoint), model_purpose('policy'):
        result = await policy.guidance(context(), PolicyServices(model=lambda name: SimpleNamespace(generate_chat=failing_model)))
    assert result['diagnostics'][0]['code'] == 'policy_fallback'
    assert result['policies']
    assert 'purpose=policy' in caplog.text and 'network unavailable' in caplog.text
    assert [e.type for e in dst.events] == ['run_started']
    dst.append_event(Event('run_finished', {'status': 'completed'}))
    await store.save(dst)
    assert (await store.load(dst.session_id)).execution['status'] == 'completed'
    assert await store.model_debug_headers(dst.session_id) == []
