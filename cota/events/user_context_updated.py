"""User context updated event."""
from cota.events.event import Event, EventType


class UserContextUpdatedEvent(Event):
    _event_type = EventType.USER_CONTEXT_UPDATED

    def _validate_payload(self):
        p = self.payload
        if 'user_id' not in p:
            raise ValueError('user_context_updated requires user_id and context')
        if p['user_id'] is not None and not isinstance(p['user_id'], str):
            raise ValueError('user_id must be a string or None')
        if p['user_id'] is None and p.get('context'):
            raise ValueError('Unidentified user cannot carry user context')
        return {'context': dict}
