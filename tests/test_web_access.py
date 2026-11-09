import pytest

from cota.channels.web.access import ExternalAccess, GuestAccess


@pytest.mark.asyncio
async def test_guest_access_is_stateless_and_restarts_with_same_key(tmp_path):
    access = GuestAccess(tmp_path / 'web.key')
    guest = await access.create_guest()
    session = await access.create_conversation(guest['user_id'])
    restored = GuestAccess(tmp_path / 'web.key')
    assert await restored.authenticate(guest['token']) == guest['user_id']
    await restored.authorize(guest['user_id'], session)
    with pytest.raises(PermissionError):
        await restored.authorize('another-user', session)
    with pytest.raises(PermissionError):
        await restored.authenticate(guest['token'] + 'bad')
    with pytest.raises(PermissionError):
        await restored.authorize(guest['user_id'], session + 'bad')
    assert list(tmp_path.iterdir()) == [tmp_path / 'web.key']


@pytest.mark.asyncio
async def test_external_application_owns_identity_and_session_permissions():
    calls = []
    async def authenticate(token):
        if token != 'app-token':
            raise PermissionError('invalid')
        return 'app-user'
    async def authorize(user, session):
        calls.append((user, session))
        return user == 'app-user' and session == 'app-session'
    access = ExternalAccess(authenticate, authorize)
    user = await access.authenticate('app-token')
    await access.authorize(user, 'app-session')
    with pytest.raises(PermissionError):
        await access.authorize(user, 'foreign-session')
    assert calls == [('app-user', 'app-session'), ('app-user', 'foreign-session')]
    assert access.allow_guests is False
    with pytest.raises(ValueError):
        ExternalAccess(authenticate, None)
