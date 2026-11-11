"""Portable evaluation contract; no provider credentials needed."""
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import yaml

from cota.evaluation.schema import load_cases
from cota.evaluation.judge import judge_turn
from cota.evaluation.artifacts import compare_runs, write_results


def document(criteria=None):
    return {'policies': [{'name': '预算', 'steps': [
        {'user': '三个人300元'}, {'bot': {'reply-review': criteria or ['价格与工具结果一致', '保留三人']}}]}]}


def save_cases(tmp_path, doc=None):
    root = tmp_path / 'policy/eval'
    root.mkdir(parents=True, exist_ok=True)
    (root / 'basic.yml').write_text(yaml.safe_dump(doc or document(), allow_unicode=True))
    return root


def test_format_ids_and_training_boundary(tmp_path):
    root = save_cases(tmp_path)
    cases = load_cases(root)
    assert cases[0]['id'] == 'basic.yml::预算'
    assert cases[0]['turns'][0] == {'user': '三个人300元', 'reply-review': ['价格与工具结果一致', '保留三人']}
    assert load_cases(root)[0]['hash'] == cases[0]['hash']
    from cota.policy.catalog import PolicyCatalog
    assert PolicyCatalog.load(root.parent).policies == []


@pytest.mark.parametrize('steps', [
    [{'bot': {'reply-review': ['ok']}}],
    [{'user': 'hi'}],
    [{'user': 'hi'}, {'bot': {'skills': ['weather'], 'reply-review': ['ok']}}],
    [{'user': 'hi'}, {'bot': {'reply-review': [{'text': 'ok', 'weight': 2}]}}],
    [{'user': 'hi'}, {'bot': {'reply-review': []}}],
])
def test_invalid_schema_rejected(tmp_path, steps):
    doc = document()
    doc['policies'][0]['steps'] = steps
    with pytest.raises(ValueError):
        load_cases(save_cases(tmp_path, doc))


def test_duplicate_yaml_key_rejected(tmp_path):
    path = tmp_path / 'eval.yml'
    path.write_text('policies: []\npolicies: []\n')
    with pytest.raises(ValueError):
        load_cases(path)


def test_duplicate_names_in_file_rejected(tmp_path):
    doc = document()
    doc['policies'] *= 2
    with pytest.raises(ValueError):
        load_cases(save_cases(tmp_path, doc))


def evidence():
    return [{'event_id': 't1', 'type': 'tool_result', 'payload': {'result': {'price': 60}}},
            {'event_id': 'b1', 'type': 'bot_utter', 'payload': {'text': '三人210元，每人70元'}}]


def verdict(status='fail', refs=None):
    return {'reviews': [{'index': 1, 'status': status, 'reason': '价格不一致', 'evidence': refs or ['t1', 'b1']}]}


@pytest.mark.asyncio
async def test_judge_uses_evidence_not_reference_answers():
    model = SimpleNamespace(generate_chat=AsyncMock(return_value={'content': json.dumps(verdict())}))
    result, trace = await judge_turn(model, ['价格正确'], evidence(), {'user': '三个人', 'replies': ['210元']}, timeout=2)
    assert result['status'] == 'completed'
    assert result['reviews'][0]['status'] == 'fail'
    assert result['reviews'][0]['criterion'] == '价格正确'
    assert '60' in trace['request']['messages'][1]['content']
    assert trace['response']['content']


@pytest.mark.asyncio
async def test_judge_receives_pi_tool_text_body_but_not_debug_or_images():
    from cota.events.tool import result_payload
    payload = result_payload('http_request', 'call', {'status_code': 200}, content=[
        {'type': 'text', 'text': '{"body":"{\\"temperature_2m_max\\": [15.2]}"}'},
        {'type': 'image', 'data': 'BASE64_IMAGE', 'mimeType': 'image/png'}])
    payload['debug'] = {'request': 'PRIVATE_PROMPT'}
    model = SimpleNamespace(generate_chat=AsyncMock(return_value={'content': json.dumps(verdict(refs=['t1']))}))
    events = [{'event_id': 't1', 'type': 'tool_result', 'payload': payload}]
    _, trace = await judge_turn(model, ['预报有依据'], events, {}, timeout=2)
    actual = json.loads(trace['request']['messages'][1]['content'])['events'][0]['payload']
    assert actual['result'] == {'status_code': 200}
    assert actual['content'] == [payload['content'][0]]
    assert '15.2' in actual['content'][0]['text']
    assert 'PRIVATE_PROMPT' not in json.dumps(actual) and 'BASE64_IMAGE' not in json.dumps(actual)


