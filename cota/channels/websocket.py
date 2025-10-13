import logging
import uuid
import json
import time
import asyncio
from typing import Any, Awaitable, Callable, Dict, List, Optional, Text, Set
from sanic import Blueprint, Sanic
from sanic.request import Request
from sanic.response import HTTPResponse
from websockets import WebSocketServerProtocol, ConnectionClosed

from cota.channels.channel import Channel
from cota.message.message import Message
from cota.channels.connection import ConnectionPool
from cota.channels.room import RoomManager

logger = logging.getLogger(__name__)


class Websocket(Channel):
    """A websocket channel with room management."""
    
    @classmethod
    def name(cls) -> Text:
        return "websocket"
    
    def __init__(
        self,
        namespace: Optional[Text] = None,
        websocket_path: Optional[Text] = "/websocket",
        connection_timeout: int = 1000,
        room_timeout: int = 3600,
    ):
        self.namespace = namespace
        self.websocket_path = websocket_path
        
        # Use connection pool and room manager
        self._connection_pool = ConnectionPool()
        self._room_manager = RoomManager()
                
        self._connection_timeout = connection_timeout
        self._room_timeout = room_timeout
        
        # Cleanup task
        self._cleanup_task = None
    
    def blueprint(
        self, on_new_message: Callable[[Message], Awaitable[Any]]
    ) -> Blueprint:
        bp = Blueprint('websocket')

        # Start background tasks when the server starts
        @bp.before_server_start
        async def before_server_start(app: Sanic):
            if self._cleanup_task is None:
                self._cleanup_task = app.add_task(self._cleanup_loop())
                logger.info("Started WebSocket cleanup background task")

        # Handle WebSocket connections
        @bp.websocket(self.websocket_path)
        async def ws_route(request: Request, ws: WebSocketServerProtocol):
            sender_id = request.args.get("sender_id", None)
            if not sender_id:
                await ws.close(4001, "No sender_id provided")
                return

            sender_id = str(sender_id)
            await self._connection_pool.add(sender_id, ws)
            
            try:
                # send login confirmation
                await ws.send(json.dumps({
                    "type": "login", 
                    "sender_id": sender_id,
                    "timestamp": time.time()
                }))
                
                await self.on_connect(ws, on_new_message)
                    
            except ConnectionClosed as e:
                logger.info(f"WebSocket connection closed by client: {e}")
            except Exception as e:
                logger.error(f"Error in WebSocket connection: {e}", exc_info=True)
                await ws.close(1011, "Internal server error")
            finally:
                await self._connection_pool.remove(sender_id)
        
        return bp
    
    async def _cleanup_loop(self):
        """Periodically clean up inactive connections and rooms"""
        while True:
            try:
                await asyncio.sleep(300)  # cleanup every 5 minutes
                
                conn_count = await self._connection_pool.cleanup_inactive(
                    self._connection_timeout
                )
                if conn_count > 0:
                    logger.info(f"Cleaned up {conn_count} inactive connections")
                
                room_count = await self._room_manager.cleanup_inactive(
                    self._room_timeout
                )
                if room_count > 0:
                    logger.info(f"Cleaned up {room_count} inactive rooms")
                
            except asyncio.CancelledError:
                logger.info("WebSocket cleanup task cancelled")
                break
            except Exception as e:
                logger.error(f"Cleanup error: {e}", exc_info=True)
                await asyncio.sleep(5)
    
    async def on_connect(self, ws, on_new_message):
        """Handle WebSocket connections and messages"""
        try:
            while True:
                try:
                    message = await ws.recv()
                    msg = json.loads(message)

                    if not self._validate_message(msg):
                        logger.warning(f"Invalid message format: {msg}")
                        continue
                    
                    # get message type, session_id, sender_id, room_id
                    msg_type = msg.get('type')
                    session_id = msg.get("session_id")
                    sender_id = msg.get("sender_id")
                    room_id = session_id

                    if msg_type == 'join':
                        await self.on_join(msg, ws)
                        continue
                    elif msg_type == 'ping':
                        # update connection activity, should ensure client send ping message
                        await self._connection_pool.update_activity(sender_id)
                        await ws.send(json.dumps({
                            "type": "pong", 
                            "timestamp": time.time()
                        }))
                        continue

                    message_obj = self.handle_message(msg)
                    await on_new_message(message_obj, self)
                    
                except json.JSONDecodeError as e:
                    logger.warning(f"Failed to parse message: {e}")
                except ConnectionClosed:
                    break
                except Exception as e:
                    logger.error(f"Error processing message: {e}", exc_info=True)
        
        except Exception as e:
            logger.error(f"Unhandled exception in on_connect: {e}", exc_info=True)
    
    def _validate_message(self, msg):
        """Validate message format"""
        required_fields = ["session_id", "sender_id"]
        return all(field in msg for field in required_fields)
    
    async def on_join(self, msg, ws):
        """Handle join room request"""
        session_id = msg.get("session_id")
        sender_id = msg.get("sender_id")
        
        if not session_id or not sender_id:
            return
            
        try:
            room_id = session_id
            # add user to room
            await self._room_manager.add_user_to_room(room_id, sender_id)
            
            # get room users
            room_users = await self._room_manager.get_room_users(room_id)

            # send join confirm
            await ws.send(json.dumps({
                "type": "join_confirm",
                "session_id": session_id,
                "room_id": room_id,
                "timestamp": time.time(),
                "room_info": {
                    "user_count": len(room_users),
                    "users": room_users,
                    "room_id": room_id
                }
            }))

            # broadcast user joined
            await self.broadcast_to_room(
                room_id,
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
                exclude_user=sender_id
            )
        except Exception as e:
            logger.error(f"Error handling join request: {e}")
            await ws.send(json.dumps({
                "type": "join_error",
                "session_id": session_id,
                "timestamp": time.time(),
                "error": str(e)
            }))
    
    async def send_text_message(self, recipient_id: Text, **kwargs: Any) -> None:
        """Send text message"""
        await self._send_message(recipient_id, kwargs)
    
    async def send_image_url(self, recipient_id: Text, **kwargs: Any) -> None:
        """Send image URL"""
        await self._send_message(recipient_id, kwargs)
    
    async def _send_message(self, recipient_id: Text, response: Any) -> None:
        """Send message to recipient(s)"""
        user_ids = await self._room_manager.get_room_users(str(recipient_id))
        
        sent_count = 0
        for user_id in user_ids:
            ws = await self._connection_pool.get(str(user_id))
            if ws:
                try:
                    await ws.send(json.dumps(response))
                    sent_count += 1
                except Exception as e:
                    logger.error(f"Error sending message to {user_id}: {e}")
        
        if sent_count == 0:
            logger.warning(f"Failed to send message to any recipient in room {recipient_id}")
    
    async def broadcast(self, message: Dict[str, Any], exclude_user: Optional[str] = None) -> int:
        """Broadcast message to all connected users"""
        connections = await self._connection_pool.get_all_connections()
        sent_count = 0
        
        for user_id, ws in connections.items():
            if user_id != exclude_user:
                try:
                    await ws.send(json.dumps(message))
                    sent_count += 1
                except Exception as e:
                    logger.error(f"Error broadcasting to {user_id}: {e}")
        
        return sent_count
    
    async def broadcast_to_room(self, room_id: str, message: Dict[str, Any], exclude_user: Optional[str] = None) -> int:
        """Broadcast message to all users in the room"""
        user_ids = await self._room_manager.get_room_users(str(room_id))
        sent_count = 0
        
        for user_id in user_ids:
            if user_id != exclude_user:
                ws = await self._connection_pool.get(str(user_id))
                if ws:
                    try:
                        await ws.send(json.dumps(message))
                        sent_count += 1
                    except Exception as e:
                        logger.error(f"Error broadcasting to room member {user_id}: {e}")
        
        return sent_count
    
    def handle_message(self, message: Dict[str, Any]) -> Message:
        """Convert original message to Message object"""
        return Message(message)