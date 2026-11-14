"""Tool started event."""
from cota.events.event import Event, EventType


class ToolStartedEvent(Event):
    _event_type = EventType.TOOL_STARTED

    def _validate_payload(self):
        p = self.payload
        if set(p) - {'tool_call_id', 'tool', 'arguments', 'requested_arguments', 'llm', 'llm_event_id'}:
            raise ValueError('Unexpected tool_started fields; outcomes belong on tool_result')
        if 'requested_arguments' in p:
            from cota.events.utils import _same
            requested = p['requested_arguments']
            if (not isinstance(requested, dict) or _same(requested, p.get('arguments'))
                    or not ('llm' in p or 'llm_event_id' in p)):
                raise ValueError('requested_arguments requires a distinct proposal and its model source')
        return {'tool_call_id': str, 'tool': str, 'arguments': dict}
