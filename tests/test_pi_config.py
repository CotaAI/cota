import pytest
from cota.agent import Agent
from cota.events import Event
from tests.resource_fixtures import skill_result
from cota.dst import DST
from cota.executor.tools.registry import ToolPolicy
from cota.runtime.pi_runtime import PiAgentRuntime


def test_agent_yml_tool_policy_is_loaded(tmp_path, monkeypatch):
    (tmp_path / 'agent.yml').write_text('system:\n  name: test\ntools:\n  deny: [http_request]\n')
    (tmp_path / 'endpoints.yml').write_text('{}')
    monkeypatch.setattr('cota.agent.create_user_memory', lambda _: None)
    agent = Agent.load_from_path(str(tmp_path))
    names = [t.name for t in agent.get_tool_registry().get_allowed_tools()]
    assert 'http_request' not in names


def test_empty_allow_list_does_not_grant_all_tools(mock_agent):
    policy = ToolPolicy(allow=[])
    assert not policy.is_allowed('http_request')
    assert not policy.is_allowed('lookup')


def test_bot_tool_policy_is_independent_of_skill_trace(mock_agent):
    mock_agent._tool_registry.set_policy(ToolPolicy(deny=['http_request']))
    dst = DST('s', mock_agent)
    rt = PiAgentRuntime(agent=mock_agent, dst=dst, session_id='s')
    schemas = rt._get_tools_schema()
    assert 'http_request' not in [s['function']['name'] for s in schemas]
    for label in ('SearchWeb', 'unknown'):
        dst.append_event(Event('run_started', {}, run_id=f'read-{label}'))
        dst.append_event(skill_result(label))
        assert rt._get_tools_schema() == schemas
        dst.append_event(Event('run_finished', {'status': 'completed'}))
        assert rt._get_tools_schema() == schemas



def test_setup_command_uses_lockfile_and_disables_install_scripts(monkeypatch):
    from types import SimpleNamespace
    from cota.runtime.pi_setup import setup
    calls = []
    monkeypatch.setattr('shutil.which', lambda name: '/bin/' + name)
    def run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(stdout='v22.19.0\n')
    monkeypatch.setattr('subprocess.run', run)
    setup()
    install = next(args for args, _ in calls if 'ci' in args)
    assert '--ignore-scripts' in install
    assert '--prefix' in install
    assert all(not kwargs.get('shell') for _, kwargs in calls)


def test_setup_rejects_old_node(monkeypatch):
    from types import SimpleNamespace
    from cota.runtime.pi_setup import setup
    monkeypatch.setattr('shutil.which', lambda name: '/bin/' + name)
    monkeypatch.setattr('subprocess.run', lambda *a, **kw: SimpleNamespace(stdout='v20.0.0\n'))
    with pytest.raises(RuntimeError, match='22.19.0'):
        setup(check_only=True)


@pytest.mark.parametrize('field', ['max_images', 'max_image_bytes'])
@pytest.mark.parametrize('value', [0, -1, True, '8', 1.5])
def test_image_budget_settings_are_positive_integers(field, value):
    from cota.config import validate_bot_config
    with pytest.raises(ValueError, match=field):
        validate_bot_config({'dialogue': {'compaction': {field: value}}})


def test_image_budget_settings_are_part_of_the_bot_contract():
    from cota.config import validate_bot_config
    validate_bot_config({'dialogue': {'compaction': {'max_images': 8, 'max_image_bytes': 16777216}}})
