"""Compose the optional chat application with Cota's public Web server.

This module knows profiles and membership, not DST, events, tools or Store.
The browser uses the same WebSocket/history API as an external application.
"""
from pathlib import Path
from urllib.parse import unquote

from sanic import response
from cota.server import create_app as create_channel_app
from .access import ChatAccess
from .registry import ChatRegistry


def create_app(agent, config_path=None, *, channel_config=None):
    config_path = config_path or getattr(agent, 'config_path', None) or './'
    channels = {name: dict(value) for name, value in (channel_config or {}).items()}
    channels.setdefault('web', {'enabled': not bool(channels), 'transport': 'websocket'})
    if not channels['web'].get('enabled'):
        raise ValueError('The chat application requires an enabled Web channel')
    if channels['web'].get('access_factory') is not None:
        raise ValueError('The chat application supplies access; remove channels.web.access_factory')
    dialogue = getattr(agent, 'dialogue', None) or {}
    mode = dialogue.get('mode', 'direct')
    state_path = Path(config_path or './') / '.cota'
    registry = ChatRegistry(state_path / 'chat.sqlite3', mode=mode)
    access = ChatAccess(registry, state_path / 'chat.key')
    app = create_channel_app(agent, config_path=config_path, channel_config=channels, access=access)
    assets = Path(__file__).parent / 'static'

    async def principal(request):
        header = request.headers.get('authorization', '')
        if not header.startswith('Bearer '):
            raise PermissionError('Bearer credential required')
        return await access.authenticate(header[7:])

    def body(request):
        value = request.json
        if not isinstance(value, dict):
            raise ValueError('Expected a JSON object')
        return value

    @app.middleware('response')
    async def chat_headers(request, result):
        if request.path.startswith('/chat'):
            result.headers['Referrer-Policy'] = 'no-referrer'
            result.headers['Content-Security-Policy'] = (
                "default-src 'self'; script-src 'self'; style-src 'self'; "
                "connect-src 'self'; img-src 'self' data:; object-src 'none'; "
                "base-uri 'none'; frame-ancestors 'none'; form-action 'self'")

    @app.get('/')
    async def root(request):
        return response.redirect('/chat/')

    @app.get('/chat/')
    async def index(request):
        return await response.file(assets / 'index.html', mime_type='text/html; charset=utf-8')

    @app.get('/chat/app.js')
    async def javascript(request):
        return await response.file(assets / 'app.js', mime_type='application/javascript')

    @app.get('/chat/style.css')
    async def stylesheet(request):
        return await response.file(assets / 'style.css', mime_type='text/css')

    @app.get('/chat/api/config')
    async def config(request):
        return response.json({'bot_name': agent.name or 'Cota Bot', 'mode': mode,
                              'response': dialogue.get('response', 'passive')})

    @app.post('/chat/api/guests')
    async def guest(request):
        return response.json(await access.create_guest(body(request).get('name')), status=201)

    @app.get('/chat/api/me')
    async def me(request):
        return response.json(await registry.user(await principal(request)))

    @app.get('/chat/api/conversations')
    async def conversations(request):
        user = await principal(request)
        page = await registry.list_conversations(user, offset=int(request.args.get('offset', '0')),
                                                  limit=int(request.args.get('limit', '100')))
        if request.args.get('summaries') == '1':
            for room in page['conversations']:
                sid = room['session_id']
                cursor = await registry.read_cursor(user, sid)
                room.update(await app.ctx.web_service.summary(user, sid, after=cursor))
                room['read_sequence'] = cursor
        return response.json(page)

    @app.post('/chat/api/conversations')
    async def chat_create_conversation(request):
        user = await principal(request)
        return response.json(await registry.create_conversation(user, body(request).get('title')), status=201)

    @app.get('/chat/api/conversations/<session_id>')
    async def conversation(request, session_id):
        return response.json(await registry.conversation(await principal(request), unquote(session_id, errors='strict')))

    @app.get('/chat/api/conversations/<session_id>/summary')
    async def summary(request, session_id):
        user = await principal(request)
        session_id = unquote(session_id, errors='strict')
        cursor = await registry.read_cursor(user, session_id)
        value = await app.ctx.web_service.summary(user, session_id, after=cursor)
        return response.json({**value, 'read_sequence': cursor})

    @app.post('/chat/api/conversations/<session_id>/read')
    async def mark_read(request, session_id):
        user = await principal(request)
        session_id = unquote(session_id, errors='strict')
        await registry.authorize(user, session_id)
        sequence = body(request).get('sequence')
        value = await app.ctx.web_service.summary(user, session_id)
        if type(sequence) is not int or not 0 <= sequence <= value['through']:
            raise ValueError('sequence must identify an existing conversation position')
        return response.json({'read_sequence': await registry.mark_read(user, session_id, sequence)})

    @app.post('/chat/api/conversations/<session_id>/invite')
    async def invite(request, session_id):
        return response.json(await registry.invite(await principal(request), unquote(session_id, errors='strict')))

    @app.post('/chat/api/join')
    async def join(request):
        user = await principal(request)
        return response.json(await registry.join(user, body(request).get('invite')))

    @app.post('/chat/api/conversations/<session_id>/remove')
    async def remove(request, session_id):
        user = await principal(request)
        await registry.remove(user, unquote(session_id, errors='strict'), body(request).get('user_id'))
        return response.json({'success': True})

    @app.post('/chat/api/conversations/<session_id>/leave')
    async def leave(request, session_id):
        await registry.leave(await principal(request), unquote(session_id, errors='strict'))
        return response.json({'success': True})

    return app
