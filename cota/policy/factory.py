"""Policy registry, strict configuration and portable JSON training artifacts."""
from copy import deepcopy
import importlib
import json
import math
import os
from pathlib import Path
import tempfile

from .base import Policy, PolicyServices, digest
from .catalog import PolicyCatalog
from .model import ModelPolicy, RetrievalModelPolicy, SearchModelPolicy
from .retrieval import AllPolicy, BM25Policy, EmbeddingPolicy, RulePolicy


_POLICIES = {'all': AllPolicy, 'bm25': BM25Policy, 'embedding': EmbeddingPolicy,
             'model': ModelPolicy, 'retrieval_model': RetrievalModelPolicy,
             'search_model': SearchModelPolicy, 'rule': RulePolicy}


def register_policy(name, implementation):
    if not isinstance(name, str) or not name.strip() or ':' in name or name in _POLICIES:
        raise ValueError('Policy registration requires a new nonempty name without colon')
    if not isinstance(implementation, type) or not issubclass(implementation, Policy):
        raise ValueError('Policy implementation must subclass Policy')
    _POLICIES[name] = implementation


def policy_class(name):
    if name in _POLICIES:
        return _POLICIES[name]
    if ':' not in name:
        raise ValueError(f'Unknown Policy type: {name}')
    module, attribute = name.split(':', 1)
    implementation = getattr(importlib.import_module(module), attribute)
    if not isinstance(implementation, type) or not issubclass(implementation, Policy):
        raise ValueError('Custom Policy must subclass cota.policy.Policy')
    return implementation


def validate_policy_config(config):
    allowed = {'type', 'artifact', 'max_policies', 'max_chars', 'context_chars', 'timeout_seconds', 'options'}
    if not isinstance(config, dict) or set(config) - allowed:
        raise ValueError('Unsupported policy configuration fields')
    kind = config.get('type', 'all')
    if not isinstance(kind, str) or not kind:
        raise ValueError('policy.type must be nonempty text')
    for key in ('max_policies', 'max_chars', 'context_chars'):
        if key in config and (type(config[key]) is not int or config[key] < 1):
            raise ValueError(f'policy.{key} must be a positive integer')
    if config.get('context_chars', 16000) < 1000:
        raise ValueError('policy.context_chars must be at least 1000')
    timeout = config.get('timeout_seconds', 20)
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError('policy.timeout_seconds must be positive and finite')
    artifact = config.get('artifact', 'models/policy.json')
    if not isinstance(artifact, str) or not artifact or Path(artifact).suffix != '.json':
        raise ValueError('policy.artifact must be a JSON path')
    options = config.get('options', {})
    if not isinstance(options, dict):
        raise ValueError('policy.options must be an object')
    policy_class(kind).validate_options(options)
    return deepcopy(config)


def catalog_budgets(config):
    validate_policy_config(config)
    return {key: config[key] for key in ('max_policies', 'max_chars') if key in config}


def _instance(root, config):
    validate_policy_config(config)
    cls = policy_class(config.get('type', 'all'))
    catalog = PolicyCatalog.load(Path(root) / 'policy', **catalog_budgets(config))
    return cls(catalog, options=config.get('options', {}),
               context_chars=config.get('context_chars', 16000), timeout_seconds=config.get('timeout_seconds', 20))


def _signature(root, config, policy):
    # Embedding index identity must change with the encoder/provider, but never
    # with credential rotation. Store only a hash, not endpoint configuration.
    from cota.utils.io import read_yaml_from_path
    endpoints = read_yaml_from_path(str(Path(root) / 'endpoints.yml')) or {}
    embeddings = endpoints.get('embeddings', {})
    options = config.get('options', {})
    embedding = options.get('embedding') or options.get('retriever_options', {}).get('embedding')
    resource = embeddings.get(embedding, {}) if embedding else {}
    identity = {k: v for k, v in resource.items() if k not in ('key', 'api_key', 'headers')}
    return {'schema_version': 1, 'type': config.get('type', 'all'),
            'implementation': type(policy).__module__ + ':' + type(policy).__qualname__,
            'version': policy.version, 'source_hash': digest(policy.policies),
            'options_hash': digest({'options': policy.options, 'embedding_resource': identity})}


def artifact_path(root, config):
    return Path(root) / config.get('artifact', 'models/policy.json')


def load_policy(root, config=None):
    config = config or {}
    policy = _instance(root, config)
    if not policy.requires_training:
        return policy
    try:
        artifact = json.loads(artifact_path(root, config).read_text(encoding='utf-8'))
        expected = _signature(root, config, policy)
        if (not isinstance(artifact, dict) or set(artifact) != {*expected, 'state', 'state_hash'}
                or any(artifact.get(k) != v for k, v in expected.items())
                or artifact['state_hash'] != digest(artifact['state'])):
            raise ValueError('Stale or damaged Policy artifact')
        policy.load_state(artifact['state'])
    except (OSError, ValueError, TypeError, KeyError) as error:
        raise ValueError('Policy training artifact missing, stale or invalid; run cota train --config ' + str(root)) from error
    return policy


async def train_policy(root, config=None, services=None):
    config, services = config or {}, services or PolicyServices()
    policy = _instance(root, config)
    signature = _signature(root, config, policy)
    state = await policy.train(services)
    policy.load_state(state)  # Validate before publishing, including plugin state.
    artifact = {**signature, 'state': state, 'state_hash': digest(state)}
    data = json.dumps(artifact, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
    # Recheck source before replacing a working model after a long embedding job.
    latest = _instance(root, config)
    if _signature(root, config, latest) != signature:
        raise ValueError('Policy sources changed during training; rerun cota train')
    target = artifact_path(root, config)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=target.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)
    return {'artifact': str(target), 'type': signature['type'], 'policies': len(policy.policies),
            'source_hash': signature['source_hash']}
