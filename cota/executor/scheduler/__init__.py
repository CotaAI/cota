"""Scheduler module for cota.

Provides timed job execution: one-shot (at), recurring (every/cron).
Inspired by OpenClaw's cron system.

Usage:
    from cota.executor.scheduler import SchedulerService, SchedulerJob

    service = SchedulerService(store_path="scheduler_jobs.json")
    await service.start()
    await service.add_job(...)
    # ... service runs in background, triggers callbacks on schedule
    await service.stop()

Service registration:
    from cota.executor.scheduler import set_scheduler_service, get_scheduler_service

    set_scheduler_service(service)   # call once at startup
    svc = get_scheduler_service()    # retrieve from anywhere
"""

from .types import SchedulerJob, ScheduleConfig, PreCheckConfig
from .store import JobStore, SQLJobStore, BaseJobStore, create_job_store
from .service import SchedulerService

# ---------------------------------------------------------------------------
# Global service accessor — one place to register / retrieve the singleton
# ---------------------------------------------------------------------------

_scheduler_service = None


def set_scheduler_service(service) -> None:
    """Set the global SchedulerService instance (called once at startup)."""
    global _scheduler_service
    _scheduler_service = service


def get_scheduler_service():
    """Get the global SchedulerService instance."""
    return _scheduler_service


__all__ = [
    "SchedulerJob",
    "ScheduleConfig",
    "PreCheckConfig",
    "JobStore",
    "SQLJobStore",
    "BaseJobStore",
    "create_job_store",
    "SchedulerService",
    "set_scheduler_service",
    "get_scheduler_service",
]
