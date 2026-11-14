"""Trainable retrieval policies. Retrieval scores are never applicability proofs."""
from collections import Counter
import math
import re
import unicodedata

from .base import Policy, Match, Selection
from .catalog import policy_skills
from cota.retrieval import tokens


def documents(policies):
    """Separate intent/outcome signals; long reply examples do not dominate retrieval."""
    result = []
    for policy in policies:
        users, outcomes, thoughts = [], [], []
        for step in policy['steps']:
            if 'user' in step:
                users.append(step['user'])
            for item in step.get('bot', []):
                if 'result' in item:
                    outcomes.append(item['result'])
                if 'thought' in item:
                    thoughts.append(item['thought'])
        fields = {'intent': '\n'.join([policy['name'], *users]),
                  'skills': ' '.join(policy_skills(policy)), 'outcome': '\n'.join(outcomes),
                  'guidance': '\n'.join(thoughts)}
        result.append({'name': policy['name'], 'fields': fields,
                       'text': '\n'.join(f'{k}: {v}' for k, v in fields.items())})
    return result


def _positive(options, key, default):
    value = options.get(key, default)
    if type(value) is not int or value < 1:
        raise ValueError(f'{key} must be a positive integer')
    return value


class AllPolicy(Policy):
    requires_training = False

    async def select(self, context, services):
        read = set(context.read_skills)
        ordered = sorted(self.eligible(context), key=lambda p: not bool(set(policy_skills(p)) & read))
        return Selection([Match(p['name']) for p in ordered])


class BM25Policy(Policy):
    option_names = frozenset({'top_k'})

    @classmethod
    def validate_options(cls, options):
        super().validate_options(options)
        _positive(options, 'top_k', 12)

    async def train(self, services):
        docs = []
        for doc in documents(self.policies):
            weighted = []
            for key, weight in [('intent', 3), ('skills', 2), ('outcome', 2), ('guidance', 1)]:
                weighted.extend(tokens(doc['fields'][key]) * weight)
            docs.append({'name': doc['name'], 'terms': dict(Counter(weighted)), 'length': len(weighted)})
        return {'documents': docs}

    def load_state(self, state):
        super().load_state(state)
        docs = state.get('documents')
        if not isinstance(docs, list) or [d.get('name') for d in docs] != [p['name'] for p in self.policies]:
            raise ValueError('Invalid BM25 training documents')
        for doc in docs:
            if (not isinstance(doc.get('terms'), dict) or any(not isinstance(k, str) or type(v) is not int or v < 1
                    for k, v in doc['terms'].items()) or doc.get('length') != sum(doc['terms'].values())):
                raise ValueError('Invalid BM25 term counts')
        self._df = Counter(term for doc in docs for term in doc['terms'])
        self._average = sum(doc['length'] for doc in docs) / max(len(docs), 1) or 1

    async def select(self, context, services):
        docs = self.state['documents']
        # The last user request has priority; recent dialogue resolves short
        # answers and actual tool results contribute result-dependent terms.
        query = Counter(tokens(context.text('latest_user')) * 3 + tokens(context.text()))
        names = {p['name'] for p in self.eligible(context)}
        ranked = []
        for doc in docs:
            if doc['name'] not in names:
                continue
            score = 0.0
            for term, weight in query.items():
                frequency = doc['terms'].get(term, 0)
                if frequency:
                    idf = math.log(1 + (len(docs) - self._df[term] + .5) / (self._df[term] + .5))
                    score += weight * idf * frequency * 2.5 / (frequency + 1.5 * (.25 + .75 * doc['length'] / self._average))
            if score > 0:
                ranked.append((score, doc['name']))
        ranked.sort(key=lambda item: -item[0])
        return Selection([Match(name, reason=f'BM25 relevance {score:.4f}')
                          for score, name in ranked[:self.options.get('top_k', 12)]])


