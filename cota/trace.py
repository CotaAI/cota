"""Pure, conservative projections of event history and resource provenance.

Reads prove that a document was read, not that instructions were followed.
Policy authoring is independent of execution history.
"""
from copy import deepcopy

from cota.events import Event, EventType
from cota.events.resources import skill_read_name

_CALL_TYPES = {EventType.TOOL_STARTED, EventType.TOOL_RESULT}


def validate_event_references(event, events):
    """Validate append order and references without inferring missing facts."""
    payload = event.payload
    from cota.events.assistant import validate_carrier_references
    validate_carrier_references(event, events)
    if event.type in _CALL_TYPES:
        phases = [e for e in events if e.type in _CALL_TYPES and e.run_id == event.run_id
                  and e.payload['tool_call_id'] == payload['tool_call_id']]
        if any(e.payload['tool'] != payload['tool'] for e in phases):
            raise ValueError('Call phases must retain the same tool identity')
        if any(e.type == event.type for e in phases):
            raise ValueError(f'Duplicate tool call: duplicate {event.type} for {payload["tool_call_id"]}')
    if event.type == EventType.RUN_STARTED:
        input_id = payload.get('input_event_id')
        if input_id is not None and not any(e.event_id == input_id and e.type == EventType.USER_UTTER for e in events):
            raise ValueError('run_started input_event_id must reference an existing user event')
        context_id = payload.get('context_input_id')
        if context_id is not None and not any(e.event_id == context_id and e.type == EventType.USER_UTTER for e in events):
            raise ValueError('run_started context_input_id must reference an existing user event')
        previous_run = payload.get('previous_run_id')
        if previous_run is not None and (previous_run == event.run_id or
                not any(e.run_id == previous_run for e in events)):
            raise ValueError('run_started previous_run_id must reference an existing prior run')


def build_trace(events, run_id):
    """Build a detached trace from execution facts."""
    if not isinstance(run_id, str) or not run_id:
        raise ValueError('run_id must be a nonempty string')
    facts = [e if isinstance(e, Event) else Event.from_dict(e) for e in events]
    trace = {'schema_version': 1, 'run_id': run_id, 'status': 'unknown',
             'input_event_id': None, 'skills': [], 'skill_history': [],
             'calls': [], 'outputs': [],
             'resources': [], 'events': []}
    first = next((i for i, e in enumerate(facts) if e.run_id == run_id), len(facts))
    trace['skill_history'] = [e.as_dict() for e in facts[:first]
                              if skill_read_name(e) and e.run_id != run_id]
    calls = {}
    for index, event in enumerate(facts):
        if event.run_id != run_id:
            continue
        event.validate()
        validate_event_references(event, facts[:index])
        payload = event.payload
        trace['events'].append(event.as_dict())
        if event.type == EventType.RUN_STARTED:
            trace['status'] = 'running'
            trace['input_event_id'] = payload.get('input_event_id')
        elif event.type == EventType.RUN_FINISHED:
            trace['status'] = payload['status']
            trace['error_type'] = payload.get('error_type')
        elif event.type == EventType.BOT_UTTER:
            trace['outputs'].append(event.as_dict())
        elif event.type in _CALL_TYPES:
            call_id = payload['tool_call_id']
            call = calls.setdefault(call_id, {
                'run_id': run_id, 'tool_call_id': call_id, 'tool': payload['tool'],
                'started': False, 'finished': False,
                'status': 'pending', 'event_ids': [],
            })
            call['event_ids'].append(event.event_id)
            if 'arguments' in payload:
                call['arguments'] = deepcopy(payload['arguments'])
            if event.type == EventType.TOOL_STARTED:
                call['started'] = True
                call['start_event_id'] = event.event_id
            elif event.type == EventType.TOOL_RESULT:
                if skill_read_name(event):
                    trace['skills'].append(event.as_dict())
                elif event.tool == 'read':
                    trace['resources'].append(event.as_dict())
                call['finished'] = True
                call['result_event_id'] = event.event_id
                for key in ('result', 'content', 'duration_ms', 'status'):
                    if key in payload:
                        call[key] = deepcopy(payload[key])
    trace['calls'] = list(calls.values())
    return deepcopy(trace)
