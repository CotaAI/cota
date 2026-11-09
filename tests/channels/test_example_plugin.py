"""Runnable generic webhook/REST adapter protocol; no platform credentials needed."""
import asyncio
import hashlib
import hmac
from importlib import import_module
import json
from pathlib import Path
from types import SimpleNamespace
import tomllib
from unittest.mock import AsyncMock

import httpx
import pytest
from sanic import Sanic

from cota.application import ApplicationUnavailable
from cota.channels import ChannelContext, MessageBus, OutboundMessage
from cota.inputs import InputConflict


EXAMPLE = Path(__file__).resolve().parents[2] / 'examples' / 'channel-plugin'
CONFIG = {'enabled': True, 'app_id': 'app-one', 'webhook_secret': 'webhook-test-secret',
          'api_base': 'https://gateway.example/v1', 'api_token': 'outbound-test-token'}
PAYLOAD = {'user_id': 'alice', 'chat_id': 'room-one', 'text': '你好', 'message_id': 'message-one'}


def make_channel(monkeypatch, *, name='office_im', mode='direct', receive=None, **settings):
    monkeypatch.syspath_prepend(str(EXAMPLE / 'src'))
    kind = import_module('cota_channel_example').ExampleIMChannel
    channel = kind({**CONFIG, **settings}, MessageBus())
    if receive is None:
        submission = SimpleNamespace(message_id='message-one', duplicate=False,
                                     receipt=AsyncMock(return_value={'status': 'queued'}))
        receive = AsyncMock(return_value=submission)
    channel.bind(ChannelContext(name, mode, receive))
    return channel, receive


def request_for(payload=PAYLOAD, *, raw=None, signature=None):
    body = raw if raw is not None else json.dumps(payload, ensure_ascii=False).encode()
    digest = hmac.new(CONFIG['webhook_secret'].encode(), body, hashlib.sha256).hexdigest()
    return SimpleNamespace(body=body, headers={'X-Signature': digest if signature is None else signature})


def callback(channel):
    blueprint = channel.http_blueprint()
    return next(route.handler for route in blueprint._future_routes if route.uri == '/webhook')


def body(response):
    return json.loads(response.body)


def test_configuration_and_blueprint_do_not_open_connections(monkeypatch):
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: pytest.fail('HTTP client before start'))
    channel, _ = make_channel(monkeypatch)
    channel.validate()
    assert channel.durable_delivery
    assert channel.delivery_scope == 'app-one'
    assert not channel.is_running
    blueprint = channel.http_blueprint()
    assert channel.name in blueprint.name
    app = Sanic('example_plugin_mount')
    app.blueprint(blueprint, url_prefix='/channels/' + channel.name)
    assert any(route.path == 'channels/office_im/webhook' for route in app.router.routes)


def test_sample_is_an_independent_installable_entry_point_package():
    package = tomllib.loads((EXAMPLE / 'pyproject.toml').read_text())
    assert package['project']['name'] == 'cota-channel-example'
    assert package['project']['entry-points']['cota.channels'] == {
        'example_im': 'cota_channel_example:ExampleIMChannel'}
    assert any(item.startswith('cota') for item in package['project']['dependencies'])


@pytest.mark.parametrize('key', ['app_id', 'webhook_secret', 'api_base', 'api_token'])
@pytest.mark.parametrize('value', ['', None, 42])
def test_required_configuration_has_helpful_errors(monkeypatch, key, value):
    channel, _ = make_channel(monkeypatch, **{key: value})
    with pytest.raises(ValueError, match=key):
        channel.validate()


@pytest.mark.parametrize('url', ['file:///tmp/messages', 'not-a-url', 'https://user:password@gateway.example',
                                 'https://gateway.example?token=x', 'https://gateway.example/#fragment'])
def test_api_base_must_be_a_plain_http_base_url(monkeypatch, url):
    channel, _ = make_channel(monkeypatch, api_base=url)
    with pytest.raises(ValueError, match='api_base'):
        channel.validate()


@pytest.mark.asyncio
async def test_signed_webhook_maps_trusted_fields_and_returns_admission_receipt(monkeypatch):
    channel, receive = make_channel(monkeypatch)
    result = await callback(channel)(request_for())
    assert result.status == 202
    assert body(result) == {'message_id': 'message-one', 'duplicate': False, 'receipt': {'status': 'queued'}}
    message = receive.await_args.args[0]
    assert message.channel == 'office_im'
    assert message.chat_id == 'room-one'
    assert message.content == '你好'
    assert message.message_id == 'message-one'
    assert message.sender_id != 'alice'
    assert message.session_key != 'office_im:room-one'
    assert message.conversation_type == 'direct'