@pytest.mark.asyncio
@pytest.mark.parametrize('response', [
    {'reviews': []}, verdict(refs=['invented']),
    {'reviews': [*verdict()['reviews'], *verdict()['reviews']]},
    {'reviews': [{**verdict()['reviews'][0], 'status': 'maybe'}]},
    {'reviews': [{**verdict()['reviews'][0], 'index': True}]},
])
async def test_malformed_judge_is_error_not_business_failure(response):
    model = SimpleNamespace(generate_chat=AsyncMock(return_value={'content': json.dumps(response)}))
    result, trace = await judge_turn(model, ['价格正确'], evidence(), {}, timeout=2)
    assert result['status'] == 'error'
    assert not result['reviews']
    assert trace['response']


@pytest.mark.asyncio
async def test_judge_exception_does_not_disclose_credentials():
    model = SimpleNamespace(generate_chat=AsyncMock(side_effect=RuntimeError('api_key=SECRET')))
    result, trace = await judge_turn(model, ['ok'], evidence(), {}, timeout=2)
    assert result['status'] == 'error'
    assert 'SECRET' not in json.dumps([result, trace])


def run_record(status='pass', case_hash='case1'):
    return {'schema_version': 1, 'run_id': 'test', 'created_at': 'now', 'status': 'completed',
            'bot': {'hash': 'bot1'}, 'judge': {'hash': 'judge1'}, 'cases': [
                {'id': 'basic.yml::预算', 'hash': case_hash, 'name': '预算', 'repetition': 1,
                 'turns': [{'user': '三个人', 'replies': ['180元'], 'execution': {'status': 'completed'},
                            'judge': {'status': 'completed', 'reviews': [
                                {'index': 1, 'criterion': '价格正确', 'status': status, 'reason': '理由', 'evidence': ['b1']} ]}}]}]}


def test_report_and_comparison_preserve_failures_and_changed_conditions(tmp_path):
    a, b = tmp_path / 'a', tmp_path / 'b'
    a.mkdir(); b.mkdir()
    write_results(a, run_record('fail'))
    write_results(b, run_record('pass'))
    report = (a / 'report.md').read_text()
    assert '价格正确' in report and '理由' in report and 'b1' in report
    comparison = compare_runs([a, b])
    assert comparison['cases'][0]['change'] == 'improved'
    changed = run_record('pass', 'different')
    changed['judge']['hash'] = 'judge2'
    write_results(b, changed)
    comparison = compare_runs([a, b])
    assert comparison['cases'][0]['change'] == 'not_comparable'
    assert comparison['warnings']

from cota.evaluation.runner import evaluate, rejudge


class FakeAgent:
    created = []

    def __init__(self, path):
        self.path = Path(path)
        self.history = []
        self.closed = False
        self.store = SimpleNamespace(export_session=AsyncMock(side_effect=self.export), engine=SimpleNamespace(dispose=lambda: None))
        self.user_memory = None
        self.created.append(self)
        assert not (self.path / 'policy/eval').exists()
        assert not (self.path / 'workspace/original.txt').exists()
        assert (self.path / 'models/policy.json').read_text() == 'trained'
        endpoints = yaml.safe_load((self.path / 'endpoints.yml').read_text())
        assert endpoints['base_store']['dialect'] == 'sqlite'

    async def export(self, session):
        return {'events': list(self.history)}

    def create_processor(self):
        return self

    async def handle_message(self, message):
        number = len(self.history)
        for kind, payload in [('user_utter', {'text': message.text}), ('bot_utter', {'text': '实际回答'}),
                              ('run_finished', {'status': 'completed'})]:
            self.history.append({'event_id': str(number + len(self.history)), 'type': kind, 'payload': payload})

    async def cleanup(self):
        self.closed = True


