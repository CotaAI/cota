"""Build and query a BM25 index over structured policy cases."""
import logging
import os
from typing import Optional

from cota.retrieval.bm25 import BM25Index
from cota.retrieval.chunker import parse_frontmatter
from .catalog import PolicyCatalog, _render, _GUIDANCE, policy_skills

logger = logging.getLogger(__name__)

_MAX_RESULT_CHARS = 8000
_REQUIRED_FIELDS = ('name', 'description')


class PolicyManifest:
    def __init__(self, name, description, top_k, directory):
        self.name = name
        self.description = description
        self.top_k = top_k
        self.directory = directory

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
        return cls(
            name=meta['name'].strip(),
            description=meta['description'].strip(),
            top_k=top_k,
            directory=policy_dir,
        )


class PolicyIndex:
    """In-memory BM25 index over policy cases."""

    def __init__(self, manifest, catalog, bm25):
        self.manifest = manifest
        self._catalog = catalog
        self._by_name = {p['name']: p for p in catalog.policies}
        self._bm25 = bm25

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
        k = top_k or self.manifest.top_k
        results = self._bm25.search(query, top_k=k)
        if not results:
            return ''
        parts = [_GUIDANCE]
        total = len(_GUIDANCE)
        for r in results:
            policy = self._by_name.get(r['id'])
            if not policy:
                continue
            rendered = _render(policy)
            if total + len(rendered) > _MAX_RESULT_CHARS and len(parts) > 1:
                break
            parts.append(rendered)
            total += len(rendered)
        return '\n\n'.join(parts)
