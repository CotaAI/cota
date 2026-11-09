"""External adapters use the same durable admission and lifecycle as built-ins."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sanic import Blueprint, response

from cota import Agent, Application
from cota.channels import BaseChannel, InboundMessage, MessageBus
from cota.channels.manager import ChannelManager
from cota.store import MemoryStore


class PartnerChannel(BaseChannel):
    durable_delivery = True

    @property
    def delivery_scope(self):
        return self.config['app_id']

    async def start(self):
        self._running = True

    async def stop(self):
        self._running = False

    async def send(self, message):
        pass

    def http_blueprint(self):
        blueprint = Blueprint('partner_' + self.name)

        @blueprint.post('/webhook')
        async def callback(request):
            submission = await self.receive(InboundMessage(
                channel='ignored', sender_id='partner:alice', chat_id='room',
                content=request.json['text'], message_id=request.json.get('message_id')))
            return response.json({'message_id': submission.message_id,
                                  'duplicate': submission.duplicate}, status=202)

        return blueprint


def config(**settings):
    return {'partner': {'enabled': True, 'factory': __name__ + ':PartnerChannel',
                        'app_id': 'app-one', **settings}}


@pytest.mark.asyncio
async def test_context_receive_acknowledges_committed_input_and_binds_channel():
    entered, release = asyncio.Event(), asyncio.Event()
    app = Application(Agent(store=MemoryStore()), channels=config())

    async def execute(message, **kwargs):
        entered.set()
        await release.wait()

    app._execute = execute
    try:
        manager = app.prepare_channels()
        channel = manager.get_channel('partner')
        assert not channel.is_running
        await app.start()
        submission = await channel.receive(InboundMessage('spoofed', 'alice', 'room', 'hello', message_id='one'))
        await asyncio.wait_for(entered.wait(), 1)
        events = await app.store.events('partner:room')
        assert events[0]['type'] == 'user_utter'
        assert events[0]['payload']['metadata']['channel'] == 'partner'
        assert not submission.future.done()
        duplicate = await channel.receive(InboundMessage('ignored', 'alice', 'room', 'hello', message_id='one'))
        assert duplicate.duplicate
        assert len(await app.store.events('partner:room')) == 1
    finally:
        release.set()
        await app.close()


@pytest.mark.asyncio
async def test_receive_propagates_busy_without_accepting_unsaved_input():
    app = Application(Agent(store=MemoryStore()), channels=config(), max_pending=1)
    release = asyncio.Event()
    app._execute = lambda message, **kwargs: release.wait()
    try:
        await app.start()
        channel = app.runner.get_channel('partner')
        await channel.receive(InboundMessage('', 'alice', 'one', 'hello'))
        with pytest.raises(asyncio.QueueFull):
            await channel.receive(InboundMessage('', 'bob', 'two', 'busy'))
        assert not await app.store.events('partner:two')
    finally:
        release.set()
        await app.close()


@pytest.mark.asyncio
async def test_context_provides_group_mode_and_preserves_mention_fields():
    app = Application(Agent(store=MemoryStore(), dialogue={'mode': 'group'}), channels=config())
    try:
        await app.start()
        channel = app.runner.get_channel('partner')
        assert channel.context.dialogue_mode == 'group'
        result = await channel.receive(InboundMessage('', 'alice', 'room', 'background', sender_name='Alice'))
        assert (await result.wait())['receipt']['status'] == 'recorded'
        assert not any(e['type'] == 'run_started' for e in await app.store.events('partner:room'))
    finally:
        await app.close()


@pytest.mark.asyncio
async def test_background_listener_failure_updates_health_and_cleans_up():
    class Broken(PartnerChannel):
        async def start(self):
            self._running = True
            self.listen = self.create_task(self.listen_forever())

        async def listen_forever(self):
            await fail.wait()
            raise ConnectionError('listener stopped')

    fail = asyncio.Event()
    channel = Broken({}, MessageBus())
    manager = ChannelManager({}, channel.bus)
    manager.channels = {'partner': channel}
    await manager.start_all()
    try:
        fail.set()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert manager.get_status()['partner']['running'] is False
        assert manager.get_status()['partner']['error']
    finally:
        await manager.stop_all()
    assert channel.listen.done()


@pytest.mark.asyncio
async def test_all_adapters_must_finish_startup_before_ready():
    manager = ChannelManager({'channel_limits': {'lifecycle_timeout': .02}}, MessageBus())
    stopped = AsyncMock()
    manager.channels = {'partner': SimpleNamespace(start=lambda: asyncio.Event().wait(), stop=stopped)}
    with pytest.raises(TimeoutError):
        await manager.start_all()
    stopped.assert_awaited()


def test_external_only_server_mounts_namespaced_http_before_start():
    from cota.server import create_app
    app = create_app(Agent(store=MemoryStore()), channel_config=config())
    assert app.ctx.web_service is None
    assert any(route.path == 'channels/partner/webhook' for route in app.router.routes)
    assert app.ctx.application.prepare_channels() is app.ctx.runner.channel_manager


def test_cmdline_group_support_is_adapter_validation():
    app = Application(Agent(store=MemoryStore(), dialogue={'mode': 'group'}),
                      channels={'cmdline': {'enabled': True}})
    with pytest.raises(ValueError, match='direct'):
        app.prepare_channels()


def test_durable_channel_requires_stable_nonempty_delivery_scope():
    app = Application(Agent(store=MemoryStore()), channels=config(app_id=''))
    with pytest.raises(ValueError, match='scope'):
        app.prepare_channels()


@pytest.mark.asyncio
async def test_listener_can_receive_immediately_after_its_start_returns():
    from cota.channels import ChannelRegistry

    class Immediate(PartnerChannel):
        durable_delivery = False

        async def start(self):
            self._running = True
            self.input = self.create_task(self.receive(InboundMessage('', 'alice', 'room', 'hello')))

    registry = ChannelRegistry()
    registry.register('immediate', Immediate)
    app = Application(Agent(store=MemoryStore()), channels={'immediate': {'enabled': True}},
                      channel_registry=registry)
    app._execute = AsyncMock(return_value=None)
    try:
        await app.start()
        channel = app.runner.get_channel('immediate')
        submission = await asyncio.wait_for(channel.input, 1)
        assert submission.session_id == 'immediate:room'
        assert await app.store.events(submission.session_id)
        assert channel.is_running
    finally:
        await app.close()


@pytest.mark.asyncio
async def test_startup_failure_is_not_masked_by_another_blocked_adapter():
    manager = ChannelManager({'channel_limits': {'lifecycle_timeout': .2}}, MessageBus())
    async def fail():
        raise ValueError('bad adapter settings')
    manager.channels = {
        'broken': SimpleNamespace(start=fail, stop=AsyncMock()),
        'blocked': SimpleNamespace(start=lambda: asyncio.Event().wait(), stop=AsyncMock()),
    }
    with pytest.raises(ValueError, match='bad adapter settings'):
        await asyncio.wait_for(manager.start_all(), .1)
    assert not manager._start_tasks


@pytest.mark.asyncio
async def test_prepared_channel_rejects_receive_before_application_start():
    from cota.application import ApplicationUnavailable
    app = Application(Agent(store=MemoryStore()), channels=config())
    try:
        channel = app.prepare_channels().get_channel('partner')
        with pytest.raises(ApplicationUnavailable):
            await asyncio.wait_for(channel.receive(InboundMessage('', 'alice', 'room', 'hello')), .05)
    finally:
        await app.close()
