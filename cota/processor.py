"""Processor — message handling and agent runtime orchestration.

The Processor is the entry point for all user messages. It:
1. Records user messages as Events in the DST
2. Delegates to PiAgentRuntime for bot response generation
3. Sends results back via Channel

Supports both legacy Channel and new MessageBus framework.
"""

import logging
import asyncio
from functools import wraps
from inspect import signature
from typing import Optional, Text, Callable, Any, TYPE_CHECKING

from cota.channels.events import InboundMessage, OutboundMessage
from cota.channels.queue import MessageBus
from cota.message.message import Message
from cota.store import Store
from cota.dst import DST
from cota.events import UserUtterEvent
from cota.inputs import input_event_id

if TYPE_CHECKING:
    from cota.agent import Agent

logger = logging.getLogger(__name__)


def _serialized_turn(method):
    method_signature = signature(method)
    input_name = list(method_signature.parameters)[1]
    @wraps(method)
    async def wrapped(self, *args, **kwargs):
        if self.agent.dialogue.get('mode', 'direct') == 'group':
            raise ValueError('Group messages require Application.submit_message')
        message = method_signature.bind(self, *args, **kwargs).arguments[input_name]
        key = (message if isinstance(message, str) else
               message.session_key if isinstance(message, InboundMessage) else message.session_id)
        async with self._turn_lock, self.store.session_lock(key):
            if isinstance(message, str):
                return await method(self, *args, **kwargs)
            receipt, _ = await self.store.check_input(message, durable_only=True)
            if receipt is not None:
                self.dst = await self.get_tracker(key)
                return receipt['status']
            self.store.start_input(message)
            try:
                await method(self, *args, **kwargs)
            finally:
                self.store.finish_input(message, processor=True)
            receipt = await self.store.input_receipt(key, message.message_id)
            return receipt['status'] if receipt else None
    return wrapped


