"""Trusted group facts at Web and official Feishu adapter boundaries."""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from cota.channels.queue import MessageBus
from cota.channels.web.access import ExternalAccess, GuestAccess
from cota.channels.web.service import WebService
from cota.channels.web.transport import WebSocketTransport
from cota.server import create_app
from cota.store import MemoryStore
from tests.channels.test_feishu import channel, event


def web_service():
    future = asyncio.get_running_loop().create_future()
    future.set_result('completed')
    receipt = {'session_id': 'room', 'message_id': 'input', 'status': 'completed'}
    submission = SimpleNamespace(future=future, duplicate=False, receipt=AsyncMock(return_value=receipt))
    application = SimpleNamespace(agent=SimpleNamespace(dialogue={'mode': 'group'}),
        runner=None, store=MemoryStore(), submit_message=AsyncMock(return_value=submission),
        receipt=AsyncMock(return_value=receipt))
    access = ExternalAccess(AsyncMock(return_value='alice'), AsyncMock(return_value=True))
    return WebService(application, access=access)


@pytest.mark.asyncio
async def test_web_service_passes_explicit_mention_reply_and_authenticated_user():
    service = web_service()
    try:
        await service.submit('alice', 'room', 'input', 'hello', mentioned=True, reply_to='previous')
        message = service.application.submit_message.call_args.args[0]
        assert message.sender_id == 'alice'
        assert message.sender_name is None
        assert message.mentioned is True
        assert message.reply_to == 'previous'
        assert message.conversation_type == 'group'
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_web_text_at_sign_is_not_a_mention():
    service = web_service()
    try:
        await service.submit('alice', 'room', 'input', '@currentbot hello')
        assert service.application.submit_message.call_args.args[0].mentioned is False
    finally:
        await service.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('mentioned', ['true', 1, None])
async def test_web_rejects_non_boolean_mentions(mentioned):
    service = web_service()
    with pytest.raises(ValueError, match='mentioned'):
        await service.submit('alice', 'room', 'input', 'hello', mentioned=mentioned)
    service.application.submit_message.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('spoof', [None, 'sender_name', 'conversation_type'])
async def test_web_socket_binds_identity_and_forwards_group_intent(spoof):
    transport = WebSocketTransport({}, MessageBus())
    service = SimpleNamespace(authenticate=AsyncMock(return_value='alice'), authorize=AsyncMock(),
        history=AsyncMock(return_value={'messages': [], 'through': 0, 'has_more': False}),
        submit=AsyncMock(return_value={'status': 'completed'}))
    transport.bind(service)
    await transport.start()
    frame = {'type': 'send', 'message_id': 'input', 'text': 'hello', 'mentioned': True, 'reply_to': 'parent'}
    if spoof:
        frame[spoof] = 'spoofed'
    socket = SimpleNamespace(recv=AsyncMock(side_effect=[
        json.dumps({'type': 'resume', 'token': 'credential', 'session_id': 'room'}), json.dumps(frame), None]),
        send=AsyncMock(), close=AsyncMock())
    await transport.handle(socket)
    if spoof:
        service.submit.assert_not_awaited()
    else:
        service.submit.assert_awaited_once_with('alice', 'room', 'input', 'hello', mentioned=True, reply_to='parent', attachments=None)
    await transport.stop()


@pytest.mark.parametrize('explicit', [False, True])
def test_group_web_rejects_guest_session_access(tmp_path, explicit):
    agent = SimpleNamespace(dialogue={'mode': 'group'}, store=MemoryStore())
    access = GuestAccess(tmp_path / 'key') if explicit else None
    with pytest.raises(ValueError, match='ExternalAccess'):
        create_app(agent, config_path=str(tmp_path), access=access)


def test_group_web_accepts_external_membership_checks(tmp_path):
    agent = SimpleNamespace(dialogue={'mode': 'group'}, store=MemoryStore())
    access = ExternalAccess(AsyncMock(return_value='alice'), AsyncMock(return_value=True))
    app = create_app(agent, config_path=str(tmp_path), access=access)
    assert app.ctx.web_service.access is access


