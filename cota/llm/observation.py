"""Model provenance, failure logs and optional independent request diagnostics."""
import asyncio
import logging
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
import time
from uuid import uuid4

from cota.events.context import assistant_message
from .metrics import request_metrics, usage_metrics

logger = logging.getLogger(__name__)

_scope = ContextVar('cota_model_trace', default=None)
_active = ContextVar('cota_model_call', default=None)
_purpose = ContextVar('cota_model_purpose', default='dialogue')


@contextmanager
def model_trace(recorder, checkpoint):
    token = _scope.set((recorder, checkpoint))
    try:
        yield
    finally:
        _scope.reset(token)


@contextmanager
def model_purpose(purpose):
    token = _purpose.set(purpose)
    try:
        yield
    finally:
        _purpose.reset(token)


async def observe_model_call(callback, request, *, llm=None):
    scope = _scope.get()
    if scope is None or _active.get() is not None:
        return await callback(**request)
    recorder, checkpoint = scope
    run_id = recorder.dst.execution.get('run_id')
    ordinal = recorder.next_request_sequence()
    metadata = {'request_id': uuid4().hex, 'request_sequence': ordinal, 'purpose': _purpose.get(), 'model': llm}
    if metadata['purpose'] == 'dialogue':
        metadata['policy'] = deepcopy(recorder.policy)
    # Core state must be committed before invoking a provider; full request bodies
    # are diagnostics and are deliberately not part of this checkpoint.
    await checkpoint()
    diagnostic = {**metadata, 'run_id': run_id, 'started_at': time.time(), 'status': 'running'}
    if recorder.debug_enabled:
        diagnostic['request'] = deepcopy(request)
        if metadata['purpose'] == 'dialogue':
            diagnostic['preparation'] = deepcopy(recorder.preparation)
    state = {'recorder': recorder, 'diagnostic': diagnostic}
    token = _active.set(state)
    started = time.perf_counter()
    try:
        await recorder.save_debug(metadata['request_id'], diagnostic)
        try:
            response = await callback(**request)
            duration_ms = (time.perf_counter() - started) * 1000
            message = assistant_message(response, int(time.time() * 1000)) if metadata['purpose'] == 'dialogue' else None
        except BaseException as error:
            failure = {**metadata, 'error_type': type(error).__name__, 'error': str(error),
                       'status': 'interrupted' if isinstance(error, asyncio.CancelledError) else 'failed',
                       'duration_ms': (time.perf_counter() - started) * 1000}
            logger.log(logging.WARNING if isinstance(error, asyncio.CancelledError) else logging.ERROR,
                       'Model request %s session=%s run=%s request=%s sequence=%s purpose=%s model=%s '
                       'duration_ms=%.1f error_type=%s',
                       failure['status'], recorder.dst.session_id, run_id, metadata['request_id'],
                       ordinal, metadata['purpose'], llm, failure['duration_ms'], failure['error_type'],
                       exc_info=True)
            diagnostic.update(failure)
            await recorder.save_debug(metadata['request_id'], diagnostic)
            raise
        diagnostic.update(status='completed', duration_ms=duration_ms)
        if recorder.debug_enabled:
            diagnostic['response'] = deepcopy(response)
        await recorder.save_debug(metadata['request_id'], diagnostic)
        if message is not None:
            # The next bot/tool_started carries this decision. Pi must await its
            # event callback's checkpoint before executing any tool side effect.
            recorder.stage_model(message, {**metadata, 'duration_ms': duration_ms}, diagnostic)
            return {**response, '_cota_message': message}
        return response
    finally:
        _active.reset(token)


async def provider_request(parameters):
    """Keep the final SDK/body request, replacing the earlier adapter request."""
    state = _active.get()
    if state is not None and state['recorder'].debug_enabled:
        state['diagnostic']['request'] = deepcopy(parameters)
        state['diagnostic']['request_size'] = request_metrics(parameters)
        state['diagnostic']['request_stage'] = 'provider'
        await state['recorder'].save_debug(state['diagnostic']['request_id'], state['diagnostic'])


def provider_response(response):
    state = _active.get()
    if state is not None and state['recorder'].debug_enabled:
        state['diagnostic']['provider_response'] = (response.model_dump(mode='json')
            if hasattr(response, 'model_dump') else deepcopy(response))
        provider = state['diagnostic']['provider_response']
        if isinstance(provider, dict):
            measured = usage_metrics(provider)
            if measured is not None:
                state['diagnostic']['usage'] = measured
