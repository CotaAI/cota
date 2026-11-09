"""Job persistence store — JSON file and SQL backends.

Two backends:
  - JobStore (JSON file): original implementation, good for personal mode
  - SQLJobStore (SQLAlchemy): persistent DB backend for RaaS service mode

Factory: create_job_store(endpoints_config) picks the right backend.
"""

import json
import logging
import os
from abc import ABC, abstractmethod
from typing import Dict, List, Optional

from .types import SchedulerJob

logger = logging.getLogger(__name__)

DEFAULT_STORE_FILE = "scheduler_jobs.json"


# =============================================================================
# Abstract base
# =============================================================================

class BaseJobStore(ABC):
    """Abstract job persistence store."""

    @abstractmethod
    def load(self) -> None:
        """Load jobs from backend."""

    @abstractmethod
    def save(self) -> None:
        """Persist all jobs."""

    @abstractmethod
    def get(self, job_id: str) -> Optional[SchedulerJob]:
        """Get a job by ID."""

    @abstractmethod
    def list_all(self, user_id: Optional[str] = None) -> List[SchedulerJob]:
        """List jobs, optionally filtered by user_id."""

    @abstractmethod
    def add(self, job: SchedulerJob) -> None:
        """Add or update a job."""

    @abstractmethod
    def remove(self, job_id: str) -> bool:
        """Remove a job by ID. Returns True if found and removed."""

    @abstractmethod
    def update(self, job: SchedulerJob) -> bool:
        """Update an existing job. Returns True if found."""

    @abstractmethod
    def clear(self) -> None:
        """Remove all jobs."""


# =============================================================================
# JSON file backend (original, backward compatible)
# =============================================================================

class JobStore(BaseJobStore):
    """Persist scheduler jobs to a JSON file.

    Thread-safe for single-process async usage (no file locking needed
    since cota runs in a single asyncio event loop).
    """

    def __init__(self, path: str = DEFAULT_STORE_FILE):
        self._path = path
        self._jobs: Dict[str, SchedulerJob] = {}
        self._loaded = False

    @property
    def path(self) -> str:
        return self._path

    def load(self) -> None:
        """Load jobs from disk."""
        if not os.path.isfile(self._path):
            logger.debug(f"No scheduler store file at {self._path}, starting empty")
            self._jobs = {}
            self._loaded = True
            return

        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"Failed to load scheduler store {self._path}: {e}")
            self._jobs = {}
            self._loaded = True
            return

        if not isinstance(data, dict):
            raise ValueError("Invalid scheduler store: expected a JSON object")
        jobs_raw = data.get("jobs", [])
        if not isinstance(jobs_raw, list):
            raise ValueError("Invalid scheduler store: jobs must be a list")
        self._jobs = {}
        for raw in jobs_raw:
            try:
                job = SchedulerJob.from_dict(raw)
                self._jobs[job.id] = job
            except Exception as e:
                logger.warning(f"Skipping malformed job: {e}")

        self._loaded = True
        logger.info(f"Loaded {len(self._jobs)} scheduler jobs from {self._path}")

    def save(self) -> None:
        """Persist all jobs to disk."""
        data = {
            "version": 1,
            "jobs": [job.to_dict() for job in self._jobs.values()],
        }
        try:
            # Write to temp file first, then rename for atomicity
            tmp_path = self._path + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self._path)
            logger.debug(f"Saved {len(self._jobs)} jobs to {self._path}")
        except OSError as e:
            logger.error(f"Failed to save scheduler store: {e}")
            raise

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self.load()

    def get(self, job_id: str) -> Optional[SchedulerJob]:
        self._ensure_loaded()
        return self._jobs.get(job_id)

    def list_all(self, user_id: Optional[str] = None) -> List[SchedulerJob]:
        self._ensure_loaded()
        jobs = list(self._jobs.values())
        if user_id is not None:
            jobs = [j for j in jobs if j.user_id == user_id]
        return jobs

    def add(self, job: SchedulerJob) -> None:
        self._ensure_loaded()
        previous = dict(self._jobs)
        self._jobs[job.id] = job
        try:
            self.save()
        except Exception:
            self._jobs = previous
            raise

    def remove(self, job_id: str) -> bool:
        self._ensure_loaded()
        if job_id in self._jobs:
            previous = self._jobs.pop(job_id)
            try:
                self.save()
            except Exception:
                self._jobs[job_id] = previous
                raise
            return True
        return False

    def update(self, job: SchedulerJob) -> bool:
        self._ensure_loaded()
        if job.id in self._jobs:
            self.add(job)
            return True
        return False

    def clear(self) -> None:
        self._ensure_loaded()
        previous = self._jobs
        self._jobs = {}
        try:
            self.save()
        except Exception:
            self._jobs = previous
            raise


# =============================================================================
# SQL backend (persistent, uses SQLAlchemy)
# =============================================================================

