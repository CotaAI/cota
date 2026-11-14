"""Shared constants and lightweight validators used across event types."""


class EventType:
    USER_CONTEXT_UPDATED = 'user_context_updated'
    USER_UTTER = 'user_utter'
    BOT_UTTER = 'bot_utter'
    RUN_STARTED = 'run_started'
    RUN_FINISHED = 'run_finished'
    CONTEXT_COMPACTION = 'context_compaction'
    TOOL_STARTED = 'tool_started'
    TOOL_RESULT = 'tool_result'


TYPES = frozenset(v for k, v in vars(EventType).items() if k.isupper())

ENVELOPE = ('schema_version', 'event_id', 'sequence', 'timestamp', 'run_id', 'type', 'source', 'payload')


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
