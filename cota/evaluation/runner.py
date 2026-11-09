"""Execute the selected Bot in fresh local state; judge/rejudge immutable evidence."""
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
from fnmatch import fnmatchcase
import math
from pathlib import Path
import shutil
import tempfile
from uuid import uuid4

from cota import __version__
from cota.agent import Agent
from cota.llm import LLM
from cota.message.message import Message
from cota.templates import TEMPLATE_IGNORE

from .artifacts import read_results, write_json, write_results
from .judge import JUDGE_VERSION, judge_turn
from .provenance import source_identity
from .metrics import summary
from .progress import Progress
from .schema import SCHEMA_VERSION, digest, load_cases, read_yaml, suite_identity


def now():
    return datetime.now(timezone.utc).isoformat()


def positive(value, label):
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        raise ValueError(f'{label} must be positive and finite')


def model_identity(config):
    # Never publish endpoint URLs, credentials, request headers or arbitrary provider settings.
    nonsecret = {k: v for k, v in config.items() if k not in ('key', 'api_key', 'password', 'headers')}
    return {'type': config.get('type', 'openai'), 'model': config.get('model'), 'config_hash': digest(nonsecret)}


def judge_resource(root):
    endpoints = read_yaml(Path(root) / 'endpoints.yml') or {}
    models = endpoints.get('llms', {})
    name = 'evaluator' if 'evaluator' in models else 'default'
    config = models.get(name)
    if not isinstance(config, dict):
        raise ValueError(f'Unknown judge model: {name}; configure llms.{name} in endpoints.yml')
    identity = {**model_identity(config), 'name': name, 'prompt_version': JUDGE_VERSION, 'max_tokens': 4096}
    identity['hash'] = digest(identity)
    return LLM(config), identity


def prepare_copy(root, target, case_source):
    """Keep trained artifacts/resources, exclude evaluation answers and deployment state."""
    source_endpoints = read_yaml(root / 'endpoints.yml') or {}
    store = source_endpoints.get('base_store', {})
    live_database = None
    if store.get('dialect', '').startswith('sqlite') and store.get('db', 'cota.db') != ':memory:':
        live_database = (root / store.get('db', 'cota.db')).resolve()

    def ignore(directory, names):
        excluded = set(TEMPLATE_IGNORE(directory, names)) | {'.git', 'evaluations'}
        parent = Path(directory)
        if parent == root / 'policy':
            excluded.add('eval')
        for name in names:
            child = parent / name
            # Template packaging drops all databases. Evaluation must retain static
            # business fixtures and exclude only the configured runtime database.
            if any(fnmatchcase(name, pattern) for pattern in ('*.db', '*.db-*', '*.sqlite*')):
                excluded.discard(name)
            if live_database and (child.resolve() == live_database or
                                  str(child.resolve()).startswith(str(live_database) + '-')):
                excluded.add(name)
            if child == case_source or child.is_symlink():
                if child.is_symlink() and name not in excluded:
                    raise ValueError('Evaluation Bot copies do not support symlinked resources')
                excluded.add(name)
        return excluded
    shutil.copytree(root, target, ignore=ignore)
    config = read_yaml(target / 'agent.yml') or {}
    if config.get('dialogue', {}).get('mode', 'direct') != 'direct':
        raise ValueError('This evaluation format supports direct conversations only')
    workspace = config.get('environment', {}).get('workspace')
    if workspace:
        bound = (root / workspace).resolve()
        if not bound.is_relative_to(root) or bound == root:
            raise ValueError('Evaluation environment.workspace must be a subdirectory inside the Bot')
        config['environment']['workspace'] = bound.relative_to(root).as_posix()
    # Hash the exact copied definition before substituting isolated persistence.
    files = {p.relative_to(target).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted(target.rglob('*')) if p.is_file() and p.name != 'endpoints.yml'}
    endpoints = read_yaml(target / 'endpoints.yml') or {}
    models = {name: model_identity(value) for name, value in endpoints.get('llms', {}).items()}
    # Provider/embedding/resource config affects behavior, but secrets must not enter artifacts.
    identity = {'files': files, 'models': models, 'cota_version': __version__,
                'embeddings': {k: model_identity(v) for k, v in endpoints.get('embeddings', {}).items()}}
    identity['runtime_hash'] = source_identity()['runtime_hash']
    identity['hash'] = digest(identity)
    endpoints['base_store'] = {'type': 'sql', 'dialect': 'sqlite', 'db': 'workspace/evaluation.db'}
    import yaml
    (target / 'agent.yml').write_text(yaml.safe_dump(config, allow_unicode=True), encoding='utf-8')
    (target / 'endpoints.yml').write_text(yaml.safe_dump(endpoints, allow_unicode=True), encoding='utf-8')
    return identity


