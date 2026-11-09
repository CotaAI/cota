"""Explicit tool-process transport; no LLM loop or environment installation.

Cota's initialize/execute/shutdown JSON-lines protocol is not the MCP protocol.
"""
import asyncio
from contextlib import suppress
from copy import deepcopy
import json
import os
import signal


class SubprocessToolClient:
    """Own a deployment-supplied process and serialize RPC calls without replay.

    command is an argv list, e.g. an absolute venv Python and tool_server.py.
    The deployment prepares dependencies and supplies cwd/env. This process is
    not a sandbox or a per-user authorization boundary. After closing or a
    transport failure, create a new client explicitly.
    """

    def __init__(self, command, *, cwd=None, env=None, timeout=120.0):
        if not isinstance(command, (list, tuple)) or not command or not all(isinstance(x, str) and x for x in command):
            raise ValueError('command must be a non-empty argv list')
        if timeout <= 0:
            raise ValueError('timeout must be positive')
        self.command, self.cwd, self.env = list(command), cwd, dict(env or {})
        self.timeout = timeout
        self._process = self._stderr_task = None
        self._lock = asyncio.Lock()
        self._closed = False
        self._schemas = []
        self._request_id = 0
        self._registry_owner = None

    @property
    def is_running(self):
        return self._process is not None and self._process.returncode is None and not self._closed

    async def start(self):
        async with self._lock:
            if self._closed:
                raise RuntimeError('Tool client is closed; create a new client explicitly')
            if self.is_running:
                return deepcopy(self._schemas)
            if self._process is not None:
                await self._stop()
                raise RuntimeError('Tool process exited; client is closed')
            try:
                self._process = await asyncio.create_subprocess_exec(
                    *self.command, cwd=self.cwd, env={**os.environ, **self.env},
                    stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE, limit=8 * 1024 * 1024,
                    start_new_session=(os.name == 'posix'),
                )
                self._stderr_task = asyncio.create_task(self._drain_stderr())
                response = await self._request('initialize', timeout=min(self.timeout, 30))
                if not isinstance(response, dict) or not isinstance(response.get('tools'), list):
                    raise ValueError('Tool server initialize must return a tools list')
                self._schemas = response['tools']
                return deepcopy(self._schemas)
            except BaseException:
                await self._stop()
                raise

    async def execute_tool(self, name, arguments):
        async with self._lock:
            if not self.is_running:
                raise RuntimeError('Tool client is not running or closed; register a new client explicitly')
            try:
                return await self._request('execute', {'tool': name, 'arguments': arguments})
            except BaseException:
                # Never associate a late reply after timeout/cancellation with the next call.
                await self._stop()
                raise

    async def shutdown(self):
        async with self._lock:
            try:
                if self.is_running:
                    with suppress(Exception):
                        await self._request('shutdown', timeout=min(self.timeout, 2))
            finally:
                await self._stop()

    async def _request(self, method, params=None, *, timeout=None):
        self._request_id += 1
        request = {'jsonrpc': '2.0', 'id': self._request_id, 'method': method}
        if params is not None:
            request['params'] = params
        async with asyncio.timeout(self.timeout if timeout is None else timeout):
            self._process.stdin.write((json.dumps(request, ensure_ascii=False) + '\n').encode())
            await self._process.stdin.drain()
            line = await self._process.stdout.readline()
            if not line:
                raise ConnectionError('Tool process closed stdout before replying')
            response = json.loads(line)
            if (not isinstance(response, dict) or response.get('jsonrpc') != '2.0'
                    or response.get('id') != self._request_id):
                raise ValueError('Invalid tool response protocol or request id')
            if 'error' in response:
                raise RuntimeError(f'Tool server error: {response["error"]}')
            if 'result' not in response:
                raise ValueError('Tool response is missing result')
            return response['result']

    async def _drain_stderr(self):
        # Diagnostics must not block the server or mix with protocol output.
        while await self._process.stderr.read(4096):
            pass

    async def _stop(self):
        self._closed = True
        if self._process:
            self._signal_processes(force=False)
            try:
                await asyncio.wait_for(self._process.wait(), 2)
            except asyncio.TimeoutError:
                pass
            finally:
                # Workers may outlive their launcher or ignore SIGTERM. The
                # owned group still needs cleanup even if returncode is set.
                self._signal_processes(force=True)
                await self._process.wait()
            self._process.stdin.close()
            with suppress(BrokenPipeError, ConnectionResetError):
                await self._process.stdin.wait_closed()
            with suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._process.stdout.read(), 2)
        if self._stderr_task:
            with suppress(asyncio.TimeoutError, asyncio.CancelledError):
                await asyncio.wait_for(self._stderr_task, 2)
        self._process = None

    def _signal_processes(self, *, force):
        with suppress(ProcessLookupError):
            if os.name == 'posix':
                os.killpg(self._process.pid, signal.SIGKILL if force else signal.SIGTERM)
            elif self._process.returncode is None:
                (self._process.kill if force else self._process.terminate)()
