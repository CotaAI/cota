"""Terminal file selection uses the normal scoped conversation attachment path."""
import asyncio
import base64
import json
import shlex

import pytest

from cota.channels.cmdline import CmdlineChannel
from cota.channels.context import ChannelContext
from cota.channels.queue import MessageBus
from cota.files import FileStorage


async def feed(channel, lines, monkeypatch):
    values = iter(lines)

    async def read():
        try:
            value = next(values)
        except StopIteration:
            raise EOFError from None
        return value() if callable(value) else value

    monkeypatch.setattr(channel, '_read_input', read)
    await channel.start()
    await asyncio.wait_for(channel.wait_closed(), 3)
    await channel.stop()


@pytest.fixture
def terminal(tmp_path, monkeypatch):
    channel = CmdlineChannel({}, MessageBus())
    channel.files = FileStorage(tmp_path / 'files')
    output = []
    monkeypatch.setattr(channel, '_write_line', output.append)
    return channel, output


@pytest.mark.asyncio
async def test_staging_copies_multiple_files_without_sending_until_text(terminal, tmp_path, monkeypatch):
    channel, output = terminal
    image = tmp_path / '参考 图.png'
    image.write_bytes(b'\x89PNG\r\n\x1a\noriginal')
    note = tmp_path / '说明.txt'
    note.write_text('hello', encoding='utf-8')

    def inspect_staging():
        assert channel.bus.inbound_size == 0
        image.write_bytes(b'changed')
        return '请参考这张图'

    await feed(channel, [f'/file {shlex.quote(str(image))}', f'/file {note}', inspect_staging, '下一条'], monkeypatch)
    first = await channel.bus.consume_inbound(timeout=.1)
    second = await channel.bus.consume_inbound(timeout=.1)
    assert first.content == '请参考这张图'
    assert [f['name'] for f in first.attachments] == ['参考 图.png', '说明.txt']
    assert first.attachments[0]['mime_type'] == 'image/png'
    assert channel.files.resolve(first.session_key, first.attachments[0]['id']).read_bytes().endswith(b'original')
    with pytest.raises(FileNotFoundError):
        channel.files.resolve('another-session', first.attachments[0]['id'])
    assert second.content == '下一条' and second.attachments == []
    assert first.session_key == second.session_key == channel.session_key
    assert first.message_id != second.message_id
    assert any('参考 图.png' in line for line in output)


@pytest.mark.asyncio
async def test_clear_and_attachment_only_send(terminal, tmp_path, monkeypatch):
    channel, output = terminal
    path = tmp_path / 'book.pdf'
    path.write_bytes(b'%PDF-1.4\nbook')
    await feed(channel, [f'/file {path}', '/clear', '', '普通消息', f'/file {path}', '', '', '/stop'], monkeypatch)
    assert channel.bus.inbound_size == 2
    first = await channel.bus.consume_inbound(timeout=.1)
    second = await channel.bus.consume_inbound(timeout=.1)
    assert first.content == '普通消息' and first.attachments == []
    assert second.content == '' and second.attachments[0]['name'] == 'book.pdf'
    assert any('清空' in line for line in output)


@pytest.mark.asyncio
async def test_paths_use_startup_directory_and_expand_home(tmp_path, monkeypatch):
    start = tmp_path / 'start'
    start.mkdir()
    home = tmp_path / 'home'
    home.mkdir()
    (start / 'a b.txt').write_text('relative')
    (home / 'home.txt').write_text('home')
    monkeypatch.chdir(start)
    channel = CmdlineChannel({}, MessageBus())
    channel.files = FileStorage(tmp_path / 'files')
    monkeypatch.setenv('HOME', str(home))
    monkeypatch.chdir(tmp_path)
    await feed(channel, [r'/file a\ b.txt', '/file ~/home.txt', ''], monkeypatch)
    message = await channel.bus.consume_inbound(timeout=.1)
    assert [f['name'] for f in message.attachments] == ['a b.txt', 'home.txt']


@pytest.mark.asyncio
@pytest.mark.parametrize('invalid', ['missing', 'directory', 'empty', 'oversize', 'symlink', 'fifo', 'syntax', 'no-path', 'two-paths'])
async def test_invalid_file_preserves_existing_attachment_and_loop(terminal, tmp_path, monkeypatch, invalid):
    channel, output = terminal
    valid = tmp_path / 'good.txt'
    valid.write_bytes(b'ok')
    bad = tmp_path / 'bad.txt'
    command = f'/file {bad}'
    if invalid == 'directory':
        bad.mkdir()
    elif invalid == 'empty':
        bad.touch()
    elif invalid == 'oversize':
        with bad.open('wb') as stream:
            stream.truncate(20 * 1024 * 1024 + 1)
    elif invalid == 'symlink':
        bad.symlink_to(valid)
    elif invalid == 'fifo':
        import os
        os.mkfifo(bad)
    elif invalid == 'syntax':
        command = '/file "unfinished'
    elif invalid == 'no-path':
        command = '/file'
    elif invalid == 'two-paths':
        command = f'/file {valid} {valid}'
    await feed(channel, [f'/file {valid}', command, '继续'], monkeypatch)
    assert channel.bus.inbound_size == 1
    message = await channel.bus.consume_inbound(timeout=.1)
    assert message.content == '继续' and len(message.attachments) == 1
    assert message.attachments[0]['name'] == 'good.txt'
    assert any(line.startswith('附件错误：') for line in output)


