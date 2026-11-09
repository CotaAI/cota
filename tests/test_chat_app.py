import asyncio
import json
from urllib.parse import quote
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import websockets
from yarl import URL

from cota.webapp import create_app
from cota.server import create_app as core_app
from cota.store import MemoryStore
from tests.test_web_app_integration import running_app, auth, resume, receive_until, completed, history


async def api(server, method, path, who=None, data=None, status=200):
    async with server.http.request(method, URL(server.url + '/chat/api/' + path, encoded=True),
                                   headers=auth(who) if who else {}, json=data) as response:
        value = await response.json()
        assert response.status == status, value
        return value


def test_optional_application_routes_and_configuration(tmp_path):
    agent = SimpleNamespace(store=MemoryStore(), name='Bot', dialogue={'mode': 'direct'}, cleanup=AsyncMock())
    core = core_app(agent, config_path=tmp_path)
    assert not any(r.path.startswith('chat') for r in core.router.routes)
    assert not any(r.path in ('', '/') for r in core.router.routes)
    assert not (tmp_path / '.cota' / 'chat.sqlite3').exists()
    with pytest.raises(ValueError, match='enabled Web'):
        create_app(agent, config_path=tmp_path, channel_config={'web': {'enabled': False}})
    with pytest.raises(ValueError, match='access_factory'):
        create_app(agent, config_path=tmp_path, channel_config={'web': {'enabled': True, 'access_factory': 'x:y'}})


@pytest.mark.parametrize('enabled', [False, True])
def test_cli_explicitly_selects_chat_factory(tmp_path, monkeypatch, enabled):
    from unittest.mock import Mock
    import cota.__main__ as cli
    import cota.webapp
    agent = SimpleNamespace(name='Bot')
    channel_factory, chat_factory = Mock(), Mock()
    monkeypatch.setattr(cli.Agent, 'load_from_path', Mock(return_value=agent))
    monkeypatch.setattr(cli, 'configure_execution_logging', Mock())
    monkeypatch.setattr(cli, 'list_routes', Mock())
    monkeypatch.setattr(cli, 'create_server_config', Mock(return_value={}))
    monkeypatch.setattr(cli.server, 'create_app', channel_factory)
    monkeypatch.setattr(cota.webapp, 'create_app', chat_factory)
    cli.run(SimpleNamespace(config=str(tmp_path), chat_app=enabled))
    selected, unused = (chat_factory, channel_factory) if enabled else (channel_factory, chat_factory)
    selected.assert_called_once_with(agent, config_path=str(tmp_path), channel_config={})
    selected.return_value.run.assert_called_once()
    unused.assert_not_called()


