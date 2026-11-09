"""Single-listener Bot application: authorized HTTP API and WebSocket chat.

Developer traces remain in the separate local debug viewer. This public
surface deliberately exposes conversation messages, never raw DST/tool data.
"""
import asyncio
import logging
from pathlib import Path
from urllib.parse import urlsplit, unquote, quote
from uuid import uuid4

from sanic import Sanic, response
from sanic.exceptions import SanicException, ServiceUnavailable
from cota.application import Application, ApplicationUnavailable
from cota.channels.web.service import WebService
from cota.channels.web.access import ExternalAccess, GuestAccess, load_access_factory
from cota.inputs import InputConflict
from cota.runtime.pi_runtime import RunInProgress
from cota.channels.registry import validate_channels

logger = logging.getLogger(__name__)


def _origin(value):
    if not isinstance(value, str) or not value or any(c.isspace() for c in value):
        return None
    try:
        parsed = urlsplit(value)
        if (parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username is not None
                or parsed.password is not None or parsed.path or parsed.query or parsed.fragment):
            return None
        parsed.port  # reject malformed/out-of-range ports
        return parsed
    except ValueError:
        return None


def _channels(config):
    channels = validate_channels({} if config is None else config)
    channels.setdefault('web', {'enabled': not bool(channels), 'transport': 'websocket'})
    if not any(value.get('enabled') for value in channels.values()):
        raise ValueError('cota run requires at least one enabled channel')
    web = channels['web']
    for obsolete in ('host', 'port'):
        if obsolete in web:
            raise ValueError(f'channels.web.{obsolete} was removed; use cota run --{obsolete}')
    if web.get('transport', 'websocket') not in ('auto', 'websocket'):
        raise ValueError('channels.web.transport supports websocket only')
    origins = web.get('cors_origins', [])
    if not isinstance(origins, list) or any(_origin(value) is None for value in origins):
        raise ValueError('channels.web.cors_origins must be a list of explicit http(s) origins without paths or wildcards')
    return channels


def _cursor(request, name, default=None):
    value = request.args.get(name)
    if value is None:
        return default
    if not value.isascii() or not value.isdecimal() or len(value) > 20:
        raise ValueError(f'{name} must be a nonnegative integer')
    return int(value)


