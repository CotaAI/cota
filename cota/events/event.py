"""Versioned event facts. Serialization has one envelope and JSON-native payloads."""

import json
import math
import time
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Dict, Optional
from uuid import uuid4


class EventType:
    USER_CONTEXT_UPDATED = 'user_context_updated'
    USER_UTTER = 'user_utter'
    BOT_UTTER = 'bot_utter'
    RUN_STARTED = 'run_started'
    RUN_FINISHED = 'run_finished'
    CONTEXT_COMPACTION = 'context_compaction'
    TOOL_STARTED = 'tool_started'
    TOOL_RESULT = 'tool_result'


_TYPES = {v for k, v in vars(EventType).items() if k.isupper()}
_ENVELOPE = ('schema_version', 'event_id', 'sequence', 'timestamp', 'run_id', 'type', 'source', 'payload')


def _json_native(value):
    if value is None or type(value) in (str, bool, int):
        return True
    if type(value) is float:
        return math.isfinite(value)
    if type(value) is list:
        return all(_json_native(item) for item in value)
    if type(value) is dict:
        return all(type(key) is str and _json_native(item) for key, item in value.items())
    return False


def validate_execution(value):
    """Validate execution checkpoint fields before the reducer changes state."""
    if not isinstance(value, dict):
        raise ValueError('execution state must be an object')
    if 'messages' in value:
        raise ValueError('Full messages are not execution state; use event-derived context')
    if 'pending_tools' in value:
        pending = value['pending_tools']
        if not isinstance(pending, dict) or any(
                not isinstance(call, dict) or not isinstance(call.get('name'), str) or
                not isinstance(call.get('arguments'), dict) for call in pending.values()):
            raise ValueError('execution.pending_tools must map call IDs to name/arguments objects')
    if 'status' in value and value['status'] not in ('running', 'limited', 'completed', 'failed', 'interrupted'):
        raise ValueError('Invalid execution status')
    if 'mode' in value and value['mode'] != 'group':
        raise ValueError('Execution mode must be group when present')
    if 'reason' in value and value['reason'] not in ('mention', 'proactive'):
        raise ValueError('Invalid group response reason')
    if 'context_through' in value and (type(value['context_through']) is not int or value['context_through'] < 1):
        raise ValueError('context_through must be a positive event sequence')
    for key in ('engine', 'engine_version', 'run_id', 'input_event_id', 'context_input_id', 'error_type'):
        if key in value and value[key] is not None and not isinstance(value[key], str):
            raise ValueError(f'execution.{key} must be a string or None')


