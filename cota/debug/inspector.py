"""Read projections of Shell or service sessions without invoking the Agent."""
from pathlib import Path
import logging


logger = logging.getLogger(__name__)


class ModelDiagnosticsUnavailable(LookupError):
    """Expected when Debug was off or a carrier reference cannot be resolved."""


class Inspector:
    def __init__(self, agent, session_id=None, live_tracker=None):
        self.agent = agent
        self.store = agent.store
        self.session_id = session_id
        self.live_tracker = live_tracker or (lambda: None)
        self.bot_name = agent.name
        self.log_path = str(Path(agent.workspace_path) / 'debug' / 'execution.log')

    async def info(self):
        metadata = await self.store.session_metadata(self.session_id) if self.session_id else None
        return {'bot': self.bot_name, 'session_id': self.session_id,
                'store': type(self.store).__name__, 'metadata': metadata,
                'progress': await self.store.execution_progress(self.session_id) if self.session_id else None,
                'log_path': self.log_path}

    def for_session(self, session_id):
        if not isinstance(session_id, str) or not session_id.strip() or len(session_id) > 255:
            raise ValueError('session_id must contain 1–255 characters')
        return Inspector(self.agent, session_id)

    async def deliveries(self, after=0, limit=100):
        """Inspect bounded delivery rows referenced by persisted Bot facts."""
        events = await self.store.events(self.session_id, after_sequence=after, limit=limit)
        rows = []
        for event in events:
            if event['type'] == 'bot_utter':
                row = await self.store.delivery(self.session_id, event['event_id'])
                if row is not None:
                    rows.append(row)
        return {'deliveries': rows, 'cursor': events[-1]['sequence'] if events else after,
                'has_more': len(events) == limit}

    async def events(self, after=0, limit=100):
        headers = await self.store.event_headers(self.session_id, after_sequence=after, limit=limit)
        # Cursor follows returned rows, never a newer separately read session cursor.
        return {'events': headers, 'after_sequence': headers[-1]['sequence'] if headers else after,
                'has_more': len(headers) == limit}

    async def event(self, sequence):
        if type(sequence) is not int or sequence < 1:
            raise ValueError('sequence must be positive')
        events = await self.store.events(self.session_id, after_sequence=sequence - 1, limit=1)
        if not events or events[0]['sequence'] != sequence:
            raise LookupError('Event not found')
        return events[0]

    async def event_view(self, sequence):
        """Join optional diagnostics for display only; never change persisted facts."""
        event = await self.event(sequence)
        try:
            request_id = await self._event_request_id(event)
            record = await self.store.model_debug(self.session_id, request_id)
            if record is None:
                return event
            # Remove only identical envelope/source metadata. Full request and
            # response bodies remain intact, including provider-specific fields.
            source = event['payload'].get('llm', {})
            repeated = {key: source[key] for key in (
                'request_id', 'request_sequence', 'model', 'purpose', 'policy',
                'duration_ms', 'status', 'error', 'error_type',
            ) if key in source}
            repeated.update({key: event[key] for key in ('event_id', 'run_id', 'session_id') if key in event})
            debug = {key: value for key, value in record.items()
                     if key not in repeated or value != repeated[key]}
            return {**event, 'debug': debug}
        except ModelDiagnosticsUnavailable:
            return event
        except Exception as error:
            logger.warning('Event diagnostics unavailable (%s)', type(error).__name__)
            return {**event, 'debug': {'error': '模型诊断读取失败，请重试；原始事件仍可查看。'}}

    async def _event_request_id(self, event):
        seen = set()
        while event['event_id'] not in seen:
            seen.add(event['event_id'])
            payload, kind = event['payload'], event['type']
            if kind in ('bot_utter', 'tool_started'):
                llm = payload.get('llm')
                request_id = llm.get('request_id') if isinstance(llm, dict) else None
            else:
                break
            if isinstance(request_id, str) and request_id:
                return request_id
            if kind == 'bot_utter' and payload.get('tool_event_id'):
                reference, allowed_types = payload['tool_event_id'], ('tool_started',)
            elif kind in ('bot_utter', 'tool_started') and payload.get('llm_event_id'):
                reference, allowed_types = payload['llm_event_id'], ('bot_utter', 'tool_started')
            else:
                break
            if not isinstance(reference, str) or reference in seen:
                break
            owner = await self.store.event_by_id(self.session_id, reference)
            if (owner is None or owner['run_id'] != event['run_id'] or
                    owner['sequence'] >= event['sequence'] or owner['type'] not in allowed_types):
                break
            event = owner
        raise ModelDiagnosticsUnavailable()

    async def model_debug(self, request_id=None, *, event_sequence=None):
        if event_sequence is not None:
            if request_id is not None:
                raise ValueError('Use request_id or event_sequence, not both')
            request_id = await self._event_request_id(await self.event(event_sequence))
        if request_id is None:
            return {'records': await self.store.model_debug_headers(self.session_id)}
        record = await self.store.model_debug(self.session_id, request_id)
        if record is None:
            raise ModelDiagnosticsUnavailable()
        return record

    async def run_metadata(self, run_id):
        if not isinstance(run_id, str) or not run_id:
            raise ValueError('run_id is required')
        record = await self.store.run_metadata(self.session_id, run_id)
        if record is None:
            raise LookupError('Skill directory not recorded for this run')
        return {'run_id': run_id, **record}

    async def state(self, source='stored'):
        result = {'source': source, 'session_id': self.session_id, 'available': False}
        if source == 'stored':
            saved = await self.store.inspect_state(self.session_id)
            if saved is not None:
                result.update(saved, available=True)
        elif source == 'live':
            # No await while copying the live tracker. The getter is Shell-owned;
            # the inspector never retains or mutates this reference.
            dst = self.live_tracker()
            if dst is not None and dst.session_id == self.session_id:
                result.update(available=True, revision=dst.revision,
                              last_sequence=len(dst.events), state=dst.state_dict())
        elif source == 'snapshot':
            snapshot = await self.store.snapshot(self.session_id)
            if snapshot is not None:
                result.update(available=True, last_sequence=snapshot.get('last_sequence'),
                              state=snapshot.get('state'), snapshot=snapshot)
        else:
            raise ValueError('source must be stored, live or snapshot')
        return result
