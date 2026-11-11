"""Durable references, scoped bytes and conversation attachment contracts."""
import pytest


def files_class():
    import importlib.util
    assert importlib.util.find_spec('cota.files') is not None, 'Unified file storage is missing'
    from cota.files import FileStorage
    return FileStorage


def test_files_are_immutable_scoped_and_names_are_safe(tmp_path):
    files = files_class()(tmp_path / 'files')
    value = files.put('alice-room', 'alice', '../../drawing.pdf', b'%PDF-1.4\nbook')
    assert set(value) == {'id', 'name', 'mime_type', 'size'}
    assert value['name'] == 'drawing.pdf' and value['mime_type'] == 'application/pdf'
    assert files.references('alice-room', [value['id']]) == [value]
    assert files.resolve('alice-room', value['id']).read_bytes().endswith(b'book')
    with pytest.raises(FileNotFoundError):
        files.resolve('bob-room', value['id'])
    with pytest.raises(ValueError):
        files.put('alice-room', 'alice', 'empty.txt', b'')
    with pytest.raises(ValueError):
        files.references('alice-room', [value['id']] * 9)


def test_export_copies_workspace_files_and_rejects_escape(tmp_path):
    files = files_class()(tmp_path / 'files')
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    source = workspace / 'book.pdf'
    source.write_bytes(b'%PDF-1.4\nfirst')
    item = files.import_paths('s', 'u', workspace, ['book.pdf'])[0]
    source.write_bytes(b'%PDF-1.4\nsecond')
    assert files.resolve('s', item['id']).read_bytes().endswith(b'first')
    (workspace / 'link.pdf').symlink_to(tmp_path / 'secret')
    for value in ('../secret', str(tmp_path / 'secret'), 'link.pdf'):
        with pytest.raises(ValueError):
            files.import_paths('s', 'u', workspace, [value])


def test_utterances_and_input_identity_include_attachments(tmp_path):
    from cota.events import UserUtterEvent, BotUtterEvent
    from cota.conversation import message_record
    from cota.channels.events import InboundMessage
    from cota.inputs import canonical_input, event_input
    from cota.dst import DST
    value = files_class()(tmp_path).put('s', 'u', 'note.txt', b'hello')
    event = UserUtterEvent('', attachments=[value], metadata={'sender_id': 'u'})
    dst = DST('s', agent=None)
    dst.append_event(event)
    assert message_record('s', event.as_dict())['attachments'] == [value]
    inbound = InboundMessage(channel='web', sender_id='u', chat_id='s', content='', attachments=[value])
    assert canonical_input(inbound)['attachments'] == event_input(event.as_dict())['attachments']
    assert value['id'] in str(dst.context_messages)
    bot = BotUtterEvent('PDF', attachments=[value])
    assert bot.payload['attachments'] == [value]
    with pytest.raises(ValueError):
        UserUtterEvent('', attachments=[dict(value, path='/etc/passwd')])


@pytest.mark.asyncio
async def test_web_upload_attachment_only_send_replay_and_private_download(tmp_path):
    import json
    import websockets
    from tests.test_web_app_integration import running_app, guest_conversation, auth, resume, receive_until
    async def respond(**kwargs):
        return {'content': '已收到文件。'}
    async with running_app(tmp_path, respond) as server:
        alice, sid = await guest_conversation(server)
        bob, other = await guest_conversation(server)
        base = f'/api/conversations/{sid}/files'
        headers = {**auth(alice), 'Content-Type': 'application/octet-stream', 'X-File-Name': 'note.txt'}
        async with server.http.post(server.url + base, headers=headers, data=b'hello attachment') as reply:
            assert reply.status == 201
            file = await reply.json()
        url = server.url + base + '/' + file['id']
        async with server.http.get(url, headers=auth(bob)) as reply:
            assert reply.status == 403
        async with server.http.get(url, headers=auth(alice)) as reply:
            assert reply.status == 200 and await reply.read() == b'hello attachment'
        async with server.http.get(url) as reply:
            assert reply.status == 403
        async with websockets.connect(server.ws_url) as socket:
            await resume(socket, alice, sid)
            await socket.send(json.dumps({'type': 'send', 'message_id': 'file-only', 'text': '', 'attachments': [file['id']]}))
            frames = await receive_until(socket, lambda fs: any(f.get('status') == 'completed' for f in fs))
            assert next(f for f in frames if f.get('role') == 'user')['attachments'] == [file]
        async with websockets.connect(server.ws_url) as socket:
            frames = await resume(socket, alice, sid)
            assert next(f for f in frames if f.get('role') == 'user')['attachments'] == [file]
        async with server.http.post(server.url + f'/api/conversations/{other}/messages', headers=auth(bob),
                                    json={'text': '', 'attachments': [file['id']]}) as reply:
            assert reply.status == 404
        history = await server.store.history(sid)
        assert history[0]['payload']['attachments'] == [file]
        assert file['id'] in str(server.model.generate_chat.call_args.kwargs['messages'])


