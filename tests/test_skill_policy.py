from copy import deepcopy

import pytest
import yaml

from cota.policy import PolicyCatalog


def policy(name='天气查询', skills=None):
    return {'name': name, 'steps': [
        {'user': '查北京天气'},
        {'bot': [{'thought': '先选择可靠的天气能力'}, {'skills': skills or ['weather']},
                 {'thought': '成功时说明来源；失败时不编造'}, {'reply': '以下是查询结果'}]},
    ]}


def result_policy():
    value = policy()
    value['steps'][1]['bot'].insert(2, {'result': '查询成功，示例城市晴，气温 22°C。'})
    return value


def test_results_preserve_example_order_and_are_not_reply_or_execution_evidence(tmp_path):
    value = result_policy()
    failed = deepcopy(value)
    failed['name'] = '查询失败'
    failed['steps'][1]['bot'][2] = {'result': '天气服务不可用，未获取到天气数据。'}
    path = tmp_path / 'branches.yml'
    path.write_text(yaml.safe_dump({'policies': [value, failed]}, allow_unicode=True))
    catalog = PolicyCatalog.load(path)
    guidance = catalog.guidance(['weather'], [])
    assert catalog.policies == guidance['policies'] == [value, failed]
    text = guidance['text']
    assert text.index('Skills: weather') < text.index('Result（示例结果条件）: 查询成功') < text.index('成功时说明')
    assert 'Result（示例结果条件）: 天气服务不可用' in text
    assert 'Reply 示例: 查询成功' not in text
    assert '示例 result 不是实际工具结果' in text
    assert '结果缺失、失败或无法确认时' in text
    assert [t['target'] for t in guidance['thoughts']] == ['skills', 'reply', 'skills', 'reply']
    # Reading a Skill affects priority, never selects a claimed result branch.
    assert catalog.guidance(['weather'], ['weather'])['policies'] == [value, failed]


def test_thought_skips_results_and_multiple_skill_result_sequences_keep_order():
    value = {'name': '查询后继续处理', 'steps': [{'bot': [
        {'skills': ['orders']}, {'result': '找到订单'},
        {'thought': '根据订单查询物流'}, {'result': '订单附带运单号'},
        {'skills': ['shipping']}, {'result': '物流已发出'},
        {'thought': '据实告知'}, {'result': '暂无预计送达日期'}, {'reply': '已发出，暂无预计送达日期'},
        {'thought': '后续有更新时再告知'}, {'result': '本例没有更多更新'},
    ]}]}
    guidance = PolicyCatalog([value]).guidance(['orders', 'shipping'], [])
    assert [(t['item'], t['target'], t['target_item']) for t in guidance['thoughts']] == [
        (2, 'skills', 4), (6, 'reply', 8), (9, 'continuation', None),
    ]
    assert guidance['policies'] == [value]
    assert guidance['text'].index('Skills: orders') < guidance['text'].index('找到订单') < guidance['text'].index('Skills: shipping')


@pytest.mark.parametrize('result', ['', '  ', None, 42, True, [], {}, {'status': 'ok'}])
def test_result_requires_nonempty_natural_language_text(result):
    value = result_policy()
    value['steps'][1]['bot'][2] = {'result': result}
    with pytest.raises(ValueError):
        PolicyCatalog([value])


def test_results_count_toward_whole_policy_budget():
    value = result_policy()
    limit = len(PolicyCatalog([value]).guidance(['weather'], [])['text'])
    assert PolicyCatalog([value], max_chars=limit).guidance(['weather'], [])['policies'] == [value]
    with pytest.raises(ValueError, match='max_chars'):
        PolicyCatalog([value], max_chars=limit - 1)


def test_ordered_thoughts_are_preserved_and_attributed_to_next_behavior():
    value = policy()
    catalog = PolicyCatalog([value])
    assert catalog.policies == [value]
    guidance = catalog.guidance(['weather'], [])
    assert guidance['policies'] == [value]
    thoughts = guidance['thoughts']
    assert [(t['item'], t['target'], t['target_item']) for t in thoughts] == [(0, 'skills', 1), (2, 'reply', 3)]
    assert all(t['step'] == 1 and t['policy'] == value['name'] for t in thoughts)
    text = guidance['text']
    assert text.index('先选择可靠') < text.index('weather') < text.index('成功时说明') < text.index('以下是查询结果')
    assert '示例不是当前对话' in text
    assert '尚未发生' in text
    assert '阅读 Skill 不代表' in text
    value['steps'][1]['bot'][0]['thought'] = 'changed'
    assert 'changed' not in catalog.guidance(['weather'], [])['text']


def test_reply_only_thought_only_and_repeated_skill_steps():
    values = [
        {'name': '礼貌', 'steps': [{'user': '谢谢'}, {'bot': [{'reply': '不客气'}]}]},
        {'name': '主动服务', 'steps': [{'bot': [{'thought': '仅在适合的时机主动帮助'}]}]},
        {'name': '组合', 'steps': [{'bot': [{'skills': ['weather']}, {'thought': '再查一次'}, {'skills': ['weather']}]}]},
    ]
    guidance = PolicyCatalog(values).guidance(['weather'], [])
    assert guidance['policies'] == values
    assert guidance['thoughts'][0]['target'] == 'continuation'
    assert guidance['thoughts'][1]['target'] == 'skills'


