"""Acknowledged JSON-lines transport to a pinned, stateless Pi Core worker."""
import asyncio
import json
from .pi_distribution import resolve_runtime


class PiBridgeError(RuntimeError):
    pass


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
            limit=32 * 1024 * 1024,
        )
        stderr = bytearray()
        async def drain_stderr():
            while chunk := await process.stderr.read(4096):
                stderr.extend(chunk)
                del stderr[:-8192]
        reader = asyncio.create_task(drain_stderr())
        async def send(value):
            process.stdin.write((json.dumps(value, ensure_ascii=False) + '\n').encode())
            await process.stdin.drain()
        try:
            async with asyncio.timeout(self.timeout):
                await send({'type': 'start', 'protocol': 1, 'options': options})
                last_id = 0
                while True:
                    line = await process.stdout.readline()
                    if not line:
                        await reader
                        raise PiBridgeError('Pi worker exited unexpectedly: ' + stderr.decode(errors='replace'))
                    message = json.loads(line)
                    if message.get('type') == 'done':
                        return message['result']
                    if message.get('type') == 'error':
                        raise PiBridgeError(message.get('error', 'Pi worker failed'))
                    if message.get('type') != 'request' or message.get('id') != last_id + 1:
                        raise PiBridgeError('Invalid Pi worker protocol sequence')
                    last_id = message['id']
                    # A failed checkpoint is fatal: never ACK it or let Pi invoke another effect.
                    result = await handler(message['method'], message['payload'])
                    await send({'type': 'response', 'id': last_id, 'result': result})
        finally:
            if process.returncode is None:
                # EOF aborts Pi first, so native shell processes receive its
                # normal cancellation cleanup before the worker exits.
                process.stdin.close()
            try:
                await asyncio.wait_for(process.wait(), 2)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
            await reader
