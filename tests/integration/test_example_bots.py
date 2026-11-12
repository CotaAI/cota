"""Load shipped weather and test-only Bots; run real Pi/Core, OpenAI serialization, tools and SQLite.

Only external model/weather HTTP boundaries are deterministic. These tests make
no claim about a real model's decisions or public services' availability.
"""
from collections import deque
import json
from pathlib import Path
import shutil

import httpx
import yaml
from openai import AsyncOpenAI
import pytest
import pytest_asyncio

from cota.agent import Agent
from cota.executor.tools.base import FunctionTool
from cota.executor.tools.registry import ToolPolicy
from cota.message.message import Message
from cota.templates import TEMPLATE_IGNORE
from tests.test_pi_runtime import call

BOTS = Path(__file__).resolve().parents[2] / 'bots'
FIXTURE_BOTS = Path(__file__).resolve().parents[1] / 'fixtures' / 'bots'


class ModelHTTP:
    def __init__(self, responses):
        self.responses = deque(responses)
        self.requests = []

    def __call__(self, request):
        self.requests.append(json.loads(request.content))
        assert self.responses, 'Unexpected additional model call'
        message = {'role': 'assistant', **self.responses.popleft()}
        return httpx.Response(200, json={
            'id': 'completion-test', 'object': 'chat.completion', 'created': 1,
            'model': 'test-model', 'choices': [{'index': 0, 'message': message,
                'finish_reason': 'tool_calls' if message.get('tool_calls') else 'stop'}],
            'usage': {'prompt_tokens': 10, 'completion_tokens': 10, 'total_tokens': 20},
        })


@pytest_asyncio.fixture
async def load_bot(tmp_path, monkeypatch):
    agents = []

    async def load(name, responses):
        target = tmp_path / name
        if not target.exists():
            source = BOTS if name == 'weather' else FIXTURE_BOTS
            shutil.copytree(source / name, target, ignore=TEMPLATE_IGNORE)
        endpoints_path = target / 'endpoints.yml'
        endpoints = yaml.safe_load(endpoints_path.read_text())
        endpoints['llms']['default'].update(key='test-only', apibase='https://model.example/v1', model='test-model')
        endpoints_path.write_text(yaml.safe_dump(endpoints))
        agent = Agent.load_from_path(str(target))
        agents.append(agent)
        adapter = agent.llm_instance('default').client
        # This fixture exercises the Python HTTP adapter contract. Native Node
        # streaming has its own real local SSE/worker integration tests.
        agent.llm_instance('default').pi_provider = lambda: None
        original = adapter.client
        script = ModelHTTP(responses)
        adapter.client = AsyncOpenAI(api_key=original.api_key, base_url=original.base_url,
                                    max_retries=0, http_client=httpx.AsyncClient(
                                        transport=httpx.MockTransport(script)))
        await original.close()
        return agent, script

    yield load
    for agent in agents:
        await agent.cleanup()
        agent.store.engine.dispose()
        agent.user_memory._engine.dispose()


async def send(agent, text, session='room', user='user'):
    await agent.create_processor().handle_message(Message(
        text=text, session_id=session, sender_id=user, receiver='bot'))
    return await agent.store.export_session(session)


def fake_weather_api(agent, responses):
    """Exercise the generic adapter with controlled weather data, without network.

    Native Node HTTP transport/security has separate runtime tests. This fixture
    keeps the shipped Bot, model serialization, Pi loop and Store real.
    """
    pending = deque(responses)
    requests = []

    async def weather_lookup(url):
        requests.append(url)
        assert pending, 'Unexpected additional weather request'
        status, body = pending.popleft()
        if status >= 400:
            return {'success': False, 'error': f'HTTP {status}', 'data': body}
        return {'success': True, 'data': body}

    agent.get_tool_registry().register(FunctionTool(
        name='weather_lookup', description='Controlled weather API fixture',
        parameters={'type': 'object', 'properties': {'url': {'type': 'string'}},
                    'required': ['url']}, handler=weather_lookup,
    ))
    agent.get_tool_registry().set_policy(ToolPolicy(allow=['web_fetch', 'weather_lookup']))
    return requests, pending


