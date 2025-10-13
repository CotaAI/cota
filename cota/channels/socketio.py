import logging
import uuid
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional, Text
from sanic import Blueprint, response, Sanic
from sanic.request import Request
from sanic.response import HTTPResponse
from socketio import AsyncServer

from cota.channels.channel import Channel
from cota.message.message import Message

logger = logging.getLogger(__name__)


class SocketBlueprint(Blueprint):
    def __init__(
        self, sio: AsyncServer, socketio_path: Text, *args: Any, **kwargs: Any
    ) -> None:
        """Creates a :class:`sanic.Blueprint` for routing socketio connenctions.

        :param sio: Instance of :class:`socketio.AsyncServer` class
        :param socketio_path: string indicating the route to accept requests on.
        """
        super().__init__(*args, **kwargs)
        self.ctx.sio = sio
        self.ctx.socketio_path = socketio_path

    def register(self, app: Sanic, options: Dict[Text, Any]) -> None:
        """Attach the Socket.IO webserver to the given Sanic instance.

        :param app: Instance of :class:`sanic.app.Sanic` class
        :param options: Options to be used while registering the
            blueprint into the app.
        """
        self.ctx.sio.attach(app, self.ctx.socketio_path)
        super().register(app, options)


class SocketIO(Channel):
    """A socket.io channel."""
    @classmethod
    def name(cls) -> Text:
        return "socketio"

    def __init__(
        self,
        namespace: Optional[Text] = None,
        socketio_path: Optional[Text] = "/socket.io",
    ):
        self.namespace = namespace
        self.socketio_path = socketio_path
        self.sio = None

    def blueprint(
        self, on_new_message: Callable[[Message], Awaitable[Any]]
    ) -> Blueprint:
        # Workaround so that socketio works with requests from other origins.
        # https://github.com/miguelgrinberg/python-socketio/issues/205#issuecomment-493769183
        # Create socket.io server using AsyncServer and specify async mode, allow CORS
        sio = AsyncServer(async_mode="sanic", cors_allowed_origins=[])
        # Create blueprint named socketio_webhook
        socketio_webhook = SocketBlueprint(
            sio, self.socketio_path, "socketio_webhook", __name__
        )

        self.sio = sio

        # Health check endpoint for socketio
        @socketio_webhook.route("/health", methods=["GET"]) 
        async def health(_: Request) -> HTTPResponse:
            return response.json({
                "status": "ok",
                "timestamp": time.time(),
                "service": "socketio"
            })

        @sio.on("connect", namespace=self.namespace)
        async def connect(sid: Text, environ: Dict) -> None:
            """Handle new socket.io connection.
            
            Args:
                sid: Session ID of the connecting client
                environ: WSGI environment dictionary containing connection details
            """
            logger.info(f"New socket.io connection from {sid}")

        @sio.on("disconnect", namespace=self.namespace)
        async def disconnect(sid: Text) -> None:
            """Handle socket.io disconnect event.
            
            Args:
                sid: Session ID of the disconnecting client
            """
            logger.debug(f"User {sid} disconnected from socketIO endpoint.")

        @sio.on("login", namespace=self.namespace)
        async def handle_login(sid: Text, data: Optional[Dict]):
            try:
                if data is None:
                    data = {}
                
                user_id = data.get("user_id")
                if not user_id:
                    logger.warning(f"Missing user_id from login request")
                    await sio.emit("login_error", {
                        "type": "login_error",
                        "error": "Missing user_id",
                        "timestamp": time.time()
                    }, room=sid)
                    return
                
                # Save basic session information
                await sio.save_session(sid, {
                    "user_id": user_id,
                    "connected_at": time.time(),
                    "last_activity": time.time()
                })
                
                # Send login confirmation
                await sio.emit(
                    "login",
                    {
                        "type": "login",
                        "sender_id": user_id,
                        "timestamp": time.time()
                    },
                    room=sid,
                    namespace=self.namespace
                )
                
                logger.info(f"User {user_id} (socket: {sid}) logged in")
                
            except Exception as e:
                logger.error(f"Error handling login request for user {sid}: {e}")
                await sio.emit("login_error", {
                    "type": "login_error",
                    "error": "Failed to process login request",
                    "timestamp": time.time()
                }, room=sid)

        @sio.on("join", namespace=self.namespace)
        async def handle_join(sid: Text, data: Optional[Dict]):
            try:
                if data is None:
                    data = {}
                
                session_id = data.get("session_id")
                sender_id = data.get("sender_id")
                
                if not session_id or not sender_id:
                    logger.warning(f"Missing required parameters from user {sid}")
                    await sio.emit("join_error", {
                        "type": "join_error",
                        "error": "Missing required parameters",
                        "timestamp": time.time()
                    }, room=sid)
                    return
                
                room_id = session_id  # Use session_id as room_id, consistent with websocket implementation
                
                # Save session information
                await sio.save_session(sid, {
                    "user_id": sender_id,
                    "session_id": session_id,
                    "room_id": room_id,
                    "connected_at": time.time(),
                    "last_activity": time.time()
                })

                # Join the room
                await sio.enter_room(sid, room_id)
                
                # Get room users (need to implement method to get room users)
                room_users = await self._get_room_users(room_id)
                
                # Send join confirmation
                await sio.emit(
                    "join_confirm",
                    {
                        "type": "join_confirm",
                        "session_id": session_id,
                        "room_id": room_id,
                        "timestamp": time.time(),
                        "room_info": {
                            "user_count": len(room_users),
                            "users": room_users,
                            "room_id": room_id
                        }
                    },
                    room=sid
                )
                
                # Notify other members in the room
                await sio.emit(
                    "user_joined",
                    {
                        "type": "user_joined",
                        "session_id": session_id,
                        "room_id": room_id,
                        "user_id": sender_id,
                        "timestamp": time.time(),
                        "room_info": {
                            "user_count": len(room_users),
                            "users": room_users,
                            "room_id": room_id
                        }
                    },
                    room=room_id,
                    skip_sid=sid
                )
                
                logger.info(f"User {sender_id} joined session {session_id}")
                
            except Exception as e:
                logger.error(f"Error handling join request: {e}")
                await sio.emit("join_error", {
                    "type": "join_error",
                    "session_id": session_id,
                    "timestamp": time.time(),
                    "error": str(e)
                }, room=sid)

        @sio.on("session_leave", namespace=self.namespace)
        async def session_leave(sid: Text, data: Optional[Dict]):
            if data is None or data.get("session_id",None) is None:
                return
            # Leave room
            await sio.leave_room(sid, data["session_id"])

        @sio.on("message", namespace=self.namespace)
        async def handle_message(sid: Text, msg: Dict) -> Any:
            try:
                logger.debug(f"Received message {msg}")
                
                if not self._validate_message(msg):
                    logger.warning(f"Invalid message format: {msg}")
                    return
                
                session_id = msg.get("session_id")
                sender_id = msg.get("sender_id")
                
                message_obj = self.handle_message(msg)
                logger.debug("Message converted to: %s", message_obj.as_dict())
                await on_new_message(message_obj, self)
                
            except Exception as e:
                logger.error(f"Error processing message: {e}", exc_info=True)
                
        def _validate_message(self, msg):
            """Validate message format"""
            required_fields = ["session_id", "sender_id"]
            return all(field in msg for field in required_fields)
            
        return socketio_webhook

    async def _send_message(self, recipient_id: Text, response: Any) -> None:
        """Sends a message to the recipient using the bot event."""
        logger.debug("Executing _send_message: %s", response)
        await self.sio.emit("bot_uttered", response, room=recipient_id)

    async def send_text_message(
        self, recipient_id: Text, **kwargs: Any
    ) -> None:
        """Send a message through this channel."""
        logger.debug("Executing send_text_message: %s", text)
        await self._send_message(recipient_id, kwargs)

    async def send_image_url(
        self, recipient_id: Text, image: Text, **kwargs: Any
    ) -> None:
        """Sends an image to the output"""
        await self._send_message(recipient_id, kwargs)
