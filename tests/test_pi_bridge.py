"""Exercise the actual subprocess pipe and acknowledgments without a model."""
import asyncio
from types import SimpleNamespace
import sys

import pytest

from cota.runtime.pi_bridge import PiBridge, PiBridgeError


@pytest.fixture
def worker(tmp_path, monkeypatch):
    from cota.runtime import pi_bridge

    def install(body):
        path = tmp_path / 'worker.py'
        path.write_text('import sys,json\nstart=json.loads(sys.stdin.readline())\n' + body)
        monkeypatch.setattr(pi_bridge, 'resolve_runtime', lambda node: SimpleNamespace(node=sys.executable, worker=path))
    return install


@pytest.mark.asyncio
async def test_large_multimodal_frame_round_trips_without_a_line_limit(worker):
    worker('''value=start['options']['payload']
print(json.dumps({'type':'request','id':1,'method':'prepare','payload':{'data':value}}),flush=True)
ack=json.loads(sys.stdin.readline())
assert ack['result']['length']==len(value)
print(json.dumps({'type':'done','result':{'status':'completed'}}),flush=True)
''')
    data = 'x' * (33 * 1024 * 1024)
    called = []

    async def handler(method, payload):
        assert method == 'prepare' and payload['data'] == data
        called.append(method)
        return {'length': len(payload['data'])}

    result = await PiBridge(timeout=30).run({'payload': data}, handler)
    assert result == {'status': 'completed'} and called == ['prepare']


@pytest.mark.asyncio
async def test_oversized_inbound_frame_fails_before_dispatch(worker, monkeypatch):
    from cota.runtime import pi_bridge
    monkeypatch.setattr(pi_bridge, 'MAX_FRAME_BYTES', 1024, raising=False)
    worker("print(json.dumps({'type':'request','id':1,'method':'prepare','payload':{'data':'x'*1048576}}),flush=True)\n")

    async def handler(*args):
        raise AssertionError('Oversized input must not be acknowledged')

    with pytest.raises(PiBridgeError, match='frame.*limit'):
        await asyncio.wait_for(PiBridge(timeout=3).run({}, handler), 5)


@pytest.mark.asyncio
async def test_oversized_outbound_frame_fails_clearly(worker, monkeypatch):
    from cota.runtime import pi_bridge
    monkeypatch.setattr(pi_bridge, 'MAX_FRAME_BYTES', 1024, raising=False)
    worker('')
    with pytest.raises(PiBridgeError, match='frame.*limit'):
        await PiBridge().run({'data': 'x' * 2048}, None)


@pytest.mark.asyncio
async def test_unterminated_frame_is_not_a_valid_completion(worker):
    worker("sys.stdout.write(json.dumps({'type':'done','result':{'status':'completed'}}));sys.stdout.flush()\n")
    with pytest.raises(PiBridgeError, match='incomplete|terminated'):
        await PiBridge().run({}, None)


@pytest.mark.asyncio
async def test_failed_checkpoint_never_acknowledges_request(worker, tmp_path):
    marker = tmp_path / 'acknowledged'
    worker("print(json.dumps({'type':'request','id':1,'method':'event','payload':{}}),flush=True)\n"
           "ack=sys.stdin.readline()\n"
           f"if ack: open({str(marker)!r},'w').write('unexpected acknowledgment')\n")

    async def fail(*args):
        raise RuntimeError('checkpoint failed')

    with pytest.raises(RuntimeError, match='checkpoint failed'):
        await PiBridge().run({}, fail)
    assert not marker.exists()


@pytest.mark.asyncio
async def test_invalid_frame_reports_protocol_error_without_echoing_content(worker):
    worker("print('PRIVATE_FRAME_CONTENT',flush=True)\n")
    with pytest.raises(PiBridgeError, match='Invalid JSON') as error:
        await PiBridge().run({}, None)
    assert 'PRIVATE_FRAME_CONTENT' not in str(error.value)


