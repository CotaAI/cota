"""Cmdline Channel - 命令行交互

适配 BaseChannel 框架的命令行 Channel。
"""

import asyncio
import os
import sys
import threading
import uuid
from typing import Any, Callable, Dict, Optional

from loguru import logger

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

    async def send(self, msg: OutboundMessage) -> None:
        self._print_message(msg)

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

    async def _input_loop(self) -> None:
        self._write_line(f"Session: {self.name}:{self._session_id}")
        self._write_line("Input message:")

        while self._running:
            try:
                message = await self._read_input()
                message = message.strip()

                if message == "/stop":
                    break

                if message:
                    inbound_msg = InboundMessage(
                        channel=self.name,
                        sender_id="default_user",
                        chat_id=self._session_id,
                        content=message,
                        metadata={},
                    )
                    if self.context is not None:
                        await self.receive(inbound_msg)
                    else:
                        await self.bus.publish_inbound(inbound_msg)

            except asyncio.CancelledError:
                break
            except EOFError:
                break
            except Exception as e:
                logger.error(f"Error in cmdline input: {e}")
        self._running = False


# 向后兼容
Cmdline = CmdlineChannel
