"""Knowledge base: loader, index, tool integration."""
import os
import tempfile
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from cota.knowledge.loader import KnowledgeManifest, discover_files
from cota.knowledge.index import KnowledgeIndex
from cota.knowledge.tool import KnowledgeTool


def _write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)


@pytest.fixture
def kb_dir(tmp_path):
    """A knowledge directory with KNOWLEDGE.md and sample files."""
    d = tmp_path / 'knowledge'
    d.mkdir()
    _write(str(d / 'KNOWLEDGE.md'), (
        '---\nname: test-kb\ndescription: 测试知识库\n---\n\n'
        '# 目录\n\n- [退款政策](refund.md)\n- [产品](products.md)\n'
    ))
    _write(str(d / 'refund.md'), (
        '---\ntitle: 退款政策\ntags: [售后, 订单]\n---\n\n'
        '# 退款政策\n\n## 普通订单\n购买后7天内可无理由退款。\n\n'
        '## 会员订单\n会员订单需联系客服处理退款。\n'
    ))
    _write(str(d / 'products.md'), (
        '# 产品目录\n\n## 基础版\n价格100元，适合个人用户。\n\n'
        '## 企业版\n价格1000元，适合团队使用。\n'
    ))
    return str(d)


class TestLoader:
    def test_missing_knowledge_md_returns_none(self, tmp_path):
        assert KnowledgeManifest.load(str(tmp_path)) is None

    def test_valid_manifest(self, kb_dir):
        m = KnowledgeManifest.load(kb_dir)
        assert m.name == 'test-kb'
        assert m.description == '测试知识库'
        assert m.rerank == 'false'
        assert m.top_k == 5

    def test_missing_required_field_raises(self, tmp_path):
        d = tmp_path / 'kb'
        d.mkdir()
        _write(str(d / 'KNOWLEDGE.md'), '---\nname: test\n---\nno description')
        with pytest.raises(ValueError, match='description'):
            KnowledgeManifest.load(str(d))

    def test_invalid_rerank_raises(self, tmp_path):
        d = tmp_path / 'kb'
        d.mkdir()
        _write(str(d / 'KNOWLEDGE.md'), '---\nname: t\ndescription: d\nrerank: invalid\n---\n')
        with pytest.raises(ValueError, match='rerank'):
            KnowledgeManifest.load(str(d))

    def test_discover_files_excludes_knowledge_md(self, kb_dir):
        files = list(discover_files(kb_dir))
        paths = [rel for rel, _ in files]
        assert 'KNOWLEDGE.md' not in paths
        assert 'refund.md' in paths
        assert 'products.md' in paths

    def test_discover_skips_non_text_files(self, kb_dir):
        _write(os.path.join(kb_dir, 'image.png'), 'fake')
        files = list(discover_files(kb_dir))
        assert not any('image.png' in rel for rel, _ in files)


class TestIndex:
    def test_build_returns_none_without_manifest(self, tmp_path):
        assert KnowledgeIndex.build(str(tmp_path)) is None

    def test_build_returns_none_without_files(self, tmp_path):
        d = tmp_path / 'kb'
        d.mkdir()
        _write(str(d / 'KNOWLEDGE.md'), '---\nname: t\ndescription: d\n---\n')
        assert KnowledgeIndex.build(str(d)) is None

    def test_build_and_search(self, kb_dir):
        index = KnowledgeIndex.build(kb_dir)
        assert index is not None
        result = index.search('退款')
        assert '退款' in result

    def test_search_relevance_order(self, kb_dir):
        index = KnowledgeIndex.build(kb_dir)
        result = index.search('企业版价格')
        assert '企业版' in result

    def test_no_match_returns_empty(self, kb_dir):
        index = KnowledgeIndex.build(kb_dir)
        result = index.search('xyznotexist')
        assert result == ''


class TestTool:
    def test_tool_properties(self, kb_dir):
        index = KnowledgeIndex.build(kb_dir)
        agent = SimpleNamespace(llm_instance=lambda name: None)
        tool = KnowledgeTool(index, agent)
        assert tool.name == 'search_knowledge'
        assert '测试知识库' in tool.description
        assert 'query' in tool.parameters['properties']

    @pytest.mark.asyncio
    async def test_execute_returns_results(self, kb_dir):
        index = KnowledgeIndex.build(kb_dir)
        agent = SimpleNamespace(llm_instance=lambda name: None)
        tool = KnowledgeTool(index, agent)
        result = await tool.execute(query='退款')
        assert not result.get('isError')
        assert '退款' in result['content'][0]['text']

    @pytest.mark.asyncio
    async def test_empty_query_returns_error(self, kb_dir):
        index = KnowledgeIndex.build(kb_dir)
        agent = SimpleNamespace(llm_instance=lambda name: None)
        tool = KnowledgeTool(index, agent)
        result = await tool.execute(query='')
        assert result['isError']

    @pytest.mark.asyncio
    async def test_no_match_returns_not_found(self, kb_dir):
        index = KnowledgeIndex.build(kb_dir)
        agent = SimpleNamespace(llm_instance=lambda name: None)
        tool = KnowledgeTool(index, agent)
        result = await tool.execute(query='xyznotexist')
        assert '未找到' in result['content'][0]['text']


class TestRerank:
    @pytest.mark.asyncio
    async def test_rerank_falls_back_on_llm_failure(self, kb_dir):
        _write(os.path.join(kb_dir, 'KNOWLEDGE.md'),
               '---\nname: t\ndescription: d\nrerank: true\n---\n')
        index = KnowledgeIndex.build(kb_dir)
        llm = SimpleNamespace(generate_chat=AsyncMock(side_effect=RuntimeError('fail')))
        result = await index.search_with_rerank('退款', llm)
        assert '退款' in result

    @pytest.mark.asyncio
    async def test_rerank_uses_llm_response(self, kb_dir):
        _write(os.path.join(kb_dir, 'KNOWLEDGE.md'),
               '---\nname: t\ndescription: d\nrerank: true\n---\n')
        index = KnowledgeIndex.build(kb_dir)
        llm = SimpleNamespace(generate_chat=AsyncMock(return_value={'content': '0'}))
        result = await index.search_with_rerank('退款', llm)
        assert result  # should return the first candidate

    @pytest.mark.asyncio
    async def test_rerank_preserves_heading_chain(self, kb_dir):
        _write(os.path.join(kb_dir, 'KNOWLEDGE.md'),
               '---\nname: t\ndescription: d\nrerank: true\n---\n')
        index = KnowledgeIndex.build(kb_dir)
        llm = SimpleNamespace(generate_chat=AsyncMock(return_value={'content': '0'}))
        result = await index.search_with_rerank('退款', llm)
        assert '[' in result and ']' in result


class TestIndexQuality:
    def test_tags_extracted_from_frontmatter(self, kb_dir):
        index = KnowledgeIndex.build(kb_dir)
        result = index.search('售后')
        assert '退款' in result

    def test_result_size_bounded(self, tmp_path):
        d = tmp_path / 'knowledge'
        d.mkdir()
        _write(str(d / 'KNOWLEDGE.md'), '---\nname: t\ndescription: d\ntop_k: 10\n---\n')
        for i in range(10):
            _write(str(d / f'doc{i}.md'), f'# Doc {i}\n\n' + f'搜索关键词 内容块{i} ' * 200)
        index = KnowledgeIndex.build(str(d))
        result = index.search('搜索关键词')
        from cota.knowledge.index import _MAX_RESULT_CHARS
        assert len(result) <= _MAX_RESULT_CHARS + 500  # allow margin for last chunk