class Processor:
    def __init__(
        self,
        agent: "Agent",
        store: Store,
        message_bus: Optional[MessageBus] = None,
        service_mode: bool = False,
    ):
        self.agent = agent
        self.store = store
        self.dst = None
        self.message_bus = message_bus
        self.service_mode = service_mode
        self._channel_callback: Optional[Callable] = None
        self._input_callback: Optional[Callable] = None
        self._stream_callback: Optional[Callable] = None
        self._turn_lock = asyncio.Lock()
        self._delivery_target = None
        self._detached_execution = False
        self._expected_sequence = None

    def set_delivery_target(self, target):
        """Bind a trusted transport target for atomic reply/outbox checkpoints."""
        from cota.delivery_store import validate_target
        self._delivery_target = validate_target(target)

    def set_message_bus(self, bus: MessageBus) -> None:
        """Set the message bus for the new Channel framework"""
        self.message_bus = bus

    def set_channel_callback(self, callback: Callable) -> None:
        """Set the channel callback for sending responses"""
        self._channel_callback = callback

    def set_stream_callback(self, callback: Callable) -> None:
        """Observe transient previews independently of durable reply delivery."""
        self._stream_callback = callback

    def set_input_callback(self, callback: Callable) -> None:
        """Observe the current inbound user event after its durable commit."""
        self._input_callback = callback

    @_serialized_turn
    async def handle_message(
        self,
        message: Message,
        channel: Optional[Any] = None,
    ):
        """Handle incoming message (legacy Channel interface)"""
        logger.info(
            f"Processor.handle_message: session={message.session_id}, "
            f"sender={message.sender_id}, receiver={message.receiver}"
        )

        if self.agent.dialogue.get("use_proxy_user") is True:
            raise ValueError('proxy simulation is not supported for identified input execution')

        # Get or create DST
        self.dst = await self._get_input_tracker(message.session_id)
        await self._load_user_context(message.sender_id)
        self.dst.append_event(UserUtterEvent(
            event_id=input_event_id(message.message_id),
            text=message.text or "",
            attachments=getattr(message, 'attachments', []),
            metadata={
                "sender": message.sender or "user",
                "sender_id": message.sender_id,
                "receiver": message.receiver or "bot",
                "receiver_id": message.receiver_id or "default_bot",
                "channel_metadata": message.metadata or {},
                "message_id": message.message_id,
                "media": (message.metadata or {}).get("media", []),
                "execute": message.receiver == "bot",
            },
        ))
        logger.info(f"DST: user event recorded, total events: {len(self.dst.events)}")
        await self.save_tracker(self.dst)

        await self._publish_input(message.message_id)

        if message.receiver != "bot":
            logger.info("Message receiver is not 'bot', saving and returning")
            await self.save_tracker(self.dst)
            return

        logger.info("Handling bot turn...")
        await self._handle_bot_turn(message.session_id, channel)
        await self.save_tracker(self.dst)
        logger.info(f"Processor completed for session={message.session_id}")

    @_serialized_turn
    async def handle_inbound_message(
        self,
        inbound: InboundMessage,
    ):
        """Handle incoming message from MessageBus (new framework)

        Args:
            inbound: InboundMessage from Channel
        """
        logger.info(
            f"Processor.handle_inbound_message: session={inbound.session_key}, "
            f"sender={inbound.sender_id}, channel={inbound.channel}"
        )

        if self.agent.dialogue.get("use_proxy_user") is True:
            raise ValueError('proxy simulation is not supported for identified input execution')

        # Get or create DST
        self.dst = await self._get_input_tracker(inbound.session_key)
        await self._load_user_context(inbound.sender_id)
        self.dst.append_event(UserUtterEvent(
            event_id=input_event_id(inbound.message_id),
            text=inbound.content or "",
            attachments=inbound.attachments,
            metadata={
                "sender": "user",
                "sender_id": inbound.sender_id,
                "channel": inbound.channel,
                "chat_id": inbound.chat_id,
                "media": inbound.media,
                "channel_metadata": inbound.metadata,
                "received_at": inbound.timestamp.isoformat(),
                "message_id": inbound.message_id,
            },
        ))
        logger.info(f"DST: user event recorded, total events: {len(self.dst.events)}")
        await self.save_tracker(self.dst)
        await self._publish_input(inbound.message_id)

        # Handle bot turn
        runtime = await self._create_runtime(
            inbound.session_key, service_mode=self.service_mode or inbound.channel == "web")

        # Always set a valid channel callback.
        # On the MessageBus path nobody calls set_channel_callback() externally,
        # so we build a callback here that publishes real-time replies to the bus.
        # On the legacy path the externally-set callback is used as-is.
        if self._delivery_target is not None:
            # The persistent dispatcher reads committed replies directly. Do not
            # also publish them through the volatile bus and send them twice.
            runtime.set_channel_callback(None)
        elif self._channel_callback:
            runtime.set_channel_callback(self._channel_callback)
        elif self.message_bus:
            async def _bus_reply_cb(msg):
                text = msg.get("text", "") if isinstance(msg, dict) else str(msg)
                outbound = OutboundMessage(
                    channel=inbound.channel,
                    chat_id=inbound.chat_id,
                    content=text,
                    metadata={**msg.get("metadata", {}),
                              **({"request_id": msg["request_id"]} if msg.get("request_id") else {})} if isinstance(msg, dict) else {},
                    event_id=msg.get("event_id") if isinstance(msg, dict) else None,
                    sequence=msg.get("sequence") if isinstance(msg, dict) else None,
                    session_id=inbound.session_key,
                    attachments=msg.get('attachments', []) if isinstance(msg, dict) else [],
                )
                await self.message_bus.publish_outbound(outbound)
            runtime.set_channel_callback(_bus_reply_cb)

        logger.info(f"Starting PiAgentRuntime for {inbound.session_key}...")
        await self._run_runtime(runtime)
        logger.info("PiAgentRuntime completed")

        await self.save_tracker(self.dst)

    async def handle_recorded_message(self, inbound):
        """Execute an accepted direct input from an isolated causal snapshot."""
        from cota.group import execution_view
        canonical = await self._get_input_tracker(inbound.session_key)
        self.dst, cutoff, context_id = execution_view(canonical, input_event_id(inbound.message_id))
        self._detached_execution = True
        await self._load_user_context(inbound.sender_id)
        runtime = await self._create_runtime(inbound.session_key, service_mode=True)
        # Trigger metadata also projects queued direct inputs after earlier replies.
        # No group mode/reason is set: personal context and plain text stay direct.
        runtime.group_trigger = {'context_through': cutoff, 'context_input_id': context_id,
                                 'input_event_id': input_event_id(inbound.message_id)}
        if self._delivery_target is None:
            if self._channel_callback:
                runtime.set_channel_callback(self._channel_callback)
            elif self.message_bus:
                async def reply(message):
                    await self.message_bus.publish_outbound(OutboundMessage(
                        channel=inbound.channel, chat_id=inbound.chat_id, content=message['text'],
                        event_id=message['event_id'], sequence=message['sequence'],
                        session_id=inbound.session_key, attachments=message.get('attachments', []),
                        metadata={**message.get('metadata', {}),
                                  **({'request_id': message['request_id']} if message.get('request_id') else {})}))
                runtime.set_channel_callback(reply)
        await self._run_runtime(runtime)
        await self.save_tracker(self.dst)
        return self.dst.execution.get('status', 'recorded')

    async def _get_input_tracker(self, session_id):
        tracker = await self.get_tracker(session_id)
        if tracker.execution.get('status') == 'running':
            from cota.runtime.pi_runtime import RunInProgress
            raise RunInProgress('Previous run is still running; reconcile its executor before submitting new input')
        return tracker

    async def handle_group_message(self, inbound, *, reason, expected_sequence=None):
        """Execute already committed group input; Runner owns the execution slot."""
        from cota.group import execution_view
        canonical = await self.get_tracker(inbound.session_key)
        if expected_sequence is not None and len(canonical.events) != expected_sequence:
            return 'recorded'
        self._expected_sequence = expected_sequence
        self.dst, cutoff, context_input_id = execution_view(canonical, input_event_id(inbound.message_id))
        self._detached_execution = True
        self.dst.update_user(None, {})
        runtime = await self._create_runtime(inbound.session_key, service_mode=True)
        runtime.group_trigger = {'mode': 'group', 'reason': reason, 'context_through': cutoff,
                                 'input_event_id': input_event_id(inbound.message_id),
                                 'context_input_id': context_input_id}
        if self._delivery_target is None:
            if self._channel_callback:
                runtime.set_channel_callback(self._channel_callback)
            elif self.message_bus:
                async def reply(message):
                    await self.message_bus.publish_outbound(OutboundMessage(
                        channel=inbound.channel, chat_id=inbound.chat_id, content=message['text'],
                        event_id=message['event_id'], sequence=message['sequence'],
                        session_id=inbound.session_key, attachments=message.get('attachments', []),
                        metadata={**message.get('metadata', {}),
                                  **({'request_id': message['request_id']} if message.get('request_id') else {})}))
                runtime.set_channel_callback(reply)
        from cota.store import ExecutionSuperseded
        try:
            await self._run_runtime(runtime)
        except ExecutionSuperseded:
            return 'recorded'  # no run or tool fact was committed; discard the detached branch
        await self.save_tracker(self.dst)
        return self.dst.execution.get('status', 'recorded')

    async def _publish_input(self, message_id):
        if self._input_callback is not None:
            try:
                await self._input_callback(self.dst.latest_user_event.as_dict())
            except Exception:
                # Notifications cannot revoke a durable input or stop its run.
                logger.exception("Committed input publication failed: %s", message_id)

    async def _load_user_context(self, user_id):
        """Refresh trusted identity and memory without blocking the event loop."""
        memory = self.agent.user_memory
        context = await memory.aget_all(user_id) if user_id and memory is not None else {}
        self.dst.update_user(user_id, context)

    async def _create_runtime(self, session_id: str, *, service_mode=None):
        """Create the Pi-backed session coordinator."""
        from cota.runtime.pi_runtime import PiAgentRuntime, validate_runtime_selection

        dialogue = self.agent.dialogue

        validate_runtime_selection(dialogue)
        runtime = PiAgentRuntime(
            agent=self.agent,
            dst=self.dst,
            session_id=session_id,
            prompt=dialogue.get("prompt") or None,
            llm=dialogue.get("llm"),
            max_iterations=dialogue.get("max_iterations", 30),
            checkpoint=self.save_tracker,
            store=self.store,
            service_mode=self.service_mode if service_mode is None else service_mode,
        )

        if self._stream_callback is not None:
            runtime.set_stream_callback(self._stream_callback)
        return runtime

    @_serialized_turn
    async def handle_session(
        self, session_id: Text, channel: Optional[Any] = None
    ):
        self.dst = await self.get_tracker(session_id)
        await self._handle_bot_turn(session_id, channel)
        await self.save_tracker(self.dst)

    async def _handle_bot_turn(
        self, session_id: Text, channel: Optional[Any] = None
    ):
        """Run PiAgentRuntime single loop."""
        logger.info(f"_handle_bot_turn for session={session_id}")

        runtime = await self._create_runtime(session_id)

        if channel:
            if getattr(channel, 'supports_streaming', False):
                async def stream_cb(frame):
                    if frame.get('session_id') == session_id:
                        await channel.send_stream(session_id, frame)
                runtime.set_stream_callback(stream_cb)
            async def channel_cb(msg):
                await channel.send_response(session_id, msg)
            runtime.set_channel_callback(channel_cb)
        elif self._channel_callback:
            runtime.set_channel_callback(self._channel_callback)

        logger.info("Starting PiAgentRuntime.run()...")
        await self._run_runtime(runtime)
        logger.info("PiAgentRuntime.run() completed")

        await self.save_tracker(self.dst)

    async def _run_runtime(self, runtime):
        from cota.runtime.pi_runtime import ModelCallError
        from cota.events import BotUtterEvent
        try:
            await runtime.run()
        except ModelCallError as error:
            # The engine checkpoint remains failed; presenting an error must not
            # mark the task completed or automatically replay its side effects.
            text = ('抱歉，处理时遇到错误，请稍后重试。'
                    if self.service_mode or getattr(runtime, '_service_mode', False)
                    else f'抱歉，处理时遇到错误：{error}')
            self.dst.append_event(BotUtterEvent(text=text,
                                           metadata={'source': 'runtime_error'}))
            await self.save_tracker(self.dst)
            await runtime.publish_committed()

    async def get_tracker(
        self,
        session_id: Text,
        user_id: Optional[Text] = None,
    ) -> DST:
        tracker = await self.store.load(session_id, agent=self.agent)
        if tracker is None:
            tracker = DST(
                session_id=session_id,
                agent=self.agent,
                user_id=user_id,
            )
        else:
            if user_id and not tracker.user_id:
                tracker.user_id = user_id

        return tracker

    async def save_tracker(self, tracker: DST) -> None:
        if self._detached_execution:
            await self.store.save_execution(tracker, delivery_target=self._delivery_target,
                                            expected_sequence=self._expected_sequence)
            self._expected_sequence = None  # the first checkpoint committed run_started atomically
        elif self._delivery_target is not None:
            await self.store.save(tracker, delivery_target=self._delivery_target)
        else:
            await self.store.save(tracker)
