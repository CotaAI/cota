"""Own MCP transport and session contexts in one task for their whole lifetime."""

import asyncio
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class _Connection:
    """One connection generation; closing it cannot mutate its replacement."""

    ready: asyncio.Future
    stop: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task | None = None
    session: object = None
    waiters: int = 0
    delivered: bool = False
    closing: bool = False


class MCPSessionOwner:
    """SDK AnyIO cancel scopes must enter and exit in the same asyncio task."""

    def __init__(self):
        self._connection = None

    @property
    def session(self):
        return self._connection.session if self._connection else None

    @property
    def connected(self):
        connection = self._connection
        return bool(
            connection
            and connection.session is not None
            and not connection.closing
            and not connection.task.done()
        )

    async def start(self, transport_factory, session_factory):
        connection = self._connection
        if connection and connection.closing:
            await asyncio.shield(
                asyncio.gather(connection.task, return_exceptions=True)
            )
            connection = self._connection
        if connection is None or connection.task.done():
            connection = _Connection(asyncio.get_running_loop().create_future())
            self._connection = connection
            connection.task = asyncio.create_task(
                self._run(connection, transport_factory, session_factory)
            )
            # A task cancelled before its first instruction never executes its
            # finally block, so settle readiness from its completion callback too.
            connection.task.add_done_callback(lambda _: self._settle_closed(connection))
        connection.waiters += 1
        try:
            session = await asyncio.shield(connection.ready)
            # Readiness alone does not transfer ownership: a cancellation can
            # arrive between initialize() and this waiter receiving its result.
            connection.delivered = True
            return session
        except asyncio.CancelledError:
            # Keep a generation if another waiter can receive it or a caller
            # already received it. Reclaim the last cancelled unclaimed waiter,
            # including a ready session which has not yet been handed off.
            if connection.waiters == 1 and not connection.delivered:
                await self._close(connection)
            raise
        finally:
            connection.waiters -= 1

    @staticmethod
    def _settle_closed(connection):
        connection.session = None
        if not connection.ready.done():
            connection.ready.cancel()

    async def _run(self, connection, transport_factory, session_factory):
        error = None
        try:
            async with (
                transport_factory() as (read, write),
                session_factory(read, write) as session,
            ):
                try:
                    await session.initialize()
                except Exception as exc:  # noqa: BLE001 — transfer the original initialization error to callers
                    error = exc
                else:
                    connection.session = session
                    connection.ready.set_result(session)
                    await connection.stop.wait()
        except BaseException as exc:  # noqa: BLE001 — transfer errors/cancellation to the caller
            error = exc
        finally:
            connection.session = None
            if not connection.ready.done():
                if isinstance(error, asyncio.CancelledError):
                    connection.ready.cancel()
                else:
                    connection.ready.set_exception(
                        error
                        or RuntimeError("MCP session closed during initialization")
                    )
            elif error and not isinstance(error, asyncio.CancelledError):
                logger.warning("MCP session owner terminated: %s", error)

    async def _close(self, connection):
        connection.closing = True
        connection.stop.set()
        if not connection.ready.done():
            connection.task.cancel()
        # gather consumes pre-start task cancellation without cancelling close().
        await asyncio.shield(asyncio.gather(connection.task, return_exceptions=True))
        self._settle_closed(connection)
        if self._connection is connection:
            self._connection = None

    async def close(self):
        if self._connection is not None:
            await self._close(self._connection)