@pytest.mark.asyncio
async def test_limit_clear_and_stop_do_not_send_commands(terminal, tmp_path, monkeypatch):
    channel, output = terminal
    path = tmp_path / 'one.txt'
    path.write_bytes(b'one')
    await feed(channel, [f'/file {path}'] * 9 + ['', '/clear', f'/file {path}', '/stop'], monkeypatch)
    assert channel.bus.inbound_size == 1
    assert len((await channel.bus.consume_inbound(timeout=.1)).attachments) == 8
    assert any(line.startswith('附件错误：') and '8' in line for line in output)
    assert len(list(channel.files.root.glob('f_*'))) == 9


@pytest.mark.asyncio
async def test_no_storage_reports_error_but_text_remains_usable(tmp_path, monkeypatch):
    channel = CmdlineChannel({}, MessageBus())
    output = []
    monkeypatch.setattr(channel, '_write_line', output.append)
    path = tmp_path / 'one.txt'
    path.write_bytes(b'one')
    await feed(channel, [f'/file {path}', '/file-name is ordinary text'], monkeypatch)
    message = await channel.bus.consume_inbound(timeout=.1)
    assert message.content == '/file-name is ordinary text' and message.attachments == []
    assert any(line.startswith('附件错误：') for line in output)


@pytest.mark.asyncio
async def test_bound_channel_uses_same_scope_for_import_and_admission(terminal, tmp_path, monkeypatch):
    channel, _ = terminal
    received = []

    async def admit(message):
        received.append(message)

    channel.bind(ChannelContext('terminal', 'direct', admit))
    path = tmp_path / 'one.txt'
    path.write_bytes(b'one')
    await feed(channel, [f'/file {path}', ''], monkeypatch)
    assert len(received) == 1 and channel.bus.inbound_size == 0
    message = received[0]
    assert message.session_key == channel.session_key
    assert channel.files.resolve(message.session_key, message.attachments[0]['id']).read_bytes() == b'one'


@pytest.mark.asyncio
async def test_path_metacharacters_are_literal_not_shell_commands(terminal, tmp_path, monkeypatch):
    channel, _ = terminal
    monkeypatch.chdir(tmp_path)
    path = tmp_path / '$(touch unexpected) $HOME `whoami`.txt'
    path.write_bytes(b'literal')
    await feed(channel, [f'/file {shlex.quote(str(path))}', ''], monkeypatch)
    message = await channel.bus.consume_inbound(timeout=.1)
    assert message.attachments[0]['name'] == path.name
    assert channel.files.resolve(message.session_key, message.attachments[0]['id']).read_bytes() == b'literal'
    assert not (tmp_path / 'unexpected').exists()


@pytest.mark.asyncio
async def test_rejected_admission_keeps_pending_files(terminal, tmp_path, monkeypatch):
    channel, _ = terminal
    attempts = []

    async def admit(message):
        attempts.append(message)
        if len(attempts) == 1:
            raise ValueError('busy')

    channel.bind(ChannelContext('terminal', 'direct', admit))
    path = tmp_path / 'one.txt'
    path.write_bytes(b'one')
    await feed(channel, [f'/file {path}', 'first', 'retry', 'after'], monkeypatch)
    assert len(attempts) == 3
    assert len(attempts[0].attachments) == 1
    assert attempts[1].attachments == attempts[0].attachments
    assert attempts[2].attachments == []
    assert len(list(channel.files.root.glob('f_*'))) == 1


@pytest.mark.asyncio
async def test_terminal_image_reaches_pi_and_sqlite_as_scoped_reference(terminal, tmp_path, monkeypatch, mock_agent):
    from cota.processor import Processor
    from cota.store import SQLStore

    channel, _ = terminal
    data = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aH1sAAAAASUVORK5CYII=')
    image = tmp_path / 'one.png'
    image.write_bytes(data)
    await feed(channel, [f'/file {image}', '看图'], monkeypatch)
    message = await channel.bus.consume_inbound(timeout=.1)
    mock_agent.files = channel.files
    mock_agent._llm_mock.supports_images = True
    store = SQLStore(db=str(tmp_path / 'events.sqlite'))
    processor = Processor(mock_agent, store, message_bus=channel.bus)
    try:
        await processor.handle_inbound_message(message)
        restored = await store.load(channel.session_key, agent=mock_agent)
        assert restored.state_dict() == processor.dst.state_dict()
        event = next(e for e in restored.events if e.type == 'user_utter')
        assert event.payload['attachments'] == message.attachments
        assert base64.b64encode(data).decode() not in json.dumps(restored.as_dict())
        request = mock_agent._llm_mock.generate_chat.call_args.kwargs
        assert any(c.get('type') == 'image_url' for m in request['messages']
                   if isinstance(m.get('content'), list) for c in m['content'])
        reply = await channel.bus.consume_outbound(timeout=.1)
        assert reply.content == 'hello' and reply.session_id == channel.session_key
    finally:
        store.engine.dispose()