@pytest.mark.asyncio
async def test_hello_restart_and_session_isolation(load_bot):
    agent, first = await load_bot('hello', [{'content': '你好，小明。'}, {'content': '你好，新朋友。'}])
    await send(agent, '我叫小明', 'a', 'alice')
    await send(agent, '你好', 'b', 'bob')
    assert '小明' not in json.dumps(first.requests[1]['messages'], ensure_ascii=False)
    assert not first.requests[0].get('tools')
    await agent.cleanup()
    agent.store.engine.dispose()
    restored, second = await load_bot('hello', [{'content': '你叫小明。'}])
    saved = await send(restored, '我叫什么', 'a', 'alice')
    assert saved['execution']['engine'] == 'pi'
    assert saved['execution']['status'] == 'completed'
    assert [m['content'] for m in second.requests[0]['messages'] if m['role'] == 'user'] == ['我叫小明', '我叫什么']
    assert [e['payload']['text'] for e in await restored.store.history('a')] == ['我叫小明', '你好，小明。', '我叫什么', '你叫小明。']
    assert [e['payload']['text'] for e in await restored.store.history('b')] == ['你好', '你好，新朋友。']
    assert not first.responses and not second.responses


@pytest.mark.asyncio
async def test_weather_skill_question_restart_api_and_history(load_bot):
    agent, first = await load_bot('weather', [
        {'tool_calls': [call('read', {'path': 'skills/weather/SKILL.md'}, 'read-weather')]},
        {'content': '你想查询哪个城市的天气？'},
    ])
    question = await send(agent, '帮我查下天气')
    assert question['execution']['status'] == 'completed'
    assert question['active_skill'] == 'weather'
    assert 'weather-city' in first.requests[0]['messages'][0]['content']
    assert 'weather-city' in first.requests[1]['messages'][0]['content']
    assert 'web_fetch' in first.requests[1]['messages'][-1]['content']
    await agent.cleanup()
    agent.store.engine.dispose()
    restored, second = await load_bot('weather', [
        {'tool_calls': [call('weather_lookup', {'url': 'https://wttr.in/Beijing?format=j1'}, 'weather-data')]},
        {'content': '北京当前 18°C，湿度 40%；来源 wttr.in，观测时间 08:00 AM。'},
    ])
    requests, pending = fake_weather_api(restored, [(200, {
        'nearest_area': [{'areaName': [{'value': 'Beijing'}]}],
        'current_condition': [{'temp_C': '18', 'humidity': '40', 'observation_time': '08:00 AM'}],
    })])
    done = await send(restored, '北京')
    assert done['execution']['status'] == 'completed'
    assert '不能照抄案例或猜测' in second.requests[0]['messages'][0]['content']
    assert 'paused_state' not in done and done.get('active_skill') == 'weather'
    assert len(requests) == 1 and not pending
    assert [m['content'] for m in second.requests[0]['messages'] if m['role'] == 'user'] == ['帮我查下天气', '北京']
    assert [e['payload']['text'] for e in await restored.store.history('room')][:3] == ['帮我查下天气', '你想查询哪个城市的天气？', '北京']
    trace = await restored.store.history('room', include_execution=True)
    http_events = [e for e in trace if e['type'] == 'tool_result' and e['payload']['tool'] == 'weather_lookup']
    assert len(http_events) == 1
    assert http_events[0]['payload']['result']['success'] is True
    assert '18' in json.dumps(http_events[0], ensure_ascii=False)
    # Both result branches are examples even before a query. Only actual 18°C
    # data reaches the tool history; the successful example's 22°C does not.
    for request in [*first.requests, *second.requests]:
        system = request['messages'][0]['content']
        assert 'weather-success' in system and 'weather-unavailable' in system
        assert 'Result（示例结果条件）: 查询成功' in system
        assert '22°C' not in str(request['messages'][1:])
    assert '22°C' not in str(http_events)
    assert any(e['type'] == 'run_finished' for e in trace)
    view = await restored.store.trace('room', done['execution']['run_id'])
    assert view['status'] == 'completed'
    assert len(view['calls']) == 1
    assert view['skills'] == []
    assert [e['payload']['resource']['skill'] for e in view['skill_history']] == ['weather']
    assert not first.responses and not second.responses
    # Real policy data must reach the model without rewriting the user's text.
    assert '<business_guidance>' in first.requests[0]['messages'][0]['content']
    assert 'weather-selection' in first.requests[0]['messages'][0]['content']


