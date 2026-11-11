"""Append-only event persistence with disposable state snapshots.

SQL revisions protect concurrent writers; they do not provide distributed leases
or exactly-once external effects. Runtime still reconciles interrupted tools.
"""
import asyncio
from copy import deepcopy
from contextlib import nullcontext
import json
import time
from typing import Dict
from weakref import WeakValueDictionary, WeakKeyDictionary

import sqlalchemy as sa
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.dialects.mysql import LONGTEXT
from cota.dst import DST
from cota.delivery_store import (MemoryDeliveryStore, SQLDeliveryStore,
                                 delivery_rows, make_delivery_table, validate_target)
from cota.snapshots import digest, make_snapshot


# Small scalar fields for an execution index; never include prompts/tool bodies.
EVENT_SUMMARY_FIELDS = ('text', 'tool_call_id', 'tool', 'skill', 'status', 'request_id',
                        'request_sequence', 'purpose',
                        'result_event_id', 'input_event_id', 'error_type',
                        'resource_kind', 'resource_skill')
DEBUG_BODY_FIELDS = ('request', 'preparation', 'response', 'provider_response')


def event_header(event):
    header = {k: v for k, v in event.items() if k != 'payload'}
    resource = event['payload'].get('resource') or {}
    values = {**event['payload'], 'resource_kind': resource.get('kind'), 'resource_skill': resource.get('skill')}
    header['summary'] = {
        key: str(int(value)) if isinstance(value, bool) else (str(value)[:200] if key == 'text' else str(value))
        for key in EVENT_SUMMARY_FIELDS
        if (value := values.get(key)) is not None
        and isinstance(value, (str, int, float, bool))
    }
    return header


class StoreConflict(RuntimeError):
    """Reload and reconcile a newer session revision before retrying."""


class ExecutionSuperseded(StoreConflict):
    """Optional execution was approved against a conversation that has changed."""


