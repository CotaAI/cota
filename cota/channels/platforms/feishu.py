"""Feishu direct/group text adapter; official SDK owns the connection protocol."""
import asyncio
from contextlib import suppress
import importlib.util
import json
from pathlib import Path
import sys
import time
from uuid import NAMESPACE_URL, uuid4, uuid5

import httpx
from loguru import logger

from ..base import BaseChannel
from ..events import InboundMessage, OutboundMessage


class _TransientHTTPError(RuntimeError):
    """A retryable Feishu status, without response payload or credentials."""


class FeishuChannel(BaseChannel):
    name = 'feishu'
    durable_delivery = True
    startup_ready = True
    startup_timeout = 35

    def __init__(self, config, bus):
        super().__init__(config, bus)
        self.app_id = config.get('app_id', '')
        self.app_secret = config.get('app_secret', '')
        self.dialogue_mode = config.get('dialogue_mode', 'direct')
        if self.dialogue_mode not in ('direct', 'group'):
            raise ValueError('Feishu dialogue_mode must be direct or group')
        self._bot_open_id = None
        self._process = None
        self._reader = None
        self._http_client = None
        self._tenant_access_token = None
        self._token_expires_at = 0
        self._token_lock = asyncio.Lock()
        self._ready = None
        self._connected = False

    @property
    def delivery_scope(self):
        return self.app_id

    @property
    def is_running(self):
        return self._running and self._connected and self._process is not None and self._process.returncode is None

    async def start(self):
        if self._running:
            return
        if not self.app_id or not self.app_secret:
            raise ValueError('Feishu app_id and app_secret are required')
        if importlib.util.find_spec('lark_oapi') is None:
            raise ImportError('Feishu requires the official SDK: pip install "cota[feishu]"')
        self._http_client = httpx.AsyncClient(timeout=5.0)
        self._ready = asyncio.get_running_loop().create_future()
        try:
            if self.dialogue_mode == 'group':
                await self._load_bot_identity()
            # Credentials travel through stdin, never argv or the environment.
            self._process = await asyncio.create_subprocess_exec(
                sys.executable, '-u', str(Path(__file__).with_name('feishu_worker.py')),
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL, limit=256 * 1024)
            self._running = True
            self._process.stdin.write((json.dumps({'app_id': self.app_id, 'app_secret': self.app_secret}) + '\n').encode())
            await self._process.stdin.drain()
            self._reader = asyncio.create_task(self._read_worker())
            await asyncio.wait_for(asyncio.shield(self._ready), 30)
        except BaseException:
            await self.stop()
            raise

    async def _read_worker(self):
        try:
            while self._running:
                raw = await self._process.stdout.readline()
                if not raw:
                    raise RuntimeError('Feishu SDK process exited')
                frame = json.loads(raw)
                kind = frame.get('type')
                if kind == 'ready':
                    self._connected = True
                    if not self._ready.done():
                        self._ready.set_result(None)
                elif kind == 'reconnecting':
                    self._connected = False
                    logger.warning('Feishu connection interrupted; official SDK is reconnecting')
                elif kind == 'event':
                    accepted = False
                    try:
                        # Acknowledge admission, not completion of a model turn.
                        await asyncio.wait_for(self._on_event(frame['event']), 1)
                        accepted = True  # ignored events are intentionally acknowledged too
                    except Exception as error:
                        logger.warning('Feishu input not admitted ({})', type(error).__name__)
                    self._process.stdin.write((json.dumps({'id': frame['id'], 'accepted': accepted}) + '\n').encode())
                    await self._process.stdin.drain()
                elif kind == 'error':
                    # Worker only exposes a class name, never SDK payloads/credentials.
                    raise RuntimeError('Feishu SDK failed: ' + str(frame.get('error_type', 'unknown')))
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self._connected = False
            self._running = False
            if self._ready is not None and not self._ready.done():
                self._ready.set_exception(error)
            else:
                logger.error('Feishu listener stopped ({})', type(error).__name__)

    async def stop(self):
        self._running = self._connected = False
        if self._ready is not None and not self._ready.done():
            self._ready.cancel()
        if self._reader:
            self._reader.cancel()
            await asyncio.gather(self._reader, return_exceptions=True)
            self._reader = None
        if self._process:
            if self._process.returncode is None:
                with suppress(ProcessLookupError):
                    self._process.terminate()
                try:
                    await asyncio.wait_for(self._process.wait(), 2)
                except asyncio.TimeoutError:
                    with suppress(ProcessLookupError):
                        self._process.kill()
                    await self._process.wait()
            self._process = None
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None

    async def _on_event(self, data):
        """Only official SDK user text for the configured mode becomes input."""
        if not isinstance(data, dict):
            return False
        header, event = data.get('header') or {}, data.get('event') or {}
        if not isinstance(header, dict) or not isinstance(event, dict):
            return False
        if header.get('event_type') != 'im.message.receive_v1' or header.get('app_id') != self.app_id:
            return False
        sender, message = event.get('sender') or {}, event.get('message') or {}
        if not isinstance(sender, dict) or not isinstance(message, dict):
            return False
        chat_type = 'group' if self.dialogue_mode == 'group' else 'p2p'
        if sender.get('sender_type') != 'user' or message.get('chat_type') != chat_type or message.get('message_type') != 'text':
            return False
        sender_id = sender.get('sender_id') or {}
        if not isinstance(sender_id, dict):
            return False
        user = sender_id.get('open_id')
        tenant = header.get('tenant_key') or sender.get('tenant_key')
        chat, message_id = message.get('chat_id'), message.get('message_id')
        if any(not isinstance(value, str) or not value or ':' in value for value in (self.app_id, tenant, user, chat, message_id)):
            return False
        if not self.is_allowed(user):
            return False
        try:
            text = json.loads(message.get('content', ''))['text']
        except (ValueError, TypeError, KeyError):
            return False
        if not isinstance(text, str) or not text.strip() or len(text) > 32768:
            return False
        mentioned = False
        if self.dialogue_mode == 'group':
            if not self._bot_open_id:
                raise RuntimeError('Feishu group bot identity has not been resolved')
            mentions = message.get('mentions') or []
            if not isinstance(mentions, list):
                return False
            mentioned = any(isinstance(item, dict) and isinstance(item.get('id'), dict)
                            and item['id'].get('open_id') == self._bot_open_id for item in mentions)
        reply_to = message.get('parent_id') or None
        if reply_to is not None and (not isinstance(reply_to, str) or not reply_to.strip() or len(reply_to) > 255):
            return False
        user_id = f'feishu:{self.app_id}:{tenant}:{user}'
        session_id = f'feishu:{self.app_id}:{tenant}:{chat_type}:{chat}'
        if max(len(user_id), len(session_id), len(message_id)) > 255:
            return False
        await self.bus.publish_inbound(InboundMessage(
            channel=self.name, sender_id=user_id, chat_id=chat, content=text,
            message_id=message_id, session_key_override=session_id,
            mentioned=mentioned, reply_to=reply_to, conversation_type=self.dialogue_mode,
            metadata={'platform_user_id': user, 'tenant_key': tenant, 'chat_type': chat_type}))
        return True

    async def _load_bot_identity(self):
        """Resolve this application's mention identity using its tenant token.

        Official API: https://open.feishu.cn/document/client-docs/bot-v3/obtain-bot-info
        Names and textual @ placeholders cannot identify the current bot.
        """
        token = await self._get_tenant_access_token()
        response = await self._http_client.get('https://open.feishu.cn/open-apis/bot/v3/info',
                                               headers={'Authorization': f'Bearer {token}'})
        bot = self._response(response).get('bot')
        identity = bot.get('open_id') if isinstance(bot, dict) else None
        if not isinstance(identity, str) or not identity.strip() or len(identity) > 255:
            raise RuntimeError('Feishu bot response is missing open_id')
        self._bot_open_id = identity

    async def _get_tenant_access_token(self):
        async with self._token_lock:
            if self._tenant_access_token and time.monotonic() < self._token_expires_at:
                return self._tenant_access_token
            result = await self._http_client.post(
                'https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal',
                json={'app_id': self.app_id, 'app_secret': self.app_secret})
            data = self._response(result)
            token = data.get('tenant_access_token')
            if not isinstance(token, str) or not token:
                raise RuntimeError('Feishu token response is missing tenant_access_token')
            self._tenant_access_token = token
            self._token_expires_at = time.monotonic() + max(0, int(data.get('expire', 7200)) - 60)
            return token

    @staticmethod
    def _response(result):
        if result.status_code in (429, 500, 502, 503, 504):
            logger.warning('Feishu transient HTTP error {}', result.status_code)
            raise _TransientHTTPError(f'Feishu HTTP error {result.status_code}')
        if result.status_code != 200:
            logger.warning('Feishu HTTP error {}', result.status_code)
            raise RuntimeError(f'Feishu HTTP error {result.status_code}')
        try:
            data = result.json()
        except ValueError:
            raise RuntimeError('Feishu returned invalid JSON') from None
        if not isinstance(data, dict) or data.get('code') != 0:
            code = data.get('code') if isinstance(data, dict) else 'unknown'
            # Codes aid permission/auth diagnosis without logging response
            # bodies, tokens, message text or signed URLs.
            code = code if type(code) is int else 'unknown'
            logger.warning('Feishu API error {}', code)
            raise RuntimeError(f'Feishu API error {code}')
        return data

    async def send(self, message: OutboundMessage):
        if self._http_client is None:
            raise RuntimeError('Feishu channel is not started')
        if message.media:
            raise ValueError('Feishu currently supports text replies only')
        identity = str(uuid5(NAMESPACE_URL, f'{self.app_id}:{message.session_id}:{message.event_id}')) if message.event_id else str(uuid4())
        for attempt in range(3):
            try:
                token = await self._get_tenant_access_token()
                response = await self._http_client.post(
                    'https://open.feishu.cn/open-apis/im/v1/messages',
                    params={'receive_id_type': 'chat_id'},
                    headers={'Authorization': f'Bearer {token}'},
                    json={'receive_id': message.chat_id, 'msg_type': 'text',
                          'content': json.dumps({'text': message.content}, ensure_ascii=False), 'uuid': identity})
                self._response(response)
                return
            except (httpx.TransportError, _TransientHTTPError) as error:
                if attempt == 2:
                    if isinstance(error, _TransientHTTPError):
                        raise
                    logger.warning('Feishu send transport failure ({})', type(error).__name__)
                    raise RuntimeError('Feishu send transport failure') from None
            await asyncio.sleep(.2 * (attempt + 1))