@pytest.mark.asyncio
async def test_weather_failure_and_fallback_results_reach_model(load_bot):
    agent, model = await load_bot('weather', [
        {'tool_calls': [call('read', {'path': 'skills/weather/SKILL.md'}, 'read-weather')]},
        {'tool_calls': [call('weather_lookup', {'url': 'https://wttr.in/Unknown?format=j1'}, 'primary')]},
        {'tool_calls': [call('weather_lookup', {'url': 'https://geocoding-api.open-meteo.com/v1/search?name=Unknown&count=3&language=zh&format=json'}, 'fallback')]},
        {'content': '暂时查不到这个城市的天气，请确认城市名称。'},
    ])
    requests, pending = fake_weather_api(agent, [(503, {'error': 'unavailable'}), (200, {'results': []})])
    state = await send(agent, '查 Unknown 的天气')
    assert state['execution']['status'] == 'completed'
    assert len(requests) == 2 and not pending and not model.responses
    results = [m['content'] for m in model.requests[-1]['messages'] if m['role'] == 'tool']
    assert any('HTTP 503' in r for r in results)
    assert any('results' in r for r in results)
    for request in model.requests:
        assert 'weather-city-not-found' in request['messages'][0]['content']
        assert 'weather-invalid-data' in request['messages'][0]['content']
        assert '22°C' not in str(request['messages'][1:])
    events = await agent.store.history('room', include_execution=True)
    assert any(e['type'] == 'tool_result' and e['payload']['tool'] == 'weather_lookup' and e['payload']['result'].get('success') is False for e in events)


@pytest.mark.asyncio
async def test_hello_cannot_execute_network_tool_even_if_model_requests_it(load_bot):
    agent, model = await load_bot('hello', [
        {'tool_calls': [call('web_fetch', {'url': 'http://127.0.0.1:1'}, 'forbidden')]},
        {'content': '没有配置网络查询能力。'},
    ])
    state = await send(agent, '访问网页')
    assert state['execution']['status'] == 'completed'
    tool_results = [m['content'] for m in model.requests[-1]['messages'] if m['role'] == 'tool']
    assert tool_results and any('web_fetch' in r for r in tool_results)
    assert not model.responses


@pytest.mark.asyncio
async def test_weather_service_rejects_private_http_target(load_bot):
    agent, model = await load_bot('weather', [
        {'tool_calls': [call('web_fetch', {'url': 'http://127.0.0.1:1'}, 'private')]},
        {'content': '无法访问该地址。'},
    ])
    state = await send(agent, '访问本机地址')
    assert state['execution']['status'] == 'completed'
    events = await agent.store.history('room', include_execution=True)
    result = next(e for e in events if e['type'] == 'tool_result')
    assert result['payload']['status'] == 'error'
    assert result['payload']['result']['error'] == 'Blocked URL (private/reserved IP)'
    assert not model.responses


