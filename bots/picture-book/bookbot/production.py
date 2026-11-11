"""Project-local production limits, derived from the existing request evidence.

No Agent loop or book-quality decision lives here. The OS lock only serializes
command reservations; generation journals remain the source of attempt counts.
"""
import math
import os
from pathlib import Path
import re

from .common import confined, read_json, sha256, write_json

MAX_GENERATIONS = 3
_ASSET = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}')
_HASH = re.compile(r'[a-f0-9]{64}')


class ProductionBlocked(ValueError):
    def __init__(self, reason, asset, message, next_action, **counts):
        super().__init__(message)
        self.details = {'reason': reason, 'asset': asset, 'retryable': False,
                        'next': next_action, **counts}


def _asset(value):
    if not isinstance(value, str) or not _ASSET.fullmatch(value):
        raise ValueError('Use a stable asset ID with 1–80 letters, numbers, hyphens or underscores')
    return value


def _invalid(asset):
    return ProductionBlocked('production_history_invalid', asset,
        'Production history is missing or invalid; its budget cannot be inferred',
        'Inspect the existing project evidence; do not reset counters or start a replacement paid request')


def _journals(project, asset=None):
    records = []
    for path in sorted(Path(project).rglob('*.request.json')):
        try:
            record = read_json(confined(project, path))
            if not isinstance(record, dict):
                raise ValueError()
            if record.get('kind') == 'review':
                continue
            if record.get('kind') not in (None, 'generation'):
                raise ValueError()
            if record.get('asset') is not None:
                _asset(record['asset'])
                if record.get('status') not in ('started', 'completed'):
                    raise ValueError()
                confined(project, record['output'])
                if 'attempt' in record and (type(record['attempt']) is not int or record['attempt'] < 1):
                    raise ValueError()
                if 'started_at' in record and (type(record['started_at']) not in (int, float)
                        or not math.isfinite(record['started_at']) or record['started_at'] < 0):
                    raise ValueError()
        except (OSError, ValueError, KeyError, TypeError):
            raise _invalid(asset) from None
        records.append((path, record))
    return records


def _criteria(project, asset):
    path = confined(project, f'.bookbot/assets/{asset}.json')
    if not path.exists():
        reviews = confined(project, f'.bookbot/reviews/{asset}')
        if reviews.exists() and any(reviews.iterdir()):
            raise _invalid(asset)
        return path, None
    try:
        record = read_json(path)
        if (record['asset'] != asset or not isinstance(record['criteria'], str)
                or not record['criteria'].strip()
                or sha256(record['criteria'].encode()) != record['criteria_hash']):
            raise ValueError()
    except (OSError, ValueError, KeyError, TypeError):
        raise _invalid(asset) from None
    return path, record


class Production:
    def __init__(self, project, asset):
        self.asset = _asset(asset)
        self.project = Path(project).resolve()
        self._lock = None

    def __enter__(self):
        path = confined(self.project, '.bookbot/production.lock')
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = path.open('a+b')
        try:
            if os.name == 'nt':
                import msvcrt
                # Windows byte locks require a byte, and lock from file position.
                self._lock.seek(0, 2)
                if self._lock.tell() == 0:
                    self._lock.write(b'\0')
                    self._lock.flush()
                self._lock.seek(0)
                msvcrt.locking(self._lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self._lock.close()
            self._lock = None
            raise ProductionBlocked('production_in_progress', self.asset,
                'Another production command is already running in this project',
                'Inspect status and the running command; do not launch a parallel paid request') from None
        return self

    def __exit__(self, *error):
        # Closing the descriptor releases the OS lock, including after a crash.
        if self._lock is not None:
            self._lock.close()
            self._lock = None

    @property
    def generations(self):
        return [(path, record) for path, record in _journals(self.project, self.asset)
                if record.get('asset') == self.asset and not record.get('reused_from')]

    def check_generation(self):
        records = self.generations
        if any(record['status'] == 'started' for _, record in records):
            raise ProductionBlocked('prior_outcome_unknown', self.asset,
                'A prior generation for this asset has an unknown outcome',
                'Inspect saved journals and provider history; keep existing assets and continue independent work')
        if len(records) >= MAX_GENERATIONS:
            raise ProductionBlocked('revision_limit_reached', self.asset,
                'The initial generation and two revisions have been used for this asset',
                'Stop regenerating this asset, preserve the current version, report unresolved issues and continue independent work',
                attempts=len(records), remaining_generations=0)
        return len(records) + 1

    def bind_criteria(self, prompt):
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError('Review criteria must be nonempty text')
        prompt = prompt.strip()
        path, previous = _criteria(self.project, self.asset)
        if previous and previous['criteria'] != prompt:
            raise ProductionBlocked('review_criteria_changed', self.asset,
                'Review criteria for this asset are already fixed',
                'Reuse the original criteria; report conflicting observations as uncertain rather than starting another revision cycle')
        if previous is None:
            write_json(path, {'asset': self.asset, 'criteria': prompt,
                              'criteria_hash': sha256(prompt.encode())})
        return prompt

    def review_path(self, identity):
        if not isinstance(identity, str) or not _HASH.fullmatch(identity):
            raise ValueError('Review identity must be a SHA-256 hex digest')
        return confined(self.project, f'.bookbot/reviews/{self.asset}/{identity}.json')


def production_status(project):
    """Read-only counters; old unlabelled records remain explicitly untracked."""
    project = Path(project).resolve()
    assets, untracked = {}, []
    for path, record in _journals(project):
        asset = record.get('asset')
        if asset is None:
            untracked.append(str(path.relative_to(project)))
        elif not record.get('reused_from'):
            assets.setdefault(asset, []).append(record)
    for path in sorted(project.glob('.bookbot/assets/*.json')):
        asset = _asset(path.stem)
        _criteria(project, asset)
        assets.setdefault(asset, [])
    result = {}
    for asset, records in sorted(assets.items()):
        entry = {'attempts': len(records), 'remaining_generations': max(0, MAX_GENERATIONS - len(records))}
        if records:
            latest = max(records, key=lambda row: (row.get('attempt', 0), row.get('started_at', 0), row['output']))
            entry['latest_output'] = latest['output']
        if any(record['status'] == 'started' for record in records):
            entry['blocked_reason'] = 'prior_outcome_unknown'
        elif len(records) >= MAX_GENERATIONS:
            entry['blocked_reason'] = 'revision_limit_reached'
        reports = sorted(project.glob(f'.bookbot/reviews/{asset}/*.json'))
        # Review pending journals do not claim a completed observation.
        entry['reviews'] = [str(p.relative_to(project)) for p in reports if not p.name.endswith('.request.json')]
        result[asset] = entry
    return {'assets': result, 'untracked_requests': untracked}
