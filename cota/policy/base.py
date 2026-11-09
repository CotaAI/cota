"""Policy extension contract and common validation/rendering boundary."""
import asyncio
from collections import OrderedDict
from copy import deepcopy
from dataclasses import asdict, dataclass, field
import hashlib
import json
import time

from .catalog import PolicyCatalog, policy_skills


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


@dataclass
class PolicyServices:
    model: object = None  # name -> existing Cota model instance
    embedding: object = None  # async (name, texts) -> vectors

    def llm(self, name):
        if self.model is None:
            raise ValueError(f'Policy model resource unavailable: {name}')
        return self.model(name)

    async def embed(self, name, texts):
        if self.embedding is None:
            raise ValueError(f'Policy embedding resource unavailable: {name}')
        return await self.embedding(name, texts)


@dataclass(frozen=True)
class Match:
    name: str
    status: str = 'candidate'
    step: int | None = None
    evidence: tuple = ()
    reason: str = ''


@dataclass
class Selection:
    matches: list = field(default_factory=list)
    diagnostics: list = field(default_factory=list)


class Policy:
    """Override train/load_state/select; guidance always validates original references.

    Training state must be JSON serializable. Increment version whenever its
    representation or semantics change. Instances are scoped to one Bot.
    """
    version = '1'
    requires_training = True
    option_names = frozenset()

    def __init__(self, catalog=None, *, options=None, context_chars=16000, timeout_seconds=20):
        self.catalog = catalog if catalog is not None else PolicyCatalog()
        self.options = deepcopy(options or {})
        self.validate_options(self.options)
        self.context_chars, self.timeout_seconds = context_chars, timeout_seconds
        self.state = {}
        self._cache = OrderedDict()

    @classmethod
    def validate_options(cls, options):
        if not isinstance(options, dict) or set(options) - cls.option_names:
            raise ValueError(f'Unsupported {cls.__name__} options: {options}')

    @property
    def policies(self):
        return self.catalog.policies

    def validate_skills(self, names):
        self.catalog.validate_skills(names)

    async def train(self, services):
        return {}

    def load_state(self, state):
        if not isinstance(state, dict):
            raise ValueError('Policy training state must be an object')
        self.state = deepcopy(state)
        self._cache.clear()

    async def select(self, context, services):
        raise NotImplementedError

    def eligible(self, context):
        available = set(context.available_skills)
        return [p for p in self.policies if set(policy_skills(p)) <= available]

    def validate_selection(self, selection, context):
        if not isinstance(selection, Selection):
            raise ValueError('Policy.select must return Selection')
        known = {p['name']: p for p in self.eligible(context)}
        seen = set()
        for match in selection.matches:
            if not isinstance(match, Match) or match.name not in known or match.name in seen:
                raise ValueError('Policy selection references an unknown, unavailable or duplicate case')
            seen.add(match.name)
            if match.status not in ('candidate', 'conditional', 'applicable', 'not_applicable'):
                raise ValueError('Invalid Policy applicability status')
            if match.step is not None and (type(match.step) is not int or not 0 <= match.step < len(known[match.name]['steps'])
                                           or 'bot' not in known[match.name]['steps'][match.step]):
                raise ValueError('Policy focus must reference an existing bot step')
            if (not isinstance(match.evidence, (list, tuple))
                    or any(not isinstance(ref, str) or ref not in context.evidence_ids for ref in match.evidence)):
                raise ValueError('Policy evidence must reference visible observations')
            if match.status == 'applicable' and (not match.evidence or match.step is None):
                raise ValueError('Applicable guidance requires evidence and a focused bot step')
            if not isinstance(match.reason, str) or len(match.reason) > 1000:
                raise ValueError('Policy reason must be a short explanation')
        return selection

    async def guidance(self, context, services=None):
        services = services or PolicyServices()
        key = digest(context.as_dict())
        started = time.monotonic()
        cached = self._cache.get(key)
        cache_hit = cached is not None
        if cached is not None:
            selection = deepcopy(cached)
            self._cache.move_to_end(key)
        else:
            try:
                async with asyncio.timeout(self.timeout_seconds):
                    selection = self.validate_selection(await self.select(context, services), context)
            except Exception as error:
                # A failed selector is not a failed business action. Preserve
                # conditional examples, never promote fallback to applicability.
                selection = Selection([Match(p['name']) for p in self.eligible(context)],
                                      [{'code': 'policy_fallback', 'error_type': type(error).__name__}])
            if not selection.diagnostics:
                self._cache[key] = deepcopy(selection)
                while len(self._cache) > 64:
                    self._cache.popitem(last=False)
        decisions = [{**asdict(match), 'evidence': list(match.evidence)} for match in selection.matches]
        guidance = self.catalog.guidance(context.available_skills, [], matches=decisions)
        return {**guidance, 'decisions': decisions, 'diagnostics': deepcopy(selection.diagnostics),
                'method': type(self).__name__, 'cache_hit': cache_hit,
                'duration_ms': round((time.monotonic() - started) * 1000, 3)}
