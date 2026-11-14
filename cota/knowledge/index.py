"""Build and query a BM25 index over knowledge file chunks."""
import logging
from typing import Optional

from cota.retrieval.bm25 import BM25Index
from cota.retrieval.chunker import chunk_markdown, parse_frontmatter
from .loader import KnowledgeManifest, discover_files

logger = logging.getLogger(__name__)

_BM25_CANDIDATE_MULTIPLIER = 4


class KnowledgeIndex:
    """In-memory BM25 index over chunked knowledge files."""

    def __init__(self, manifest, chunks, bm25):
        self.manifest = manifest
        self._chunks = {chunk['id']: chunk for chunk in chunks}
        self._bm25 = bm25

    @classmethod
    def build(cls, knowledge_dir) -> Optional["KnowledgeIndex"]:
        manifest = KnowledgeManifest.load(knowledge_dir)
        if manifest is None:
            return None

        chunks = []
        for rel_path, abs_path in discover_files(knowledge_dir):
            try:
                with open(abs_path, 'r', encoding='utf-8') as f:
                    text = f.read()
            except Exception as e:
                logger.warning(f'Cannot read knowledge file {rel_path}: {e}')
                continue
            file_chunks = chunk_markdown(text, source=rel_path)
            chunks.extend(file_chunks)

        if not chunks:
            logger.info(f'Knowledge directory {knowledge_dir} has no indexable content')
            return None

        documents = []
        for chunk in chunks:
            meta, _ = parse_frontmatter('')
            tags = ''
            if chunk['source']:
                try:
                    with open(f'{knowledge_dir}/{chunk["source"]}', 'r', encoding='utf-8') as f:
                        file_meta, _ = parse_frontmatter(f.read())
                        tags = ' '.join(file_meta.get('tags', []) or [])
                except Exception:
                    pass
            title_text = ' '.join(chunk['heading_chain'])
            documents.append({
                'id': chunk['id'],
                'text': chunk['text'],
                'fields': {
                    'title': (title_text, 3),
                    'tags': (tags, 2),
                    'body': (chunk['text'], 1),
                },
            })

        bm25 = BM25Index(documents)
        logger.info(f'Knowledge index built: {len(chunks)} chunks from {knowledge_dir}')
        return cls(manifest, chunks, bm25)

    def search(self, query, top_k=None):
        """BM25 search, return formatted chunks."""
        k = top_k or self.manifest.top_k
        results = self._bm25.search(query, top_k=k)
        return self._format_results(results)

    async def search_with_rerank(self, query, llm_instance, top_k=None):
        """BM25 candidate retrieval + LLM reranking."""
        k = top_k or self.manifest.top_k
        candidates = self._bm25.search(query, top_k=k * _BM25_CANDIDATE_MULTIPLIER)
        if not candidates:
            return ''
        prompt = self._build_rerank_prompt(query, candidates)
        try:
            response = await llm_instance.generate_chat(
                messages=[{'role': 'user', 'content': prompt}],
                max_tokens=500, temperature=0.0,
            )
            return self._parse_rerank_response(response['content'], candidates, k)
        except Exception as e:
            logger.warning(f'LLM rerank failed, falling back to BM25: {e}')
            return self._format_results(candidates[:k])

    async def search_with_navigate(self, query, llm_instance, top_k=None):
        """LLM reads TOC → targeted BM25 → LLM rerank."""
        k = top_k or self.manifest.top_k
        max_steps = self.manifest.max_steps

        if not self.manifest.toc_text or max_steps < 2:
            return await self.search_with_rerank(query, llm_instance, top_k)

        # Step 1: LLM reads TOC and identifies relevant sections
        nav_prompt = (
            f'用户问题：{query}\n\n'
            f'以下是知识库的目录：\n{self.manifest.toc_text}\n\n'
            f'列出与问题最相关的文件路径（每行一个路径，只输出路径，不要其它内容）。'
            f'最多列出 {min(max_steps, 5)} 个。'
        )
        try:
            response = await llm_instance.generate_chat(
                messages=[{'role': 'user', 'content': nav_prompt}],
                max_tokens=200, temperature=0.0,
            )
            target_sources = self._parse_nav_response(response['content'])
        except Exception as e:
            logger.warning(f'LLM navigation failed, falling back to rerank: {e}')
            return await self.search_with_rerank(query, llm_instance, top_k)

        # Step 2: BM25 search scoped to target sources
        if target_sources:
            scoped_chunks = [c for c in self._chunks.values() if c['source'] in target_sources]
            if scoped_chunks:
                scoped_docs = [{'id': c['id'], 'text': c['text'],
                                'fields': {'title': (' '.join(c['heading_chain']), 3), 'body': (c['text'], 1)}}
                               for c in scoped_chunks]
                scoped_bm25 = BM25Index(scoped_docs)
                candidates = scoped_bm25.search(query, top_k=k * _BM25_CANDIDATE_MULTIPLIER)
                if candidates:
                    # Step 3: LLM rerank on scoped results
                    prompt = self._build_rerank_prompt(query, candidates)
                    try:
                        response = await llm_instance.generate_chat(
                            messages=[{'role': 'user', 'content': prompt}],
                            max_tokens=500, temperature=0.0,
                        )
                        return self._parse_rerank_response(response['content'], candidates, k)
                    except Exception as e:
                        logger.warning(f'LLM rerank (navigate) failed: {e}')
                        return self._format_results(candidates[:k])

        return await self.search_with_rerank(query, llm_instance, top_k)

    def _format_results(self, results):
        """Format BM25 results as readable text for the model."""
        if not results:
            return ''
        parts = []
        for r in results:
            chunk = self._chunks.get(r['id'])
            if not chunk:
                continue
            header = ' > '.join(chunk['heading_chain']) if chunk['heading_chain'] else chunk['source']
            parts.append(f'[{header}]\n{chunk["text"]}')
        return '\n\n---\n\n'.join(parts)

    @staticmethod
    def _build_rerank_prompt(query, candidates):
        numbered = '\n\n'.join(f'[{i}] {c["text"][:500]}' for i, c in enumerate(candidates))
        return (
            f'用户问题：{query}\n\n'
            f'以下是候选知识片段，请判断每段与问题的相关性。\n'
            f'只输出相关片段的编号（用逗号分隔，最相关的在前），不要输出其它内容。\n'
            f'如果没有相关片段，输出"无"。\n\n{numbered}'
        )

    @staticmethod
    def _parse_rerank_response(response, candidates, top_k):
        """Parse LLM rerank response: extract indices, return formatted results."""
        import re
        indices = [int(x) for x in re.findall(r'\d+', response) if int(x) < len(candidates)]
        if not indices:
            return ''
        seen = set()
        unique = []
        for idx in indices:
            if idx not in seen:
                seen.add(idx)
                unique.append(idx)
        selected = [candidates[i] for i in unique[:top_k]]
        parts = []
        for r in selected:
            parts.append(r['text'])
        return '\n\n---\n\n'.join(parts)

    def _parse_nav_response(self, response):
        """Parse LLM navigation response: extract file paths."""
        sources = set(c['source'] for c in self._chunks.values())
        found = []
        for line in response.strip().splitlines():
            path = line.strip().strip('-').strip('*').strip()
            if path in sources:
                found.append(path)
            else:
                bare = path.lstrip('./')
                if bare in sources:
                    found.append(bare)
        return found
