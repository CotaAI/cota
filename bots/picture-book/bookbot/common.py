"""Portable project/configuration boundaries for the example Bot."""
import hashlib
import json
import os
from pathlib import Path
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
    return json.loads(Path(path).read_text(encoding='utf-8'))


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


def book_config(root):
    try:
        config = yaml.safe_load((Path(root) / 'endpoints.yml').read_text(encoding='utf-8')) or {}
    except yaml.YAMLError:
        # YAML errors include excerpts of the document, potentially its key.
        raise ValueError('Invalid endpoints.yml YAML; check the file locally (contents omitted)') from None
    if not isinstance(config, dict) or not isinstance(config.get('picture_book', {}), dict):
        raise ValueError('endpoints.yml and picture_book must be mappings')
    return config.get('picture_book', {})


def model_config(root, kind):
    value = book_config(root).get(kind) or {}
    label = f'endpoints.yml picture_book.{kind}'
    if not isinstance(value, dict) or any(not isinstance(value.get(k), str) or not value[k].strip()
                                          for k in ('key', 'apibase', 'model')):
        raise ValueError(f'Configure {label}: key, apibase, model')
    parsed = urlsplit(value['apibase'])
    if (parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment):
        raise ValueError(f'{label}.apibase must be an HTTP(S) API base URL without credentials/query')
    return value
