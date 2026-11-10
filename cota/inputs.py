"""Transport-independent input identity; durable facts remain ordinary events."""

from copy import deepcopy
from hashlib import sha256
from uuid import uuid4


class InputConflict(ValueError):
    """A message_id was reused for different input in the same session."""


def message_id(value=None):
    if value is None:
        return uuid4().hex
    if not isinstance(value, str) or not value.strip() or len(value) > 255:
        raise ValueError('message_id must be a nonempty string of at most 255 characters')
    return value


def input_event_id(value):
    return 'input-' + sha256(message_id(value).encode('utf-8')).hexdigest()


def input_key(message):
    session_id = getattr(message, 'session_key', None) or message.session_id
    return session_id, message_id(message.message_id)


def canonical_input(message):
    """Transport, timestamps and delivery metadata do not change user input."""
    if hasattr(message, 'content'):
        value = deepcopy({'sender': 'user', 'sender_id': message.sender_id,
                         'text': message.content or '', 'media': message.media, 'execute': True})
        if getattr(message, 'attachments', None):
            value['attachments'] = deepcopy(message.attachments)
        if getattr(message, 'conversation_type', None) == 'group':
            value.pop('execute')
            value.update(mode='group', mentioned=message.mentioned, reply_to=message.reply_to,
                         sender_name=message.sender_name)
        return value
    value = deepcopy({'sender': message.sender or 'user', 'sender_id': message.sender_id,
                     'text': message.text or '', 'media': (message.metadata or {}).get('media', []),
                     'execute': message.receiver == 'bot'})
    if getattr(message, 'attachments', None):
        value['attachments'] = deepcopy(message.attachments)
    return value


def event_input(event):
    payload = event['payload']
    metadata = payload.get('metadata') or {}
    value = {'sender': metadata.get('sender', 'user'), 'sender_id': metadata.get('sender_id'),
            'text': payload.get('text', ''), 'media': metadata.get('media', []),
            'execute': metadata.get('execute', True)}
    if payload.get('attachments'):
        value['attachments'] = deepcopy(payload['attachments'])

    if metadata.get('mode') == 'group':
        value.pop('execute')
        value.update(mode='group', mentioned=metadata.get('mentioned', False),
                     reply_to=metadata.get('reply_to'), sender_name=metadata.get('sender_name'))
    return value
