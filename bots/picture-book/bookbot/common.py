"""Portable project/configuration boundaries for the example Bot."""
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import urlsplit

import yaml


def confined(root, value):
    root = Path(root).resolve()
    candidate = root / value
    # A lexical in-root symlink must not turn publication into arbitrary reads.
    if any(p.is_symlink() for p in (candidate, *candidate.parents) if p != root and root in p.parents):
        raise ValueError('Symlinks are not supported in book projects')
    path = candidate.resolve()
    if not path.is_relative_to(root) or path == root:
        raise ValueError('Path must stay inside the project directory')
    return path


def project_path(root, value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('Project name or path is required')
    return confined(Path(root) / 'workspace/books', value)


def read_json(path):
    value = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise ValueError('Project JSON records must be objects')
    return value


def atomic_bytes(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix='.book-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as output:
            output.write(value)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def write_json(path, value):
    atomic_bytes(path, (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode())


def sha256(value):
    return hashlib.sha256(value).hexdigest()


def endpoint_config(root):
    try:
        config = yaml.safe_load((Path(root) / 'endpoints.yml').read_text(encoding='utf-8')) or {}
    except yaml.YAMLError:
        # YAML errors include excerpts of the document, potentially its key.
        raise ValueError('Invalid endpoints.yml YAML; check the file locally (contents omitted)') from None
    if not isinstance(config, dict) or not isinstance(config.get('picture_book', {}), dict):
        raise ValueError('endpoints.yml and picture_book must be mappings')
    return config


def book_config(root):
    return endpoint_config(root).get('picture_book', {})


def model_config(root, kind):
    config = endpoint_config(root)
    alias = {'image': 'image-generate', 'vision': 'image-understanding'}[kind]
    llms = config.get('llms') or {}
    if not isinstance(llms, dict):
        raise ValueError('endpoints.yml llms must be a mapping')
    if alias in llms:
        value = dict(llms[alias]) if isinstance(llms[alias], dict) else llms[alias]
        if kind == 'image' and isinstance(value, dict):
            value['api'] = value.get('type', 'openai')
        label = f'endpoints.yml llms.{alias}'
    else:
        value = config.get('picture_book', {}).get(kind) or {}
        label = f'endpoints.yml picture_book.{kind}'
    if not isinstance(value, dict) or any(not isinstance(value.get(k), str) or not value[k].strip()
                                          for k in ('key', 'apibase', 'model')):
        raise ValueError(f'Configure {label}: key, apibase, model')
    parsed = urlsplit(value['apibase'])
    if (parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment):
        raise ValueError(f'{label}.apibase must be an HTTP(S) API base URL without credentials/query')
    if kind == 'image':
        if value.get('api', 'openai') not in ('openai', 'qwen'):
            raise ValueError(f'{label}.api must be openai or qwen')
        hosts = value.get('download_hosts', ['*.aliyuncs.com'])
        if (not isinstance(hosts, list) or not hosts or any(not isinstance(host, str)
                or not re.fullmatch(r'(?:\*\.)?(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z][a-z0-9-]*', host)
                for host in hosts)):
            raise ValueError(f'{label}.download_hosts must list exact HTTPS hosts or *.domain suffixes')
    return value
