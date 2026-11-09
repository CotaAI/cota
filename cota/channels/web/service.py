"""Web projections and subscriptions over trusted application identities.

This layer never replays an interrupted model/tool run. Socket lifetimes don't
own executions: disconnecting only unsubscribes the client from live output.
"""
import asyncio
import logging
from weakref import WeakValueDictionary

from cota.channels.events import InboundMessage
from cota.conversation import message_record

logger = logging.getLogger(__name__)


class WebService:
    def __init__(self, application, *, access):
        self.application = application
        self.agent, self.runner = application.agent, application.runner
        self.store = application.store
        self.access = access
        self._locks = WeakValueDictionary()
        self._observed = set()
        self._watchers = set()
        self.transport = None

    def lock(self, session_id):
        lock = self._locks.get(session_id)
        if lock is None:
            lock = self._locks[session_id] = asyncio.Lock()
        return lock

    async def authenticate(self, token):
        return await self.access.authenticate(token)

    async def authorize(self, user_id, session_id):
        await self.access.authorize(user_id, session_id)

    async def history(self, user_id, session_id, *, after=0, limit=100, until=None):
        await self.authorize(user_id, session_id)
        return await self.application.history(session_id, after=after, limit=limit, until=until)

    async def message_page(self, user_id, session_id, *, before=None, limit=50):
        await self.authorize(user_id, session_id)
        return await self.application.message_page(session_id, before=before, limit=limit)

    async def summary(self, user_id, session_id, *, after=0):
        await self.authorize(user_id, session_id)
        return await self.application.conversation_summary(session_id, after=after, exclude_sender=user_id)

    async def submit(self, user_id, session_id, message_id=None, text=None, *, mentioned=False, reply_to=None):
        await self.authorize(user_id, session_id)
        if not isinstance(text, str) or not text.strip() or len(text) > 32768:
            raise ValueError('text must contain 1–32768 characters')
        inbound = InboundMessage(channel='web', sender_id=user_id, chat_id=session_id,
                                 session_key_override=session_id, content=text, message_id=message_id,
                                 mentioned=mentioned, reply_to=reply_to,
                                 conversation_type=(getattr(self.agent, 'dialogue', None) or {}).get('mode', 'direct'))
        async def input_committed(event):
            if self.transport:
                await self.transport.publish(session_id, message_record(session_id, event))
        async def output_committed(reply):
            if self.transport:
                event = await self.store.event_by_id(session_id, reply['event_id'])
                await self.transport.publish(session_id, message_record(session_id, event))
        # This lock only coordinates receipt notifications on Web connections.
        # Store/Runner own actual admission and deduplication for every channel.
        async with self.lock(session_id):
            submission = await self.application.submit_message(
                inbound, on_input=input_committed, on_reply=output_committed)
            future = submission.future
            receipt = await submission.receipt()
            if receipt is None:
                # A pre-commit failure may already have released its live claim.
                # The observer below still reports the result to this connection.
                receipt = {'session_id': session_id, 'message_id': inbound.message_id,
                           'status': 'queued', 'error': None}
            if future not in self._observed:
                self._observed.add(future)
                watcher = asyncio.create_task(self._observe(session_id, inbound.message_id, future))
                self._watchers.add(watcher)
                watcher.add_done_callback(self._watchers.discard)
            return {**receipt, 'duplicate': submission.duplicate}

    async def _observe(self, session_id, message_id, future):
        try:
            status, error = 'completed', None
            try:
                status = await asyncio.shield(future) or 'completed'
            except asyncio.CancelledError:
                if asyncio.current_task().cancelling():
                    # Web shutdown detaches observation, not the executor.
                    return
                status, error = 'interrupted', 'execution_cancelled'
            except Exception:
                status, error = 'failed', 'execution_failed'
                logger.exception('Web execution failed for session %s', session_id)
            receipt = await self.application.receipt(session_id, message_id)
            if receipt is None:
                # No durable user event means no persisted execution to recover.
                # Still finish the live client's request; do not create a table/event.
                receipt = {'session_id': session_id, 'message_id': message_id,
                           'status': status, 'error': error}
            from cota.application import completion_receipt
            receipt = completion_receipt(receipt, status, error)
            if self.transport and receipt:
                await self.transport.publish(session_id, {'type': 'receipt', **receipt})
        except Exception:
            logger.exception('Could not publish Web submission receipt')
        finally:
            self._observed.discard(future)

    async def receipt(self, user_id, session_id, message_id):
        await self.authorize(user_id, session_id)
        return await self.application.receipt(session_id, message_id)

    async def close(self):
        # Runner stops first. Its bounded shutdown may leave a stalled executor;
        # never turn a delivery observer into another unbounded shutdown wait.
        watchers = list(self._watchers)
        for watcher in watchers:
            watcher.cancel()
        if watchers:
            await asyncio.gather(*watchers, return_exceptions=True)