class FakeJudge:
    instances = []

    def __init__(self, config):
        self.requests = []
        self.closed = False
        self.instances.append(self)

    async def generate_chat(self, **request):
        self.requests.append(request)
        data = json.loads(request['messages'][1]['content'])
        return {'content': json.dumps({'reviews': [
            {'index': i, 'status': 'pass', 'reason': '满足要求', 'evidence': [data['events'][-1]['event_id']]}
            for i, _ in enumerate(data['reply-review'], 1)]})}

    async def close(self):
        self.closed = True


def configured_bot(tmp_path):
    bot = tmp_path / 'bot'
    save_cases(bot)
    (bot / 'agent.yml').write_text('{}\n')
    (bot / 'endpoints.yml').write_text(yaml.safe_dump({'llms': {'default': {
        'key': 'PRIVATE_KEY', 'apibase': 'https://example.test/v1', 'model': 'test'}},
        'base_store': {'type': 'sql', 'dialect': 'mysql', 'password': 'DB_SECRET'}}))
    (bot / 'workspace').mkdir()
    (bot / 'workspace/original.txt').write_text('original memory')
    (bot / 'models').mkdir()
    (bot / 'models/policy.json').write_text('trained')
    return bot


@pytest.mark.asyncio
async def test_runner_isolation_rejudge_and_no_secret_artifacts(tmp_path, monkeypatch):
    import cota.evaluation.runner as runner
    bot = configured_bot(tmp_path)
    doc = document(['HIDDEN_RUBRIC'])
    doc['policies'][0]['steps'] += [{'user': '改成100元'}, {'bot': {'reply-review': ['记住三人']}}]
    save_cases(bot, doc)
    FakeAgent.created = []
    FakeJudge.instances = []
    monkeypatch.setattr(runner.Agent, 'load_from_path', FakeAgent)
    monkeypatch.setattr(runner, 'LLM', FakeJudge)
    output = tmp_path / 'results'
    result = await evaluate(bot, output=output, repeat=2)
    assert len(result['cases']) == 2
    assert len(FakeAgent.created) == 2 and all(a.closed for a in FakeAgent.created)
    for agent in FakeAgent.created:
        assert [e['payload']['text'] for e in agent.history if e['type'] == 'user_utter'] == ['三个人300元', '改成100元']
        assert 'HIDDEN_RUBRIC' not in json.dumps(agent.history)
        assert not agent.path.exists()
    second_request = json.loads(FakeJudge.instances[0].requests[1]['messages'][1]['content'])
    assert any(e['payload'].get('text') == '实际回答' for e in second_request['events'])
    assert all(j.closed for j in FakeJudge.instances)
    serialized = '\n'.join(p.read_text() for p in output.rglob('*.json'))
    assert 'PRIVATE_KEY' not in serialized and 'DB_SECRET' not in serialized
    assert (bot / 'workspace/original.txt').read_text() == 'original memory'
    before = (output / 'results.json').read_bytes()
    monkeypatch.setattr(runner.Agent, 'load_from_path', lambda *a: pytest.fail('rejudge must not execute Bot'))
    again = await rejudge(output, bot, output=tmp_path / 'rejudged')
    assert again['source_run_id'] == result['run_id']
    assert (output / 'results.json').read_bytes() == before
    assert again['cases'][0]['turns'][0]['judge']['status'] == 'completed'
    with pytest.raises(FileExistsError):
        await rejudge(output, bot, output=output)


