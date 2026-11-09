"""Real localhost HTTP/WebSocket acceptance with Pi and file-backed SQLite.

Only the model call is deterministic; server listeners, transports, execution,
Store, user memory, and reconnect all use the production implementation.
"""
import asyncio
from contextlib import asynccontextmanager
import json
import socket
from types import SimpleNamespace
from unittest.mock import AsyncMock

import aiohttp
import pytest
import websockets

from cota.agent import Agent
from cota.executor.tools import ToolRegistry
from cota.executor.user_memory import SQLUserMemory
from cota.server import create_app
from cota.store import SQLStore


def tool_call(name, args, identity):
    return {'id': identity, 'type': 'function',
            'function': {'name': name, 'arguments': json.dumps(args)}}


def latest_turn(messages):
    index = max(i for i, message in enumerate(messages) if message['role'] == 'user')
    return messages[index]['content'], messages[index + 1:]


@asynccontextmanager
async def running_app(tmp_path, respond, *, access=None, app_factory=create_app, mode='direct'):
    database = str(tmp_path / 'web.db')
    store, memory = SQLStore(db=database), SQLUserMemory(db=database)
    model = SimpleNamespace(generate_chat=AsyncMock(side_effect=respond))
    agent = Agent(name='Socket test bot', store=store, llms={'default': model},
                  dialogue={'mode': mode, 'llm': 'default', 'max_iterations': 8, 'max_tokens': 500})
    agent.config_path = str(tmp_path)
    agent.workspace_path = str(tmp_path / 'workspace')
    (tmp_path / 'workspace').mkdir(exist_ok=True)
    agent.user_memory = memory
    agent._tool_registry = ToolRegistry()
    app = app_factory(agent, config_path=str(tmp_path), **({'access': access} if access else {}), channel_config={
        'web': {'enabled': True, 'transport': 'websocket', 'concurrency': 2}})
    # Sanic's production optimization rewrites shared class methods. Multiple
    # app instances in one pytest process must retain the unmodified handlers.
    app.config.TOUCHUP = False
    server = None
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    started = False
    try:
        # Sanic 23 normalizes port=0 to 8000; pre-bind to obtain a real ephemeral port.
        listener.bind(('127.0.0.1', 0))
        listener.listen(128)
        listener.setblocking(False)
        server = await app.create_server(sock=listener, access_log=False,
                                         return_asyncio_server=True)
        await server.startup()
        started = True
        await server.before_start()
        await server.start_serving()
        await server.after_start()
        port = server.server.sockets[0].getsockname()[1]
        async with aiohttp.ClientSession() as http:
            yield SimpleNamespace(app=app, agent=agent, model=model, store=store, memory=memory,
                                  http=http, url=f'http://127.0.0.1:{port}',
                                  ws_url=f'ws://127.0.0.1:{port}/ws')
    finally:
        if server is not None:
            if started:
                await server.before_stop()
            await server.close()
            if started:
                await server.after_stop()
        store.engine.dispose()
        memory._engine.dispose()
        listener.close()


def auth(guest):
    return {'Authorization': 'Bearer ' + guest['token']}


async def guest_conversation(server):
    async with server.http.post(server.url + '/api/guests') as response:
        assert response.status == 201
        guest = await response.json()
    async with server.http.post(server.url + '/api/conversations', headers=auth(guest)) as response:
        assert response.status == 201
        return guest, (await response.json())['session_id']


async def receive_until(socket, predicate, *, timeout=20):
    frames = []
    async with asyncio.timeout(timeout):
        while not predicate(frames):
            frames.append(json.loads(await socket.recv()))
    return frames


async def resume(socket, guest, session_id, after=0):
    await socket.send(json.dumps({'type': 'resume', 'token': guest['token'],
                                 'session_id': session_id, 'after_sequence': after}))
    return await receive_until(socket, lambda frames: any(f['type'] in ('ready', 'error') for f in frames))


async def send(socket, message_id, text):
    await socket.send(json.dumps({'type': 'send', 'message_id': message_id, 'text': text}))


def completed(frames, message_id, answer):
    return (any(f['type'] == 'receipt' and f['message_id'] == message_id and
                f['status'] == 'completed' for f in frames)
            and any(f['type'] == 'message' and f['role'] == 'bot' and f['text'] == answer for f in frames))


async def history(server, guest, session_id, after=0):
    async with server.http.get(f'{server.url}/api/conversations/{session_id}/messages',
                               params={'after_sequence': after}, headers=auth(guest)) as response:
        assert response.status == 200
        return await response.json()


