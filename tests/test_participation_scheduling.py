import asyncio


from cota.channels.runner import ChannelRunner
from tests.test_channel_scheduling import inbound


async def test_foreground_passes_queued_background_but_keeps_its_fifo():
    runner = ChannelRunner({}, None, concurrency=1, max_pending=8)
    await runner.start()
    release, entered = asyncio.Event(), asyncio.Event()
    order = []
    async def handle(message):
        order.append(message.content)
        if message.content == 'active':
            entered.set()
            await release.wait()
    try:
        active = await runner.submit(inbound('g', 'active'), handle)
        await entered.wait()
        background = await runner.submit(inbound('g', 'background'), handle, background=True)
        first = await runner.submit(inbound('g', 'first'), handle)
        second = await runner.submit(inbound('g', 'second'), handle)
        assert runner.has_foreground('test:g')
        release.set()
        await asyncio.gather(active, background, first, second)
        assert order == ['active', 'first', 'second', 'background']
        assert not runner.has_foreground('test:g')
    finally:
        release.set()
        await runner.stop()


async def test_explicit_capacity_evicts_queued_background_not_running_work():
    runner = ChannelRunner({}, None, concurrency=1, max_pending=2)
    await runner.start()
    release = asyncio.Event()
    try:
        active = await runner.submit(inbound('a', 'active'), lambda _: release.wait())
        await asyncio.sleep(0)
        background = await runner.submit(inbound('b', 'optional'), lambda _: release.wait(), background=True)
        first = await runner.submit(inbound('c', 'explicit'), lambda _: asyncio.sleep(0))
        assert background.cancelled()
        assert not active.cancelled()
        release.set()
        await asyncio.gather(active, first)
        assert runner._pending == 0 and not runner._background
    finally:
        release.set()
        await runner.stop()


async def test_foreground_ready_session_precedes_background_ready_session():
    runner = ChannelRunner({}, None, concurrency=1)
    await runner.start()
    release = asyncio.Event()
    order = []
    async def record(message):
        order.append(message.content)
    try:
        active = await runner.submit(inbound('a', 'active'), lambda _: release.wait())
        background = await runner.submit(inbound('b', 'background'), record, background=True)
        first = await runner.submit(inbound('c', 'explicit'), record)
        release.set()
        await asyncio.gather(active, background, first)
        assert order == ['explicit', 'background']
    finally:
        release.set()
        await runner.stop()
