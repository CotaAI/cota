"""A tool server is a transport, not another agent loop."""
import asyncio
import os
import sys
import subprocess

import pytest

from cota.dst import DST
from cota.events import Event, UserUtterEvent
from cota.executor.tools.registry import ToolRegistry, ToolPolicy
from cota.runtime.pi_runtime import PiAgentRuntime
from cota.store import MemoryStore
from tests.test_pi_runtime import call


@pytest.fixture
def process_client(tmp_path):
    # Standalone stdlib server also works in an environment without Cota installed.
    script = tmp_path / 'server.py'
    script.write_text('''import json, os, subprocess, sys, time
for line in sys.stdin:
    req = json.loads(line)
    method = req['method']
    if method == 'initialize':
        names = os.environ.get('TOOL_NAMES', 'report').split(',')
        result = {'tools': [{'name': name, 'description': 'test report', 'parameters': {
            'type': 'object', 'properties': {'value': {'type': 'integer'}}, 'required': ['value']
        }} for name in names]}
    elif method == 'execute':
        if os.environ.get('CHILD_PID_FILE'):
            subprocess.Popen([sys.executable, '-c',
                "import os,signal,time; from pathlib import Path; "
                "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                "Path(os.environ['CHILD_PID_FILE']).write_text(str(os.getpid())); time.sleep(30)"])
            while not os.path.exists(os.environ['CHILD_PID_FILE']): time.sleep(0.01)
            if os.environ.get('EXIT_AFTER_CHILD'): os._exit(0)
        if os.environ.get('SLOW'): time.sleep(2)
        result = {'success': True, 'value': req['params']['arguments']['value'],
                  'pid': os.getpid(), 'cwd': os.getcwd(), 'token': os.environ.get('REPORT_TOKEN')}
    else:
        result = {'ok': True}
    response_id = req['id'] + (1 if os.environ.get('BAD_ID') and method == 'execute' else 0)
    print(json.dumps({'jsonrpc': '2.0', 'id': response_id, 'result': result}), flush=True)
    if method == 'shutdown': break
''')
    def factory(**kwargs):
        from cota.executor.tool_process import SubprocessToolClient
        return SubprocessToolClient([sys.executable, str(script)], cwd=str(tmp_path), **kwargs)
    return factory


@pytest.mark.asyncio
async def test_register_execute_concurrently_and_cleanup(process_client, tmp_path):
    client = process_client(env={'REPORT_TOKEN': 'test-token'})
    registry = ToolRegistry()
    try:
        assert await registry.connect_process(client) == ['report']
        results = await asyncio.gather(*(registry.get('report').execute(value=n) for n in range(4)))
        assert [r['value'] for r in results] == list(range(4))
        assert all(r['pid'] != os.getpid() and r['cwd'] == str(tmp_path) for r in results)
        assert all(r['token'] == 'test-token' for r in results)
    finally:
        await registry.cleanup()
    assert not client.is_running
    assert registry.get('report') is None


@pytest.mark.asyncio
async def test_registration_collision_is_atomic_and_closes_process(process_client):
    registry = ToolRegistry()
    from cota.executor.tools.base import FunctionTool, create_tool_schema
    original = FunctionTool("existing", "existing", create_tool_schema({}), lambda: {})
    registry.register(original)
    client = process_client(env={'TOOL_NAMES': 'report,existing'})
    with pytest.raises(ValueError, match='already registered'):
        await registry.connect_process(client)
    assert registry.get('existing') is original
    assert registry.get('report') is None
    assert not client.is_running


@pytest.mark.asyncio
async def test_group_all_policy_includes_explicitly_registered_tools(process_client):
    registry = ToolRegistry()
    registry.set_policy(ToolPolicy(allow=['group:all']))
    try:
        await registry.connect_process(process_client())
        assert 'report' in [t.name for t in registry.get_allowed_tools()]
    finally:
        await registry.cleanup()


@pytest.mark.asyncio
async def test_concurrent_registration_keeps_successful_connection(process_client):
    registry = ToolRegistry()
    client = process_client()
    try:
        results = await asyncio.gather(registry.connect_process(client), registry.connect_process(client),
                                       return_exceptions=True)
        assert sum(isinstance(result, ValueError) for result in results) == 1
        assert client.is_running
        assert (await registry.get('report').execute(value=1))['value'] == 1
    finally:
        await registry.cleanup()


@pytest.mark.asyncio
async def test_client_has_one_registry_owner(process_client):
    first, second = ToolRegistry(), ToolRegistry()
    client = process_client()
    try:
        await first.connect_process(client)
        with pytest.raises(ValueError, match='already registered'):
            await second.connect_process(client)
        assert client.is_running
        assert second.get('report') is None
    finally:
        await first.cleanup()
        await second.cleanup()


