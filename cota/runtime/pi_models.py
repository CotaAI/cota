"""Observe Node provider calls without owning their transport or execution loop."""
from copy import deepcopy
import logging
import time
from uuid import uuid4

from cota.llm.metrics import request_metrics
from cota.events.assistant import public_content

logger = logging.getLogger(__name__)


def public_message(message):
    """Project public text/tool decisions into Cota's stable event contract."""
    result = deepcopy(message)
    result['content'] = public_content(message.get('content', []))
    if result['content'] != message.get('content', []) or message.get('responseId'):
        # Only provider-required continuation adds a private protocol artifact.
        # Ordinary text/tool messages keep the existing compact event shape.
        result['cotaContinuation'] = {k: deepcopy(v) for k, v in message.items() if k in
            ('role', 'content', 'api', 'provider', 'model', 'responseId', 'responseModel',
             'usage', 'stopReason', 'timestamp', 'thinkingLevel')}
    return result


def _response(message):
    """Keep the Debug response view shared with Python auxiliary providers."""
    return {'content': '\n'.join(b['text'] for b in message['content'] if b['type'] == 'text'),
            'tool_calls': [{'id': b['id'], 'type': 'function', 'function': {
                'name': b['name'], 'arguments': b['arguments']}}
                for b in message['content'] if b['type'] == 'toolCall'],
            'usage': message.get('usage', {}), 'finish_reason': message.get('stopReason')}


class PiModelObserver:
    def __init__(self, recorder, checkpoint):
        self.recorder, self.checkpoint = recorder, checkpoint
        self.active = {}
        self.last_error_type = None

    async def begin(self, payload):
        self.last_error_type = None
        purpose = payload.get('purpose')
        if purpose not in ('dialogue', 'compaction'):
            raise ValueError('Unknown native model purpose')
        if self.active:
            raise ValueError('A native provider request is already active')
        metadata = {'request_id': uuid4().hex, 'request_sequence': self.recorder.next_request_sequence(),
                    'purpose': purpose, 'model': payload['model']}
        if purpose == 'dialogue':
            metadata['policy'] = deepcopy(self.recorder.policy)
        await self.checkpoint()
        diagnostic = {**metadata, 'run_id': self.recorder.dst.execution.get('run_id'),
                      'started_at': time.time(), 'status': 'running'}
        if self.recorder.debug_enabled and purpose == 'dialogue':
            diagnostic['preparation'] = deepcopy(self.recorder.preparation)
            diagnostic['preparation']['context_budget'] = payload.get('contextBudget', {})
        self.active[metadata['request_id']] = (metadata, diagnostic, time.perf_counter())
        await self.recorder.save_debug(metadata['request_id'], diagnostic)
        return {'request_id': metadata['request_id'], 'debug': self.recorder.debug_enabled}

    def _get(self, payload):
        try:
            return self.active[payload['request_id']]
        except KeyError:
            raise ValueError('Unknown or completed native model request') from None

    async def observe(self, payload):
        _, diagnostic, _ = self._get(payload)
        if self.recorder.debug_enabled and payload['kind'] == 'request':
            diagnostic.update(request=deepcopy(payload['request']), request_stage='provider',
                              request_size=request_metrics(payload['request']))
        elif payload['kind'] == 'transport':
            diagnostic['transport'] = deepcopy(payload['transport'])
            attempt = next(iter(reversed(payload['transport'].get('attempts', []))), {})
            logger.info('Native model HTTP request=%s attempt=%s status=%s status_code=%s elapsed_ms=%s',
                        payload['request_id'], attempt.get('number'), attempt.get('status'),
                        attempt.get('status_code'), attempt.get('headers_ms', attempt.get('started_ms')))
        await self.recorder.save_debug(payload['request_id'], diagnostic)
        return {}

    async def complete(self, payload):
        metadata, diagnostic, _ = self._get(payload)
        message = public_message(payload['message'])
        if message.get('stopReason') not in ('stop', 'toolUse', 'length'):
            raise ValueError('An incomplete native response cannot become an assistant decision')
        diagnostic.update(status='completed', duration_ms=payload['duration_ms'])
        if payload.get('transport'):
            diagnostic['transport'] = deepcopy(payload['transport'])
        if self.recorder.debug_enabled:
            diagnostic['response'] = _response(message)
            diagnostic['provider_response'] = deepcopy(payload['message'])
            usage = message.get('usage', {})
            diagnostic['usage'] = {'prompt_tokens': sum(usage.get(k, 0) for k in ('input', 'cacheRead', 'cacheWrite')),
                                   'completion_tokens': usage.get('output', 0),
                                   'total_tokens': usage.get('totalTokens', 0)}
        await self.recorder.save_debug(metadata['request_id'], diagnostic)
        if metadata['purpose'] == 'dialogue':
            self.recorder.stage_model(message, {**metadata, 'duration_ms': payload['duration_ms']}, diagnostic)
        self.active.pop(metadata['request_id'])
        logger.info('Native model completed request=%s model=%s duration_ms=%.1f',
                    metadata['request_id'], metadata['model'], payload['duration_ms'])
        return {}

    async def fail(self, payload):
        metadata, diagnostic, started = self._get(payload)
        self.last_error_type = payload.get('error_type', 'ModelCallError')
        diagnostic.update(status='interrupted' if payload.get('error_type') in ('AbortError', 'CancelledError') else 'failed',
                          error_type=payload.get('error_type', 'ModelCallError'),
                          duration_ms=payload.get('duration_ms', (time.perf_counter() - started) * 1000))
        if self.recorder.debug_enabled:
            diagnostic['error'] = payload.get('error', '')
        if payload.get('transport'):
            diagnostic['transport'] = deepcopy(payload['transport'])
        await self.recorder.save_debug(metadata['request_id'], diagnostic)
        self.active.pop(metadata['request_id'])
        logger.error('Native model %s request=%s model=%s duration_ms=%.1f error_type=%s',
                     diagnostic['status'], metadata['request_id'], metadata['model'],
                     diagnostic['duration_ms'], diagnostic['error_type'])
        return {}

    async def interrupt(self, error):
        for request_id in list(self.active):
            await self.fail({'request_id': request_id,
                             'error_type': getattr(error, 'error_type', None) or type(error).__name__,
                             'error': str(error)})
