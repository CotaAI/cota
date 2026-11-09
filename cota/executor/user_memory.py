"""User Memory — cross-session persistent memory, isolated by user_id.

Stores long-term user preferences and personalization data across sessions.
Execution traces live in DST and Store. This module is about the *user*:
  - profile: basic info, language, timezone, preferences
  - agent_settings: per-bot personalization (e.g. response style)
  - skill_notes: user-specific notes for specific skills

Storage is always keyed by user_id (not session_id), so data persists
across all sessions for the same user.

Two backends:
  - MemoryUserMemory: in-process dict, no persistence (default / testing)
  - SQLUserMemory: SQLAlchemy-backed, persistent across restarts
"""

import json
import asyncio
import threading
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Only trusted applications register device connections. Never render these as
# conversational memory or permit model tools to read/write them.
RESERVED_MEMORY_KEYS = frozenset({'mcp_endpoint', 'mcp_auth_token'})


# =============================================================================
# Abstract base
# =============================================================================

class UserMemory(ABC):
    """Abstract cross-session user memory store."""

    @abstractmethod
    def get(self, user_id: str, key: str) -> Optional[Any]:
        """Get a single value by key for a user. Returns None if not found."""

    @abstractmethod
    def set(self, user_id: str, key: str, value: Any) -> None:
        """Set a key-value pair for a user. Creates or updates."""

    @abstractmethod
    def delete(self, user_id: str, key: str) -> bool:
        """Delete a key. Returns True if it existed."""

    @abstractmethod
    def get_all(self, user_id: str) -> Dict[str, Any]:
        """Return all key-value pairs for a user as a dict."""

    async def _async_call(self, method, *args):
        def invoke():
            lock = getattr(self, "_io_lock", None)
            if lock is not None:
                with lock:
                    return method(*args)
            return method(*args)
        return await asyncio.to_thread(invoke)

    async def aget(self, user_id: str, key: str) -> Optional[Any]:
        return await self._async_call(self.get, user_id, key)

    async def aset(self, user_id: str, key: str, value: Any) -> None:
        await self._async_call(self.set, user_id, key, value)

    async def adelete(self, user_id: str, key: str) -> bool:
        return await self._async_call(self.delete, user_id, key)

    async def aget_all(self, user_id: str) -> Dict[str, Any]:
        return await self._async_call(self.get_all, user_id)

    async def asearch(self, user_id: str, query: str) -> Dict[str, Any]:
        return await self._async_call(self.search, user_id, query)

    def search(self, user_id: str, query: str) -> Dict[str, Any]:
        """Return entries whose key or value contains the query string.

        Default implementation: scan all entries (subclasses may override
        with a proper index / FTS query).
        """
        query_lower = query.lower()
        results = {}
        for k, v in self.get_all(user_id).items():
            if query_lower in k.lower() or query_lower in str(v).lower():
                results[k] = v
        return results


# =============================================================================
# In-memory backend (no persistence, good for testing / personal mode)
# =============================================================================

class MemoryUserMemory(UserMemory):
    """Simple dict-based user memory with no persistence."""

    def __init__(self) -> None:
        # { user_id: { key: value } }
        self._store: Dict[str, Dict[str, Any]] = {}

    def get(self, user_id: str, key: str) -> Optional[Any]:
        return self._store.get(user_id, {}).get(key)

    def set(self, user_id: str, key: str, value: Any) -> None:
        if user_id not in self._store:
            self._store[user_id] = {}
        self._store[user_id][key] = value
        logger.debug(f"UserMemory.set: user={user_id} key={key}")

    def delete(self, user_id: str, key: str) -> bool:
        user_data = self._store.get(user_id, {})
        if key in user_data:
            del user_data[key]
            logger.debug(f"UserMemory.delete: user={user_id} key={key}")
            return True
        return False

    def get_all(self, user_id: str) -> Dict[str, Any]:
        return dict(self._store.get(user_id, {}))


# =============================================================================
# SQL backend (persistent, uses SQLAlchemy)
# =============================================================================