def normalize_vectors(vectors, count, dimension=None):
    if not isinstance(vectors, list) or len(vectors) != count:
        raise ValueError('Embedding response count mismatch')
    normalized = []
    for row in vectors:
        if (not isinstance(row, list) or not row or (dimension is not None and len(row) != dimension)
                or any(type(v) not in (int, float) or not math.isfinite(v) for v in row)):
            raise ValueError('Invalid embedding dimension or values')
        dimension = len(row)
        norm = math.hypot(*row)
        if not norm or not math.isfinite(norm):
            raise ValueError('Invalid zero or overflowing embedding')
        normalized.append([v / norm for v in row])
    return normalized


class EmbeddingPolicy(Policy):
    option_names = frozenset({'embedding', 'top_k', 'min_score'})

    @classmethod
    def validate_options(cls, options):
        super().validate_options(options)
        if not isinstance(options.get('embedding'), str) or not options['embedding'].strip():
            raise ValueError('embedding requires a named endpoints.yml embedding resource')
        _positive(options, 'top_k', 12)
        value = options.get('min_score', 0)
        if type(value) not in (int, float) or not math.isfinite(value) or not -1 <= value <= 1:
            raise ValueError('min_score must be between -1 and 1')

    async def train(self, services):
        docs = documents(self.policies)
        vectors = []
        for start in range(0, len(docs), 64):
            batch = docs[start:start + 64]
            vectors.extend(await services.embed(self.options['embedding'], [d['text'] for d in batch]))
        vectors = normalize_vectors(vectors, len(docs))
        return {'names': [d['name'] for d in docs], 'vectors': vectors}

    def load_state(self, state):
        super().load_state(state)
        if state.get('names') != [p['name'] for p in self.policies]:
            raise ValueError('Invalid embedding policy names')
        self.state['vectors'] = normalize_vectors(state.get('vectors'), len(state['names']))

    async def select(self, context, services):
        if not self.state['names'] or not context.text().strip():
            return Selection()
        query = normalize_vectors(await services.embed(self.options['embedding'], [context.text()]), 1,
                                  len(self.state['vectors'][0]))[0]
        eligible = {p['name'] for p in self.eligible(context)}
        ranked = [(sum(a * b for a, b in zip(query, vector)), name)
                  for name, vector in zip(self.state['names'], self.state['vectors']) if name in eligible]
        ranked.sort(key=lambda item: -item[0])
        return Selection([Match(name, reason=f'Cosine relevance {score:.4f}')
                          for score, name in ranked[:self.options.get('top_k', 12)]
                          if score >= self.options.get('min_score', 0)])


class RulePolicy(Policy):
    option_names = frozenset({'rules'})

    @classmethod
    def validate_options(cls, options):
        super().validate_options(options)
        if not isinstance(options.get('rules'), list):
            raise ValueError('rule Policy requires rules: [...]')
        for rule in options['rules']:
            if (not isinstance(rule, dict) or set(rule) != {'policy', 'field', 'any'}
                    or not isinstance(rule['policy'], str)
                    or rule['field'] not in ('latest_user', 'conversation', 'tool_results')
                    or not isinstance(rule['any'], list) or not rule['any']
                    or any(not isinstance(s, str) or not s.strip() for s in rule['any'])):
                raise ValueError('Each rule requires policy, field and nonempty literal any phrases')

    async def train(self, services):
        names = {p['name'] for p in self.policies}
        if any(r['policy'] not in names for r in self.options['rules']):
            raise ValueError('Rule references unknown Policy')
        return {'rules': [{**r, 'any': [unicodedata.normalize('NFKC', s).casefold() for s in r['any']]}
                          for r in self.options['rules']]}

    def load_state(self, state):
        super().load_state(state)
        self.validate_options({'rules': state.get('rules')})
        if any(r['policy'] not in {p['name'] for p in self.policies} for r in state['rules']):
            raise ValueError('Rule references unknown Policy')

    async def select(self, context, services):
        names = {p['name'] for p in self.eligible(context)}
        matches = []
        for rule in self.state['rules']:
            text = unicodedata.normalize('NFKC', context.text(rule['field'])).casefold()
            if rule['policy'] in names and any(phrase in text for phrase in rule['any']):
                matches.append(Match(rule['policy'], reason='Compiled literal rule match'))
                names.remove(rule['policy'])
        return Selection(matches)