@pytest.mark.asyncio
async def test_pet_business_policy_question_and_cancel(load_bot):
    agent, model = await load_bot('pet', [
        {'tool_calls': [call('read', {'path': 'skills/pet-care/SKILL.md'}, 'read-pet')]},
        {'content': '你养的是什么宠物？'},
        {'content': '好的，需要时再来找我。'},
    ])
    question = await send(agent, '帮我安排宠物的日常照护')
    assert question['execution']['status'] == 'completed'
    done = await send(agent, '先不弄了')
    assert 'paused_state' not in done
    assert done['execution']['status'] == 'completed'
    assert [e['payload']['text'] for e in await agent.store.history('room')] == [
        '帮我安排宠物的日常照护', '你养的是什么宠物？', '先不弄了', '好的，需要时再来找我。']
    assert not model.responses
    assert '明确日常照护需求' in model.requests[0]['messages'][0]['content']
    assert '尊重用户取消' in model.requests[2]['messages'][0]['content']
    assert 'pet-cancel' in model.requests[0]['messages'][0]['content']
    assert 'pet-cancel' in model.requests[1]['messages'][0]['content']


@pytest.mark.asyncio
@pytest.mark.parametrize('name', ['hello', 'pet', 'weather'])
async def test_bot_role_reaches_model(load_bot, name):
    agent, model = await load_bot(name, [{'content': '你好。'}])
    await send(agent, '你好')
    assert agent.description in model.requests[0]['messages'][0]['content']


@pytest.mark.asyncio
async def test_reviewed_policy_is_saved_and_used_by_reloaded_bot(load_bot):
    from cota.dst import DST
    from cota.annotation_files import export_worksheet, write_worksheet

    agent, original = await load_bot('weather', [{'content': '无法回答。'}])
    state = await send(agent, '请查询北京天气')
    dst = DST.from_events(state['session_id'], state['events'], agent=agent, revision=state['revision'])
    document = export_worksheet(dst)
    document['policies'][0]['name'] = 'reviewed-weather'
    document['policies'][0]['steps'][1]['bot'] = [
        {'thought': 'REVIEWED_SELECTION: 阅读 weather 并查询真实结果'}, {'skills': ['weather']},
        {'result': 'REVIEWED_RESULT: 示例查询失败，无法确认当前天气'},
        {'thought': 'REVIEWED_REPLY: 失败时说明，禁止编造'}, {'reply': '这是经过核对的查询结果'},
    ]
    assert all(p['name'] != 'reviewed-weather' for p in agent.policy.policies)
    path = Path(agent.config_path) / 'policy' / 'reviewed.yml'
    write_worksheet(path, document)
    assert await agent.store.export_session(dst.session_id) == state
    await agent.cleanup()
    agent.store.engine.dispose()
    updated, script = await load_bot('weather', [
        {'tool_calls': [call('read', {'path': 'skills/weather/SKILL.md'}, 'reviewed-read')]},
        {'content': '已阅读天气查询指引。'},
    ])
    result = await send(updated, '继续查询北京天气')
    for request in script.requests:
        assert 'REVIEWED_SELECTION' in request['messages'][0]['content']
        assert 'REVIEWED_REPLY' in request['messages'][0]['content']
        assert 'Result（示例结果条件）: REVIEWED_RESULT' in request['messages'][0]['content']
        assert 'REVIEWED_RESULT' not in str(request['messages'][1:])
    trace = await updated.store.trace('room', result['execution']['run_id'])
    assert trace['skills'][0]['payload']['resource']['skill'] == 'weather'
    prepared = next(e['payload']['llm']['policy'] for e in trace['events'] if e['payload'].get('llm'))
    assert 'reviewed-weather' in [p['name'] for p in prepared['policies']]
    old_trace = await updated.store.trace('room', state['execution']['run_id'])
    assert 'policy_annotations' not in old_trace
    assert old_trace['events'] == [e for e in state['events'] if e['run_id'] == state['execution']['run_id']]
    assert not original.responses and not script.responses


