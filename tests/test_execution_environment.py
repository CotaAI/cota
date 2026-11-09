"""Real Pi tools operate in an explicit deployment environment, not the Bot folder."""
from pathlib import Path

import pytest

from cota.config import validate_bot_config
from cota.dst import DST
from cota.events import UserUtterEvent
from cota.runtime.pi_runtime import PiAgentRuntime
from cota.store import MemoryStore
from tests.test_pi_runtime import call


def personal_agent(agent, path, **options):
    from cota.executor.environment import ExecutionEnvironment
    agent.deploy = 'personal'
    agent.environment = ExecutionEnvironment.from_config(
        {'type': 'machine', 'workspace': str(path), **options}, base_path=agent.config_path)
    return agent


@pytest.mark.parametrize('environment', [
    {'type': 'device', 'workspace': '/tmp'}, {'type': 'container'},
    {'type': 'machine', 'workspace': ''},
    {'type': 'none', 'workspace': '/tmp'}, {'type': 'machine', 'workspace': '/tmp', 'readonly': True},
    {'type': 'machine', 'workspace': '/tmp', 'timeout_seconds': 0},
    {'type': 'machine', 'workspace': '/tmp', 'timeout_seconds': True},
])
def test_rejects_invalid_environments(environment):
    with pytest.raises(ValueError):
        validate_bot_config({'deploy': 'personal', 'environment': environment})


def test_personal_machine_config_is_supported():
    validate_bot_config({'deploy': 'personal', 'environment': {'type': 'machine', 'workspace': './files'}})


def test_binding_is_explicit_frozen_and_relative_to_bot(tmp_path):
    from dataclasses import FrozenInstanceError
    from cota.executor.environment import ExecutionEnvironment
    env = ExecutionEnvironment.from_config({'type': 'machine', 'workspace': 'files'}, base_path=tmp_path)
    assert env.workspace == str(tmp_path / 'files')
    assert not (tmp_path / 'files').exists()  # binding doesn't execute or create files
    with pytest.raises(FrozenInstanceError):
        env.workspace = '/somewhere'
    assert ExecutionEnvironment.from_config({}, base_path=tmp_path).type == 'none'


@pytest.mark.asyncio
async def test_real_pi_tools_share_machine_workspace_and_restore_trace(mock_agent, tmp_path):
    work = tmp_path / 'files'
    personal_agent(mock_agent, work)
    mock_agent.skill_paths = []
    responses = [
        {'tool_calls': [call('write', {'path': 'note.txt', 'content': 'one\ntwo\n'}, 'w')]},
        {'tool_calls': [call('edit', {'path': 'note.txt', 'edits': [{'oldText': 'two', 'newText': 'three'}]}, 'e')]},
        {'tool_calls': [call('read', {'path': 'note.txt', 'offset': 2, 'limit': 1}, 'r')]},
        {'tool_calls': [call('bash', {'command': 'cat note.txt'}, 'b')]},
        {'content': 'done'},
    ]
    mock_agent._llm_mock.generate_chat.side_effect = responses
    store = MemoryStore()
    dst = DST('tools', mock_agent)
    dst.append_event(UserUtterEvent('create and edit'))
    await PiAgentRuntime(mock_agent, dst, 'tools', checkpoint=store.save).run()
    assert (work / 'note.txt').read_text() == 'one\nthree\n'
    assert not (Path(mock_agent.config_path) / 'note.txt').exists()
    results = [e for e in dst.events if e.type == 'tool_result']
    assert [e.tool for e in results] == ['write', 'edit', 'read', 'bash']
    assert all(e.payload['status'] == 'success' for e in results)
    assert 'diff' in results[1].payload['result']
    assert results[-1].payload['result']['exit_code'] == 0
    assert all('resource' not in e.payload for e in results)
    metadata = dst.run_metadata[dst.execution['run_id']]['environment']
    assert metadata['type'] == 'machine' and metadata['workspace'] == str(work)
    restored = await store.load('tools', agent=mock_agent)
    assert restored.state_dict() == dst.state_dict()
    assert restored.context_messages == dst.context_messages
    messages = mock_agent._llm_mock.generate_chat.call_args_list[0].kwargs['messages']
    assert 'Use read to examine files' in messages[0]['content']
    assert str(work) in messages[0]['content']
    for request in mock_agent._llm_mock.generate_chat.call_args_list:
        assert {'read', 'write', 'edit', 'bash'} <= {t['function']['name'] for t in request.kwargs['tools']}


