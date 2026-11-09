"""Concurrent callers share connection establishment without sharing cancellation."""

import asyncio
from contextlib import asynccontextmanager

import pytest

from cota.executor.mcp_lifecycle import MCPSessionOwner


@pytest.fixture
def setup_owner():
    owner = MCPSessionOwner()
    entered, proceed, closed = asyncio.Event(), asyncio.Event(), asyncio.Event()

    @asynccontextmanager
    async def transport():
        try:
            yield None, None
        finally:
            closed.set()

    class Session:
        def __init__(self, *args):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def initialize(self):
            entered.set()
            await proceed.wait()

    return owner, transport, Session, entered, proceed, closed


async def test_cancel_one_cold_start_waiter_does_not_cancel_other(setup_owner):
    owner, transport, Session, entered, proceed, closed = setup_owner
    first = asyncio.create_task(owner.start(transport, Session))
    second = asyncio.create_task(owner.start(transport, Session))
    try:
        await entered.wait()
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        proceed.set()
        session = await asyncio.wait_for(second, 1)
        assert session is owner.session
        assert owner.connected
        assert not closed.is_set()
    finally:
        await owner.close()
        await asyncio.gather(first, second, return_exceptions=True)


async def test_close_before_owner_task_starts_settles_connecting_caller(setup_owner):
    owner, transport, Session, entered, proceed, closed = setup_owner
    connecting = asyncio.create_task(owner.start(transport, Session))
    closing = asyncio.create_task(owner.close())
    try:
        await asyncio.wait_for(asyncio.shield(closing), 1)
        done, _ = await asyncio.wait({connecting}, timeout=0.1)
        assert connecting in done, (
            "close must settle readiness even before owner coroutine starts"
        )
        with pytest.raises(asyncio.CancelledError):
            await connecting
        proceed.set()
        assert await asyncio.wait_for(owner.start(transport, Session), 1)
        assert owner.connected
    finally:
        connecting.cancel()
        await asyncio.gather(connecting, closing, return_exceptions=True)
        await owner.close()


@pytest.mark.parametrize("waiter_count", [1, 2])
async def test_cancel_after_initialize_before_handoff_reclaims_only_unclaimed_connection(
    setup_owner, waiter_count
):
    owner, transport, Session, entered, proceed, closed = setup_owner
    original_initialize = Session.initialize
    callers = []

    async def initialize(self):
        await original_initialize(self)
        # Cancel the first caller after initialize succeeds, before its shield
        # wakes it up to receive the session.
        asyncio.get_running_loop().call_soon(callers[0].cancel)

    Session.initialize = initialize
    callers.extend(
        asyncio.create_task(owner.start(transport, Session))
        for _ in range(waiter_count)
    )
    try:
        await entered.wait()
        proceed.set()
        with pytest.raises(asyncio.CancelledError):
            await callers[0]
        if waiter_count == 1:
            assert not owner.connected
            assert closed.is_set()
        else:
            assert await callers[1] is owner.session
            assert owner.connected
            assert not closed.is_set()
    finally:
        await owner.close()
        await asyncio.gather(*callers, return_exceptions=True)


async def test_cancel_reusing_a_delivered_connection_does_not_close_it(setup_owner):
    owner, transport, Session, entered, proceed, closed = setup_owner
    proceed.set()
    first_session = await owner.start(transport, Session)

    async def cancelled_borrower():
        asyncio.current_task().cancel()
        await owner.start(transport, Session)

    try:
        with pytest.raises(asyncio.CancelledError):
            await asyncio.create_task(cancelled_borrower())
        assert owner.connected
        assert owner.session is first_session
        assert not closed.is_set()
    finally:
        await owner.close()
