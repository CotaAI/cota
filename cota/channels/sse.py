import logging
import json
import time
import asyncio
from typing import Any, Awaitable, Callable, Dict, List, Optional, Text
from sanic import Blueprint, response
from sanic.request import Request
from sanic.response import HTTPResponse

from cota.channels.channel import Channel
from cota.message.message import Message
from cota.channels.connection import ConnectionPool
from cota.channels.room import RoomManager

logger = logging.getLogger(__name__)


class SSE(Channel):
    """A Server-Sent Events (SSE) channel with connection and room management."""
    
    @classmethod
    def name(cls) -> Text:
        return "sse"
    
    def __init__(
        self,
        namespace: Optional[Text] = None,
        sse_path: Optional[Text] = "/sse",
        connection_timeout: int = 1000,
        room_timeout: int = 3600,
    ):
        self.namespace = namespace
        self.sse_path = sse_path
        
        # Connection and room management
        self._connection_pool = ConnectionPool()
        self._room_manager = RoomManager()
                
        self._connection_timeout = connection_timeout
        self._room_timeout = room_timeout
        
        # Cleanup task
        self._cleanup_task = None
    
    async def start_background_tasks(self, app):
        if self._cleanup_task is None:
            self._cleanup_task = app.add_task(self._cleanup_loop())
            logger.info("Started SSE cleanup background task")
    
    async def _cleanup_loop(self):
        """Periodically clean up inactive connections and rooms"""
        while True:
            try:
                await asyncio.sleep(300)  # Clean up every 5 minutes
                
                conn_count = await self._connection_pool.cleanup_inactive(self._connection_timeout)
                if conn_count > 0:
                    logger.info(f"Cleaned up {conn_count} inactive SSE connections")
                
                room_count = await self._room_manager.cleanup_inactive(self._room_timeout)
                if room_count > 0:
                    logger.info(f"Cleaned up {room_count} inactive rooms")
                    
            except asyncio.CancelledError:
                logger.info("SSE cleanup task cancelled")
                break
            except Exception as e:
                logger.error(f"Error in SSE cleanup task: {e}", exc_info=True)

    def blueprint(
        self, on_new_message: Callable[[Message], Awaitable[Any]]
    ) -> Blueprint:
        bp = Blueprint('sse_webhook')

        @bp.route("/health", methods=["GET"])
        async def health(_: Request) -> HTTPResponse:
            return response.json({
                "status": "ok",
                "timestamp": time.time(),
                "service": "sse"
            })

        @bp.route(self.sse_path, methods=['GET'])
        async def sse_feed(request: Request) -> HTTPResponse:
            """Handle SSE connection requests"""
            sender_id = request.args.get("sender_id", None)
            
            # Create response stream
            response_stream = await self._handle_sse_connection(sender_id)
            return response.stream(
                response_stream,
                content_type='text/event-stream',  # Required content type for SSE
                headers={
                    'Cache-Control': 'no-cache',
                    'Connection': 'keep-alive',
                    'X-Accel-Buffering': 'no'
                }
            )

        @bp.route(self.sse_path + "/message", methods=['POST'])
        async def handle_message(request: Request) -> HTTPResponse:
            """Handle incoming messages via HTTP POST"""
            try:
                msg = request.json
                if not self._validate_message(msg):
                    return response.json({
                        "type": "message_error",
                        "error": "Invalid message format",
                        "timestamp": time.time()
                    }, status=400)

                msg_type = msg.get('type')
                
                if msg_type == 'join':
                    await self._handle_join(msg)
                    return response.json({
                        "type": "join_confirm",
                        "session_id": msg.get("session_id"),
                        "timestamp": time.time()
                    })
                elif msg_type == 'leave':
                    await self._handle_leave(msg)
                    return response.json({
                        "type": "leave_confirm",
                        "session_id": msg.get("session_id"),
                        "timestamp": time.time()
                    })

                message_obj = self.handle_message(msg)
                await on_new_message(message_obj, self)
                return response.json({
                    "type": "message_confirm",
                    "timestamp": time.time()
                })

            except Exception as e:
                logger.error(f"Error processing message: {e}", exc_info=True)
                return response.json({
                    "type": "error",
                    "error": "Internal server error",
                    "timestamp": time.time()
                }, status=500)

        return bp

    def _validate_message(self, msg: Dict) -> bool:
        """Validate message format"""
        required_fields = ["session_id", "sender_id"]
        return all(field in msg for field in required_fields)

    async def _handle_sse_connection(self, sender_id: str):
        """Handle SSE connection and message streaming"""
        queue = asyncio.Queue()
        await self._connection_pool.add(sender_id, queue)
        
        try:
            # Send initial connection message
            await queue.put(self._format_sse_message({
                "type": "login",
                "sender_id": sender_id,
                "timestamp": time.time()
            }))

            # Start heartbeat task
            heartbeat_task = asyncio.create_task(self._send_heartbeat(queue, sender_id))

            while True:
                message = await queue.get()
                yield message

        finally:
            heartbeat_task.cancel()
            await self._connection_pool.remove(sender_id)
            logger.info(f"SSE connection closed for {sender_id}")

    async def _send_heartbeat(self, queue: asyncio.Queue, sender_id: str):
        """Send periodic heartbeat messages"""
        while True:
            try:
                await asyncio.sleep(30)
                await queue.put(self._format_sse_message({
                    "type": "ping",
                    "timestamp": time.time()
                }))
                await self._connection_pool.update_activity(sender_id)
            except Exception:
                break

    async def _handle_join(self, msg: Dict):
        """Handle join room request"""
        session_id = msg.get("session_id")
        sender_id = msg.get("sender_id")
        
        if not session_id or not sender_id:
            raise ValueError("Missing required parameters")
            
        room_id = session_id
        
        # Add user to room
        await self._room_manager.add_user_to_room(room_id, sender_id)
        
        # Get room users
        room_users = await self._room_manager.get_room_users(room_id)
        
        # Send join confirmation to the user
        queue = await self._connection_pool.get(sender_id)
        if queue:
            await queue.put(self._format_sse_message({
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
        
        # Notify other users in the room
        await self._broadcast_to_room(
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

    async def _handle_leave(self, msg: Dict):
        """Handle leave room request"""
        session_id = msg.get("session_id")
        sender_id = msg.get("sender_id")
        
        if session_id and sender_id:
            await self._room_manager.remove_user_from_room(session_id, sender_id)
            
            # Notify other users
            room_users = await self._room_manager.get_room_users(session_id)
            await self._broadcast_to_room(
                session_id,
                {
                    "type": "user_left",
                    "session_id": session_id,
                    "user_id": sender_id,
                    "timestamp": time.time(),
                    "room_info": {
                        "user_count": len(room_users),
                        "users": room_users,
                        "room_id": session_id
                    }
                }
            )

    async def _broadcast_to_room(self, room_id: str, message: Dict[str, Any], exclude_user: Optional[str] = None) -> int:
        """Broadcast message to all users in the room"""
        user_ids = await self._room_manager.get_room_users(str(room_id))
        sent_count = 0
        
        for user_id in user_ids:
            if user_id != exclude_user:
                queue = await self._connection_pool.get(str(user_id))
                if queue:
                    try:
                        await queue.put(self._format_sse_message(message))
                        sent_count += 1
                    except Exception as e:
                        logger.error(f"Error broadcasting to room member {user_id}: {e}")
        
        return sent_count

    def _format_sse_message(self, data: Dict) -> str:
        """Format message for SSE protocol"""
        return f"data: {json.dumps(data)}\n\n"

    async def send_text_message(self, recipient_id: Text, **kwargs: Any) -> None:
        """Send text message"""
        await self._send_message(recipient_id, kwargs)

    async def send_image_url(self, recipient_id: Text, **kwargs: Any) -> None:
        """Send image URL"""
        await self._send_message(recipient_id, kwargs)

    async def _send_message(self, recipient_id: Text, response: Any) -> None:
        """Send message to recipient(s)"""
        logger.debug(f"Sending message to recipient {recipient_id}")
        
        user_ids = await self._room_manager.get_room_users(str(recipient_id))
        logger.debug(f"Recipients in room: {user_ids}")
        
        sent_count = 0
        for user_id in user_ids:
            queue = await self._connection_pool.get(str(user_id))
            if queue:
                try:
                    await queue.put(self._format_sse_message(response))
                    sent_count += 1
                except Exception as e:
                    logger.error(f"Error sending message to {user_id}: {e}")

        if sent_count > 0:
            logger.debug(f"Message sent to {sent_count}/{len(user_ids)} recipients")
        else:
            logger.warning(f"Failed to send message to any recipient in room {recipient_id}")

    def handle_message(self, message: Dict[str, Any]) -> Message:
        """Convert original message to Message object"""
        return Message(message)