@pytest.mark.asyncio
async def test_none_does_not_offer_machine_tools_or_allow_hallucinated_writes(mock_agent, tmp_path):
    target = tmp_path / 'no.txt'
    mock_agent._llm_mock.generate_chat.side_effect = [
        {'tool_calls': [call('write', {'path': str(target), 'content': 'no'})]}, {'content': 'done'}]
    dst = DST('none', mock_agent)
    dst.append_event(UserUtterEvent('write'))
    await PiAgentRuntime(mock_agent, dst, 'none').run()
    assert not target.exists()
    offered = mock_agent._llm_mock.generate_chat.call_args_list[0].kwargs['tools']
    assert not {'write', 'edit', 'bash'} & {t['function']['name'] for t in offered}
    assert next(e for e in dst.events if e.type == 'tool_result').payload['status'] == 'blocked'


@pytest.mark.asyncio
async def test_native_start_checkpoint_failure_prevents_side_effect(mock_agent, tmp_path):
    personal_agent(mock_agent, tmp_path)
    mock_agent._llm_mock.generate_chat.return_value = {'tool_calls': [call('write', {'path': 'never', 'content': 'no'})]}
    dst = DST('fail', mock_agent)
    dst.append_event(UserUtterEvent('write'))
    async def checkpoint(tracker):
        if any(e.type == 'tool_started' for e in tracker.events):
            raise OSError('store unavailable')
    with pytest.raises(OSError, match='store unavailable'):
        await PiAgentRuntime(mock_agent, dst, 'fail', checkpoint=checkpoint).run()
    assert not (tmp_path / 'never').exists()


@pytest.mark.asyncio
async def test_environment_revocation_before_native_call_blocks_execution(mock_agent, tmp_path):
    from cota.executor.environment import ExecutionEnvironment
    personal_agent(mock_agent, tmp_path)
    dst = DST('revoke', mock_agent)
    dst.append_event(UserUtterEvent('write'))
    async def model(**kwargs):
        mock_agent.environment = ExecutionEnvironment()
        return {'tool_calls': [call('write', {'path': 'never', 'content': 'no'})]}
    first = True
    async def respond(**kwargs):
        nonlocal first
        if first:
            first = False
            return await model(**kwargs)
        return {'content': 'blocked'}
    mock_agent._llm_mock.generate_chat.side_effect = respond
    await PiAgentRuntime(mock_agent, dst, 'revoke').run()
    assert not (tmp_path / 'never').exists()
    assert next(e for e in dst.events if e.type == 'tool_result').payload['status'] == 'blocked'


@pytest.mark.asyncio
async def test_machine_skill_read_and_business_file_have_distinct_provenance(mock_agent, tmp_path):
    personal_agent(mock_agent, tmp_path)
    (tmp_path / 'data').write_text('business data')
    mock_agent._llm_mock.generate_chat.side_effect = [
        {'tool_calls': [call('read', {'path': mock_agent.skill_file('SearchWeb')}, 's')]},
        {'tool_calls': [call('read', {'path': 'data'}, 'f')]}, {'content': 'done'}]
    dst = DST('provenance', mock_agent)
    dst.append_event(UserUtterEvent('read both'))
    await PiAgentRuntime(mock_agent, dst, dst.session_id).run()
    results = [e for e in dst.events if e.type == 'tool_result']
    assert results[0].payload['resource']['skill'] == 'SearchWeb'
    assert 'resource' not in results[1].payload
    assert dst.active_skill == 'SearchWeb'


