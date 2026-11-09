"""Deployment purpose is distinct from machine location and channel transport."""
import pytest

from cota.agent import Agent
from cota.config import validate_bot_config
from cota.dst import DST
from cota.events import UserUtterEvent
from cota.executor.environment import ExecutionEnvironment
from cota.runtime.pi_runtime import PiAgentRuntime
from cota.store import MemoryStore
from tests.test_pi_runtime import call


@pytest.mark.parametrize('deploy', ['personal', 'service'])
def test_supported_deploy_modes(deploy):
    validate_bot_config({'deploy': deploy})


@pytest.mark.parametrize('deploy', ['local', 'remote', 'host', '', None, {}, True])
def test_invalid_deploy_modes(deploy):
    with pytest.raises(ValueError, match='deploy'):
        validate_bot_config({'deploy': deploy})


@pytest.mark.asyncio
@pytest.mark.parametrize('deploy,kind', [('personal', 'machine'), ('service', 'none')])
async def test_load_deploy_resolves_default_environment_at_bot(tmp_path, deploy, kind):
    (tmp_path / 'agent.yml').write_text(f'deploy: {deploy}\n')
    (tmp_path / 'endpoints.yml').write_text('{}')
    agent = Agent.load_from_path(str(tmp_path))
    try:
        assert agent.deploy == deploy
        assert agent.environment.type == kind
        assert agent.environment.workspace == (str(tmp_path / 'files') if kind == 'machine' else None)
        assert not (tmp_path / 'files').exists()
    finally:
        await agent.cleanup()


def test_omitted_deploy_does_not_grant_machine_access():
    agent = Agent()
    assert agent.deploy == 'service'
    assert agent.environment.type == 'none'


def test_personal_can_disable_machine_tools():
    agent = Agent(deploy='personal', environment=ExecutionEnvironment())
    assert agent.environment.type == 'none'
    validate_bot_config({'deploy': 'personal', 'environment': {'type': 'none'}})


def test_personal_environment_options_keep_deployment_defaults(tmp_path):
    options = {'workspace': 'documents', 'shell': 'bash'}
    environment = ExecutionEnvironment.for_deployment('personal', options, base_path=tmp_path)
    assert environment.type == 'machine'
    assert environment.workspace == str(tmp_path / 'documents')
    assert environment.shell == 'bash'
    assert options == {'workspace': 'documents', 'shell': 'bash'}


def test_old_host_backend_is_not_an_alias():
    with pytest.raises(ValueError, match='environment'):
        validate_bot_config({'deploy': 'personal', 'environment': {'type': 'host', 'workspace': '/tmp'}})


def test_service_cannot_bind_unrestricted_machine(tmp_path):
    with pytest.raises(ValueError, match='service'):
        validate_bot_config({'deploy': 'service', 'environment': {'type': 'machine', 'workspace': str(tmp_path)}})
    environment = ExecutionEnvironment('machine', str(tmp_path))
    with pytest.raises(ValueError, match='service'):
        Agent(deploy='service', environment=environment)


def test_mutated_service_agent_is_rejected_before_runtime(mock_agent, tmp_path):
    mock_agent.deploy = 'service'
    mock_agent.environment = ExecutionEnvironment('machine', str(tmp_path))
    with pytest.raises(ValueError, match='service'):
        PiAgentRuntime(mock_agent, DST('s', mock_agent), 's')


@pytest.mark.asyncio
async def test_deploy_revocation_blocks_native_side_effect_and_restores_provenance(mock_agent, tmp_path):
    mock_agent.deploy = 'personal'
    mock_agent.environment = ExecutionEnvironment('machine', str(tmp_path))
    mock_agent.skill_paths = []
    target = tmp_path / 'private.txt'

    async def model(**kwargs):
        mock_agent.deploy = 'service'
        if mock_agent._llm_mock.generate_chat.call_count == 1:
            return {'tool_calls': [call('write', {'path': str(target), 'content': 'forbidden'}, 'w')]}
        return {'content': 'blocked'}

    mock_agent._llm_mock.generate_chat.side_effect = model
    store = MemoryStore()
    dst = DST('s', mock_agent)
    dst.append_event(UserUtterEvent('write'))
    await PiAgentRuntime(mock_agent, dst, 's', checkpoint=store.save).run()
    assert not target.exists()
    results = [e for e in dst.events if e.type == 'tool_result']
    assert results and results[0].payload['status'] != 'success'
    restored = await store.load('s', agent=mock_agent)
    metadata = restored.run_metadata[dst.execution['run_id']]
    assert metadata['deploy'] == 'personal'
    assert metadata['environment']['type'] == 'machine'
    assert restored.context_messages == dst.context_messages


def test_metadata_rejects_service_machine_binding(tmp_path):
    from cota.events import Event
    from cota.run_metadata import validate_run_metadata
    metadata = {'r': {'available_skills': [], 'deploy': 'service',
                      'environment': {'type': 'machine', 'workspace': str(tmp_path), 'timeout_seconds': 60}}}
    with pytest.raises(ValueError, match='service'):
        validate_run_metadata(metadata, [Event('run_started', {}, run_id='r')])
