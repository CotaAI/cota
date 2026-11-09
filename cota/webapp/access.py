"""Visitor identity and application membership adapter for the public Web API."""
from cota.channels.web.access import GuestAccess
from .registry import text


class ChatAccess:
    # Core /api/guests and /api/conversations must not bypass this app's registry.
    allow_guests = False

    def __init__(self, registry, key_path):
        self.registry = registry
        self.credentials = GuestAccess(key_path)

    async def create_guest(self, name):
        name = text(name, 'name', 60)
        identity = await self.credentials.create_guest()
        await self.registry.add_user(identity['user_id'], name)
        return {**identity, 'name': name}

    async def authenticate(self, token):
        user_id = await self.credentials.authenticate(token)
        await self.registry.user(user_id)
        return user_id

    async def authorize(self, user_id, session_id):
        await self.registry.authorize(user_id, session_id)