@pytest.mark.asyncio
@pytest.mark.parametrize('weather_status', [200, 503])
async def test_weather_outing_resources_policy_and_replay(load_bot, weather_status):
    """Real Pi resource reads and policy injection; model decisions are scripted."""
    from cota.events.resources import skill_read_name
    agent, model = await load_bot('weather', [
        {'tool_calls': [call('read', {'path': f'skills/{skill}/SKILL.md'}, skill)
                        for skill in ('weather', 'activity-search', 'outing-plan')]},
        {'tool_calls': [call('read', {'path': 'skills/activity-search/activities.json'}, 'catalog')]},
        {'tool_calls': [call('weather_lookup', {'url': 'https://wttr.in/Hangzhou?format=j1'}, 'forecast')]},
        {'content': '科技探索馆适合带孩子去，三人门票180元。'},
    ])
    requests, pending = fake_weather_api(agent, [(weather_status, {'temperature_c': 18, 'city': '杭州'})])
    saved = await send(agent, '杭州，两大一小，门票总预算三百，帮我安排今天的亲子活动')
    events = await agent.store.events('room')
    references = [e for e in events if e['type'] == 'tool_result'
                  and e['payload'].get('resource', {}).get('kind') == 'reference']
    assert len(references) == 1
    resource = references[0]['payload']['resource']
    assert resource['skill'] == 'activity-search'
    assert resource['path'].endswith('/activity-search/activities.json')
    assert resource['hash'].startswith('sha256:')
    from cota.events import Event
    assert skill_read_name(Event.from_dict(references[0])) is None  # Data read is not another Skill activation.
    last = model.requests[-1]
    assert 'hz-science' in str(last['messages'])
    assert 'outing-weather-unavailable' in last['messages'][0]['content']
    assert 'outing-budget' in last['messages'][0]['content']
    assert {t['function']['name'] for t in last['tools']} == {'read', 'web_fetch', 'weather_lookup'}
    assert requests and not pending and not model.responses
    restored = await agent.store.load('room', agent=agent)
    assert restored.context_messages == saved['context_messages']
    assert {'weather', 'activity-search', 'outing-plan'} <= {
        e['payload']['resource']['skill'] for e in events
        if e['type'] == 'tool_result' and e['payload'].get('resource', {}).get('kind') == 'skill'}