@pytest.mark.asyncio
async def test_execution_failure_keeps_artifacts_and_skips_following_turns(tmp_path, monkeypatch):
    import cota.evaluation.runner as runner
    bot = configured_bot(tmp_path)
    doc = document()
    doc['policies'][0]['steps'] += [{'user': '第二轮'}, {'bot': {'reply-review': ['ok']}}]
    save_cases(bot, doc)
    monkeypatch.setattr(runner.Agent, 'load_from_path', FakeAgent)
    monkeypatch.setattr(FakeAgent, 'handle_message', AsyncMock(side_effect=RuntimeError('PRIVATE_KEY')))
    monkeypatch.setattr(runner, 'LLM', FakeJudge)
    output = tmp_path / 'results'
    result = await evaluate(bot, output=output)
    turns = result['cases'][0]['turns']
    assert turns[0]['execution']['status'] == 'error'
    assert turns[1]['execution']['status'] == 'skipped'
    assert turns[0]['judge']['status'] == 'skipped'
    assert (output / 'report.md').exists()
    assert 'PRIVATE_KEY' not in (output / 'results.json').read_text()


def test_cli_parser_contract():
    from cota.__main__ import create_argument_parser
    parser = create_argument_parser()
    args = parser.parse_args(['eval', '--config', 'bot'])
    assert args.config == 'bot'
    args = parser.parse_args(['eval', 'compare', 'a', 'b', '--output', 'comparison'])
    assert args.runs == ['a', 'b']
    args = parser.parse_args(['eval', 'judge', '--run', 'a', '--config', 'bot', '--output', 'new'])
    assert args.run == 'a'


@pytest.mark.asyncio
async def test_progress_reports_cases_stages_errors_and_rejudge(tmp_path, monkeypatch):
    import cota.evaluation.runner as runner
    bot = configured_bot(tmp_path)
    monkeypatch.setattr(runner.Agent, 'load_from_path', FakeAgent)
    monkeypatch.setattr(runner, 'LLM', FakeJudge)
    events = []
    await evaluate(bot, output=tmp_path / 'run', repeat=2, progress=events.append)
    assert events[0]['event'] == 'run_started' and events[0]['case_runs'] == 2
    assert [e['phase'] for e in events if e['event'] == 'stage_started'] == ['bot', 'judge'] * 2
    assert [e['index'] for e in events if e['event'] == 'case_finished'] == [1, 2]
    assert events[-1]['event'] == 'run_finished'
    assert events[-1]['summary']['criteria_passed'] == 4
    assert 'PRIVATE_KEY' not in json.dumps(events)
    events.clear()
    await rejudge(tmp_path / 'run', bot, output=tmp_path / 'again', progress=events.append)
    assert [e['phase'] for e in events if e['event'] == 'stage_started'] == ['judge'] * 2
    monkeypatch.setattr(FakeAgent, 'handle_message', AsyncMock(side_effect=RuntimeError('PRIVATE_KEY')))
    events.clear()
    await evaluate(bot, output=tmp_path / 'error', progress=events.append)
    assert events[-1]['summary']['turns_errored'] == 1
    assert [e['phase'] for e in events if e['event'] == 'stage_started'] == ['bot']


@pytest.mark.asyncio
async def test_progress_heartbeat_stops_on_cancellation():
    import asyncio
    from cota.evaluation.progress import Progress
    events = []
    progress = Progress(events.append, interval=0.001)
    async def waiting():
        async with progress.stage('bot', turn=1):
            await asyncio.Event().wait()
    task = asyncio.create_task(waiting())
    while not any(e['event'] == 'heartbeat' for e in events):
        await asyncio.sleep(0.001)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    count = len(events)
    await asyncio.sleep(0.005)
    assert len(events) == count


def test_eval_cli_prints_progress_without_debug(tmp_path, monkeypatch, capsys):
    import cota.evaluation.runner as runner
    from cota.evaluation.cli import run_eval
    from cota.__main__ import create_argument_parser
    bot = configured_bot(tmp_path)
    monkeypatch.chdir(bot)
    monkeypatch.setattr(runner.Agent, 'load_from_path', FakeAgent)
    monkeypatch.setattr(runner, 'LLM', FakeJudge)
    with pytest.raises(SystemExit) as error:
        run_eval(create_argument_parser().parse_args(['eval']))
    assert error.value.code == 0
    output = capsys.readouterr()
    for text in ['准备评测', '[1/1]', 'Bot 执行', 'LLM 评判', '评测完成', '2/2']:
        assert text in output.err
    assert 'results.json' in output.out
    assert 'PRIVATE_KEY' not in output.err


