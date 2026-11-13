"""Import actual Pi image_understand observations; never request another verdict."""
import json
from contextlib import closing
from pathlib import Path
import sqlite3
import time

from .common import confined, endpoint_config, model_config, read_json, sha256, write_json
from .models import _artifact_path, _cached_review, _identity, image_data
from .production import Production
from .review_checks import assess


def _observation(root, tool_call_id):
    # This example uses the Bot's local SQLite Store. Open read-only: never
    # initialize a Store/Agent or migrate, append to, or lock a live session.
    config = endpoint_config(root)
    store = config.get('base_store', {})
    if (not isinstance(store, dict) or store.get('type') != 'sql' or store.get('dialect') != 'sqlite'
            or not isinstance(store.get('db'), str) or not store['db'].strip()):
        raise ValueError('Importing tool reviews requires this Bot\'s SQLite Store')
    database = (Path(root) / store['db']).resolve()
    try:
        with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=5)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT session_id,sequence,event_id,run_id,type,payload FROM events "
                "WHERE type IN ('tool_started','tool_result') AND json_extract(payload,'$.tool_call_id')=? "
                'ORDER BY session_id,sequence LIMIT 3', (tool_call_id,)).fetchall()
        if len(rows) != 2:
            raise ValueError()
        start, result = [dict(row) for row in rows]
        args, outcome = json.loads(start['payload']), json.loads(result['payload'])
        if (start['type'] != 'tool_started' or result['type'] != 'tool_result'
                or start['session_id'] != result['session_id'] or not start['run_id']
                or start['run_id'] != result['run_id'] or start['sequence'] >= result['sequence']
                or args.get('tool') != 'image_understand' or outcome.get('tool') != 'image_understand'
                or outcome.get('status') != 'success'):
            raise ValueError()
        details = outcome['result']
        content = outcome['content'][0]
        if not isinstance(details, dict) or content.get('type') != 'text' or not content.get('text', '').strip():
            raise ValueError()
        source = {'tool': 'image_understand', 'session_id': result['session_id'], 'run_id': result['run_id'],
                  'tool_call_id': tool_call_id, 'event_id': result['event_id']}
        return args['arguments'], details, content['text'], source
    except (sqlite3.Error, ValueError, KeyError, IndexError, TypeError, AttributeError):
        raise ValueError('No unique committed successful image_understand call; inspect the tool result') from None


def record_review(root, project, prompt_file, images, output, *, asset, tool_call_id):
    if len(images) != 1:
        raise ValueError('Native review imports one target image; review each PDF face separately')
    args, details, text, source = _observation(root, tool_call_id)
    config = model_config(root, 'vision')
    prompt = confined(project, prompt_file).read_text(encoding='utf-8').strip()
    if not prompt or len(prompt) > 32000:
        raise ValueError('Review prompt must be nonempty and at most 32000 characters')
    inputs = [image_data(project, images[0])]
    image, data, _ = inputs[0]
    original = confined(project, args.get('image_path', ''))
    if (args.get('prompt', '').strip() != prompt or details.get('model') != config['model']
            or Path(details.get('image_path', '')).resolve() != original
            or details.get('image_sha256') != sha256(data)):
        raise ValueError('Visual review input, criteria or model does not match the actual tool call')
    evidence = [{'image': 1, 'role': 'target', 'path': str(original.relative_to(project)), 'sha256': sha256(data)}]
    current = [{**evidence[0], 'path': str(image.relative_to(project))}]
    identity = sha256((_identity(config, prompt, inputs) + ':' + asset + ':native-review-v1').encode())
    with Production(project, asset) as production:
        path = _artifact_path(project, output, '.json')
        if path.exists() and read_json(path).get('input_hash') != identity:
            raise ValueError('Review already exists; choose a new revision filename')
        production.bind_criteria(prompt)
        canonical = production.review_path(identity)
        journal = canonical.with_suffix('.request.json')
        cached = _cached_review(canonical, journal, identity, asset)
        if cached is not None:
            if path.exists() and any(read_json(path).get(k) != v for k, v in cached.items()):
                raise ValueError('Saved visual review was modified; preserve existing evidence')
            if not path.exists():
                write_json(path, cached)
            return {**cached, 'reused': True, 'current_image_inputs': current}
        record = {'asset': asset, 'model': config['model'], 'input_hash': identity, 'content': text,
                  'prompt': prompt, 'assessment': assess(text, prompt), 'source': source,
                  'images': [evidence[0]['path']], 'image_inputs': evidence, 'created_at': time.time()}
        write_json(canonical, record)
        write_json(journal, {'kind': 'review', 'asset': asset, 'status': 'completed', 'input_hash': identity,
                             'report_hash': sha256(canonical.read_bytes())})
        write_json(path, record)
        return {**record, 'reused': False, 'current_image_inputs': current}


def require_visual_reviews(project):
    from .render_state import accepted_review
    manifest = read_json(project / 'book.json')
    count = len(manifest['pages'])
    missing = []
    for page in manifest['pages']:
        if page.get('blank'):
            continue
        number = page['page']
        preview = confined(project, f'previews/pages/page-{number:0{len(str(count))}d}.png')
        if not preview.is_file() or not accepted_review(project, number, sha256(preview.read_bytes()), require_native=True):
            missing.append(number)
    if missing:
        raise ValueError(f'Missing passing image_understand visual review for PDF faces: {missing}; '
                         'import actual tool evidence with review --tool-call-id, or deliver an explicitly unapproved draft')
