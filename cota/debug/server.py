"""A loopback-only, read-only HTTP viewer with no production server lifecycle."""
import asyncio
import json
import logging
from pathlib import Path
import secrets
import socket
from urllib.parse import urlsplit

from aiohttp import web

from cota.debug.inspector import ModelDiagnosticsUnavailable

logger = logging.getLogger(__name__)
_ASSETS = Path(__file__).parent / 'static'
_HEADERS = {
    'Cache-Control': 'no-store',
    'Referrer-Policy': 'no-referrer',
    'X-Content-Type-Options': 'nosniff',
    'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; "
                             "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; object-src 'none'",
}


class DebugServer:
    def __init__(self, inspector):
        self.inspector = inspector
        self.token = secrets.token_urlsafe(24)
        self.origin = None
        self.runner = None
        self.query_lock = asyncio.Lock()
        self.app = web.Application(middlewares=[self._guard])
        prefix = '/' + self.token
        for name in ('index.html', 'app.js', 'style.css'):
            path = prefix + ('/' if name == 'index.html' else '/' + name)
            async def asset(request, filename=name):
                return web.FileResponse(_ASSETS / filename, headers=_HEADERS)
            self.app.router.add_get(path, asset)
        self.app.router.add_get(prefix + '/api/{kind}', self._query)
        self.app.router.add_get(prefix + '/api/event/{sequence}', self._query)

    @web.middleware
    async def _guard(self, request, handler):
        if not self.origin or request.host != urlsplit(self.origin).netloc:
            return web.json_response({'error': 'Invalid local host'}, status=403, headers=_HEADERS)
        if (request.headers.get('Origin', self.origin) != self.origin or
                request.headers.get('Sec-Fetch-Site') == 'cross-site'):
            return web.json_response({'error': 'Same-origin access required'}, status=403, headers=_HEADERS)
        try:
            response = await handler(request)
        except web.HTTPException as error:
            response = web.json_response({'error': error.reason}, status=error.status)
        response.headers.update(_HEADERS)
        return response

    async def _query(self, request):
        if request.method != 'GET':
            raise web.HTTPMethodNotAllowed(request.method, ['GET'])
        if self.query_lock.locked():
            return web.json_response({'error': '另一项查询正在运行，请稍后重试'}, status=429)
        async with self.query_lock:
            try:
                kind = request.match_info.get('kind', 'event')
                inspector = self.inspector
                if inspector.session_id is None and request.query.get('session_id'):
                    inspector = inspector.for_session(request.query['session_id'])
                if kind == 'info':
                    data = await inspector.info()
                    data['multi_session'] = self.inspector.session_id is None
                elif kind == 'sessions' and self.inspector.session_id is None:
                    data = await self.inspector.store.session_page(after=request.query.get('after'),
                                                                   limit=int(request.query.get('limit', 100)))
                elif kind == 'events':
                    data = await inspector.events(int(request.query.get('after', 0)),
                                                      int(request.query.get('limit', 100)))
                elif kind == 'event':
                    data = await inspector.event_view(int(request.match_info['sequence']))
                elif kind == 'deliveries':
                    data = await inspector.deliveries(int(request.query.get('after', 0)),
                                                     int(request.query.get('limit', 100)))
                elif kind == 'model-debug':
                    sequence = request.query.get('event_sequence')
                    data = await inspector.model_debug(
                        request.query.get('request_id'),
                        event_sequence=int(sequence) if sequence is not None else None)
                elif kind == 'run-metadata':
                    data = await inspector.run_metadata(request.query.get('run_id'))
                elif kind == 'state':
                    data = await inspector.state(request.query.get('source', 'stored'))
                else:
                    raise web.HTTPNotFound()
                text = await asyncio.to_thread(json.dumps, data, ensure_ascii=False, allow_nan=False)
                return web.Response(text=text, content_type='application/json')
            except web.HTTPException:
                raise
            except ValueError as error:
                return web.json_response({'error': str(error)}, status=400)
            except ModelDiagnosticsUnavailable:
                return web.json_response({
                    'code': 'model_diagnostics_unavailable',
                    'error': '没有模型请求详情。该次调用可能未开启 Debug，或关联记录不可用。',
                }, status=404)
            except LookupError:
                return web.json_response({'error': '记录不存在'}, status=404)
            except Exception as error:
                logger.warning('Debug query failed (%s); Bot execution is unaffected', type(error).__name__)
                return web.json_response({'error': f'查询失败（{type(error).__name__}），不影响 Bot 执行'}, status=500)

    async def start(self):
        self.runner = web.AppRunner(self.app, access_log=None, shutdown_timeout=2)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.bind(('127.0.0.1', 0))
            sock.listen(socket.SOMAXCONN)
            sock.setblocking(False)
            self.origin = f'http://127.0.0.1:{sock.getsockname()[1]}'
            await self.runner.setup()
            await web.SockSite(self.runner, sock).start()
        except BaseException:
            sock.close()
            await self.close()
            raise
        return f'{self.origin}/{self.token}/'

    async def close(self):
        if self.runner is not None:
            await self.runner.cleanup()
            self.runner = None
