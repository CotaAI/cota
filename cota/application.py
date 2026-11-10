"""Trusted application API over the existing scheduler and durable event store.

Authentication and conversation membership belong to the caller. A session can
contain several users; its latest user identity is never an ownership rule.
"""
import asyncio
from dataclasses import dataclass, field, replace
from weakref import WeakValueDictionary

from cota.channels.events import InboundMessage
from cota.channels.runner import ChannelRunner
from cota.conversation import message_record
from cota.events import UserUtterEvent
from cota.inputs import input_event_id, message_id as normalize_message_id
from cota.processor import Processor


class ApplicationUnavailable(RuntimeError):
    """Admission is closed because the application has not started or is stopping."""


def _identifier(name, value):
    if not isinstance(value, str) or not value.strip() or len(value) > 255:
        raise ValueError(f'{name} must be a nonempty string of at most 255 characters')
    return value


def completion_receipt(receipt, status, error):
    """Overlay live pre-run failures without inventing persisted run facts."""
    if error and receipt.get('status') in ('recorded', 'queued', 'running'):
        return {**receipt, 'status': status, 'error': error}
    return receipt


@dataclass
class Submission:
    """An admitted input. Cancelling wait() does not cancel its execution.

    ``future`` exposes the scheduler result for transport observers, which must
    also shield their awaits. Use wait() for the stable application result.
    """
    session_id: str
    message_id: str
    future: asyncio.Future
    duplicate: bool
    _application: 'Application' = field(repr=False)

    async def receipt(self):
        return await self._application.receipt(self.session_id, self.message_id)

    async def wait(self):
        status, error = 'completed', None
        try:
            status = await asyncio.shield(self.future) or 'completed'
        except asyncio.CancelledError:
            if asyncio.current_task().cancelling():
                raise
            status, error = 'interrupted', 'execution_cancelled'
        except Exception:
            status, error = 'failed', 'execution_failed'
        receipt = await self.receipt()
        if receipt is None:
            # Pre-commit failures and queued cancellation have no durable facts.
            receipt = {'session_id': self.session_id, 'message_id': self.message_id,
                       'status': status, 'error': error}
        receipt = completion_receipt(receipt, status, error)
        messages = []
        event = await self._application.store.event_by_id(self.session_id, input_event_id(self.message_id))
        if event is not None:
            messages.append(message_record(self.session_id, event))
        run_id = receipt.get('run_id')
        if run_id:
            cursor = 0
            while True:
                events = await self._application.store.events(self.session_id, run_id=run_id,
                                                              after_sequence=cursor, limit=1000)
                messages.extend(message_record(self.session_id, e) for e in events if e['type'] == 'bot_utter')
                if len(events) < 1000:
                    break
                cursor = events[-1]['sequence']
        return {'receipt': receipt, 'messages': messages}


