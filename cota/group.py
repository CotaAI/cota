"""Group intake and participation, independent of transport and Pi execution."""
import asyncio
import logging
from dataclasses import dataclass, field
import time

from cota.dst import DST
from cota.events import UserUtterEvent
from cota.inputs import input_event_id

logger = logging.getLogger(__name__)


def execution_view(canonical, trigger_id):
    """Freeze visible user input while retaining completed earlier executions."""
    trigger = next(e for e in canonical.events if e.event_id == trigger_id)
    cutoff = trigger
    by_id = {e.event_id: e for e in canonical.events}
    if any(by_id.get(e.payload.get(key), trigger).sequence > trigger.sequence
           for e in canonical.events if e.type == 'run_started'
           for key in ('input_event_id', 'context_input_id')):
        # A rejected/unscheduled old mention may be explicitly retried after a
        # newer run. Keep that run's causal inputs; freeze a fresh context now.
        cutoff = canonical.latest_user_event
    facts = []
    for event in canonical.events:
        if event.type == 'user_utter' and event.sequence > cutoff.sequence:
            continue
        raw = event.as_dict()
        raw['sequence'] = len(facts) + 1
        facts.append(raw)
    return DST.from_events(canonical.session_id, facts, agent=canonical.agent,
                           run_metadata=canonical.run_metadata), cutoff.sequence, cutoff.event_id


async def validate_session_mode(store, session_id, mode):
    first = await store._query_events(session_id, kinds=('user_utter',), limit=1)
    if first and (first[0]['payload'].get('metadata') or {}).get('mode', 'direct') != mode:
        raise ValueError('Conversation mode changed; create a new session')


@dataclass
class _Candidate:
    inbound: object
    on_reply: object
    result: asyncio.Future
    first_at: float
    updated_at: float
    considered: bool = False
    started: bool = False


@dataclass
class _Slot:
    candidate: _Candidate | None = None
    changed: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task | None = None
    judging: asyncio.Task | None = None
    execution: asyncio.Future | None = None
    execution_candidate: _Candidate | None = None


