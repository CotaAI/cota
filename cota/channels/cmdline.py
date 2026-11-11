"""Cmdline Channel - 命令行交互

适配 BaseChannel 框架的命令行 Channel。
"""

import asyncio
from collections import OrderedDict
import hashlib
import os
from pathlib import Path
import shlex
import sys
import threading
import uuid
from typing import Any, Callable, Dict, Optional

from loguru import logger

from cota.files import MAX_ATTACHMENTS

from .base import BaseChannel
from .events import InboundMessage, OutboundMessage
from .queue import MessageBus

_BUILTIN_INPUT = input


class CmdlineChannel(BaseChannel):
    """命令行 Channel

    - **非 debug 模式**: ``send()`` 直接打印，``_input_loop`` 始终显示
      ``Input message:`` 提示。
    - **debug 模式**: 完整执行记录写入文件；回复仍立即打印，不能依赖
      Processor 完成回调与出站队列的先后顺序。

    无论哪种模式，用户随时都可以输入，消息会排进队列。
    """

    name = "cmdline"
    supports_attachments = True
    supports_streaming = True
    dialogue_modes = frozenset({'direct'})

    @staticmethod
    def _write_line(text: str) -> None:
        sys.stderr.write(text + "\n")
        sys.stderr.flush()

    def __init__(
        self,
        config: Dict[str, Any],
        bus: MessageBus,
        message_handler: Optional[Callable] = None,
        debug: bool = False,
    ):
        super().__init__(config, bus)
        self._message_handler = message_handler
        self._session_id = uuid.uuid4().hex
        self._running_task = None
        self._debug = debug
        self._stdin_buffer = b''
        self._stdin_eof = False
        self._input_directory = Path.cwd()
        self._stream_requests = OrderedDict()
        self._stream_active = None

    def set_message_handler(self, handler: Callable) -> None:
        self._message_handler = handler

    @property
    def session_key(self) -> str:
        return f'{self.name}:{self._session_id}'

    async def wait_closed(self) -> None:
        if self._running_task:
            await self._running_task

    async def start(self) -> None:
        self._running = True
        self._running_task = self.create_task(self._input_loop())
        logger.info("Cmdline channel started")

    async def stop(self) -> None:
        self._running = False
        if self._running_task:
            self._running_task.cancel()
            try:
                await self._running_task
            except asyncio.CancelledError:
                pass
        logger.info("Cmdline channel stopped")

    # ── Output ──────────────────────────────────────────────────────

    def _print_message(self, msg: OutboundMessage) -> None:
        sender = msg.metadata.get("sender", "bot")
        text = msg.content
        prefix = "Bot: " if sender == "bot" else f"{sender.title()}: "
        lines = text.split("\n")
        for i, line in enumerate(lines):
            if i == 0:
                self._write_line(f"{prefix}{line}")
            else:
                self._write_line(f"{' ' * len(prefix)}{line}")

    @staticmethod
    def _write_chunk(text):
        sys.stderr.write(text)
        sys.stderr.flush()

    def _close_stream_line(self):
        state = self._stream_requests.get(self._stream_active)
        if state and state['open']:
            self._write_chunk('\n')
            state['open'] = False

    async def send_stream(self, session_id, frame):
        if session_id != self.session_key or frame.get('session_id') != session_id:
            return
        request_id, run_id, phase = (frame.get(key) for key in ('request_id', 'run_id', 'phase'))
        if (not isinstance(request_id, str) or not 0 < len(request_id) <= 255 or
                not isinstance(run_id, str) or not 0 < len(run_id) <= 255):
            return
        state = self._stream_requests.get(request_id)
        if phase == 'start':
            if state is not None:
                return
            self._close_stream_line()
            state = {'run_id': run_id, 'size': 0, 'digest': hashlib.sha256(),
                     'open': False, 'status': 'streaming'}
            self._stream_requests[request_id] = state
            while len(self._stream_requests) > 64:
                self._stream_requests.popitem(last=False)
            self._stream_active = request_id
        elif (state is None or state['run_id'] != run_id or
              (state['status'] != 'streaming' and not (phase == 'error' and state['status'] == 'ended'))):
            return
        elif phase == 'delta':
            text = frame.get('text')
            if not isinstance(text, str) or len(text) > 65536 or not text:
                return
            if self._stream_active != request_id:
                return
            if not state['open']:
                self._write_chunk('Bot: ')
                state['open'] = True
            self._write_chunk(text)
            state['size'] += len(text)
            state['digest'].update(text.encode('utf-8'))
        elif phase == 'end':
            state['status'] = 'ended'
        elif phase == 'error':
            self._close_stream_line()
            state['status'] = 'error'
            self._write_line('[回复已中断]')

    async def send(self, msg: OutboundMessage) -> None:
        state = self._stream_requests.get(msg.metadata.get('request_id')) if msg.session_id == self.session_key else None
        if state is not None and state['size']:
            size = state['size']
            matches = (len(msg.content) >= size and
                       hashlib.sha256(msg.content[:size].encode('utf-8')).digest() == state['digest'].digest())
            if matches:
                tail = msg.content[size:]
                if state['open']:
                    self._write_chunk(tail + '\n')
                    state['open'] = False
                elif tail:
                    self._write_line(tail)
            else:
                self._close_stream_line()
                self._print_message(msg)
            state['status'] = 'committed'
        else:
            self._close_stream_line()
            self._print_message(msg)
            if state is not None:
                state['status'] = 'committed'
        request_id = msg.metadata.get('request_id')
        if (msg.session_id == self.session_key and isinstance(request_id, str) and 0 < len(request_id) <= 255
                and state is None):
            self._stream_requests[request_id] = {'run_id': None, 'size': 0, 'open': False,
                                                 'status': 'committed'}
            while len(self._stream_requests) > 64:
                self._stream_requests.popitem(last=False)
        # Attachments always come from the durable reply, never previews.
        files = getattr(self, 'files', None)
        for item in msg.attachments:
            path = await asyncio.to_thread(files.resolve, msg.session_id, item['id']) if files else item['id']
            self._write_line(f"File: {item['name']} — {path}")

    def flush_output(self) -> None:
        """Show input prompt after a turn (debug mode only).

        Called after the Processor finishes a turn so that Bot replies
        appear below all log output.
        """
        self._write_line("")
        self._write_line("Input message:")

    # ── Input loop ──────────────────────────────────────────────────

    async def _read_input(self) -> str:
        loop = asyncio.get_running_loop()
        descriptor = None
        if input is _BUILTIN_INPUT:
            try:
                descriptor = sys.stdin.fileno()
            except (AttributeError, OSError, ValueError):
                pass
        if descriptor is not None:
            # Reading available bytes avoids blocking on a partial pipe line.
            # Terminal canonical mode still supplies its usual line editing.
            while b'\n' not in self._stdin_buffer and not self._stdin_eof:
                available = loop.create_future()

                def readable():
                    if not available.done():
                        available.set_result(None)

                try:
                    loop.add_reader(descriptor, readable)
                except (NotImplementedError, PermissionError):
                    # Regular files / loops without fd watchers use a daemon
                    # raw read, never a thread holding stdin's buffered lock.
                    data = await self._daemon_read(lambda: os.read(descriptor, 4096))
                else:
                    try:
                        await available
                        data = os.read(descriptor, 4096)
                    finally:
                        loop.remove_reader(descriptor)
                if data:
                    self._stdin_buffer += data
                else:
                    self._stdin_eof = True
            if not self._stdin_buffer:
                raise EOFError
            line, separator, rest = self._stdin_buffer.partition(b'\n')
            self._stdin_buffer = rest
            return line.decode(sys.stdin.encoding or 'utf-8', errors=sys.stdin.errors or 'strict').rstrip('\r')
        # Preserve injected input implementations and descriptor-less consoles.
        return await self._daemon_read(input)

    @staticmethod
    async def _daemon_read(reader):
        # The default executor must join blocked workers during asyncio.run's
        # shutdown. A daemon fallback lets stop return without that dependency.
        loop = asyncio.get_running_loop()
        result = loop.create_future()

        def deliver(value, error):
            if not result.done():
                if error is None:
                    result.set_result(value)
                else:
                    result.set_exception(error)

        def read():
            try:
                value, error = reader(), None
            except BaseException as exc:
                value, error = None, exc
            try:
                loop.call_soon_threadsafe(deliver, value, error)
            except RuntimeError:
                pass  # The channel's owning event loop has already closed.

        threading.Thread(target=read, name='cota-stdin', daemon=True).start()
        return await result

    async def _load_attachment(self, argument: str):
        paths = shlex.split(argument)
        if len(paths) != 1:
            raise ValueError('用法：/file "文件路径"；路径含空格时请加引号')
        files = getattr(self, 'files', None)
        if files is None:
            raise ValueError('未配置附件存储，无法添加文件')
        path = self._input_directory / Path(paths[0]).expanduser()
        # The local user explicitly selects this file, independently of the
        # model's workspace. Reuse bounded copying and regular-file validation.
        references = await asyncio.to_thread(files.import_paths, self.session_key,
                                             'default_user', path.parent, [path.name])
        return references[0]

    async def _input_loop(self) -> None:
        self._write_line(f"Session: {self.name}:{self._session_id}")
        self._write_line('附件：/file "路径" 添加，/clear 清空；输入文字或直接回车发送。/stop 退出。')
        self._write_line("Input message:")
        pending = []

        while self._running:
            try:
                message = await self._read_input()
                message = message.strip()

                if message == "/stop":
                    break

                if message == '/clear':
                    pending.clear()
                    self._write_line('已清空待发送附件。')
                    continue

                command = message.split(maxsplit=1)
                if command and command[0] == '/file':
                    try:
                        if len(pending) >= MAX_ATTACHMENTS:
                            raise ValueError(f'每条消息最多 {MAX_ATTACHMENTS} 个附件，请先发送或 /clear')
                        item = await self._load_attachment(command[1] if len(command) > 1 else '')
                    except (OSError, ValueError, RuntimeError) as error:
                        self._write_line(f'附件错误：{error}')
                    else:
                        pending.append(item)
                        self._write_line(f'已添加：{item["name"]}（待发送 {len(pending)}/{MAX_ATTACHMENTS}）')
                    continue

                if message or pending:
                    inbound_msg = InboundMessage(
                        channel=self.name,
                        sender_id="default_user",
                        chat_id=self._session_id,
                        content=message,
                        metadata={},
                        attachments=pending,
                    )
                    if self.context is not None:
                        await self.receive(inbound_msg)
                    else:
                        await self.bus.publish_inbound(inbound_msg)
                    pending.clear()

            except asyncio.CancelledError:
                break
            except EOFError:
                break
            except Exception as e:
                logger.error(f"Error in cmdline input: {e}")
        self._running = False


# 向后兼容
Cmdline = CmdlineChannel