@pytest.mark.parametrize('value', [
    {'id': 'old', 'stage': 'selection', 'skills': ['weather'], 'when': 'weather', 'guidance': 'use'},
    {'name': '', 'steps': []}, {'name': 'bad', 'steps': []},
    {'name': 'bad', 'steps': [{'user': 'only user'}]},
    {'name': 'bad', 'steps': [{'user': 'hi', 'bot': [{'reply': 'hi'}]}]},
    {'name': 'bad', 'steps': [{'bot': {'thought': 'x', 'skills': ['weather']}}]},
    {'name': 'bad', 'steps': [{'bot': []}]},
    {'name': 'bad', 'steps': [{'skill': 'weather'}]},
    {'name': 'bad', 'steps': [{'bot': [{'thought': 'x', 'reply': 'y'}]}]},
    {'name': 'bad', 'steps': [{'bot': [{'thought': ' '}]}]},
    {'name': 'bad', 'steps': [{'bot': [{'skills': 'weather'}]}]},
    {'name': 'bad', 'steps': [{'bot': [{'skills': []}]}]},
    {'name': 'bad', 'steps': [{'bot': [{'skills': ['weather', 'weather']}]}]},
    {'name': 'bad', 'steps': [{'bot': [{'reply': 42}]}]},
    {'name': 'bad', 'steps': [{'bot': [{'reply': 'ok'}]}], 'when': 'old'},
])
def test_strict_schema(value):
    with pytest.raises(ValueError):
        PolicyCatalog([value])


def test_load_roundtrip_and_reject_old_contract_and_duplicate_yaml(tmp_path):
    path = tmp_path / 'policy.yml'
    path.write_text(yaml.safe_dump({'policies': [policy()]}, allow_unicode=True))
    assert PolicyCatalog.load(path).policies == [policy()]
    for content in ('schema_version: 1\ncases: []\n', 'policies: []\npolicies: []\n',
                    'policies:\n- name: x\n  steps:\n  - bot:\n    - thought: first\n      thought: overwritten\n'):
        path.write_text(content)
        with pytest.raises(ValueError):
            PolicyCatalog.load(path)


def test_catalog_names_and_skills_are_checked(tmp_path):
    with pytest.raises(ValueError, match='Duplicate'):
        PolicyCatalog([policy(), policy()])
    for name in ('a.yml', 'b.yaml'):
        (tmp_path / name).write_text(yaml.safe_dump({'policies': [policy()]}))
    with pytest.raises(ValueError, match='Duplicate'):
        PolicyCatalog.load(tmp_path)
    with pytest.raises(ValueError, match='Unknown'):
        PolicyCatalog([policy()]).validate_skills(['orders'])
    assert PolicyCatalog([policy()]).guidance([], [])['policies'] == []


def test_budgets_preserve_whole_examples_and_prioritize_retained_read():
    a, b = policy('first', ['a']), policy('second', ['b'])
    catalog = PolicyCatalog([a, b], max_policies=1)
    assert catalog.guidance(['a', 'b'], [])['policies'] == [a]
    result = catalog.guidance(['a', 'b'], ['b'])
    assert result['policies'] == [b]
    assert result['omitted_policies'] == [{'name': 'first', 'reason': 'max_policies'}]
    assert catalog.guidance(['a', 'b'], [])['policies'] == [a]
    for options in ({'max_policies': 0}, {'max_policies': True}, {'max_chars': -1}, {'max_chars': 1.5}):
        with pytest.raises(ValueError):
            PolicyCatalog([], **options)
    with pytest.raises(ValueError, match='max_chars'):
        PolicyCatalog([a], max_chars=10)


def test_multiple_consecutive_and_trailing_thoughts_have_stable_attribution():
    p = {'name': 'x', 'steps': [{'bot': [{'thought': 'a'}, {'thought': 'b'},
         {'skills': ['weather']}, {'thought': 'c'}]}]}
    result = PolicyCatalog([p]).guidance(['weather'], [])
    assert [t['target'] for t in result['thoughts']] == ['skills', 'skills', 'continuation']
    assert [t['target_item'] for t in result['thoughts']] == [2, 2, None]


def test_character_budget_reports_omission_without_truncating_and_considers_later_policy():
    first = {'name': 'one', 'steps': [{'bot': [{'thought': 'a' * 200}]}]}
    large = {'name': 'two', 'steps': [{'bot': [{'thought': 'b' * 300}]}]}
    small = {'name': 'three', 'steps': [{'bot': [{'reply': 'ok'}]}]}
    limit = len(PolicyCatalog([first, small]).guidance([], [])['text'])
    # Ensure the individual large policy fits, but not together with first.
    assert len(PolicyCatalog([large]).guidance([], [])['text']) > limit
    large['steps'][0]['bot'][0]['thought'] = 'b' * 180
    result = PolicyCatalog([first, large, small], max_chars=limit).guidance([], [])
    assert result['policies'] == [first, small]
    assert result['omitted_policies'] == [{'name': 'two', 'reason': 'max_chars'}]
    assert len(result['text']) <= limit


def test_selected_policy_rendering_ignores_rank_only_reordering():
    first = policy(); first['name'] = 'a'
    second = deepcopy(first); second['name'] = 'b'
    catalog = PolicyCatalog([first, second])
    matches = [{'name': name, 'status': 'candidate', 'step': None} for name in ['a', 'b']]
    a = catalog.guidance(['weather'], [], matches=matches)
    b = catalog.guidance(['weather'], [], matches=list(reversed(matches)))
    assert a['text'] == b['text']
    assert a['policies'] == list(reversed(b['policies']))
