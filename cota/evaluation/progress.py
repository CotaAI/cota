"""Optional progress observer; never part of Bot events, prompts or score artifacts."""
import asyncio
from contextlib import asynccontextmanager, suppress
import logging
from time import monotonic


class Progress:
    def __init__(self, callback=None, *, interval=15):
        self.callback = callback
        self.interval = interval
        self.context = {}
        self.started = monotonic()

    def emit(self, event, **fields):
        if self.callback is not None:
            try:
                self.callback({'event': event, **self.context, **fields})
            except Exception as error:
                # A display/observer failure must not change evaluation results.
                logging.getLogger(__name__).warning('Evaluation progress observer failed: %s', type(error).__name__)

    def case(self, case, index, total):
        self.context = {'index': index, 'total': total, 'case_id': case['id'],
                        'repetition': case['repetition'], 'turns': len(case['turns'])}
        self.emit('case_started')

    @asynccontextmanager
    async def stage(self, phase, **fields):
        started = monotonic()
        self.emit('stage_started', phase=phase, **fields)

        async def heartbeat():
            while True:
                await asyncio.sleep(self.interval)
                self.emit('heartbeat', phase=phase, elapsed_seconds=monotonic() - started, **fields)

        task = asyncio.create_task(heartbeat()) if self.callback else None
        try:
            yield
        finally:
            if task:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

    def finish(self, result):
        self.context = {}
        self.emit('run_finished', status=result['status'], summary=result['summary'],
                  elapsed_seconds=monotonic() - self.started)
