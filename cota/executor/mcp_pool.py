"""MCP Connection Pool — per-user dynamic connection management.

Manages RemoteMCPClient instances keyed by user_id.
Same user across multiple sessions shares one connection.
Idle connections are automatically closed after a configurable timeout.
"""

import asyncio
import logging
import time
from typing import Dict, Optional

from .mcp_remote import RemoteMCPClient

logger = logging.getLogger(__name__)

# Defaults
DEFAULT_IDLE_TIMEOUT = 300   # 5 minutes
DEFAULT_MAX_CONNECTIONS = 100


class MCPConnectionPool:
    """Per-user MCP connection pool.

    Usage::

        pool = MCPConnectionPool()
        client = await pool.get_or_create(
            user_id="alice",
            endpoint_url="https://alice-device:8080/mcp",
        )
        tools = await client.list_tools()
        # ... later ...
        await pool.close_all()
    """

    def __init__(
        self,
        idle_timeout: int = DEFAULT_IDLE_TIMEOUT,
        max_connections: int = DEFAULT_MAX_CONNECTIONS,
    ) -> None:
        self._connections: Dict[str, RemoteMCPClient] = {}
        self._idle_timeout = idle_timeout
        self._max_connections = max_connections
        self._lock = asyncio.Lock()
        logger.info(
            f"MCPConnectionPool created (idle_timeout={idle_timeout}s, "
            f"max_connections={max_connections})"
        )

    async def get_or_create(
        self,
        user_id: str,
        endpoint_url: str,
        auth_token: Optional[str] = None,
    ) -> RemoteMCPClient:
        """Get an existing connection or create a new one for a user.

        If the user already has a connected client pointing to the same
        endpoint, it is reused.  If the endpoint changed (user updated
        their MCP server), the old connection is closed and a new one
        is created.
        """
        async with self._lock:
            existing = self._connections.get(user_id)

            # Reuse if same endpoint and still connected
            if (existing and existing.endpoint_url == endpoint_url
                    and existing.auth_token == auth_token and existing.connected):
                existing.last_used = time.monotonic()
                return existing

            # Close stale / mismatched connection
            if existing:
                await self._close_client(user_id)

            # Enforce max connections
            if len(self._connections) >= self._max_connections:
                await self._evict_oldest()

            # Create new connection
            client = RemoteMCPClient(
                endpoint_url=endpoint_url,
                auth_token=auth_token,
            )
            await client.connect()
            self._connections[user_id] = client
            logger.info(
                f"MCPPool: new connection for user={user_id} "
                f"endpoint={endpoint_url} "
                f"(total={len(self._connections)})"
            )
            return client

    async def disconnect(self, user_id: str) -> None:
        """Explicitly disconnect a user's MCP connection."""
        async with self._lock:
            await self._close_client(user_id)

    async def cleanup_idle(self) -> int:
        """Close connections that have been idle longer than the timeout.

        Returns the number of connections closed.
        """
        now = time.monotonic()
        to_close = []

        async with self._lock:
            for uid, client in self._connections.items():
                if now - client.last_used > self._idle_timeout:
                    to_close.append(uid)

            for uid in to_close:
                await self._close_client(uid)

        if to_close:
            logger.info(f"MCPPool: cleaned up {len(to_close)} idle connections")
        return len(to_close)

    async def close_all(self) -> None:
        """Close all connections (shutdown)."""
        async with self._lock:
            for uid in list(self._connections.keys()):
                await self._close_client(uid)
        logger.info("MCPPool: all connections closed")

    @property
    def active_count(self) -> int:
        return len(self._connections)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _close_client(self, user_id: str) -> None:
        """Close and remove a client. Caller must hold self._lock."""
        client = self._connections.pop(user_id, None)
        if client:
            try:
                await client.close()
            except Exception as e:
                logger.warning(f"MCPPool: error closing connection for {user_id}: {e}")

    async def _evict_oldest(self) -> None:
        """Evict the least recently used connection. Caller must hold self._lock."""
        if not self._connections:
            return
        oldest_uid = min(
            self._connections,
            key=lambda uid: self._connections[uid].last_used,
        )
        logger.info(f"MCPPool: evicting oldest connection (user={oldest_uid})")
        await self._close_client(oldest_uid)