async def close_agent(agent):
    try:
        await agent.cleanup()
    finally:
        for owner, attribute in ((agent.store, 'engine'), (agent.user_memory, '_engine')):
            engine = getattr(owner, attribute, None)
            if engine is not None:
                engine.dispose()


def new_result(bot, judge):
    return {'schema_version': SCHEMA_VERSION, 'run_id': uuid4().hex, 'created_at': now(),
            'status': 'running', 'bot': bot, 'judge': judge, 'engine': source_identity(), 'cases': []}


def planned_case(case, repetition):
    return {k: deepcopy(v) for k, v in case.items() if k != 'turns'} | {
        'repetition': repetition, 'turns': [dict(deepcopy(t), replies=[], execution={'status': 'skipped'},
                                               judge={'status': 'skipped', 'reviews': []}) for t in case['turns']]}


async def judge_record(model, turn, state, output, stem, timeout):
    events = state.get('events', [])[:turn['event_count']]
    turn['judge'], trace = await judge_turn(model, turn['reply-review'], events,
                                          {'user': turn['user'], 'replies': turn['replies']}, timeout=timeout)
    turn['judge_trace'] = f'traces/{stem}.judge.json'
    write_json(output / turn['judge_trace'], trace)


async def execute_case(bot, case, model, output, index, *, timeout, judge_timeout, debug, checkpoint, progress):
    agent = None
    try:
        agent = Agent.load_from_path(str(bot))
        if debug:
            agent.store.enable_debug_log(str(bot / 'workspace/evaluation.log'))
        session = uuid4().hex
        for number, turn in enumerate(case['turns'], 1):
            stem = f'{index:04d}-{number:03d}'
            before = len((await agent.store.export_session(session) or {}).get('events', []))
            try:
                async with progress.stage('bot', turn=number, timeout_seconds=timeout):
                    await asyncio.wait_for(agent.create_processor().handle_message(Message(
                        text=turn['user'], session_id=session, sender_id=session, receiver='bot')), timeout)
                turn['execution'] = {'status': 'completed'}
            except Exception as error:
                turn['execution'] = {'status': 'error', 'error_type': type(error).__name__}
            state = await agent.store.export_session(session) or {'events': []}
            events = state['events'][before:]
            turn['event_count'] = len(state['events'])
            turn['replies'] = [e['payload']['text'] for e in events if e['type'] == 'bot_utter']
            finished = [e for e in events if e['type'] == 'run_finished']
            if turn['execution']['status'] == 'completed' and (
                    not finished or finished[-1]['payload'].get('status') != 'completed'):
                turn['execution'] = {'status': 'error', 'error_type': 'IncompleteRun'}
            if debug:
                state['model_debug'] = {}
                for event in state['events']:
                    request_id = event['payload'].get('llm', {}).get('request_id')
                    if request_id:
                        state['model_debug'][request_id] = await agent.store.model_debug(session, request_id)
            turn['trace'] = f'traces/{stem}.execution.json'
            write_json(output / turn['trace'], state)
            turn['trace_hash'] = digest(state)
            checkpoint()
            if turn['execution']['status'] != 'completed':
                progress.emit('turn_finished', turn=number, execution=turn['execution'], judge=turn['judge']['status'])
                break
            async with progress.stage('judge', turn=number, timeout_seconds=judge_timeout):
                await judge_record(model, turn, state, output, stem, judge_timeout)
            checkpoint()
            progress.emit('turn_finished', turn=number, execution=turn['execution'], judge=turn['judge']['status'])
    except Exception as error:
        pending = next((t for t in case['turns'] if t['execution']['status'] == 'skipped'), case['turns'][-1])
        pending['execution'] = {'status': 'error', 'error_type': type(error).__name__}
    finally:
        if agent is not None:
            await close_agent(agent)


