"""Acknowledged JSON-lines transport to a pinned, stateless Pi Core worker."""
import asyncio
import json
import logging
from .pi_distribution import resolve_runtime

MAX_FRAME_BYTES = 128 * 1024 * 1024
PIPE_CHUNK_BYTES = 64 * 1024
logger = logging.getLogger(__name__)


class PiBridgeError(RuntimeError):
    pass


class PiModelError(PiBridgeError):
    """A failed native provider call, distinct from checkpoint/protocol failure."""

    def __init__(self, message, *, error_type=None):
        super().__init__(message)
        self.error_type = error_type


async def _read_frame(reader):
    """Assemble a bounded JSON line independently of StreamReader's buffer size."""
    frame = bytearray()
    while True:
        try:
            chunk = await reader.readuntil(b'\n')
        except asyncio.LimitOverrunError as error:
            if len(frame) + error.consumed > MAX_FRAME_BYTES:
                raise PiBridgeError('Pi RPC frame exceeds the byte limit') from None
            frame.extend(await reader.readexactly(error.consumed))
            continue
        except asyncio.IncompleteReadError as error:
            if not frame and not error.partial:
                return None
            raise PiBridgeError('Pi RPC frame terminated before its newline; incomplete message') from None
        if len(frame) + len(chunk) > MAX_FRAME_BYTES:
            raise PiBridgeError('Pi RPC frame exceeds the byte limit')
        frame.extend(chunk)
        try:
            value = json.loads(frame)
        except (ValueError, UnicodeError):
            raise PiBridgeError('Invalid JSON in Pi RPC frame') from None
        if not isinstance(value, dict):
            raise PiBridgeError('Pi RPC frame must contain an object')
        return value


class PiBridge:
    def __init__(self, node=None, timeout=300):
        self.node = node
        self.timeout = timeout

    async def discover_skills(self, cwd, skill_paths):
        """Read Pi's visible catalog, without an agent turn or executable RPCs."""
        async def reject_request(method, payload):
            raise PiBridgeError('Skill discovery must not issue requests')
        return await self.run({'operation': 'discover_skills', 'cwd': cwd,
                               'skillPaths': skill_paths}, reject_request)

    async def run(self, options, handler):
        try:
            runtime = resolve_runtime(self.node)
        except RuntimeError as error:
            raise PiBridgeError(str(error)) from error
        process = await asyncio.create_subprocess_exec(
            str(runtime.node), str(runtime.worker), stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            limit=PIPE_CHUNK_BYTES,
        )
        stderr = bytearray()
        async def drain_stderr():
            while chunk := await process.stderr.read(4096):
                stderr.extend(chunk)
                del stderr[:-8192]
        async def discard_stdout():
            while await process.stdout.read(PIPE_CHUNK_BYTES):
                pass
        reader = asyncio.create_task(drain_stderr())
        tasks = []
        async def send(value):
            frame = (json.dumps(value, ensure_ascii=False, separators=(',', ':')) + '\n').encode()
            if len(frame) > MAX_FRAME_BYTES:
                raise PiBridgeError('Pi RPC frame exceeds the byte limit')
            for offset in range(0, len(frame), PIPE_CHUNK_BYTES):
                process.stdin.write(frame[offset:offset + PIPE_CHUNK_BYTES])
                await process.stdin.drain()
        deadline = asyncio.timeout(self.timeout)
        try:
            async with deadline:
                await send({'type': 'start', 'protocol': 1, 'options': options})
                requests, notifications = asyncio.Queue(maxsize=32), asyncio.Queue(maxsize=64)

                async def receive():
                    last_id = 0
                    while True:
                        message = await _read_frame(process.stdout)
                        if message is None:
                            await reader
                            raise PiBridgeError('Pi worker exited unexpectedly: ' + stderr.decode(errors='replace'))
                        if message.get('type') == 'done':
                            return message['result']
                        if message.get('type') == 'error':
                            error = message.get('error', 'Pi worker failed')
                            if message.get('code') == 'model_error':
                                raise PiModelError(error, error_type=message.get('error_type'))
                            raise PiBridgeError(error)
                        if message.get('type') == 'notification':
                            if message.get('method') != 'stream' or not isinstance(message.get('payload'), dict):
                                raise PiBridgeError('Invalid Pi worker notification')
                            # Deltas are previews, not execution facts. A slow viewer
                            # must not block provider drainage or durable RPCs. The
                            # committed utterance always replaces the preview.
                            if notifications.full():
                                notifications.get_nowait()
                                notifications.task_done()
                            notifications.put_nowait(message)
                            continue
                        if message.get('type') != 'request' or message.get('id') != last_id + 1:
                            raise PiBridgeError('Invalid Pi worker protocol sequence')
                        last_id = message['id']
                        try:
                            requests.put_nowait(message)
                        except asyncio.QueueFull:
                            raise PiBridgeError('Too many pending Pi worker requests') from None

                async def acknowledge():
                    while True:
                        message = await requests.get()
                        try:
                            # A failed checkpoint is fatal: never ACK it or let
                            # Pi invoke another effect. Preserve request order.
                            result = await handler(message['method'], message['payload'])
                            await send({'type': 'response', 'id': message['id'], 'result': result})
                        finally:
                            requests.task_done()

                async def previews():
                    available = True
                    while True:
                        message = await notifications.get()
                        try:
                            if available:
                                try:
                                    await asyncio.wait_for(handler('stream', message['payload']), 1)
                                except Exception:
                                    available = False
                                    logger.warning('Pi live preview unavailable; committed delivery continues')
                        finally:
                            notifications.task_done()

                receiver = asyncio.create_task(receive())
                acknowledger = asyncio.create_task(acknowledge())
                tasks = [receiver, acknowledger, asyncio.create_task(previews())]
                done, _ = await asyncio.wait([receiver, acknowledger], return_when=asyncio.FIRST_COMPLETED)
                if acknowledger in done:
                    acknowledger.result()
                result = await receiver
                await requests.join()
                await notifications.join()
                return result
        except TimeoutError:
            if deadline.expired():
                raise TimeoutError(f'Pi run exceeded total timeout of {self.timeout:g} seconds') from None
            raise
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            # A rejected large frame can leave stdout paused. Drain it while
            # shutting down, or even a killed child can leave wait() blocked.
            stdout_reader = asyncio.create_task(discard_stdout())
            if process.returncode is None:
                # EOF aborts Pi first, so native shell processes receive its
                # normal cancellation cleanup before the worker exits.
                process.stdin.close()
            try:
                await asyncio.wait_for(process.wait(), 2)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
            await asyncio.gather(stdout_reader, reader)
