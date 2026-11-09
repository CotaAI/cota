"""Readable projection of committed events; Store remains authoritative."""
import json
import logging
from pathlib import Path
from threading import Lock

logger = logging.getLogger('cota.execution')
_SUMMARIES = {'run_started', 'run_finished', 'bot_utter',
              'tool_started', 'tool_result', 'context_compaction'}


class ExecutionLog:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)
        self._lock = Lock()

    def write(self, session_id, events):
        chunks = []
        for event in events:
            payload = event['payload']
            header = (f"session={session_id} run={event.get('run_id')} "
                      f"seq={event['sequence']} event={event['event_id']} type={event['type']} "
                      f"request={payload.get('request_id', payload.get('llm', {}).get('request_id', '-'))} "
                      f"call={payload.get('tool_call_id', '-')}")
            chunks.append('\n' + '=' * 80 + '\n' + header + '\n' +
                          json.dumps(event, ensure_ascii=False, indent=2) + '\n')
        if chunks:
            with self._lock, self.path.open('a', encoding='utf-8') as output:
                output.write(''.join(chunks))


def emit_committed(session_id, events, debug_log=None):
    for event in events:
        if event['type'] not in _SUMMARIES:
            continue
        payload = event['payload']
        level = logging.ERROR if payload.get('status') == 'failed' else logging.INFO
        logger.log(level, 'session=%s run=%s seq=%s %s request=%s call=%s tool=%s status=%s duration_ms=%s',
                   session_id, event.get('run_id'), event['sequence'], event['type'],
                   payload.get('request_id', payload.get('llm', {}).get('request_id', '-')),
                   payload.get('tool_call_id', '-'), payload.get('tool', '-'),
                   payload.get('status', '-'), payload.get('duration_ms', payload.get('llm', {}).get('duration_ms', '-')))
    if debug_log:
        try:
            debug_log.write(session_id, events)
        except Exception as error:
            # A debug projection failure must never turn a committed tool into a failed transaction.
            logger.error('Cannot append execution log %s (%s); events remain in Store',
                         debug_log.path, type(error).__name__)
