"""Service debug reads persisted sessions without a live Shell/Processor."""
import json
from types import SimpleNamespace

import pytest

from cota.debug.inspector import Inspector
from cota.debug.server import DebugServer
from cota.dst import DST
from cota.events import UserUtterEvent, BotUtterEvent
from cota.store import MemoryStore, SQLStore
from tests.test_debug_viewer import request_debug


@pytest.fixture(params=['memory', 'sqlite'])
def store(request, tmp_path):
    value = MemoryStore() if request.param == 'memory' else SQLStore(db=str(tmp_path / 'service.db'))
    yield value
    if hasattr(value, 'engine'):
        value.engine.dispose()


@pytest.mark.asyncio
async def test_session_page_is_bounded_without_restoring_dst(store, monkeypatch):
    for name in ('partner:a', 'partner:b', 'web:c'):
        dst = DST(name, None)
        dst.append_event(UserUtterEvent(name))
        await store.save(dst)
    def forbidden(*args, **kwargs):
        raise AssertionError('Listing sessions must not reconstruct history')
    monkeypatch.setattr(store, 'load', forbidden)
    first = await store.session_page(limit=2)
    assert [r['session_id'] for r in first['sessions']] == ['partner:a', 'partner:b']
    assert first['has_more']
    second = await store.session_page(after=first['cursor'], limit=2)
    assert [r['session_id'] for r in second['sessions']] == ['web:c']
    assert not second['has_more']
    with pytest.raises(ValueError):
        await store.session_page(limit=100000)


@pytest.mark.asyncio
async def test_service_viewer_selects_session_and_reads_delivery_without_mutation(store):
    dst = DST('partner:room', None)
    dst.append_event(UserUtterEvent('hello'))
    reply = BotUtterEvent('answer')
    dst.append_event(reply)
    await store.save(dst, delivery_target={'channel': 'partner', 'scope': 'app-one', 'chat_id': 'room'})
    inspector = Inspector(SimpleNamespace(name='test', store=store, workspace_path='/tmp'))
    viewer = DebugServer(inspector)
    prefix = '/' + viewer.token
    sessions = await request_debug(viewer, prefix + '/api/sessions?limit=1')
    assert json.loads(sessions.text)['sessions'][0]['session_id'] == 'partner:room'
    events = await request_debug(viewer, prefix + '/api/events?session_id=partner%3Aroom')
    assert json.loads(events.text)['after_sequence'] == 2
    deliveries = await request_debug(viewer, prefix + '/api/deliveries?session_id=partner%3Aroom')
    row = json.loads(deliveries.text)['deliveries'][0]
    assert row['event_id'] == reply.event_id
    assert row['status'] == 'pending'
    assert row['attempts'] == 0
    assert inspector.session_id is None
    assert (await store.delivery(dst.session_id, reply.event_id))['attempts'] == 0
    state = await request_debug(viewer, prefix + '/api/state?session_id=partner%3Aroom&source=stored')
    assert json.loads(state.text)['available']
    assert (await request_debug(viewer, prefix + '/api/sessions?limit=100000')).status == 400