@pytest.mark.asyncio
async def test_socket_users_run_concurrently_with_fifo_and_private_sql_memory(tmp_path):
    entered, release = asyncio.Event(), asyncio.Event()
    turns = []
    snapshots = {}

    async def respond(**kwargs):
        text, following = latest_turn(kwargs['messages'])
        turns.append(text)
        snapshots[text] = [m['content'] for m in kwargs['messages'] if m['role'] == 'user']
        owner = text.split('-')[0]
        other = 'bob' if owner == 'alice' else 'alice'
        assert owner + '_private_color' in kwargs['messages'][0]['content']
        assert other + '_private_color' not in kwargs['messages'][0]['content']
        if text == 'alice-one':
            entered.set()
            await release.wait()
        return {'content': 'answer:' + text}

    async with running_app(tmp_path, respond) as server:
        alice, alice_session = await guest_conversation(server)
        bob, bob_session = await guest_conversation(server)
        await server.memory.aset(alice['user_id'], 'color', 'alice_private_color')
        await server.memory.aset(bob['user_id'], 'color', 'bob_private_color')
        async with websockets.connect(server.ws_url) as a, websockets.connect(server.ws_url) as b:
            assert (await resume(a, alice, alice_session))[-1]['type'] == 'ready'
            assert (await resume(b, bob, bob_session))[-1]['type'] == 'ready'
            await send(a, 'a1', 'alice-one')
            await asyncio.wait_for(entered.wait(), 20)
            try:
                await send(a, 'a2', 'alice-two')
                await send(b, 'b1', 'bob-one')
                b_frames = await receive_until(b, lambda f: completed(f, 'b1', 'answer:bob-one'))
                assert turns == ['alice-one', 'bob-one']
                assert all(f.get('session_id') == bob_session for f in b_frames)
                assert [f['text'] for f in b_frames if f['type'] == 'message' and f['role'] == 'user'] == ['bob-one']
                assert snapshots['bob-one'] == ['bob-one']
            finally:
                release.set()
            a_frames = await receive_until(a, lambda f: completed(f, 'a1', 'answer:alice-one') and
                                            completed(f, 'a2', 'answer:alice-two'))
            assert all(f.get('session_id') == alice_session for f in a_frames)
            assert [f['text'] for f in a_frames if f['type'] == 'message' and f['role'] == 'user'] == [
                'alice-one', 'alice-two']
            assert [f['text'] for f in a_frames if f['type'] == 'message' and f['role'] == 'bot'] == [
                'answer:alice-one', 'answer:alice-two']
            assert snapshots['alice-two'] == ['alice-one', 'alice-two']
            assert await server.memory.aget(alice['user_id'], 'color') == 'alice_private_color'
            assert await server.memory.aget(bob['user_id'], 'color') == 'bob_private_color'
            a_history = await history(server, alice, alice_session)
            assert [f['text'] for f in a_history['messages']] == [
                'alice-one', 'alice-two', 'answer:alice-one', 'answer:alice-two']
            # Every visible answer already exists under the same durable identity.
            for frame in a_frames + b_frames:
                if frame['type'] == 'message':
                    event = await server.store.event_by_id(frame['session_id'], frame['event_id'])
                    assert event['sequence'] == frame['sequence']
                    assert event['payload']['text'] == frame['text']


@pytest.mark.asyncio
async def test_socket_disconnect_resume_duplicates_and_conflict(tmp_path):
    entered, release = asyncio.Event(), asyncio.Event()

    async def respond(**kwargs):
        entered.set()
        await release.wait()
        return {'content': 'finished after reconnect'}

    async with running_app(tmp_path, respond) as server:
        guest, session = await guest_conversation(server)
        async with websockets.connect(server.ws_url) as original:
            await resume(original, guest, session)
            await send(original, 'stable-id', 'keep running')
            await asyncio.wait_for(entered.wait(), 20)
        try:
            async with websockets.connect(server.ws_url) as resumed:
                replay = await resume(resumed, guest, session)
                assert [f['text'] for f in replay if f['type'] == 'message'] == ['keep running']
                await send(resumed, 'stable-id', 'keep running')
                duplicate = await receive_until(resumed, lambda f: any(x['type'] == 'receipt' for x in f))
                assert duplicate[-1]['duplicate'] is True
                await send(resumed, 'stable-id', 'changed content')
                conflict = await receive_until(resumed, lambda f: any(x['type'] == 'error' for x in f))
                assert conflict[-1]['code'] == 'invalid_request'
                release.set()
                frames = await receive_until(resumed, lambda f: completed(f, 'stable-id', 'finished after reconnect'))
                bot = next(f for f in frames if f['type'] == 'message' and f['role'] == 'bot')
                assert server.model.generate_chat.await_count == 1
                page = await history(server, guest, session)
                assert [f['text'] for f in page['messages']] == ['keep running', 'finished after reconnect']
            async with websockets.connect(server.ws_url) as caught_up:
                replay = await resume(caught_up, guest, session, after=bot['sequence'])
                assert [f for f in replay if f['type'] == 'message'] == []
                assert replay[-1]['cursor'] >= bot['sequence']
                await send(caught_up, 'stable-id', 'keep running')
                duplicate = await receive_until(caught_up, lambda f: any(x['type'] == 'receipt' for x in f))
                assert duplicate[-1]['status'] == 'completed'
                assert server.model.generate_chat.await_count == 1
        finally:
            release.set()


