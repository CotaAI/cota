"""Images generations/edits and vision Chat Completions, without hidden retries.

Uses HTTPX (already a Cota dependency) so no image SDK version assumptions leak
into the framework. Prompts and binary images never appear in command arguments.
"""
import base64
from contextlib import ExitStack
import io
import json
import time

import httpx

from .common import confined, model_config, read_json, sha256, write_json, atomic_bytes

MAX_IMAGE_BYTES = 32 * 1024 * 1024


def image_data(project, path):
    from PIL import Image
    path = confined(project, path)
    if path.stat().st_size > MAX_IMAGE_BYTES:
        raise ValueError('Image exceeds 32 MiB')
    data = path.read_bytes()
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format not in ('PNG', 'JPEG', 'WEBP'):
                raise ValueError('Use PNG, JPEG or WebP images')
            mime = Image.MIME[image.format]
            image.verify()
    except (OSError, Image.DecompressionBombError):
        raise ValueError('Invalid image') from None
    return path, data, mime


def _request(client, config, route, **kwargs):
    try:
        result = client.post(config['apibase'].rstrip('/') + route,
                             headers={'Authorization': 'Bearer ' + config['key']}, timeout=240, **kwargs)
        if result.status_code != 200:
            raise ValueError(f'Model request failed (HTTP {result.status_code}); no automatic retry')
        if len(result.content) > 64 * 1024 * 1024:
            raise ValueError('Model response exceeds 64 MiB')
        return result.json()
    except httpx.HTTPError as error:
        raise ValueError(f'Model transport failed ({type(error).__name__}); check saved request before retrying') from None
    except json.JSONDecodeError:
        raise ValueError('Model returned invalid JSON') from None


def _identity(config, prompt, images):
    value = {'apibase': config['apibase'], 'model': config['model'], 'prompt': prompt,
             'images': [sha256(data) for _, data, _ in images]}
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode())


def generate(root, project, prompt_file, output, *, references=(), client=None):
    """One image per request. Reference images use multipart /images/edits."""
    from PIL import Image
    config = model_config(root, 'image')
    prompt = confined(project, prompt_file).read_text(encoding='utf-8')
    if not prompt.strip() or len(prompt) > 32000 or len(references) > 8:
        raise ValueError('Provide a nonempty prompt (up to 32000 chars) and at most eight reference images')
    images = [image_data(project, path) for path in references]
    path = confined(project, output)
    if path.suffix.lower() != '.png':
        raise ValueError('Generated image output must end in .png')
    settings = {key: config[key] for key in ('size', 'quality', 'response_format') if key in config}
    identity = sha256((_identity(config, prompt, images) + json.dumps(settings, sort_keys=True)).encode())
    journal = path.with_suffix('.request.json')
    previous = read_json(journal) if journal.exists() else None
    if path.exists():
        if previous and previous.get('status') == 'completed' and previous['input_hash'] == identity:
            if sha256(path.read_bytes()) == previous['sha256']:
                return {**previous, 'reused': True}
        raise ValueError('Output already exists with different or unverified input; choose a new revision filename')
    if previous and previous.get('status') == 'started':
        raise ValueError('Prior generation has an unknown outcome; inspect provider history, then use a new revision filename')
    record = {'status': 'started', 'model': config['model'], 'input_hash': identity,
              'prompt': prompt, 'references': [str(p.relative_to(project)) for p, _, _ in images],
              'output': str(path.relative_to(project)), 'started_at': time.time()}
    write_json(journal, record)
    # A timeout/cancellation leaves started: a provider may already have charged.
    with ExitStack() as stack:
        client = client or stack.enter_context(httpx.Client(trust_env=False))
        if images:
            result = _request(client, config, '/images/edits',
                              data={'model': config['model'], 'prompt': prompt, 'n': '1', **settings},
                              files=[('image[]', (p.name, data, mime)) for p, data, mime in images])
        else:
            result = _request(client, config, '/images/generations',
                              json={'model': config['model'], 'prompt': prompt, 'n': 1, **settings})
    try:
        encoded = result['data'][0]['b64_json']
        if not isinstance(encoded, str) or len(encoded) > MAX_IMAGE_BYTES * 4 / 3 + 4:
            raise ValueError('Invalid image response')
        data = base64.b64decode(encoded, validate=True)
        with Image.open(io.BytesIO(data)) as image:
            image.load()
            png = io.BytesIO()
            image.convert('RGBA').save(png, 'PNG')
        atomic_bytes(path, png.getvalue())
    except (KeyError, IndexError, TypeError, ValueError, OSError, Image.DecompressionBombError):
        raise ValueError('Expected a valid b64_json image; URL-only responses are not downloaded. Check provider format') from None
    record.update(status='completed', sha256=sha256(path.read_bytes()), finished_at=time.time())
    write_json(journal, record)
    return {**record, 'reused': False}


def review(root, project, prompt_file, images, output, *, client=None):
    config = model_config(root, 'vision')
    if not 1 <= len(images) <= 8:
        raise ValueError('Review requires one to eight actual images')
    prompt = confined(project, prompt_file).read_text(encoding='utf-8')
    inputs = [image_data(project, image) for image in images]
    path = confined(project, output)
    if path.suffix != '.json':
        raise ValueError('Review output must end in .json')
    identity = _identity(config, prompt, inputs)
    if path.exists():
        previous = read_json(path)
        if previous.get('input_hash') == identity:
            return {**previous, 'reused': True}
        raise ValueError('Review already exists; choose a new revision filename')
    content = [{'type': 'text', 'text': prompt}, *[
        {'type': 'image_url', 'image_url': {'url': f'data:{mime};base64,' + base64.b64encode(data).decode()}}
        for _, data, mime in inputs]]
    with ExitStack() as stack:
        client = client or stack.enter_context(httpx.Client(trust_env=False))
        result = _request(client, config, '/chat/completions', json={
            'model': config['model'], 'messages': [{'role': 'user', 'content': content}]})
    try:
        text = result['choices'][0]['message']['content']
        if not isinstance(text, str) or not text.strip():
            raise ValueError()
    except (KeyError, IndexError, TypeError, ValueError):
        raise ValueError('Vision model did not return review text') from None
    record = {'model': config['model'], 'input_hash': identity, 'content': text, 'prompt': prompt,
              'images': [str(p.relative_to(project)) for p, _, _ in inputs], 'created_at': time.time()}
    write_json(path, record)
    return record
