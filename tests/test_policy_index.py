"""PolicyManifest, PolicyIndex (BM25 + embedding), and PolicyTool integration."""
import os

import pytest

from cota.policy.index import PolicyManifest, PolicyIndex
from cota.policy.tool import PolicyTool


def _write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)


_POLICY_DOC = """\
---
name: test-policy
description: 测试策略
---

## 退款流程

- User: 我要退款
- Bot:
  - Thought: 先核实订单状态
  - Skills: order-query
  - Result: 订单在7天内，可以退款
  - Thought: 按退款流程处理
  - Skills: refund
  - Reply: 已为您发起退款

## 查询物流

- User: 我的快递到哪了
- Bot:
  - Thought: 查询物流信息
  - Skills: logistics
  - Reply: 您的包裹目前在运输中
"""


@pytest.fixture
def policy_dir(tmp_path):
    d = tmp_path / 'policy'
    d.mkdir()
    _write(str(d / 'POLICY.md'), _POLICY_DOC)
    return str(d)


class TestPolicyManifest:
    def test_missing_policy_md_returns_none(self, tmp_path):
        assert PolicyManifest.load(str(tmp_path)) is None

    def test_valid_manifest(self, policy_dir):
        m = PolicyManifest.load(policy_dir)
        assert m.name == 'test-policy'
        assert m.description == '测试策略'
        assert m.embedding is None
        assert m.top_k == 5

    def test_embedding_field(self, tmp_path):
        d = tmp_path / 'p'
        d.mkdir()
        _write(str(d / 'POLICY.md'), '---\nname: t\ndescription: d\nembedding: default\n---\n')
        m = PolicyManifest.load(str(d))
        assert m.embedding == 'default'

    def test_empty_embedding_raises(self, tmp_path):
        d = tmp_path / 'p'
        d.mkdir()
        _write(str(d / 'POLICY.md'), '---\nname: t\ndescription: d\nembedding: ""\n---\n')
        with pytest.raises(ValueError, match='embedding'):
            PolicyManifest.load(str(d))

    def test_missing_required_field_raises(self, tmp_path):
        d = tmp_path / 'p'
        d.mkdir()
        _write(str(d / 'POLICY.md'), '---\nname: test\n---\nno description')
        with pytest.raises(ValueError, match='description'):
            PolicyManifest.load(str(d))


class TestPolicyIndex:
    def test_build_returns_none_without_manifest(self, tmp_path):
        assert PolicyIndex.build(str(tmp_path)) is None

    def test_build_and_search(self, policy_dir):
        index = PolicyIndex.build(policy_dir)
        assert index is not None
        result, count = index.search('退款')
        assert '退款' in result
        assert count >= 1

    def test_search_no_match(self, policy_dir):
        index = PolicyIndex.build(policy_dir)
        result, count = index.search('xyznotexist')
        assert result == ''
        assert count == 0


class TestPolicyTool:
    def test_tool_properties(self, policy_dir):
        index = PolicyIndex.build(policy_dir)
        tool = PolicyTool(index)
        assert tool.name == 'policy_guidance'
        assert '测试策略' in tool.description
        assert 'scenario' in tool.parameters['properties']

    @pytest.mark.asyncio
    async def test_execute_bm25(self, policy_dir):
        index = PolicyIndex.build(policy_dir)
        tool = PolicyTool(index)
        result = await tool.execute(scenario='退款')
        assert not result.get('isError')
        assert '退款' in result['content'][0]['text']
        assert result['details']['hits'] >= 1

    @pytest.mark.asyncio
    async def test_execute_empty_scenario(self, policy_dir):
        index = PolicyIndex.build(policy_dir)
        tool = PolicyTool(index)
        result = await tool.execute(scenario='')
        assert result['isError']

    @pytest.mark.asyncio
    async def test_no_match_returns_not_found(self, policy_dir):
        index = PolicyIndex.build(policy_dir)
        tool = PolicyTool(index)
        result = await tool.execute(scenario='xyznotexist')
        assert '未找到' in result['content'][0]['text']