@pytest.mark.asyncio
@pytest.mark.parametrize('mentions, expected', [
    ([{'id': {'open_id': 'ou_bot'}, 'name': 'irrelevant'}], True),
    ([{'id': {'open_id': 'ou_other'}, 'name': 'Our bot'}], False),
    ([], False),
])
async def test_feishu_group_mention_matches_current_bot_id_only(mentions, expected):
    ch = channel(dialogue_mode='group')
    ch._bot_open_id = 'ou_bot'
    data = event(chat='oc_group')
    data['event']['message'].update(chat_type='group', mentions=mentions, parent_id='om_parent',
                                  content=json.dumps({'text': '@Our bot hello'}))
    assert await ch._on_event(data) is True
    message = await ch.bus.consume_inbound()
    assert message.session_key == 'feishu:cli_test:t1:group:oc_group'
    assert message.sender_id == 'feishu:cli_test:t1:ou_alice'
    assert message.chat_id == 'oc_group'
    assert message.conversation_type == 'group'
    assert message.mentioned is expected
    assert message.reply_to == 'om_parent'


@pytest.mark.asyncio
async def test_feishu_group_rejects_private_and_disallowed_sender():
    ch = channel(dialogue_mode='group', allow_from=['ou_allowed'])
    ch._bot_open_id = 'ou_bot'
    assert await ch._on_event(event(user='ou_allowed')) is False
    data = event()
    data['event']['message']['chat_type'] = 'group'
    assert await ch._on_event(data) is False
    assert ch.bus.inbound_size == 0


@pytest.mark.asyncio
async def test_feishu_group_start_resolves_bot_identity_before_worker(monkeypatch):
    import cota.channels.platforms.feishu as module
    calls = []
    def respond(request):
        calls.append(request)
        if '/auth/' in request.url.path:
            return httpx.Response(200, json={'code': 0, 'tenant_access_token': 'test-token', 'expire': 7200})
        assert request.method == 'GET'
        assert request.url.path == '/open-apis/bot/v3/info'
        assert request.headers['Authorization'] == 'Bearer test-token'
        return httpx.Response(200, json={'code': 0, 'bot': {'open_id': 'ou_bot'}})
    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    monkeypatch.setattr(module.httpx, 'AsyncClient', lambda **kwargs: client)
    monkeypatch.setattr(module.importlib.util, 'find_spec', lambda name: object())
    ch = channel(dialogue_mode='group')
    process = SimpleNamespace(returncode=0, stdin=SimpleNamespace(write=lambda value: None, drain=AsyncMock()))
    async def spawn(*args, **kwargs):
        assert ch._bot_open_id == 'ou_bot'
        return process
    async def ready():
        ch._connected = True
        ch._ready.set_result(None)
    monkeypatch.setattr(module.asyncio, 'create_subprocess_exec', spawn)
    ch._read_worker = ready
    try:
        await ch.start()
        assert len(calls) == 2
    finally:
        await ch.stop()


@pytest.mark.asyncio
async def test_feishu_group_identity_missing_fails_before_admission():
    ch = channel(dialogue_mode='group')
    ch._http_client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request:
        httpx.Response(200, json={'code': 0, 'tenant_access_token': 'token', 'bot': {}})))
    try:
        with pytest.raises(RuntimeError, match='open_id'):
            await ch._load_bot_identity()
        data = event()
        data['event']['message']['chat_type'] = 'group'
        with pytest.raises(RuntimeError, match='identity'):
            await ch._on_event(data)
        assert ch.bus.inbound_size == 0
    finally:
        await ch.stop()


@pytest.mark.asyncio
async def test_web_observer_reports_pre_run_failure_with_recorded_input():
    service = web_service()
    service.application.receipt.return_value = {'session_id': 'room', 'message_id': 'input',
                                               'status': 'recorded', 'error': None}
    service.transport = SimpleNamespace(publish=AsyncMock())
    future = asyncio.get_running_loop().create_future()
    future.set_exception(RuntimeError('private setup error'))
    await service._observe('room', 'input', future)
    receipt = service.transport.publish.call_args.args[1]
    assert receipt['status'] == 'failed'
    assert receipt['error'] == 'execution_failed'
    assert 'private setup error' not in str(receipt)
