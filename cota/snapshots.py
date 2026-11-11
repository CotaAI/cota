"""Disposable, versioned state snapshots. Events remain authoritative."""
from copy import deepcopy
import hashlib
import json
import logging
import time

logger = logging.getLogger(__name__)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     allow_nan=False, separators=(',', ':')).encode()).hexdigest()


def make_snapshot(dst):
    snapshot = {
        'session_id': dst.session_id, 'schema_version': dst.STATE_VERSION,
        'last_sequence': len(dst.events),
        'last_event_id': dst.events[-1].event_id if dst.events else None,
        'events_hash': dst.event_hash(),
        'state': dst.state_dict(), 'created_at': time.time(),
    }
    snapshot['checksum'] = digest(snapshot)
    return snapshot


def usable_snapshot(snapshot, session_id, facts):
    """Reject stale-format/corrupt caches without hiding invalid source events."""
    from cota.dst import DST
    try:
        candidate = deepcopy(snapshot)
        checksum = candidate.pop('checksum')
        seq = candidate['last_sequence']
        state = candidate['state']
        expected = DST(session_id, None).state_dict()
        if (candidate['session_id'] != session_id or
                type(candidate['schema_version']) is not int or candidate['schema_version'] != DST.STATE_VERSION or
                type(seq) is not int or not 0 <= seq <= len(facts) or
                checksum != digest(candidate) or set(state) != set(expected) or
                candidate['events_hash'] != digest([event.as_dict() for event in facts[:seq]]) or
                candidate['last_event_id'] != (facts[seq - 1].event_id if seq else None)):
            raise ValueError('snapshot version, checksum or event cursor mismatch')
        if not all(isinstance(state[key], dict) for key in ('user_context', 'execution')):
            raise ValueError('invalid state objects')
        if state['created_at'] != (facts[0].timestamp if seq else None) or state['updated_at'] != (facts[seq-1].timestamp if seq else None):
            raise ValueError('invalid state timestamps')
        for kind in ('user', 'bot'):
            last = next((e.event_id for e in reversed(facts[:seq]) if e.type == kind + '_utter'), None)
            if state['latest_' + kind + '_event_id'] != last:
                raise ValueError('invalid message cursor')
        from cota.events.context import validate_context
        validate_context(state['context_messages'])
        from cota.events.event import validate_execution
        validate_execution(state['execution'])
        return True
    except (KeyError, TypeError, ValueError, AttributeError):
        logger.warning('Ignoring unusable DST snapshot for session %s; replaying events', session_id)
        return False