@pytest.mark.asyncio
async def test_outing_city_budget_updates_survive_reload_and_do_not_leak(load_bot):
    agent, first = await load_bot('weather', [
        {'tool_calls': [call('read', {'path': 'skills/activity-search/SKILL.md'})]},
        {'tool_calls': [call('read', {'path': 'skills/activity-search/activities.json'})]},
        {'content': '科技探索馆三人180元。'},
    ])
    await send(agent, '杭州，两大一小，只要室内，门票三百以内，不查天气。', 'alice', 'alice')
    await agent.cleanup()
    agent.store.engine.dispose()
    restored, model = await load_bot('weather', [
        {'content': '三人一百元暂时没有合适的室内活动。'},
        {'content': '上海可以考虑海洋探索馆，三人270元。'},
        {'content': '请问你希望在哪个城市找活动？'},
    ])
    await send(restored, '预算改成一百，其他不变。', 'alice', 'alice')
    await send(restored, '换上海，预算恢复三百，人数不变。', 'alice', 'alice')
    await send(restored, '推荐个活动吧。', 'bob', 'bob')
    users = [m['content'] for m in model.requests[1]['messages'] if m['role'] == 'user']
    assert users == ['杭州，两大一小，只要室内，门票三百以内，不查天气。',
                     '预算改成一百，其他不变。', '换上海，预算恢复三百，人数不变。']
    assert any('hz-science' in str(m.get('content')) for m in model.requests[1]['messages'] if m['role'] == 'tool')
    assert not any(m['role'] == 'tool' for m in model.requests[2]['messages'])
    assert [m['content'] for m in model.requests[2]['messages'] if m['role'] == 'user'] == ['推荐个活动吧。']
    assert not any(e['type'] == 'tool_started' and e['payload']['tool'] == 'web_fetch'
                   for e in await restored.store.events('alice'))
    assert not first.responses and not model.responses


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['missing', 'malformed', 'outside'])
async def test_activity_catalog_failures_reach_pi_without_escaping_resources(load_bot, kind):
    path = 'skills/activity-search/activities.json' if kind != 'outside' else 'private.json'
    agent, model = await load_bot('weather', [
        {'tool_calls': [call('read', {'path': 'skills/activity-search/SKILL.md'})]},
        {'tool_calls': [call('read', {'path': path})]},
        {'content': '活动资料暂不可用，无法确认候选。'},
    ])
    catalog = Path(agent.config_path) / 'skills/activity-search/activities.json'
    if kind == 'missing':
        catalog.unlink()
    elif kind == 'malformed':
        catalog.write_text('{broken-json', encoding='utf-8')
    else:
        (Path(agent.config_path) / path).write_text('OUTSIDE_SECRET', encoding='utf-8')
    state = await send(agent, '杭州有哪些活动？')
    results = [e['payload'] for e in state['events'] if e['type'] == 'tool_result']
    if kind == 'malformed':
        assert results[-1]['status'] == 'success'  # read returns bytes, not business validity.
        assert '{broken-json' in str(model.requests[-1]['messages'])
    else:
        assert results[-1]['status'] != 'success'
        assert 'OUTSIDE_SECRET' not in json.dumps(model.requests, ensure_ascii=False)
    assert state['execution']['status'] == 'completed'
    assert not model.responses


@pytest.mark.asyncio
async def test_portable_evaluation_runs_real_pi_and_judge_transport(tmp_path, monkeypatch):
    from cota.evaluation.runner import evaluate, rejudge
    import openai
    from cota.llm import LLM
    monkeypatch.setattr(LLM, 'pi_provider', lambda self: None)

    root = tmp_path / 'weather'
    shutil.copytree(BOTS / 'weather', root, ignore=TEMPLATE_IGNORE)
    endpoints = {'llms': {
        'default': {'type': 'openai', 'key': 'test-only', 'apibase': 'https://model.example/v1', 'model': 'bot-model'},
        'evaluator': {'type': 'openai', 'key': 'judge-only', 'apibase': 'https://model.example/v1', 'model': 'judge-model'}}}
    (root / 'endpoints.yml').write_text(yaml.safe_dump(endpoints))
    (root / 'policy/eval/data.yml').write_text(yaml.safe_dump({'policies': [
        {'name': 'greeting', 'steps': [{'user': '你好'}, {'bot': {'reply-review': ['HIDDEN_REVIEW']}},
                                     {'user': '谢谢'}, {'bot': {'reply-review': ['友好回应']}}]}]}, allow_unicode=True))
    bot_model = ModelHTTP([
        {'tool_calls': [call('read', {'path': 'skills/activity-search/SKILL.md'})]},
        {'content': '你好，可以帮你查询天气和活动。'}, {'content': '不客气。'}])
    judge_requests = []

    def transport(request):
        data = json.loads(request.content)
        if data['model'] == 'bot-model':
            return bot_model(request)
        judge_requests.append(data)
        facts = json.loads(data['messages'][1]['content'])
        answer = {'reviews': [{'index': 1, 'status': 'pass', 'reason': '符合',
                               'evidence': [facts['events'][-1]['event_id']]}]}
        return ModelHTTP([{'content': json.dumps(answer)}])(request)

    # Preserve the real SDK configuration and hooks; substitute only its HTTP
    # transport so endpoint retry settings are not supplied twice by this test.
    monkeypatch.setattr(openai, 'DefaultAsyncHttpxClient', lambda **kwargs: httpx.AsyncClient(
        transport=httpx.MockTransport(transport), **kwargs))
    output = tmp_path / 'evaluation'
    result = await evaluate(root, output=output, debug=True)
    assert result['status'] == 'completed'
    assert result['judge']['name'] == 'evaluator'
    turns = result['cases'][0]['turns']
    assert all(t['execution']['status'] == 'completed' and t['judge']['status'] == 'completed' for t in turns)
    assert len(judge_requests) == 2 and not bot_model.responses
    assert 'HIDDEN_REVIEW' not in json.dumps(bot_model.requests)
    assert 'HIDDEN_REVIEW' in json.dumps(judge_requests)
    assert [m['content'] for m in bot_model.requests[-1]['messages'] if m['role'] == 'user'] == ['你好', '谢谢']
    state = json.loads((output / turns[1]['trace']).read_text())
    assert state['model_debug'] and any(state['model_debug'].values())
    assert any(e['type'] == 'tool_result' for e in state['events'])
    count = len(bot_model.requests)
    rejudged = await rejudge(output, root, output=tmp_path / 'rejudge')
    assert rejudged['judge']['name'] == 'evaluator'
    assert len(bot_model.requests) == count and len(judge_requests) == 4
    assert not (root / 'workspace').exists()