@pytest.mark.asyncio
async def test_group_chat_two_members_replay_revocation_and_restart(tmp_path):
    async def respond(**kwargs):
        return {'content': 'Hello everyone'}

    async with running_app(tmp_path, respond, app_factory=create_app, mode='group') as server:
        config = await api(server, 'GET', 'config')
        assert config['mode'] == 'group'
        async with server.http.get(server.url + '/') as response:
            assert str(response.url).endswith('/chat/')
            assert 'text/html' in response.headers['Content-Type']
        alice = await api(server, 'POST', 'guests', data={'name': 'Alice'}, status=201)
        bob = await api(server, 'POST', 'guests', data={'name': 'Bob'}, status=201)
        eve = await api(server, 'POST', 'guests', data={'name': 'Eve'}, status=201)
        room = await api(server, 'POST', 'conversations', alice, {'title': 'Team'}, 201)
        sid = room['session_id']
        encoded = quote(sid, safe='')
        assert (await api(server, 'GET', f'conversations/{encoded}', alice))['session_id'] == sid
        async with server.http.get(URL(f'{server.url}/api/conversations/{encoded}/messages', encoded=True), headers=auth(alice)) as response:
            assert response.status == 200
        await api(server, 'GET', f'conversations/{sid}', eve, status=403)
        invitation = await api(server, 'POST', f'conversations/{sid}/invite', alice, {})
        await api(server, 'POST', 'join', bob, {'invite': invitation['invite']})
        async with websockets.connect(server.ws_url) as a, websockets.connect(server.ws_url) as b:
            await resume(a, alice, sid)
            await resume(b, bob, sid)
            await a.send(json.dumps({'type': 'send', 'message_id': 'ordinary', 'text': '大家好'}))
            await receive_until(a, lambda f: any(x.get('status') == 'recorded' for x in f))
            shared = await receive_until(b, lambda f: any(x.get('text') == '大家好' for x in f))
            assert next(f for f in shared if f['type'] == 'message')['sender_id'] == alice['user_id']
            assert server.model.generate_chat.await_count == 0
            await b.send(json.dumps({'type': 'send', 'message_id': 'mention', 'text': '帮忙', 'mentioned': True}))
            frames = await receive_until(b, lambda f: completed(f, 'mention', 'Hello everyone'))
            await receive_until(a, lambda f: any(x.get('text') == 'Hello everyone' for x in f))
            bot = next(f for f in frames if f.get('role') == 'bot')
            await api(server, 'POST', f'conversations/{sid}/remove', alice, {'user_id': bob['user_id']})
            await a.send(json.dumps({'type': 'send', 'message_id': 'private-after', 'text': '移除后的消息'}))
            await receive_until(a, lambda f: any(x.get('text') == '移除后的消息' for x in f))
            # No queued/live data may be delivered after the membership check fails.
            async with asyncio.timeout(3):
                while True:
                    try:
                        frame = json.loads(await b.recv())
                    except websockets.ConnectionClosed:
                        break
                    assert frame.get('text') != '移除后的消息'
            async with server.http.get(f'{server.url}/api/conversations/{sid}/messages', headers=auth(bob)) as response:
                assert response.status == 403
            await api(server, 'POST', 'join', bob, {'invite': invitation['invite']}, 403)
        async with websockets.connect(server.ws_url) as outsider:
            assert (await resume(outsider, eve, sid))[-1]['code'] == 'unauthorized'
        async with websockets.connect(server.ws_url) as reconnected:
            replay = await resume(reconnected, alice, sid, after=bot['sequence'])
            assert [f['text'] for f in replay if f['type'] == 'message'] == ['移除后的消息']
        before = await history(server, alice, sid)

    async with running_app(tmp_path, respond, app_factory=create_app, mode='group') as server:
        assert (await api(server, 'GET', 'me', alice))['name'] == 'Alice'
        listed = await api(server, 'GET', 'conversations', alice)
        assert listed['conversations'] == [room]
        assert await history(server, alice, sid) == before
        assert (await api(server, 'GET', 'conversations', bob))['conversations'] == []
        async with websockets.connect(server.ws_url) as denied:
            assert (await resume(denied, bob, sid))[-1]['code'] == 'unauthorized'


@pytest.mark.asyncio
async def test_chat_http_validation_and_direct_privacy(tmp_path):
    async def respond(**kwargs):
        return {'content': 'Hi'}
    async with running_app(tmp_path, respond, app_factory=create_app) as server:
        alice = await api(server, 'POST', 'guests', data={'name': '<script>Alice</script>'}, status=201)
        bob = await api(server, 'POST', 'guests', data={'name': 'Bob'}, status=201)
        room = await api(server, 'POST', 'conversations', alice, {'title': 'Private'}, 201)
        sid = room['session_id']
        await api(server, 'GET', f'conversations/{sid}', bob, status=403)
        await api(server, 'POST', f'conversations/{sid}/invite', alice, {}, 400)
        await api(server, 'GET', 'conversations', status=403)
        for body in ([], {'name': ''}, {'name': 'a' * 61}):
            await api(server, 'POST', 'guests', data=body, status=400)
        await api(server, 'GET', 'conversations?limit=101', alice, status=400)
        for path in ('/api/guests', '/api/conversations'):
            async with server.http.post(server.url + path, headers=auth(alice), json={}) as response:
                assert response.status == 403
        async with server.http.post(server.url + '/chat/api/guests', json={'name': 'bad'},
                                     headers={'Origin': 'https://attacker.invalid'}) as response:
            assert response.status == 403


