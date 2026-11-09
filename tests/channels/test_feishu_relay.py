"""Official SDK worker admission protocol, without contacting Feishu."""
import io
import json

import pytest

from cota.channels.platforms import feishu_worker as worker


def relay(monkeypatch, acknowledgements):
    source, output = io.StringIO(acknowledgements), io.StringIO()
    monkeypatch.setattr(worker.select, 'select', lambda *args: ([source], [], []))
    return worker.EventRelay(source, output), output


def test_relay_discards_late_ack_and_increments_message_identity(monkeypatch):
    instance, output = relay(monkeypatch, '\n'.join([
        '{"id":"old","accepted":false}', '{"id":"1","accepted":true}',
        '{"id":"2","accepted":true}', '']))
    instance.handle({'message': '你好'})
    instance.handle({'message': 'next'})
    frames = [json.loads(line) for line in output.getvalue().splitlines()]
    assert frames == [{'type': 'event', 'id': '1', 'event': {'message': '你好'}},
                      {'type': 'event', 'id': '2', 'event': {'message': 'next'}}]


@pytest.mark.parametrize('ack,error', [('', 'stream closed'), ('{"id":"1","accepted":false}\n', 'queue unavailable')])
def test_relay_rejects_closed_or_unavailable_parent(monkeypatch, ack, error):
    instance, _ = relay(monkeypatch, ack)
    with pytest.raises(RuntimeError, match=error):
        instance.handle({'message': 'hello'})


def test_relay_admission_timeout_is_bounded(monkeypatch):
    instance, _ = relay(monkeypatch, '')
    monkeypatch.setattr(worker.select, 'select', lambda *args: ([], [], []))
    with pytest.raises(TimeoutError, match='admission timed out'):
        instance.handle({'message': 'hello'})


def test_worker_reports_only_error_type_for_malformed_config(monkeypatch):
    output = io.StringIO()
    monkeypatch.setattr(worker.sys, 'stdin', io.StringIO('SECRET_NOT_JSON'))
    monkeypatch.setattr(worker.sys, 'stdout', output)
    assert worker.main() == 1
    assert json.loads(output.getvalue()) == {'type': 'error', 'error_type': 'JSONDecodeError'}
