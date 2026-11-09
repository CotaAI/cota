"""Run from outside the checkout using a fresh venv's Python after pip installing its wheel."""
import asyncio
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile

import yaml

from cota.runtime.pi_bridge import PiBridge
from cota.runtime.pi_distribution import resolve_runtime
from cota.runtime.pi_setup import setup
from cota.templates import bot_templates_dir


async def smoke():
    runtime = resolve_runtime()
    assert runtime.bundled, 'Smoke must use the installed release wheel'
    assert 'site-packages' in str(runtime.worker), runtime.worker
    calls, events = [], []
    schema = {'type': 'function', 'function': {
        'name': 'echo', 'description': 'Echo a message',
        'parameters': {'type': 'object', 'properties': {'text': {'type': 'string'}}, 'required': ['text']},
    }}

    async def handle(method, payload):
        if method == 'skills_loaded':
            return {}
        if method == 'prepare':
            return {'messages': payload['messages'], 'tools': [schema]}
        if method == 'model':
            if not calls:
                return {'tool_calls': [{'id': 'call-1', 'type': 'function', 'function': {
                    'name': 'echo', 'arguments': json.dumps({'text': 'hello'})}}]}
            return {'content': 'done'}
        if method == 'tool':
            calls.append(payload)
            return {'content': [{'type': 'text', 'text': 'hello'}]}
        if method == 'event':
            events.append(payload['event'])
            return {}
        raise AssertionError(method)

    result = await PiBridge().run({
        'messages': [{'role': 'user', 'content': 'echo hello', 'timestamp': 1}],
        'maxIterations': 3,
    }, handle)
    assert result['status'] == 'completed', result
    assert len(calls) == 1, calls
    assert result['messages'][-1]['content'][0]['text'] == 'done', result
    assert any(e['type'] == 'message_end' and e['message']['role'] == 'toolResult' for e in events)


async def smoke_examples(root):
    """Exercise the actual installed templates with an offline model callback."""
    from cota.agent import Agent
    from cota.dst import DST
    from cota.message.message import Message

    for name in ('weather',):
        agent = Agent.load_from_path(str(root / 'cota_projects' / name))
        read_calls = []
        async def respond(**kwargs):
            assert agent.description in kwargs['messages'][0]['content']
            if name == 'weather' and not read_calls:
                read_calls.append(True)
                return {'tool_calls': [{'id': 'read-weather', 'type': 'function', 'function': {
                    'name': 'read', 'arguments': json.dumps({'path': 'skills/weather/SKILL.md'}),
                }}]}
            if name == 'weather':
                assert '只依据查到的数据回答' in kwargs['messages'][0]['content']
                assert any(m['role'] == 'tool' and 'wttr.in' in m.get('content', '') for m in kwargs['messages'])
            return {'content': '模板已运行。'}
        agent.llm_instance('default').generate_chat = respond
        try:
            await agent.create_processor().handle_message(Message(
                text='你好', session_id='smoke', sender_id='user', receiver='bot'))
            saved = await agent.store.export_session('smoke')
            snapshot = await agent.store.snapshot('smoke')
            assert snapshot['schema_version'] == DST.STATE_VERSION and 'events' not in snapshot['state']
            assert saved['execution']['status'] == 'completed', name
            trace = await agent.store.trace('smoke', saved['execution']['run_id'])
            assert trace['status'] == 'completed'
            assert all(e['schema_version'] == 1 for e in trace['events'])
            if name == 'weather':
                assert saved['active_skill'] == 'weather'
                assert any(e['type'] == 'tool_result' and e['payload']['status'] == 'success'
                           and e['payload'].get('resource', {}).get('kind') == 'skill'
                           for e in saved['events'])
                assert len(trace['skills']) == len(trace['calls']) == 1
                assert trace['skills'][0]['payload']['resource']['hash'].startswith('sha256:')
                assert trace['calls'][0]['status'] == 'success'
            assert [e['payload']['text'] for e in await agent.store.history('smoke')] == ['你好', '模板已运行。']
        finally:
            await agent.cleanup()
            agent.store.engine.dispose()
            agent.user_memory._engine.dispose()


