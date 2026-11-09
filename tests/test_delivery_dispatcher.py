"""Durable reply transport: retry stored facts, never rerun an agent."""
import asyncio
from types import SimpleNamespace


from cota.dst import DST
from cota.events import BotUtterEvent
from cota.store import MemoryStore
from cota.channels.delivery import DeliveryDispatcher


async def append(store, sid, text, chat='chat', scope='app'):
    dst = await store.load(sid) or DST(sid, agent=None)
    event = BotUtterEvent(text=text)
    dst.append_event(event)
    await store.save(dst, delivery_target={'channel': 'test', 'scope': scope, 'chat_id': chat})
    return event.event_id


async def until(predicate, timeout=2):
    async def wait():
        while not await predicate():
            await asyncio.sleep(.005)
    await asyncio.wait_for(wait(), timeout)


def dispatcher(store, send, **kwargs):
    channel = SimpleNamespace(durable_delivery=True, delivery_scope='app', send=send)
    return DeliveryDispatcher(store, {'test': channel}, poll_interval=.005, retry_delay=.01,
                              send_timeout=.1, shutdown_timeout=.05, **kwargs)


async def test_retry_preserves_order_and_other_target_continues():
    store = MemoryStore()
    first = await append(store, 'a', 'a1', 'a')
    second = await append(store, 'a', 'a2', 'a')
    other = await append(store, 'b', 'b1', 'b')
    attempts, sent = [], []
    async def send(message):
        attempts.append(message.content)
        if message.content == 'a1' and attempts.count('a1') == 1:
            raise ConnectionError('offline')
        sent.append(message.content)
    worker = dispatcher(store, send)
    await worker.start()
    try:
        async def done(): return (await store.delivery('a', second))['status'] == 'delivered'
        await until(done)
        assert sent == ['b1', 'a1', 'a2']
        assert attempts.count('a1') == 2
        assert (await store.delivery('b', other))['status'] == 'delivered'
        assert (await store.delivery('a', first))['attempts'] == 2
    finally:
        await worker.stop()


async def test_exhausted_head_is_retained_and_manual_retry_unblocks():
    store = MemoryStore()
    first = await append(store, 'a', 'a1')
    second = await append(store, 'a', 'a2')
    offline, sent = True, []
    async def send(message):
        if offline: raise ConnectionError('contains-secret-details')
        sent.append(message.content)
    worker = dispatcher(store, send, max_attempts=2)
    await worker.start()
    try:
        async def failed(): return (await store.delivery('a', first))['status'] == 'failed'
        await until(failed)
        assert (await store.delivery('a', first))['error_type'] == 'ConnectionError'
        assert (await store.delivery('a', second))['attempts'] == 0
        offline = False
        assert await store.retry_delivery('a', first)
        async def done(): return (await store.delivery('a', second))['status'] == 'delivered'
        await until(done)
        assert sent == ['a1', 'a2']
        assert not await store.retry_delivery('a', first)
    finally:
        await worker.stop()


async def test_cancelled_send_stays_pending_and_new_dispatcher_recovers_same_event():
    store = MemoryStore()
    identity = await append(store, 'a', 'reply')
    entered = asyncio.Event()
    async def blocked(message):
        entered.set()
        await asyncio.Event().wait()
    worker = dispatcher(store, blocked)
    await worker.start()
    await asyncio.wait_for(entered.wait(), 1)
    await asyncio.wait_for(worker.stop(), .5)
    assert (await store.delivery('a', identity))['status'] == 'pending'
    sent = []
    async def send(message): sent.append(message.event_id)
    restarted = dispatcher(store, send)
    await restarted.start()
    try:
        async def done(): return (await store.delivery('a', identity))['status'] == 'delivered'
        await until(done)
        assert sent == [identity]
    finally:
        await restarted.stop()


async def test_success_ack_write_failure_retries_ack_without_resending(monkeypatch):
    store = MemoryStore()
    identity = await append(store, 'a', 'reply')
    original = store.finish_delivery
    writes, sends = 0, []
    async def finish(*args, **kwargs):
        nonlocal writes
        writes += 1
        if writes < 3: raise OSError('database busy')
        return await original(*args, **kwargs)
    monkeypatch.setattr(store, 'finish_delivery', finish)
    async def send(message): sends.append(message.event_id)
    worker = dispatcher(store, send)
    await worker.start()
    try:
        async def done(): return (await store.delivery('a', identity))['status'] == 'delivered'
        await until(done)
        assert writes == 3 and sends == [identity]
    finally:
        await worker.stop()


async def test_stop_drains_a_finishing_send():
    store = MemoryStore()
    identity = await append(store, 'a', 'reply')
    entered, release = asyncio.Event(), asyncio.Event()
    async def send(message):
        entered.set()
        await release.wait()
    worker = dispatcher(store, send)
    await worker.start()
    await entered.wait()
    close = asyncio.create_task(worker.stop())
    await asyncio.sleep(.005)
    release.set()
    await close
    assert (await store.delivery('a', identity))['status'] == 'delivered'


async def test_restart_does_not_reset_budget_of_ambiguous_attempts():
    store = MemoryStore()
    identity = await append(store, 'a', 'reply')
    # Simulate two processes dying after starting send, before saving outcome.
    await store.begin_delivery('a', identity)
    await store.begin_delivery('a', identity)
    sent = []
    async def send(message): sent.append(message.event_id)
    worker = dispatcher(store, send, max_attempts=2)
    await worker.start()
    try:
        async def terminal(): return (await store.delivery('a', identity))['status'] != 'pending'
        await until(terminal)
        row = await store.delivery('a', identity)
        assert sent == []
        assert row['status'] == 'failed' and row['attempts'] == 2
        assert row['error_type'] == 'AttemptsExhausted'
    finally:
        await worker.stop()