@pytest.mark.asyncio
async def test_ack_waits_for_persisted_receipt_without_waiting_for_execution(monkeypatch):
    entered, release = asyncio.Event(), asyncio.Event()
    async def receipt():
        entered.set()
        await release.wait()
        return {'status': 'queued'}
    submission = SimpleNamespace(message_id='message-one', duplicate=True, receipt=receipt,
                                 wait=lambda: pytest.fail('webhook waited for model execution'))
    channel, _ = make_channel(monkeypatch, receive=AsyncMock(return_value=submission))
    task = asyncio.create_task(callback(channel)(request_for()))
    try:
        await asyncio.wait_for(entered.wait(), 1)
        assert not task.done()
        release.set()
        result = await asyncio.wait_for(task, 1)
        assert result.status == 202
        assert body(result)['duplicate'] is True
    finally:
        release.set()
        await task


@pytest.mark.asyncio
@pytest.mark.parametrize('signature', ['', 'bad', '0' * 64])
async def test_invalid_signature_never_submits_or_reveals_payload(monkeypatch, signature):
    channel, receive = make_channel(monkeypatch)
    result = await callback(channel)(request_for(signature=signature))
    assert result.status == 401
    receive.assert_not_awaited()
    assert 'alice' not in result.body.decode()
    assert CONFIG['webhook_secret'] not in result.body.decode()


@pytest.mark.asyncio
async def test_signature_covers_exact_raw_body_before_json_parsing(monkeypatch):
    channel, receive = make_channel(monkeypatch)
    request = request_for()
    request.body += b' '
    result = await callback(channel)(request)
    assert result.status == 401
    receive.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('payload', [[], {'text': 'hello'}, {**PAYLOAD, 'message_id': None},
                                    {**PAYLOAD, 'message_id': 7}, {**PAYLOAD, 'user_id': ''},
                                    {**PAYLOAD, 'chat_id': 'a' * 256}, {**PAYLOAD, 'text': 7},
                                    {**PAYLOAD, 'text': ' '}, {**PAYLOAD, 'text': 'a' * 32769},
                                    {**PAYLOAD, 'mentioned': 'yes'}, {**PAYLOAD, 'reply_to': ''}])
async def test_malformed_signed_payload_is_rejected_before_submission(monkeypatch, payload):
    channel, receive = make_channel(monkeypatch)
    result = await callback(channel)(request_for(payload))
    assert result.status == 400
    receive.assert_not_awaited()


@pytest.mark.asyncio
async def test_signed_invalid_json_returns_bad_request(monkeypatch):
    channel, receive = make_channel(monkeypatch)
    result = await callback(channel)(request_for(raw=b'not json'))
    assert result.status == 400
    receive.assert_not_awaited()


@pytest.mark.asyncio
async def test_group_fields_and_identity_scopes_follow_bound_context(monkeypatch):
    payload = {**PAYLOAD, 'mentioned': True, 'sender_name': 'Alice', 'reply_to': 'bot-event-one'}
    messages = []
    for name, app, mode in [('office_im', 'app-one', 'group'), ('other_im', 'app-one', 'group'),
                            ('office_im', 'app-two', 'group'), ('office_im', 'app-one', 'direct')]:
        channel, receive = make_channel(monkeypatch, name=name, app_id=app, mode=mode)
        await callback(channel)(request_for(payload))
        messages.append(receive.await_args.args[0])
    assert len({message.session_key for message in messages}) == 4
    assert len({message.sender_id for message in messages[:3]}) == 3
    assert messages[0].mentioned
    assert messages[0].sender_name == 'Alice'
    assert messages[0].reply_to == 'bot-event-one'
    assert messages[0].conversation_type == 'group'
    assert messages[3].conversation_type == 'direct'


@pytest.mark.asyncio
@pytest.mark.parametrize('error', [asyncio.QueueFull(), ApplicationUnavailable('stopping')])
async def test_busy_requires_gateway_to_retry_same_message_id(monkeypatch, error):
    channel, _ = make_channel(monkeypatch, receive=AsyncMock(side_effect=error))
    result = await callback(channel)(request_for())
    assert result.status == 503
    assert result.headers['Retry-After'] == '1'
    assert body(result)['error'] == 'retry_same_message_id'


