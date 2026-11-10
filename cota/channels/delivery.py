"""Bounded delivery of committed replies, independent of agent execution.

One dispatcher owns a Store. Pending rows survive cancellation; a successful
send followed by a crash before acknowledgment may be sent again on restart.
Channels should use the stable event_id as their provider idempotency key.
"""
import asyncio
import math
import time

from loguru import logger

from .events import OutboundMessage


class DeliveryDispatcher:
    def __init__(self, store, channels, *, concurrency=8, poll_interval=.25,
                 send_timeout=10, max_attempts=8, retry_delay=1,
                 max_retry_delay=300, shutdown_timeout=5):
        for name, value in (('concurrency', concurrency), ('max_attempts', max_attempts)):
            if type(value) is not int or value < 1:
                raise ValueError(f'{name} must be a positive integer')
        for name, value in (('poll_interval', poll_interval), ('send_timeout', send_timeout),
                            ('retry_delay', retry_delay), ('max_retry_delay', max_retry_delay),
                            ('shutdown_timeout', shutdown_timeout)):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError(f'{name} must be finite and positive')
        self.store, self.channels = store, channels
        self.concurrency, self.max_attempts = concurrency, max_attempts
        self.poll_interval, self.send_timeout = poll_interval, send_timeout
        self.retry_delay, self.max_retry_delay = retry_delay, max_retry_delay
        self.shutdown_timeout = shutdown_timeout
        self._task = None
        self._sends = {}
        self._closing = False
        self._wake = asyncio.Event()

    async def start(self):
        if self._task is None:
            self._closing = False
            self._task = asyncio.create_task(self._run())

    async def stop(self):
        if self._task is None:
            return
        self._closing = True
        self._wake.set()
        # Continue ready work briefly, including replies committed just before
        # shutdown. Future backoffs and disabled targets remain durable.
        done, pending = await asyncio.wait([self._task], timeout=self.shutdown_timeout)
        tasks = list(self._sends.values()) + list(pending)
        for task in tasks:
            task.cancel()
        if tasks:
            finished, stalled = await asyncio.wait(tasks, timeout=.1)
            done |= finished
            for task in stalled:
                task.add_done_callback(self._observe)
            if stalled:
                logger.error('{} delivery tasks did not acknowledge cancellation', len(stalled))
        for task in done:
            self._observe(task)
        self._task = None

    @staticmethod
    def _observe(task):
        if not task.cancelled() and task.exception() is not None:
            logger.error('Delivery task failed ({})', type(task.exception()).__name__)

    async def _run(self):
        while True:
            self._wake.clear()
            try:
                targets = {name: channel.delivery_scope for name, channel in self.channels.items()
                           if getattr(channel, 'durable_delivery', False)}
                if len(self._sends) < self.concurrency:
                    rows = await self.store.due_deliveries(targets, now=time.time(), limit=min(1000, self.concurrency * 2))
                    for row in rows:
                        key = (row['session_id'], row['event_id'])
                        if key in self._sends:
                            continue
                        if len(self._sends) >= self.concurrency:
                            break
                        task = asyncio.create_task(self._send(row, self.channels[row['channel']]))
                        self._sends[key] = task
                        task.add_done_callback(lambda done, key=key: self._sent(key, done))
                if self._closing and not self._sends:
                    return
            except Exception as error:
                logger.error('Cannot read pending deliveries ({})', type(error).__name__)
            try:
                await asyncio.wait_for(self._wake.wait(), self.poll_interval)
            except asyncio.TimeoutError:
                pass

    def _sent(self, key, task):
        self._sends.pop(key, None)
        self._observe(task)
        self._wake.set()

    async def _send(self, row, channel):
        sid, eid = row['session_id'], row['event_id']
        if row['attempts'] >= self.max_attempts:
            # An interrupted send may have reached the provider. Restart must
            # not reset its budget or send forever without operator review.
            await self._record(sid, eid, 'AttemptsExhausted', None)
            logger.warning('Reply {} delivery failed (AttemptsExhausted)', eid)
            return
        row = await self.store.begin_delivery(sid, eid)
        if row is None:
            return
        error_type, retry_at = None, None
        try:
            event = await self.store.event_by_id(sid, eid)
            if event is None or event['type'] != 'bot_utter':
                raise ValueError('Delivery has no committed bot reply')
            message = OutboundMessage(
                channel=row['channel'], chat_id=row['chat_id'], content=event['payload']['text'],
                metadata=event['payload'].get('metadata') or {},
                attachments=event['payload'].get('attachments', []),
                event_id=eid, sequence=event['sequence'], session_id=sid)
            if message.attachments and not getattr(channel, 'supports_attachments', False):
                from cota.files import UnsupportedAttachments
                raise UnsupportedAttachments('Channel does not support attachments')
            await asyncio.wait_for(channel.send(message), self.send_timeout)
        except Exception as error:
            error_type = type(error).__name__
            from cota.files import UnsupportedAttachments
            if row['attempts'] < self.max_attempts and not isinstance(error, UnsupportedAttachments):
                delay = min(self.max_retry_delay, self.retry_delay * 2 ** min(row['attempts'] - 1, 30))
                retry_at = time.time() + delay
            logger.warning('Reply {} delivery {} ({})', eid,
                           'will retry' if retry_at is not None else 'failed', error_type)
        await self._record(sid, eid, error_type, retry_at)

    async def _record(self, sid, eid, error_type, retry_at):
        # Do not send again if only the database acknowledgment failed. Keep
        # retrying that write while alive; shutdown leaves an ambiguous pending
        # row recoverable with the same provider idempotency key.
        while True:
            try:
                await self.store.finish_delivery(sid, eid, error=error_type, retry_at=retry_at)
                return
            except Exception as error:
                logger.error('Cannot record delivery {} outcome ({})', eid, type(error).__name__)
                await asyncio.sleep(min(self.poll_interval, 1))