@dataclass
class Event:
    type: str
    payload: Dict[str, Any] = field(default_factory=dict)
    run_id: Optional[str] = None
    source: str = 'cota'
    event_id: str = field(default_factory=lambda: uuid4().hex)
    sequence: Optional[int] = None
    timestamp: float = field(default_factory=time.time)
    schema_version: int = 1

    def __setattr__(self, name, value):
        if self.__dict__.get('_sealed'):
            raise TypeError('Reducer-owned event is immutable; apply a new event')
        object.__setattr__(self, name, value)

    def __deepcopy__(self, memo):
        # EventHistory returns editable detached facts without revalidating old
        # image payloads merely to inspect a tool name or an event identity.
        result = object.__new__(type(self))
        memo[id(self)] = result
        for key, value in vars(self).items():
            if key != '_sealed':
                object.__setattr__(result, key, deepcopy(value, memo))
        return result

    def freeze(self):
        from .immutable import freeze_json
        if not self.__dict__.get('_sealed'):
            self.validate()
            self.payload = freeze_json(self.payload)
            self._sealed = True
        return self

    def __post_init__(self):
        self.payload = deepcopy(self.payload)
        self.validate()
        # One stable JSON numeric representation across SQLite/MySQL.
        self.timestamp = float(self.timestamp)

    def validate(self):
        if self.__dict__.get('_sealed'):
            return
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError('Unsupported event schema_version')
        if not isinstance(self.type, str) or self.type not in _TYPES:
            raise ValueError(f'Unknown event type: {self.type}')
        if not isinstance(self.event_id, str) or not self.event_id:
            raise ValueError('event_id must be a nonempty string')
        if self.sequence is not None and (type(self.sequence) is not int or self.sequence < 0):
            raise ValueError('sequence must be a nonnegative integer or None')
        if type(self.timestamp) not in (int, float) or not math.isfinite(self.timestamp):
            raise ValueError('timestamp must be finite numeric time')
        if self.run_id is not None and (not isinstance(self.run_id, str) or not self.run_id):
            raise ValueError('run_id must be a nonempty string or None')
        if not isinstance(self.source, str) or not self.source:
            raise ValueError('source must be a nonempty string')
        if not isinstance(self.payload, dict):
            raise ValueError('payload must be an object')
        if not _json_native(self.payload):
            raise ValueError('payload must contain JSON-native values')
        try:
            json.dumps(self.payload, allow_nan=False)
        except (ValueError, TypeError) as exc:
            raise ValueError('payload must contain JSON values') from exc
        from cota.events.resources import validate_resource
        validate_resource(self)
        from cota.events.assistant import validate_carrier
        validate_carrier(self)
        if isinstance(self.payload.get('metadata'), dict) and 'model_event_id' in self.payload['metadata']:
            raise ValueError('model_event_id was removed; use assistant carrier event references')
        required = {}
        if self.type == EventType.USER_CONTEXT_UPDATED:
            required = {'context': dict}
            if 'user_id' not in self.payload:
                raise ValueError('user_context_updated requires user_id and context')
            if self.payload['user_id'] is not None and not isinstance(self.payload['user_id'], str):
                raise ValueError('user_id must be a string or None')
            if self.payload['user_id'] is None and self.payload.get('context'):
                raise ValueError('Unidentified user cannot carry user context')
        if self.type in (EventType.RUN_STARTED, EventType.RUN_FINISHED):
            validate_execution(self.payload)
        if self.type in (EventType.USER_UTTER, EventType.BOT_UTTER):
            required = {'text': str}
            if 'attachments' in self.payload:
                from cota.files import validate_attachments
                validate_attachments(self.payload['attachments'])
        elif self.type == EventType.TOOL_STARTED:
            required = {'tool_call_id': str, 'tool': str, 'arguments': dict}
            if set(self.payload) - {'tool_call_id', 'tool', 'arguments', 'requested_arguments', 'llm', 'llm_event_id'}:
                raise ValueError('Unexpected tool_started fields; outcomes belong on tool_result')
            if 'requested_arguments' in self.payload:
                from cota.events.assistant import _same
                requested = self.payload['requested_arguments']
                if (not isinstance(requested, dict) or _same(requested, self.payload.get('arguments'))
                        or not ('llm' in self.payload or 'llm_event_id' in self.payload)):
                    raise ValueError('requested_arguments requires a distinct proposal and its model source')
        elif self.type == EventType.TOOL_RESULT:
            required = {'tool_call_id': str, 'tool': str, 'status': str}
            if 'result' not in self.payload:
                raise ValueError('tool_result requires result')
            if self.payload.get('status') not in ('success', 'error', 'blocked'):
                raise ValueError('Invalid tool_result status')
            if set(self.payload) - {'tool_call_id', 'tool', 'status', 'result', 'content', 'duration_ms', 'resource'}:
                raise ValueError('Unexpected tool_result fields; arguments belong on tool_started')
            if 'content' in self.payload:
                blocks = self.payload['content']
                if not isinstance(blocks, list) or any(not isinstance(b, dict) or not isinstance(b.get('type'), str) for b in blocks):
                    raise ValueError('content must contain Pi content blocks')
        elif self.type == EventType.RUN_FINISHED:
            required = {'status': str}
            if self.payload.get('status') not in ('limited', 'completed', 'failed', 'interrupted'):
                raise ValueError('Invalid run_finished status')
        elif self.type == EventType.CONTEXT_COMPACTION:
            required = {'summary': str, 'replaced_message_ids': list}
            ids = self.payload.get('replaced_message_ids', [])
            if not ids or any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != len(ids):
                raise ValueError('Compaction requires unique replaced message IDs')
        for key, expected in required.items():
            if not isinstance(self.payload.get(key), expected):
                raise ValueError(f'{self.type} requires {key} of type {expected.__name__}')
            if expected is str and key != 'text' and not self.payload[key]:
                raise ValueError(f'{self.type} requires nonempty {key}')
        for key in ('metadata', 'arguments', 'resource'):
            if key in self.payload and self.payload[key] is not None and not isinstance(self.payload[key], dict):
                raise ValueError(f'{key} must be an object')
        duration = self.payload.get('duration_ms')
        if duration is not None and (type(duration) not in (int, float) or duration < 0):
            raise ValueError('duration_ms must be a nonnegative number or None')
        for key in ('result_event_id', 'input_event_id', 'previous_run_id', 'request_id'):
            value = self.payload.get(key)
            if value is not None and (not isinstance(value, str) or not value):
                raise ValueError(f'{key} must be a nonempty string or None')
        if 'request_sequence' in self.payload:
            if type(self.payload['request_sequence']) is not int or self.payload['request_sequence'] < 1:
                raise ValueError('request_sequence must be a positive integer')

    @property
    def text(self):
        return self.payload.get('text', '')

    @property
    def metadata(self):
        return self.payload.get('metadata') or {}

    @property
    def skill(self):
        from cota.events.resources import skill_read_name
        return skill_read_name(self) or self.payload.get('skill')

    @property
    def tool(self):
        return self.payload.get('tool')

    @property
    def result(self):
        return self.payload.get('result')

    def as_dict(self):
        if not self.__dict__.get('_sealed'):
            self.validate()
        return deepcopy({key: getattr(self, key) for key in _ENVELOPE})

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict) or set(data) != set(_ENVELOPE):
            raise ValueError('Expected versioned event envelope')
        if not isinstance(data.get('type'), str):
            raise ValueError('Event type must be a string')
        subtype = _TYPE_TO_CLASS.get(data.get('type'), Event)
        event = subtype.__new__(subtype)
        Event.__init__(event, **deepcopy(data))
        return event


