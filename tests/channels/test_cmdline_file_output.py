"""Received terminal attachments are readable without involving the model."""
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from cota.channels.cmdline import CmdlineChannel
from cota.channels.events import OutboundMessage
from cota.channels.queue import MessageBus
from cota.files import FileStorage


@pytest.fixture
def channel(tmp_path, monkeypatch):
    result = CmdlineChannel({}, MessageBus())
    result.files = FileStorage(tmp_path / 'files')
    output = []
    monkeypatch.setattr(result, '_write_line', output.append)
    return result, output


async def deliver(channel, name, body):
    item = channel.files.put(channel.session_key, 'u', name, body)
    await channel.send(OutboundMessage('cmdline', channel._session_id, '',
                                      session_id=channel.session_key, attachments=[item]))
    return item


@pytest.mark.asyncio
async def test_markdown_receives_preview_and_numbered_open_command(channel):
    terminal, output = channel
    await deliver(terminal, '故事与分镜.md', '# 故事\n小抗体出发了。\n'.encode())
    text = '\n'.join(output)
    assert '小抗体出发了。' in text
    assert '/open 1' in text and '/files' in text
    assert '故事与分镜.md' in text and 'File [1]' in text
    assert 'Bot: ' not in text  # Attachment-only replies need no empty text bubble.


@pytest.mark.asyncio
async def test_binary_and_large_text_previews_are_bounded_and_escape_safe(channel):
    terminal, output = channel
    await deliver(terminal, 'book.pdf', b'%PDF-1.4\nBINARY_NOT_A_PREVIEW')
    assert 'BINARY_NOT_A_PREVIEW' not in '\n'.join(output)
    output.clear()
    await deliver(terminal, 'note.txt', ('safe\x1b[2J\r\n' + 'x' * 100000).encode())
    text = '\n'.join(output)
    assert len(text) < 3000 and '\x1b' not in text and '\r' not in text
    assert '省略' in text


@pytest.mark.asyncio
async def test_file_commands_do_not_become_user_messages(channel, monkeypatch):
    terminal, output = channel
    item = await deliver(terminal, '故事.md', '内容'.encode())
    opened = []
    monkeypatch.setattr(terminal, '_open_file', AsyncMock(side_effect=opened.append))
    values = iter(['/files', '/open 1', '/open 99', '/open 1; echo injection', '/stop'])
    async def read():
        return next(values)
    monkeypatch.setattr(terminal, '_read_input', read)
    await terminal.start()
    await asyncio.wait_for(terminal.wait_closed(), 2)
    await terminal.stop()
    assert terminal.bus.inbound_size == 0
    assert len(opened) == 1
    assert Path(opened[0]).name == '故事.md'
    assert Path(opened[0]).read_text() == '内容'
    assert terminal.files.resolve(terminal.session_key, item['id']).read_text() == '内容'
    assert any(line.startswith('附件错误：') for line in output)


@pytest.mark.asyncio
async def test_missing_attachment_reports_failure_and_other_files_still_display(channel):
    terminal, output = channel
    bad = terminal.files.put(terminal.session_key, 'u', 'missing.txt', b'missing')
    good = terminal.files.put(terminal.session_key, 'u', 'good.txt', b'visible content')
    terminal.files.resolve(terminal.session_key, bad['id']).unlink()
    await terminal.send(OutboundMessage('cmdline', terminal._session_id, 'files', session_id=terminal.session_key,
                                       attachments=[bad, good]))
    assert any('missing.txt' in line and '不可用' in line for line in output)
    assert 'visible content' in '\n'.join(output)


@pytest.mark.asyncio
@pytest.mark.parametrize('debug', [False, True])
async def test_actual_pi_send_files_reaches_terminal_through_processor_bus(tmp_path, monkeypatch, mock_agent, capsys, debug):
    from cota.channels.events import InboundMessage
    from cota.executor.environment import ExecutionEnvironment
    from cota.executor.tools import ToolPolicy
    from cota.processor import Processor
    from cota.store import SQLStore
    from tests.test_pi_runtime import call
    terminal = CmdlineChannel({}, MessageBus(), debug=debug)
    terminal.files = FileStorage(tmp_path / 'files')
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    (workspace / '分镜.md').write_text('# 草案\n小抗体夹住病毒。', encoding='utf-8')
    mock_agent.files = terminal.files
    mock_agent.deploy = 'personal'
    mock_agent.environment = ExecutionEnvironment('machine', str(workspace))
    mock_agent.get_tool_registry().set_policy(ToolPolicy(allow=['send_files']))
    mock_agent._llm_mock.generate_chat.side_effect = [
        {'tool_calls': [call('send_files', {'paths': ['分镜.md']}, 'send')]},
        {'content': '请确认草案。'},
    ]
    store = SQLStore(db=str(tmp_path / 'events.db'))
    try:
        processor = Processor(mock_agent, store, message_bus=terminal.bus)
        await processor.handle_inbound_message(InboundMessage('cmdline', 'u', terminal._session_id, '发给我'))
        while terminal.bus.outbound_size:
            await terminal.send(await terminal.bus.consume_outbound(timeout=.1))
        text = capsys.readouterr().err
        assert '小抗体夹住病毒。' in text and 'File [1]' in text and '/open 1' in text
        restored = await store.load(terminal.session_key)
        assert len([e for e in restored.events if e.type == 'bot_utter' and e.payload.get('attachments')]) == 1
    finally:
        store.engine.dispose()


@pytest.mark.asyncio
async def test_attachment_index_is_bounded_and_repeated_ids_keep_number(channel):
    terminal, _ = channel
    first = await deliver(terminal, 'first.txt', b'first')
    await terminal.send(OutboundMessage('cmdline', terminal._session_id, '', session_id=terminal.session_key, attachments=[first]))
    assert list(terminal._received_files.entries) == [1]
    for number in range(65):
        await deliver(terminal, f'{number}.txt', b'hello')
    assert len(terminal._received_files.entries) == 64
    with pytest.raises(ValueError, match='编号'):
        await terminal._received_files.open_path('1', terminal.files)


@pytest.mark.asyncio
@pytest.mark.parametrize('platform,command', [('darwin', 'open'), ('linux', 'xdg-open')])
async def test_open_is_explicit_and_does_not_interpret_shell_metacharacters(channel, monkeypatch, platform, command):
    import sys
    terminal, _ = channel
    process = type('Process', (), {'wait': AsyncMock(return_value=0), 'returncode': 0})()
    launcher = AsyncMock(return_value=process)
    monkeypatch.setattr(asyncio, 'create_subprocess_exec', launcher)
    monkeypatch.setattr(sys, 'platform', platform)
    item = await deliver(terminal, '$(touch unexpected).pdf', b'%PDF-1.4\nbook')
    launcher.assert_not_awaited()  # Receiving a file never launches an application.
    path = await terminal._received_files.open_path('1', terminal.files)
    await terminal._open_file(path)
    assert launcher.call_args.args == (command, str(path))
    assert path.name == '$(touch unexpected).pdf'
    assert terminal.files.resolve(terminal.session_key, item['id']).read_bytes().startswith(b'%PDF')


@pytest.mark.asyncio
async def test_open_does_not_launch_executable_attachments(channel, monkeypatch):
    terminal, _ = channel
    await deliver(terminal, 'run.sh', b'echo never-run')
    with pytest.raises(ValueError, match='类型'):
        await terminal._received_files.open_path('1', terminal.files)