class SQLUserMemory(UserMemory):
    """SQLAlchemy-backed persistent user memory.

    Creates a ``user_memory`` table in the configured database.
    Defaults to SQLite (``user_memory.db``) when no config is provided.

    Config keys (same convention as store.py SQLStore):
        dialect:  e.g. "sqlite", "mysql+pymysql"
        host:     DB host (not needed for sqlite)
        port:     DB port
        db:       Database name / sqlite file path
        username: DB username
        password: DB password
    """

    def __init__(
        self,
        dialect: str = "sqlite",
        host: Optional[str] = None,
        port: Optional[int] = None,
        db: str = "user_memory.db",
        username: Optional[str] = None,
        password: Optional[str] = None,
    ) -> None:
        import sqlalchemy as sa
        from sqlalchemy.orm import DeclarativeBase, sessionmaker

        if dialect == "sqlite":
            url = f"sqlite:///{db}"
        else:
            url = sa.engine.url.URL.create(
                drivername=dialect,
                username=username,
                password=password,
                host=host,
                port=port,
                database=db,
            )

        self._io_lock = threading.RLock()
        options = {}
        if dialect == "sqlite":
            options["connect_args"] = {"check_same_thread": False}
            if db == ":memory:":
                options["poolclass"] = sa.pool.StaticPool
        self._engine = sa.create_engine(url, **options)

        class Base(DeclarativeBase):
            pass

        class _UserMemoryRow(Base):
            __tablename__ = "user_memory"
            id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
            user_id = sa.Column(sa.String(255), nullable=False, index=True)
            key = sa.Column(sa.String(255), nullable=False)
            value = sa.Column(sa.Text, nullable=True)
            updated_at = sa.Column(sa.String(64), nullable=True)
            __table_args__ = (
                sa.UniqueConstraint("user_id", "key", name="uq_user_key"),
            )

        Base.metadata.create_all(self._engine)
        self._session_factory = sessionmaker(bind=self._engine)
        self._Row = _UserMemoryRow
        logger.info(f"SQLUserMemory initialised (dialect={dialect}, db={db})")

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def get(self, user_id: str, key: str) -> Optional[Any]:
        with self._session_factory() as session:
            row = session.query(self._Row).filter_by(
                user_id=user_id, key=key
            ).first()
            if row is None:
                return None
            try:
                return json.loads(row.value)
            except (json.JSONDecodeError, TypeError):
                return row.value

    def set(self, user_id: str, key: str, value: Any) -> None:
        value_str = json.dumps(value, ensure_ascii=False)
        with self._session_factory() as session:
            row = session.query(self._Row).filter_by(
                user_id=user_id, key=key
            ).first()
            if row:
                row.value = value_str
                row.updated_at = self._now()
            else:
                session.add(self._Row(
                    user_id=user_id,
                    key=key,
                    value=value_str,
                    updated_at=self._now(),
                ))
            session.commit()
        logger.debug(f"SQLUserMemory.set: user={user_id} key={key}")

    def delete(self, user_id: str, key: str) -> bool:
        with self._session_factory() as session:
            deleted = session.query(self._Row).filter_by(
                user_id=user_id, key=key
            ).delete()
            session.commit()
        return deleted > 0

    def get_all(self, user_id: str) -> Dict[str, Any]:
        with self._session_factory() as session:
            rows = session.query(self._Row).filter_by(user_id=user_id).all()
            result = {}
            for row in rows:
                try:
                    result[row.key] = json.loads(row.value)
                except (json.JSONDecodeError, TypeError):
                    result[row.key] = row.value
            return result


# =============================================================================
# Factory
# =============================================================================

def create_user_memory(endpoints_config: Dict) -> UserMemory:
    """Create a UserMemory instance from endpoints config.

    If ``base_store.type`` is ``sql``, returns a SQLUserMemory using the
    same DB settings.  Otherwise returns an in-memory MemoryUserMemory.

    Args:
        endpoints_config: Parsed endpoints.yml dict.

    Returns:
        UserMemory instance ready to use.
    """
    store_config = endpoints_config.get("base_store", {})
    store_type = store_config.get("type", "").lower()

    if store_type == "sql":
        # An explicitly configured durable backend must fail visibly; falling
        # back would silently lose or cross-contaminate personalization.
        mem = SQLUserMemory(
            dialect=store_config.get("dialect", "sqlite"),
            host=store_config.get("host"),
            port=store_config.get("port"),
            db=store_config.get("db", "user_memory.db"),
            username=store_config.get("username"),
            password=store_config.get("password"),
        )
        logger.info("UserMemory: using SQL backend")
        return mem

    logger.info("UserMemory: using in-memory backend (no persistence)")
    return MemoryUserMemory()
