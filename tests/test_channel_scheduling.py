import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from cota.channels.events import InboundMessage, OutboundMessage
from cota.channels.manager import ChannelManager
from cota.channels.queue import MessageBus
from cota.channels.runner import ChannelRunner


def inbound(session, content):
    return InboundMessage('test', 'user', session, content)


@pytest.mark.asyncio
async def test_session_fifo_does_not_reserve_other_session_capacity():
    runner = ChannelRunner({}, None, concurrency=2, max_pending=8)
    await runner.start()
    release = asyncio.Event()
    started = asyncio.Event()
    order = []

    async def handle(message):
        order.append(message.content)
        if message.content == 'a1':
            started.set()
            await release.wait()
        return message.content

    try:
        a1 = await runner.submit(inbound('a', 'a1'), handle)
        await started.wait()
        a2 = await runner.submit(inbound('a', 'a2'), handle)
        b = await runner.submit(inbound('b', 'b'), handle)
        assert await asyncio.wait_for(b, 1) == 'b'
        assert not a2.done()
        release.set()
        assert await a1 == 'a1'
        assert await a2 == 'a2'
        assert order == ['a1', 'b', 'a2']
    finally:
        await runner.stop()


@pytest.mark.asyncio
async def test_bounded_admission_shutdown_and_handler_errors():
    runner = ChannelRunner({}, None, concurrency=1, max_pending=2)
    await runner.start()
    blocked = asyncio.Event()
    first = await runner.submit(inbound('a', '1'), lambda _: blocked.wait())
    second = await runner.submit(inbound('a', '2'), lambda _: blocked.wait())
    with pytest.raises(asyncio.QueueFull):
        await runner.submit(inbound('b', '3'), lambda _: blocked.wait())
    await asyncio.wait_for(runner.stop(), 1)
    assert first.cancelled() and second.cancelled()
    with pytest.raises(RuntimeError):
        await runner.submit(inbound('a', '4'))


@pytest.mark.asyncio
async def test_failure_is_returned_and_does_not_block_following_turn():
    runner = ChannelRunner({}, None)
    await runner.start()

    async def fail(_):
        raise ValueError('handler failed')

    try:
        failed = await runner.submit(inbound('a', '1'), fail)
        following = await runner.submit(inbound('a', '2'), AsyncMock(return_value='ok'))
        with pytest.raises(ValueError, match='handler failed'):
            await failed
        assert await following == 'ok'
    finally:
        await runner.stop()


@pytest.mark.asyncio
async def test_bus_path_runs_independent_processors_concurrently():
    release = asyncio.Event()
    a_started = asyncio.Event()
    b_started = asyncio.Event()
    processors = []

    def create_processor(**kwargs):
        async def handle(message):
            if message.chat_id == 'a':
                a_started.set()
                await release.wait()
            else:
                b_started.set()
        processor = SimpleNamespace(handle_inbound_message=handle)
        processors.append(processor)
        return processor

    runner = ChannelRunner({}, SimpleNamespace(create_processor=create_processor), concurrency=2)
    await runner.start()
    try:
        await runner.message_bus.publish_inbound(inbound('a', '1'))
        await a_started.wait()
        await runner.message_bus.publish_inbound(inbound('b', '2'))
        await asyncio.wait_for(b_started.wait(), 1)
        assert len(processors) == 2
    finally:
        release.set()
        await runner.stop()


@pytest.mark.parametrize('kwargs', [{'concurrency': 0}, {'max_pending': 0}, {'concurrency': -1}])
def test_invalid_limits(kwargs):
    with pytest.raises(ValueError):
        ChannelRunner({}, None, **kwargs)


@pytest.mark.asyncio
@pytest.mark.parametrize('direction', ['inbound', 'outbound'])
async def test_bus_close_wakes_consumer_and_rejects_publish(direction):
    bus = MessageBus(maxsize=1)
    consumer = asyncio.create_task(getattr(bus, f'consume_{direction}')())
    await asyncio.sleep(0)
    await bus.close()
    assert await asyncio.wait_for(consumer, .2) is None
    message = inbound('a', '1') if direction == 'inbound' else OutboundMessage('test', 'a', '1')
    with pytest.raises(RuntimeError):
        await getattr(bus, f'publish_{direction}')(message)


@pytest.mark.asyncio
async def test_bus_close_wakes_blocked_publisher():
    bus = MessageBus(maxsize=1)
    await bus.publish_inbound(inbound('a', '1'))
    publisher = asyncio.create_task(bus.publish_inbound(inbound('a', '2')))
    await asyncio.sleep(0)
    await bus.close()
    with pytest.raises(RuntimeError):
        await asyncio.wait_for(publisher, .2)


@pytest.mark.asyncio
async def test_manager_startup_timeout_and_failure_propagates():
    manager = ChannelManager({}, MessageBus())
    platform = SimpleNamespace(start=AsyncMock(side_effect=lambda: None), stop=AsyncMock())
    async def serve():
        await asyncio.Event().wait()
    platform.start = serve
    manager.channels = {'platform': platform}
    manager._lifecycle_timeout = .02
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(manager.start_all(), .2)
    await manager.stop_all()

    manager = ChannelManager({}, MessageBus())
    manager.channels = {'web': SimpleNamespace(start=AsyncMock(side_effect=ValueError('bad start')), stop=AsyncMock())}
    with pytest.raises(ValueError, match='bad start'):
        await manager.start_all()
    await manager.stop_all()