async def evaluate(config, *, output=None, cases=None, repeat=1, case_ids=None,
                   timeout=300, judge_timeout=120, debug=False, progress=None):
    progress = Progress(progress)
    root = Path(config).resolve()
    case_source = Path(cases).resolve() if cases else root / 'policy/eval'
    definitions = load_cases(case_source)
    if case_ids:
        unknown = set(case_ids) - {c['id'] for c in definitions}
        if unknown:
            raise ValueError('Unknown case IDs: ' + ', '.join(sorted(unknown)))
        definitions = [c for c in definitions if c['id'] in case_ids]
    if type(repeat) is not int or repeat < 1:
        raise ValueError('repeat must be a positive integer')
    positive(timeout, 'timeout'); positive(judge_timeout, 'judge_timeout')
    model, judge_info = judge_resource(root)
    result = None
    try:
        with tempfile.TemporaryDirectory(prefix='cota-eval-') as directory:
            base = Path(directory) / 'definition'
            identity = prepare_copy(root, base, case_source)
            result = new_result(identity, judge_info)
            output = Path(output).resolve() if output else root / 'workspace/evaluations' / result['run_id']
            output.mkdir(parents=True, exist_ok=False)
            result['cases'] = [planned_case(c, n) for c in definitions for n in range(1, repeat + 1)]
            result['suite'] = suite_identity(definitions)
            result['execution'] = {'repeat': repeat, 'timeout_seconds': timeout, 'judge_timeout_seconds': judge_timeout, 'debug': debug}
            write_results(output, result)
            progress.emit('run_started', case_runs=len(result['cases']),
                          turns=sum(len(c['turns']) for c in result['cases']),
                          judge=judge_info['name'], output=str(output))
            try:
                for index, case in enumerate(result['cases'], 1):
                    progress.case(case, index, len(result['cases']))
                    bot = Path(directory) / f'case-{index}'
                    shutil.copytree(base, bot)
                    await execute_case(bot, case, model, output, index, timeout=timeout,
                                       judge_timeout=judge_timeout, debug=debug, checkpoint=lambda: write_results(output, result),
                                       progress=progress)
                    shutil.rmtree(bot)
                    write_results(output, result)
                    progress.emit('case_finished', summary=summary(case))
                result['status'] = 'completed'
            finally:
                if result['status'] == 'running':
                    result['status'] = 'interrupted'
                result['finished_at'] = now()
                write_results(output, result)
                progress.finish(result)
            return result
    finally:
        await model.close()


async def rejudge(run, config, *, output, judge_timeout=120, progress=None):
    progress = Progress(progress)
    positive(judge_timeout, 'judge_timeout')
    source = Path(run).resolve()
    source = source if source.is_dir() else source.parent
    previous = read_results(source)
    result = deepcopy(previous)
    model, identity = judge_resource(Path(config).resolve())
    output = Path(output).resolve()
    try:
        output.mkdir(parents=True, exist_ok=False)
        result.update(run_id=uuid4().hex, source_run_id=previous['run_id'], created_at=now(),
                      judge=identity, engine=source_identity(), status='running')
        result.pop('finished_at', None)
        result.setdefault('execution', {})['judge_timeout_seconds'] = judge_timeout
        for case in result['cases']:
            for turn in case['turns']:
                turn['judge'] = {'status': 'skipped', 'reviews': []}
                turn.pop('judge_trace', None)
        write_results(output, result)
        progress.emit('run_started', case_runs=len(result['cases']),
                      turns=sum(len(c['turns']) for c in result['cases']), judge=identity['name'], output=str(output))
        try:
            for index, case in enumerate(result['cases'], 1):
                progress.case(case, index, len(result['cases']))
                for number, turn in enumerate(case['turns'], 1):
                    turn['judge'] = {'status': 'skipped', 'reviews': []}
                    turn.pop('judge_trace', None)
                    if not turn.get('trace'):
                        continue
                    if Path(turn['trace']).is_absolute():
                        raise ValueError('Trace path must be relative')
                    trace_path = (source / turn['trace']).resolve()
                    if not trace_path.is_relative_to(source):
                        raise ValueError('Trace path must stay inside the source run')
                    import json
                    state = json.loads(trace_path.read_text(encoding='utf-8'))
                    if digest(state) != turn['trace_hash']:
                        raise ValueError('Saved execution trace has changed')
                    write_json(output / turn['trace'], state)
                    if turn['execution']['status'] == 'completed':
                        async with progress.stage('judge', turn=number, timeout_seconds=judge_timeout):
                            await judge_record(model, turn, state, output, f'{index:04d}-{number:03d}', judge_timeout)
                        write_results(output, result)
                        progress.emit('turn_finished', turn=number, execution=turn['execution'], judge=turn['judge']['status'])
                write_results(output, result)
                progress.emit('case_finished', summary=summary(case))
            result['status'] = 'completed'
        finally:
            if result['status'] == 'running':
                result['status'] = 'interrupted'
            result['finished_at'] = now()
            write_results(output, result)
            progress.finish(result)
        return result
    finally:
        await model.close()
