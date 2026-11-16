"""Content-addressed disk cache for embedding vectors."""
import hashlib
import json
import logging
import os
from typing import List, Optional

logger = logging.getLogger(__name__)


class EmbeddingCache:
    """Cache embeddings on disk keyed by SHA256(cache_key + texts)."""

    def __init__(self, cache_dir):
        self._dir = cache_dir

    def _key(self, identity, texts):
        h = hashlib.sha256()
        h.update(identity.encode('utf-8'))
        for t in texts:
            h.update(b'\x00')
            h.update(t.encode('utf-8'))
        return h.hexdigest()

    def _path(self, key):
        return os.path.join(self._dir, f'{key}.json')

    def get(self, identity, texts) -> Optional[List[List[float]]]:
        key = self._key(identity, texts)
        path = self._path(key)
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if not isinstance(data, list) or len(data) != len(texts):
                return None
            if data and len(data) > 1:
                dim = len(data[0])
                if any(len(v) != dim for v in data[1:]):
                    return None
            return data
        except Exception:
            return None

    def put(self, identity, texts, embeddings):
        key = self._key(identity, texts)
        path = self._path(key)
        try:
            os.makedirs(self._dir, exist_ok=True)
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(embeddings, f)
        except Exception as e:
            logger.warning(f'Failed to cache embeddings: {e}')