@pytest.mark.asyncio
async def test_conflicting_duplicate_is_not_acknowledged(monkeypatch):
    channel, _ = make_channel(monkeypatch, receive=AsyncMock(side_effect=InputConflict('private data')))
    result = await callback(channel)(request_for())
    assert result.status == 409
    assert 'private data' not in result.body.decode()


@pytest.mark.asyncio
async def test_rest_send_uses_shared_client_and_stable_event_id_without_internal_retries(monkeypatch):
    requests = []
    def handle(request):
        requests.append(request)
        return httpx.Response(202)
    real_client = httpx.AsyncClient
    clients = []
    def client_factory(**kwargs):
        client = real_client(transport=httpx.MockTransport(handle), **kwargs)
        clients.append(client)
        return client
    monkeypatch.setattr(httpx, 'AsyncClient', client_factory)
    channel, _ = make_channel(monkeypatch)
    await channel.start()
    await channel.start()
    assert channel.is_running
    message = OutboundMessage('office_im', 'room-one', 'reply', event_id='bot-event-one')
    try:
        await channel.send(message)
        await channel.send(message)
        assert len(clients) == 1
        assert len(requests) == 2
        for request in requests:
            assert str(request.url) == 'https://gateway.example/v1/messages'
            assert request.headers['Authorization'] == 'Bearer outbound-test-token'
            assert request.headers['Idempotency-Key'] == 'bot-event-one'
            assert json.loads(request.content) == {'app_id': 'app-one', 'chat_id': 'room-one',
                                                   'text': 'reply', 'event_id': 'bot-event-one'}
    finally:
        await channel.stop()
        await channel.stop()
    assert clients[0].is_closed
    assert not channel.is_running


@pytest.mark.asyncio
async def test_rest_failure_propagates_for_core_delivery_retry(monkeypatch):
    requests = []
    def handle(request):
        requests.append(request)
        return httpx.Response(503)
    real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs:
                        real_client(transport=httpx.MockTransport(handle), **kwargs))
    channel, _ = make_channel(monkeypatch)
    await channel.start()
    try:
        with pytest.raises(httpx.HTTPStatusError):
            await channel.send(OutboundMessage('office_im', 'room', 'reply', event_id='event-one'))
        assert len(requests) == 1
    finally:
        await channel.stop()


@pytest.mark.asyncio
async def test_send_requires_started_client_and_stable_event_id(monkeypatch):
    channel, _ = make_channel(monkeypatch)
    with pytest.raises(RuntimeError, match='start|running'):
        await channel.send(OutboundMessage('office_im', 'room', 'reply', event_id='event-one'))
    await channel.start()
    try:
        with pytest.raises(ValueError, match='event_id'):
            await channel.send(OutboundMessage('office_im', 'room', 'reply'))
    finally:
        await channel.stop()


@pytest.mark.asyncio
async def test_non_ascii_signature_is_unauthorized(monkeypatch):
    channel, receive = make_channel(monkeypatch)
    result = await callback(channel)(request_for(signature='签名'))
    assert result.status == 401
    receive.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_persistence_receipt_is_not_acknowledged(monkeypatch):
    submission = SimpleNamespace(message_id='message-one', duplicate=False,
                                 receipt=AsyncMock(return_value=None))
    channel, _ = make_channel(monkeypatch, receive=AsyncMock(return_value=submission))
    result = await callback(channel)(request_for())
    assert result.status == 503
    assert body(result)['error'] == 'retry_same_message_id'


@pytest.mark.asyncio
async def test_real_application_persists_and_deduplicates_before_model_finishes(monkeypatch):
    from cota import Agent, Application
    from cota.store import MemoryStore

    make_channel(monkeypatch)  # Make the independent package importable in this test.
    app = Application(Agent(store=MemoryStore()), channels={
        'office_im': {**CONFIG, 'factory': 'cota_channel_example:ExampleIMChannel'}})
    entered, release = asyncio.Event(), asyncio.Event()
    async def execute(message, **kwargs):
        entered.set()
        await release.wait()
    app._execute = execute
    try:
        await app.start()
        channel = app.runner.get_channel('office_im')
        first = await callback(channel)(request_for())
        await asyncio.wait_for(entered.wait(), 1)
        assert first.status == 202
        receipt = body(first)['receipt']
        assert receipt is not None
        events = await app.store.events(receipt['session_id'])
        assert len(events) == 1
        assert events[0]['type'] == 'user_utter'
        assert not release.is_set()
        duplicate = await callback(channel)(request_for())
        assert body(duplicate)['duplicate']
        assert len(await app.store.events(receipt['session_id'])) == 1
    finally:
        release.set()
        await app.close()