class SQLJobStore(BaseJobStore):
    """SQLAlchemy-backed persistent job store.

    Creates a ``scheduler_jobs`` table in the configured database.
    All jobs are stored with user_id for multi-user isolation.

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
        db: str = "scheduler_jobs.db",
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

        self._engine = sa.create_engine(url)

        class Base(DeclarativeBase):
            pass

        class _SchedulerJobRow(Base):
            __tablename__ = "scheduler_jobs"
            id = sa.Column(sa.String(32), primary_key=True)
            user_id = sa.Column(sa.String(255), nullable=False, index=True, default="")
            name = sa.Column(sa.String(255), nullable=False, default="")
            data = sa.Column(sa.Text, nullable=False)  # Full job dict as JSON

        Base.metadata.create_all(self._engine)
        self._session_factory = sessionmaker(bind=self._engine)
        self._Row = _SchedulerJobRow
        # In-memory cache for fast iteration in the scheduler tick loop
        self._jobs: Dict[str, SchedulerJob] = {}
        self._loaded = False
        logger.info(f"SQLJobStore initialised (dialect={dialect}, db={db})")

    def load(self) -> None:
        """Load all jobs from DB into memory cache."""
        with self._session_factory() as session:
            rows = session.query(self._Row).all()
            self._jobs = {}
            for row in rows:
                try:
                    d = json.loads(row.data)
                    job = SchedulerJob.from_dict(d)
                    self._jobs[job.id] = job
                except Exception as e:
                    logger.warning(f"Skipping malformed job row {row.id}: {e}")
        self._loaded = True
        logger.info(f"SQLJobStore: loaded {len(self._jobs)} jobs from DB")

    def save(self) -> None:
        """Persist all in-memory jobs to DB (full sync)."""
        with self._session_factory() as session:
            # Clear and re-insert (simple, safe for moderate job counts)
            session.query(self._Row).delete()
            for job in self._jobs.values():
                session.add(self._Row(
                    id=job.id,
                    user_id=job.user_id,
                    name=job.name,
                    data=json.dumps(job.to_dict(), ensure_ascii=False),
                ))
            session.commit()

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self.load()

    def get(self, job_id: str) -> Optional[SchedulerJob]:
        self._ensure_loaded()
        return self._jobs.get(job_id)

    def list_all(self, user_id: Optional[str] = None) -> List[SchedulerJob]:
        self._ensure_loaded()
        jobs = list(self._jobs.values())
        if user_id is not None:
            jobs = [j for j in jobs if j.user_id == user_id]
        return jobs

    def add(self, job: SchedulerJob) -> None:
        self._ensure_loaded()
        self._persist_one(job)
        self._jobs[job.id] = job

    def remove(self, job_id: str) -> bool:
        self._ensure_loaded()
        if job_id in self._jobs:
            self._delete_one(job_id)
            del self._jobs[job_id]
            return True
        return False

    def update(self, job: SchedulerJob) -> bool:
        self._ensure_loaded()
        if job.id in self._jobs:
            self._persist_one(job)
            self._jobs[job.id] = job
            return True
        return False

    def clear(self) -> None:
        with self._session_factory() as session:
            session.query(self._Row).delete()
            session.commit()
        self._jobs = {}

    def _persist_one(self, job: SchedulerJob) -> None:
        """Upsert a single job to DB."""
        with self._session_factory() as session:
            row = session.query(self._Row).filter_by(id=job.id).first()
            data_str = json.dumps(job.to_dict(), ensure_ascii=False)
            if row:
                row.user_id = job.user_id
                row.name = job.name
                row.data = data_str
            else:
                session.add(self._Row(
                    id=job.id,
                    user_id=job.user_id,
                    name=job.name,
                    data=data_str,
                ))
            session.commit()

    def _delete_one(self, job_id: str) -> None:
        """Delete a single job from DB."""
        with self._session_factory() as session:
            session.query(self._Row).filter_by(id=job_id).delete()
            session.commit()


# =============================================================================
# Factory
# =============================================================================

def create_job_store(endpoints_config: Dict = None) -> BaseJobStore:
    """Create a JobStore instance from endpoints config.

    If ``base_store.type`` is ``sql``, returns a SQLJobStore using the
    same DB settings. Otherwise returns a JSON file-based JobStore.

    Args:
        endpoints_config: Parsed endpoints.yml dict. None for default.

    Returns:
        BaseJobStore instance ready to use.
    """
    if endpoints_config is None:
        return JobStore()

    store_config = endpoints_config.get("base_store", {})
    store_type = store_config.get("type", "").lower()

    if store_type == "sql":
        return SQLJobStore(
            dialect=store_config.get("dialect", "sqlite"),
            host=store_config.get("host"),
            port=store_config.get("port"),
            db=store_config.get("db", "scheduler_jobs.db"),
            username=store_config.get("username"),
            password=store_config.get("password"),
        )

    logger.info("JobStore: using JSON file backend")
    return JobStore()
