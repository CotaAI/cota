"""Real SDK/HTTP boundaries, without network access or provider charges."""
import asyncio
import json

import httpx
import pytest

from cota.dst import DST
from cota.events import Event
from cota.llm import LLM
from cota.llm.observation import model_trace
from cota.runtime.pi_trace import PiTraceRecorder
from cota.store import MemoryStore


CONFIG = {'key': 'private-test-key', 'apibase': 'https://offline.invalid/v1', 'model': 'test'}


def completion():
    return {'id': 'q', 'object': 'chat.completion', 'created': 1, 'model': 'test',
            'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': 'done'},
                         'finish_reason': 'stop'}]}


async def install_transport(llm, handler):
    client = llm.client.client
    hooks = client._client.event_hooks
    await client.close()
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), event_hooks=hooks)


@pytest.mark.asyncio
async def test_default_and_explicit_sdk_retry_limits():
    for options, expected in [({}, 0), ({'max_retries': 1, 'timeout_seconds': 2}, 1)]:
        llm = LLM({**CONFIG, **options})
        try:
            assert llm.client.client.max_retries == expected
            assert llm.timeout_seconds == options.get('timeout_seconds', 180)
        finally:
            await llm.close()


@pytest.mark.parametrize('option,value', [
    ('timeout_seconds', True), ('timeout_seconds', 0), ('timeout_seconds', -1),
    ('timeout_seconds', float('inf')), ('timeout_seconds', '180'),
    ('max_retries', True), ('max_retries', -1), ('max_retries', 1.5), ('max_retries', 6),
])
def test_invalid_request_limits_fail_at_configuration(option, value):
    with pytest.raises(ValueError, match=option):
        LLM({**CONFIG, option: value})


@pytest.mark.asyncio
async def test_total_deadline_interrupts_a_live_request_and_retains_diagnostics(tmp_path):
    llm = LLM({**CONFIG, 'timeout_seconds': 1, 'max_retries': 1})
    started, cancelled = asyncio.Event(), asyncio.Event()

    async def waiting(request):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    await install_transport(llm, waiting)
    store, dst = MemoryStore(), DST('deadline', None)
    store.enable_debug_log(tmp_path / 'debug.log')
    dst.append_event(Event('run_started', {}, run_id='r'))

    async def save():
        await store.save(dst)

    try:
        with model_trace(PiTraceRecorder(dst, store), save):
            with pytest.raises(TimeoutError, match='total.*timeout|timeout.*total'):
                await asyncio.wait_for(llm.generate_chat([{'role': 'user', 'content': 'hello'}]), 3)
        assert started.is_set() and cancelled.is_set()
        header = (await store.model_debug_headers('deadline'))[0]
        record = await store.model_debug('deadline', header['request_id'])
        assert record['status'] == 'failed' and record['error']
        assert len(record['transport']['attempts']) == 1
        assert record['transport']['attempts'][0]['status'] == 'failed'
        assert record['transport']['timeout_seconds'] == 1
        assert 'private-test-key' not in json.dumps(record)
        assert [e.type for e in dst.events] == ['run_started']
    finally:
        await llm.close()


