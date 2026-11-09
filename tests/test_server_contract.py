"""Public server boundaries: real HTTP, shared execution and owned shutdown."""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import quote

import pytest
import websockets
from yarl import URL

from cota.channels.web.access import ExternalAccess
from cota.server import create_app
from cota.store import MemoryStore
from tests.test_web_app_integration import (
    running_app, guest_conversation, auth, resume, send, receive_until, completed,
)


def minimal_agent():
    return SimpleNamespace(store=MemoryStore(), name='Test', cleanup=AsyncMock())


@pytest.mark.parametrize('channels', [[], {'web': None}, {'web': True},
    {'web': {'enabled': 'false'}}, {'unknown': {'enabled': True}},
    {'web': {'enabled': True, 'cors_origins': 'https://example.com'}},
    {'web': {'enabled': True, 'cors_origins': ['null']}},
    {'web': {'enabled': True, 'cors_origins': ['https://example.com/path']}},
    {'web': {'enabled': True, 'cors_origins': ['https://user:pass@example.com']}},
    {'web': {'enabled': True, 'cors_origins': ['http://[broken']}},
    {'web': {'enabled': True, 'transport': 'sse'}},
])
def test_invalid_deployment_fails_at_factory_with_clear_error(channels):
    with pytest.raises(ValueError, match='channel|origin|transport'):
        create_app(minimal_agent(), channel_config=channels)


def test_missing_agent_has_clear_error():
    with pytest.raises(ValueError, match='agent|Agent'):
        create_app()


@pytest.mark.asyncio
async def test_http_submit_is_nonblocking_and_deduplicates_with_websocket(tmp_path):
    entered, release = asyncio.Event(), asyncio.Event()
    async def model(**kwargs):
        entered.set()
        await release.wait()
        return {'content': 'HTTP answer'}
    async with running_app(tmp_path, model) as server:
        who, sid = await guest_conversation(server)
        url = server.url + f'/api/conversations/{sid}/messages'
        try:
            async with server.http.post(url, headers=auth(who), json={'text': 'hello'}) as response:
                assert response.status == 202
                receipt = await response.json()
                mid = receipt['message_id']
                assert mid and receipt['session_id'] == sid and receipt['duplicate'] is False
                location = response.headers['Location']
                assert location.endswith('/submissions/' + mid)
            await asyncio.wait_for(entered.wait(), 3)
            async with websockets.connect(server.ws_url) as ws:
                await resume(ws, who, sid)
                await send(ws, mid, 'hello')
                frames = await receive_until(ws, lambda rows: any(r.get('type') == 'receipt' for r in rows))
                assert next(r for r in frames if r.get('type') == 'receipt')['duplicate'] is True
                async with server.http.post(url, headers=auth(who), json={'text': 'changed', 'message_id': mid}) as response:
                    assert response.status == 409
                    assert (await response.json())['error'] == 'input_conflict'
                release.set()
                await receive_until(ws, lambda rows: completed(rows, mid, 'HTTP answer'))
            async with server.http.get(server.url + location, headers=auth(who)) as response:
                assert (await response.json())['status'] == 'completed'
            assert server.model.generate_chat.await_count == 1
            async with server.http.get(url, headers=auth(who)) as response:
                assert [m['text'] for m in (await response.json())['messages']] == ['hello', 'HTTP answer']
        finally:
            release.set()


@pytest.mark.asyncio
async def test_http_validation_authorization_and_safe_json_errors(tmp_path, monkeypatch):
    async def model(**kwargs):
        raise AssertionError('Invalid requests must not execute')
    async with running_app(tmp_path, model) as server:
        who, sid = await guest_conversation(server)
        other, _ = await guest_conversation(server)
        url = server.url + f'/api/conversations/{sid}/messages'
        for headers in ({}, auth(other)):
            async with server.http.post(url, headers=headers, json={'text': 'hello'}) as response:
                assert response.status == 403
                assert (await response.json())['error'] == 'unauthorized'
        invalid = [[], {}, {'text': ''}, {'text': 'x', 'user_id': 'forged'},
                   {'text': 'x', 'session_id': sid}, {'text': 'x', 'mentioned': 'true'},
                   {'text': 'x', 'message_id': ''}, {'text': 'x', 'reply_to': 2},
                   {'text': 'x' * 32769}]
        for body in invalid:
            async with server.http.post(url, headers=auth(who), json=body) as response:
                assert response.status == 400, body
                assert (await response.json())['error'] == 'invalid_request'
        async with server.http.post(url, headers={**auth(who), 'Content-Type': 'application/json'}, data='{') as response:
            assert response.status == 400 and (await response.json())['error'] == 'invalid_request'
        async with server.http.post(url, headers=auth(who), data='hello') as response:
            assert response.status == 415
            assert (await response.json())['error'] == 'unsupported_media_type'
        async with server.http.post(url, headers=auth(who), json={'text': 'x' * (300 * 1024)}) as response:
            assert response.status == 413 and (await response.json())['error'] == 'payload_too_large'
        for path, method, status in [('/does-not-exist', 'GET', 404), ('/version', 'POST', 405)]:
            async with server.http.request(method, server.url + path, headers={'Accept': 'text/html'}) as response:
                assert response.status == status
                assert 'error' in await response.json()
                if status == 405:
                    assert 'GET' in response.headers['Allow']
        monkeypatch.setattr(server.app.ctx.web_service, 'history', AsyncMock(side_effect=RuntimeError('private-credential')))
        async with server.http.get(url, headers={**auth(who), 'Accept': 'text/html'}) as response:
            assert response.status == 500
            body = await response.json()
            assert body['error'] == 'internal_error' and 'private-credential' not in json.dumps(body)
        server.model.generate_chat.assert_not_awaited()


