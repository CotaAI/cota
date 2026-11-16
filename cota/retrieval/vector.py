"""Pure-Python vector and hybrid (BM25 + vector) search indexes."""
import math


class VectorIndex:
    """Cosine-similarity search over pre-computed embeddings."""

    def __init__(self, items):
        self._items = []
        self._dim = None
        for item in items:
            vec = item['embedding']
            if self._dim is None:
                self._dim = len(vec)
            elif len(vec) != self._dim:
                raise ValueError(
                    f'Embedding dimension mismatch: expected {self._dim}, got {len(vec)} for {item["id"]}')
            norm = math.sqrt(sum(x * x for x in vec))
            self._items.append({
                'id': item['id'],
                'embedding': vec,
                'norm': norm,
            })

    def search(self, query_embedding, top_k=5):
        q_norm = math.sqrt(sum(x * x for x in query_embedding))
        if q_norm == 0:
            return []
        if self._dim is not None and len(query_embedding) != self._dim:
            raise ValueError(
                f'Query embedding dimension {len(query_embedding)} != index dimension {self._dim}')
        scored = []
        for item in self._items:
            if item['norm'] == 0:
                continue
            dot = sum(a * b for a, b in zip(query_embedding, item['embedding']))
            score = dot / (q_norm * item['norm'])
            scored.append({'id': item['id'], 'score': score, 'text': '', 'matched_terms': []})
        scored.sort(key=lambda x: x['score'], reverse=True)
        return scored[:top_k]


_RRF_K = 60


class HybridIndex:
    """Reciprocal Rank Fusion of BM25 and vector search results."""

    def __init__(self, bm25, vector):
        self._bm25 = bm25
        self._vector = vector

    def search(self, query, query_embedding, top_k=5, candidate_multiplier=4):
        n = top_k * candidate_multiplier
        bm25_results = self._bm25.search(query, top_k=n)
        vector_results = self._vector.search(query_embedding, top_k=n)

        scores = {}
        bm25_data = {}
        for rank, r in enumerate(bm25_results):
            doc_id = r['id']
            scores[doc_id] = scores.get(doc_id, 0) + 1.0 / (_RRF_K + rank + 1)
            bm25_data[doc_id] = r
        for rank, r in enumerate(vector_results):
            doc_id = r['id']
            scores[doc_id] = scores.get(doc_id, 0) + 1.0 / (_RRF_K + rank + 1)

        fused = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
        results = []
        for doc_id, score in fused:
            base = bm25_data.get(doc_id, {'id': doc_id, 'text': '', 'matched_terms': []})
            results.append({
                'id': doc_id,
                'score': score,
                'text': base.get('text', ''),
                'matched_terms': base.get('matched_terms', []),
            })
        return results
