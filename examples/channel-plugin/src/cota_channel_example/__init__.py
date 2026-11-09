"""Generic gateway protocol example, independent of any real IM provider."""
import asyncio
import hashlib
import hmac
import json
from urllib.parse import urlsplit
from uuid import NAMESPACE_URL, uuid5

import httpx
from sanic import Blueprint, response

from cota.application import ApplicationUnavailable
from cota.channels import BaseChannel, InboundMessage
from cota.inputs import InputConflict, message_id


def _text(value, field, limit=255):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f'{field} must be nonempty text of at most {limit} characters')
    return value


class ExampleIMChannel(BaseChannel):
    """HMAC-authenticated input and idempotent REST output through a gateway.

    The trusted gateway must authenticate platform users, enforce membership,
    and supply stable message IDs. This is not an implementation of SeaTalk or
    any other provider's native callback, authentication, or message API.
    """

    name = 'example_im'
    durable_delivery = True

    def __init__(self, config, bus):
        super().__init__(config, bus)
        self._client = None

    @property
    def delivery_scope(self):
        return self.config.get('app_id')

    def validate(self):
        for key in ('app_id', 'webhook_secret', 'api_base', 'api_token'):
            _text(self.config.get(key), key, 4096 if key != 'app_id' else 255)
        try:
            url = urlsplit(self.config['api_base'])
            valid = (url.scheme in ('http', 'https') and url.hostname and
                     not url.username and not url.password and not url.query and not url.fragment)
            _ = url.port
        except ValueError:
            valid = False
        if not valid:
            raise ValueError('api_base must be an HTTP(S) base URL without credentials, query, or fragment')

    async def start(self):
        if self._running:
            return
        self.validate()
        self._client = httpx.AsyncClient(timeout=10.0)
        self._running = True

    async def stop(self):
        self._running = False
        await self.cancel_tasks()
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _scoped_id(self, kind, value):
        identity = json.dumps([self.name, self.config['app_id'], kind, value], ensure_ascii=False)
        return f'{self.name}:{kind}:{uuid5(NAMESPACE_URL, identity).hex}'

    def _inbound(self, payload):
        if not isinstance(payload, dict):
            raise ValueError('payload must be an object')
        user = _text(payload.get('user_id'), 'user_id')
        chat = _text(payload.get('chat_id'), 'chat_id')
        text = _text(payload.get('text'), 'text', 32768)
        # Native platform IDs are required: do not generate a fresh ID on retry.
        platform_id = _text(payload.get('message_id'), 'message_id')
        mode = self.context.dialogue_mode
        return InboundMessage(
            channel=self.name, sender_id=self._scoped_id('user', user), chat_id=chat,
            content=text, message_id=message_id(platform_id),
            session_key_override=self._scoped_id(mode, chat),
            conversation_type=mode, mentioned=payload.get('mentioned', False),
            sender_name=payload.get('sender_name'), reply_to=payload.get('reply_to'),
        )

    def http_blueprint(self):
        blueprint = Blueprint('example_im_' + self.name)

        @blueprint.post('/webhook')
        async def webhook(request):
            signature = request.headers.get('X-Signature', '')
            expected = hmac.new(self.config['webhook_secret'].encode(), request.body,
                                hashlib.sha256).hexdigest()
            if not isinstance(signature, str) or not hmac.compare_digest(signature.encode(), expected.encode()):
                return response.json({'error': 'invalid_signature'}, status=401)
            try:
                inbound = self._inbound(json.loads(request.body))
            except (ValueError, TypeError, UnicodeDecodeError):
                return response.json({'error': 'invalid_payload'}, status=400)
            try:
                submission = await self.receive(inbound)
                receipt = await submission.receipt()
                if receipt is None:
                    raise ApplicationUnavailable('Persistence receipt unavailable')
            except InputConflict:
                return response.json({'error': 'message_id_conflict'}, status=409)
            except (asyncio.QueueFull, ApplicationUnavailable):
                return response.json({'error': 'retry_same_message_id'}, status=503,
                                     headers={'Retry-After': '1'})
            return response.json({'message_id': submission.message_id,
                                  'duplicate': submission.duplicate, 'receipt': receipt}, status=202)

        return blueprint

    async def send(self, message):
        if not self._running or self._client is None:
            raise RuntimeError('ExampleIMChannel must be started before sending')
        event_id = _text(message.event_id, 'event_id')
        result = await self._client.post(
            self.config['api_base'].rstrip('/') + '/messages',
            headers={'Authorization': 'Bearer ' + self.config['api_token'],
                     'Idempotency-Key': event_id},
            json={'app_id': self.config['app_id'], 'chat_id': message.chat_id,
                  'text': message.content, 'event_id': event_id},
        )
        # DeliveryDispatcher owns retries. A failed send must remain a failure.
        result.raise_for_status()