class GroupConversation:
    # Internal defaults, deliberately separate judgement cost from speaking rate.
    cooldown_seconds = 60
    debounce_seconds = 1
    max_wait_seconds = 3
    judgement_interval = 2

    def __init__(self, application):
        from cota.participation import ParticipationJudge
        self.application = application
        self.store = application.store
        self.agent = application.agent
        self.judge = ParticipationJudge(self.agent, self.store)
        self._slots = {}
        self._evaluated = {}
        self._judgements = asyncio.Semaphore(application.runner.concurrency)
        self._closed = False

    @staticmethod
    def _settle(candidate, status='recorded', error=None):
        if not candidate.result.done():
            if error is not None:
                candidate.result.set_exception(error)
            else:
                candidate.result.set_result(status)

    def _invalidate(self, slot):
        candidate = slot.candidate
        if candidate and not candidate.started:
            # An in-flight submission/active pre-start handler still owns a
            # Store claim. Do not publish a terminal result until it releases it.
            if slot.execution_candidate is not candidate:
                self._settle(candidate)
            elif slot.execution and self.application.runner.discard_background(slot.execution):
                self._settle(candidate)
            if slot.judging:
                slot.judging.cancel()
        slot.changed.set()

    def _offer(self, inbound, on_reply):
        sid, now = inbound.session_key, time.monotonic()
        slot = self._slots.get(sid)
        if slot is None:
            if self._closed or len(self._slots) >= self.application.runner.max_pending:
                return None  # best effort; the input itself is already durable
            slot = self._slots[sid] = _Slot()
        previous = slot.candidate
        first_at = previous.first_at if previous and not previous.considered else now
        self._invalidate(slot)
        result = asyncio.get_running_loop().create_future()
        # A caller may ignore Submission; consume failures without hiding them from wait().
        result.add_done_callback(lambda f: None if f.cancelled() else f.exception())
        slot.candidate = _Candidate(inbound, on_reply, result, first_at, now)
        if slot.task is None:
            slot.task = asyncio.create_task(self._consider(sid, slot))
        return result

    async def receive(self, inbound, on_input, on_reply):
        from cota.application import Submission
        sid = inbound.session_key
        async with self.store.input_admission_lock(sid):
            receipt, future = await self.store.check_input(inbound)
            duplicate = receipt is not None
            if receipt is None:
                await validate_session_mode(self.store, sid, 'group')
                metadata = {'mode': 'group', 'sender': 'user', 'sender_id': inbound.sender_id,
                            'channel': inbound.channel, 'chat_id': inbound.chat_id,
                            'message_id': inbound.message_id, 'mentioned': inbound.mentioned}
                if inbound.media:
                    metadata['media'] = inbound.media
                for key in ('sender_name', 'reply_to'):
                    if getattr(inbound, key) is not None:
                        metadata[key] = getattr(inbound, key)
                event = UserUtterEvent(event_id=input_event_id(inbound.message_id),
                                       text=inbound.content, metadata=metadata)
                committed = await self.store.append_conversation_event(sid, event, agent=self.agent)
                if on_input:
                    try:
                        await on_input(committed)
                    except Exception:
                        logger.exception('Group input publication failed')
        # No model or execution queue waits under the input admission lock.
        if self._closed:
            future = None
        elif inbound.mentioned:
            if not duplicate and (slot := self._slots.get(sid)):
                self._invalidate(slot)
                slot.candidate = None
            if future is None and not (receipt or {}).get('run_id'):
                async def execute(message):
                    return await self.application._execute_group(message, 'mention', on_reply)
                future = await self.application.runner.submit(inbound, handler=execute, recorded=True)
        elif not duplicate and self.agent.dialogue.get('response') == 'proactive':
            future = self._offer(inbound, on_reply)
        elif future is None and (slot := self._slots.get(sid)):
            candidate = slot.candidate
            if candidate and candidate.inbound.message_id == inbound.message_id:
                future = candidate.result
        if future is None:
            future = asyncio.get_running_loop().create_future()
            future.set_result((receipt or {}).get('status', 'recorded'))
        return Submission(sid, inbound.message_id, future, duplicate, self.application)

    def _eligible(self, tracker, candidate):
        if self._closed or candidate.result.cancelled():
            return False
        if not tracker or not tracker.latest_user_event:
            return False
        if tracker.latest_user_event.event_id != input_event_id(candidate.inbound.message_id):
            return False
        if self.application.runner.has_foreground(tracker.session_id):
            return False
        last_reply = next((e for e in reversed(tracker.events) if e.type == 'bot_utter'), None)
        return not last_reply or time.time() - last_reply.timestamp >= self.cooldown_seconds

    async def _consider(self, sid, slot):
        candidate = None
        try:
            while not self._closed and slot.candidate:
                candidate = slot.candidate
                slot.changed.clear()
                now = time.monotonic()
                deadline = max(min(candidate.updated_at + self.debounce_seconds,
                                   candidate.first_at + self.max_wait_seconds),
                               self._evaluated.get(sid, -float('inf')) + self.judgement_interval)
                if deadline > now:
                    try:
                        await asyncio.wait_for(slot.changed.wait(), deadline - now)
                        continue
                    except asyncio.TimeoutError:
                        pass
                async with self._judgements:
                    if slot.candidate is not candidate:
                        continue
                    tracker = await self.store.load(sid, agent=self.agent)
                    if slot.candidate is not candidate:
                        continue
                    if not self._eligible(tracker, candidate):
                        self._settle(candidate)
                        slot.candidate = None
                        continue
                    candidate.considered = True
                    sequence = tracker.events[-1].sequence
                    now = time.monotonic()
                    self._evaluated = {key: ts for key, ts in self._evaluated.items()
                                       if now - ts < self.judgement_interval}
                    if len(self._evaluated) >= self.application.runner.max_pending:
                        self._evaluated.pop(next(iter(self._evaluated)))
                    self._evaluated[sid] = now
                    slot.judging = asyncio.create_task(self.judge.decide(tracker))
                    try:
                        selected = await slot.judging
                    except asyncio.CancelledError:
                        if asyncio.current_task().cancelling():
                            raise
                        continue  # new input invalidated this judgement
                    finally:
                        slot.judging = None
                if slot.candidate is not candidate:
                    continue
                current = await self.store.load(sid, agent=self.agent)
                if slot.candidate is not candidate:
                    continue
                if selected and self._eligible(current, candidate) and current.events[-1].sequence == sequence:
                    async def execute(message, selected_candidate=candidate, expected=sequence):
                        current = await self.store.load(sid, agent=self.agent)
                        if (slot.candidate is not selected_candidate or not self._eligible(current, selected_candidate)
                                or current.events[-1].sequence != expected):
                            return 'recorded'
                        selected_candidate.started = True
                        return await self.application._execute_group(message, 'proactive', selected_candidate.on_reply,
                                                                      expected_sequence=expected)
                    try:
                        slot.execution_candidate = candidate
                        slot.execution = await self.application.runner.submit(
                            candidate.inbound, handler=execute, recorded=True, background=True)
                        if slot.candidate is not candidate:
                            self.application.runner.discard_background(slot.execution)
                        status = await asyncio.shield(slot.execution)
                        self._settle(candidate, status or 'recorded')
                    except asyncio.QueueFull:
                        self._settle(candidate)
                    except asyncio.CancelledError:
                        if asyncio.current_task().cancelling():
                            raise
                        self._settle(candidate)  # evicted/superseded before execution
                    except Exception as error:
                        self._settle(candidate, error=error)
                    finally:
                        slot.execution = None
                        slot.execution_candidate = None
                else:
                    self._settle(candidate)
                if slot.candidate is candidate:
                    slot.candidate = None
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception('Group participation scheduling failed for %s', sid)
        finally:
            for pending in (candidate, slot.candidate):
                if pending and not pending.result.done():
                    if pending.started:
                        pending.result.cancel()
                    else:
                        self._settle(pending)
            self._slots.pop(sid, None)

    async def close(self):
        self._closed = True
        for slot in list(self._slots.values()):
            self._invalidate(slot)
            # Runner owns admitted work, including its pre-start checks. Keep
            # the waiter alive until shutdown releases the input claim.
            if slot.execution is not None:
                continue
            slot.task.cancel()

    async def drain(self):
        # Called after Runner has resolved/cancelled all execution futures.
        tasks = [slot.task for slot in self._slots.values()]
        if tasks:
            for task in tasks:
                task.cancel()
            _, pending = await asyncio.wait(tasks, timeout=self.application.runner.shutdown_timeout)
            if pending:
                logger.error('Participation tasks did not stop within shutdown timeout')
        self._evaluated.clear()
