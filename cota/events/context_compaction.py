"""Context compaction event."""
from cota.events.event import Event, EventType


class ContextCompactionEvent(Event):
    _event_type = EventType.CONTEXT_COMPACTION

    def _validate_payload(self):
        p = self.payload
        ids = p.get('replaced_message_ids', [])
        if not ids or any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != len(ids):
            raise ValueError('Compaction requires unique replaced message IDs')
        if 'reason' in p and p['reason'] not in ('threshold', 'bytes', 'overflow'):
            raise ValueError('Invalid compaction reason')
        if 'tokens_before' in p and (type(p['tokens_before']) is not int or p['tokens_before'] < 0):
            raise ValueError('compaction.tokens_before must be a nonnegative integer')
        return {'summary': str, 'replaced_message_ids': list}
