"""WebSocket connection adapter mounted on Cota's existing HTTP server.

Conversation ownership and execution live in WebService. Each connection has
its own bounded sender; a disconnected/slow client cannot stall other users.
"""
import asyncio
from contextlib import suppress
from dataclasses import dataclass, field
import json
import logging
from weakref import WeakValueDictionary

from .service import message_record

logger = logging.getLogger(__name__)


@dataclass(eq=False)
class Connection:
    socket: object
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=128))
    sender: asyncio.Task | None = None
    user_id: str | None = None
    session_id: str | None = None
    token: str | None = field(default=None, repr=False)
    pending: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=128))
    replaying: bool = False
    handler: asyncio.Task | None = None
    sessions: set = field(default_factory=set)
    managed: bool = False
    cursors: dict = field(default_factory=dict)
    replay_session: str | None = None
    stream_queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=32))
    stream_next: dict | None = None


class WebSocketTransport:
    name = 'websocket'

    def __init__(self, config, bus):
        self.config, self.bus = config, bus
        self.service = None
        self._running = False
        self._connections = {}
        self._handlers = set()
        self._closing_handlers = set()
        self._users = {}
        self._locks = WeakValueDictionary()
        for name, default, ceiling in (('max_connections', 1024, 10000),
                                       ('max_connections_per_user', 8, 100),
                                       ('max_subscriptions', 32, 256)):
            value = config.get(name, default)
            if type(value) is not int or not 1 <= value <= ceiling:
                raise ValueError(f'{name} must be between 1 and {ceiling}')
            setattr(self, name, value)

    def status(self):
        return {'connections': len(self._handlers),
                'subscriptions': sum(len(group) for group in self._connections.values()),
                'max_connections': self.max_connections, 'max_subscriptions': self.max_subscriptions}

    @property
    def is_running(self):
        return self._running

    def bind(self, service):
        self.service = service
        service.transport = self

    def _lock(self, session_id):
        lock = self._locks.get(session_id)
        if lock is None:
            lock = self._locks[session_id] = asyncio.Lock()
        return lock

    async def start(self):
        if self.service is None:
            raise RuntimeError('WebChannel must be mounted by cota.server.create_app')
        self._running = True

    async def stop(self):
        self._running = False
        handlers = tuple(self._handlers)
        for handler in handlers:
            if handler not in self._closing_handlers:
                handler.cancel()
        connections = {c for group in self._connections.values() for c in group}
        self._connections.clear()
        for connection in connections:
            if connection.sender:
                connection.sender.cancel()
        await asyncio.gather(*(self._close(c.socket) for c in connections), return_exceptions=True)
        await asyncio.gather(*(c.sender for c in connections if c.sender), return_exceptions=True)
        await asyncio.gather(*handlers, return_exceptions=True)

    @staticmethod
    async def _close(socket):
        with suppress(Exception):
            await asyncio.wait_for(socket.close(), 2)

    async def _send_loop(self, connection):
        try:
            while True:
                frame = await self._next_frame(connection)
                # Membership and credentials can be revoked after resume, even
                # while history/live frames are waiting in a slow client's queue.
                session_id = frame.get('session_id', connection.session_id)
                if connection.managed and session_id not in connection.sessions and frame.get('type') != 'error':
                    continue
                await asyncio.wait_for(self._authorize_connection(connection, session_id), 10)
                await asyncio.wait_for(connection.socket.send(json.dumps(frame, ensure_ascii=False)), 10)
        except PermissionError:
            with suppress(Exception):
                await asyncio.wait_for(connection.socket.send(json.dumps({
                    'type': 'error', 'code': 'unauthorized', 'message': 'Conversation access expired or was revoked'})), 2)
            await self._close(connection.socket)
        except asyncio.CancelledError:
            # The handler/stop owns socket closure. It may first need to send a
            # sanitized terminal error after taking over this writer.
            raise
        except Exception:
            await self._close(connection.socket)

    @staticmethod
    async def _next_frame(connection):
        # Durable messages have priority and their own capacity. Preview traffic
        # cannot occupy the replay/outbox queue or advance its cursor.
        if not connection.queue.empty():
            return connection.queue.get_nowait()
        if connection.stream_next is not None:
            frame, connection.stream_next = connection.stream_next, None
            return frame
        if not connection.stream_queue.empty():
            return connection.stream_queue.get_nowait()
        durable = asyncio.create_task(connection.queue.get())
        preview = asyncio.create_task(connection.stream_queue.get())
        try:
            await asyncio.wait((durable, preview), return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in (durable, preview):
                if not task.done():
                    task.cancel()
            await asyncio.gather(durable, preview, return_exceptions=True)
        if not durable.cancelled():
            if not preview.cancelled():
                connection.stream_next = preview.result()
            return durable.result()
        return preview.result()

    async def send_stream(self, session_id, frame):
        """Best-effort public previews for current subscribers; no replay."""
        if not isinstance(frame, dict) or frame.get('session_id') != session_id:
            return
        if frame.get('phase') not in ('start', 'delta', 'end', 'error'):
            return
        if any(not isinstance(frame.get(key), str) or not 0 < len(frame[key]) <= 255
               for key in ('session_id', 'run_id', 'request_id')):
            return
        if 'text' in frame and (not isinstance(frame['text'], str) or len(frame['text']) > 65536):
            return
        public = {'type': 'stream', **{key: frame[key] for key in
                  ('session_id', 'run_id', 'request_id', 'phase', 'text') if key in frame}}
        for connection in tuple(self._connections.get(session_id, ())):
            if session_id not in connection.sessions or (connection.replaying and connection.replay_session == session_id):
                continue
            try:
                connection.stream_queue.put_nowait(public)
            except asyncio.QueueFull:
                # Abandon an incomplete preview rather than blocking generation.
                # Clients retain the authoritative final message/reconnect path.
                while not connection.stream_queue.empty():
                    connection.stream_queue.get_nowait()
                connection.stream_queue.put_nowait({**public, 'phase': 'error', 'text': ''})

    async def _authorize_connection(self, connection, session_id=None):
        user_id = await self.service.authenticate(connection.token)
        if user_id != connection.user_id:
            raise PermissionError('Connection identity changed')
        await self.service.authorize(user_id, session_id or connection.session_id)

    async def publish(self, session_id, frame):
        async with self._lock(session_id):
            for connection in tuple(self._connections.get(session_id, ())):
                try:
                    if connection.replaying and connection.replay_session == session_id:
                        connection.pending.put_nowait(frame)
                    else:
                        await self._enqueue_committed(connection, session_id, frame)
                except Exception:
                    # The durable history is the replay source; disconnect this
                    # subscriber rather than dropping selected messages silently.
                    self._connections[session_id].discard(connection)
                    if connection.sender:
                        connection.sender.cancel()
                    if connection.handler:
                        connection.handler.cancel()

    async def _enqueue_committed(self, connection, session_id, frame, *, wait=False):
        async def enqueue(value):
            if wait:
                await asyncio.wait_for(connection.queue.put(value), 10)
            else:
                connection.queue.put_nowait(value)
        if frame.get('type') != 'message' or session_id not in connection.cursors:
            await enqueue(frame)
            return
        cursor, target = connection.cursors[session_id], frame['sequence']
        if target <= cursor:
            return
        # Commits and callback completion may race. A higher live sequence must
        # first deliver every earlier persisted public message, or a reconnect
        # after that sequence could permanently skip a delayed callback's reply.
        while True:
            # This is an internal projection, not delivery. The sender checks
            # credentials/membership immediately before writing each frame; an
            # external auth backend must never stall the producer's checkpoint.
            page = await asyncio.wait_for(self.service.application.history(
                session_id, after=cursor, until=target, limit=500), 10)
            for message in page['messages']:
                await enqueue(message)
            cursor = page['cursor']
            connection.cursors[session_id] = cursor
            if not page['has_more']:
                break

    async def subscribe(self, connection, session_id, *, after=0, recent=False):
        await self.service.authorize(connection.user_id, session_id)
        if session_id in connection.sessions:
            return
        if len(connection.sessions) >= self.max_subscriptions:
            raise asyncio.QueueFull
        if type(after) is not int or not 0 <= after < 2**63:
            raise ValueError('after_sequence must be a nonnegative integer')
        connection.managed = True
        connection.replaying, connection.replay_session = True, session_id
        async with self._lock(session_id):
            connection.sessions.add(session_id)
            self._connections.setdefault(session_id, set()).add(connection)
        try:
            # Register before snapshot; bounded pending frames follow ready.
            page = (await self.service.message_page(connection.user_id, session_id, limit=50) if recent else
                    await self.service.history(connection.user_id, session_id, after=after, limit=500))
            through = page['through']
            while True:
                for message in page['messages']:
                    await asyncio.wait_for(connection.queue.put(message), 10)
                if recent or not page['has_more']:
                    break
                page = await self.service.history(connection.user_id, session_id,
                                                  after=page['cursor'], limit=500, until=through)
            connection.cursors[session_id] = through
            await asyncio.wait_for(connection.queue.put({'type': 'ready', 'session_id': session_id,
                                                         'cursor': through, **({'has_more': page['has_more']} if recent else {})}), 10)
            while not connection.pending.empty():
                await self._enqueue_committed(connection, session_id, connection.pending.get_nowait(), wait=True)
        except BaseException:
            await self.unsubscribe(connection, session_id)
            raise
        finally:
            connection.replaying, connection.replay_session = False, None

    async def unsubscribe(self, connection, session_id):
        async with self._lock(session_id):
            connection.sessions.discard(session_id)
            connection.cursors.pop(session_id, None)
            group = self._connections.get(session_id)
            if group is not None:
                group.discard(connection)
                if not group:
                    self._connections.pop(session_id, None)

    async def send(self, message):
        if not message.event_id or not message.sequence or not message.session_id:
            raise ValueError('Web replies require a committed event identity')
        event = await self.service.store.event_by_id(message.session_id, message.event_id)
        if event is None or event['type'] != 'bot_utter':
            raise ValueError('Web reply is not a persisted bot utterance')
        await self.publish(message.session_id, message_record(message.session_id, event))

    @staticmethod
    def _frame(raw):
        if not isinstance(raw, str) or len(raw.encode("utf-8")) > 256 * 1024:
            raise ValueError('Expected a JSON text frame up to 256 KiB')
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError('Expected a JSON object')
        return value

    @staticmethod
    def _error(error):
        from cota.application import ApplicationUnavailable
        from cota.inputs import InputConflict
        from cota.runtime.pi_runtime import RunInProgress

        if isinstance(error, PermissionError):
            code, message = 'unauthorized', 'Conversation access expired or was revoked'
        elif isinstance(error, ApplicationUnavailable):
            code, message = 'not_ready', 'Application is not ready'
        elif isinstance(error, asyncio.QueueFull):
            code, message = 'busy', 'Please retry later'
        elif isinstance(error, InputConflict):
            code, message = 'invalid_request', 'Message identity conflicts with an existing input'
        elif isinstance(error, RunInProgress):
            code, message = 'run_in_progress', 'Conversation execution is already in progress'
        elif isinstance(error, FileNotFoundError):
            code, message = 'not_found', 'File not found in this conversation'
        elif isinstance(error, ValueError):
            code, message = 'invalid_request', str(error)
        elif isinstance(error, asyncio.TimeoutError):
            code, message = 'invalid_request', 'Request timed out'
        else:
            logger.exception('WebSocket request failed')
            code, message = 'internal_error', 'Internal server error'
        return {'type': 'error', 'code': code, 'message': message}

    async def handle(self, socket):
        if not self._running:
            await self._close(socket)
            return
        if len(self._handlers) >= self.max_connections:
            with suppress(Exception):
                await asyncio.wait_for(socket.send(json.dumps(self._error(asyncio.QueueFull()))), 2)
            await self._close(socket)
            return
        handler = asyncio.current_task()
        self._handlers.add(handler)
        connection, session_id, user_id = None, None, None
        counted_user = False
        try:
            hello = self._frame(await asyncio.wait_for(socket.recv(), 10))
            if hello.get('type') != 'resume':
                raise ValueError('First frame must be resume')
            user_id = await asyncio.wait_for(self.service.authenticate(hello.get('token')), 10)
            if self._users.get(user_id, 0) >= self.max_connections_per_user:
                raise asyncio.QueueFull
            self._users[user_id] = self._users.get(user_id, 0) + 1
            counted_user = True
            session_id = hello.get('session_id')
            await asyncio.wait_for(self.service.authorize(user_id, session_id), 10)
            after = hello.get('after_sequence', 0)
            connection = Connection(socket, user_id=user_id, session_id=session_id, token=hello.get('token'),
                                    handler=handler)
            connection.sender = asyncio.create_task(self._send_loop(connection))
            await self.subscribe(connection, session_id, after=after, recent=hello.get('recent') is True)
            while True:
                raw = await socket.recv()
                if raw is None:
                    break
                frame = self._frame(raw)
                try:
                    target = frame.get('session_id', connection.session_id)
                    await asyncio.wait_for(self._authorize_connection(connection, target), 10)
                    if frame.get('type') == 'subscribe':
                        await self.subscribe(connection, target, after=frame.get('after_sequence', 0), recent=frame.get('recent') is True)
                        continue
                    if frame.get('type') == 'unsubscribe':
                        await self.unsubscribe(connection, target)
                        continue
                    if frame.get('type') != 'send':
                        raise ValueError('Expected send frame')
                    if any(key in frame for key in ('sender_id', 'user_id', 'sender_name', 'conversation_type')):
                        raise ValueError('Identity is bound by resume')
                    if target not in connection.sessions:
                        raise ValueError('Subscribe to the conversation before sending')
                    receipt = await self.service.submit(user_id, target, frame.get('message_id'), frame.get('text', ''),
                                                        mentioned=frame.get('mentioned', False), reply_to=frame.get('reply_to'),
                                                        attachments=frame.get('attachments'))
                    connection.queue.put_nowait({'type': 'receipt', **receipt})
                except PermissionError:
                    raise
                except Exception as error:
                    connection.queue.put_nowait({**self._error(error), 'message_id': frame.get('message_id'), 'session_id': target})
        except asyncio.CancelledError:
            raise
        except Exception as error:
            frame = self._error(error)
            if connection:
                # Only one writer may use the socket, including error responses.
                connection.sender.cancel()
                await asyncio.gather(connection.sender, return_exceptions=True)
            with suppress(Exception):
                await asyncio.wait_for(socket.send(json.dumps(frame)), 2)
        finally:
            # stop must await cleanup already in progress, not inject another
            # cancellation after publication has forgotten this connection.
            self._closing_handlers.add(handler)
            try:
                if connection:
                    for subscribed in tuple(connection.sessions):
                        await self.unsubscribe(connection, subscribed)
                    connection.sender.cancel()
                    await asyncio.gather(connection.sender, return_exceptions=True)
                await self._close(socket)
            finally:
                if counted_user:
                    self._users[user_id] -= 1
                    if not self._users[user_id]:
                        self._users.pop(user_id)
                self._closing_handlers.discard(handler)
                self._handlers.discard(handler)


class TransportFactory:
    @classmethod
    def create(cls, transport_type, config, bus):
        if transport_type not in ('auto', 'websocket'):
            raise ValueError('Web serving currently supports transport=websocket only')
        return WebSocketTransport(config, bus)

    @classmethod
    def get_available_transports(cls):
        return ['websocket']
