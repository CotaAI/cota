"""Skill discovery is immutable run metadata, independent of replay snapshots."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from cota.dst import DST
from cota.events import Event, UserUtterEvent
from cota.runtime.pi_runtime import PiAgentRuntime
from cota.store import MemoryStore, SQLStore


@pytest.fixture(params=['memory', 'sqlite'])
def store(request, tmp_path):
    value = MemoryStore() if request.param == 'memory' else SQLStore(db=str(tmp_path / 'runs.db'))
    yield value
    if isinstance(value, SQLStore):
        value.engine.dispose()


def start():
    dst = DST('s', None)
    user = UserUtterEvent('check weather')
    dst.append_event(user)
    dst.append_event(Event('run_started', {'input_event_id': user.event_id}, run_id='r'))
    return dst


@pytest.mark.asyncio
@pytest.mark.parametrize('debug', [False, True])
async def test_discovery_is_metadata_and_does_not_change_state(store, mock_agent, tmp_path, debug):
    if debug:
        store.enable_debug_log(tmp_path / 'execution.log')
    dst = start()
    state, events = dst.state_dict(), list(dst.events)
    runtime = PiAgentRuntime(mock_agent, dst, 's', checkpoint=store.save, store=store)
    payload = {'skills': [{'name': 'weather', 'filePath': '/skills/weather/SKILL.md'}],
               'diagnostics': [{'message': 'fixture warning'}]}
    await runtime._handle_request('skills_loaded', payload)
    assert dst.state_dict() == state
    assert list(dst.events) == events
    assert runtime._available_skills == ['weather']
    metadata = (await store.run_metadata('s', 'r'))
    assert metadata['available_skills'] == ['weather']
    assert metadata['deploy'] == 'service'
    if debug:
        assert {k: v for k, v in metadata['discovery'].items() if k != 'tools'} == payload
        tools = {item['name']: item for item in metadata['discovery']['tools']}
        assert tools['http_request'] == {'name': 'http_request', 'source': 'cota', 'available': True}
        assert tools['read']['available'] is True
        assert tools['bash']['available'] is False
        assert tools['bash']['reason'] == 'Execution environment: none'
    else:
        assert 'discovery' not in metadata
    assert 'skills_loaded' not in [e['type'] for e in await store.events('s')]
    if isinstance(store, SQLStore):
        reopened = SQLStore(db=store.engine.url.database)
        try:
            assert await reopened.run_metadata('s', 'r') == metadata
        finally:
            reopened.engine.dispose()
    assert await store.run_metadata('s', 'absent') is None


@pytest.mark.asyncio
async def test_historical_catalog_survives_snapshot_loss_and_catalog_change(store):
    dst = start()
    dst.record_run_skills('r', ['weather'])
    dst.append_event(Event('run_finished', {'status': 'completed'}, run_id='r'))
    await store.save(dst)
    restored = await store.load('s', agent=SimpleNamespace(skills=['other']))
    if isinstance(store, MemoryStore):
        store.snapshots.clear()
    else:
        with store.engine.begin() as conn:
            conn.execute(store.SQLSnapshot.__table__.delete())
    replayed = await store.load('s')
    assert replayed.state_dict() == restored.state_dict()
    assert replayed.trace('r') == await store.trace('s', 'r')
    assert replayed.run_metadata == {'r': {'available_skills': ['weather']}}


@pytest.mark.asyncio
async def test_metadata_is_detached_and_persisted_catalog_cannot_be_rewritten(store):
    dst = start()
    names = ['weather']
    dst.record_run_skills('r', names)
    names.clear()
    await store.save(dst)
    dst.run_metadata['r']['available_skills'].clear()
    exported = await store.run_metadata('s', 'r')
    exported['available_skills'].clear()
    assert dst.run_metadata['r']['available_skills'] == ['weather']
    assert (await store.run_metadata('s', 'r'))['available_skills'] == ['weather']
    with pytest.raises(ValueError, match='immutable'):
        dst.record_run_skills('r', ['other'])
    # Even bypassing public setters must not rewrite/delete persisted evidence.
    dst._run_metadata.clear()
    with pytest.raises(ValueError, match='run metadata'):
        await store.save(dst)
    assert (await store.load('s')).run_metadata['r']['available_skills'] == ['weather']


@pytest.mark.asyncio
async def test_discovery_is_saved_before_policy_validation_fails(store, mock_agent, tmp_path):
    store.enable_debug_log(tmp_path / 'execution.log')
    dst = start()
    mock_agent.policy.validate_skills = Mock(side_effect=ValueError('unknown policy skill'))
    runtime = PiAgentRuntime(mock_agent, dst, 's', checkpoint=store.save, store=store)
    payload = {'skills': [], 'diagnostics': [{'message': 'invalid SKILL.md'}]}
    with pytest.raises(ValueError, match='unknown policy skill'):
        await runtime._handle_request('skills_loaded', payload)
    discovery = (await store.run_metadata('s', 'r'))['discovery']
    assert {k: v for k, v in discovery.items() if k != 'tools'} == payload
    assert discovery['tools']
    mock_agent._llm_mock.generate_chat.assert_not_awaited()


def test_discovery_event_is_no_longer_supported():
    with pytest.raises(ValueError):
        Event('skills_loaded', {'skills': []})


@pytest.mark.asyncio
async def test_tool_inventory_records_initial_policy_without_refreshing_history(store, mock_agent, tmp_path):
    from cota.executor.tools import ToolPolicy
    from cota.executor.tools.base import FunctionTool
    from cota.executor.environment import ExecutionEnvironment
    store.enable_debug_log(tmp_path / 'execution.log')
    registry = mock_agent.get_tool_registry()
    registry.register(FunctionTool('lookup', 'lookup', {}, lambda: {}))
    registry.set_policy(ToolPolicy(deny=['http_request', 'lookup']))
    mock_agent.deploy = 'personal'
    mock_agent.environment = ExecutionEnvironment('machine', str(tmp_path))
    dst = start()
    runtime = PiAgentRuntime(mock_agent, dst, 's', store=store, checkpoint=store.save)
    native = {'available': ['read', 'write', 'edit', 'ls', 'bash'],
              'unavailable': {'find': 'fd missing', 'grep': 'rg missing', 'powershell': 'Windows only'}}
    await runtime._handle_request('skills_loaded', {'skills': [], 'nativeTools': native})
    initial = (await store.run_metadata('s', 'r'))['discovery']['tools']
    tools = {item['name']: item for item in initial}
    assert tools['find'] == {'name': 'find', 'source': 'pi', 'available': False, 'reason': 'fd missing'}
    assert tools['lookup'] == {'name': 'lookup', 'source': 'application', 'available': False, 'reason': 'Disabled by tools policy'}
    assert tools['http_request']['reason'] == 'Disabled by tools policy'
    registry.set_policy(ToolPolicy())
    assert (await store.run_metadata('s', 'r'))['discovery']['tools'] == initial
