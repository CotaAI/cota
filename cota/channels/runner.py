"""Bounded session execution: foreground FIFO, optional background work last."""

import asyncio
from collections import deque
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Dict, Optional

from loguru import logger
from cota.inputs import InputConflict

from .base import BaseChannel
from .manager import ChannelManager
from .queue import MessageBus
from .events import InboundMessage, OutboundMessage

if TYPE_CHECKING:
    from cota.agent import Agent

Handler = Callable[[InboundMessage], Awaitable[Any]]


class ChannelRunner:
    def __init__(
        self,
        config: Dict[str, Any],
        agent: "Agent",
        message_handler: Optional[Callable] = None,
        *,
        concurrency: int = 8,
        max_pending: int = 256,
        shutdown_timeout: float = 5.0,
        channel_registry=None,
    ):
        for name, value in (("concurrency", concurrency), ("max_pending", max_pending)):
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if shutdown_timeout <= 0:
            raise ValueError("shutdown_timeout must be positive")
        self.config = config
        self.agent = agent
        from cota.store import MemoryStore
        self.store = getattr(agent, "store", None) or MemoryStore()
        self.message_handler = message_handler
        self.message_receiver = None
        self.message_bus = MessageBus(maxsize=max_pending)
        self.channel_manager: Optional[ChannelManager] = None
        self.channel_registry = channel_registry
        self._running = False
        self._processor_task: Optional[asyncio.Task] = None
        self.concurrency = concurrency
        self.max_pending = max_pending
        self.shutdown_timeout = shutdown_timeout
        self._sessions = {}
        self._ready = deque()
        self._active = {}
        self._active_turns = {}
        self._results = set()
        self._background = set()
        self._pending = 0
        self._capacity = asyncio.Event()
        self._capacity.set()
        # Volatile retry ownership for committed group mentions only. The head
        # stays inside this max_pending-sized buffer while one worker waits.
        # A full buffer backpressures intake (which may hold one more input).
        # Restart never reconstructs this queue or replays model/tool work.
        self._deferred_inputs = {}
        self._retry_changed = asyncio.Condition()
        self._retry_task: Optional[asyncio.Task] = None

    def prepare_channels(self):
        """Create adapters without starting I/O, so HTTP routes can be mounted."""
        if self.channel_manager is None:
            self.channel_manager = ChannelManager(self.config, self.message_bus, store=self.store,
                registry=self.channel_registry, receive=self.message_receiver,
                dialogue_mode=(getattr(self.agent, 'dialogue', None) or {}).get('mode', 'direct'))
            for channel in self.channel_manager.channels.values():
                channel.files = (getattr(self.agent, '_files', None) or
                                 (getattr(self.agent, 'files', None) if getattr(self.agent, 'config_path', None) else None))
            if self.agent is not None:
                self.agent._attachment_channels = {name: channel.supports_attachments
                    for name, channel in self.channel_manager.channels.items()}
        return self.channel_manager

    async def start(self, configure: Optional[Callable[[ChannelManager], Awaitable[None]]] = None) -> None:
        if self._running:
            return
        if self.message_bus.is_closed:
            raise RuntimeError("A stopped runner cannot be restarted")
        self.prepare_channels()
        self._running = True
        self._processor_task = asyncio.create_task(self._process_messages())
        try:
            if configure is not None:
                await configure(self.channel_manager)
            await self.channel_manager.start_all()
        except BaseException:
            await self.stop()
            raise
        logger.info(f"Channel runner started, channels: {self.enabled_channels}")

    async def submit(self, inbound: InboundMessage, handler: Optional[Handler] = None, *, recorded=False,
                     background=False, prepare=None) -> asyncio.Future:
        """Admit a turn without waiting for it to run; return its result future.

        max_pending bounds all unfinished turns (queued and active). Admission
        fails with QueueFull rather than growing an unbounded backlog. Cancelling
        the result does not interrupt an already executing turn.
        Optional background work yields to queued explicit work. Its queued
        future may be cancelled to make room; active execution is never evicted.
        """
        if not self._running or self.message_bus.is_closed:
            raise RuntimeError("Channel runner is not accepting messages")
        async with self.store.input_admission_lock(inbound.session_key):
            receipt, existing = await self.store.check_input(inbound)
            if receipt is not None and not (recorded and receipt['status'] == 'recorded' and existing is None):
                if existing is not None:
                    return existing
                result = asyncio.get_running_loop().create_future()
                result.set_result(receipt['status'])
                return result
            await self.store.ensure_input_admissible(inbound.session_key)
            if not self._running or self.message_bus.is_closed:
                raise RuntimeError("Channel runner is not accepting messages")
            if recorded:
                first = next((key for key in self._deferred_inputs if key[0] == inbound.session_key), None)
                if first is not None and first != (inbound.session_key, inbound.message_id):
                    raise asyncio.QueueFull  # retain this session's deferred FIFO
            if self._pending >= self.max_pending:
                if background or not self._evict_background():
                    raise asyncio.QueueFull
            # Reserve before the durable append yields to another session.
            self._pending += 1
            if self._pending >= self.max_pending:
                self._capacity.clear()
            try:
                if prepare is not None:
                    await prepare()
                if not self._running:
                    raise RuntimeError("Channel runner stopped during admission")
            except BaseException:
                self._pending -= 1
                self._capacity.set()
                raise
            result = asyncio.get_running_loop().create_future()
            result.add_done_callback(self._observe_result)
            self.store.claim_input(inbound, result)
            self._results.add(result)
            if background:
                self._background.add(result)
            key = inbound.session_key
            if key not in self._sessions:
                self._sessions[key] = deque()
                self._ready.append(key)
            queue = self._sessions[key]
            turn = (inbound, handler, result)
            if background:
                queue.append(turn)
            else:
                index = next((i for i, item in enumerate(queue) if item[2] in self._background), len(queue))
                queue.insert(index, turn)
            self._pump()
            return result

    def has_foreground(self, session_id):
        """Whether this conversation already has an explicit request to serve."""
        active = self._active_turns.get(session_id)
        return bool((active and active[2] not in self._background)
                    or any(turn[2] not in self._background for turn in self._sessions.get(session_id, ()))
                    or any(key[0] == session_id for key in self._deferred_inputs))

    def _evict_background(self):
        for queue in list(self._sessions.values()):
            for turn in reversed(queue):
                if self.discard_background(turn[2]):
                    return True
        return False

    def discard_background(self, result):
        """Drop queued optional work and release its claim before notifying callers.

        False means it already entered the execution slot (or finished). The
        owner must then await Runner's result, including its finally cleanup.
        """
        if result not in self._background:
            return False
        for key, queue in list(self._sessions.items()):
            for turn in queue:
                if turn[2] is not result:
                    continue
                queue.remove(turn)
                self.store.finish_input(turn[0])
                self._background.discard(result)
                self._pending -= 1
                self._capacity.set()
                if not queue and key not in self._active:
                    self._sessions.pop(key)
                    self._ready.remove(key)
                result.cancel()
                return True
        return False

    def _observe_result(self, result):
        self._results.discard(result)
        if not result.cancelled():
            error = result.exception()
            if error is not None:
                logger.error(f"Channel message failed: {error}")

    def _pump(self):
        while self._running and self._ready and len(self._active) < self.concurrency:
            key = next((key for key in self._ready
                        if self._sessions[key][0][2] not in self._background), self._ready[0])
            self._ready.remove(key)
            turn = self._sessions[key].popleft()
            self._active_turns[key] = turn
            self._active[key] = asyncio.create_task(self._run_turn(key, turn))

    async def _run_turn(self, key, turn):
        inbound, handler, result = turn
        try:
            if result.cancelled():
                return
            self.store.start_input(inbound)
            handler = handler or self.message_handler
            if handler is None:
                processor = self.agent.create_processor(message_bus=self.message_bus)
                value = await processor.handle_inbound_message(inbound)
            else:
                value = await handler(inbound)
            if not result.done():
                result.set_result(value)
        except asyncio.CancelledError:
            result.cancel()
            raise
        except Exception as error:
            if not result.done():
                result.set_exception(error)
            else:
                logger.error(f"Channel message failed after result cancellation: {error}")
        finally:
            self.store.finish_input(inbound)
            self._background.discard(result)
            self._active.pop(key, None)
            self._active_turns.pop(key, None)
            self._pending -= 1
            self._capacity.set()
            queue = self._sessions.get(key)
            if queue:
                self._ready.append(key)
            else:
                self._sessions.pop(key, None)
            self._pump()

    async def stop(self, *, graceful=False) -> None:
        self._running = False
        self._capacity.set()
        for queue in self._sessions.values():
            for inbound, _, result in queue:
                self.store.finish_input(inbound)
                self._background.discard(result)
                result.cancel()
                self._pending -= 1
            queue.clear()
        self._ready.clear()
        tasks = list(self._active.values())
        if self._processor_task:
            self._processor_task.cancel()
        if self._retry_task:
            self._retry_task.cancel()
        if graceful and tasks:
            # No new admission or next queued turn. Active work can checkpoint
            # a final reply while the bus/adapters are still available.
            _, remaining = await asyncio.wait(tasks, timeout=self.shutdown_timeout)
            tasks = list(remaining)
        if self._processor_task:
            tasks.append(self._processor_task)
        if self._retry_task:
            tasks.append(self._retry_task)
        for task in tasks:
            task.cancel()
        await self.message_bus.close()
        if tasks:
            _, pending = await asyncio.wait(tasks, timeout=self.shutdown_timeout)
            if pending:
                logger.error(f"{len(pending)} channel tasks did not stop within timeout")
        # A task cancelled before its first instruction cannot run its finally.
        for key, task in list(self._active.items()):
            if task.done():
                inbound, _, result = self._active_turns.pop(key)
                self.store.finish_input(inbound)
                self._background.discard(result)
                result.cancel()
                self._active.pop(key)
                self._pending -= 1
        self._sessions.clear()
        self._ready.clear()
        self._deferred_inputs.clear()
        if self.channel_manager:
            await self.channel_manager.stop_all()
        logger.info("Channel runner stopped")

    async def _process_messages(self) -> None:
        from cota.runtime.pi_runtime import RunInProgress
        while self._running:
            inbound = await self.message_bus.consume_inbound()
            if inbound is None:
                return
            while self._running:
                try:
                    if self.message_receiver is not None:
                        await self.message_receiver(inbound)
                    else:
                        await self.submit(inbound)
                    break
                except asyncio.QueueFull:
                    if (self.message_receiver is not None and inbound.mentioned and
                            (getattr(self.agent, 'dialogue', None) or {}).get('mode') == 'group'):
                        receipt = await self.store.input_receipt(inbound.session_key, inbound.message_id)
                        if receipt and receipt['status'] == 'recorded' and not receipt.get('run_id'):
                            await self._defer_group_input(inbound)
                            break
                    await self._capacity.wait()
                except (ValueError, InputConflict, RunInProgress) as error:
                    logger.warning(f"Rejected channel input: {error}")
                    break
                except RuntimeError:
                    if self.message_bus.is_closed or not self._running:
                        return
                    raise

    async def _defer_group_input(self, inbound):
        key = (inbound.session_key, inbound.message_id)
        async with self._retry_changed:
            while self._running and key not in self._deferred_inputs and len(self._deferred_inputs) >= self.max_pending:
                await self._retry_changed.wait()
            if not self._running:
                return
            # The receiver already checked identity before raising QueueFull;
            # duplicate channel delivery therefore needs no second retry slot.
            self._deferred_inputs.setdefault(key, inbound)
            if self._retry_task is None:
                self._retry_task = asyncio.create_task(self._retry_group_inputs())
                self._retry_task.add_done_callback(self._observe_retry)
            self._retry_changed.notify_all()

    @staticmethod
    def _observe_retry(task):
        if not task.cancelled() and task.exception() is not None:
            logger.error(f"Group input retry worker failed: {task.exception()}")

    async def _retry_group_inputs(self):
        from cota.runtime.pi_runtime import RunInProgress
        while self._running:
            async with self._retry_changed:
                await self._retry_changed.wait_for(lambda: self._deferred_inputs or not self._running)
                if not self._running:
                    return
                key, inbound = next(iter(self._deferred_inputs.items()))
            try:
                while self._running:
                    await self._capacity.wait()
                    if not self._running:
                        return
                    try:
                        # Reenter normal identity/run checks. A run_started fact
                        # or another live owner prevents model/tool replay.
                        await self.message_receiver(inbound)
                        break
                    except asyncio.QueueFull:
                        continue
            except (ValueError, InputConflict, RunInProgress) as error:
                logger.warning(f"Rejected deferred channel input: {error}")
            except Exception as error:
                logger.error(f"Deferred channel input failed: {error}")
            finally:
                async with self._retry_changed:
                    self._deferred_inputs.pop(key, None)
                    self._retry_changed.notify_all()

    def get_channel(self, name: str) -> Optional[BaseChannel]:
        """获取指定 Channel"""
        if self.channel_manager:
            return self.channel_manager.get_channel(name)
        return None

    @property
    def enabled_channels(self) -> list[str]:
        """获取已启用的 Channel 列表"""
        if self.channel_manager:
            return self.channel_manager.enabled_channels
        return []

    async def send_to_channel(
        self,
        channel_name: str,
        chat_id: str,
        content: str,
        media: list = None,
        metadata: dict = None,
    ) -> None:
        """发送消息到指定 Channel"""
        outbound = OutboundMessage(
            channel=channel_name,
            chat_id=chat_id,
            content=content,
            media=media or [],
            metadata=metadata or {},
        )
        await self.message_bus.publish_outbound(outbound)