@pytest.mark.asyncio
async def test_http_and_socket_enforce_conversation_ownership(tmp_path):
    async def respond(**kwargs):
        return {'content': 'private'}

    async with running_app(tmp_path, respond) as server:
        alice, session = await guest_conversation(server)
        bob, _ = await guest_conversation(server)
        for headers in ({}, auth(bob), {'Authorization': 'Bearer invalid'}):
            async with server.http.get(f'{server.url}/api/conversations/{session}/messages', headers=headers) as response:
                assert response.status == 403
        async with websockets.connect(server.ws_url) as socket:
            frame = (await resume(socket, bob, session))[-1]
            assert frame['type'] == 'error' and frame['code'] == 'unauthorized'
        async with websockets.connect(server.ws_url) as socket:
            await resume(socket, alice, session)
            await socket.send(json.dumps({'type': 'send', 'message_id': 'spoof', 'text': 'hi',
                                          'sender_id': bob['user_id']}))
            error = await receive_until(socket, lambda f: any(x['type'] == 'error' for x in f))
            assert error[-1]['code'] == 'invalid_request'
        for path in ('/api/chat', '/api/tracker', '/sse', '/api/session/foo/trace', '/api/workspace'):
            async with server.http.get(server.url + path) as response:
                assert response.status == 404
        assert server.model.generate_chat.await_count == 0
        assert (await history(server, alice, session))['messages'] == []


@pytest.mark.asyncio
async def test_recreated_server_preserves_identity_history_receipts_and_memory(tmp_path):
    async def respond(**kwargs):
        return {'content': 'durable answer'}

    async with running_app(tmp_path, respond) as server:
        guest, session = await guest_conversation(server)
        async with websockets.connect(server.ws_url) as socket:
            await resume(socket, guest, session)
            await send(socket, 'saved', 'durable question')
            await receive_until(socket, lambda f: completed(f, 'saved', 'durable answer'))
        await server.memory.aset(guest['user_id'], 'preference', 'tea')
        before = await history(server, guest, session)

    async with running_app(tmp_path, respond) as recreated:
        assert await history(recreated, guest, session) == before
        assert await recreated.memory.aget(guest['user_id'], 'preference') == 'tea'
        async with websockets.connect(recreated.ws_url) as socket:
            replay = await resume(socket, guest, session)
            assert [f for f in replay if f['type'] == 'message'] == before['messages']
            await send(socket, 'saved', 'durable question')
            receipt = await receive_until(socket, lambda f: any(x['type'] == 'receipt' for x in f))
            assert receipt[-1]['status'] == 'completed' and receipt[-1]['duplicate'] is True
            assert recreated.model.generate_chat.await_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('text', ['中' * 22000, 'controls:' + '\x01' * 32759],
                         ids=['chinese-22000-characters', 'escaped-controls-at-text-limit'])
async def test_large_valid_text_frames_complete_once_without_disconnect(tmp_path, text):
    async def respond(**kwargs):
        actual, _ = latest_turn(kwargs['messages'])
        assert actual == text
        return {'content': 'large input received'}

    async with running_app(tmp_path, respond) as server:
        guest, session = await guest_conversation(server)
        async with websockets.connect(server.ws_url) as socket:
            await resume(socket, guest, session)
            # Exercise actual UTF-8 byte size and JSON control-character escaping.
            frame = json.dumps({'type': 'send', 'message_id': 'large', 'text': text}, ensure_ascii=False)
            assert 65536 < len(frame.encode('utf-8')) < 256 * 1024
            await socket.send(frame)
            frames = await receive_until(socket, lambda f: completed(f, 'large', 'large input received'))
            assert not any(frame['type'] == 'error' for frame in frames)
            assert server.model.generate_chat.await_count == 1
            pong = await socket.ping()
            await asyncio.wait_for(pong, 2)
            page = await history(server, guest, session)
            assert [message['text'] for message in page['messages']] == [text, 'large input received']


