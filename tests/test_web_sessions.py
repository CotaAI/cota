"""Web delegates application access and channel-neutral submission state."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa

from cota.channels.web.access import ExternalAccess, GuestAccess
from cota.channels.web.service import WebService
from cota.store import SQLStore
from cota.application import Application


@pytest.mark.asyncio
async def test_web_access_creates_no_application_tables(tmp_path):
    store = SQLStore(db=str(tmp_path / 'store.db'))
    try:
        before = set(sa.inspect(store.engine).get_table_names())
        service = WebService(Application(SimpleNamespace(store=store)),
                             access=GuestAccess(tmp_path / 'web.key'))
        guest = await service.access.create_guest()
        session = await service.access.create_conversation(guest['user_id'])
        await service.authorize(guest['user_id'], session)
        assert (await service.history(guest['user_id'], session))['messages'] == []
        assert set(sa.inspect(store.engine).get_table_names()) == before
        assert not any(name.startswith('web_') for name in before)
    finally:
        store.engine.dispose()


@pytest.mark.asyncio
async def test_external_session_is_accepted_without_local_owner_record(tmp_path):
    from cota.store import MemoryStore
    store = MemoryStore()
    access = ExternalAccess(AsyncMock(return_value='alice'), AsyncMock(return_value=True))
    service = WebService(Application(SimpleNamespace(store=store)), access=access)
    assert (await service.history('alice', 'external:conversation-42'))['messages'] == []
    assert await service.receipt('alice', 'external:conversation-42', 'missing') is None
    assert not hasattr(service, 'repository')
    access._authorize.return_value = False
    with pytest.raises(PermissionError):
        await service.history('alice', 'external:conversation-42')


@pytest.mark.asyncio
async def test_service_close_does_not_wait_for_or_cancel_stalled_executor():
    import asyncio
    from cota.store import MemoryStore
    access = ExternalAccess(AsyncMock(return_value='alice'), AsyncMock(return_value=True))
    service = WebService(Application(SimpleNamespace(store=MemoryStore())), access=access)
    service.transport = SimpleNamespace(publish=AsyncMock())
    execution = asyncio.get_running_loop().create_future()
    observer = asyncio.create_task(service._observe('session', 'message', execution))
    service._watchers.add(observer)
    service._observed.add(execution)
    await asyncio.sleep(0)
    try:
        await asyncio.wait_for(service.close(), .1)
        assert not execution.done()
        service.transport.publish.assert_not_called()
    finally:
        observer.cancel()
        execution.cancel()
        await asyncio.gather(observer, return_exceptions=True)