class Store:
    def __init__(self, snapshot_interval=100):
        if type(snapshot_interval) is not int or snapshot_interval < 1:
            raise ValueError('snapshot_interval must be a positive integer')
        self.snapshot_interval = snapshot_interval
        self._locks = WeakValueDictionary()
        self._debug_log = None
        # Admission is volatile; only committed user/run events survive restart.
        self._inputs = {}
        self._input_locks = WeakValueDictionary()
        # Lifetime follows the detached execution, not every historical session.
        self._execution_commits = WeakKeyDictionary()

    def input_admission_lock(self, session_id):
        lock = self._input_locks.get(session_id)
        if lock is None:
            lock = asyncio.Lock()
            self._input_locks[session_id] = lock
        return lock

    async def _input_event(self, session_id, message_id):
        from cota.inputs import input_event_id, InputConflict
        event = await self.event_by_id(session_id, input_event_id(message_id))
        if event is not None and (event['type'] != 'user_utter' or
                (event['payload'].get('metadata') or {}).get('message_id') != message_id):
            raise InputConflict('message_id does not match its committed input event')
        return event

    async def check_input(self, message, *, durable_only=False):
        """Validate identity, returning (receipt, live future) for existing input."""
        from cota.inputs import input_key, canonical_input, event_input, InputConflict
        key = input_key(message)
        canonical = canonical_input(message)
        pending = self._inputs.get(key)
        if pending is not None and pending['canonical'] != canonical:
            raise InputConflict('message_id already identifies different input')
        event = await self._input_event(*key)
        if event is not None:
            if event_input(event) != canonical:
                raise InputConflict('message_id already identifies different input')
            return await self._input_receipt(*key, event), pending.get('future') if pending else None
        if pending is not None and not durable_only:
            return deepcopy(pending['receipt']), pending.get('future')
        return None, None

    def claim_input(self, message, future=None):
        from cota.inputs import input_key, canonical_input
        key = input_key(message)
        self._inputs[key] = {'canonical': canonical_input(message), 'future': future,
                            'receipt': {'session_id': key[0], 'message_id': key[1],
                                        'status': 'queued', 'error': None}}

    def start_input(self, message):
        from cota.inputs import input_key
        key = input_key(message)
        if key not in self._inputs:
            self.claim_input(message)
        self._inputs[key]['receipt']['status'] = 'running'

    def finish_input(self, message, *, processor=False):
        from cota.inputs import input_key
        key = input_key(message)
        pending = self._inputs.get(key)
        if pending is not None and (not processor or pending['future'] is None):
            self._inputs.pop(key)

    async def ensure_input_admissible(self, session_id):
        """Reject unowned unfinished runs before admitting a new input."""
        runs = await self._query_events(session_id, kinds=('run_started',), descending=True, limit=1)
        if not runs:
            return
        run = runs[0]
        finished = await self._query_events(session_id, run_id=run['run_id'],
                                            kinds=('run_finished',), limit=1)
        if finished:
            return
        from cota.inputs import input_event_id
        if any(sid == session_id and pending['receipt']['status'] == 'running' and
               input_event_id(mid) == run['payload'].get('input_event_id')
               for (sid, mid), pending in self._inputs.items()):
            return
        from cota.runtime.pi_runtime import RunInProgress
        raise RunInProgress('Previous run is still running; reconcile its executor before submitting new input')

    async def input_receipt(self, session_id, message_id):
        """Current input status from live admission or immutable user/run facts.

        Application inputs are durable before admission returns. Accepted inputs
        without a run are recorded and can be dispatched after restart. Started
        runs without a live executor or terminal fact are interrupted; merely
        looking up a receipt never resumes execution.
        """
        event = await self._input_event(session_id, message_id)
        if event is None and (session_id, message_id) not in self._inputs:
            # A commit may finish and drop its volatile claim while the first
            # SQL read is in flight. Re-read after observing that handoff.
            event = await self._input_event(session_id, message_id)
        return await self._input_receipt(session_id, message_id, event)

    async def _input_receipt(self, session_id, message_id, event):
        pending = self._inputs.get((session_id, message_id))
        if event is None:
            return deepcopy(pending['receipt']) if pending else None
        receipt = {'session_id': session_id, 'message_id': message_id,
                   'status': pending['receipt']['status'] if pending else (
                       'recorded' if ((event['payload'].get('metadata') or {}).get('mode') == 'group'
                                      or (event['payload'].get('metadata') or {}).get('accepted'))
                       else 'interrupted'),
                   'error': None, 'input_event_id': event['event_id']}
        if (event['payload'].get('metadata') or {}).get('execute') is False:
            receipt['status'] = 'completed'
            return receipt
        cursor = event['sequence']
        while True:
            runs = await self._query_events(session_id, kinds=('run_started',),
                                            after_sequence=cursor, limit=100)
            for run in runs:
                if run['payload'].get('input_event_id') != event['event_id']:
                    continue
                receipt['run_id'] = run['run_id']
                if pending is None:
                    receipt['status'] = 'interrupted'
                finished = await self._query_events(session_id, run_id=run['run_id'],
                                                    kinds=('run_finished',), descending=True, limit=1)
                if finished:
                    receipt['status'] = finished[0]['payload']['status']
                    receipt['error'] = finished[0]['payload'].get('error') or finished[0]['payload'].get('error_type')
                return receipt
            if len(runs) < 100:
                return receipt
            cursor = runs[-1]['sequence']

    def enable_debug_log(self, path):
        from cota.execution_logging import ExecutionLog
        self._debug_log = ExecutionLog(path)
        return self._debug_log.path

    @property
    def debug_enabled(self):
        return self._debug_log is not None

    async def save_model_debug(self, session_id, request_id, data):
        """Merge optional diagnostic fields; large bodies are write-once.

        An adapter request may be upgraded once to its actual provider payload.
        Status/transport/linkage updates need not carry request bodies again.
        Diagnostics never participate in state recovery or stop execution.
        """
        if not self.debug_enabled:
            return
        import logging
        try:
            await self._save_model_debug(session_id, request_id, deepcopy(data))
        except Exception as error:
            logging.getLogger(__name__).warning('Cannot save model diagnostics (%s)', type(error).__name__)

    async def model_debug(self, session_id, request_id):
        raise NotImplementedError

    async def model_debug_headers(self, session_id, limit=100):
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError('Invalid diagnostic page size')
        return await self._model_debug_headers(session_id, limit)

    def _emit_saved(self, data, previous_count):
        from cota.execution_logging import emit_committed
        emit_committed(data['session_id'], data['events'][previous_count:], self._debug_log)

    def session_lock(self, session_id):
        lock = self._locks.get(session_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[session_id] = lock
        return lock

    @staticmethod
    def create(endpoint_config: Dict) -> "Store":
        kind = endpoint_config.get('type', 'memory')
        interval = endpoint_config.get('snapshot_interval', 100)
        if not kind or kind.lower() == 'memory':
            return MemoryStore(snapshot_interval=interval)
        if kind.lower() != 'sql':
            raise ValueError(f'Unknown Store type: {kind}')
        dialect = endpoint_config.get('dialect', 'mysql+pymysql')
        defaults = ({'db': 'cota.db'} if dialect.startswith('sqlite') else
                    {'host': '127.0.0.1', 'port': 3306, 'db': 'mysql',
                     'username': 'root', 'password': ''})
        keys = ('host', 'port', 'db', 'username', 'password', 'login_db', 'query')
        return SQLStore(dialect=dialect, snapshot_interval=interval, **{
            k: endpoint_config.get(k, defaults.get(k)) for k in keys
            if k in endpoint_config or k in defaults})

    def _write_data(self, dst):
        data = dst.commit_data()
        boundary = any(e['type'] == 'run_finished' for e in data['events'])
        data['snapshot'] = (make_snapshot(dst) if data['events'] and (
            boundary or data['last_sequence'] - data['snapshot_sequence'] >= self.snapshot_interval) else None)
        return data

    def _prepare_commit(self, data, old, old_runs):
        revision = (old or {}).get('revision', 0)
        if revision != data['revision']:
            raise StoreConflict(f"Stale session revision: {data['session_id']}")
        count = (old or {}).get('last_sequence', 0)
        if count > data['last_sequence'] or count < data['base_sequence']:
            raise ValueError('Cannot edit or delete persisted event facts')
        prefix = data['prefix_hashes'][count].copy()
        prefix.update(b']')
        if old and prefix.hexdigest() != old['events_hash']:
            raise ValueError('Cannot edit or delete persisted event facts')
        if any(data['run_metadata'].get(run) != value for run, value in old_runs.items()):
            raise ValueError('Cannot edit or delete persisted run metadata')
        offset = count - data['base_sequence']
        new_events = data['events'][offset:]
        if old and not new_events and data['run_metadata'] == old_runs:
            return None, None, offset
        metadata = {'session_id': data['session_id'], 'user_id': data['user_id'],
                    'revision': revision + 1, 'last_sequence': data['last_sequence'],
                    'events_hash': data['events_hash'], 'updated_at': time.time()}
        return metadata, data['snapshot'], offset

    @staticmethod
    def _mark_saved(dst, data, revision):
        dst.revision = revision
        dst._persisted_sequence = data['last_sequence']
        if data['snapshot'] is not None:
            dst._snapshot_sequence = data['snapshot']['last_sequence']

    async def save(self, dst, delivery_target=None):
        raise NotImplementedError

    async def append_conversation_event(self, session_id, event, agent=None):
        """Append an input fact without sharing the producer's mutable event."""
        from cota.events import Event
        fact = Event.from_dict(event.as_dict())
        fact.sequence = None
        async with self.session_lock(session_id):
            canonical = await self.load(session_id, agent=agent)
            if canonical is None:
                canonical = DST(session_id, agent)
            canonical.apply_event(fact)
            await self.save(canonical)
            return fact.as_dict()

    async def save_execution(self, dst, delivery_target=None, *, expected_sequence=None):
        """Merge a detached execution's facts into the latest session journal.

        Later conversation inputs may be absent from ``dst`` by design. Event
        identities, rather than its local sequences or revision, identify facts
        already committed. The runtime view remains unchanged; returned records
        contain canonical sequences for delivery and other external references.
        """
        from cota.events import Event
        from cota.run_metadata import validate_run_metadata
        target = validate_target(delivery_target)
        dst._check_state()
        # The branch can advance while SQL/lock I/O yields. ACK exactly this
        # immutable write boundary, never a later event not included in it.
        branch_events = dst.events
        branch_count = len(branch_events)
        branch_hash = dst.event_hash(branch_count)
        branch_metadata = dst.run_metadata
        async with self.session_lock(dst.session_id):
            cached = self._execution_commits.get(dst)
            current = await self.session_metadata(dst.session_id)
            if cached and cached['revision'] == (current or {}).get('revision', 0):
                canonical, by_id = cached['canonical'], cached['by_id']
            else:
                canonical = await self.load(dst.session_id, agent=dst.agent)
                if canonical is None:
                    canonical = DST(dst.session_id, dst.agent)
                by_id = {event.event_id: event.as_dict() for event in canonical.events}
            if expected_sequence is not None and len(canonical.events) != expected_sequence:
                raise ExecutionSuperseded('Conversation changed before optional execution started')
            count = cached['count'] if cached else 0
            if cached and (branch_count < count or dst.event_hash(count) != cached['hash']):
                raise StoreConflict('Cannot edit persisted execution events')
            committed = dict(cached['committed']) if cached else {}
            changed = False
            try:
                for item in branch_events[count:]:
                    event = item.as_dict()
                    previous = by_id.get(event['event_id'])
                    if previous is not None:
                        if digest({**previous, 'sequence': None}) != digest({**event, 'sequence': None}):
                            raise StoreConflict(f"Cannot edit persisted event: {event['event_id']}")
                    else:
                        fact = Event.from_dict({**event, 'sequence': None})
                        canonical.apply_event(fact)
                        previous = fact.as_dict()
                        by_id[fact.event_id] = previous
                        changed = True
                    committed[event['event_id']] = previous
                metadata = canonical.run_metadata
                # A detached view may legitimately lack a later run's metadata,
                # but cannot delete metadata it has already committed itself.
                if cached and any(branch_metadata.get(k) != v for k, v in cached['runs'].items()):
                    raise StoreConflict('Cannot edit persisted run metadata')
                for run_id, value in branch_metadata.items():
                    if run_id in metadata:
                        if digest(metadata[run_id]) != digest(value):
                            raise StoreConflict(f'Cannot edit persisted run metadata: {run_id}')
                    else:
                        metadata[run_id] = value
                        changed = True
                canonical._run_metadata = validate_run_metadata(metadata,
                    [{'type': 'run_started', 'run_id': run} for run in canonical._run_ids])
                if changed:
                    await self.save(canonical, delivery_target=target)
            except BaseException:
                # A failed transaction may have advanced the private reducer;
                # never reuse it without reloading the committed journal.
                self._execution_commits.pop(dst, None)
                raise
            self._execution_commits[dst] = {
                'revision': canonical.revision, 'canonical': canonical, 'by_id': by_id,
                'count': branch_count, 'hash': branch_hash,
                'runs': branch_metadata, 'committed': committed}
            return deepcopy(committed)

    async def _read(self, session_id):
        """Read session metadata, snapshot, events and run metadata consistently."""
        raise NotImplementedError

    async def load(self, session_id, agent=None):
        record = await self._read(session_id)
        return self._restore(session_id, record, agent)

    @staticmethod
    def _restore(session_id, record, agent=None):
        if record is None:
            return None
        metadata, snapshot, events, runs = record
        if len(events) != metadata['last_sequence'] or digest(events) != metadata['events_hash']:
            raise ValueError('Persisted event stream does not match session metadata')
        tracker = DST.from_events(session_id, events, agent, snapshot=snapshot,
                                  revision=metadata['revision'], run_metadata=runs)
        tracker._persisted_sequence = len(events)
        return tracker

    async def inspect_state(self, session_id):
        """On-demand state view; expensive validation/replay runs off the event loop."""
        record = await self._read(session_id)
        def restore():
            tracker = self._restore(session_id, record)
            if tracker is None:
                return None
            return {'session_id': session_id, 'revision': tracker.revision,
                    'last_sequence': len(tracker.events), 'state': tracker.state_dict()}
        return await asyncio.to_thread(restore)

    async def execution_progress(self, session_id):
        """Last observed execution phase, not an executor lease/liveness claim.

        Poll only small headers. No history replay, diagnostic image bodies or
        heartbeat events are needed, including for remote service sessions.
        """
        runs = await self._event_headers(session_id, 0, 1, kinds=('run_started',), descending=True)
        if not runs:
            return {'status': 'idle', 'phase': 'idle'}
        start = runs[0]
        finished = await self._event_headers(session_id, start['sequence'], 1,
            kinds=('run_finished',), run_id=start['run_id'], descending=True)
        latest = finished[0] if finished else start
        status = latest['summary'].get('status', 'running')
        result = {'run_id': latest['run_id'], 'status': status, 'phase': status,
                  'since': latest['timestamp']}
        if latest['type'] == 'run_finished':
            result['duration_seconds'] = max(0, latest['timestamp'] - start['timestamp'])
            if latest['summary'].get('error_type'):
                result['error_type'] = latest['summary']['error_type']
            return result
        tools = await self._event_headers(session_id, latest['sequence'], 1,
            kinds=('tool_started', 'tool_result'), run_id=latest['run_id'], descending=True)
        if tools and tools[0]['type'] == 'tool_started':
            return {**result, 'phase': 'tool', 'tool': tools[0]['summary'].get('tool'),
                    'since': tools[0]['timestamp']}
        requests = await self.model_debug_headers(session_id, limit=1) if self.debug_enabled else []
        request = next((r for r in requests if r.get('run_id') == latest['run_id'] and r['status'] == 'running'), None)
        if request:
            return {**result, 'phase': 'compaction' if request['purpose'] == 'compaction' else 'model',
                    'request_id': request['request_id'], 'since': request['started_at']}
        return {**result, 'phase': 'preparing', 'since': tools[0]['timestamp'] if tools else latest['timestamp']}

    async def session_metadata(self, session_id):
        """Read a session cursor without hydrating its history."""
        raise NotImplementedError

    async def session_page(self, *, after=None, limit=100):
        """Bounded administrative metadata index; never loads event bodies."""
        if (after is not None and (not isinstance(after, str) or not after or len(after) > 255)
                or type(limit) is not int or not 1 <= limit <= 100):
            raise ValueError('Expected a session cursor and 1 <= limit <= 100')
        rows = await self._session_page(after, limit + 1)
        page = rows[:limit]
        return {'sessions': page, 'cursor': page[-1]['session_id'] if page else after,
                'has_more': len(rows) > limit}

    async def event_headers(self, session_id, *, after_sequence=0, limit=100):
        """Bounded execution index; full event payloads are fetched separately."""
        if type(after_sequence) is not int or after_sequence < 0 or type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError('Expected after_sequence >= 0 and 1 <= limit <= 1000')
        return await self._event_headers(session_id, after_sequence, limit)

    async def export_session(self, session_id):
        """Export state and history for inspection; use load() to resume execution."""
        tracker = await self.load(session_id)
        return tracker.as_dict() if tracker is not None else None

    async def snapshot(self, session_id):
        record = await self._read(session_id)
        return deepcopy(record[1]) if record else None

    async def export_conversations(self, user_id):
        return [await self.export_session(sid) for sid in await self._conversation_ids(user_id)]

    async def history(self, session_id, *, include_execution=False, offset=0, limit=100):
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError('Expected offset >= 0 and 1 <= limit <= 1000')
        return await self._query_events(session_id, kinds=None if include_execution else ('user_utter', 'bot_utter'),
                                        offset=offset, limit=limit)

    async def events(self, session_id, run_id=None, after_sequence=0, limit=100):
        if (type(after_sequence) is not int or after_sequence < 0 or
                type(limit) is not int or not 1 <= limit <= 1000):
            raise ValueError('Expected after_sequence >= 0 and 1 <= limit <= 1000')
        if run_id is not None and (not isinstance(run_id, str) or not run_id):
            raise ValueError('run_id must be a nonempty string or None')
        return await self._query_events(session_id, run_id=run_id, after_sequence=after_sequence, limit=limit)

    async def trace(self, session_id, run_id):
        from cota.trace import build_trace
        record = await self._read(session_id)
        return build_trace(record[2] if record else [], run_id)

    async def run_metadata(self, session_id, run_id):
        """Original Skill catalog for a run; optional discovery detail is Debug-only."""
        raise NotImplementedError

    async def event_by_id(self, session_id, event_id):
        """Read a single immutable fact for provenance links without restoring DST."""
        raise NotImplementedError

    async def latest_utter(self, session_ids):
        result = []
        for sid in session_ids:
            result.extend(await self._query_events(sid, kinds=('user_utter', 'bot_utter'), descending=True, limit=1))
        return result


class MemoryStore(MemoryDeliveryStore, Store):
    def __init__(self, snapshot_interval=100):
        super().__init__(snapshot_interval)
        self.sessions = {}
        self.delivery_rows = {}
        self._delivery_ordinal = 0
        self.event_rows = {}
        self.snapshots = {}
        self.model_records = {}
        self.run_records = {}

    async def run_metadata(self, session_id, run_id):
        return deepcopy(self.run_records.get(session_id, {}).get(run_id))

    async def event_by_id(self, session_id, event_id):
        return deepcopy(next((event for event in self.event_rows.get(session_id, [])
                              if event['event_id'] == event_id), None))

    async def _save_model_debug(self, session_id, request_id, data):
        record = self.model_records.setdefault((session_id, request_id), {})
        upgrade = data.get('request_stage') == 'provider' and record.get('request_stage') != 'provider'
        record.update({k: v for k, v in data.items() if k not in DEBUG_BODY_FIELDS
                       or k not in record or k == 'request' and upgrade})

    async def model_debug(self, session_id, request_id):
        return deepcopy(self.model_records.get((session_id, request_id)))

    async def _model_debug_headers(self, session_id, limit):
        rows = [data for (sid, _), data in self.model_records.items() if sid == session_id]
        rows.sort(key=lambda row: row['started_at'], reverse=True)
        return [{k: row.get(k) for k in ('request_id', 'run_id', 'purpose', 'status', 'started_at')}
                for row in rows[:limit]]

    async def save(self, dst, delivery_target=None):
        target = validate_target(delivery_target)
        data = self._write_data(dst)
        metadata, snapshot, count = self._prepare_commit(data, self.sessions.get(dst.session_id),
                                                        self.run_records.get(dst.session_id, {}))
        if metadata is None:
            self._mark_saved(dst, data, dst.revision)
            return
        new_events = deepcopy(data['events'][count:])
        new_runs = deepcopy(data['run_metadata'])
        pending = delivery_rows(dst.session_id, new_events, target)
        for ordinal, row in enumerate(pending, self._delivery_ordinal + 1):
            row['id'] = ordinal
        # Prepare all fallible data before the atomic in-memory commit; no await.
        self.event_rows.setdefault(dst.session_id, []).extend(new_events)
        self.delivery_rows.update({(row['session_id'], row['event_id']): row for row in pending})
        self._delivery_ordinal += len(pending)
        self.sessions[dst.session_id] = metadata
        self.run_records[dst.session_id] = new_runs
        if snapshot is not None:
            self.snapshots[dst.session_id] = snapshot
        self._mark_saved(dst, data, metadata['revision'])
        self._emit_saved(data, count)

    async def _read(self, session_id):
        if session_id not in self.sessions:
            return None
        return deepcopy((self.sessions[session_id], self.snapshots.get(session_id),
                         self.event_rows[session_id], self.run_records.get(session_id, {})))

    async def session_metadata(self, session_id):
        return deepcopy(self.sessions.get(session_id))

    async def _session_page(self, after, limit):
        import heapq
        keys = heapq.nsmallest(limit, (key for key in self.sessions if after is None or key > after))
        return [{key: self.sessions[sid].get(key) for key in
                 ('session_id', 'user_id', 'revision', 'last_sequence', 'updated_at')} for sid in keys]

    async def snapshot(self, session_id):
        return deepcopy(self.snapshots.get(session_id))

    async def _event_headers(self, session_id, after_sequence, limit, *, kinds=None, run_id=None, descending=False):
        # Sequence is contiguous, so this is a slice, not a full-history scan/copy.
        from itertools import islice
        stored_rows = self.event_rows.get(session_id, [])
        if kinds is None and run_id is None and not descending:
            return [event_header(e) for e in stored_rows[after_sequence:after_sequence + limit]]
        rows = (stored_rows[index] for index in (range(len(stored_rows) - 1, after_sequence - 1, -1)
                                         if descending else range(after_sequence, len(stored_rows))))
        return [event_header(e) for e in islice((e for e in rows
                if (kinds is None or e['type'] in kinds) and (run_id is None or e['run_id'] == run_id)), limit)]

    async def _conversation_ids(self, user_id):
        return [m['session_id'] for m in sorted(self.sessions.values(), key=lambda m: m['updated_at'], reverse=True)
                if m['user_id'] == user_id]

    async def _query_events(self, session_id, *, kinds=None, run_id=None, after_sequence=0,
                            offset=0, limit=None, descending=False, before_sequence=None):
        rows = [e for e in self.event_rows.get(session_id, [])
                if e['sequence'] > after_sequence and (before_sequence is None or e['sequence'] < before_sequence) and (kinds is None or e['type'] in kinds)
                and (run_id is None or e['run_id'] == run_id)]
        if descending:
            rows.reverse()
        return deepcopy(rows[offset:offset + limit if limit is not None else None])

    async def message_count(self, session_id, *, after=0, through=None, exclude_sender=None):
        return sum(1 for e in self.event_rows.get(session_id, [])
                   if e['type'] in ('user_utter', 'bot_utter') and e['sequence'] > after
                   and (through is None or e['sequence'] <= through)
                   and not (exclude_sender is not None and e['type'] == 'user_utter'
                            and (e['payload'].get('metadata') or {}).get('sender_id') == exclude_sender))

    async def unstarted_inputs(self, *, session_id=None, after=None, limit=100):
        """Bounded accepted direct work with no run_started fact; never resume tools."""
        import heapq
        def candidates():
            for sid, rows in self.event_rows.items():
                if session_id is not None and sid != session_id:
                    continue
                started = {e['payload'].get('input_event_id') for e in rows if e['type'] == 'run_started'}
                for event in rows:
                    if (event['type'] == 'user_utter' and (event['payload'].get('metadata') or {}).get('accepted')
                            and event['event_id'] not in started
                            and (after is None or (sid, event['sequence']) > tuple(after))):
                        yield {'session_id': sid, **event}
        return deepcopy(heapq.nsmallest(limit, candidates(), key=lambda e: (e['session_id'], e['sequence'])))


class SQLStore(SQLDeliveryStore, Store):
    class Base(DeclarativeBase):
        pass

    class SQLSession(Base):
        __tablename__ = 'sessions'
        session_id = sa.Column(sa.String(255), primary_key=True)
        user_id = sa.Column(sa.String(255), index=True)
        revision = sa.Column(sa.Integer, nullable=False)
        last_sequence = sa.Column(sa.Integer, nullable=False)
        events_hash = sa.Column(sa.String(64), nullable=False)
        updated_at = sa.Column(sa.Double, nullable=False)

    class SQLEvent(Base):
        __tablename__ = 'events'
        session_id = sa.Column(sa.String(255), sa.ForeignKey('sessions.session_id'), primary_key=True)
        sequence = sa.Column(sa.Integer, primary_key=True)
        event_id = sa.Column(sa.String(255), nullable=False)
        run_id = sa.Column(sa.String(255))
        type = sa.Column(sa.String(64), nullable=False)
        source = sa.Column(sa.String(64), nullable=False)
        timestamp = sa.Column(sa.Double, nullable=False)
        schema_version = sa.Column(sa.Integer, nullable=False)
        payload = sa.Column(sa.Text().with_variant(LONGTEXT(), 'mysql'), nullable=False)
        __table_args__ = (
            sa.UniqueConstraint('session_id', 'event_id'),
            sa.Index('ix_events_session_run_sequence', 'session_id', 'run_id', 'sequence'),
            sa.Index('ix_events_session_type_sequence', 'session_id', 'type', 'sequence'),
        )

    SQLDelivery = type('SQLDelivery', (Base,), {'__table__': make_delivery_table(Base.metadata)})

    class SQLSnapshot(Base):
        __tablename__ = 'session_snapshots'
        session_id = sa.Column(sa.String(255), sa.ForeignKey('sessions.session_id'), primary_key=True)
        last_sequence = sa.Column(sa.Integer, nullable=False)
        data = sa.Column(sa.Text().with_variant(LONGTEXT(), 'mysql'), nullable=False)

    class SQLModelDebug(Base):
        __tablename__ = 'model_debug'
        session_id = sa.Column(sa.String(255), primary_key=True)
        request_id = sa.Column(sa.String(255), primary_key=True)
        run_id = sa.Column(sa.String(255))
        purpose = sa.Column(sa.String(64), nullable=False)
        status = sa.Column(sa.String(32), nullable=False)
        started_at = sa.Column(sa.Double, nullable=False)
        data = sa.Column(sa.Text().with_variant(LONGTEXT(), 'mysql'), nullable=False)
        __table_args__ = (sa.Index('ix_model_debug_session_time', 'session_id', 'started_at'),)

    class SQLRunMetadata(Base):
        __tablename__ = 'run_metadata'
        session_id = sa.Column(sa.String(255), sa.ForeignKey('sessions.session_id'), primary_key=True)
        run_id = sa.Column(sa.String(255), primary_key=True)
        data = sa.Column(sa.Text().with_variant(LONGTEXT(), 'mysql'), nullable=False)

    class SQLModelDebugBody(Base):
        """Large diagnostics are independent of frequently changing status."""
        __tablename__ = 'model_debug_bodies'
        session_id = sa.Column(sa.String(255), primary_key=True)
        request_id = sa.Column(sa.String(255), primary_key=True)
        field = sa.Column(sa.String(32), primary_key=True)
        stage = sa.Column(sa.String(32), nullable=False)
        data = sa.Column(sa.Text().with_variant(LONGTEXT(), 'mysql'), nullable=False)

    def __init__(self, dialect='sqlite', host=None, port=None, db='cota.db',
                 username=None, password=None, login_db=None, query=None, snapshot_interval=100):
        super().__init__(snapshot_interval)
        url = sa.engine.URL.create(dialect, username=username, password=password,
                                   host=host, port=port, database=login_db or db, query=query or {})
        options = {}
        if dialect.startswith('sqlite'):
            options['connect_args'] = {'check_same_thread': False}
            if db == ':memory:':
                options['poolclass'] = sa.pool.StaticPool
        self.engine = sa.create_engine(url, **options)
        if login_db:
            self._create_database(self.engine, db)
            self.engine.dispose()
            self.engine = sa.create_engine(url.set(database=db), **options)
        try:
            inspector = sa.inspect(self.engine)
            for table in self.Base.metadata.sorted_tables:
                if inspector.has_table(table.name):
                    existing = {column['name'] for column in inspector.get_columns(table.name)}
                    missing = set(table.c.keys()) - existing
                    if missing:
                        raise ValueError(f'Incompatible Store schema: {table.name}; missing columns: {", ".join(sorted(missing))}')
            self.Base.metadata.create_all(self.engine)
        except Exception:
            self.engine.dispose()
            raise
        self._io_lock = asyncio.Lock()

    @staticmethod
    def _create_database(engine, db):
        import re
        if not re.fullmatch(r'[a-zA-Z0-9_-]+', db):
            raise ValueError(f'Invalid database name: {db}')
        from psycopg2 import sql
        with engine.connect().execution_options(isolation_level='AUTOCOMMIT') as conn:
            cursor = conn.connection.cursor()
            try:
                cursor.execute('SELECT 1 FROM pg_catalog.pg_database WHERE datname = %s', (db,))
                if not cursor.fetchone():
                    cursor.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(db)))
            finally:
                cursor.close()

    async def _io(self, func, *args):
        # Also serializes access to the single connection used by in-memory SQLite.
        # Drain a cancelled transaction before releasing this local lock.
        async with self._io_lock:
            task = asyncio.create_task(asyncio.to_thread(func, *args))
            try:
                return await asyncio.shield(task)
            except asyncio.CancelledError:
                await task
                raise

    async def save(self, dst, delivery_target=None):
        data = self._write_data(dst)
        target = validate_target(delivery_target)
        revision = await self._io(self._save, data, target)
        self._mark_saved(dst, data, revision)

    async def _save_model_debug(self, session_id, request_id, data):
        def write():
            table = self.SQLModelDebug.__table__
            bodies = self.SQLModelDebugBody.__table__
            match = (table.c.session_id == session_id, table.c.request_id == request_id)
            body_match = (bodies.c.session_id == session_id, bodies.c.request_id == request_id)
            with self.engine.begin() as conn:
                raw = conn.execute(sa.select(table.c.data).where(*match)).scalar_one_or_none()
                previous = json.loads(raw) if raw is not None else {}
                stages = dict(conn.execute(sa.select(bodies.c.field, bodies.c.stage).where(*body_match)).all())
                stage = data.get('request_stage', previous.get('request_stage', 'adapter'))
                for field in DEBUG_BODY_FIELDS:
                    if field not in data:
                        continue
                    upgrade = field == 'request' and stage == 'provider' and stages.get(field) != 'provider'
                    if field in stages and not upgrade:
                        continue
                    payload = json.dumps(data[field], ensure_ascii=False, allow_nan=False)
                    if field in stages:
                        conn.execute(bodies.update().where(*body_match, bodies.c.field == field)
                                     .values(stage=stage, data=payload))
                    else:
                        conn.execute(bodies.insert().values(session_id=session_id, request_id=request_id,
                                     field=field, stage=stage, data=payload))
                previous.update({k: v for k, v in data.items() if k not in DEBUG_BODY_FIELDS})
                small = {k: v for k, v in previous.items() if k not in DEBUG_BODY_FIELDS or k not in data}
                values = {k: small.get(k) for k in ('run_id', 'purpose', 'status', 'started_at')}
                values['data'] = json.dumps(small, ensure_ascii=False, allow_nan=False)
                if raw is None:
                    conn.execute(table.insert().values(session_id=session_id, request_id=request_id, **values))
                else:
                    conn.execute(table.update().where(*match).values(**values))
        await self._io(write)

    async def model_debug(self, session_id, request_id):
        def read():
            table = self.SQLModelDebug.__table__
            bodies = self.SQLModelDebugBody.__table__
            with self.engine.connect() as conn:
                raw = conn.execute(sa.select(table.c.data).where(table.c.session_id == session_id,
                    table.c.request_id == request_id)).scalar_one_or_none()
                if raw is None:
                    return None
                record = json.loads(raw)
                record.update({field: json.loads(data) for field, data in conn.execute(
                    sa.select(bodies.c.field, bodies.c.data).where(bodies.c.session_id == session_id,
                                                                  bodies.c.request_id == request_id))})
                return record
        return await self._io(read)

    async def _model_debug_headers(self, session_id, limit):
        def read():
            table = self.SQLModelDebug.__table__
            with self.engine.connect() as conn:
                return [dict(row) for row in conn.execute(sa.select(table.c.request_id, table.c.run_id,
                    table.c.purpose, table.c.status, table.c.started_at).where(table.c.session_id == session_id)
                    .order_by(table.c.started_at.desc()).limit(limit)).mappings()]
        return await self._io(read)

    async def run_metadata(self, session_id, run_id):
        def read():
            table = self.SQLRunMetadata.__table__
            with self.engine.connect() as conn:
                raw = conn.execute(sa.select(table.c.data).where(
                    table.c.session_id == session_id, table.c.run_id == run_id)).scalar_one_or_none()
                return json.loads(raw) if raw is not None else None
        return await self._io(read)

    async def event_by_id(self, session_id, event_id):
        def read():
            table = self.SQLEvent.__table__
            with self.engine.connect() as conn:
                row = conn.execute(sa.select(table).where(
                    table.c.session_id == session_id, table.c.event_id == event_id)).mappings().first()
                return self._event(row) if row is not None else None
        return await self._io(read)

    def _read_runs(self, conn, session_id):
        table = self.SQLRunMetadata.__table__
        return {row.run_id: json.loads(row.data) for row in conn.execute(
            sa.select(table.c.run_id, table.c.data).where(table.c.session_id == session_id))}

    @staticmethod
    def _decode_snapshot(raw):
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (ValueError, TypeError):
            return {}  # Invalid cache: load falls back to the event stream.

    def _save(self, data, delivery_target=None):
        sessions, snapshots, events = self.SQLSession.__table__, self.SQLSnapshot.__table__, self.SQLEvent.__table__
        sid = data['session_id']
        with self.engine.begin() as conn:
            old = conn.execute(sa.select(sessions).where(sessions.c.session_id == sid)).mappings().first()
            old_runs = self._read_runs(conn, sid)
            metadata, snapshot, count = self._prepare_commit(data, old, old_runs)
            if metadata is None:
                return old['revision']
            if old:
                result = conn.execute(sessions.update().where(sessions.c.session_id == sid,
                                      sessions.c.revision == data['revision']).values(**metadata))
                if result.rowcount != 1:
                    raise StoreConflict(f'Concurrent session revision: {sid}')
            else:
                try:
                    conn.execute(sessions.insert().values(**metadata))
                except sa.exc.IntegrityError as exc:
                    raise StoreConflict(f'Concurrent session revision: {sid}') from exc
            rows = [{**e, 'session_id': sid, 'payload': json.dumps(e['payload'], ensure_ascii=False, allow_nan=False)}
                    for e in data['events'][count:]]
            if rows:
                conn.execute(events.insert(), rows)
            pending = delivery_rows(sid, data['events'][count:], delivery_target)
            if pending:
                conn.execute(self.SQLDelivery.__table__.insert(), pending)
            new_runs = [{'session_id': sid, 'run_id': run,
                         'data': json.dumps(value, ensure_ascii=False, allow_nan=False)}
                        for run, value in data['run_metadata'].items() if run not in old_runs]
            if new_runs:
                conn.execute(self.SQLRunMetadata.__table__.insert(), new_runs)
            if snapshot is not None:
                # The session revision update above serializes snapshot writers.
                conn.execute(snapshots.delete().where(snapshots.c.session_id == sid))
                conn.execute(snapshots.insert().values(session_id=sid, last_sequence=snapshot['last_sequence'],
                                                      data=json.dumps(snapshot, ensure_ascii=False, allow_nan=False)))
        self._emit_saved(data, count)
        return metadata['revision']

    @staticmethod
    def _event(row):
        data = dict(row)
        data.pop('session_id')
        data['payload'] = json.loads(data['payload'])
        return data

    async def _read(self, session_id):
        return await self._io(self._read_sync, session_id)

    def _read_sync(self, session_id):
        sessions, snapshots, events = self.SQLSession.__table__, self.SQLSnapshot.__table__, self.SQLEvent.__table__
        # All SELECTs must see one commit, including on PostgreSQL's default
        # READ COMMITTED connections. Set isolation before SQL autobegins.
        with self.engine.connect() as conn:
            if self.engine.dialect.name == 'sqlite':
                conn.exec_driver_sql('BEGIN')
            elif self.engine.dialect.name in ('mysql', 'postgresql'):
                conn = conn.execution_options(isolation_level='REPEATABLE READ')
            with conn.begin() if not conn.in_transaction() else nullcontext():
                metadata = conn.execute(sa.select(sessions).where(sessions.c.session_id == session_id)).mappings().first()
                if metadata is None:
                    return None
                raw = conn.execute(sa.select(snapshots.c.data).where(snapshots.c.session_id == session_id)).scalar_one_or_none()
                rows = conn.execute(sa.select(events).where(events.c.session_id == session_id,
                                    events.c.sequence <= metadata['last_sequence']).order_by(events.c.sequence)).mappings()
                return (dict(metadata), self._decode_snapshot(raw), [self._event(row) for row in rows],
                        self._read_runs(conn, session_id))

    async def _conversation_ids(self, user_id):
        def query():
            table = self.SQLSession.__table__
            with self.engine.connect() as conn:
                return list(conn.scalars(sa.select(table.c.session_id).where(table.c.user_id == user_id).order_by(table.c.updated_at.desc())))
        return await self._io(query)

    async def session_metadata(self, session_id):
        def query():
            table = self.SQLSession.__table__
            with self.engine.connect() as conn:
                row = conn.execute(sa.select(table).where(table.c.session_id == session_id)).mappings().first()
                return dict(row) if row else None
        return await self._io(query)

    async def _session_page(self, after, limit):
        def query():
            table = self.SQLSession.__table__
            statement = sa.select(table.c.session_id, table.c.user_id, table.c.revision,
                                  table.c.last_sequence, table.c.updated_at)
            if after is not None:
                statement = statement.where(table.c.session_id > after)
            with self.engine.connect() as conn:
                return [dict(row) for row in conn.execute(
                    statement.order_by(table.c.session_id).limit(limit)).mappings()]
        return await self._io(query)

    async def snapshot(self, session_id):
        def query():
            table = self.SQLSnapshot.__table__
            with self.engine.connect() as conn:
                raw = conn.execute(sa.select(table.c.data).where(table.c.session_id == session_id)).scalar_one_or_none()
                return self._decode_snapshot(raw)
        return await self._io(query)

    async def _event_headers(self, session_id, after_sequence, limit, *, kinds=None, run_id=None, descending=False):
        def query():
            table = self.SQLEvent.__table__
            columns = [c for c in table.c if c.name not in ('session_id', 'payload')]
            # Extract bounded scalars in SQL: large model/tool bodies never cross
            # the database connection during polling (SQLite, MySQL, PostgreSQL).
            payload = (sa.cast(table.c.payload, sa.JSON) if self.engine.dialect.name == 'postgresql'
                       else sa.type_coerce(table.c.payload, sa.JSON))
            for key in EVENT_SUMMARY_FIELDS:
                value = payload['resource'][key.removeprefix('resource_')] if key.startswith('resource_') else payload[key]
                scalar = value.as_string()
                # Only display text is shortened. IDs must stay exact for links
                # and call grouping, including long provider-generated call IDs.
                scalar = sa.func.substr(scalar, 1, 200) if key == 'text' else sa.cast(scalar, sa.Text)
                columns.append(scalar.label('summary_' + key))
            stmt = sa.select(*columns).where(table.c.session_id == session_id,
                    table.c.sequence > after_sequence)
            if kinds is not None:
                stmt = stmt.where(table.c.type.in_(kinds))
            if run_id is not None:
                stmt = stmt.where(table.c.run_id == run_id)
            stmt = stmt.order_by(table.c.sequence.desc() if descending else table.c.sequence).limit(limit)
            with self.engine.connect() as conn:
                result = []
                for row in conn.execute(stmt).mappings():
                    header = dict(row)
                    header['summary'] = {key: value for key in EVENT_SUMMARY_FIELDS
                        if (value := header.pop('summary_' + key)) is not None}
                    result.append(header)
                return result
        return await self._io(query)

    async def _query_events(self, session_id, *, kinds=None, run_id=None, after_sequence=0,
                            offset=0, limit=None, descending=False, before_sequence=None):
        def query():
            table = self.SQLEvent.__table__
            stmt = sa.select(table).where(table.c.session_id == session_id, table.c.sequence > after_sequence)
            if before_sequence is not None:
                stmt = stmt.where(table.c.sequence < before_sequence)
            if kinds is not None:
                stmt = stmt.where(table.c.type.in_(kinds))
            if run_id is not None:
                stmt = stmt.where(table.c.run_id == run_id)
            stmt = stmt.order_by(table.c.sequence.desc() if descending else table.c.sequence).offset(offset)
            if limit is not None:
                stmt = stmt.limit(limit)
            with self.engine.connect() as conn:
                return [self._event(row) for row in conn.execute(stmt).mappings()]
        return await self._io(query)

    async def message_count(self, session_id, *, after=0, through=None, exclude_sender=None):
        def query():
            table = self.SQLEvent.__table__
            stmt = sa.select(sa.func.count()).select_from(table).where(
                table.c.session_id == session_id, table.c.sequence > after,
                table.c.type.in_(('user_utter', 'bot_utter')))
            if through is not None:
                stmt = stmt.where(table.c.sequence <= through)
            if exclude_sender is not None:
                payload = (sa.cast(table.c.payload, sa.JSON) if self.engine.dialect.name == 'postgresql'
                           else sa.type_coerce(table.c.payload, sa.JSON))
                sender = payload['metadata']['sender_id'].as_string()
                stmt = stmt.where(sa.or_(table.c.type != 'user_utter', sender.is_(None), sender != exclude_sender))
            with self.engine.connect() as conn:
                return conn.scalar(stmt)
        return await self._io(query)

    async def unstarted_inputs(self, *, session_id=None, after=None, limit=100):
        def query():
            table = self.SQLEvent.__table__
            runs = table.alias('started_runs')
            def payload(column):
                return (sa.cast(column, sa.JSON) if self.engine.dialect.name == 'postgresql'
                        else sa.type_coerce(column, sa.JSON))
            started = sa.exists(sa.select(1).where(runs.c.session_id == table.c.session_id,
                runs.c.type == 'run_started', payload(runs.c.payload)['input_event_id'].as_string() == table.c.event_id))
            stmt = sa.select(table).where(table.c.type == 'user_utter',
                payload(table.c.payload)['metadata']['accepted'].as_boolean().is_(True), ~started)
            if session_id is not None:
                stmt = stmt.where(table.c.session_id == session_id)
            if after is not None:
                stmt = stmt.where(sa.or_(table.c.session_id > after[0],
                    sa.and_(table.c.session_id == after[0], table.c.sequence > after[1])))
            stmt = stmt.order_by(table.c.session_id, table.c.sequence).limit(limit)
            with self.engine.connect() as conn:
                return [{'session_id': row['session_id'], **self._event(row)} for row in conn.execute(stmt).mappings()]
        return await self._io(query)