@pytest.mark.asyncio
async def test_external_identity_without_web_tables_and_server_generated_message_id(tmp_path):
    from cota.channels.web.access import ExternalAccess
    import sqlalchemy as sa
    async def authenticate(token):
        if token not in ('alice-token', 'bob-token'):
            raise PermissionError('invalid')
        return token.removesuffix('-token')
    async def authorize(user_id, session_id):
        return session_id == 'app:' + user_id
    async def respond(**kwargs):
        return {'content': 'external answer'}
    access = ExternalAccess(authenticate, authorize)
    async with running_app(tmp_path, respond, access=access) as server:
        guest = {'token': 'alice-token', 'user_id': 'alice'}
        async with server.http.post(server.url + '/api/guests') as response:
            assert response.status == 403
        async with server.http.post(server.url + '/api/conversations', headers=auth(guest)) as response:
            assert response.status == 403
        async with websockets.connect(server.ws_url) as socket:
            assert (await resume(socket, guest, 'app:alice'))[-1]['type'] == 'ready'
            await socket.send(json.dumps({'type': 'send', 'text': 'without an ID'}))
            frames = await receive_until(socket, lambda frames: any(
                f['type'] == 'receipt' and f['status'] == 'completed' for f in frames))
            receipt = next(f for f in frames if f['type'] == 'receipt')
            message_id = receipt['message_id']
            assert message_id
            user = next(f for f in frames if f['type'] == 'message' and f['role'] == 'user')
            assert user['message_id'] == message_id
            await send(socket, message_id, 'without an ID')
            repeated = await receive_until(socket, lambda f: any(x['type'] == 'receipt' for x in f))
            assert repeated[-1]['status'] == 'completed'
            assert server.model.generate_chat.await_count == 1
        async with server.http.get(server.url + '/api/conversations/app:alice/messages',
                                   headers={'Authorization': 'Bearer bob-token'}) as response:
            assert response.status == 403
        assert not any(name.startswith('web_') for name in sa.inspect(server.store.engine).get_table_names())


@pytest.mark.asyncio
async def test_failure_before_run_preserves_accepted_input_and_returns_terminal_receipt(tmp_path, monkeypatch):
    from cota.processor import Processor
    async def unavailable(*args, **kwargs):
        raise OSError('memory unavailable')
    monkeypatch.setattr(Processor, '_load_user_context', unavailable)
    async def respond(**kwargs):
        raise AssertionError('Must fail before invoking model')
    async with running_app(tmp_path, respond) as server:
        guest, session = await guest_conversation(server)
        async with websockets.connect(server.ws_url) as socket:
            await resume(socket, guest, session)
            await send(socket, 'failed-input', 'hello')
            frames = await receive_until(socket, lambda frames: any(
                f['type'] == 'receipt' and f['status'] == 'failed' for f in frames), timeout=2)
            assert frames[-1]['message_id'] == 'failed-input'
            assert [m['text'] for m in (await history(server, guest, session))['messages']] == ['hello']