def test_init_weather_thirty_cases_run_through_eval_cli(tmp_path, monkeypatch):
    """Real init/Pi/Store/CLI over all authored inputs; scripted model verdicts, not accuracy."""
    from types import SimpleNamespace
    from cota import __main__ as cli
    from cota.evaluation.judge import PROMPT
    from cota.evaluation.schema import load_cases
    from cota.llm import LLM

    monkeypatch.chdir(tmp_path)
    cli.init(SimpleNamespace())
    root = tmp_path / 'cota_projects/weather'
    cases = load_cases(root / 'policy/eval')
    assert len(cases) == 30
    endpoints = yaml.safe_load((root / 'endpoints.yml').read_text())
    endpoints['llms']['default'].update(key='test-only', apibase='https://model.example/v1', model='test-model')
    (root / 'endpoints.yml').write_text(yaml.safe_dump(endpoints))
    judged = []

    async def respond(self, messages, **kwargs):
        if messages[0]['content'] != PROMPT:
            return {'content': '受控测试回复。', 'finish_reason': 'stop'}
        data = json.loads(messages[-1]['content'])
        judged.append(data)
        bot_event = next(e for e in reversed(data['events']) if e['type'] == 'bot_utter')
        return {'content': json.dumps({'reviews': [
            {'index': i, 'status': 'pass', 'reason': '受控评委输出，仅验证协议', 'evidence': [bot_event['event_id']]}
            for i, _ in enumerate(data['reply-review'], 1)]}), 'finish_reason': 'stop'}

    monkeypatch.setattr(LLM, 'generate_chat', respond)
    monkeypatch.setattr(LLM, 'pi_provider', lambda self: None)
    output = tmp_path / 'evaluation'
    monkeypatch.setattr('sys.argv', ['cota', 'eval', '--config', str(root), '--output', str(output)])
    with pytest.raises(SystemExit) as exit_info:
        cli.main()
    assert exit_info.value.code == 0
    result = json.loads((output / 'results.json').read_text())
    assert len(judged) == result['summary']['turns_completed'] == 43
    assert result['summary']['case_runs'] == result['suite']['cases'] == 30
    assert result['summary']['criteria_total'] == result['suite']['criteria']
    assert result['summary']['judgement_coverage'] == 1
    assert len(list((output / 'traces').glob('*.execution.json'))) == 43
    assert len(list((output / 'traces').glob('*.judge.json'))) == 43
    assert result['summary']['criterion_pass_rate'] == 1  # Scripted judge, NOT a real-model accuracy claim.
    assert result['engine']['evaluation_hash'] and result['bot']['runtime_hash']
    assert not (root / 'workspace').exists()