def create_app(agent=None, config_path=None, *, channel_config=None, authenticate=None, authorize=None, access=None,
               channel_registry=None):
    if agent is None:
        raise ValueError('agent is required; load it with Agent.load_from_path before create_app')
    config_path = config_path or getattr(agent, 'config_path', None) or './'
    channels = _channels(channel_config)
    web_config = channels['web']
    web_enabled = web_config.get('enabled', False)
    if access is not None and (authenticate is not None or authorize is not None):
        raise ValueError('Pass access or authenticate/authorize callbacks, not both')
    factory = web_config.get('access_factory')
    if factory is not None and (access is not None or authenticate is not None or authorize is not None):
        raise ValueError('access_factory cannot be combined with explicit access callbacks')
    if web_enabled and access is None:
        if factory is not None:
            access = load_access_factory(factory, config_path or './')
        elif authenticate is not None or authorize is not None:
            access = ExternalAccess(authenticate, authorize)
        else:
            access = GuestAccess(Path(config_path or './') / '.cota' / 'web.key')
    if (web_enabled and (getattr(agent, 'dialogue', None) or {}).get('mode', 'direct') == 'group'
            and getattr(access, 'allow_guests', True)):
        raise ValueError('Group Web requires ExternalAccess with authentication and conversation membership checks; '
                         'GuestAccess sessions belong to one user')
    application = Application(agent, channels=channels,
                              concurrency=web_config.get('concurrency', 8),
                              max_pending=web_config.get('max_pending', 256),
                              channel_registry=channel_registry)
    runner = application.runner
    service = WebService(application, access=access) if web_enabled else None
    app = Sanic('cota-' + uuid4().hex[:8])
    # Match WebSocket's limit, including JSON escaping of a valid 32768-char text.
    app.config.REQUEST_MAX_SIZE = 256 * 1024
    app.config.WEBSOCKET_MAX_SIZE = 256 * 1024
    app.config.WEBSOCKET_PING_INTERVAL = 20
    app.config.WEBSOCKET_PING_TIMEOUT = 20
    app.ctx.application = application
    app.ctx.agent, app.ctx.runner, app.ctx.web_service = agent, runner, service
    app.ctx.config_path = config_path or './'
    app.ctx.shutdown_task = None
    app.ctx.debug_viewer = None
    application.prepare_channels().mount_http(app)
    assets = Path(__file__).parent / 'channels' / 'utils'
    allowed_origins = set(web_config.get('cors_origins', []))

    @app.middleware('request')
    async def check_origin(request):
        if request.path.startswith('/channels/'):
            if request.method == 'POST' and not application.accepting_messages:
                raise ServiceUnavailable('Application is not accepting messages')
            return  # Platform callbacks own their signature/authentication policy.
        origin = request.headers.get('origin')
        if origin:
            parsed = _origin(origin)
            # Scheme-independent host match supports TLS-terminating proxies.
            same_host = parsed is not None and parsed.netloc == request.host
            if not same_host and origin not in allowed_origins:
                return response.json({'error': 'origin_not_allowed'}, status=403)
        if request.method == 'OPTIONS':
            return response.empty(status=204)
        if request.method == 'POST' and not application.accepting_messages:
            raise ServiceUnavailable('Application is not accepting messages')

    @app.middleware('response')
    async def response_headers(request, result):
        result.headers['Cache-Control'] = 'no-store'
        result.headers['X-Content-Type-Options'] = 'nosniff'
        origin = request.headers.get('origin')
        if not request.path.startswith('/channels/') and origin and origin in allowed_origins:
            result.headers['Access-Control-Allow-Origin'] = origin
            result.headers['Vary'] = 'Origin'
            result.headers['Access-Control-Allow-Headers'] = 'Authorization, Content-Type'
            result.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
            result.headers['Access-Control-Expose-Headers'] = 'Location, Retry-After'

    @app.exception(InputConflict, RunInProgress)
    async def conflict(request, error):
        code = 'input_conflict' if isinstance(error, InputConflict) else 'run_in_progress'
        return response.json({'error': code, 'message': str(error)}, status=409)

    @app.exception(asyncio.QueueFull)
    async def busy(request, error):
        return response.json({'error': 'busy', 'message': 'Please retry with the same message_id'},
                             status=429, headers={'Retry-After': '1'})

    @app.exception(PermissionError)
    async def forbidden(request, error):
        return response.json({'error': 'unauthorized', 'message': 'Authentication or conversation access denied'}, status=403)

    @app.exception(ValueError)
    async def invalid(request, error):
        return response.json({'error': 'invalid_request', 'message': str(error)}, status=400)

    @app.exception(Exception)
    async def http_error(request, error):
        status = (503 if isinstance(error, ApplicationUnavailable) else
                  error.status_code if isinstance(error, SanicException) else 500)
        codes = {400: 'invalid_request', 404: 'not_found', 405: 'method_not_allowed',
                 408: 'request_timeout', 413: 'payload_too_large', 415: 'unsupported_media_type',
                 503: 'not_ready'}
        code = codes.get(status, 'internal_error' if status >= 500 else 'http_error')
        if status >= 500 and status != 503:
            logger.exception('Public HTTP request failed')
        return response.json({'error': code}, status=status,
                             headers=error.headers if isinstance(error, SanicException) else None)

    async def principal(request):
        header = request.headers.get('authorization', '')
        scheme, _, token = header.partition(' ')
        if scheme.lower() != 'bearer' or not token.strip():
            raise PermissionError('Bearer credential required')
        return await service.authenticate(token.strip())

    async def configure(manager):
        if service is not None:
            manager.get_channel('web').get_transport().bind(service)

    async def close_debug():
        viewer, app.ctx.debug_viewer = app.ctx.debug_viewer, None
        if viewer is not None:
            try:
                await viewer.close()
            except Exception as error:
                logger.warning('Cannot close Debug viewer (%s)', type(error).__name__)

    @app.listener('before_server_start')
    async def start(app, loop):
        try:
            await application.start(configure=configure)
            if agent.store.debug_enabled:
                from cota.debug.inspector import Inspector
                from cota.debug.server import DebugServer
                import sys
                viewer = app.ctx.debug_viewer = DebugServer(Inspector(agent))
                try:
                    url = await viewer.start()
                    sys.stderr.write(f'Cota Debug: {url}\n')
                    sys.stderr.flush()
                except Exception as error:
                    logger.warning('Debug viewer unavailable (%s); Bot service continues', type(error).__name__)
                    await close_debug()
        except BaseException:
            await stop(app, loop)
            raise

    async def teardown():
        try:
            await application.close()
        finally:
            try:
                if service is not None:
                    await service.close()
            finally:
                await close_debug()

    @app.listener('before_server_stop')
    async def stop(app, loop):
        if app.ctx.shutdown_task is None:
            app.ctx.shutdown_task = asyncio.create_task(teardown())
            # Observe detached failures if the server's listener waiter is cancelled.
            app.ctx.shutdown_task.add_done_callback(
                lambda task: None if task.cancelled() else task.exception())
        await asyncio.shield(app.ctx.shutdown_task)

    @app.get('/api/health')
    async def health(request):
        actual = runner.channel_manager.get_status() if runner.channel_manager else {}
        statuses = {name: {'enabled': True, 'running': bool(actual.get(name, {}).get('running')),
                          'error': 'channel_failed' if actual.get(name, {}).get('error') else None}
                    for name, settings in channels.items() if settings.get('enabled')}
        healthy = application.accepting_messages and all(v['running'] and not v['error'] for v in statuses.values())
        runtime = service.transport.status() if service and service.transport else {}
        return response.json({'success': healthy, 'bot': agent.name, 'channels': statuses, 'web': runtime}, status=200 if healthy else 503)

    @app.get('/version')
    async def version(request):
        from cota import __version__
        return response.json({'version': __version__})

    if service is None:
        return app

    @app.post('/api/guests')
    async def create_guest(request):
        if not service.access.allow_guests:
            raise PermissionError('Use the configured identity provider')
        return response.json(await service.access.create_guest(), status=201)

    @app.post('/api/conversations')
    async def create_conversation(request):
        user_id = await principal(request)
        if not service.access.allow_guests:
            raise PermissionError('Create conversations in the surrounding application')
        session_id = await service.access.create_conversation(user_id)
        return response.json({'session_id': session_id}, status=201)

    @app.get('/api/conversations/<session_id>/messages')
    async def history(request, session_id):
        user_id = await principal(request)
        if 'recent' in request.args or 'before_sequence' in request.args:
            if 'after_sequence' in request.args or 'until_sequence' in request.args:
                raise ValueError('Backward paging cannot be combined with forward replay')
            page = await service.message_page(user_id, unquote(session_id, errors='strict'),
                before=_cursor(request, 'before_sequence'), limit=_cursor(request, 'limit', 50))
            return response.json(page)
        page = await service.history(user_id, unquote(session_id, errors='strict'),
            after=_cursor(request, 'after_sequence', 0), limit=_cursor(request, 'limit', 100),
            until=_cursor(request, 'until_sequence'))
        return response.json(page)

    @app.post('/api/conversations/<session_id>/messages')
    async def submit(request, session_id):
        user_id = await principal(request)
        session_id = unquote(session_id, errors='strict')
        if request.content_type.split(';', 1)[0].strip().lower() != 'application/json':
            raise SanicException('Expected application/json', status_code=415)
        body = request.json
        if not isinstance(body, dict):
            raise ValueError('Expected a JSON object')
        if set(body) - {'text', 'message_id', 'mentioned', 'reply_to'}:
            raise ValueError('Allowed fields: text, message_id, mentioned, reply_to; identity comes from authorization')
        try:
            value = await service.submit(user_id, session_id, body.get('message_id'), body.get('text'),
                                         mentioned=body.get('mentioned', False), reply_to=body.get('reply_to'))
        except RuntimeError:
            # Shutdown may win while authorization or Store admission awaits.
            if not application.accepting_messages:
                raise ServiceUnavailable('Application is not accepting messages') from None
            raise
        location = f'/api/conversations/{quote(session_id, safe="")}/submissions/{quote(value["message_id"], safe="")}'
        return response.json(value, status=202, headers={'Location': location})

    @app.get('/api/conversations/<session_id>/submissions/<message_id>')
    async def receipt(request, session_id, message_id):
        user_id = await principal(request)
        value = await service.receipt(user_id, unquote(session_id, errors='strict'), unquote(message_id, errors='strict'))
        return response.json(value or {'error': 'not_found'}, status=200 if value else 404)

    @app.websocket('/ws')
    async def socket(request, ws):
        await service.transport.handle(ws)

    @app.get('/cota.js')
    async def client(request):
        return await response.file(assets / 'cota.js', mime_type='application/javascript')

    return app
