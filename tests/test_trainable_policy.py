import json
import asyncio
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import yaml



def examples():
    return [
        {'name': '天气查询', 'steps': [{'user': '查询天气温度'}, {'bot': [
            {'skills': ['weather']}, {'result': '天气服务查询成功'},
            {'thought': '使用实际天气回答'}, {'reply': '示例温度'}]}]},
        {'name': '取消订单', 'steps': [{'user': '取消订单退款'}, {'bot': [
            {'skills': ['orders']}, {'thought': '核实订单后取消'}]}]},
    ]


def setup_bot(tmp_path, kind='bm25', options=None):
    (tmp_path / 'policy').mkdir(exist_ok=True)
    (tmp_path / 'policy' / 'data.yml').write_text(yaml.safe_dump({'policies': examples()}, allow_unicode=True))
    config = {'type': kind, 'options': options or {}}
    (tmp_path / 'agent.yml').write_text(yaml.safe_dump({'policy': config}))
    (tmp_path / 'endpoints.yml').write_text('{}')
    return config


def context(text='查询北京天气', session='s'):
    from cota.policy import PolicyContext
    return PolicyContext(session_id=session, observations=(
        {'role': 'user', 'text': text, 'event_id': 'u1'},
    ), available_skills=('weather', 'orders'), read_skills=())


@pytest.mark.asyncio
async def test_bm25_train_reload_and_stale_detection(tmp_path):
    from cota.policy import train_policy, load_policy
    config = setup_bot(tmp_path)
    with pytest.raises(ValueError, match='cota train'):
        load_policy(tmp_path, config)
    await train_policy(tmp_path, config)
    loaded = load_policy(tmp_path, config)
    result = await loaded.guidance(context())
    assert result['policies'][0]['name'] == '天气查询'
    assert result['decisions'][0]['status'] == 'candidate'
    assert 'Result（示例结果条件）' in result['text']
    artifact = tmp_path / 'models' / 'policy.json'
    assert json.loads(artifact.read_text())['type'] == 'bm25'
    assert not (tmp_path / 'workspace').exists()
    data = examples()
    data[0]['steps'][0]['user'] = 'new data'
    (tmp_path / 'policy' / 'data.yml').write_text(yaml.safe_dump({'policies': data}))
    with pytest.raises(ValueError, match='cota train'):
        load_policy(tmp_path, config)


@pytest.mark.asyncio
async def test_query_change_and_no_match_do_not_keep_previous_business(tmp_path):
    from cota.policy import train_policy, load_policy
    config = setup_bot(tmp_path)
    await train_policy(tmp_path, config)
    policy = load_policy(tmp_path, config)
    assert (await policy.guidance(context()))['policies'][0]['name'] == '天气查询'
    assert (await policy.guidance(context('取消订单退款')))['policies'][0]['name'] == '取消订单'
    assert (await policy.guidance(context('xyzxyz')))['policies'] == []


@pytest.mark.asyncio
async def test_rule_training_is_literal_and_does_not_claim_result(tmp_path):
    from cota.policy import train_policy, load_policy
    config = setup_bot(tmp_path, 'rule', {'rules': [
        {'policy': '取消订单', 'field': 'latest_user', 'any': ['不要了', '取消订单']},
    ]})
    await train_policy(tmp_path, config)
    selected = await load_policy(tmp_path, config).guidance(context('不要了'))
    assert [p['name'] for p in selected['policies']] == ['取消订单']
    assert selected['decisions'][0]['status'] == 'candidate'


@pytest.mark.asyncio
async def test_custom_policy_training_and_common_reference_validation(tmp_path):
    from cota.policy import Policy, Selection, Match, register_policy, train_policy, load_policy
    class CustomPolicy(Policy):
        version = 'test-1'
        async def train(self, services):
            return {'names': [self.policies[1]['name']]}
        async def select(self, ctx, services):
            return Selection([Match(name=self.state['names'][0])])
    register_policy('test-custom', CustomPolicy)
    config = setup_bot(tmp_path, 'test-custom')
    await train_policy(tmp_path, config)
    result = await load_policy(tmp_path, config).guidance(context())
    assert result['policies'][0]['name'] == '取消订单'
    with pytest.raises(ValueError):
        register_policy('test-custom', CustomPolicy)


