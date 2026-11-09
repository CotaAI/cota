"""The major-version API has one recovery path and explicit exports."""
import pytest
import sqlalchemy as sa

from cota.dst import DST
from cota.store import Store, SQLStore, MemoryStore


def test_dst_exports_have_explicit_empty_state_without_legacy_import_api():
    dst = DST('s', None)
    assert dst.as_dict()['active_skill'] is None
    assert 'schema_version' not in dst.as_dict()
    assert not hasattr(DST, 'from_dict')
    assert not hasattr(DST, 'current_state')


@pytest.mark.asyncio
async def test_export_is_explicit_and_load_remains_the_recovery_api():
    store = MemoryStore()
    dst = DST('s', None)
    dst.update_user('alice', {'city': '北京'})
    await store.save(dst)
    assert await store.export_session('s') == dst.as_dict()
    assert (await store.load('s')).state_dict() == dst.state_dict()
    assert await store.export_session('missing') is None
    assert not hasattr(Store, 'retrieve')
    assert not hasattr(Store, 'retrieve_conversations')


@pytest.mark.parametrize('table,columns', [
    ('sessions', 'session_id TEXT PRIMARY KEY'),
    ('events', 'session_id TEXT, sequence INTEGER'),
    ('session_snapshots', 'session_id TEXT PRIMARY KEY'),
])
def test_incomplete_current_schema_fails_at_startup_without_modifying_tables(tmp_path, table, columns):
    path = str(tmp_path / 'incomplete.db')
    engine = sa.create_engine('sqlite:///' + path)
    with engine.begin() as conn:
        conn.exec_driver_sql(f'CREATE TABLE {table} ({columns})')
    before = sa.inspect(engine).get_table_names()
    with pytest.raises(ValueError, match=f'Incompatible Store schema: {table}'):
        SQLStore(db=path)
    assert sa.inspect(engine).get_table_names() == before
    engine.dispose()


@pytest.mark.asyncio
async def test_release_template_smoke_uses_current_store_contract(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import yaml
    from cota import __main__ as cli
    from scripts.smoke_installed import smoke_examples
    monkeypatch.chdir(tmp_path)
    cli.init(SimpleNamespace())
    for name in ('weather',):
        path = tmp_path / 'cota_projects' / name / 'endpoints.yml'
        endpoints = yaml.safe_load(path.read_text())
        endpoints['llms']['default'].update(key='smoke-only', apibase='https://model.example/v1', model='test-model')
        path.write_text(yaml.safe_dump(endpoints))
    await smoke_examples(tmp_path)