class UserUtterEvent(Event):
    def __init__(self, text: str, metadata=None, *, attachments=None, **kw):
        payload = {'text': text, 'metadata': metadata or {}}
        if attachments is not None:
            from cota.files import validate_attachments
            attachments = validate_attachments(attachments)
        if attachments:
            payload['attachments'] = attachments
        super().__init__(EventType.USER_UTTER, payload, **kw)


class BotUtterEvent(Event):
    def __init__(self, text: str, metadata=None, *, llm=None, llm_event_id=None,
                 tool_event_id=None, attachments=None, **kw):
        payload = {'text': text, 'metadata': metadata or {}}
        if attachments is not None:
            from cota.files import validate_attachments
            attachments = validate_attachments(attachments)
        if attachments:
            payload['attachments'] = attachments
        if llm is not None:
            payload['llm'] = llm
        if llm_event_id is not None:
            payload['llm_event_id'] = llm_event_id
        if tool_event_id is not None:
            payload['tool_event_id'] = tool_event_id
        super().__init__(EventType.BOT_UTTER, payload, **kw)


class ToolResultEvent(Event):
    """Observed outcome; arguments and model origin belong to tool_started."""
    def __init__(self, tool: str, result=None, *, tool_call_id=None, content=None,
                 status='success', duration_ms=None, resource=None, **kw):
        from cota.events.tool import result_payload
        super().__init__(EventType.TOOL_RESULT, result_payload(
            tool, tool_call_id or uuid4().hex, result, content=content, status=status,
            duration_ms=duration_ms, resource=resource), **kw)


_TYPE_TO_CLASS = {
    EventType.USER_UTTER: UserUtterEvent, EventType.BOT_UTTER: BotUtterEvent,
    EventType.TOOL_RESULT: ToolResultEvent,
}