@pytest.mark.asyncio
async def test_whole_turn_timeout_has_a_descriptive_error_and_stops_worker(worker):
    worker("import time\ntime.sleep(10)\n")
    with pytest.raises(TimeoutError, match='Pi run.*total.*timeout'):
        await asyncio.wait_for(PiBridge(timeout=.1).run({}, None), 4)


@pytest.mark.asyncio
async def test_stream_notifications_do_not_block_durable_request_processing(worker):
    worker('''print(json.dumps({'type':'notification','method':'stream','payload':{'phase':'delta','text':'hello'}}),flush=True)
print(json.dumps({'type':'request','id':1,'method':'checkpoint','payload':{}}),flush=True)
ack=json.loads(sys.stdin.readline())
assert ack['id']==1
print(json.dumps({'type':'done','result':{'status':'completed'}}),flush=True)
''')
    checkpoint = asyncio.Event()
    seen = []
    async def handler(method, payload):
        if method == 'stream':
            await asyncio.wait_for(checkpoint.wait(), 1)
            seen.append(payload['text'])
        else:
            checkpoint.set()
            return {}
    assert await PiBridge(timeout=3).run({}, handler) == {'status': 'completed'}
    assert seen == ['hello']


@pytest.mark.asyncio
async def test_notification_callback_failure_does_not_retry_or_fail_model(worker):
    worker('''print(json.dumps({'type':'notification','method':'stream','payload':{'phase':'delta','text':'hello'}}),flush=True)
print(json.dumps({'type':'done','result':{'status':'completed'}}),flush=True)
''')
    async def handler(method, payload):
        raise ConnectionError('viewer disconnected')
    assert await PiBridge(timeout=3).run({}, handler) == {'status': 'completed'}


@pytest.mark.asyncio
async def test_unknown_notification_is_rejected_without_echoing_private_payload(worker):
    worker("print(json.dumps({'type':'notification','method':'PRIVATE','payload':{}}),flush=True)\n")
    with pytest.raises(PiBridgeError, match='notification') as error:
        await PiBridge(timeout=3).run({}, None)
    assert 'PRIVATE' not in str(error.value)


@pytest.mark.asyncio
async def test_native_timeout_type_survives_unacknowledged_observation():
    """Terminal classification survives deadline cancellation of the RPC queue."""
    from cota.runtime.pi_bridge import PiModelError
    tasks = set()
    async def serve(reader, writer):
        task = asyncio.current_task()
        tasks.add(task)
        try:
            headers = await reader.readuntil(b'\r\n\r\n')
            length = next(int(line.split(b':', 1)[1]) for line in headers.split(b'\r\n')
                          if line.lower().startswith(b'content-length:'))
            await reader.readexactly(length)
            writer.write(b'HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nConnection: close\r\n\r\n: keepalive\n\n')
            await writer.drain()
            await reader.read()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            writer.close()
            await writer.wait_closed()
            tasks.discard(task)
    server = await asyncio.start_server(serve, '127.0.0.1', 0)
    seen = []
    async def handler(method, payload):
        seen.append(method)
        if method == 'prepare':
            return {'systemPrompt': 'test', 'tools': []}
        if method == 'model_begin':
            return {'request_id': 'q', 'debug': False}
        if method == 'model_observation':
            attempt = payload.get('transport', {}).get('attempts', [{}])[-1]
            if attempt.get('status_code') == 200:
                await asyncio.sleep(2)
        return {}
    options = {'messages': [{'role': 'user', 'content': 'hello', 'timestamp': 1, 'cotaEventId': 'u'}],
               'maxIterations': 1, 'provider': {'apiKey': 'local-test', 'model': 'test',
                   'baseUrl': f'http://127.0.0.1:{server.sockets[0].getsockname()[1]}/v1',
                   'timeoutSeconds': 1, 'maxRetries': 0, 'vision': False}}
    try:
        with pytest.raises(PiModelError) as caught:
            await PiBridge(timeout=5).run(options, handler)
        assert getattr(caught.value, 'error_type', None) == 'TimeoutError'
        assert 'model_failed' not in seen  # Error type cannot depend on this callback.
    finally:
        server.close()
        await server.wait_closed()
        await asyncio.gather(*tasks, return_exceptions=True)