@pytest.mark.asyncio
async def test_timeout_is_infrastructure_error():
    import asyncio
    async def hang(**kwargs):
        await asyncio.Event().wait()
    model = SimpleNamespace(generate_chat=hang)
    result, _ = await judge_turn(model, ['ok'], evidence(), {}, timeout=0.01)
    assert result['status'] == 'error' and result['error_type'] == 'TimeoutError'


@pytest.mark.asyncio
async def test_rejudge_rejects_tampered_trace(tmp_path, monkeypatch):
    import cota.evaluation.runner as runner
    bot = configured_bot(tmp_path)
    monkeypatch.setattr(runner.Agent, 'load_from_path', FakeAgent)
    monkeypatch.setattr(runner, 'LLM', FakeJudge)
    result = await evaluate(bot, output=tmp_path / 'a')
    trace = tmp_path / 'a' / result['cases'][0]['turns'][0]['trace']
    trace.write_text('{"events": []}')
    with pytest.raises(ValueError, match='changed'):
        await rejudge(tmp_path / 'a', bot, output=tmp_path / 'b')
    report = json.loads((tmp_path / 'b/results.json').read_text())
    assert report['status'] == 'interrupted'
    assert all(t['judge']['status'] == 'skipped' for c in report['cases'] for t in c['turns'])


def test_equal_totals_with_different_failed_criteria_are_not_unchanged(tmp_path):
    a, b = run_record('fail'), run_record('pass')
    for run, status in [(a, 'pass'), (b, 'fail')]:
        run['cases'][0]['turns'][0]['judge']['reviews'].append(
            {'index': 2, 'criterion': '人数正确', 'status': status, 'reason': '理由', 'evidence': ['b1']})
    for name, run in [('a', a), ('b', b)]:
        directory = tmp_path / name
        directory.mkdir()
        write_results(directory, run)
    assert compare_runs([tmp_path / 'a', tmp_path / 'b'])['cases'][0]['change'] == 'mixed'


@pytest.mark.asyncio
async def test_group_and_external_workspace_fail_before_creating_output(tmp_path, monkeypatch):
    import cota.evaluation.runner as runner
    bot = configured_bot(tmp_path)
    monkeypatch.setattr(runner, 'LLM', FakeJudge)
    for config in [{'dialogue': {'mode': 'group'}}, {'environment': {'workspace': '/tmp/outside'}}]:
        (bot / 'agent.yml').write_text(yaml.safe_dump(config))
        with pytest.raises(ValueError):
            await evaluate(bot, output=tmp_path / 'result')
        assert not (tmp_path / 'result').exists()


def test_shipped_weather_eval_is_packaged_but_never_trained():
    from cota.policy.catalog import PolicyCatalog
    from cota.templates import template_files
    root = Path(__file__).resolve().parents[1] / 'bots/weather'
    cases = load_cases(root / 'policy/eval')
    assert len(cases) == 30 and sum(len(c['turns']) for c in cases) == 43
    assert len(PolicyCatalog.load(root / 'policy', max_policies=16, max_chars=18000).policies) == 12
    assert root / 'policy/eval/data.yml' in list(template_files(root))
    assert all('模拟' not in turn['user'] for case in cases for turn in case['turns'])


def test_copy_keeps_static_databases_and_excludes_configured_live_store(tmp_path):
    from cota.evaluation.runner import prepare_copy
    bot = configured_bot(tmp_path)
    endpoints = yaml.safe_load((bot / 'endpoints.yml').read_text())
    endpoints['base_store'] = {'type': 'sql', 'dialect': 'sqlite', 'db': 'live.db'}
    (bot / 'endpoints.yml').write_text(yaml.safe_dump(endpoints))
    (bot / 'live.db').write_bytes(b'production history')
    (bot / 'live.db-wal').write_bytes(b'production journal')
    (bot / 'resources').mkdir()
    (bot / 'resources/catalog.db').write_bytes(b'static catalog')
    target = tmp_path / 'copy'
    prepare_copy(bot, target, bot / 'policy/eval')
    assert (target / 'resources/catalog.db').read_bytes() == b'static catalog'
    assert not (target / 'live.db').exists() and not (target / 'live.db-wal').exists()


