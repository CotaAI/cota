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
