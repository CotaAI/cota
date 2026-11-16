"""Content-addressed disk cache for embedding vectors."""
import hashlib
import json
import logging
import os
from typing import List, Optional

logger = logging.getLogger(__name__)


class EmbeddingCache:
    """Cache embeddings on disk keyed by SHA256(model + texts)."""

    def __init__(self, cache_dir):
        self._dir = cache_dir

    def _key(self, model, texts):
        h = hashlib.sha256()
        h.update(model.encode('utf-8'))
        for t in texts:
            h.update(b'\x00')
            h.update(t.encode('utf-8'))
        return h.hexdigest()

    def _path(self, key):
        return os.path.join(self._dir, f'{key}.json')

    def get(self, model, texts) -> Optional[List[List[float]]]:
        key = self._key(model, texts)
        path = self._path(key)
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return None

    def put(self, model, texts, embeddings):
        key = self._key(model, texts)
        path = self._path(key)
        try:
            os.makedirs(self._dir, exist_ok=True)
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(embeddings, f)
        except Exception as e:
            logger.warning(f'Failed to cache embeddings: {e}')