@pytest.mark.asyncio
async def test_disconnect_allows_scoped_replacement(process_client):
    registry = ToolRegistry()
    old = process_client()
    unrelated = process_client(env={'TOOL_NAMES': 'other'})
    try:
        await registry.connect_process(old)
        await registry.connect_process(unrelated)
        await registry.disconnect_process(old)
        assert not old.is_running and unrelated.is_running
        replacement = process_client()
        await registry.connect_process(replacement)
        assert (await registry.get('report').execute(value=2))['value'] == 2
    finally:
        await registry.cleanup()


@pytest.mark.asyncio
@pytest.mark.parametrize('env,exception', [({'SLOW': '1'}, TimeoutError), ({'BAD_ID': '1'}, ValueError)])
async def test_uncertain_rpc_stops_process_without_retry(process_client, env, exception):
    client = process_client(env=env)
    await client.start()
    client.timeout = 0.2
    with pytest.raises(exception):
        await client.execute_tool('report', {'value': 1})
    assert not client.is_running
    with pytest.raises(RuntimeError, match='closed'):
        await client.execute_tool('report', {'value': 2})
    await client.shutdown()


@pytest.mark.asyncio
async def test_cancellation_stops_process(process_client):
    client = process_client(env={'SLOW': '1'})
    await client.start()
    task = asyncio.create_task(client.execute_tool('report', {'value': 1}))
    await asyncio.sleep(0.1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not client.is_running


def process_is_alive(pid):
    # Zombies have already stopped executing, even before init reaps them.
    result = subprocess.run(['ps', '-o', 'stat=', '-p', str(pid)], capture_output=True, text=True)
    return result.returncode == 0 and bool(result.stdout.strip()) and not result.stdout.strip().startswith('Z')


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != 'posix', reason='POSIX process-group cleanup')
@pytest.mark.parametrize('reason', ['timeout', 'cancel', 'launcher_exited'])
async def test_process_tree_stops_after_uncertain_call(process_client, tmp_path, reason):
    marker = tmp_path / 'child-pid'
    env = {'SLOW': '1', 'CHILD_PID_FILE': str(marker)}
    if reason == 'launcher_exited':
        env['EXIT_AFTER_CHILD'] = '1'
    client = process_client(env=env)
    await client.start()
    client.timeout = 0.3 if reason != 'cancel' else 10
    task = asyncio.create_task(client.execute_tool('report', {'value': 1}))
    pid = None
    try:
        async with asyncio.timeout(5):
            while not marker.exists():
                await asyncio.sleep(0.01)
        pid = int(marker.read_text())
        if reason == 'cancel':
            task.cancel()
        with pytest.raises(asyncio.CancelledError if reason == 'cancel' else TimeoutError):
            await task
        for _ in range(50):
            if not process_is_alive(pid):
                break
            await asyncio.sleep(0.02)
        assert not process_is_alive(pid), 'tool descendant survived cancellation/timeout'
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await client.shutdown()
        if pid is not None and process_is_alive(pid):
            os.kill(pid, 9)


@pytest.mark.asyncio
async def test_pi_calls_registered_process_and_records_result(mock_agent, process_client):
    registry = mock_agent.get_tool_registry()
    client = process_client()
    await registry.connect_process(client)
    store = MemoryStore()
    dst = DST('s', mock_agent)
    dst.append_event(UserUtterEvent('create report'))
    mock_agent._llm_mock.generate_chat.side_effect = [
        {'tool_calls': [call('report', {'value': 7})]}, {'content': 'report ready'},
    ]
    try:
        await PiAgentRuntime(mock_agent, dst, 's', checkpoint=store.save).run()
        event = next(e for e in dst.events if e.type == 'tool_result' and e.tool == 'report')
        assert event.payload['result']['value'] == 7
        assert (await store.history('s'))[-1]['payload']['text'] == 'report ready'
        # Same execution-boundary policy as ordinary Python tools.
        registry.set_policy(ToolPolicy(deny=['report']))
        dst.append_event(UserUtterEvent('again'))
        dst.append_event(Event('run_started', {'input_event_id': dst.latest_user_event.event_id}, run_id='blocked-run'))
        dst.append_event(Event('tool_started', {'tool_call_id': 'bad', 'tool': 'report', 'arguments': {'value': 8}}))
        runtime = PiAgentRuntime(mock_agent, dst, 's', checkpoint=store.save)
        result = await runtime._execute_tool({'name': 'report', 'args': {'value': 8}, 'toolCallId': 'bad'})
        assert result['isError']
        assert 'not allowed' in result['content'][0]['text']
    finally:
        await registry.cleanup()


@pytest.mark.asyncio
@pytest.mark.parametrize('name', ['read', 'web_fetch'])
async def test_reserved_process_tool_rejection_is_atomic(process_client, name):
    registry = ToolRegistry()
    client = process_client(env={'TOOL_NAMES': 'report,' + name})
    with pytest.raises(ValueError, match='reserved'):
        await registry.connect_process(client)
    assert registry.list_tools() == []
    assert not client.is_running