@pytest.mark.asyncio
async def test_sdk_retry_attempts_and_response_headers_are_observable(tmp_path):
    llm = LLM({**CONFIG, 'timeout_seconds': 2, 'max_retries': 1})
    requests = []

    async def respond(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(503, headers={'retry-after-ms': '1'}, json={'error': 'busy'})
        return httpx.Response(200, json=completion())

    await install_transport(llm, respond)
    store, dst = MemoryStore(), DST('retry', None)
    store.enable_debug_log(tmp_path / 'debug.log')
    dst.append_event(Event('run_started', {}, run_id='r'))

    async def save():
        await store.save(dst)

    try:
        with model_trace(PiTraceRecorder(dst, store), save):
            result = await llm.generate_chat([{'role': 'user', 'content': 'hello'}])
        assert result['content'] == 'done' and len(requests) == 2
        header = (await store.model_debug_headers('retry'))[0]
        record = await store.model_debug('retry', header['request_id'])
        transport = record['transport']
        assert [a['status_code'] for a in transport['attempts']] == [503, 200]
        assert [a['number'] for a in transport['attempts']] == [1, 2]
        assert all(a['headers_ms'] >= a['started_ms'] for a in transport['attempts'])
        assert transport['response_ready_ms'] >= transport['attempts'][-1]['headers_ms']
        assert 'first_token_ms' not in transport
        assert 'private-test-key' not in json.dumps(record)
    finally:
        await llm.close()


@pytest.mark.asyncio
async def test_cancellation_is_not_converted_into_a_retry():
    llm = LLM({**CONFIG, 'max_retries': 1})
    started, calls = asyncio.Event(), []

    async def waiting(request):
        calls.append(request)
        started.set()
        await asyncio.Event().wait()

    await install_transport(llm, waiting)
    try:
        task = asyncio.create_task(llm.generate_chat([{'role': 'user', 'content': 'hello'}]))
        await asyncio.wait_for(started.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert len(calls) == 1
    finally:
        await llm.close()


@pytest.mark.asyncio
async def test_custom_limits_are_local_settings_not_provider_payload():
    llm = LLM({**CONFIG, 'type': 'custom', 'timeout_seconds': 2, 'max_retries': 0})
    try:
        assert 'timeout_seconds' not in llm.client.extra_config
        assert 'max_retries' not in llm.client.extra_config
    finally:
        await llm.close()


def test_custom_retry_setting_is_not_silently_ignored():
    with pytest.raises(ValueError, match='max_retries'):
        LLM({**CONFIG, 'type': 'custom', 'max_retries': 1})


@pytest.mark.asyncio
async def test_keepalive_body_cannot_extend_the_total_deadline(tmp_path):
    llm = LLM({**CONFIG, 'timeout_seconds': 1})
    entered, closed = asyncio.Event(), asyncio.Event()

    class KeepAlive(httpx.AsyncByteStream):
        async def __aiter__(self):
            entered.set()
            while True:
                yield b'\n'
                await asyncio.sleep(.01)

        async def aclose(self):
            closed.set()

    await install_transport(llm, lambda request: httpx.Response(200, stream=KeepAlive()))
    store, dst = MemoryStore(), DST('keepalive', None)
    store.enable_debug_log(tmp_path / 'debug.log')
    dst.append_event(Event('run_started', {}, run_id='r'))

    async def save():
        await store.save(dst)

    try:
        with model_trace(PiTraceRecorder(dst, store), save):
            with pytest.raises(TimeoutError, match='total timeout'):
                await asyncio.wait_for(llm.generate_chat([{'role': 'user', 'content': 'hello'}]), 3)
        assert entered.is_set() and closed.is_set()
        header = (await store.model_debug_headers(dst.session_id))[0]
        record = await store.model_debug(dst.session_id, header['request_id'])
        attempt = record['transport']['attempts'][0]
        assert attempt['status_code'] == 200 and attempt['status'] == 'failed'
        assert attempt['headers_ms'] >= attempt['started_ms']
        assert 'response_ready_ms' not in record['transport']
    finally:
        await llm.close()


@pytest.mark.asyncio
async def test_total_deadline_also_covers_sdk_retry_backoff():
    llm = LLM({**CONFIG, 'timeout_seconds': 1, 'max_retries': 1})
    calls = []

    async def respond(request):
        calls.append(request)
        return httpx.Response(503, headers={'retry-after-ms': '5000'}, json={'error': 'busy'})

    await install_transport(llm, respond)
    try:
        with pytest.raises(TimeoutError, match='total timeout'):
            await asyncio.wait_for(llm.generate_chat([{'role': 'user', 'content': 'hello'}]), 3)
        assert len(calls) == 1
    finally:
        await llm.close()


@pytest.mark.asyncio
async def test_concurrent_http_diagnostics_do_not_mix_sessions(tmp_path):
    llm = LLM({**CONFIG, 'max_retries': 1})
    counts = {}

    async def respond(request):
        name = json.loads(request.content)['messages'][0]['content']
        counts[name] = counts.get(name, 0) + 1
        await asyncio.sleep(0)
        if name == 'retry' and counts[name] == 1:
            return httpx.Response(503, headers={'retry-after-ms': '1'}, json={'error': 'busy'})
        return httpx.Response(200, json=completion())

    await install_transport(llm, respond)
    store = MemoryStore()
    store.enable_debug_log(tmp_path / 'debug.log')

    async def run(name):
        dst = DST(name, None)
        dst.append_event(Event('run_started', {}, run_id=name))

        async def save():
            await store.save(dst)

        with model_trace(PiTraceRecorder(dst, store), save):
            await llm.generate_chat([{'role': 'user', 'content': name}])
        header = (await store.model_debug_headers(name))[0]
        return await store.model_debug(name, header['request_id'])

    try:
        retry, plain = await asyncio.gather(run('retry'), run('plain'))
        assert [a['status_code'] for a in retry['transport']['attempts']] == [503, 200]
        assert [a['status_code'] for a in plain['transport']['attempts']] == [200]
        assert retry['request_id'] != plain['request_id']
    finally:
        await llm.close()


@pytest.mark.asyncio
async def test_default_failure_is_not_retried_or_copied_into_ordinary_logs(caplog):
    from openai import InternalServerError
    llm = LLM(CONFIG)
    calls = []

    async def respond(request):
        calls.append(request)
        return httpx.Response(503, json={'error': {'message': 'PRIVATE_PROVIDER_BODY'}})

    await install_transport(llm, respond)
    store, dst = MemoryStore(), DST('failure', None)
    dst.append_event(Event('run_started', {}, run_id='r'))

    async def save():
        await store.save(dst)

    try:
        with model_trace(PiTraceRecorder(dst, store), save):
            with pytest.raises(InternalServerError):
                await llm.generate_chat([{'role': 'user', 'content': 'hello'}])
        assert len(calls) == 1
        assert 'PRIVATE_PROVIDER_BODY' not in caplog.text
        assert 'error_type=InternalServerError' in caplog.text
        assert not await store.model_debug_headers(dst.session_id)
    finally:
        await llm.close()
