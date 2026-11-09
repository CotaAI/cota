import pytest

from cota.webapp.registry import ChatRegistry
from cota.webapp.access import ChatAccess


@pytest.mark.asyncio
async def test_identity_membership_invitation_and_restart(tmp_path):
    registry = ChatRegistry(tmp_path / 'chat.db', mode='group')
    access = ChatAccess(registry, tmp_path / 'chat.key')
    alice = await access.create_guest('Alice')
    bob = await access.create_guest('Bob')
    assert await access.authenticate(alice['token']) == alice['user_id']
    room = await registry.create_conversation(alice['user_id'], 'Team')
    sid = room['session_id']
    await access.authorize(alice['user_id'], sid)
    with pytest.raises(PermissionError):
        await access.authorize(bob['user_id'], sid)
    invitation = await registry.invite(alice['user_id'], sid)
    assert (await registry.join(bob['user_id'], invitation['invite']))['session_id'] == sid
    await registry.join(bob['user_id'], invitation['invite'])
    assert len((await registry.conversation(bob['user_id'], sid))['members']) == 2
    recreated = ChatRegistry(tmp_path / 'chat.db', mode='group')
    restored = ChatAccess(recreated, tmp_path / 'chat.key')
    assert await restored.authenticate(bob['token']) == bob['user_id']
    await restored.authorize(bob['user_id'], sid)
    assert (await recreated.list_conversations(bob['user_id']))['conversations'] == [room]
    with pytest.raises(PermissionError):
        await recreated.invite(bob['user_id'], sid)
    with pytest.raises(PermissionError):
        await recreated.remove(bob['user_id'], sid, alice['user_id'])
    await recreated.remove(alice['user_id'], sid, bob['user_id'])
    with pytest.raises(PermissionError):
        await restored.authorize(bob['user_id'], sid)
    with pytest.raises(PermissionError):
        await recreated.join(bob['user_id'], invitation['invite'])


@pytest.mark.asyncio
async def test_invite_rotation_expiry_and_owner_cannot_leave(tmp_path):
    import sqlite3
    registry = ChatRegistry(tmp_path / 'chat.db', mode='group')
    for user in ('alice', 'bob'):
        await registry.add_user(user, user)
    sid = (await registry.create_conversation('alice', 'Room'))['session_id']
    old = await registry.invite('alice', sid)
    current = await registry.invite('alice', sid)
    with pytest.raises(PermissionError):
        await registry.join('bob', old['invite'])
    with sqlite3.connect(tmp_path / 'chat.db') as db:
        row = db.execute('SELECT invite_digest FROM conversations').fetchone()
        assert row[0] != current['invite']
        db.execute('UPDATE conversations SET invite_expires = 1')
    with pytest.raises(PermissionError):
        await registry.join('bob', current['invite'])
    with pytest.raises(ValueError):
        await registry.leave('alice', sid)
    with pytest.raises(ValueError):
        await registry.remove('alice', sid, 'alice')


@pytest.mark.asyncio
async def test_direct_is_private_and_pagination_validated(tmp_path):
    registry = ChatRegistry(tmp_path / 'chat.db', mode='direct')
    await registry.add_user('alice', 'Alice')
    await registry.add_user('bob', 'Bob')
    rooms = [await registry.create_conversation('alice', str(i)) for i in range(3)]
    page = await registry.list_conversations('alice', limit=2)
    assert len(page['conversations']) == 2 and page['has_more']
    assert len((await registry.list_conversations('alice', offset=2, limit=2))['conversations']) == 1
    assert (await registry.list_conversations('bob'))['conversations'] == []
    with pytest.raises(PermissionError):
        await registry.conversation('bob', rooms[0]['session_id'])
    with pytest.raises(ValueError):
        await registry.invite('alice', rooms[0]['session_id'])
    for kwargs in ({'limit': 0}, {'limit': 101}, {'offset': -1}, {'limit': True}):
        with pytest.raises(ValueError):
            await registry.list_conversations('alice', **kwargs)
    with pytest.raises(PermissionError):
        await registry.create_conversation('unknown', 'not a user')
    with pytest.raises(ValueError):
        await registry.create_conversation('alice', ' ')
    group = ChatRegistry(tmp_path / 'chat.db', mode='group')
    with pytest.raises(PermissionError):
        await group.authorize('alice', rooms[0]['session_id'])


@pytest.mark.asyncio
async def test_leave_revokes_membership_and_old_invite(tmp_path):
    registry = ChatRegistry(tmp_path / 'chat.db', mode='group')
    for user in ('alice', 'bob'):
        await registry.add_user(user, user)
    sid = (await registry.create_conversation('alice', 'Room'))['session_id']
    invitation = await registry.invite('alice', sid)
    await registry.join('bob', invitation['invite'])
    await registry.leave('bob', sid)
    with pytest.raises(PermissionError):
        await registry.authorize('bob', sid)
    assert (await registry.list_conversations('bob'))['conversations'] == []
    with pytest.raises(PermissionError):
        await registry.join('bob', invitation['invite'])


@pytest.mark.asyncio
async def test_read_cursor_is_authorized_monotonic_and_persistent(tmp_path):
    path = tmp_path / 'chat.db'
    registry = ChatRegistry(path, mode='group')
    for user in ('alice', 'bob'):
        await registry.add_user(user, user)
    sid = (await registry.create_conversation('alice', 'Room'))['session_id']
    assert await registry.read_cursor('alice', sid) == 0
    assert await registry.mark_read('alice', sid, 10) == 10
    assert await registry.mark_read('alice', sid, 2) == 10
    assert await ChatRegistry(path, mode='group').read_cursor('alice', sid) == 10
    for cursor in (-1, True, '2', 2**63):
        with pytest.raises(ValueError):
            await registry.mark_read('alice', sid, cursor)
    with pytest.raises(PermissionError):
        await registry.mark_read('bob', sid, 10)
    with pytest.raises(PermissionError):
        await registry.read_cursor('bob', sid)