class Application:
    """One long-lived owner of an Agent, its scheduler and channel lifecycle.

    ``channels`` maps channel names to their configuration. Direct SDK use
    needs no channels; ``channel_limits`` optionally controls outbound delivery.
    """
    def __init__(self, agent, channels=None, concurrency=8, max_pending=256, *, channel_limits=None,
                 channel_registry=None):
        self.agent = agent
        dialogue = getattr(agent, 'dialogue', None) or {}
        mode = dialogue.get('mode', 'direct')
        if mode not in ('direct', 'group') or dialogue.get('response', 'passive') not in ('passive', 'proactive'):
            raise ValueError('dialogue requires mode=direct/group and response=passive/proactive')
        channels = {name: dict(settings) for name, settings in (channels or {}).items()}
        self.runner = ChannelRunner({'channels': channels or {}, 'channel_limits': channel_limits or {}},
                                    agent, message_handler=self._execute,
                                    concurrency=concurrency, max_pending=max_pending,
                                    channel_registry=channel_registry)
        self.store = self.runner.store
        self.agent.store = self.store
        self._started = False
        self._starting = False
        self._closed = False
        self._lifecycle_lock = asyncio.Lock()
        self._close_task = None
        self._recovery_task = None
        self._submission_locks = WeakValueDictionary()
        self._channel_ready = asyncio.Event()
        from cota.group import GroupConversation
        self.group = GroupConversation(self)
        self.runner.message_receiver = self._receive_channel

    async def _receive_channel(self, inbound):
        # A listener may deliver immediately after its own start() returns,
        # while other adapters are still starting. Never lose that first input.
        if self._closed or (not self._starting and not self._started):
            raise ApplicationUnavailable('Application is not accepting messages')
        await self._channel_ready.wait()
        return await self.submit_message(inbound)

    def prepare_channels(self):
        """Prepare adapters for optional HTTP mounting before start()."""
        if self._closed:
            raise RuntimeError('Application is closed')
        return self.runner.prepare_channels()

    async def start(self, configure=None):
        try:
            async with self._lifecycle_lock:
                if self._closed:
                    raise RuntimeError('A closed application cannot be restarted')
                if self._started:
                    return self
                self._starting = True
                try:
                    await self.runner.start(configure=configure)
                finally:
                    self._starting = False
                self._started = True
                self._channel_ready.set()
                self._recovery_task = asyncio.create_task(self._recover_unstarted())
        except BaseException:
            # Teardown owns its lifetime even if startup's caller is cancelled
            # again while cleaning up partially initialized channels.
            await self.close()
            raise
        return self

    async def close(self):
        # Mark admission closed before the first await. All callers share one
        # retained task; cancelling a waiter cannot abandon channel cleanup.
        self._closed = True
        self._channel_ready.set()  # Release listeners on partial startup failure.
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._teardown())
        await asyncio.shield(self._close_task)

    async def _teardown(self):
        async with self._lifecycle_lock:
            try:
                if self._recovery_task is not None:
                    self._recovery_task.cancel()
                    await asyncio.gather(self._recovery_task, return_exceptions=True)
                await self.group.close()
                await self.runner.stop(graceful=self._started)
            finally:
                try:
                    await self.group.drain()
                finally:
                    await self.agent.cleanup()

    async def __aenter__(self):
        return await self.start()

    async def __aexit__(self, exc_type, exc_value, traceback):
        await self.close()

    @property
    def accepting_messages(self):
        return self._started and not self._closed and self.runner._running

    async def submit(self, *, user_id, session_id, text='', message_id=None, mentioned=False, sender_name=None, reply_to=None,
                     attachments=None):
        _identifier('user_id', user_id)
        _identifier('session_id', session_id)
        return await self.submit_message(InboundMessage(
            channel='application', sender_id=user_id, chat_id=session_id, content=text,
            session_key_override=session_id, message_id=message_id, mentioned=mentioned,
            sender_name=sender_name, reply_to=reply_to, attachments=[] if attachments is None else attachments))

    async def submit_message(self, inbound, on_input=None, on_reply=None):
        if not isinstance(inbound, InboundMessage):
            raise TypeError('inbound must be an InboundMessage')
        _identifier('user_id', inbound.sender_id)
        _identifier('session_id', inbound.session_key)
        normalize_message_id(inbound.message_id)
        if (not isinstance(inbound.content, str) or len(inbound.content) > 32768
                or not inbound.content.strip() and not inbound.attachments):
            raise ValueError('Provide text (up to 32768 characters) or attachments')
        if inbound.attachments:
            references = await asyncio.to_thread(self.agent.files.references, inbound.session_key,
                                                  [item['id'] for item in inbound.attachments])
            if references != inbound.attachments:
                raise ValueError('Attachment references do not match stored files')
        if not self.accepting_messages:
            raise ApplicationUnavailable('Application is not accepting messages')
        mode = (getattr(self.agent, 'dialogue', None) or {}).get('mode', 'direct')
        if inbound.conversation_type is not None and inbound.conversation_type != mode:
            raise ValueError('Inbound conversation type does not match dialogue.mode')
        inbound = replace(inbound, conversation_type=mode)
        if mode == 'group':
            return await self.group.receive(inbound, on_input, on_reply)
        from cota.group import validate_session_mode
        lock = self._submission_locks.get(inbound.session_key)
        if lock is None:
            lock = self._submission_locks[inbound.session_key] = asyncio.Lock()
        async def execute(message):
            return await self._execute(message, on_reply=on_reply)
        async def record():
            await validate_session_mode(self.store, inbound.session_key, mode)
            metadata = {'sender': 'user', 'sender_id': inbound.sender_id,
                        'channel': inbound.channel, 'chat_id': inbound.chat_id,
                        'media': inbound.media, 'channel_metadata': inbound.metadata,
                        'received_at': inbound.timestamp.isoformat(),
                        'message_id': inbound.message_id, 'accepted': True}
            event = UserUtterEvent(event_id=input_event_id(inbound.message_id),
                                   text=inbound.content, metadata=metadata, attachments=inbound.attachments)
            committed = await self.store.append_conversation_event(inbound.session_key, event, agent=self.agent)
            if on_input is not None:
                try:
                    await on_input(committed)
                except Exception:
                    pass  # publication failure cannot revoke accepted input
        async with lock:
            previous, existing = await self.store.check_input(inbound)
            if previous is None or (previous['status'] == 'recorded' and existing is None):
                await self._recover_session(inbound.session_key, exclude=inbound.message_id)
            future = await self.runner.submit(inbound, handler=execute, recorded=True,
                                               prepare=record if previous is None else None)
            return Submission(inbound.session_key, inbound.message_id, future, previous is not None, self)

    @staticmethod
    def _recorded_inbound(event):
        metadata = event['payload']['metadata']
        return InboundMessage(channel=metadata.get('channel', 'application'),
            sender_id=metadata['sender_id'], chat_id=metadata.get('chat_id', event['session_id']),
            content=event['payload']['text'], media=metadata.get('media', []),
            metadata=metadata.get('channel_metadata', {}), session_key_override=event['session_id'],
            message_id=metadata['message_id'], conversation_type='direct',
            attachments=event['payload'].get('attachments', []))

    async def _recover_session(self, session_id, exclude=None):
        # Schedule old committed work before a newly arriving turn in this room.
        # The session admission lock owned by Application preserves FIFO even
        # when startup recovery and external submit race.
        after = None
        while True:
            events = await self.store.unstarted_inputs(session_id=session_id, after=after,
                                                        limit=self.runner.max_pending)
            for event in events:
                if event['payload']['metadata']['message_id'] == exclude:
                    return
                await self.runner.submit(self._recorded_inbound(event), handler=self._execute, recorded=True)
            if len(events) < self.runner.max_pending:
                return
            after = (session_id, events[-1]['sequence'])

    async def _recover_unstarted(self):
        """One bounded startup sweep. Started runs always require reconciliation."""
        import logging
        from cota.runtime.pi_runtime import RunInProgress
        if (getattr(self.agent, 'dialogue', None) or {}).get('mode', 'direct') != 'direct':
            return
        after = None
        try:
            while self.accepting_messages:
                events = await self.store.unstarted_inputs(after=after, limit=min(100, self.runner.max_pending))
                if not events:
                    return
                for event in events:
                    sid = event['session_id']
                    lock = self._submission_locks.get(sid)
                    if lock is None:
                        lock = self._submission_locks[sid] = asyncio.Lock()
                    while self.accepting_messages:
                        try:
                            async with lock:
                                await self.runner.submit(self._recorded_inbound(event), handler=self._execute, recorded=True)
                            break
                        except asyncio.QueueFull:
                            await self.runner._capacity.wait()
                        except RunInProgress:
                            break  # orphaned run may have performed effects; never replay it
                    after = (sid, event['sequence'])
        except asyncio.CancelledError:
            raise
        except Exception:
            logging.getLogger(__name__).exception('Unstarted input recovery stopped')

    def _processor(self, inbound, on_input=None, on_reply=None):
        processor = Processor(self.agent, self.store, self.runner.message_bus, service_mode=True)
        channel = self.runner.get_channel(inbound.channel)
        if on_reply is None and getattr(channel, 'durable_delivery', False):
            processor.set_delivery_target({'channel': inbound.channel,
                                           'scope': channel.delivery_scope,
                                           'chat_id': inbound.chat_id})
        if on_input is not None:
            processor.set_input_callback(on_input)
        if on_reply is not None:
            processor.set_channel_callback(on_reply)
        elif inbound.channel == 'application':
            async def reply_committed(_reply):
                # SDK callers read committed replies through Submission.wait().
                pass
            processor.set_channel_callback(reply_committed)
        return processor

    async def _execute(self, inbound, on_input=None, on_reply=None):
        processor = self._processor(inbound, on_input, on_reply)
        return await processor.handle_recorded_message(inbound)

    async def _execute_group(self, inbound, reason, on_reply, *, expected_sequence=None):
        processor = self._processor(inbound, on_reply=on_reply)
        return await processor.handle_group_message(inbound, reason=reason, expected_sequence=expected_sequence)

    async def delivery_status(self, session_id, event_id):
        """Trusted transport receipt; delivered means provider accepted, not read."""
        _identifier('session_id', session_id)
        _identifier('event_id', event_id)
        return await self.store.delivery(session_id, event_id)

    async def retry_delivery(self, session_id, event_id):
        """Retry a failed saved reply. Never rerun its input/model/tools."""
        _identifier('session_id', session_id)
        _identifier('event_id', event_id)
        return await self.store.retry_delivery(session_id, event_id)

    async def receipt(self, session_id, message_id):
        _identifier('session_id', session_id)
        _identifier('message_id', message_id)
        receipt = await self.store.input_receipt(session_id, message_id)
        if receipt and receipt.get('error'):
            receipt = {**receipt, 'error': ('execution_cancelled' if receipt['status'] == 'interrupted'
                                          else 'execution_failed')}
        return receipt

    async def history(self, session_id, after=0, limit=100, until=None):
        _identifier('session_id', session_id)
        if (type(after) is not int or after < 0 or type(limit) is not int or not 1 <= limit <= 500
                or (until is not None and (type(until) is not int or until < 0))):
            raise ValueError('Invalid history cursor or limit')
        metadata = await self.store.session_metadata(session_id)
        last = (metadata or {}).get('last_sequence', 0)
        if until is not None:
            last = min(last, until)
        if after > last:
            raise ValueError('History cursor is ahead of this conversation')
        events = await self.store.events(session_id, after_sequence=after, limit=limit)
        events = [event for event in events if event['sequence'] <= last]
        cursor = events[-1]['sequence'] if events else after
        return {'messages': [message_record(session_id, e) for e in events
                             if e['type'] in ('user_utter', 'bot_utter')],
                'cursor': cursor, 'through': last, 'has_more': cursor < last}

    async def message_page(self, session_id, before=None, limit=50):
        """Recent public messages, or older messages before an exclusive cursor."""
        _identifier('session_id', session_id)
        if (type(limit) is not int or not 1 <= limit <= 500 or
                (before is not None and (type(before) is not int or before < 0))):
            raise ValueError('Invalid history cursor or limit')
        metadata = await self.store.session_metadata(session_id)
        through = (metadata or {}).get('last_sequence', 0)
        events = await self.store._query_events(session_id, kinds=('user_utter', 'bot_utter'),
            before_sequence=min(before, through + 1) if before is not None else through + 1,
            descending=True, limit=limit + 1)
        messages = [message_record(session_id, event) for event in reversed(events[:limit])]
        return {'messages': messages, 'through': through,
                'cursor': messages[0]['sequence'] if messages else 0, 'has_more': len(events) > limit}

    async def conversation_summary(self, session_id, after=0, exclude_sender=None):
        """Public preview and unread message count; caller owns access/read state."""
        _identifier('session_id', session_id)
        if type(after) is not int or after < 0:
            raise ValueError('Invalid history cursor')
        if exclude_sender is not None:
            _identifier('exclude_sender', exclude_sender)
        metadata = await self.store.session_metadata(session_id)
        through = (metadata or {}).get('last_sequence', 0)
        events = await self.store._query_events(session_id, kinds=('user_utter', 'bot_utter'),
            before_sequence=through + 1, descending=True, limit=1)
        last = message_record(session_id, events[0]) if events else None
        unread = await self.store.message_count(session_id, after=after, through=through,
                                                exclude_sender=exclude_sender)
        return {'last_message': last, 'last_active': last['timestamp'] if last else None,
                'unread': unread, 'through': through}