@pytest.mark.asyncio
async def test_pi_send_files_commits_utterance_and_does_not_export_outside_workspace(mock_agent, tmp_path):
    from cota.executor.environment import ExecutionEnvironment
    from cota.executor.tools import ToolPolicy
    from cota.events import UserUtterEvent
    from cota.dst import DST
    from cota.store import MemoryStore
    from cota.runtime.pi_runtime import PiAgentRuntime
    from tests.test_pi_runtime import call
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    (workspace / 'book.pdf').write_bytes(b'%PDF-1.4\nbook')
    mock_agent.files = files_class()(tmp_path / 'files')
    mock_agent.deploy = 'personal'
    mock_agent.environment = ExecutionEnvironment('machine', str(workspace))
    mock_agent.get_tool_registry().set_policy(ToolPolicy(allow=['send_files']))
    mock_agent._llm_mock.generate_chat.side_effect = [
        {'tool_calls': [call('send_files', {'paths': ['book.pdf'], 'text': '绘本'}, 'send')]},
        {'content': ''},
        {'tool_calls': [call('send_files', {'paths': ['../private.key']}, 'escape')]},
        {'content': '该文件不在工作区内。'},
    ]
    store = MemoryStore()
    dst = DST('s', mock_agent)
    dst.append_event(UserUtterEvent('发送文件'))
    await PiAgentRuntime(mock_agent, dst, 's', checkpoint=store.save).run()
    reply = next(e for e in dst.events if e.type == 'bot_utter')
    assert reply.payload['attachments'][0]['name'] == 'book.pdf'
    assert reply.payload['tool_event_id']
    restored = await store.load('s', agent=mock_agent)
    assert restored.state_dict() == dst.state_dict()
    dst.append_event(UserUtterEvent('发另一个'))
    await PiAgentRuntime(mock_agent, dst, 's', checkpoint=store.save).run()
    result = [e for e in dst.events if e.type == 'tool_result'][-1]
    assert result.payload['status'] == 'error'


def test_text_only_sdk_does_not_require_a_config_directory():
    from cota.agent import Agent
    from cota.application import Application
    from cota.store import MemoryStore
    application = Application(Agent(store=MemoryStore()), channels={'web': {'enabled': True}})
    assert application.prepare_channels().get_channel('web') is not None


@pytest.mark.asyncio
async def test_large_image_limit_is_explicit_to_the_model(mock_agent, tmp_path):
    from cota.dst import DST
    from cota.events import UserUtterEvent
    from cota.runtime.pi_runtime import PiAgentRuntime
    mock_agent.files = files_class()(tmp_path)
    item = mock_agent.files.put('s', 'u', 'large.png', b'\x89PNG\r\n\x1a\n' + b'x' * (2 * 1024 * 1024))
    dst = DST('s', mock_agent)
    dst.append_event(UserUtterEvent('看图', attachments=[item]))
    messages = await PiAgentRuntime(mock_agent, dst, 's')._initial_context()
    assert 'image' in str(messages).lower() and 'limit' in str(messages).lower()


def test_size_integrity_and_symlink_checks(tmp_path, monkeypatch):
    import cota.files as module
    files = files_class()(tmp_path / 'files')
    monkeypatch.setattr(module, 'MAX_FILE_BYTES', 8)
    with pytest.raises(ValueError):
        files.put('s', 'u', 'big.txt', b'x' * 9)
    item = files.put('s', 'u', 'ok.txt', b'original')
    path = files.resolve('s', item['id'])
    path.write_bytes(b'modified')
    with pytest.raises(FileNotFoundError):
        files.resolve('s', item['id'])
    path.unlink()
    path.symlink_to(tmp_path / 'private')
    with pytest.raises(FileNotFoundError):
        files.resolve('s', item['id'])