@pytest.mark.asyncio
async def test_model_selection_checks_evidence_and_caches_exact_context(tmp_path):
    from cota.policy import train_policy, load_policy, PolicyServices
    config = setup_bot(tmp_path, 'model', {'llm': 'judge'})
    client = SimpleNamespace(generate_chat=AsyncMock(return_value={'content': json.dumps({'matches': [
        {'name': '天气查询', 'step': 1, 'status': 'conditional', 'evidence': ['u1'], 'reason': '尚未查询'},
    ]})}))
    services = PolicyServices(model=lambda name: client)
    await train_policy(tmp_path, config, services)
    policy = load_policy(tmp_path, config)
    result = await policy.guidance(context(), services)
    assert result['decisions'][0]['status'] == 'conditional'
    assert result['decisions'][0]['evidence'] == ['u1']
    assert result['policies'][0] == examples()[0]
    again = await policy.guidance(context(), services)
    assert again['cache_hit'] is True
    assert client.generate_chat.await_count == 1
    await policy.guidance(context(session='other'), services)
    assert client.generate_chat.await_count == 2
    client.generate_chat.return_value = {'content': json.dumps({'matches': [
        {'name': '天气查询', 'step': 1, 'status': 'applicable', 'evidence': ['invented'], 'reason': 'bad'},
    ]})}
    bad = await policy.guidance(context('different request'), services)
    assert bad['diagnostics'] and all(m['status'] == 'candidate' for m in bad['decisions'])


def test_policy_context_excludes_injected_guidance_and_unretained_evidence(mock_agent):
    from cota.policy import PolicyContext
    from cota.dst import DST
    from cota.events import UserUtterEvent
    dst = DST('s', mock_agent)
    dst.append_event(UserUtterEvent('真实问题'))
    ctx = PolicyContext.from_runtime([
        {'role': 'system', 'content': 'EXAMPLE_FAKE_FACT'},
        {'role': 'user', 'content': '真实问题'},
        {'role': 'assistant', 'content': [{'type': 'thinking', 'thinking': 'PRIVATE_REASONING'}]},
    ], dst, ['SearchWeb'], [])
    content = json.dumps(ctx.as_dict(), ensure_ascii=False)
    assert '真实问题' in content
    assert dst.latest_user_event.event_id in content
    assert 'EXAMPLE_FAKE_FACT' not in content and 'PRIVATE_REASONING' not in content


