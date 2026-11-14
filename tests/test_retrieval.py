"""Shared retrieval infrastructure: tokenizer, BM25 index, Markdown chunker."""
import pytest
from cota.retrieval import tokens, BM25Index, chunk_markdown
from cota.knowledge.index import _extract_window


class TestTokenizer:
    def test_latin_words(self):
        assert tokens('hello world') == ['hello', 'world']

    def test_chinese_chars_and_bigrams(self):
        result = tokens('退款')
        assert '退' in result and '款' in result and '退款' in result

    def test_mixed_text(self):
        result = tokens('hello退款policy')
        assert 'hello' in result and 'policy' in result and '退款' in result

    def test_case_insensitive(self):
        assert tokens('Hello') == tokens('hello')

    def test_empty(self):
        assert tokens('') == []


class TestBM25Index:
    def test_basic_search(self):
        docs = [
            {'id': 'a', 'text': '退款政策：7天内可退款'},
            {'id': 'b', 'text': '产品介绍：这是一款好产品'},
            {'id': 'c', 'text': '配送说明：全国包邮'},
        ]
        index = BM25Index(docs)
        results = index.search('退款', top_k=2)
        assert len(results) >= 1
        assert results[0]['id'] == 'a'

    def test_field_weighting(self):
        docs = [
            {'id': 'a', 'fields': {'title': ('退款政策', 3), 'body': ('7天内可退款', 1)}},
            {'id': 'b', 'fields': {'title': ('产品介绍', 3), 'body': ('退款不适用于特价品', 1)}},
        ]
        index = BM25Index(docs)
        results = index.search('退款政策')
        assert results[0]['id'] == 'a'

    def test_empty_query(self):
        index = BM25Index([{'id': 'a', 'text': 'hello'}])
        assert index.search('') == []

    def test_no_match(self):
        index = BM25Index([{'id': 'a', 'text': 'hello world'}])
        assert index.search('退款') == []

    def test_top_k_limits(self):
        docs = [{'id': str(i), 'text': f'document {i} about search'} for i in range(20)]
        index = BM25Index(docs)
        results = index.search('search', top_k=3)
        assert len(results) == 3


class TestChunker:
    def test_heading_split(self):
        text = '# Main\n\n## Section A\nContent A\n\n## Section B\nContent B'
        chunks = chunk_markdown(text, source='test.md')
        assert len(chunks) >= 2
        section_a = next(c for c in chunks if 'Section A' in c['title'])
        assert 'Content A' in section_a['text']

    def test_heading_chain(self):
        text = '# Main\n## Sub\nContent'
        chunks = chunk_markdown(text, source='test.md')
        sub_chunk = next(c for c in chunks if 'Sub' in str(c['heading_chain']))
        assert 'Main' in sub_chunk['heading_chain']
        assert 'Sub' in sub_chunk['heading_chain']

    def test_frontmatter_title(self):
        text = '---\ntitle: My Document\n---\n\n## Section\nContent'
        chunks = chunk_markdown(text, source='test.md')
        assert any('My Document' in c['title'] for c in chunks)

    def test_no_headings_returns_single_chunk(self):
        text = 'Just plain text without any headings.'
        chunks = chunk_markdown(text, source='test.md')
        assert len(chunks) == 1
        assert 'Just plain text' in chunks[0]['text']

    def test_fenced_code_headings_ignored(self):
        text = '## Real\nContent\n\n```\n## Not a heading\n```\n'
        chunks = chunk_markdown(text, source='test.md')
        headings = [c['title'] for c in chunks]
        assert not any('Not a heading' in h for h in headings)

    def test_duplicate_heading_ids_unique(self):
        text = '## A\nFirst\n\n## A\nSecond\n\n## A~1\nThird'
        chunks = chunk_markdown(text, source='test.md')
        ids = [c['id'] for c in chunks]
        assert len(ids) == len(set(ids)), f'Duplicate IDs: {ids}'
        first = next(c for c in chunks if c['text'] == 'First')
        second = next(c for c in chunks if c['text'] == 'Second')
        third = next(c for c in chunks if c['text'] == 'Third')
        assert first['id'] != second['id']
        assert second['id'] != third['id']
        assert first['id'] != third['id']

    def test_duplicate_heading_with_separator_in_title(self):
        text = '## A\nFirst\n\n## A~1\nSecond\n\n## A\nThird'
        chunks = chunk_markdown(text, source='s')
        ids = [c['id'] for c in chunks]
        assert len(ids) == len(set(ids)), f'Duplicate IDs: {ids}'

    def test_no_heading_long_text_split(self):
        para = 'A' * 600
        text = f'{para}\n\n{para}\n\n{para}'
        chunks = chunk_markdown(text, source='test.txt')
        assert len(chunks) > 1
        assert all(len(c['text']) <= 1200 for c in chunks)
        ids = [c['id'] for c in chunks]
        assert len(ids) == len(set(ids))

    def test_single_long_paragraph_hard_split(self):
        text = '## Big\n' + 'X' * 5000
        chunks = chunk_markdown(text, source='test.md')
        assert all(len(c['text']) <= 1200 for c in chunks)
        assert len(chunks) >= 5

    def test_empty_sections_skipped(self):
        text = '## A\n\n## B\nContent B'
        chunks = chunk_markdown(text, source='test.md')
        assert all(c['text'].strip() for c in chunks)


class TestExtractWindow:
    def test_short_text_unchanged(self):
        assert _extract_window('short text', ['short'], 100) == 'short text'

    def test_window_covers_densest_cluster(self):
        parts = ['退款办理提示' + 'X' * 400, '退款期限是30天，退款金额按原价计算']
        text = '。'.join(parts)
        result = _extract_window(text, ['退款', '期限'], 200)
        assert '退款期限' in result
        assert '30天' in result

    def test_no_match_returns_head(self):
        text = 'A' * 500
        result = _extract_window(text, ['zzz'], 100)
        assert len(result) <= 104  # 100 + '...'
        assert result.startswith('A')

    def test_matched_terms_returns_matched(self):
        results = BM25Index([{'id': 'a', 'text': 'hello world'}]).search('hello')
        assert 'matched_terms' in results[0]
        assert 'hello' in results[0]['matched_terms']


class TestToolContextHint:
    @staticmethod
    def _hint(name, args, result):
        from cota.runtime.pi_runtime import PiAgentRuntime
        return PiAgentRuntime._tool_context_hint(name, args, result)

    def test_knowledge_reads_hits_from_details(self):
        result = {'content': [{'type': 'text', 'text': 'anything'}], 'details': {'hits': 3}}
        hint = self._hint('search_knowledge', {'query': 'test'}, result)
        assert '3条结果' in hint['summary']

    def test_knowledge_zero_hits(self):
        result = {'content': [{'type': 'text', 'text': '未找到相关知识。'}], 'details': {'hits': 0}}
        hint = self._hint('search_knowledge', {'query': 'test'}, result)
        assert '无结果' in hint['summary']

    def test_policy_reads_hits_from_details(self):
        result = {'content': [{'type': 'text', 'text': 'policies'}], 'details': {'hits': 2}}
        hint = self._hint('policy_guidance', {'scenario': 'test'}, result)
        assert '2条结果' in hint['summary']

    def test_error_returns_none(self):
        result = {'content': [{'type': 'text', 'text': 'error'}], 'isError': True}
        assert self._hint('search_knowledge', {'query': 'x'}, result) is None

    def test_missing_hits_returns_none(self):
        result = {'content': [{'type': 'text', 'text': 'text'}], 'details': {}}
        assert self._hint('search_knowledge', {'query': 'x'}, result) is None
