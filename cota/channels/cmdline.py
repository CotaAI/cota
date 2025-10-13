import sys
import logging
import uuid
import json
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional, Text
from sanic import Blueprint, response, Sanic
from sanic.request import Request
from sanic.response import HTTPResponse
import websockets
from cota.channels.channel import Channel
from cota.message.message import Message

logger = logging.getLogger(__name__)


class Cmdline(Channel):
    """A cmdline channel."""
    @classmethod
    def name(cls) -> Text:
        return "cmdline"

    def __init__(
        self,
        namespace: Optional[Text] = None,
        on_new_message: Callable[[Message], Awaitable[Any]] = None
    ):
        self.namespace = namespace
        self.on_new_message = on_new_message

    def blueprint(
        self, on_new_message: Callable[[Message], Awaitable[Any]]
    ) -> Blueprint:
        pass

    async def on_connect(self):
        """Handle the connection and continuously read messages from the command line."""
        session_id = uuid.uuid4().hex
        while True:
            print("Input message:")
            message = input().strip()

            if message == "/stop":
                sys.exit(0)

            message = {
                    'type': 'text',
                    'sender': 'user',
                    'sender_id': 'default_user',
                    'receiver': 'bot',
                    'receiver_id': 'default_bot',
                    'session_id': session_id,
                    'text': message,
                    'metadata': {}
                }
            message = self.handle_message(message)
            await self.on_new_message(message, self)

    async def send_text_message(
        self, recipient_id: Text, **kwargs: Any
    ) -> None:
        """Send a message through this channel."""
        await self._send_message(recipient_id, kwargs)

    async def send_image_url(
        self, recipient_id: Text, **kwargs: Any
    ) -> None:
        """Sends an image to the output"""
        await self._send_message(recipient_id, kwargs)

    async def _send_message(self, recipient_id: Text, response: Any) -> None:
        """Sends a message to the recipient using the bot event."""
        if response.get('sender') != 'user':
            print('Bot: ', response.get('text'))