@pytest.mark.asyncio
async def test_readiness_detects_missing_failed_and_draining_channels(tmp_path):
    async def model(**kwargs):
        raise AssertionError('Health must not invoke model')
    async with running_app(tmp_path, model) as server:
        manager = server.app.ctx.runner.channel_manager
        manager.startup_failures['web'] = 'private-credential'
        async with server.http.get(server.url + '/api/health') as response:
            assert response.status == 503
            value = await response.json()
            assert value['success'] is False and 'private-credential' not in json.dumps(value)
        manager.startup_failures.clear()
        web = manager.channels.pop('web')
        try:
            async with server.http.get(server.url + '/api/health') as response:
                assert response.status == 503
        finally:
            manager.channels['web'] = web
        entered, release = asyncio.Event(), asyncio.Event()
        close = server.app.ctx.application._teardown
        async def gated_close():
            entered.set()
            await release.wait()
            await close()
        server.app.ctx.application._teardown = gated_close
        task = asyncio.create_task(server.app.ctx.application.close())
        await entered.wait()
        try:
            async with server.http.get(server.url + '/api/health') as response:
                assert response.status == 503 and (await response.json())['success'] is False
        finally:
            release.set()
            await task


@pytest.mark.asyncio
async def test_http_submission_backpressure_and_shutdown(tmp_path):
    entered, release = asyncio.Event(), asyncio.Event()
    async def model(**kwargs):
        entered.set()
        await release.wait()
        return {'content': 'done'}
    async with running_app(tmp_path, model) as server:
        server.app.ctx.runner.max_pending = 1
        who, sid = await guest_conversation(server)
        url = server.url + f'/api/conversations/{sid}/messages'
        try:
            async with server.http.post(url, headers=auth(who), json={'text': 'first', 'message_id': 'one'}) as response:
                assert response.status == 202
            await asyncio.wait_for(entered.wait(), 3)
            async with server.http.post(url, headers=auth(who), json={'text': 'second', 'message_id': 'two'}) as response:
                assert response.status == 429 and response.headers['Retry-After'] == '1'
                assert (await response.json())['error'] == 'busy'
        finally:
            release.set()
        await server.app.ctx.application.close()
        async with server.http.post(url, headers=auth(who), json={'text': 'third'}) as response:
            assert response.status == 503 and (await response.json())['error'] == 'not_ready'


@pytest.mark.asyncio
async def test_http_encoded_ids_bounded_history_and_large_valid_text(tmp_path):
    sid, mid = 'room/a%2Fb', 'input/a%2Fb'
    async def authenticate(token):
        return 'alice'
    async def authorize(user, session):
        return session == sid
    async def model(**kwargs):
        return {'content': 'done'}
    async with running_app(tmp_path, model, access=ExternalAccess(authenticate, authorize)) as server:
        path = f'/api/conversations/{quote(sid, safe="")}/messages'
        async with server.http.post(URL(server.url + path, encoded=True),
                                    headers={'Authorization': 'Bearer token', 'Content-Type': 'Application/JSON; charset=utf-8'},
                                    json={'text': '\x01' * 32768, 'message_id': mid}) as response:
            assert response.status == 202
            location = response.headers['Location']
            assert location.endswith(quote(mid, safe=''))
        async with asyncio.timeout(5):
            while True:
                async with server.http.get(URL(server.url + location, encoded=True), headers={'Authorization': 'Bearer token'}) as response:
                    receipt = await response.json()
                if receipt.get('status') == 'completed':
                    break
                await asyncio.sleep(.01)
        async with server.http.get(URL(server.url + path + '?until_sequence=1', encoded=True),
                                   headers={'Authorization': 'Bearer token'}) as response:
            page = await response.json()
            assert page['through'] == 1 and page['cursor'] <= 1
            assert all(row['sequence'] <= 1 for row in page['messages'])


