"""Translate Pi observations into Cota events without driving execution."""
from copy import deepcopy
import hashlib
from time import perf_counter

from cota.events import Event, BotUtterEvent
from cota.events.tool import result_payload, text_result
from cota.events.assistant import _same, canonical_json


def reply_digest(value):
    normalized = {'content': value.get('content', []), 'details': value.get('details') or {},
                  'isError': bool(value.get('isError'))}
    return hashlib.sha256(canonical_json(normalized).encode()).hexdigest()


class PiTraceRecorder:
    def __init__(self, dst, store=None):
        self.dst = dst
        self.store = store
        self.preparation = {}
        self.policy = {}
        self._request_sequence = 0
        self._request_run_id = None
        self._pending_model = None
        self._tool_started_at = {}
        self._tool_reply_hashes = {}

    def next_request_sequence(self):
        run_id = self.dst.execution.get('run_id')
        if self._request_run_id != run_id:
            self._request_sequence, self._request_run_id = 0, run_id
        self._request_sequence += 1
        return self._request_sequence

    def stage_model(self, message, metadata, diagnostic):
        self._pending_model = {'message': deepcopy(message), 'metadata': deepcopy(metadata),
                               'diagnostic': diagnostic, 'owner_id': None}

    def _model_origin(self):
        pending = self._pending_model
        metadata = pending['metadata']
        return {key: deepcopy(metadata[key]) for key in
                ('request_id', 'request_sequence', 'duration_ms', 'policy') if key in metadata} | {
                    'model': metadata.get('model'), 'stop_reason': pending['message']['stopReason']}

    def observe_assistant(self, message):
        pending = self._pending_model
        if pending is None or not _same(pending['message']['content'], message.get('content')):
            raise ValueError('Pi assistant message does not match its model response')
        if any(block['type'] == 'toolCall' for block in message['content']):
            return None  # The first tool start owns the complete batch.
        text = '\n'.join(block['text'] for block in message['content'] if block['type'] == 'text')
        if not text:
            return None  # Empty outputs are diagnostic-only.
        event = BotUtterEvent(text, metadata={'source': 'model'}, llm=self._model_origin(),
                         run_id=self.dst.execution['run_id'])
        self.dst.append_event(event)
        pending['owner_id'] = event.event_id
        return event

    async def link_model_debug(self, event):
        if event is not None and event.payload.get('llm') and self.debug_enabled:
            diagnostic = self._pending_model['diagnostic']
            diagnostic['event_id'] = event.event_id
            await self.save_debug(event.payload['llm']['request_id'], diagnostic)

    def tool_source(self, call_id):
        event = next((e for e in reversed(self.dst.events) if e.type == 'tool_started'
                      and e.run_id == self.dst.execution.get('run_id')
                      and e.payload['tool_call_id'] == call_id), None)
        if event is None:
            raise ValueError('Tool-generated bot requires its tool_started source')
        return event.event_id

    @property
    def debug_enabled(self):
        return bool(self.store is not None and self.store.debug_enabled)

    async def save_debug(self, request_id, data):
        if self.debug_enabled:
            await self.store.save_model_debug(self.dst.session_id, request_id, data)

    def record(self, kind, payload, *, source='cota'):
        event = Event(type=kind, payload=deepcopy(payload),
                      run_id=self.dst.execution.get('run_id'), source=source)
        self.dst.append_event(event)
        return event

    def result(self, call_id, tool, arguments, raw_result, model_result, *, source='cota', executed=True, resource=None):
        started_at = self._tool_started_at.get(call_id)
        # From receipt of Pi's start notification to the prepared result, before
        # its checkpoint. Includes bridging/start persistence, not result saving.
        duration_ms = (perf_counter() - started_at) * 1000 if started_at is not None else None
        self.require_started(call_id, tool, arguments)
        status = 'blocked' if not executed else 'error' if model_result.get('isError') else 'success'
        result = self.record('tool_result', result_payload(
            tool, call_id, raw_result, content=model_result['content'], status=status,
            duration_ms=duration_ms, resource=resource), source=source)
        # Pi's details are protocol acknowledgement data, not another persisted
        # copy of the business result. A digest also validates repeated end callbacks.
        self._tool_reply_hashes[call_id] = reply_digest(model_result)
        self._tool_started_at.pop(call_id, None)
        return result

    def require_started(self, call_id, tool, arguments):
        start = next((e for e in reversed(self.dst.events) if e.type == 'tool_started'
                      and e.run_id == self.dst.execution.get('run_id') and e.payload['tool_call_id'] == call_id), None)
        if start is None or start.tool != tool or not _same(start.payload['arguments'], arguments):
            raise ValueError('Tool result requires its matching tool_started')
        return start

    def observe(self, event):
        """Tool phases share a call ID; message context is projected from durable facts."""
        kind = event['type']
        if kind == 'tool_execution_start':
            call_id = event['toolCallId']
            payload = {'tool_call_id': call_id, 'tool': event['toolName'], 'arguments': event['args']}
            if 'requestedArgs' in event and not _same(event['requestedArgs'], event['args']):
                payload['requested_arguments'] = event['requestedArgs']
            pending = self._pending_model
            if pending is None:
                raise ValueError('Pi tool start has no pending assistant decision')
            if pending['owner_id']:
                payload['llm_event_id'] = pending['owner_id']
            else:
                payload['llm'] = self._model_origin()
                payload['llm']['message'] = {'content': deepcopy(pending['message']['content']),
                                             'stop_reason': pending['message']['stopReason']}
            event = self.record('tool_started', payload, source='pi')
            self._tool_started_at[call_id] = perf_counter()
            if pending['owner_id'] is None:
                pending['owner_id'] = event.event_id
            return event
        if kind == 'tool_execution_end':
            call_id = event['toolCallId']
            start = next((item for item in reversed(self.dst.events)
                          if item.run_id == self.dst.execution['run_id'] and item.type == 'tool_started'
                          and item.payload['tool_call_id'] == call_id), None)
            if start is None or start.tool != event['toolName']:
                raise ValueError('Pi tool end requires its matching tool start')
            result = next((item for item in reversed(self.dst.events)
                           if item.run_id == self.dst.execution['run_id'] and item.type == 'tool_result'
                           and item.payload['tool_call_id'] == call_id), None)
            model_result = {**event['result'], 'isError': bool(event.get('isError'))}
            if result:
                # Pi acknowledges the same result. Never rewrite an already
                # committed fact or let a changed result reach the next model.
                if self._tool_reply_hashes.get(call_id) != reply_digest(model_result):
                    raise ValueError('Pi tool end differs from the recorded result')
                return None
            # Pi 1.4 supplies durationMs only after entering tool.execute;
            # validation, unknown tools and blocked batch tails omit it.
            blocks = model_result['content']
            value = text_result(blocks)
            recorded = self.result(call_id, start.tool, start.payload['arguments'], value,
                                   model_result, source='pi', executed=event.get('durationMs') is not None)
            return recorded