@pytest.mark.asyncio
async def test_outbound_slow_recipient_isolated_and_target_fifo():
    bus = MessageBus()
    manager = ChannelManager({}, bus)
    release = asyncio.Event()
    b_sent = asyncio.Event()
    sent = []

    async def send(message):
        if message.chat_id == 'a':
            await release.wait()
        sent.append(message.content)
        if message.chat_id == 'b':
            b_sent.set()

    manager.channels = {'web': SimpleNamespace(start=AsyncMock(), stop=AsyncMock(), send=send)}
    await manager.start_all()
    try:
        for target, content in [('a', 'a1'), ('a', 'a2'), ('b', 'b1')]:
            await bus.publish_outbound(OutboundMessage('web', target, content))
        await asyncio.wait_for(b_sent.wait(), .2)
        assert sent == ['b1']
        release.set()
        for _ in range(20):
            if len(sent) == 3:
                break
            await asyncio.sleep(.01)
        assert sent == ['b1', 'a1', 'a2']
    finally:
        await manager.stop_all()


@pytest.mark.asyncio
async def test_active_sessions_stay_within_limit():
    runner = ChannelRunner({}, None, concurrency=2, max_pending=10)
    await runner.start()
    release = asyncio.Event()
    running = 0
    peak = 0

    async def handle(_):
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        try:
            await release.wait()
        finally:
            running -= 1

    try:
        results = [await runner.submit(inbound(str(i), str(i)), handle) for i in range(6)]
        await asyncio.sleep(0)
        assert running == 2
        release.set()
        await asyncio.gather(*results)
        assert peak == 2
    finally:
        await runner.stop()


@pytest.mark.asyncio
async def test_send_timeout_advances_same_target():
    bus = MessageBus()
    manager = ChannelManager({'channel_limits': {'send_timeout': .02}}, bus)
    delivered = asyncio.Event()
    cancelled = asyncio.Event()

    async def send(message):
        if message.content == '1':
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        else:
            delivered.set()

    manager.channels = {'web': SimpleNamespace(start=AsyncMock(), stop=AsyncMock(), send=send)}
    await manager.start_all()
    try:
        await bus.publish_outbound(OutboundMessage('web', 'a', '1'))
        await bus.publish_outbound(OutboundMessage('web', 'a', '2'))
        await asyncio.wait_for(delivered.wait(), 1)
        assert cancelled.is_set()
    finally:
        await manager.stop_all()


@pytest.mark.asyncio
async def test_delayed_platform_failure_is_observed_in_status():
    manager = ChannelManager({}, MessageBus())
    fail = asyncio.Event()

    from tests.channels.test_plugin_runtime import PartnerChannel

    class FailingChannel(PartnerChannel):
        async def start(self):
            self._running = True
            self.create_task(self.listen())

        async def listen(self):
            await fail.wait()
            raise ValueError('listener failed')

    manager.channels = {'platform': FailingChannel({}, manager.bus)}
    await manager.start_all()
    try:
        fail.set()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert manager.get_status()['platform']['error'] == 'ValueError'
    finally:
        await manager.stop_all()


@pytest.mark.asyncio
async def test_queued_caller_cancellation_skips_turn_and_releases_capacity():
    runner = ChannelRunner({}, None, concurrency=1, max_pending=2)
    await runner.start()
    release = asyncio.Event()
    cancelled_handler = AsyncMock()
    try:
        active = await runner.submit(inbound('a', '1'), lambda _: release.wait())
        queued = await runner.submit(inbound('a', '2'), cancelled_handler)
        queued.cancel()
        release.set()
        await active
        await asyncio.sleep(0)
        cancelled_handler.assert_not_called()
        next_result = await runner.submit(inbound('b', '3'), AsyncMock(return_value='ok'))
        assert await next_result == 'ok'
    finally:
        await runner.stop()


@pytest.mark.asyncio
async def test_runner_configure_hook_runs_before_channel_start():
    runner = ChannelRunner({}, None)
    configured = []

    async def start_channel():
        assert configured == ['bound']
        configured.append('started')

    async def configure(manager):
        configured.append('bound')
        manager.channels['web'] = SimpleNamespace(start=start_channel, stop=AsyncMock())

    try:
        await runner.start(configure=configure)
        assert configured == ['bound', 'started']
    finally:
        await runner.stop()


@pytest.mark.asyncio
async def test_graceful_stop_finishes_active_turn_but_rejects_queued_input():
    runner = ChannelRunner({}, None, shutdown_timeout=.1)
    await runner.start()
    entered, release = asyncio.Event(), asyncio.Event()
    async def handle(message):
        entered.set()
        await release.wait()
        return 'completed'
    active = await runner.submit(inbound('a', '1'), handle)
    await entered.wait()
    queued = await runner.submit(inbound('a', '2'), handle)
    closing = asyncio.create_task(runner.stop(graceful=True))
    await asyncio.sleep(.005)
    release.set()
    await closing
    assert await active == 'completed'
    assert queued.cancelled()
    assert runner.message_bus.is_closed
