"""Parse KNOWLEDGE.md manifest and discover knowledge files."""
import os
import logging
from typing import Optional

from cota.retrieval.chunker import parse_frontmatter

logger = logging.getLogger(__name__)

_REQUIRED_FIELDS = ('name', 'description')
_OPTIONAL_FIELDS = {'rerank': 'false', 'llm': None, 'top_k': 5, 'max_steps': 3}
_KNOWLEDGE_EXTENSIONS = {'.md', '.txt'}


class KnowledgeManifest:
    """Parsed KNOWLEDGE.md: metadata, description, and file entries."""

    def __init__(self, name, description, rerank, llm, top_k, max_steps, toc_text, directory):
        self.name = name
        self.description = description
        self.rerank = rerank
        self.llm = llm
        self.top_k = top_k
        self.max_steps = max_steps
        self.toc_text = toc_text
        self.directory = directory

    @classmethod
    def load(cls, knowledge_dir) -> Optional["KnowledgeManifest"]:
        manifest_path = os.path.join(knowledge_dir, 'KNOWLEDGE.md')
        if not os.path.isfile(manifest_path):
            return None

        with open(manifest_path, 'r', encoding='utf-8') as f:
            text = f.read()

        meta, body = parse_frontmatter(text)

        for field in _REQUIRED_FIELDS:
            if not isinstance(meta.get(field), str) or not meta[field].strip():
                raise ValueError(f'KNOWLEDGE.md requires {field} in frontmatter')

        rerank = str(meta.get('rerank', 'false')).lower()
        if rerank not in ('false', 'true', 'navigate'):
            raise ValueError(f'KNOWLEDGE.md rerank must be false, true, or navigate; got {rerank}')

        top_k = meta.get('top_k', _OPTIONAL_FIELDS['top_k'])
        if not isinstance(top_k, int) or top_k < 1:
            raise ValueError('KNOWLEDGE.md top_k must be a positive integer')

        max_steps = meta.get('max_steps', _OPTIONAL_FIELDS['max_steps'])
        if not isinstance(max_steps, int) or max_steps < 1:
            raise ValueError('KNOWLEDGE.md max_steps must be a positive integer')

        llm = meta.get('llm')
        if llm is not None and (not isinstance(llm, str) or not llm.strip()):
            raise ValueError('KNOWLEDGE.md llm must be a non-empty string')

        return cls(
            name=meta['name'].strip(),
            description=meta['description'].strip(),
            rerank=rerank,
            llm=llm,
            top_k=top_k,
            max_steps=max_steps,
            toc_text=body.strip(),
            directory=knowledge_dir,
        )


def discover_files(knowledge_dir):
    """Walk the knowledge directory and yield (relative_path, absolute_path) for indexable files.

    KNOWLEDGE.md itself is excluded.
    """
    for root, _dirs, files in os.walk(knowledge_dir):
        for name in sorted(files):
            if name == 'KNOWLEDGE.md':
                continue
            _, ext = os.path.splitext(name)
            if ext.lower() not in _KNOWLEDGE_EXTENSIONS:
                continue
            abs_path = os.path.join(root, name)
            rel_path = os.path.relpath(abs_path, knowledge_dir)
            yield rel_path, abs_path
