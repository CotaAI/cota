"""Large immutable diagnostics are not rewritten on status updates."""
import json

import pytest
import sqlalchemy as sa

from cota.store import MemoryStore, SQLStore


@pytest.fixture(params=['memory', 'sqlite'])
def store(request, tmp_path):
    value = MemoryStore() if request.param == 'memory' else SQLStore(db=str(tmp_path / 'debug.db'))
    value.enable_debug_log(tmp_path / 'execution.log')
    yield value
    if isinstance(value, SQLStore):
        value.engine.dispose()


@pytest.mark.asyncio
async def test_debug_updates_preserve_once_written_request_and_reopen(store, tmp_path):
    record = {'request_id': 'q', 'purpose': 'dialogue', 'started_at': 1.,
              'status': 'running', 'request_stage': 'provider',
              'request': {'messages': [{'role': 'user', 'content': 'pixels' * 100000}]}}
    await store.save_model_debug('s', 'q', record)
    # Updates are patches: terminal and linkage fields need no image body.
    await store.save_model_debug('s', 'q', {'status': 'completed', 'duration_ms': 50, 'response': {'content': 'seen'}})
    await store.save_model_debug('s', 'q', {'event_id': 'e'})
    expected = {**record, 'status': 'completed', 'duration_ms': 50, 'response': {'content': 'seen'}, 'event_id': 'e'}
    assert await store.model_debug('s', 'q') == expected
    assert (await store.model_debug_headers('s'))[0]['status'] == 'completed'
    if isinstance(store, SQLStore):
        reopened = SQLStore(db=str(tmp_path / 'debug.db'))
        try:
            assert await reopened.model_debug('s', 'q') == expected
        finally:
            reopened.engine.dispose()


@pytest.mark.asyncio
async def test_request_upgrade_from_adapter_to_actual_provider(store):
    common = {'request_id': 'q', 'purpose': 'dialogue', 'started_at': 1., 'status': 'running'}
    await store.save_model_debug('s', 'q', {**common, 'request': {'adapter': True}})
    actual = {'messages': [], 'stream': True}
    await store.save_model_debug('s', 'q', {**common, 'request_stage': 'provider', 'request': actual})
    await store.save_model_debug('s', 'q', {'status': 'failed', 'error_type': 'TimeoutError'})
    result = await store.model_debug('s', 'q')
    assert result['request'] == actual
    assert result['request_stage'] == 'provider'
    assert result['status'] == 'failed'


@pytest.mark.asyncio
async def test_sql_status_update_does_not_write_original_request(tmp_path):
    store = SQLStore(db=str(tmp_path / 'write-once.db'))
    store.enable_debug_log(tmp_path / 'log')
    statements = []
    def record_sql(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')):
            statements.append((statement, str(parameters)))
    sa.event.listen(store.engine, 'before_cursor_execute', record_sql)
    try:
        data = {'request_id': 'q', 'purpose': 'dialogue', 'status': 'running', 'started_at': 1.,
                'request_stage': 'provider', 'request': {'image': 'UNIQUE_IMAGE_BYTES' * 10000}}
        await store.save_model_debug('s', 'q', data)
        statements.clear()
        # The observer may still supply its complete current view.
        await store.save_model_debug('s', 'q', {**data, 'status': 'completed', 'event_id': 'e'})
        assert statements
        assert all('UNIQUE_IMAGE_BYTES' not in params for _, params in statements)
        result = await store.model_debug('s', 'q')
        assert json.dumps(result['request']) == json.dumps(data['request'])
    finally:
        store.engine.dispose()
