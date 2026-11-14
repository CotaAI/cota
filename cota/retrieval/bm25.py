"""Generic BM25 index, not tied to any business domain."""
import math
from collections import Counter
from .tokenizer import tokens


class BM25Index:
    """In-memory BM25 index over tokenized documents.

    Each document is a dict with at least 'id' and either 'text' or 'fields'.
    Fields mode allows weighted indexing: fields is {name: (text, weight)}.
    """

    def __init__(self, documents):
        self._docs = []
        for doc in documents:
            terms = self._tokenize(doc)
            self._docs.append({'id': doc['id'], 'terms': dict(terms), 'length': sum(terms.values()),
                               'text': doc.get('text', '')})
        self._df = Counter(term for doc in self._docs for term in doc['terms'])
        self._n = len(self._docs)
        self._avgdl = sum(doc['length'] for doc in self._docs) / max(self._n, 1) or 1

    @staticmethod
    def _tokenize(doc):
        if 'fields' in doc:
            terms = Counter()
            for name, (text, weight) in doc['fields'].items():
                terms.update({t: c * weight for t, c in Counter(tokens(text)).items()})
            return terms
        return Counter(tokens(doc.get('text', '')))

    def search(self, query, top_k=5):
        """Return top_k documents sorted by BM25 relevance."""
        query_terms = Counter(tokens(query))
        scored = []
        for doc in self._docs:
            score = 0.0
            for term, weight in query_terms.items():
                freq = doc['terms'].get(term, 0)
                if freq:
                    idf = math.log(1 + (self._n - self._df[term] + .5) / (self._df[term] + .5))
                    score += weight * idf * freq * 2.5 / (freq + 1.5 * (.25 + .75 * doc['length'] / self._avgdl))
            if score > 0:
                scored.append((score, doc))
        scored.sort(key=lambda item: -item[0])
        return [{'id': doc['id'], 'score': score, 'text': doc['text']}
                for score, doc in scored[:top_k]]
