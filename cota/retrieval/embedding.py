"""Thin async wrapper around OpenAI-compatible embedding endpoints."""
import logging
from typing import List

logger = logging.getLogger(__name__)

_BATCH_SIZE = 256
_TIMEOUT = 30
_MAX_RETRIES = 1


class EmbeddingClient:
    """Batch-embed texts via an OpenAI-compatible embeddings API."""

    def __init__(self, config):
        from openai import AsyncOpenAI
        self._model = config['model']
        self._dimensions = config.get('dimensions')
        self._apibase = config['apibase']
        self._client = AsyncOpenAI(
            api_key=config['key'],
            base_url=config['apibase'],
            timeout=_TIMEOUT,
            max_retries=_MAX_RETRIES,
        )

    @property
    def model(self):
        return self._model

    @property
    def cache_key(self):
        """Identity string for cache keying; includes all config that affects output."""
        parts = [self._apibase or '', self._model or '']
        if self._dimensions is not None:
            parts.append(str(self._dimensions))
        return '\x01'.join(parts)

    async def embed(self, texts: List[str]) -> List[List[float]]:
        all_embeddings: List[List[float]] = [[] for _ in texts]
        for start in range(0, len(texts), _BATCH_SIZE):
            batch = texts[start:start + _BATCH_SIZE]
            kwargs = {'model': self._model, 'input': batch}
            if self._dimensions is not None:
                kwargs['dimensions'] = self._dimensions
            response = await self._client.embeddings.create(**kwargs)
            if len(response.data) != len(batch):
                raise ValueError(
                    f'Embedding API returned {len(response.data)} vectors for {len(batch)} inputs')
            for item in response.data:
                all_embeddings[start + item.index] = item.embedding
        return all_embeddings

    async def close(self):
        await self._client.close()