def test_case_id_stays_stable_when_selecting_nested_file(tmp_path):
    root = save_cases(tmp_path)
    nested = root / 'nested'
    nested.mkdir()
    file = nested / 'extra.yml'
    file.write_text(yaml.safe_dump(document()))
    all_cases = {c['id']: c for c in load_cases(root)}
    selected = load_cases(file)[0]
    assert selected['id'] == 'nested/extra.yml::预算'
    assert all_cases[selected['id']]['hash'] == selected['hash']


def test_comparison_keeps_unjudged_criteria_visible(tmp_path):
    a, b = run_record('pass'), run_record('pass')
    a['cases'][0]['turns'][0]['reply-review'] = ['价格正确']
    a['cases'][0]['turns'][0]['judge'] = {'status': 'error', 'reviews': []}
    for name, run in [('a', a), ('b', b)]:
        directory = tmp_path / name
        directory.mkdir()
        write_results(directory, run)
    row = compare_runs([tmp_path / 'a', tmp_path / 'b'])['cases'][0]
    assert row['change'] == 'inconclusive'
    assert row['criteria'][0]['criterion'] == '价格正确'
    assert row['criteria'][0]['reviews'][0] is None


@pytest.mark.asyncio
@pytest.mark.parametrize('configured, expected', [
    (['default'], 'default'),
    (['default', 'evaluator'], 'evaluator'),
    (['evaluator'], 'evaluator'),
    (['default', 'custom'], 'default'),
])
async def test_judge_model_selection(tmp_path, monkeypatch, configured, expected):
    import cota.evaluation.runner as runner
    (tmp_path / 'endpoints.yml').write_text(yaml.safe_dump({'llms': {
        name: {'model': name} for name in configured}}))
    monkeypatch.setattr(runner, 'LLM', FakeJudge)
    model, identity = runner.judge_resource(tmp_path)
    assert identity['name'] == expected
    assert identity['model'] == expected
    await model.close()


@pytest.mark.parametrize('evaluator', [None, {}, {'model': 'incomplete'}])
def test_invalid_configured_evaluator_does_not_fall_back(tmp_path, evaluator):
    from cota.evaluation.runner import judge_resource
    (tmp_path / 'endpoints.yml').write_text(yaml.safe_dump({'llms': {
        'default': {'key': 'default-key', 'apibase': 'https://example.test/v1', 'model': 'default'},
        'evaluator': evaluator}}))
    with pytest.raises(ValueError):
        judge_resource(tmp_path)


def test_missing_default_and_evaluator_reports_configuration_error(tmp_path):
    from cota.evaluation.runner import judge_resource
    (tmp_path / 'endpoints.yml').write_text(yaml.safe_dump({'llms': {'custom': {}}}))
    with pytest.raises(ValueError, match='Unknown judge model: default'):
        judge_resource(tmp_path)


@pytest.mark.parametrize('command', [
    ['eval'], ['eval', 'judge', '--run', 'old', '--output', 'new'],
])
def test_cli_has_no_judge_override(command):
    from cota.__main__ import create_argument_parser
    parser = create_argument_parser()
    assert not hasattr(parser.parse_args(command), 'judge')
    # Removing --judge must not make it an abbreviation of --judge-timeout.
    with pytest.raises(SystemExit) as error:
        parser.parse_args([*command, '--judge', '12'])
    assert error.value.code == 2
    assert parser.parse_args([*command, '--judge-timeout', '12']).judge_timeout == 12


