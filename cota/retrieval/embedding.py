"""Thin async wrapper around OpenAI-compatible embedding endpoints."""
import logging
from typing import List

logger = logging.getLogger(__name__)


class EmbeddingClient:
    """Batch-embed texts via an OpenAI-compatible embeddings API."""

    def __init__(self, config):
        from openai import AsyncOpenAI
        self._model = config['model']
        self._dimensions = config.get('dimensions')
        self._client = AsyncOpenAI(
            api_key=config['key'],
            base_url=config['apibase'],
        )

    @property
    def model(self):
        return self._model

    async def embed(self, texts: List[str]) -> List[List[float]]:
        kwargs = {'model': self._model, 'input': texts}
        if self._dimensions is not None:
            kwargs['dimensions'] = self._dimensions
        response = await self._client.embeddings.create(**kwargs)
        return [item.embedding for item in response.data]

    async def close(self):
        await self._client.close()
