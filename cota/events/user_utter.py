"""User utterance event."""
from cota.events.common import EventType
from cota.events.event import Event


class UserUtterEvent(Event):
    def __init__(self, text: str, metadata=None, *, attachments=None, **kw):
        payload = {'text': text, 'metadata': metadata or {}}
        if attachments is not None:
            from cota.files import validate_attachments
            attachments = validate_attachments(attachments)
        if attachments:
            payload['attachments'] = attachments
        super().__init__(EventType.USER_UTTER, payload, **kw)

    def _validate_payload(self):
        if 'attachments' in self.payload:
            from cota.files import validate_attachments
            validate_attachments(self.payload['attachments'])
        return {'text': str}