def test_results_contain_machine_summary_and_unjudged_denominator(tmp_path):
    record = run_record()
    turn = record['cases'][0]['turns'][0]
    turn['reply-review'] = ['价格正确']
    record['cases'][0]['turns'].append({'user': 'next', 'reply-review': ['a', 'b'], 'replies': [],
                                      'execution': {'status': 'skipped'}, 'judge': {'status': 'skipped', 'reviews': []}})
    write_results(tmp_path, record)
    saved = json.loads((tmp_path / 'results.json').read_text())
    stats = saved['summary']
    assert stats['criteria_total'] == 3
    assert stats['criteria_passed'] == 1 and stats['criteria_unjudged'] == 2
    assert stats['criterion_pass_rate'] == pytest.approx(1 / 3)
    assert stats['judgement_coverage'] == pytest.approx(1 / 3)
    assert stats['case_runs'] == 1 and stats['case_pass_rate'] == 0
    assert saved['cases'][0]['summary']['verdict'] == 'inconclusive'


def test_comparison_marks_incremental_improvement_while_case_still_fails(tmp_path):
    from copy import deepcopy
    before = run_record('fail')
    before['cases'][0]['turns'][0]['judge']['reviews'].append(
        {'index': 2, 'criterion': '人数正确', 'status': 'fail', 'reason': '人数错误', 'evidence': ['b1']})
    after = deepcopy(before)
    after['cases'][0]['turns'][0]['judge']['reviews'][0]['status'] = 'pass'
    for name, record in [('a', before), ('b', after)]:
        (tmp_path / name).mkdir()
        write_results(tmp_path / name, record)
    compared = compare_runs([tmp_path / 'a', tmp_path / 'b'])
    assert compared['comparable'] is True
    assert compared['summary']['criterion_pass_rate_delta'] == 0.5
    row = compared['cases'][0]
    assert row['change'] == 'improved' and row['results'][-1]['verdict'] == 'fail'
    assert row['criteria'][0]['change'] == 'improved'
    assert row['criteria'][1]['change'] == 'unchanged'


def test_missing_or_changed_cases_cannot_inflate_comparison_score(tmp_path):
    from copy import deepcopy
    before, after = run_record('fail'), run_record('pass')
    extra = deepcopy(before['cases'][0])
    extra['id'] = 'extra.yml::case'
    before['cases'].append(extra)
    for name, record in [('a', before), ('b', after)]:
        (tmp_path / name).mkdir()
        write_results(tmp_path / name, record)
    compared = compare_runs([tmp_path / 'a', tmp_path / 'b'])
    assert compared['comparable'] is False
    assert compared['summary']['criterion_pass_rate_delta'] is None
    assert 'case_missing' in compared['cases'][1]['reasons']
    assert compared['cases'][0]['change'] == 'improved'


def test_interrupted_run_is_not_a_successful_baseline(tmp_path):
    a, b = run_record(), run_record()
    a['status'] = 'interrupted'
    for name, record in [('a', a), ('b', b)]:
        (tmp_path / name).mkdir()
        write_results(tmp_path / name, record)
    compared = compare_runs([tmp_path / 'a', tmp_path / 'b'])
    assert not compared['comparable']
    assert 'run_incomplete' in compared['cases'][0]['reasons']


def test_suite_identity_ignores_case_order_but_tracks_rubric_edits(tmp_path):
    from copy import deepcopy
    from cota.evaluation.schema import suite_identity
    cases = load_cases(save_cases(tmp_path))
    second = deepcopy(cases[0])
    second.update(id='extra.yml::case', hash='second')
    a = suite_identity([*cases, second])
    assert a == suite_identity([second, *cases])
    assert a['cases'] == 2 and a['criteria'] == 4
    second['hash'] = 'changed'
    assert suite_identity([*cases, second])['hash'] != a['hash']


def test_empty_run_never_exits_successfully():
    from cota.evaluation.artifacts import exit_code
    record = run_record()
    record['cases'] = []
    assert exit_code(record) == 1