@pytest.mark.asyncio
async def test_recovered_web_input_delivers_canonical_live_reply_once(tmp_path):
    """Startup recovery has no submit callback; normal channel delivery must work."""
    from cota.inputs import input_event_id

    async def must_not_run(**kwargs):
        raise AssertionError('The accepted input must remain unstarted before restart')

    async with running_app(tmp_path, must_not_run) as original:
        guest, session = await guest_conversation(original)
        # Persist a real Web submission at the crash boundary before scheduling.
        original.app.ctx.runner._pump = lambda: None
        async with original.http.post(f'{original.url}/api/conversations/{session}/messages',
                headers=auth(guest), json={'message_id': 'recover-live', 'text': 'recover this question'}) as response:
            assert response.status == 202
            assert (await response.json())['message_id'] == 'recover-live'
        accepted = await original.store.event_by_id(session, input_event_id('recover-live'))
        assert accepted is not None
        assert not await original.store._query_events(session, kinds=('run_started',))
        original.model.generate_chat.assert_not_awaited()

    entered, release = asyncio.Event(), asyncio.Event()

    async def recovered_model(**kwargs):
        assert [m['content'] for m in kwargs['messages'] if m['role'] == 'user'] == ['recover this question']
        entered.set()
        await release.wait()
        return {'content': 'recovered live answer'}

    async with running_app(tmp_path, recovered_model) as restarted:
        try:
            await asyncio.wait_for(entered.wait(), 20)
            async with websockets.connect(restarted.ws_url) as socket:
                replay = await resume(socket, guest, session)
                assert replay[-1]['type'] == 'ready'
                assert [f['text'] for f in replay if f['type'] == 'message'] == ['recover this question']
                release.set()
                # No resubmission or reconnect: delivery must come through the bus.
                frames = await receive_until(socket, lambda frames: any(
                    f.get('type') == 'message' and f.get('role') == 'bot' for f in frames))
                bot = next(f for f in frames if f.get('role') == 'bot')
                assert bot['text'] == 'recovered live answer'
                canonical = await restarted.store.event_by_id(session, bot['event_id'])
                assert bot['sequence'] == canonical['sequence']
                assert bot['sequence'] > accepted['sequence']
                assert bot['text'] == canonical['payload']['text']
                assert bot['session_id'] == session
                await send(socket, 'recover-live', 'recover this question')
                receipt_frames = await receive_until(socket, lambda frames: any(
                    f.get('type') == 'receipt' and f.get('status') == 'completed' for f in frames))
                assert next(f for f in receipt_frames if f.get('type') == 'receipt')['duplicate'] is True
                restarted.model.generate_chat.assert_awaited_once()
                persisted = await history(restarted, guest, session)
                assert [m['text'] for m in persisted['messages']] == ['recover this question', 'recovered live answer']
                assert persisted['messages'][-1] == bot
        finally:
            release.set()

    async with running_app(tmp_path, must_not_run) as again:
        async with websockets.connect(again.ws_url) as socket:
            replay = await resume(socket, guest, session)
            assert [f for f in replay if f['type'] == 'message'] == persisted['messages']
            await send(socket, 'recover-live', 'recover this question')
            receipts = await receive_until(socket, lambda frames: any(f.get('type') == 'receipt' for f in frames))
            assert receipts[-1]['status'] == 'completed' and receipts[-1]['duplicate']
            again.model.generate_chat.assert_not_awaited()


@pytest.mark.asyncio
async def test_live_publication_fills_durable_gaps_before_advancing_cursor(tmp_path, monkeypatch):
    from cota.inputs import input_event_id
    delayed, release = asyncio.Event(), asyncio.Event()
    delayed_once = False

    async def respond(**kwargs):
        question, _ = latest_turn(kwargs['messages'])
        return {'content': 'answer:' + question}

    async with running_app(tmp_path, respond) as server:
        guest, session = await guest_conversation(server)
        original_lookup = server.store.event_by_id
        async def delayed_lookup(sid, event_id):
            nonlocal delayed_once
            event = await original_lookup(sid, event_id)
            if event and event['type'] == 'bot_utter' and not delayed_once:
                delayed_once = True
                delayed.set()
                await release.wait()
            return event
        monkeypatch.setattr(server.store, 'event_by_id', delayed_lookup)
        try:
            async with websockets.connect(server.ws_url) as socket:
                await resume(socket, guest, session)
                await send(socket, 'first-gap', 'first')
                await asyncio.wait_for(delayed.wait(), 20)
                await send(socket, 'second-gap', 'second')
                frames = await receive_until(socket, lambda frames: any(
                    f.get('type') == 'message' and f.get('message_id') == 'second-gap' for f in frames))
                visible = [f for f in frames if f.get('type') == 'message']
                assert [f['text'] for f in visible] == ['first', 'answer:first', 'second']
                cursor = visible[-1]['sequence']
                assert cursor == (await original_lookup(session, input_event_id('second-gap')))['sequence']
            async with websockets.connect(server.ws_url) as resumed:
                replay = await resume(resumed, guest, session, after=cursor)
                release.set()
                tail = await receive_until(resumed, lambda frames: any(f.get('text') == 'answer:second' for f in frames))
                all_messages = visible + [f for f in replay + tail if f.get('type') == 'message']
                assert [f['text'] for f in all_messages] == ['first', 'answer:first', 'second', 'answer:second']
                for frame in all_messages:
                    assert frame['sequence'] == (await original_lookup(session, frame['event_id']))['sequence']
                assert server.model.generate_chat.await_count == 2
        finally:
            release.set()
