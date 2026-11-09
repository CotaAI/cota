"""Web client adapter. The server owns listening sockets and authentication."""
from ..base import BaseChannel
from .transport import TransportFactory


class WebChannel(BaseChannel):
    name = 'web'

    def __init__(self, config, bus):
        super().__init__(config, bus)
        self._transport = TransportFactory.create(config.get('transport', 'websocket'), config, bus)

    async def start(self):
        await self._transport.start()
        self._running = True

    async def stop(self):
        await self._transport.stop()
        self._running = False

    async def send(self, message):
        await self._transport.send(message)

    def get_transport(self):
        return self._transport
