"""Bot utterance event."""
from cota.events.common import EventType
from cota.events.event import Event


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

    def _validate_payload(self):
        if 'attachments' in self.payload:
            from cota.files import validate_attachments
            validate_attachments(self.payload['attachments'])
        return {'text': str}
