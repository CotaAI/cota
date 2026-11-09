"""Read-only inspection must stay bounded and never alter the running Bot."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa

from cota.dst import DST
from cota.events import Event, UserUtterEvent, ToolResultEvent
from cota.store import MemoryStore, SQLStore


@pytest.fixture(params=['memory', 'sqlite'])
def store(request, tmp_path):
    value = MemoryStore() if request.param == 'memory' else SQLStore(db=str(tmp_path / 'debug.db'))
    yield value
    if isinstance(value, SQLStore):
        value.engine.dispose()


async def seed(store):
    dst = DST('cmdline:test', None)
    dst.append_event(UserUtterEvent('weather?'))
    dst.append_event(Event('run_started', {'input_event_id': dst.latest_user_event.event_id}, run_id='r'))
    dst.append_event(Event('tool_started', {'tool_call_id': 'call', 'tool': 'read', 'arguments': {'large': 'x' * 10000}}))
    await store.save(dst)
    return dst


@pytest.mark.asyncio
async def test_header_pagination_is_small_detached_and_ordered(store):
    dst = await seed(store)
    headers = await store.event_headers(dst.session_id, after_sequence=1, limit=1)
    assert len(headers) == 1 and headers[0]['sequence'] == 2
    assert 'payload' not in headers[0]
    assert headers[0]['summary']['input_event_id'] == dst.events[0].event_id
    header = (await store.event_headers(dst.session_id, after_sequence=2))[0]
    assert header['summary'] == {'tool_call_id': 'call', 'tool': 'read'}
    header['summary']['tool'] = 'edited'
    assert (await store.events(dst.session_id, after_sequence=2))[0]['payload']['tool'] == 'read'
    assert (await store.session_metadata(dst.session_id))['last_sequence'] == 3
    assert await store.session_metadata('missing') is None
    with pytest.raises(ValueError):
        await store.event_headers(dst.session_id, limit=1001)


@pytest.mark.asyncio
async def test_sql_header_query_does_not_select_full_payload(store):
    if not isinstance(store, SQLStore):
        pytest.skip('SQL projection')
    await seed(store)
    statements = []
    def capture(conn, cursor, statement, parameters, context, many):
        statements.append(statement)
    sa.event.listen(store.engine, 'before_cursor_execute', capture)
    try:
        await store.event_headers('cmdline:test')
        await store.session_metadata('cmdline:test')
    finally:
        sa.event.remove(store.engine, 'before_cursor_execute', capture)
    assert not any(', events.payload,' in sql or 'SELECT events.payload' in sql for sql in statements)
    assert any('json_extract' in sql.lower() for sql in statements)


@pytest.mark.asyncio
async def test_inspector_separates_live_stored_and_snapshot_and_is_read_only(store):
    from cota.debug.inspector import Inspector
    dst = await seed(store)
    agent = SimpleNamespace(name='test', store=store, workspace_path='/tmp/workspace')
    inspector = Inspector(agent, dst.session_id, lambda: dst)
    before = await store.export_session(dst.session_id)
    dst.update_user('alice', {'city': '北京'})
    live = await inspector.state('live')
    saved = await inspector.state('stored')
    assert live['source'] == 'live' and live['last_sequence'] == 4
    assert saved['source'] == 'stored' and saved['last_sequence'] == 3
    assert saved['state']['user_context'] == {}
    assert live['state']['user_context'] == {'city': '北京'}
    assert (await inspector.state('snapshot'))['available'] is False
    live['state']['user_context'].clear()
    assert dst.get_user_pref('city') == '北京'
    assert (await inspector.event(3))['payload']['arguments']['large'] == 'x' * 10000
    assert await store.export_session(dst.session_id) == before
    with pytest.raises(LookupError):
        await inspector.event(100)
    with pytest.raises(ValueError):
        await inspector.state('unknown')


@pytest.mark.asyncio
async def test_empty_and_snapshot_views_have_explicit_sources(store):
    from cota.debug.inspector import Inspector
    agent = SimpleNamespace(name='test', store=store, workspace_path='/tmp/workspace')
    inspector = Inspector(agent, 'cmdline:test', lambda: None)
    assert (await inspector.state('stored'))['available'] is False
    assert (await inspector.state('live'))['available'] is False
    assert await store.session_metadata('cmdline:test') is None
    dst = await seed(store)
    dst.append_event(Event('run_finished', {'status': 'completed'}))
    await store.save(dst)
    snapshot = await inspector.state('snapshot')
    assert snapshot['source'] == 'snapshot'
    assert snapshot['last_sequence'] == 4
    assert snapshot['state']['execution']['status'] == 'completed'


@pytest.mark.asyncio
async def test_state_reconstruction_does_not_block_event_loop(store, monkeypatch):
    import threading
    await seed(store)
    original = DST.from_events
    threads = []
    def record(*args, **kwargs):
        threads.append(threading.get_ident())
        return original(*args, **kwargs)
    monkeypatch.setattr(DST, 'from_events', record)
    await store.inspect_state('cmdline:test')
    assert threads and all(t != threading.get_ident() for t in threads)


async def request_debug(viewer, path, *, method='GET', headers=None):
    from aiohttp.test_utils import make_mocked_request
    viewer.origin = 'http://127.0.0.1:8123'
    if not viewer.app.frozen:
        viewer.app.freeze()
    request = make_mocked_request(method, path, headers={'Host': '127.0.0.1:8123', **(headers or {})}, app=viewer.app)
    return await viewer.app._handle(request)


@pytest.mark.asyncio
async def test_http_routes_are_read_only_and_protect_local_data(store):
    import json
    from cota.debug.inspector import Inspector
    from cota.debug.server import DebugServer
    dst = await seed(store)
    inspector = Inspector(SimpleNamespace(name='test', store=store, workspace_path='/tmp'), dst.session_id, lambda: dst)
    viewer = DebugServer(inspector)
    prefix = '/' + viewer.token
    assert (await request_debug(viewer, prefix + '/api/info')).status == 200
    events = await request_debug(viewer, prefix + '/api/events?after=1&limit=1')
    assert json.loads(events.text)['after_sequence'] == 2
    assert (await request_debug(viewer, prefix + '/api/event/3')).status == 200
    assert (await request_debug(viewer, prefix + '/api/state?source=live')).status == 200
    assert (await request_debug(viewer, '/wrong/api/info')).status == 404
    assert (await request_debug(viewer, prefix + '/api/info', method='POST')).status == 405
    assert (await request_debug(viewer, prefix + '/api/events?limit=100000')).status == 400
    assert (await request_debug(viewer, prefix + '/api/event/999')).status == 404
    assert (await request_debug(viewer, prefix + '/api/info', headers={'Origin': 'https://evil.test'})).status == 403
    assert (await request_debug(viewer, prefix + '/api/info', headers={'Host': 'evil.test'})).status == 403
    assert (await request_debug(viewer, prefix + '/api/info', headers={'Sec-Fetch-Site': 'cross-site'})).status == 403
    assert events.headers['Cache-Control'] == 'no-store'
    assert 'frame-ancestors' in events.headers['Content-Security-Policy']
    assert len(dst.events) == 3


@pytest.mark.asyncio
async def test_debug_query_errors_do_not_change_store(store, monkeypatch):
    from cota.debug.inspector import Inspector
    from cota.debug.server import DebugServer
    dst = await seed(store)
    inspector = Inspector(SimpleNamespace(name='test', store=store, workspace_path='/tmp'), dst.session_id, lambda: dst)
    viewer = DebugServer(inspector)
    monkeypatch.setattr(inspector, 'state', AsyncMock(side_effect=RuntimeError('private database detail')))
    response = await request_debug(viewer, '/' + viewer.token + '/api/state')
    assert response.status == 500
    assert 'private database detail' not in response.text
    dst.append_event(UserUtterEvent('still running'))
    await store.save(dst)
    assert (await store.load(dst.session_id)).latest_user_text() == 'still running'


@pytest.mark.asyncio
async def test_debug_does_not_queue_unbounded_queries(store):
    from cota.debug.inspector import Inspector
    from cota.debug.server import DebugServer
    inspector = Inspector(SimpleNamespace(name='test', store=store, workspace_path='/tmp'), 's', lambda: None)
    viewer = DebugServer(inspector)
    async with viewer.query_lock:
        response = await request_debug(viewer, '/' + viewer.token + '/api/info')
    assert response.status == 429


@pytest.mark.asyncio
async def test_real_http_serves_assets_and_closes_socket(tmp_path):
    import aiohttp
    from cota.debug.inspector import Inspector
    from cota.debug.server import DebugServer
    store = MemoryStore()
    dst = await seed(store)
    viewer = DebugServer(Inspector(SimpleNamespace(name='test', store=store, workspace_path=str(tmp_path)), dst.session_id, lambda: dst))
    url = await viewer.start()
    try:
        assert url.startswith('http://127.0.0.1:')
        async with aiohttp.ClientSession() as client:
            for path, content in [('', '<h2>Events</h2>'), ('app.js', 'renderEvents'), ('style.css', '.workspace')]:
                async with client.get(url + path) as response:
                    assert response.status == 200
                    assert content in await response.text()
            async with client.get(url + 'api/events') as response:
                assert (await response.json())['after_sequence'] == 3
    finally:
        await viewer.close()
    async with aiohttp.ClientSession() as client:
        with pytest.raises(aiohttp.ClientConnectionError):
            await client.get(url)


@pytest.mark.asyncio
async def test_header_identity_is_not_truncated_and_summary_types_are_consistent(store):
    dst = DST('ids', None)
    call_id = 'c' * 250
    dst.append_event(Event('tool_started', {'tool_call_id': call_id, 'tool': 'read', 'arguments': {}}))
    dst.append_event(ToolResultEvent('read', tool_call_id=call_id, content=[]))
    await store.save(dst)
    headers = await store.event_headers('ids')
    assert headers[0]['summary']['tool_call_id'] == call_id
    assert headers[1]['summary']['status'] == 'success'


@pytest.mark.asyncio
async def test_model_diagnostics_route_is_separate_from_events(store, tmp_path):
    import json
    from cota.debug.inspector import Inspector
    from cota.debug.server import DebugServer
    dst = await seed(store)
    store.enable_debug_log(tmp_path / 'debug.log')
    before = await store.export_session(dst.session_id)
    data = {'request_id': 'q', 'run_id': 'r', 'purpose': 'dialogue', 'status': 'running',
            'started_at': 1, 'request': {'messages': [{'role': 'system', 'content': 'private prompt'}]}}
    await store.save_model_debug(dst.session_id, 'q', data)
    viewer = DebugServer(Inspector(SimpleNamespace(name='test', store=store, workspace_path='/tmp'), dst.session_id, lambda: dst))
    prefix = '/' + viewer.token
    rows = await request_debug(viewer, prefix + '/api/model-debug')
    assert json.loads(rows.text)['records'][0]['request_id'] == 'q'
    detail = await request_debug(viewer, prefix + '/api/model-debug?request_id=q')
    assert json.loads(detail.text) == data
    assert (await request_debug(viewer, prefix + '/api/model-debug?request_id=missing')).status == 404
    assert (await request_debug(viewer, prefix + '/api/model-debug', method='POST')).status == 405
    assert await store.export_session(dst.session_id) == before


@pytest.mark.asyncio
async def test_skill_directory_route_reads_run_metadata_without_emitting_events(store):
    import json
    from cota.debug.inspector import Inspector
    from cota.debug.server import DebugServer
    dst = await seed(store)
    dst.record_run_skills('r', ['weather'], discovery={'skills': [{'name': 'weather'}], 'diagnostics': []})
    await store.save(dst)
    before = await store.export_session(dst.session_id)
    viewer = DebugServer(Inspector(SimpleNamespace(name='test', store=store, workspace_path='/tmp'), dst.session_id, lambda: dst))
    route = '/' + viewer.token + '/api/run-metadata'
    response = await request_debug(viewer, route + '?run_id=r')
    assert response.status == 200
    assert json.loads(response.text) == {'run_id': 'r', **dst.run_metadata['r']}
    assert (await request_debug(viewer, route)).status == 400
    assert (await request_debug(viewer, route + '?run_id=absent')).status == 404
    assert await store.export_session(dst.session_id) == before


@pytest.mark.asyncio
async def test_model_diagnostics_resolve_carriers_without_changing_events(store, tmp_path):
    import json
    from cota.debug.inspector import Inspector
    from cota.debug.server import DebugServer
    dst = await seed(store)
    def append(event):
        dst.append_event(event)
        return dst.events[-1]
    owner = append(Event('bot_utter', {
        'text': 'hi', 'metadata': {'source': 'model'},
        'llm': {'request_id': 'q', 'request_sequence': 1, 'model': 'default', 'stop_reason': 'stop'},
    }, run_id='r'))
    tool_owner = append(Event('tool_started', {
        'tool_call_id': 'c1', 'tool': 'read', 'arguments': {},
        'llm': {'request_id': 'tools', 'request_sequence': 2, 'model': 'default', 'stop_reason': 'toolUse',
                'message': {'content': [
                    {'type': 'toolCall', 'id': 'c1', 'name': 'read', 'arguments': {}},
                    {'type': 'toolCall', 'id': 'c2', 'name': 'read', 'arguments': {}}], 'stop_reason': 'toolUse'}},
    }, run_id='r'))
    tool = append(Event('tool_started', {
        'tool_call_id': 'c2', 'tool': 'read', 'arguments': {}, 'llm_event_id': tool_owner.event_id,
    }, run_id='r'))
    output = append(Event('bot_utter', {
        'text': 'tool output', 'metadata': {'source': 'tool'}, 'tool_event_id': tool.event_id,
    }, run_id='r'))
    await store.save(dst)
    store.enable_debug_log(tmp_path / 'debug.log')
    records = {}
    for request_id in ('q', 'tools', 'failed'):
        records[request_id] = {'request_id': request_id, 'run_id': 'r', 'purpose': 'dialogue',
                               'status': 'completed', 'started_at': 1,
                               'request': {'messages': [{'role': 'user', 'content': 'private'}],
                                           'tools': [{'name': 'read', 'parameters': {}}], 'temperature': 0.2},
                               'response': {'content': 'normalized'},
                               'provider_response': {'choices': [{'message': {'content': 'original'}}]},
                               'preparation': {'policy': {'candidates': ['weather']}}}
        if request_id == 'failed':
            records[request_id].update(status='failed', error_type='ConnectionError', error='network unavailable')
            records[request_id].pop('response')
            records[request_id].pop('provider_response')
        await store.save_model_debug(dst.session_id, request_id, records[request_id])
    before = await store.export_session(dst.session_id)
    viewer = DebugServer(Inspector(SimpleNamespace(name='test', store=store, workspace_path='/tmp'), dst.session_id, lambda: dst))
    route = '/' + viewer.token + '/api/model-debug'
    for event, request_id in ((owner, 'q'), (tool_owner, 'tools'), (tool, 'tools'), (output, 'tools')):
        response = await request_debug(viewer, route + f'?event_sequence={event.sequence}')
        assert response.status == 200
        assert json.loads(response.text) == records[request_id]
        response = await request_debug(viewer, '/' + viewer.token + f'/api/event/{event.sequence}')
        assert response.status == 200
        view = json.loads(response.text)
        debug = view.pop('debug')
        assert view == await viewer.inspector.event(event.sequence)
        assert 'run_id' not in debug
        for key in ('request', 'response', 'provider_response', 'preparation'):
            assert debug[key] == records[request_id][key]
        if event in (owner, tool_owner):
            assert 'request_id' not in debug  # already present in the event
        else:
            assert debug['request_id'] == request_id  # linked events need request identity
    response = await request_debug(viewer, route + '?request_id=failed')
    assert response.status == 200 and json.loads(response.text) == records['failed']
    response = await request_debug(viewer, route)
    assert any(r['request_id'] == 'failed' and r['status'] == 'failed' for r in json.loads(response.text)['records'])
    assert (await request_debug(viewer, route + '?event_sequence=0')).status == 400
    assert (await request_debug(viewer, route + '?event_sequence=bad')).status == 400
    assert (await request_debug(viewer, route + '?event_sequence=4&request_id=q')).status == 400
    assert await store.export_session(dst.session_id) == before


@pytest.mark.asyncio
async def test_model_diagnostics_absence_is_a_friendly_expected_response(store):
    import json
    from cota.debug.inspector import Inspector
    from cota.debug.server import DebugServer
    dst = await seed(store)
    def append(event):
        dst.append_event(event)
        return dst.events[-1]
    owner = append(Event('bot_utter', {
        'text': 'hi', 'metadata': {'source': 'model'},
        'llm': {'request_id': 'q', 'request_sequence': 1, 'model': 'default', 'stop_reason': 'stop'},
    }, run_id='r'))
    await store.save(dst)
    viewer = DebugServer(Inspector(SimpleNamespace(name='test', store=store, workspace_path='/tmp'), dst.session_id, lambda: dst))
    response = await request_debug(viewer, '/' + viewer.token + f'/api/event/{owner.sequence}')
    assert response.status == 200
    assert 'debug' not in json.loads(response.text)
    route = '/' + viewer.token + '/api/model-debug'
    for query in (f'?event_sequence={owner.sequence}', '?request_id=q'):
        response = await request_debug(viewer, route + query)
        assert response.status == 404
        data = json.loads(response.text)
        assert data['code'] == 'model_diagnostics_unavailable'
        assert 'Debug' in data['error']


@pytest.mark.asyncio
async def test_event_remains_readable_when_diagnostics_fail(store, monkeypatch):
    from cota.debug.inspector import Inspector
    dst = await seed(store)
    dst.append_event(Event('bot_utter', {
        'text': 'hi', 'llm': {'request_id': 'q', 'request_sequence': 1,
                              'model': 'default', 'stop_reason': 'stop'},
    }, run_id='r'))
    await store.save(dst)
    inspector = Inspector(SimpleNamespace(name='test', store=store, workspace_path='/tmp'), dst.session_id, lambda: dst)
    before = await inspector.event(4)
    monkeypatch.setattr(store, 'model_debug', AsyncMock(side_effect=RuntimeError('private database details')))
    view = await inspector.event_view(4)
    debug = view.pop('debug')
    assert view == before
    assert debug == {'error': '模型诊断读取失败，请重试；原始事件仍可查看。'}
    assert 'debug' not in await inspector.event_view(1)


@pytest.mark.asyncio
@pytest.mark.parametrize('bad_link', ['missing', 'cross_run', 'forward', 'cycle', 'wrong_type'])
async def test_model_diagnostics_never_follow_invalid_event_links(bad_link):
    from cota.debug.inspector import Inspector
    # A corrupt persisted reference must not return another request or loop forever.
    current = {'event_id': 'child', 'sequence': 4, 'run_id': 'r', 'type': 'bot_utter',
               'payload': {'tool_event_id': 'target'}}
    target = {'event_id': 'target', 'sequence': 3, 'run_id': 'r', 'type': 'tool_started',
              'payload': {'llm': {'request_id': 'q'}}}
    if bad_link == 'missing':
        target = None
    elif bad_link == 'cross_run':
        target['run_id'] = 'other'
    elif bad_link == 'forward':
        target['sequence'] = 5
    elif bad_link == 'cycle':
        target['payload'] = {'llm_event_id': 'child'}
    elif bad_link == 'wrong_type':
        target['type'] = 'user'
    store = SimpleNamespace(events=AsyncMock(return_value=[current]),
                            event_by_id=AsyncMock(side_effect=lambda session, event_id: current if event_id == 'child' else target),
                            model_debug=AsyncMock(return_value={'request_id': 'q'}))
    inspector = Inspector(SimpleNamespace(name='test', store=store, workspace_path='/tmp'), 'session', lambda: None)
    with pytest.raises(LookupError):
        await inspector.model_debug(event_sequence=4)
    store.model_debug.assert_not_awaited()
