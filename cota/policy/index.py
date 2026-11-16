"""Build and query a BM25 index over structured policy cases."""
import logging
import os
from typing import Optional

from cota.retrieval.bm25 import BM25Index
from cota.retrieval.vector import VectorIndex, HybridIndex
from cota.retrieval.cache import EmbeddingCache
from cota.retrieval.chunker import parse_frontmatter
from .catalog import PolicyCatalog, _render, _GUIDANCE, policy_skills

logger = logging.getLogger(__name__)

_MAX_RESULT_CHARS = 8000
_REQUIRED_FIELDS = ('name', 'description')


class PolicyManifest:
    def __init__(self, name, description, top_k, directory, embedding=None):
        self.name = name
        self.description = description
        self.top_k = top_k
        self.directory = directory
        self.embedding = embedding

    @classmethod
    def load(cls, policy_dir) -> Optional["PolicyManifest"]:
        manifest_path = os.path.join(policy_dir, 'POLICY.md')
        if not os.path.isfile(manifest_path):
            return None
        with open(manifest_path, 'r', encoding='utf-8') as f:
            text = f.read()
        meta, _ = parse_frontmatter(text)
        for field in _REQUIRED_FIELDS:
            if not isinstance(meta.get(field), str) or not meta[field].strip():
                raise ValueError(f'POLICY.md requires {field} in frontmatter')
        top_k = meta.get('top_k', 5)
        if not isinstance(top_k, int) or top_k < 1:
            raise ValueError('POLICY.md top_k must be a positive integer')
        embedding = meta.get('embedding')
        if embedding is not None and (not isinstance(embedding, str) or not embedding.strip()):
            raise ValueError('POLICY.md embedding must be a non-empty string')
        return cls(
            name=meta['name'].strip(),
            description=meta['description'].strip(),
            top_k=top_k,
            directory=policy_dir,
            embedding=embedding,
        )


def _compact_repr(policy):
    """Compact text representation of a policy case for embedding."""
    parts = [policy['name']]
    for step in policy['steps']:
        if 'user' in step:
            parts.append(f'用户: {step["user"]}')
        for item in step.get('bot', []):
            if 'thought' in item:
                parts.append(f'指导: {item["thought"]}')
            elif 'result' in item:
                parts.append(f'结果: {item["result"]}')
    return ' | '.join(parts)


class PolicyIndex:
    """In-memory BM25 index over policy cases."""

    def __init__(self, manifest, catalog, bm25):
        self.manifest = manifest
        self._catalog = catalog
        self._by_name = {p['name']: p for p in catalog.policies}
        self._bm25 = bm25
        self._vector = None
        self._doc_texts = [_compact_repr(p) for p in catalog.policies]
        self._doc_ids = [p['name'] for p in catalog.policies]

    @classmethod
    def build(cls, policy_dir) -> Optional["PolicyIndex"]:
        manifest = PolicyManifest.load(policy_dir)
        if manifest is None:
            return None
        catalog = PolicyCatalog.load(policy_dir)
        if not catalog.policies:
            return None

        documents = []
        for policy in catalog.policies:
            users, outcomes, thoughts = [], [], []
            for step in policy['steps']:
                if 'user' in step:
                    users.append(step['user'])
                for item in step.get('bot', []):
                    if 'result' in item:
                        outcomes.append(item['result'])
                    if 'thought' in item:
                        thoughts.append(item['thought'])
            documents.append({
                'id': policy['name'],
                'fields': {
                    'intent': ('\n'.join([policy['name'], *users]), 3),
                    'skills': (' '.join(policy_skills(policy)), 2),
                    'outcome': ('\n'.join(outcomes), 2),
                    'guidance': ('\n'.join(thoughts), 1),
                },
            })

        bm25 = BM25Index(documents)
        logger.info('Policy index built: %d cases from %s', len(catalog.policies), policy_dir)
        return cls(manifest, catalog, bm25)

    def search(self, query, top_k=None):
        """Returns (formatted_text, hit_count)."""
        k = top_k or self.manifest.top_k
        results = self._bm25.search(query, top_k=k)
        return self._format_results(results, k)

    async def attach_embeddings(self, embedding_client, bot_path):
        """Compute or load cached embeddings and build the vector index."""
        if not self._doc_texts:
            return
        cache = EmbeddingCache(os.path.join(bot_path, '.cota', 'embeddings'))
        cached = cache.get(embedding_client.model, self._doc_texts)
        if cached and len(cached) == len(self._doc_texts):
            vectors = cached
        else:
            vectors = await embedding_client.embed(self._doc_texts)
            cache.put(embedding_client.model, self._doc_texts, vectors)
        items = [{'id': doc_id, 'embedding': vec}
                 for doc_id, vec in zip(self._doc_ids, vectors)]
        self._vector = VectorIndex(items)
        logger.info('Policy vector index built: %d embeddings', len(items))

    async def search_with_embedding(self, query, embedding_client, top_k=None):
        """Hybrid BM25+vector search. Returns (text, hit_count)."""
        k = top_k or self.manifest.top_k
        query_vec = (await embedding_client.embed([query]))[0]
        hybrid = HybridIndex(self._bm25, self._vector)
        results = hybrid.search(query, query_vec, top_k=k)
        return self._format_results(results, k)

    def _format_results(self, results, top_k=None):
        """Format BM25 results with budget control. Returns (text, hit_count)."""
        if not results:
            return '', 0
        k = top_k or self.manifest.top_k
        parts = [_GUIDANCE]
        total = len(_GUIDANCE)
        hit_count = 0
        for r in results:
            if hit_count >= k:
                break
            policy = self._by_name.get(r['id'])
            if not policy:
                continue
            rendered = _render(policy)
            if total + len(rendered) > _MAX_RESULT_CHARS and hit_count > 0:
                break
            parts.append(rendered)
            total += len(rendered)
            hit_count += 1
        return '\n\n'.join(parts), hit_count
