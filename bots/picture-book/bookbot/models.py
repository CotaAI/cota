"""OpenAI/Qwen Images and vision Chat Completions, without hidden retries.

Uses HTTPX (already a Cota dependency) so no image SDK version assumptions leak
into the framework. Prompts and binary images never appear in command arguments.
"""
import base64
from contextlib import ExitStack
import io
import json
import time
from urllib.parse import urlsplit

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
             'api': config.get('api', 'openai'),
             'images': [sha256(data) for _, data, _ in images]}
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode())


def _download_image(client, config, url):
    try:
        parsed = urlsplit(url)
        host = parsed.hostname or ''
        hosts = config.get('download_hosts', ['*.aliyuncs.com'])
        allowed = any(host.endswith(rule[1:]) if rule.startswith('*.') else host == rule for rule in hosts)
        if (parsed.scheme != 'https' or not allowed or parsed.username or parsed.password
                or parsed.fragment or parsed.port not in (None, 443)):
            raise ValueError()
    except (ValueError, TypeError):
        raise ValueError('Image URL must use HTTPS on an approved download_hosts domain') from None
    try:
        # Request headers from the authenticated POST are not reused. Never
        # follow redirects or retain signed URLs in errors/journals.
        with client.stream('GET', url, timeout=60, follow_redirects=False) as response:
            if response.status_code != 200:
                raise ValueError(f'Image download failed (HTTP {response.status_code}); no automatic retry')
            length = response.headers.get('content-length', '')
            if length.isdecimal() and int(length) > MAX_IMAGE_BYTES:
                raise ValueError('Downloaded image exceeds 32 MiB')
            data = bytearray()
            for chunk in response.iter_bytes():
                data.extend(chunk)
                if len(data) > MAX_IMAGE_BYTES:
                    raise ValueError('Downloaded image exceeds 32 MiB')
            return bytes(data)
    except httpx.HTTPError as error:
        raise ValueError(f'Image download failed ({type(error).__name__}); no automatic retry') from None


def _image_result(client, config, result):
    try:
        item = result['data'][0]
        encoded = item.get('b64_json')
        if encoded is not None:
            if not isinstance(encoded, str) or len(encoded) > MAX_IMAGE_BYTES * 4 / 3 + 4:
                raise ValueError()
            return base64.b64decode(encoded, validate=True)
        if config.get('api') == 'qwen' and isinstance(item.get('url'), str):
            url = item['url']
        else:
            raise ValueError()
    except (KeyError, IndexError, AttributeError, TypeError, ValueError):
        raise ValueError('Expected b64_json image data, or an approved image URL for api=qwen') from None
    return _download_image(client, config, url)


def generate(root, project, prompt_file, output, *, references=(), client=None):
    """One image per request; explicit image.api selects the provider protocol."""
    from PIL import Image
    config = model_config(root, 'image')
    prompt = confined(project, prompt_file).read_text(encoding='utf-8')
    if not prompt.strip() or len(prompt) > 32000 or len(references) > 8:
        raise ValueError('Provide a nonempty prompt (up to 32000 chars) and at most eight reference images')
    images = [image_data(project, path) for path in references]
    api = config.get('api', 'openai')
    if api == 'qwen':
        if config['model'].startswith('qwen-image-3.0') and len(images) > 3:
            raise ValueError('Qwen Image 3.0 supports at most three reference images')
        for _, data, _ in images:
            with Image.open(io.BytesIO(data)) as image:
                width, height = image.size
            if len(data) > 10 * 1024 * 1024 or max(width, height) > 8000 or max(width, height) / min(width, height) > 10:
                raise ValueError('Qwen references require <=10 MiB, <=8000 pixels per side and <=10:1 aspect ratio')
    path = confined(project, output)
    if path.suffix.lower() != '.png':
        raise ValueError('Generated image output must end in .png')
    settings = {key: config[key] for key in (('size',) if api == 'qwen' else
                                            ('size', 'quality', 'response_format')) if key in config}
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
    record = {'status': 'started', 'model': config['model'], 'api': api, 'input_hash': identity,
              'prompt': prompt, 'references': [str(p.relative_to(project)) for p, _, _ in images],
              'output': str(path.relative_to(project)), 'started_at': time.time()}
    write_json(journal, record)
    # A timeout/cancellation leaves started: a provider may already have charged.
    with ExitStack() as stack:
        client = client or stack.enter_context(httpx.Client(trust_env=False))
        if api == 'qwen':
            body = {'model': config['model'], 'prompt': prompt, 'n': 1, **settings}
            if images:
                inputs = [f'data:{mime};base64,' + base64.b64encode(data).decode() for _, data, mime in images]
                body['image'] = inputs[0] if len(inputs) == 1 else inputs
            result = _request(client, config, '/images/generations', json=body)
        elif images:
            result = _request(client, config, '/images/edits',
                              data={'model': config['model'], 'prompt': prompt, 'n': '1', **settings},
                              files=[('image[]', (p.name, data, mime)) for p, data, mime in images])
        else:
            result = _request(client, config, '/images/generations',
                              json={'model': config['model'], 'prompt': prompt, 'n': 1, **settings})
        data = _image_result(client, config, result)
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.load()
            png = io.BytesIO()
            image.convert('RGBA').save(png, 'PNG')
        atomic_bytes(path, png.getvalue())
    except (KeyError, IndexError, TypeError, ValueError, OSError, Image.DecompressionBombError):
        raise ValueError('Model output is not a valid PNG/JPEG/WebP image; check provider format') from None
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
