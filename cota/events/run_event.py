"""Run lifecycle events."""
from cota.events.event import Event, EventType, validate_execution


class RunStartedEvent(Event):
    _event_type = EventType.RUN_STARTED

    def _validate_payload(self):
        validate_execution(self.payload)
        return {}


class RunFinishedEvent(Event):
    _event_type = EventType.RUN_FINISHED

    def _validate_payload(self):
        validate_execution(self.payload)
        if self.payload.get('status') not in ('limited', 'completed', 'failed', 'interrupted'):
            raise ValueError('Invalid run_finished status')
        return {'status': str}
