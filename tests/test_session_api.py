"""Management reads are opt-in and authorized by the embedding application."""
from functools import partial

import pytest

from cota.dst import DST
from cota.events import UserUtterEvent, BotUtterEvent, Event
from cota.server import create_app
from tests.test_web_app_integration import running_app


async def unused_model(**kwargs):
    raise AssertionError('Management reads must not execute the model')


@pytest.mark.asyncio
async def test_default_chat_service_does_not_mount_management_reads(tmp_path):
    async with running_app(tmp_path, unused_model) as server:
        for path in ('/api/sessions', '/api/sessions/other/events', '/api/sessions/other/runs/run/trace'):
            async with server.http.get(server.url + path) as response:
                assert response.status == 404


@pytest.mark.asyncio
async def test_management_routes_preserve_rest_reads_behind_application_authorization(tmp_path):
    checked = []

    async def authorize(request):
        checked.append(request.path)
        return request.headers.get('Authorization') == 'Bearer management-access'

    factory = partial(create_app, session_api_authorize=authorize)
    async with running_app(tmp_path, unused_model, app_factory=factory) as server:
        dst = DST('internal-session', server.agent)
        dst.append_event(UserUtterEvent('hello'))
        dst.append_event(Event('run_started', {'input_event_id': dst.latest_user_event.event_id}, run_id='run1'))
        dst.append_event(BotUtterEvent('saved reply'))
        dst.append_event(Event('run_finished', {'status': 'completed'}))
        await server.store.save(dst)
        paths = ('/api/sessions', '/api/sessions/internal-session',
                 '/api/sessions/internal-session/events', '/api/sessions/internal-session/events/1',
                 '/api/sessions/internal-session/history', '/api/sessions/internal-session/runs/run1/trace',
                 '/api/sessions/internal-session/export')
        for path in paths:
            async with server.http.get(server.url + path) as response:
                assert response.status == 403
                assert (await response.json())['error'] == 'unauthorized'
            async with server.http.get(server.url + path, headers={'Authorization': 'Bearer management-access'}) as response:
                assert response.status == 200, (path, await response.text())
                assert await response.json()
        async with server.http.get(server.url + '/api/sessions/internal-session/export?format=yaml',
                                   headers={'Authorization': 'Bearer management-access'}) as response:
            assert response.status == 200 and 'policies:' in await response.text()
        assert len(checked) == 2 * len(paths) + 1
        server.model.generate_chat.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('decision', [None, 1])
async def test_management_requires_explicit_true_from_external_callback(tmp_path, decision):
    factory = partial(create_app, session_api_authorize=lambda request: decision)
    async with running_app(tmp_path, unused_model, app_factory=factory) as server:
        async with server.http.get(server.url + '/api/sessions') as response:
            assert response.status == 403
