"""Versioned PDF-page progress for the example Bot, independent of Cota DST.

Call plan/complete under Production's project lock. Version counts are an audit
trail, not a paid-image budget. Changed pixels always require current evidence.
"""
import re

from .common import confined, read_json, sha256
from .production import ProductionBlocked, _criteria

_STATE = '.bookbot/render-state.json'
_HASH = re.compile(r'[a-f0-9]{64}')


def _invalid():
    return ProductionBlocked('render_history_invalid', 'render',
        'Saved page-version history is invalid and cannot be trusted',
        'Preserve the existing package and inspect the render history; do not reset it')


def load_state(project, manifest=None):
    path = confined(project, _STATE)
    if not path.exists():
        if (manifest or {}).get('render_page_hashes'):
            raise _invalid()
        return {'version': 1, 'pages': {}}
    try:
        data = read_json(path)
        if data.get('version') != 1 or not isinstance(data.get('pages'), dict):
            raise ValueError()
        active = data.get('active_pages', list(data['pages']))
        if (not isinstance(active, list) or any(not isinstance(n, str) or n not in data['pages'] for n in active)
                or len(set(active)) != len(active)):
            raise ValueError()
        for number, row in data['pages'].items():
            if (not number.isdecimal() or int(number) < 1 or not isinstance(row, dict)
                    or type(row.get('versions')) is not int or row['versions'] < 1
                    or not isinstance(row.get('input_hash'), str) or not _HASH.fullmatch(row['input_hash'])
                    or not isinstance(row.get('preview_hash'), str) or not _HASH.fullmatch(row['preview_hash'])
                    or type(row.get('blank')) is not bool):
                raise ValueError()
        return data
    except (OSError, ValueError, TypeError, AttributeError):
        raise _invalid() from None


def accepted_review(project, number, preview_hash, *, require_native=False):
    """Only current-criteria, exact-image evidence can count as accepted."""
    folders = confined(project, '.bookbot/reviews')
    if not folders.exists():
        return False
    for folder in folders.glob('pdf-face-*'):
        if not re.fullmatch(r'pdf-face-0*' + str(number), folder.name):
            continue
        for candidate in folder.glob('*.json'):
            if candidate.name.endswith('.request.json'):
                continue
            try:
                path = confined(project, candidate)
                raw = path.read_bytes()
                report = read_json(path)
                metadata = read_json(confined(project, path.with_suffix('.request.json')))
                target = report['image_inputs'][0]
                assessment = report['assessment']
                if 'prompt' in report or require_native:
                    _, criteria = _criteria(project, folder.name)
                    if criteria is None or criteria['criteria_hash'] != sha256(report.get('prompt', '').encode()):
                        continue
                if require_native:
                    source = report.get('source', {})
                    if source.get('tool') != 'image_understand' or not all(
                            isinstance(source.get(k), str) and source[k] for k in
                            ('session_id', 'run_id', 'event_id', 'tool_call_id')):
                        continue
                checks = assessment.get('checks')
                if not isinstance(checks, list) or not checks or not all(isinstance(c, dict) for c in checks):
                    continue
                required = [c for c in checks if c.get('severity') == 'required']
                if (metadata.get('kind') == 'review' and metadata.get('status') == 'completed'
                        and metadata.get('input_hash') == report.get('input_hash') == path.stem
                        and metadata.get('asset') == report.get('asset') == folder.name
                        and metadata.get('report_hash') == sha256(raw)
                        and target.get('role') == 'target' and target.get('sha256') == preview_hash
                        and assessment.get('verdict') == 'pass' and required
                        and all(c.get('status') == 'pass' for c in required)):
                    return True
            except (OSError, ValueError, KeyError, IndexError, TypeError, AttributeError):
                # Corrupt or unstructured prose is never evidence of acceptance.
                continue
    return False


def plan_versions(project, state, hashes):
    changed = []
    active = set(state.get('active_pages', state['pages']))
    for number in active - hashes.keys():
        if accepted_review(project, int(number), state['pages'][number]['preview_hash']):
            raise ProductionBlocked('accepted_page_changed', f'pdf-face-{int(number):02d}',
                'An accepted page cannot be removed from this production task',
                'Keep the accepted package; use a separate user-requested production task for structural changes')
    for number, fingerprint in hashes.items():
        previous = state['pages'].get(number)
        if previous and previous['input_hash'] == fingerprint and number in active:
            continue
        changed.append(int(number))
    return changed


def completed_state(state, hashes, preview_hashes, blanks):
    pages = {number: dict(row) for number, row in state['pages'].items()}
    for number, fingerprint in hashes.items():
        previous = pages.get(number)
        changed = not previous or previous['input_hash'] != fingerprint or number not in state.get('active_pages', state['pages'])
        pages[number] = {'versions': (previous['versions'] if previous else 0) + int(changed),
                         'input_hash': fingerprint, 'preview_hash': preview_hashes[number],
                         'blank': number in blanks}
    return {'version': 1, 'pages': pages, 'active_pages': sorted(hashes, key=int)}


def render_status(project):
    state = load_state(project)
    pages, pending = {}, []
    for number, row in sorted(state['pages'].items(), key=lambda item: int(item[0])):
        accepted = accepted_review(project, int(number), row['preview_hash'])
        active = number in state.get('active_pages', state['pages'])
        pages[number] = {**row, 'accepted': accepted, 'active': active}
        if active and not row['blank'] and not accepted:
            pending.append(int(number))
    return {'pages': pages, 'pending_pages': pending, 'based_on': 'last_completed_build'}
