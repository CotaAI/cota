"""Optional Web application access adapters; neither adapter uses Store tables.

Embedded applications supply authentication and conversation authorization.
The standalone guest adapter uses signed credentials and signed session IDs.
"""
import asyncio
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import tempfile
import time
from uuid import uuid4


def valid_identity(value):
    if not isinstance(value, str) or not value or len(value) > 255:
        raise PermissionError('Invalid identity or conversation')
    return value


class ExternalAccess:
    allow_guests = False

    def __init__(self, authenticate, authorize):
        if not callable(authenticate) or not callable(authorize):
            raise ValueError('External Web access requires both authenticate(token) and authorize(user_id, session_id)')
        self._authenticate, self._authorize = authenticate, authorize

    async def authenticate(self, token):
        return valid_identity(await self._authenticate(token))

    async def authorize(self, user_id, session_id):
        valid_identity(user_id)
        valid_identity(session_id)
        # A permission check must explicitly grant access; fail closed on None.
        if await self._authorize(user_id, session_id) is not True:
            raise PermissionError('Conversation not accessible')


class GuestAccess:
    """Convenience application adapter, not a Cota identity/account database.

    The private signing key must stay with the deployment, not a shared Bot package.
    Rotating/deleting it invalidates all issued guest credentials and session IDs.
    """
    allow_guests = True

    def __init__(self, key_path):
        self.key_path = Path(key_path)
        self._key = None
        self._lock = asyncio.Lock()

    def _load_key(self):
        path = self.key_path
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            # Publish a complete key atomically, even if two app instances start.
            fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.web-key-')
            try:
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(secrets.token_bytes(32))
                try:
                    os.link(temporary, path)
                except FileExistsError:
                    pass
            finally:
                os.unlink(temporary)
        key = path.read_bytes()
        if len(key) != 32:
            raise ValueError('Invalid standalone Web signing key')
        return key

    async def _secret(self):
        async with self._lock:
            if self._key is None:
                self._key = await asyncio.to_thread(self._load_key)
        return self._key

    async def _signature(self, purpose, value):
        return hmac.new(await self._secret(), (purpose + ':' + value).encode(), hashlib.sha256).hexdigest()

    async def create_guest(self):
        user_id = 'guest:' + uuid4().hex
        expires_at = int(time.time()) + 30 * 86400
        payload = base64.urlsafe_b64encode(json.dumps([user_id, expires_at]).encode()).decode().rstrip('=')
        return {'user_id': user_id, 'expires_at': expires_at,
                'token': payload + '.' + await self._signature('guest', payload)}

    async def authenticate(self, token):
        try:
            if not isinstance(token, str) or len(token) > 512:
                raise ValueError('Invalid credential')
            payload, signature = token.split('.')
            expected = await self._signature('guest', payload)
            if not hmac.compare_digest(signature, expected):
                raise ValueError('Invalid signature')
            user_id, expires_at = json.loads(base64.urlsafe_b64decode(payload + '=' * (-len(payload) % 4)))
            if type(expires_at) is not int or expires_at <= time.time():
                raise ValueError('Expired credential')
            return valid_identity(user_id)
        except (ValueError, TypeError):
            raise PermissionError('Invalid or expired credential') from None

    async def create_conversation(self, user_id):
        valid_identity(user_id)
        nonce = uuid4().hex
        return 'web:' + nonce + ':' + await self._signature('session', user_id + ':' + nonce)

    async def authorize(self, user_id, session_id):
        valid_identity(user_id)
        valid_identity(session_id)
        parts = session_id.split(':')
        if len(parts) != 3 or parts[0] != 'web':
            raise PermissionError('Conversation not accessible')
        signature = await self._signature('session', user_id + ':' + parts[1])
        if not hmac.compare_digest(signature.encode(), parts[2].encode()):
            raise PermissionError('Conversation not accessible')


def load_access_factory(reference, config_path):
    """Load a trusted deployment adapter, never code received in a chat message."""
    import importlib
    import importlib.util
    import inspect
    if not isinstance(reference, str) or reference.count(':') != 1:
        raise ValueError('access_factory must be module:factory or ./file.py:factory')
    module_name, name = reference.split(':')
    if module_name.endswith('.py'):
        path = (Path(config_path) / module_name).resolve()
        spec = importlib.util.spec_from_file_location('_cota_access_' + uuid4().hex, path)
        if spec is None or spec.loader is None:
            raise ValueError('Cannot load access_factory file')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    else:
        module = importlib.import_module(module_name)
    factory = getattr(module, name, None)
    if not callable(factory):
        raise ValueError('access_factory must refer to a callable')
    access = factory()
    if inspect.isawaitable(access):
        if inspect.iscoroutine(access):
            access.close()
        raise ValueError('access_factory must be synchronous; its access methods are async')
    if not all(callable(getattr(access, method, None)) for method in ('authenticate', 'authorize')):
        raise ValueError('access_factory must return an authenticate/authorize adapter')
    if type(getattr(access, 'allow_guests', None)) is not bool:
        raise ValueError('access_factory adapter must declare allow_guests')
    if access.allow_guests and not all(callable(getattr(access, method, None)) for method in ('create_guest', 'create_conversation')):
        raise ValueError('Guest access_factory adapter must provide guest/conversation creation')
    return access