def test_train_cli_runs_without_store_or_model_and_checks_staleness(tmp_path):
    setup_bot(tmp_path)
    result = subprocess.run([sys.executable, '-m', 'cota', 'train', '--config', str(tmp_path)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    checked = subprocess.run([sys.executable, '-m', 'cota', 'train', '--config', str(tmp_path), '--check'], capture_output=True, text=True)
    assert checked.returncode == 0, checked.stderr
    assert '产物校验通过' in checked.stdout
    assert not list(tmp_path.rglob('*.db'))


@pytest.mark.asyncio
async def test_embedding_trains_vectors_then_embeds_only_query_and_binds_encoder(tmp_path):
    from cota.policy import train_policy, load_policy, PolicyServices
    config = setup_bot(tmp_path, 'embedding', {'embedding': 'semantic'})
    endpoints = {'embeddings': {'semantic': {'type': 'openai', 'model': 'encoder-v1', 'key': 'secret', 'apibase': 'https://example.invalid'}}}
    (tmp_path / 'endpoints.yml').write_text(yaml.safe_dump(endpoints))
    embed = AsyncMock(side_effect=[[[1.0, 0.0], [0.0, 1.0]], [[0.0, 1.0]]])
    await train_policy(tmp_path, config, PolicyServices(embedding=embed))
    policy = load_policy(tmp_path, config)
    result = await policy.guidance(context('我不想买了'), PolicyServices(embedding=embed))
    assert result['policies'][0]['name'] == '取消订单'
    assert len(embed.call_args_list[0].args[1]) == 2
    assert len(embed.call_args_list[1].args[1]) == 1
    artifact = (tmp_path / 'models/policy.json').read_text()
    assert 'secret' not in artifact and 'example.invalid' not in artifact
    endpoints['embeddings']['semantic']['key'] = 'rotated-secret'
    (tmp_path / 'endpoints.yml').write_text(yaml.safe_dump(endpoints))
    load_policy(tmp_path, config)
    endpoints['embeddings']['semantic']['model'] = 'encoder-v2'
    (tmp_path / 'endpoints.yml').write_text(yaml.safe_dump(endpoints))
    with pytest.raises(ValueError, match='cota train'):
        load_policy(tmp_path, config)


@pytest.mark.asyncio
async def test_failed_training_preserves_existing_artifact(tmp_path):
    from cota.policy import train_policy, PolicyServices
    config = setup_bot(tmp_path, 'embedding', {'embedding': 'semantic'})
    good = PolicyServices(embedding=AsyncMock(return_value=[[1, 0], [0, 1]]))
    await train_policy(tmp_path, config, good)
    path = tmp_path / 'models/policy.json'
    before = path.read_bytes()
    bad = PolicyServices(embedding=AsyncMock(return_value=[[1, 0], [1]]))
    with pytest.raises(ValueError, match='dimension'):
        await train_policy(tmp_path, config, bad)
    assert path.read_bytes() == before


def tool_call(name, args, call_id='1'):
    return {'id': call_id, 'type': 'function', 'function': {'name': name, 'arguments': json.dumps(args)}}


@pytest.mark.asyncio
async def test_search_model_greps_and_reads_only_policy_corpus(tmp_path):
    from cota.policy import train_policy, load_policy, PolicyServices
    config = setup_bot(tmp_path, 'search_model', {'llm': 'judge'})
    client = SimpleNamespace(generate_chat=AsyncMock(side_effect=[
        {'tool_calls': [tool_call('grep_policies', {'query': '天气'})]},
        {'tool_calls': [tool_call('read_policy', {'name': '天气查询'}, '2')]},
        {'content': json.dumps({'matches': [{'name': '天气查询', 'step': 1, 'status': 'conditional',
                                           'evidence': ['u1'], 'reason': '需要实际查询结果'}]})},
    ]))
    await train_policy(tmp_path, config)
    result = await load_policy(tmp_path, config).guidance(context(), PolicyServices(model=lambda name: client))
    assert not result['diagnostics']
    assert result['policies'][0]['name'] == '天气查询'
    requests = client.generate_chat.call_args_list
    assert {t['function']['name'] for t in requests[0].kwargs['tools']} == {'grep_policies', 'read_policy'}
    assert any(m['role'] == 'tool' and 'case' in m['content'] for m in requests[-1].kwargs['messages'])


@pytest.mark.asyncio
async def test_retrieval_model_judges_only_candidates_and_falls_back_to_them(tmp_path):
    from cota.policy import train_policy, load_policy, PolicyServices
    config = setup_bot(tmp_path, 'retrieval_model', {'llm': 'judge', 'retriever_options': {'top_k': 1}})
    await train_policy(tmp_path, config)
    client = SimpleNamespace(generate_chat=AsyncMock(return_value={'content': 'malformed'}))
    result = await load_policy(tmp_path, config).guidance(context(), PolicyServices(model=lambda name: client))
    assert [p['name'] for p in result['policies']] == ['天气查询']
    assert result['diagnostics'][0]['code'] == 'model_fallback_to_retrieval'
    payload = json.loads(client.generate_chat.call_args.kwargs['messages'][1]['content'])
    assert [p['name'] for p in payload['cases']] == ['天气查询']


@pytest.mark.asyncio
async def test_cancellation_not_converted_to_policy_fallback(tmp_path):
    from cota.policy import train_policy, load_policy, PolicyServices
    config = setup_bot(tmp_path, 'model', {'llm': 'judge'})
    await train_policy(tmp_path, config)
    client = SimpleNamespace(generate_chat=AsyncMock(side_effect=asyncio.CancelledError))
    with pytest.raises(asyncio.CancelledError):
        await load_policy(tmp_path, config).guidance(context(), PolicyServices(model=lambda name: client))


@pytest.mark.parametrize('config', [
    {'type': 'bm25', 'options': {'top_k': 0}}, {'type': 'model', 'options': {}},
    {'type': 'embedding', 'options': {'embedding': 'e', 'min_score': float('nan')}},
    {'type': 'all', 'unknown': 1}, {'type': 'all', 'options': {'llm': 'x'}},
    {'type': 'all', 'context_chars': 1}, {'type': 'all', 'timeout_seconds': True},
    {'type': 'retrieval_model', 'options': {'llm': 'judge', 'retriever': 'unknown'}},
])
def test_strategy_config_rejects_unknown_and_invalid_options(config):
    from cota.config import validate_bot_config
    with pytest.raises(ValueError):
        validate_bot_config({'policy': config})


@pytest.mark.asyncio
async def test_context_retains_only_real_visible_tool_evidence(mock_agent):
    from cota.policy import PolicyContext
    from cota.runtime.pi_runtime import PiAgentRuntime
    from cota.dst import DST
    from cota.events import UserUtterEvent
    from tests.test_pi_runtime import call
    dst = DST('s', mock_agent)
    dst.append_event(UserUtterEvent('search'))
    mock_agent._llm_mock.generate_chat.side_effect = [
        {'tool_calls': [call('read', {'path': mock_agent.skill_file('SearchWeb')}, 'r')]}, {'content': 'done'},
    ]
    await PiAgentRuntime(mock_agent, dst, 's').run()
    ctx = PolicyContext.from_runtime(dst.context_messages, dst, ['SearchWeb'], ['SearchWeb'])
    result = next(e for e in dst.events if e.type == 'tool_result')
    assert result.event_id in ctx.evidence_ids
    without = PolicyContext.from_runtime([{'role': 'user', 'content': 'new task'}], dst, ['SearchWeb'], [])
    assert result.event_id not in without.evidence_ids


@pytest.mark.asyncio
async def test_corrupt_artifact_and_changed_options_are_rejected(tmp_path):
    from cota.policy import train_policy, load_policy
    config = setup_bot(tmp_path)
    await train_policy(tmp_path, config)
    changed = {**config, 'options': {'top_k': 1}}
    with pytest.raises(ValueError, match='cota train'):
        load_policy(tmp_path, changed)
    path = tmp_path / 'models/policy.json'
    artifact = json.loads(path.read_text())
    artifact['state']['documents'][0]['terms']['injected'] = 1000
    path.write_text(json.dumps(artifact))
    with pytest.raises(ValueError, match='cota train'):
        load_policy(tmp_path, config)


@pytest.mark.asyncio
async def test_installed_module_policy_uses_same_training_contract(tmp_path, monkeypatch):
    from cota.policy import train_policy, load_policy
    module = tmp_path / 'custom_business_policy.py'
    module.write_text('''from cota.policy import Policy, Selection, Match
class CustomPolicy(Policy):
    version = 'company-1'
    async def train(self, services):
        return {'chosen': self.policies[0]['name']}
    async def select(self, context, services):
        return Selection([Match(self.state['chosen'])])
''')
    monkeypatch.syspath_prepend(str(tmp_path))
    config = setup_bot(tmp_path, 'custom_business_policy:CustomPolicy')
    await train_policy(tmp_path, config)
    result = await load_policy(tmp_path, config).guidance(context())
    assert result['policies'][0]['name'] == '天气查询'


@pytest.mark.asyncio
async def test_trained_policy_in_real_pi_loop_and_store_trace(mock_agent, tmp_path):
    from cota.policy import train_policy, load_policy
    from cota.dst import DST
    from cota.events import UserUtterEvent
    from cota.store import MemoryStore
    from cota.runtime.pi_runtime import PiAgentRuntime
    from tests.test_pi_runtime import call
    config = setup_bot(tmp_path)
    values = examples()
    for value in values:
        value['steps'][1]['bot'][0]['skills'] = ['SearchWeb']
    (tmp_path / 'policy/data.yml').write_text(yaml.safe_dump({'policies': values}, allow_unicode=True))
    await train_policy(tmp_path, config)
    mock_agent.policy = load_policy(tmp_path, config)
    mock_agent._llm_mock.generate_chat.side_effect = [
        {'tool_calls': [call('read', {'path': mock_agent.skill_file('SearchWeb')})]}, {'content': '请提供城市'},
    ]
    dst, store = DST('trained', mock_agent), MemoryStore()
    dst.append_event(UserUtterEvent('查询天气温度'))
    await PiAgentRuntime(mock_agent, dst, 'trained', checkpoint=store.save).run()
    for request in mock_agent._llm_mock.generate_chat.call_args_list:
        system = request.kwargs['messages'][0]['content']
        assert 'Policy:' not in system
        guidance = str(request.kwargs['messages'][-1]['content'])
        assert 'Policy: 天气查询' in guidance and 'Policy: 取消订单' not in guidance
        assert '示例温度' not in str(request.kwargs['messages'][1:-1])
    restored = (await store.load('trained', agent=mock_agent))
    selections = [e.payload['llm']['policy'] for e in restored.events if e.payload.get('llm')]
    assert len(selections) == 2
    assert all(s['method'] == 'BM25Policy' and s['decisions'][0]['status'] == 'candidate' for s in selections)
    assert [e.text for e in restored.events if e.type == 'user_utter'] == ['查询天气温度']


@pytest.mark.asyncio
async def test_empty_model_selection_is_not_replaced_by_all_cases(tmp_path):
    from cota.policy import train_policy, load_policy, PolicyServices
    config = setup_bot(tmp_path, 'model', {'llm': 'judge'})
    await train_policy(tmp_path, config)
    client = SimpleNamespace(generate_chat=AsyncMock(return_value={'content': '{"matches": []}'}))
    result = await load_policy(tmp_path, config).guidance(context('闲聊'), PolicyServices(model=lambda name: client))
    assert not result['text'] and not result['policies'] and not result['diagnostics']


@pytest.mark.asyncio
async def test_common_renderer_enforces_budget_without_losing_case_conditions(tmp_path):
    from cota.policy import load_policy
    config = setup_bot(tmp_path, 'all')
    config['max_policies'] = 1
    policy = load_policy(tmp_path, config)
    result = await policy.guidance(context())
    assert len(result['policies']) == 1
    assert result['policies'][0] == examples()[0]
    assert result['omitted_policies'] == [{'name': '取消订单', 'reason': 'max_policies'}]
    assert '天气服务查询成功' in result['text'] and '示例温度' in result['text']


@pytest.mark.asyncio
async def test_context_change_invalidates_cached_model_judgment(tmp_path):
    from cota.policy import PolicyContext, PolicyServices, train_policy, load_policy
    config = setup_bot(tmp_path, 'model', {'llm': 'judge'})
    await train_policy(tmp_path, config)
    client = SimpleNamespace(generate_chat=AsyncMock(return_value={'content': '{"matches": []}'}))
    policy, services = load_policy(tmp_path, config), PolicyServices(model=lambda name: client)
    await policy.guidance(context(), services)
    observed = PolicyContext('s', observations=(*context().observations,
        {'role': 'tool', 'text': 'HTTP 503', 'event_id': 't1'}), available_skills=context().available_skills)
    result = await policy.guidance(observed, services)
    assert not result['cache_hit'] and client.generate_chat.await_count == 2


def test_bounded_context_keeps_latest_user_when_tool_outputs_are_large(mock_agent):
    from cota.policy import PolicyContext
    from cota.dst import DST
    from cota.events import UserUtterEvent
    dst = DST('s', mock_agent)
    dst.append_event(UserUtterEvent('查订单 A123，不要取消'))
    messages = [{'role': 'user', 'content': dst.latest_user_event.text}] + [
        {'role': 'toolResult', 'toolName': 'lookup', 'toolCallId': str(i),
         'content': [{'type': 'text', 'text': 'x' * 8000}]} for i in range(10)]
    ctx = PolicyContext.from_runtime(messages, dst, ['orders'], [], max_chars=2000)
    assert ctx.text('latest_user') == dst.latest_user_event.text
    assert len(json.dumps(ctx.as_dict()['observations'], ensure_ascii=False)) <= 2000
    assert any(item.get('truncated') for item in ctx.observations)


@pytest.mark.asyncio
@pytest.mark.parametrize('field', ['key', 'apibase', 'model'])
async def test_embedding_rejects_environment_references_before_http(monkeypatch, field):
    import openai
    from cota.policy.resources import PolicyResources
    monkeypatch.setenv('MODEL_SETTING', 'must-not-be-used')
    def unexpected_client(**kwargs):
        raise AssertionError('Invalid configuration must fail before creating HTTP client')
    monkeypatch.setattr(openai, 'AsyncOpenAI', unexpected_client)
    config = {'model': 'encoder', 'key': 'test', 'apibase': 'https://example.invalid/v1'}
    config[field] = '${MODEL_SETTING}'
    resources = PolicyResources({'embeddings': {'semantic': config}})
    with pytest.raises(ValueError, match='endpoints.yml'):
        await resources.embed('semantic', ['weather'])


@pytest.mark.asyncio
async def test_embedding_http_adapter_uses_named_resource_and_orders_response(monkeypatch):
    import httpx
    import openai
    from cota.policy.resources import PolicyResources
    original = openai.AsyncOpenAI
    requests = []
    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={'object': 'list', 'model': 'encoder', 'data': [
            {'object': 'embedding', 'index': 1, 'embedding': [0, 1]},
            {'object': 'embedding', 'index': 0, 'embedding': [1, 0]},
        ], 'usage': {'prompt_tokens': 1, 'total_tokens': 1}})
    monkeypatch.setattr(openai, 'AsyncOpenAI', lambda **kwargs: original(
        **kwargs, http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond))))
    resources = PolicyResources({'embeddings': {'semantic': {
        'model': 'encoder', 'key': 'test', 'apibase': 'https://example.invalid/v1', 'dimensions': 2,
    }}})
    assert await resources.embed('semantic', ['weather', 'orders']) == [[1, 0], [0, 1]]
    assert requests == [{'model': 'encoder', 'input': ['weather', 'orders'], 'encoding_format': 'float', 'dimensions': 2}]


@pytest.mark.asyncio
async def test_not_applicable_and_invalid_focus_are_not_injected_as_current_rules(tmp_path):
    from cota.policy import train_policy, load_policy, PolicyServices
    config = setup_bot(tmp_path, 'model', {'llm': 'judge'})
    await train_policy(tmp_path, config)
    client = SimpleNamespace(generate_chat=AsyncMock(return_value={'content': json.dumps({'matches': [
        {'name': '天气查询', 'step': 1, 'status': 'not_applicable', 'evidence': ['u1'], 'reason': '用户不需要'},
    ]})}))
    policy = load_policy(tmp_path, config)
    result = await policy.guidance(context(), PolicyServices(model=lambda _: client))
    assert not result['text'] and result['decisions'][0]['status'] == 'not_applicable'
    client.generate_chat.return_value = {'content': json.dumps({'matches': [
        {'name': '天气查询', 'step': 0, 'status': 'applicable', 'evidence': ['u1'], 'reason': 'wrong user step'},
    ]})}
    invalid = await policy.guidance(context('换个说法'), PolicyServices(model=lambda _: client))
    assert invalid['diagnostics'] and all(m['status'] == 'candidate' for m in invalid['decisions'])
