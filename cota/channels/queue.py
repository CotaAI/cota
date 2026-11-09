"""Closable async queues between channel adapters and processors."""

import asyncio
from typing import Optional

from .events import InboundMessage, OutboundMessage


class MessageBus:
    """Closing discards queued messages and wakes consumers and publishers.

    A consumer receives None after closure. A publisher raises RuntimeError,
    including publishers that were waiting for room when the bus was closed.
    """

    def __init__(self, maxsize: int = 0):
        if maxsize < 0:
            raise ValueError('maxsize must be nonnegative')
        self._inbound_queue: asyncio.Queue[InboundMessage] = asyncio.Queue(maxsize=maxsize)
        self._outbound_queue: asyncio.Queue[OutboundMessage] = asyncio.Queue(maxsize=maxsize)
        self._closed = asyncio.Event()
        self._changed = asyncio.Condition()

    async def _publish(self, queue, message):
        async with self._changed:
            while queue.full() and not self.is_closed:
                await self._changed.wait()
            if self.is_closed:
                raise RuntimeError('Message bus is closed')
            queue.put_nowait(message)
            self._changed.notify_all()

    async def _consume(self, queue, timeout):
        async def receive():
            async with self._changed:
                while queue.empty() and not self.is_closed:
                    await self._changed.wait()
                if self.is_closed:
                    return None
                message = queue.get_nowait()
                self._changed.notify_all()
                return message
        if timeout is None:
            return await receive()
        return await asyncio.wait_for(receive(), timeout)

    async def publish_inbound(self, msg: InboundMessage) -> None:
        await self._publish(self._inbound_queue, msg)

    async def consume_inbound(self, timeout: Optional[float] = None) -> Optional[InboundMessage]:
        return await self._consume(self._inbound_queue, timeout)

    async def publish_outbound(self, msg: OutboundMessage) -> None:
        await self._publish(self._outbound_queue, msg)

    async def consume_outbound(self, timeout: Optional[float] = None) -> Optional[OutboundMessage]:
        return await self._consume(self._outbound_queue, timeout)

    @property
    def inbound_size(self) -> int:
        return self._inbound_queue.qsize()

    @property
    def outbound_size(self) -> int:
        return self._outbound_queue.qsize()

    async def close(self) -> None:
        async with self._changed:
            self._closed.set()
            for queue in (self._inbound_queue, self._outbound_queue):
                while not queue.empty():
                    queue.get_nowait()
            self._changed.notify_all()

    @property
    def is_closed(self) -> bool:
        return self._closed.is_set()

    def is_empty(self) -> bool:
        return self._inbound_queue.empty() and self._outbound_queue.empty()