def smoke_training(root):
    """The installed CLI trains a portable local index without network or Pi."""
    import yaml
    from cota.policy import load_policy, PolicyContext
    bot = root / 'cota_projects' / 'weather'
    config_path = bot / 'agent.yml'
    config = yaml.safe_load(config_path.read_text())
    config['policy'] = {'type': 'bm25', 'max_policies': 4, 'options': {'top_k': 8}}
    config_path.write_text(yaml.safe_dump(config, allow_unicode=True))
    cli = Path(sys.executable).parent / 'cota'
    for extra in ([], ['--check']):
        subprocess.run([str(cli), 'train', '--config', str(bot), *extra],
                       cwd=root, check=True, stdout=subprocess.DEVNULL)
    policy = load_policy(bot, config['policy'])
    guidance = asyncio.run(policy.guidance(PolicyContext(
        'offline-training', observations=({'role': 'user', 'text': '北京天气查询', 'event_id': 'u1'},),
        available_skills=('weather',))))
    assert guidance['policies'] and guidance['method'] == 'BM25Policy'
    assert (bot / 'models' / 'policy.json').is_file()


def main():
    with tempfile.TemporaryDirectory(prefix='cota-offline-smoke-') as directory:
        root = Path(directory)
        (root / 'empty-path').mkdir()
        guard = root / 'offline.cjs'
        guard.write_text("const net = require('node:net');\n"
                         "net.Socket.prototype.connect = function () { throw Error('Network disabled in smoke test'); };\n")
        python_guard = root / 'sitecustomize.py'
        python_guard.write_text("import socket\n"
                                "def blocked(*args, **kwargs): raise RuntimeError('Network disabled in smoke test')\n"
                                "socket.socket.connect = blocked\n"
                                "socket.create_connection = blocked\n")
        os.environ['PATH'] = str(root / 'empty-path')
        os.environ['NODE_OPTIONS'] = f'--require="{guard}"'
        os.environ['PYTHONPATH'] = str(root)
        assert shutil.which('node') is None and shutil.which('npm') is None
        # Guard this process too; subprocesses load the same guard via sitecustomize.
        def blocked(*args, **kwargs):
            raise RuntimeError('Network disabled in smoke test')
        socket.socket.connect = blocked
        socket.create_connection = blocked
        templates = bot_templates_dir()
        assert 'site-packages' in str(templates)
        assert templates.parts[-2:] == ('_templates', 'bots')
        decoy = root / 'bots' / 'unrelated'
        decoy.mkdir(parents=True)
        (decoy / 'agent.yml').write_text('system: {}')
        (decoy / 'endpoints.yml').write_text('{}')
        cli = Path(sys.executable).parent / 'cota'
        subprocess.run([str(cli), '--help'], cwd=root, check=True, stdout=subprocess.DEVNULL)
        subprocess.run([str(cli), 'init'], cwd=root, check=True, stdout=subprocess.DEVNULL)
        bots = root / 'cota_projects'
        assert {p.name for p in bots.iterdir() if p.is_dir()} == {'weather'}
        assert not any(p.name in {'workspace', '.venv', '__pycache__', '.front_cache.html',
                                 '.front_meta.json', 'scheduler_jobs.json'} for p in bots.rglob('*'))
        for name in ('weather',):
            path = bots / name / 'endpoints.yml'
            endpoints = yaml.safe_load(path.read_text())
            endpoints['llms']['default'].update(key='smoke-only', apibase='https://model.example/v1', model='test-model')
            path.write_text(yaml.safe_dump(endpoints))
        setup()  # In a release this is a read-only check, even without --check.
        asyncio.run(smoke())
        asyncio.run(smoke_examples(root))
        smoke_training(root)
    print('Installed wheel: CLI, Policy training, weather Bot template and real Pi tool loop passed without system Node/npm or network.')


if __name__ == '__main__':
    main()