@pytest.mark.asyncio
async def test_images_reach_provider_but_not_event_binary_payload(mock_agent, tmp_path):
    import base64
    import json
    from cota.dst import DST
    from cota.events import UserUtterEvent
    from cota.runtime.pi_runtime import PiAgentRuntime
    # Actual 1×1 PNG fixture; no image dependency needed for the core test.
    data = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aH1sAAAAASUVORK5CYII=')
    mock_agent.files = files_class()(tmp_path)
    mock_agent._llm_mock.supports_images = True
    item = mock_agent.files.put('s', 'u', 'one.png', data)
    dst = DST('s', mock_agent)
    dst.append_event(UserUtterEvent('图片有什么', attachments=[item]))
    await PiAgentRuntime(mock_agent, dst, 's').run()
    request = mock_agent._llm_mock.generate_chat.call_args.kwargs
    assert any(c.get('type') == 'image_url' for m in request['messages'] if isinstance(m.get('content'), list) for c in m['content'])
    assert base64.b64encode(data).decode() not in json.dumps(dst.as_dict())


@pytest.mark.asyncio
async def test_group_attachments_follow_membership_and_input_deduplication(tmp_path):
    from tests.test_web_app_integration import running_app, auth
    from tests.test_chat_app import api
    from cota.webapp import create_app
    async def respond(**kwargs):
        return {'content': '收到。'}
    async with running_app(tmp_path, respond, app_factory=create_app, mode='group') as server:
        alice = await api(server, 'POST', 'guests', data={'name':'Alice'}, status=201)
        bob = await api(server, 'POST', 'guests', data={'name':'Bob'}, status=201)
        sid = (await api(server, 'POST', 'conversations', alice, {'title':'files'}, 201))['session_id']
        invite = await api(server, 'POST', f'conversations/{sid}/invite', alice, {})
        await api(server, 'POST', 'join', bob, {'invite':invite['invite']})
        url = server.url + f'/api/conversations/{sid}/files'
        async with server.http.post(url, headers={**auth(alice), 'Content-Type':'application/octet-stream', 'X-File-Name':'note.txt'}, data=b'note') as reply:
            file = await reply.json()
        body = {'message_id':'same', 'text':'', 'attachments':[file['id']]}
        for _ in range(2):
            async with server.http.post(server.url + f'/api/conversations/{sid}/messages', headers=auth(alice), json=body) as reply:
                assert reply.status == 202
        async with server.http.post(server.url + f'/api/conversations/{sid}/messages', headers=auth(alice), json={**body, 'attachments':[], 'text':'changed'}) as reply:
            assert reply.status == 409
        assert server.model.generate_chat.await_count == 0
        assert len(await server.store.history(sid)) == 1
        async with server.http.get(url + '/' + file['id'], headers=auth(bob)) as reply:
            assert reply.status == 200
        await api(server, 'POST', f'conversations/{sid}/remove', alice, {'user_id':bob['user_id']})
        async with server.http.get(url + '/' + file['id'], headers=auth(bob)) as reply:
            assert reply.status == 403


@pytest.mark.asyncio
async def test_attachment_delivery_retry_keeps_reference_and_unsupported_fails_once(tmp_path):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from cota.dst import DST
    from cota.events import BotUtterEvent
    from cota.store import MemoryStore
    from cota.channels.delivery import DeliveryDispatcher
    from tests.test_delivery_dispatcher import until
    file = files_class()(tmp_path).put('s', 'u', 'book.pdf', b'%PDF-1.4\nbook')
    for supported in (True, False):
        store = MemoryStore()
        dst = DST('s', agent=None)
        event = BotUtterEvent('PDF', attachments=[file])
        dst.append_event(event)
        await store.save(dst, delivery_target={'channel':'test','scope':'app','chat_id':'chat'})
        send = AsyncMock(side_effect=[ConnectionError('offline'), None])
        channel = SimpleNamespace(durable_delivery=True, delivery_scope='app', supports_attachments=supported, send=send)
        dispatcher = DeliveryDispatcher(store, {'test':channel}, poll_interval=.005, retry_delay=.01)
        await dispatcher.start()
        try:
            async def done():
                return (await store.delivery('s', event.event_id))['status'] in ('delivered','failed')
            await until(done)
            row = await store.delivery('s', event.event_id)
            if supported:
                assert send.await_count == 2
                assert all(c.args[0].attachments == [file] and c.args[0].event_id == event.event_id for c in send.await_args_list)
            else:
                assert send.await_count == 0 and row['attempts'] == 1 and row['error_type'] == 'UnsupportedAttachments'
        finally:
            await dispatcher.stop()


