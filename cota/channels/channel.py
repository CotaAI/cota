import asyncio
import inspect
import json
import logging
import uuid
from asyncio import Queue, CancelledError
from sanic import Sanic, Blueprint, response
from sanic.request import Request
from sanic.response import HTTPResponse
from typing import Text, List, Dict, Any, Optional, Callable, Iterable, Awaitable, NoReturn

from cota.message.message import Message
from cota.channels.utils import convert_message_dict

try:
    from urlparse import urljoin  # pytype: disable=import-error
except ImportError:
    from urllib.parse import urljoin

logger = logging.getLogger(__name__)


def register(
    channels: List["Channel"], app: Sanic, route: Optional[Text] = None
) -> None:
    """Register a group of input channels to Sanic application and create corresponding route handlers for each channel"""
    async def handler(message: Message, channel):
        await app.ctx.agent.processor.handle_message(message, channel)

    for channel in channels:
        if route:
            p = urljoin(route, channel.url_prefix())
        else:
            p = None
        # registe bulueprint to sanic
        app.blueprint(channel.blueprint(handler), url_prefix=p)
    app.ctx.channels = channels


class Channel:
    @classmethod
    def name(cls) -> Text:
        return cls.__name__

    def url_prefix(self) -> Text:
        return self.name()

    def blueprint(
        self, on_new_message: Callable[[Message], Awaitable[Any]]
    ) -> Blueprint:
        """Defines a Sanic blueprint.

        The blueprint will be attached to a running sanic server and handle
        incoming routes it registered for."""
        raise NotImplementedError("Component listener needs to provide blueprint.")

    @classmethod
    def raise_missing_credentials_exception(cls) -> NoReturn:
        raise Exception(
            "To use the {} input channel, you need to "
            "pass a credentials file using '--credentials'. "
            "The argument should be a file path pointing to "
            "a yml file containing the {} authentication "
            "information. Details in the docs: "
            "{}/user-guide/messaging-and-voice-channels/".format(
                cls.name(), cls.name(), DOCS_BASE_URL
            )
        )


    def get_metadata(self, request: Request) -> Optional[Dict[Text, Any]]:
        """Extracts additional information from the incoming request.

         Implementing this function is not required. However, it can be used to extract
         metadata from the request. The return value is passed on to the
         ``UserMessage`` object and stored in the conversation tracker.

        Args:
            request: incoming request with the message of the user

        Returns:
            Metadata which was extracted from the request.
        """
        pass
    
    def handle_message(self, message: Dict[Text, Any]) -> Message:
        """ handle client message """
        if message.get("type") == "text":
            return self.handle_text_message(message.pop("sender_id"), message.pop("text"), **message)
        
        if message.get("type") == "image":
            return self.handle_image_message(message.pop("sender_id"), message.pop("image"), **message)

    def handle_text_message(self, sender_id:Text, text:Text, **kwargs: Any) -> Message:
        return Message(
            sender = 'user',
            sender_id = sender_id,
            receiver = kwargs.get("receiver", None),
            receiver_id = kwargs.get("receiver_id", None),
            session_id = kwargs.get("session_id", None),
            text = text,
            metadata = {}
        )

    def handle_image_message(self, sender_id:Text, image:Text, **kwargs: Any) -> Message:
        return Message(
            sender = 'user',
            sender_id = sender_id,
            receiver = kwargs.get("receiver", None),
            receiver_id = kwargs.get("receiver_id", None),
            session_id = kwargs.get("session_id", None),
            text = "",
            metadata = {"image": image}
        )

    async def send_response(self, recipient_id: Text, message: Dict[Text, Any]) -> None:
        """Send a message to the client."""
        messages = convert_message_dict(message)

        for message in messages:
            if message.get('type') == 'text':
                await self.send_text_message(recipient_id, **message)
            
            if message.get('type') == 'image':
                await self.send_image_url(recipient_id, **message)

    async def send_text_message(
        self, recipient_id: Text, **kwargs: Any
    ) -> None:
        """Send a message through this channel."""

        raise NotImplementedError(
            "Output channel needs to implement a send message for simple texts."
        )

    async def send_image_url(
        self, recipient_id: Text, **kwargs: Any
    ) -> None:
        """Sends an image. Default will just post the url as a string."""

        await self.send_text_message(recipient_id, f"Image: {image}")