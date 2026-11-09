"""The small, trusted host interface exposed to a Channel adapter."""
from dataclasses import dataclass, replace
from typing import Awaitable, Callable, Any

from .events import InboundMessage


@dataclass(frozen=True)
class ChannelContext:
    name: str
    dialogue_mode: str
    _receive: Callable[[InboundMessage], Awaitable[Any]] | None

    async def receive(self, message: InboundMessage):
        """Return only after Application admits and persists this input.

        Identity/authorization must already have been checked by the adapter.
        A return value confirms admission, never model completion or delivery.
        """
        if not isinstance(message, InboundMessage):
            raise TypeError('Channel.receive requires InboundMessage')
        if self._receive is None:
            raise RuntimeError('Durable Channel.receive requires an Application host')
        return await self._receive(replace(message, channel=self.name))