@pytest.mark.asyncio
async def test_chat_summary_read_cursor_and_recent_pages(tmp_path):
    async def respond(**kwargs):
        return {'content': 'Hi'}
    async with running_app(tmp_path, respond, app_factory=create_app, mode='group') as server:
        alice = await api(server, 'POST', 'guests', data={'name': 'Alice'}, status=201)
        bob = await api(server, 'POST', 'guests', data={'name': 'Bob'}, status=201)
        sid = (await api(server, 'POST', 'conversations', alice, {'title': 'Room'}, 201))['session_id']
        invitation = await api(server, 'POST', f'conversations/{sid}/invite', alice, {})
        await api(server, 'POST', 'join', bob, {'invite': invitation['invite']})
        async with websockets.connect(server.ws_url) as socket:
            await resume(socket, alice, sid)
            for n in range(3):
                await socket.send(json.dumps({'type': 'send', 'message_id': f'm{n}', 'text': f'text{n}'}))
                await receive_until(socket, lambda f: any(x.get('status') == 'recorded' and x.get('message_id') == f'm{n}' for x in f))
        summary = await api(server, 'GET', f'conversations/{sid}/summary', bob)
        assert summary['unread'] == 3
        assert summary['last_message']['text'] == 'text2'
        assert summary['last_active'] is not None
        assert (await api(server, 'GET', f'conversations/{sid}/summary', alice))['unread'] == 0
        await api(server, 'POST', f'conversations/{sid}/read', bob, {'sequence': summary['through']})
        assert (await api(server, 'GET', f'conversations/{sid}/summary', bob))['unread'] == 0
        await api(server, 'POST', f'conversations/{sid}/read', bob, {'sequence': summary['through'] + 100}, 400)
        async with server.http.get(f'{server.url}/api/conversations/{sid}/messages?recent=1&limit=2', headers=auth(bob)) as response:
            page = await response.json()
            assert response.status == 200
        assert [m['text'] for m in page['messages']] == ['text1', 'text2']
        assert page['has_more']
        async with server.http.get(f'{server.url}/api/conversations/{sid}/messages?before_sequence={page["cursor"]}&limit=2', headers=auth(bob)) as response:
            assert [m['text'] for m in (await response.json())['messages']] == ['text0']
        await api(server, 'POST', f'conversations/{sid}/remove', alice, {'user_id': bob['user_id']})
        await api(server, 'GET', f'conversations/{sid}/summary', bob, status=403)
        await api(server, 'POST', f'conversations/{sid}/read', bob, {'sequence': 0}, 403)


@pytest.mark.asyncio
async def test_one_socket_subscribes_sends_and_revokes_second_room(tmp_path):
    async def respond(**kwargs):
        return {'content': 'Hi'}
    async with running_app(tmp_path, respond, app_factory=create_app, mode='group') as server:
        alice = await api(server, 'POST', 'guests', data={'name': 'Alice'}, status=201)
        bob = await api(server, 'POST', 'guests', data={'name': 'Bob'}, status=201)
        rooms = [(await api(server, 'POST', 'conversations', alice, {'title': str(n)}, 201))['session_id'] for n in range(2)]
        for sid in rooms:
            invite = await api(server, 'POST', f'conversations/{sid}/invite', alice, {})
            await api(server, 'POST', 'join', bob, {'invite': invite['invite']})
        async with websockets.connect(server.ws_url) as socket:
            await resume(socket, bob, rooms[0])
            await socket.send(json.dumps({'type': 'subscribe', 'session_id': rooms[1], 'recent': True}))
            frames = await receive_until(socket, lambda f: any(x.get('type') == 'ready' for x in f))
            assert frames[-1]['session_id'] == rooms[1]
            await socket.send(json.dumps({'type': 'send', 'session_id': rooms[1], 'message_id': 'secondary', 'text': 'hello second'}))
            frames = await receive_until(socket, lambda f: any(x.get('status') == 'recorded' for x in f))
            assert all(x.get('session_id') == rooms[1] for x in frames)
            await api(server, 'POST', f'conversations/{rooms[1]}/remove', alice, {'user_id': bob['user_id']})
            await socket.send(json.dumps({'type': 'send', 'session_id': rooms[1], 'message_id': 'revoked', 'text': 'no'}))
            frames = await receive_until(socket, lambda f: any(x.get('code') == 'unauthorized' for x in f))
            assert frames[-1]['code'] == 'unauthorized'
        assert not server.app.ctx.web_service.transport._connections