@pytest.mark.asyncio
async def test_native_result_checkpoint_failure_stops_followup_calls(mock_agent, tmp_path):
    personal_agent(mock_agent, tmp_path)
    mock_agent._llm_mock.generate_chat.return_value = {'tool_calls': [
        call('write', {'path': 'first', 'content': 'done'}, 'a'),
        call('write', {'path': 'second', 'content': 'never'}, 'b')]}
    dst = DST('result-failure', mock_agent)
    dst.append_event(UserUtterEvent('write'))
    async def checkpoint(tracker):
        if any(e.type == 'tool_result' for e in tracker.events):
            raise OSError('result store failed')
    with pytest.raises(OSError, match='result store failed'):
        await PiAgentRuntime(mock_agent, dst, dst.session_id, checkpoint=checkpoint).run()
    assert (tmp_path / 'first').read_text() == 'done'
    assert not (tmp_path / 'second').exists()
    assert mock_agent._llm_mock.generate_chat.await_count == 1


@pytest.mark.asyncio
async def test_machine_command_timeout_is_enforced_even_if_model_requests_more(mock_agent, tmp_path):
    personal_agent(mock_agent, tmp_path, timeout_seconds=0.1)
    mock_agent._llm_mock.generate_chat.side_effect = [
        {'tool_calls': [call('bash', {'command': 'sleep 3; touch too-late', 'timeout': 100})]},
        {'content': 'timed out'}]
    dst = DST('timeout', mock_agent)
    dst.append_event(UserUtterEvent('run'))
    await PiAgentRuntime(mock_agent, dst, dst.session_id).run()
    result = next(e for e in dst.events if e.type == 'tool_result')
    assert result.payload['status'] == 'error'
    assert 'timed out' in str(result.payload).lower() or 'timeout' in str(result.payload).lower()
    assert not (tmp_path / 'too-late').exists()


