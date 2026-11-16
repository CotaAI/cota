"""Embedding infrastructure: EmbeddingClient, VectorIndex, HybridIndex, EmbeddingCache."""
import os

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from cota.retrieval.embedding import EmbeddingClient
from cota.retrieval.vector import VectorIndex, HybridIndex
from cota.retrieval.cache import EmbeddingCache
from cota.retrieval.bm25 import BM25Index


class TestVectorIndex:
    def test_cosine_similarity_ranking(self):
        items = [
            {'id': 'a', 'embedding': [1.0, 0.0, 0.0]},
            {'id': 'b', 'embedding': [0.0, 1.0, 0.0]},
            {'id': 'c', 'embedding': [0.7, 0.7, 0.0]},
        ]
        index = VectorIndex(items)
        results = index.search([1.0, 0.0, 0.0], top_k=3)
        assert results[0]['id'] == 'a'
        assert abs(results[0]['score'] - 1.0) < 0.01

    def test_top_k_limits(self):
        items = [{'id': str(i), 'embedding': [float(i), 0.0]} for i in range(10)]
        index = VectorIndex(items)
        results = index.search([1.0, 0.0], top_k=3)
        assert len(results) == 3

    def test_zero_query_returns_empty(self):
        items = [{'id': 'a', 'embedding': [1.0, 0.0]}]
        index = VectorIndex(items)
        results = index.search([0.0, 0.0], top_k=5)
        assert results == []


class TestHybridIndex:
    def test_rrf_fusion(self):
        bm25_docs = [
            {'id': 'a', 'text': 'hello world'},
            {'id': 'b', 'text': 'hello there'},
            {'id': 'c', 'text': 'goodbye world'},
        ]
        bm25 = BM25Index(bm25_docs)

        vector_items = [
            {'id': 'a', 'embedding': [0.5, 0.5]},
            {'id': 'b', 'embedding': [0.3, 0.7]},
            {'id': 'c', 'embedding': [0.9, 0.1]},
        ]
        vector = VectorIndex(vector_items)

        hybrid = HybridIndex(bm25, vector)
        results = hybrid.search('hello', [0.8, 0.2], top_k=3)
        assert len(results) >= 1
        ids = [r['id'] for r in results]
        assert 'a' in ids or 'b' in ids

    def test_preserves_matched_terms(self):
        bm25 = BM25Index([{'id': 'a', 'text': 'hello world'}])
        vector = VectorIndex([{'id': 'a', 'embedding': [1.0]}])
        hybrid = HybridIndex(bm25, vector)
        results = hybrid.search('hello', [1.0], top_k=1)
        assert len(results) == 1
        assert 'hello' in results[0]['matched_terms']


class TestEmbeddingCache:
    def test_put_and_get(self, tmp_path):
        cache = EmbeddingCache(str(tmp_path / 'cache'))
        texts = ['hello', 'world']
        embeddings = [[1.0, 2.0], [3.0, 4.0]]
        cache.put('model-a', texts, embeddings)
        result = cache.get('model-a', texts)
        assert result == embeddings

    def test_miss_returns_none(self, tmp_path):
        cache = EmbeddingCache(str(tmp_path / 'cache'))
        assert cache.get('model-a', ['hello']) is None

    def test_different_model_misses(self, tmp_path):
        cache = EmbeddingCache(str(tmp_path / 'cache'))
        cache.put('model-a', ['hello'], [[1.0]])
        assert cache.get('model-b', ['hello']) is None

    def test_different_texts_misses(self, tmp_path):
        cache = EmbeddingCache(str(tmp_path / 'cache'))
        cache.put('model-a', ['hello'], [[1.0]])
        assert cache.get('model-a', ['world']) is None

    def test_graceful_on_corrupt_file(self, tmp_path):
        cache = EmbeddingCache(str(tmp_path / 'cache'))
        cache.put('model-a', ['hello'], [[1.0]])
        for f in os.listdir(str(tmp_path / 'cache')):
            path = os.path.join(str(tmp_path / 'cache'), f)
            with open(path, 'w') as fp:
                fp.write('not json')
        assert cache.get('model-a', ['hello']) is None


class TestEmbeddingClient:
    @pytest.mark.asyncio
    async def test_embed_calls_api(self):
        mock_response = SimpleNamespace(data=[
            SimpleNamespace(embedding=[1.0, 2.0]),
            SimpleNamespace(embedding=[3.0, 4.0]),
        ])
        client = EmbeddingClient.__new__(EmbeddingClient)
        client._model = 'test-model'
        client._dimensions = None
        client._client = SimpleNamespace(
            embeddings=SimpleNamespace(create=AsyncMock(return_value=mock_response)),
            close=AsyncMock(),
        )
        result = await client.embed(['hello', 'world'])
        assert result == [[1.0, 2.0], [3.0, 4.0]]
        client._client.embeddings.create.assert_called_once()

    def test_model_property(self):
        client = EmbeddingClient.__new__(EmbeddingClient)
        client._model = 'text-embedding-3-small'
        assert client.model == 'text-embedding-3-small'
