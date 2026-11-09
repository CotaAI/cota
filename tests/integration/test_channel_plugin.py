"""A plugin webhook, real Pi execution and REST retry across SQLite restarts."""
import asyncio

import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestServer
import httpx
import pytest

from cota.server import create_app
from cota.channels import InboundMessage
from tests.channels.test_plugin_runtime import PartnerChannel
from tests.test_web_app_integration import running_app


class RestChannel(PartnerChannel):
    async def start(self):
        self.client = httpx.AsyncClient(base_url=self.config['api_base'], timeout=1)
        self._running = True

    async def stop(self):
        self._running = False
        if getattr(self, 'client', None) is not None:
            await self.client.aclose()

    async def send(self, message):
        result = await self.client.post('/messages', json={'chat_id': message.chat_id, 'text': message.content},
                                        headers={'Idempotency-Key': message.event_id})
        result.raise_for_status()


async def eventually(job):
    async with asyncio.timeout(20):
        while not (value := await job()):
            await asyncio.sleep(.01)
        return value


@pytest.mark.asyncio
async def test_webhook_ack_persists_and_restart_retries_committed_reply_with_same_id(tmp_path):
    fail = True
    sends = []
    provider = web.Application()

    async def deliver(request):
        sends.append((request.headers['Idempotency-Key'], await request.json()))
        return web.json_response({}, status=503 if fail else 200)

    provider.router.add_post('/messages', deliver)
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []

    async def model(**kwargs):
        calls.append(kwargs)
        entered.set()
        await release.wait()
        return {'content': 'answer'}

    async with TestServer(provider) as remote:
        settings = {'partner': {'enabled': True, 'factory': __name__ + ':RestChannel',
                                'app_id': 'app-one', 'api_base': str(remote.make_url('/'))}}
        async with running_app(tmp_path, model, channel_config=settings) as server:
            async with server.http.post(server.url + '/channels/partner/webhook',
                                        json={'text': 'hello', 'message_id': 'one'},
                                        headers={'Origin': 'https://provider.example'}) as result:
                assert result.status == 202  # Web CORS rules do not replace plugin authentication.
                assert (await result.json())['message_id'] == 'one'
            await asyncio.wait_for(entered.wait(), 10)
            assert (await server.store.events('partner:room'))[0]['payload']['text'] == 'hello'
            assert not sends
            async with server.http.post(server.url + '/channels/partner/webhook',
                                        json={'text': 'hello', 'message_id': 'one'}) as result:
                assert (await result.json())['duplicate'] is True
            release.set()

            async def failed_attempt():
                rows = await server.store.events('partner:room')
                reply = next((row for row in rows if row['type'] == 'bot_utter'), None)
                if reply is None:
                    return None
                delivery = await server.store.delivery('partner:room', reply['event_id'])
                return delivery if delivery['error_type'] else None

            pending = await eventually(failed_attempt)
            assert pending['status'] == 'pending'
            assert len(calls) == 1
        fail = False

        async def forbidden(**kwargs):
            raise AssertionError('Delivery recovery must not execute the model again')

        async with running_app(tmp_path, forbidden, channel_config=settings) as server:
            async def delivered():
                row = await server.store.delivery('partner:room', pending['event_id'])
                return row if row['status'] == 'delivered' else None
            row = await eventually(delivered)
            assert row['attempts'] >= 2
            assert server.model.generate_chat.await_count == 0
            assert {identity for identity, _ in sends} == {pending['event_id']}
            assert all(payload == {'chat_id': 'room', 'text': 'answer'} for _, payload in sends)
            async with server.http.get(server.url + '/api/health') as response:
                health = await response.json()
                assert response.status == 200 and health['channels']['partner']['running']


@pytest.mark.asyncio
async def test_service_debug_is_separate_and_selects_plugin_session(tmp_path):
    def debug_app(agent, **kwargs):
        agent.store.enable_debug_log(tmp_path / 'debug.log')
        return create_app(agent, **kwargs)

    async def model(**kwargs):
        return {'content': 'answer'}

    settings = {'partner': {'enabled': True,
                            'factory': 'tests.channels.test_plugin_runtime:PartnerChannel', 'app_id': 'app-one'}}
    async with running_app(tmp_path, model, app_factory=debug_app, channel_config=settings) as server:
        submission = await server.app.ctx.runner.get_channel('partner').receive(
            InboundMessage('', 'alice', 'room', 'hello'))
        await submission.wait()
        viewer = server.app.ctx.debug_viewer
        debug_url = f'{viewer.origin}/{viewer.token}/'
        assert not server.url.startswith(viewer.origin)
        async with aiohttp.ClientSession() as client:
            async with client.get(debug_url + 'api/sessions') as response:
                assert (await response.json())['sessions'][0]['session_id'] == 'partner:room'
            async with client.get(debug_url + 'api/events', params={'session_id': 'partner:room'}) as response:
                assert any(event['type'] == 'bot_utter' for event in (await response.json())['events'])
            async with client.get(debug_url + 'api/model-debug', params={'session_id': 'partner:room'}) as response:
                assert (await response.json())['records']
        async with server.http.get(server.url + '/api/events') as response:
            assert response.status == 404


@pytest.mark.asyncio
async def test_debug_viewer_failure_does_not_stop_bot_service(tmp_path, monkeypatch):
    from cota.debug.server import DebugServer
    from unittest.mock import AsyncMock
    monkeypatch.setattr(DebugServer, 'start', AsyncMock(side_effect=OSError('local listener unavailable')))
    def debug_app(agent, **kwargs):
        agent.store.enable_debug_log(tmp_path / 'debug.log')
        return create_app(agent, **kwargs)
    async def model(**kwargs):
        return {'content': 'answer'}
    settings = {'partner': {'enabled': True,
                            'factory': 'tests.channels.test_plugin_runtime:PartnerChannel', 'app_id': 'app-one'}}
    async with running_app(tmp_path, model, app_factory=debug_app, channel_config=settings) as server:
        assert server.app.ctx.application.accepting_messages
        assert server.app.ctx.debug_viewer is None
        submission = await server.app.ctx.runner.get_channel('partner').receive(
            InboundMessage('', 'alice', 'room', 'hello'))
        assert (await submission.wait())['receipt']['status'] == 'completed'