@pytest.mark.asyncio
async def test_cancelled_bridge_terminates_native_shell(mock_agent, tmp_path):
    import asyncio
    import os
    import signal
    personal_agent(mock_agent, tmp_path)
    mock_agent._llm_mock.generate_chat.return_value = {'tool_calls': [
        call('bash', {'command': 'echo $$ > shell.pid; sleep 30'})]}
    dst = DST('cancel', mock_agent)
    dst.append_event(UserUtterEvent('run'))
    task = asyncio.create_task(PiAgentRuntime(mock_agent, dst, dst.session_id).run())
    pid = None
    try:
        async with asyncio.timeout(10):
            while not (tmp_path / 'shell.pid').exists():
                if task.done():
                    await task
                await asyncio.sleep(.02)
        pid = int((tmp_path / 'shell.pid').read_text())
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        # Give process reaping a short bounded window.
        for _ in range(50):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
            await asyncio.sleep(.02)
        else:
            pytest.fail('Pi shell survived bridge cancellation')
        assert dst.execution['status'] == 'interrupted'
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        if pid:
            try:
                os.killpg(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def test_run_environment_validation_does_not_reinterpret_historical_symlinks(tmp_path):
    from cota.run_metadata import validate_run_metadata
    from cota.events import Event
    work = tmp_path / 'work'
    other = tmp_path / 'other'
    other.mkdir()
    work.symlink_to(other, target_is_directory=True)
    record = {'r': {'available_skills': [], 'environment': {
        'type': 'machine', 'workspace': str(work), 'timeout_seconds': 60}}}
    assert validate_run_metadata(record, [Event('run_started', {}, run_id='r')]) == record


@pytest.mark.parametrize('name', ['read', 'write', 'edit', 'bash'])
def test_native_names_cannot_be_reconfigured_as_extension_tools(name):
    with pytest.raises(ValueError, match='environment'):
        validate_bot_config({'tools': {'deny': [name]}})


@pytest.mark.asyncio
async def test_agent_load_resolves_machine_workspace_without_changing_internal_workspace(tmp_path):
    from cota.agent import Agent
    (tmp_path / 'agent.yml').write_text('deploy: personal\nenvironment:\n  type: machine\n  workspace: files\n')
    (tmp_path / 'endpoints.yml').write_text('{}')
    agent = Agent.load_from_path(str(tmp_path))
    try:
        assert agent.environment.workspace == str(tmp_path / 'files')
        assert agent.workspace_path == str(tmp_path / 'workspace')
    finally:
        await agent.cleanup()


@pytest.mark.asyncio
async def test_two_bot_environments_do_not_overwrite_each_others_working_directory(tmp_path):
    import asyncio
    from tests.conftest import MockAgent
    agents = [MockAgent(), MockAgent()]
    async def run(index):
        agent = personal_agent(agents[index], tmp_path / str(index))
        agent.skill_paths = []
        agent._llm_mock.generate_chat.side_effect = [
            {'tool_calls': [call('write', {'path': 'same.txt', 'content': str(index)})]},
            {'content': 'done'}]
        dst = DST(str(index), agent)
        dst.append_event(UserUtterEvent('write'))
        await PiAgentRuntime(agent, dst, dst.session_id).run()
    try:
        await asyncio.gather(run(0), run(1))
        assert (tmp_path / '0/same.txt').read_text() == '0'
        assert (tmp_path / '1/same.txt').read_text() == '1'
    finally:
        for agent in agents:
            agent._skill_directory.cleanup()


@pytest.mark.parametrize('shell', ['auto', 'bash', 'powershell', 'both'])
def test_machine_supports_explicit_shell_selection(tmp_path, shell):
    from cota.executor.environment import ExecutionEnvironment
    config = {'type': 'machine', 'workspace': str(tmp_path), 'shell': shell}
    validate_bot_config({'deploy': 'personal', 'environment': config})
    env = ExecutionEnvironment.from_config(config, base_path=tmp_path)
    assert env.shell == shell
    assert {'read', 'write', 'edit', 'grep', 'find', 'ls'} <= env.tool_names()
    assert ('bash' in env.tool_names()) == (shell != 'powershell')
    assert ('powershell' in env.tool_names()) == (shell != 'bash')


@pytest.mark.parametrize('shell', ['', None, ['bash'], 'sh'])
def test_invalid_shell_selection_is_rejected(tmp_path, shell):
    with pytest.raises(ValueError):
        validate_bot_config({'deploy': 'personal', 'environment': {'type': 'machine', 'workspace': str(tmp_path), 'shell': shell}})


@pytest.mark.parametrize('name', ['grep', 'find', 'ls', 'powershell'])
def test_additional_native_names_are_reserved(name):
    with pytest.raises(ValueError, match='environment'):
        validate_bot_config({'tools': {'allow': [name]}})


@pytest.mark.asyncio
async def test_native_listing_inventory_and_result_survive_store(mock_agent, tmp_path):
    personal_agent(mock_agent, tmp_path)
    (tmp_path / 'note.txt').write_text('hello')
    (tmp_path / 'z.txt').write_text('outside the requested result limit')
    mock_agent._llm_mock.generate_chat.side_effect = [
        {'tool_calls': [call('ls', {'path': '.', 'limit': 1})]}, {'content': 'done'}]
    dst = DST('listing', mock_agent)
    dst.append_event(UserUtterEvent('list files'))
    store = MemoryStore()
    await PiAgentRuntime(mock_agent, dst, dst.session_id, checkpoint=store.save).run()
    result = next(e for e in dst.events if e.type == 'tool_result')
    assert result.payload['status'] == 'success'
    assert result.payload['result']['entryLimitReached'] == 1
    from cota.events.tool import result_content
    assert 'note.txt' in str(result_content(result.payload))
    inventory = dst.run_metadata[dst.execution['run_id']]['native_tools']
    assert {'read', 'write', 'edit', 'ls'} <= set(inventory['available'])
    assert not set(inventory['available']) & set(inventory['unavailable'])
    assert set(inventory['available']) | set(inventory['unavailable']) == set(mock_agent.environment.tool_names())
    assert (await store.load(dst.session_id)).run_metadata == dst.run_metadata
    schemas = mock_agent._llm_mock.generate_chat.call_args.kwargs['tools']
    from cota.executor.environment import NATIVE_TOOLS
    assert {t['function']['name'] for t in schemas} & NATIVE_TOOLS == set(inventory['available'])


@pytest.mark.asyncio
async def test_explicit_unsupported_powershell_fails_before_model(mock_agent, tmp_path):
    import sys
    if sys.platform == 'win32':
        pytest.skip('Non-Windows platform contract')
    personal_agent(mock_agent, tmp_path, shell='powershell')
    dst = DST('unsupported-shell', mock_agent)
    dst.append_event(UserUtterEvent('run command'))
    with pytest.raises(RuntimeError, match='[Pp]ower[Ss]hell|powershell'):
        await PiAgentRuntime(mock_agent, dst, dst.session_id).run()
    mock_agent._llm_mock.generate_chat.assert_not_awaited()


@pytest.mark.asyncio
async def test_unavailable_native_tool_is_not_offered_or_executed(mock_agent, tmp_path, monkeypatch):
    import shutil
    mock_agent.dialogue['pi_node'] = shutil.which('node')
    monkeypatch.setenv('PI_CODING_AGENT_DIR', str(tmp_path / 'empty-pi'))
    monkeypatch.setenv('PATH', str(tmp_path / 'empty-path'))
    personal_agent(mock_agent, tmp_path)
    mock_agent._llm_mock.generate_chat.side_effect = [
        {'tool_calls': [call('grep', {'pattern': 'secret', 'path': '.'})]}, {'content': 'unavailable'}]
    dst = DST('missing-tools', mock_agent)
    dst.append_event(UserUtterEvent('search'))
    await PiAgentRuntime(mock_agent, dst, dst.session_id).run()
    offered = {t['function']['name'] for t in mock_agent._llm_mock.generate_chat.call_args.kwargs['tools']}
    assert 'grep' not in offered and 'find' not in offered
    assert next(e for e in dst.events if e.type == 'tool_result').payload['status'] == 'blocked'
    unavailable = dst.run_metadata[dst.execution['run_id']]['native_tools']['unavailable']
    assert 'grep' in unavailable and 'find' in unavailable
    assert not (tmp_path / 'empty-pi').exists()  # no on-demand installation


@pytest.mark.asyncio
@pytest.mark.parametrize('tool,args', [('grep', {'pattern': 'HELLO', 'path': '.'}), ('find', {'pattern': '*.txt'})])
async def test_real_native_search_trace_and_checkpoint(mock_agent, tmp_path, tool, args):
    personal_agent(mock_agent, tmp_path)
    (tmp_path / 'match.txt').write_text('HELLO\n')
    store = MemoryStore()
    dst = DST('search', mock_agent)
    dst.append_event(UserUtterEvent('search'))
    mock_agent._llm_mock.generate_chat.side_effect = [
        {'tool_calls': [call(tool, args)]}, {'content': 'done'}]
    await PiAgentRuntime(mock_agent, dst, dst.session_id, checkpoint=store.save).run()
    inventory = dst.run_metadata[dst.execution['run_id']]['native_tools']
    if tool in inventory['unavailable']:
        pytest.skip(inventory['unavailable'][tool])
    result = next(e for e in dst.events if e.type == 'tool_result')
    assert result.payload['status'] == 'success'
    from cota.events.tool import result_content
    assert 'match.txt' in str(result_content(result.payload))
    assert 'resource' not in result.payload
    restored = await store.load(dst.session_id)
    assert restored.context_messages == dst.context_messages
    assert restored.run_metadata == dst.run_metadata


@pytest.mark.parametrize('inventory', [
    {'available': ['ls'], 'unavailable': {}},
    {'available': ['read', 'write', 'edit', 'ls', 'unknown'], 'unavailable': {}},
    {'available': ['read', 'read'], 'unavailable': {}},
    {'available': [], 'unavailable': {'ls': ''}},
])
def test_invalid_native_inventory_cannot_be_persisted(tmp_path, inventory):
    from cota.executor.environment import ExecutionEnvironment
    env = ExecutionEnvironment.from_config({'type': 'machine', 'workspace': str(tmp_path)}, base_path=tmp_path)
    with pytest.raises(ValueError):
        env.validate_inventory(inventory)