def test_annotation_export_preserves_attachment_only_turns(tmp_path):
    from cota.annotation_files import export_worksheet
    from cota.dst import DST
    from cota.events import UserUtterEvent, BotUtterEvent
    item = files_class()(tmp_path).put('s', 'u', 'reference.png', b'image')
    dst = DST('s', agent=None)
    dst.append_event(UserUtterEvent('', attachments=[item]))
    dst.append_event(BotUtterEvent('', attachments=[item]))
    steps = export_worksheet(dst)['policies'][0]['steps']
    assert len(steps) == 2 and 'reference.png' in steps[0]['user']


def test_send_files_is_hidden_when_target_channel_cannot_deliver(mock_agent, tmp_path):
    from cota.executor.environment import ExecutionEnvironment
    from cota.dst import DST
    from cota.events import UserUtterEvent
    from cota.runtime.pi_runtime import PiAgentRuntime
    mock_agent.files = files_class()(tmp_path / 'files')
    mock_agent.deploy = 'personal'
    mock_agent.environment = ExecutionEnvironment('machine', str(tmp_path))
    mock_agent._attachment_channels = {'feishu':False}
    dst = DST('s', mock_agent)
    dst.append_event(UserUtterEvent('发文件', metadata={'channel':'feishu'}))
    assert not PiAgentRuntime(mock_agent, dst, 's')._files_allowed()


@pytest.mark.asyncio
async def test_http_upload_limits_and_encoded_filename(tmp_path):
    from urllib.parse import quote
    from tests.test_web_app_integration import running_app, guest_conversation, auth
    async def respond(**kwargs):
        return {'content':'ok'}
    async with running_app(tmp_path, respond) as server:
        guest, sid = await guest_conversation(server)
        url = server.url + f'/api/conversations/{sid}/files'
        headers = {**auth(guest), 'Content-Type':'application/octet-stream', 'X-File-Name':quote('绘本.pdf')}
        async with server.http.post(url, headers=headers, data=b'%PDF-1.4\n') as response:
            assert response.status == 201
            assert (await response.json())['name'] == '绘本.pdf'
        async with server.http.post(url, headers=headers, data=b'') as response:
            assert response.status == 400
        async with server.http.post(url, headers=headers, data=b'x' * (20 * 1024 * 1024 + 1)) as response:
            assert response.status == 413
        async with server.http.post(url, headers={**headers,'Content-Type':'text/plain'}, data=b'text') as response:
            assert response.status == 415
        async with server.http.post(server.url + f'/api/conversations/{sid}/messages', headers=auth(guest),
                                    json={'text':'x' * (256 * 1024)}) as response:
            assert response.status == 413


@pytest.mark.asyncio
async def test_text_model_can_delegate_images_without_receiving_image_blocks(mock_agent, tmp_path):
    from cota.dst import DST
    from cota.events import UserUtterEvent
    from cota.runtime.pi_runtime import PiAgentRuntime
    mock_agent.files = files_class()(tmp_path)
    mock_agent._llm_mock.supports_images = False
    file = mock_agent.files.put('s', 'u', 'small.png', b'\x89PNG\r\n\x1a\nimage')
    dst = DST('s', mock_agent)
    dst.append_event(UserUtterEvent('请看图', attachments=[file]))
    messages = await PiAgentRuntime(mock_agent, dst, 's')._initial_context()
    content = messages[0]['content']
    assert isinstance(content, list)
    assert not any(block['type'] == 'image' for block in content)
    assert 'not configured for image input' in str(content)


def test_named_local_copy_preserves_extension_scope_and_source(tmp_path):
    files = files_class()(tmp_path / 'files')
    item = files.put('s', 'u', '故事与分镜.md', '原始内容'.encode())
    path = files.named_copy('s', item['id'])
    assert path.name == '故事与分镜.md' and path.read_text() == '原始内容'
    assert files.named_copy('s', item['id']) == path
    with pytest.raises(FileNotFoundError):
        files.named_copy('other', item['id'])
    path.write_text('user edited copy')
    assert files.resolve('s', item['id']).read_text() == '原始内容'
    with pytest.raises(FileNotFoundError):
        files.named_copy('s', item['id'])  # Do not silently overwrite local edits.


def test_named_local_copy_rejects_symlink_directory(tmp_path):
    files = files_class()(tmp_path / 'files')
    item = files.put('s', 'u', 'data', b'original')
    outside = tmp_path / 'outside'
    outside.mkdir()
    (files.root / item['id'] / 'view').symlink_to(outside, target_is_directory=True)
    with pytest.raises(FileNotFoundError):
        files.named_copy('s', item['id'])
    assert not list(outside.iterdir())
