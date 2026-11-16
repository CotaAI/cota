"""Build and query a BM25 index over knowledge file chunks."""
import logging
import os
from typing import Optional

from cota.retrieval.bm25 import BM25Index
from cota.retrieval.vector import VectorIndex, HybridIndex
from cota.retrieval.cache import EmbeddingCache
from cota.retrieval.chunker import chunk_markdown, parse_frontmatter
from .loader import KnowledgeManifest, discover_files

logger = logging.getLogger(__name__)

_MAX_CHUNK_CHARS = 800
_MAX_RESULT_CHARS = 4000


def _extract_window(text, matched_terms, max_chars):
    """Extract a window covering the densest cluster of matched terms."""
    if len(text) <= max_chars:
        return text
    text_lower = text.lower()
    positions = []
    for term in matched_terms:
        term_lower = term.lower()
        start = 0
        while True:
            pos = text_lower.find(term_lower, start)
            if pos == -1:
                break
            positions.append(pos)
            start = pos + 1
    if not positions:
        return text[:max_chars] + '...'
    positions.sort()
    best_start = max(0, positions[0] - max_chars // 4)
    best_count = 0
    for pos in positions:
        win_start = max(0, pos - max_chars // 4)
        win_end = win_start + max_chars
        count = sum(1 for p in positions if win_start <= p < win_end)
        if count > best_count:
            best_count = count
            best_start = win_start
    end = min(len(text), best_start + max_chars)
    if end == len(text):
        best_start = max(0, end - max_chars)
    prefix = '...' if best_start > 0 else ''
    suffix = '...' if end < len(text) else ''
    return prefix + text[best_start:end] + suffix


class KnowledgeIndex:
    """In-memory BM25 index over chunked knowledge files."""

    def __init__(self, manifest, chunks, bm25):
        self.manifest = manifest
        self._chunks = {chunk['id']: chunk for chunk in chunks}
        self._bm25 = bm25
        self._vector = None
        self._doc_texts = [chunk['text'] for chunk in chunks]
        self._doc_ids = [chunk['id'] for chunk in chunks]

    @classmethod
    def build(cls, knowledge_dir) -> Optional["KnowledgeIndex"]:
        manifest = KnowledgeManifest.load(knowledge_dir)
        if manifest is None:
            return None

        chunks = []
        file_tags = {}
        for rel_path, abs_path in discover_files(knowledge_dir):
            try:
                with open(abs_path, 'r', encoding='utf-8') as f:
                    text = f.read()
            except Exception as e:
                logger.warning(f'Cannot read knowledge file {rel_path}: {e}')
                continue
            meta, _ = parse_frontmatter(text)
            tags = meta.get('tags', [])
            file_tags[rel_path] = ' '.join(tags) if tags else ''
            file_chunks = chunk_markdown(text, source=rel_path)
            chunks.extend(file_chunks)

        if not chunks:
            logger.info(f'Knowledge directory {knowledge_dir} has no indexable content')
            return None

        documents = []
        for chunk in chunks:
            title_text = ' '.join(chunk['heading_chain'])
            documents.append({
                'id': chunk['id'],
                'fields': {
                    'title': (title_text, 3),
                    'tags': (file_tags.get(chunk['source'], ''), 2),
                    'body': (chunk['text'], 1),
                },
            })

        bm25 = BM25Index(documents)
        logger.info(f'Knowledge index built: {len(chunks)} chunks from {knowledge_dir}')
        return cls(manifest, chunks, bm25)

    def search(self, query, top_k=None):
        """BM25 search, return (formatted_text, hit_count)."""
        k = top_k or self.manifest.top_k
        results = self._bm25.search(query, top_k=k)
        return self._format_results(results)

    async def attach_embeddings(self, embedding_client, bot_path):
        """Compute or load cached embeddings and build the vector index."""
        if not self._doc_texts:
            return
        try:
            cache = EmbeddingCache(os.path.join(bot_path, '.cota', 'embeddings'))
            cached = cache.get(embedding_client.cache_key, self._doc_texts)
            if cached and len(cached) == len(self._doc_texts):
                vectors = cached
            else:
                vectors = await embedding_client.embed(self._doc_texts)
                cache.put(embedding_client.cache_key, self._doc_texts, vectors)
            items = [{'id': doc_id, 'embedding': vec}
                     for doc_id, vec in zip(self._doc_ids, vectors)]
            self._vector = VectorIndex(items)
            logger.info('Knowledge vector index built: %d embeddings', len(items))
        except Exception as e:
            logger.warning('Knowledge embedding init failed, BM25 fallback: %s', e)
            self._vector = None

    async def search_with_embedding(self, query, embedding_client, top_k=None):
        """Hybrid BM25+vector search. Returns (text, hit_count)."""
        k = top_k or self.manifest.top_k
        query_vec = (await embedding_client.embed([query]))[0]
        hybrid = HybridIndex(self._bm25, self._vector)
        results = hybrid.search(query, query_vec, top_k=k)
        return self._format_results(results)

    def _format_results(self, results):
        """Format BM25 results as readable text for the model.

        Returns (text, hit_count) tuple.
        """
        if not results:
            return '', 0
        parts = []
        total = 0
        for r in results:
            chunk = self._chunks.get(r['id'])
            if not chunk:
                continue
            header = ' > '.join(chunk['heading_chain']) if chunk['heading_chain'] else chunk['source']
            text = chunk['text']
            if len(text) > _MAX_CHUNK_CHARS:
                text = _extract_window(text, r.get('matched_terms', []), _MAX_CHUNK_CHARS)
            part = f'[{header}]\n{text}'
            if total + len(part) > _MAX_RESULT_CHARS and parts:
                break
            parts.append(part)
            total += len(part)
        return '\n\n---\n\n'.join(parts), len(parts)