@pytest.mark.asyncio
async def test_cors_preflight_and_exposed_receipt_location(tmp_path):
    def factory(*args, **kwargs):
        kwargs['channel_config']['web']['cors_origins'] = ['https://frontend.example']
        return create_app(*args, **kwargs)
    async def model(**kwargs):
        return {'content': 'done'}
    async with running_app(tmp_path, model, app_factory=factory) as server:
        who, sid = await guest_conversation(server)
        url = server.url + f'/api/conversations/{sid}/messages'
        headers = {'Origin': 'https://frontend.example'}
        async with server.http.options(url, headers={**headers, 'Access-Control-Request-Method': 'POST',
                                                     'Access-Control-Request-Headers': 'authorization,content-type'}) as response:
            assert response.status == 204
            assert response.headers['Access-Control-Allow-Origin'] == headers['Origin']
        async with server.http.post(url, headers={**headers, **auth(who)}, json={'text': 'hello'}) as response:
            assert response.status == 202
            assert 'Location' in response.headers['Access-Control-Expose-Headers']
        for origin in ('https://other.example', 'http://[broken'):
            async with server.http.get(url, headers={**auth(who), 'Origin': origin}) as response:
                assert response.status == 403 and (await response.json())['error'] == 'origin_not_allowed'


@pytest.mark.asyncio
@pytest.mark.parametrize('fails', [False, True])
async def test_cancelled_server_stop_retains_ordered_cleanup(fails):
    app = create_app(minimal_agent())
    stop = next(item.listener for item in app._future_listeners
                if item.event == 'before_server_stop' and item.listener.__name__ == 'stop')
    entered, release = asyncio.Event(), asyncio.Event()
    async def close():
        entered.set()
        await release.wait()
        if fails:
            raise RuntimeError('cleanup failure')
    app.ctx.application.close = close
    app.ctx.web_service.close = AsyncMock()
    first = asyncio.create_task(stop(app, asyncio.get_running_loop()))
    await entered.wait()
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    try:
        app.ctx.web_service.close.assert_not_awaited()
    finally:
        release.set()
    if fails:
        with pytest.raises(RuntimeError, match='cleanup failure'):
            await stop(app, asyncio.get_running_loop())
    else:
        await stop(app, asyncio.get_running_loop())
    app.ctx.web_service.close.assert_awaited_once()


def test_default_access_uses_loaded_bot_directory(tmp_path):
    agent = minimal_agent()
    agent.config_path = tmp_path
    app = create_app(agent)
    assert app.ctx.web_service.access.key_path == tmp_path / '.cota' / 'web.key'


@pytest.mark.asyncio
@pytest.mark.parametrize('during_admission', [False, True])
async def test_shutdown_during_authentication_returns_not_ready(tmp_path, during_admission):
    entered, release = asyncio.Event(), asyncio.Event()
    async def authenticate(token):
        if not during_admission:
            entered.set()
            await release.wait()
        return 'alice'
    async def authorize(user, session):
        return True
    async def model(**kwargs):
        raise AssertionError('Closed application must not execute')
    async with running_app(tmp_path, model, access=ExternalAccess(authenticate, authorize)) as server:
        if during_admission:
            admissible = server.store.ensure_input_admissible
            async def gated_admission(*args, **kwargs):
                entered.set()
                await release.wait()
                return await admissible(*args, **kwargs)
            server.store.ensure_input_admissible = gated_admission
        async def submit():
            async with server.http.post(server.url + '/api/conversations/room/messages',
                                        headers={'Authorization': 'Bearer token'}, json={'text': 'hello'}) as response:
                return response.status, await response.json()
        pending = asyncio.create_task(submit())
        await asyncio.wait_for(entered.wait(), 2)
        try:
            await server.app.ctx.application.close()
        finally:
            release.set()
        status, body = await pending
        assert status == 503 and body['error'] == 'not_ready'
        server.model.generate_chat.assert_not_awaited()


@pytest.mark.asyncio
async def test_http_group_messages_and_mentions_follow_shared_application_contract(tmp_path):
    async def authenticate(token):
        return token
    async def authorize(user, session):
        return session == 'room' and user in ('alice', 'bob')
    async def model(**kwargs):
        return {'content': 'group answer'}
    async with running_app(tmp_path, model, access=ExternalAccess(authenticate, authorize), mode='group') as server:
        url = server.url + '/api/conversations/room/messages'
        async with server.http.post(url, headers={'Authorization': 'Bearer alice'},
                                    json={'text': 'discussion', 'message_id': 'one'}) as response:
            assert response.status == 202 and (await response.json())['status'] == 'recorded'
        server.model.generate_chat.assert_not_awaited()
        async with server.http.post(url, headers={'Authorization': 'Bearer bob'},
                                    json={'text': 'help us', 'message_id': 'two', 'mentioned': True, 'reply_to': 'one'}) as response:
            assert response.status == 202
            location = response.headers['Location']
        async with asyncio.timeout(5):
            while True:
                async with server.http.get(server.url + location, headers={'Authorization': 'Bearer bob'}) as response:
                    value = await response.json()
                if value['status'] == 'completed':
                    break
                await asyncio.sleep(.01)
        async with server.http.get(url, headers={'Authorization': 'Bearer alice'}) as response:
            messages = (await response.json())['messages']
        assert [m['text'] for m in messages] == ['discussion', 'help us', 'group answer']
        assert messages[0]['sender_id'] == 'alice' and messages[1]['sender_id'] == 'bob'
        assert messages[1]['reply_to'] == 'one' and messages[1]['mentioned'] is True