@pytest.mark.asyncio
async def test_runner_records_suite_and_code_identity(tmp_path, monkeypatch):
    import cota.evaluation.runner as runner
    bot = configured_bot(tmp_path)
    monkeypatch.setattr(runner.Agent, 'load_from_path', FakeAgent)
    monkeypatch.setattr(runner, 'LLM', FakeJudge)
    result = await evaluate(bot, output=tmp_path / 'run', repeat=2)
    assert result['suite']['cases'] == 1
    assert result['suite']['criteria'] == 2
    assert result['summary']['case_runs'] == 2
    assert result['summary']['criteria_total'] == 4
    assert result['summary']['criterion_pass_rate'] == 1
    assert len(result['bot']['runtime_hash']) == 64
    assert len(result['engine']['evaluation_hash']) == 64
    again = await rejudge(tmp_path / 'run', bot, output=tmp_path / 'again')
    assert again['suite'] == result['suite']
    assert again['bot'] == result['bot']
    assert again['engine'] == result['engine']


@pytest.mark.parametrize('value', [[], {'schema_version': 1}, {'schema_version': 999},
                                 {'schema_version': 1, 'cases': []}])
def test_invalid_result_file_is_an_actionable_error(tmp_path, value):
    from cota.evaluation.artifacts import read_results
    path = tmp_path / 'results.json'
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        read_results(path)


def test_different_execution_budgets_are_explicitly_noncomparable(tmp_path):
    a, b = run_record('fail'), run_record('pass')
    a['execution'] = {'timeout_seconds': 30, 'judge_timeout_seconds': 120}
    b['execution'] = {'timeout_seconds': 300, 'judge_timeout_seconds': 120}
    for name, record in [('a', a), ('b', b)]:
        (tmp_path / name).mkdir()
        write_results(tmp_path / name, record)
    compared = compare_runs([tmp_path / 'a', tmp_path / 'b'])
    assert not compared['comparable']
    assert 'execution_settings_changed' in compared['cases'][0]['reasons']
    assert compared['runs'][0]['execution']['timeout_seconds'] == 30


@pytest.mark.asyncio
async def test_rejudge_records_actual_judge_timeout(tmp_path, monkeypatch):
    import cota.evaluation.runner as runner
    bot = configured_bot(tmp_path)
    monkeypatch.setattr(runner.Agent, 'load_from_path', FakeAgent)
    monkeypatch.setattr(runner, 'LLM', FakeJudge)
    await evaluate(bot, output=tmp_path / 'run', judge_timeout=30)
    again = await rejudge(tmp_path / 'run', bot, output=tmp_path / 'again', judge_timeout=60)
    assert again['execution']['judge_timeout_seconds'] == 60


def test_comparison_cli_writes_machine_and_human_views(tmp_path, monkeypatch):
    from cota import __main__ as cli
    for name, record in [('before', run_record('fail')), ('after', run_record('pass'))]:
        (tmp_path / name).mkdir()
        write_results(tmp_path / name, record)
    output = tmp_path / 'comparison'
    monkeypatch.setattr('sys.argv', ['cota', 'eval', 'compare', str(tmp_path / 'before'), str(tmp_path / 'after'),
                                    '--output', str(output)])
    cli.main()
    value = json.loads((output / 'comparison.json').read_text())
    assert value['comparable'] and value['summary']['criterion_pass_rate_delta'] == 1
    report = (output / 'report.md').read_text()
    assert '价格正确' in report and '改善' in report


@pytest.mark.parametrize('damage', ['duplicate', 'invalid_status', 'missing_review'])
def test_result_validation_rejects_corrupted_comparison_inputs(tmp_path, damage):
    from copy import deepcopy
    from cota.evaluation.artifacts import read_results
    record = run_record()
    if damage == 'duplicate':
        record['cases'].append(deepcopy(record['cases'][0]))
    elif damage == 'invalid_status':
        record['cases'][0]['turns'][0]['execution']['status'] = 'bad'
    else:
        record['cases'][0]['turns'][0]['reply-review'] = ['价格正确', '人数正确']
    (tmp_path / 'results.json').write_text(json.dumps(record))
    with pytest.raises(ValueError):
        read_results(tmp_path)
