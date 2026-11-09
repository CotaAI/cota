import asyncio
from unittest.mock import AsyncMock

import pytest

from cota.executor.scheduler import SchedulerService
from cota.executor.scheduler.store import JobStore, create_job_store
from cota.executor.scheduler.types import PreCheckConfig


@pytest.fixture
def service(tmp_path):
    return SchedulerService(store_path=str(tmp_path / "jobs.json"))


async def test_trigger_reserves_job_and_stop_awaits_callbacks(service):
    started, finished = asyncio.Event(), asyncio.Event()

    async def callback(job):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            finished.set()

    service.set_callback(callback)
    job = await service.add_job("a", {"type": "every", "every_seconds": 10}, {})
    try:
        assert await service.trigger_job(job.id)
        assert not await service.trigger_job(job.id)
        await started.wait()
        assert service.store.get(job.id).run_count == 1
    finally:
        await service.stop()
    assert finished.is_set()
    assert not service._busy_jobs


async def test_missing_callback_does_not_count_or_consume_one_shot(service):
    job = await service.add_job("a", {"type": "at", "at": "+1m"}, {})
    assert not await service.trigger_job(job.id)
    assert job.run_count == 0
    assert service.store.get(job.id)
    job.next_run_at = 0
    await service._tick()
    assert job.run_count == 0
    assert service.store.get(job.id)


async def test_manual_one_shot_consumed_and_schedule_change_clears_flag(service):
    service.set_callback(AsyncMock())
    first = await service.add_job("a", {"type": "at", "at": "+1m"}, {})
    assert await service.trigger_job(first.id)
    assert not await service.trigger_job(first.id)
    second = await service.add_job("b", {"type": "at", "at": "+1m"}, {})
    await service.update_job(second.id, schedule={"type": "every", "every_seconds": 10})
    assert not service.store.get(second.id).delete_after_run
    await service.stop()


@pytest.mark.parametrize(
    "schedule",
    [
        {"type": "every", "every_seconds": -1},
        {"type": "every", "every_seconds": 0},
        {"type": "every", "every_seconds": float("nan")},
        {"type": "cron", "expr": "bad"},
        {"type": "cron", "expr": "* * * * *", "tz": "Bad/Zone"},
        {"type": "at", "at": "bad"},
        {"type": "at", "at": "+-3m"},
        {"type": "unknown"},
    ],
)
async def test_invalid_schedule_rejected(service, schedule):
    with pytest.raises(ValueError):
        await service.add_job("bad", schedule, {})


async def test_scheduler_status_filters_by_owner(service):
    own = await service.add_job('own', {'type': 'every', 'every_seconds': 10}, {}, user_id='alice')
    await service.add_job('other', {'type': 'every', 'every_seconds': 10}, {}, user_id='bob')
    await service.add_job('orphan', {'type': 'every', 'every_seconds': 10}, {})
    status = await service.get_status(user_id='alice')
    assert status['total_jobs'] == 1
    assert [job['id'] for job in status['jobs']] == [own.id]


def test_store_write_failure_rolls_back(tmp_path):
    from cota.executor.scheduler.types import SchedulerJob

    store = JobStore(str(tmp_path / "missing" / "jobs.json"))
    job = SchedulerJob(name="a")
    with pytest.raises(OSError):
        store.add(job)
    assert store.get(job.id) is None


def test_sql_failure_is_not_silently_downgraded(monkeypatch):
    def fail(**kwargs):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr("cota.executor.scheduler.store.SQLJobStore", fail)
    with pytest.raises(RuntimeError, match="database unavailable"):
        create_job_store({"base_store": {"type": "sql"}})


async def test_precheck_timeout_reaps_child(service, monkeypatch):
    class Process:
        returncode = None
        killed = False
        waited = False

        async def communicate(self):
            await asyncio.Event().wait()

        def kill(self):
            self.killed = True

        async def wait(self):
            self.waited = True

    process = Process()
    monkeypatch.setattr(
        asyncio, "create_subprocess_exec", AsyncMock(return_value=process)
    )
    assert (
        await service._run_pre_check(PreCheckConfig(command="test", timeout=0.001))
        is None
    )
    assert process.killed and process.waited


def test_unimplemented_trigger_job_name_rejected():
    with pytest.raises(ValueError, match="trigger_job_name"):
        PreCheckConfig.from_dict({"command": "test", "trigger_job_name": "other"})


async def test_due_precheck_without_callback_is_not_consumed(service):
    job = await service.add_job(
        "watch", {"type": "at", "at": "+1m"}, {}, pre_check={"command": "check"}
    )
    job.next_run_at = 0
    service._run_pre_check = AsyncMock(return_value={"has_new": True})
    await service._tick()
    assert job.run_count == 0
    assert service.store.get(job.id) is job


@pytest.mark.parametrize("action", ["remove", "clear"])
def test_json_mutation_failure_preserves_cached_jobs(tmp_path, monkeypatch, action):
    from cota.executor.scheduler.types import SchedulerJob

    store = JobStore(str(tmp_path / "jobs.json"))
    job = SchedulerJob(name="a")
    store.add(job)

    def fail():
        raise OSError("disk full")

    monkeypatch.setattr(store, "save", fail)
    with pytest.raises(OSError):
        if action == "remove":
            store.remove(job.id)
        else:
            store.clear()
    assert store.get(job.id) is job


async def test_cancelled_precheck_reaps_child(service, monkeypatch):
    started = asyncio.Event()

    class Process:
        returncode = None
        killed = False
        waited = False

        async def communicate(self):
            started.set()
            await asyncio.Event().wait()

        def kill(self):
            self.killed = True

        async def wait(self):
            self.waited = True

    process = Process()
    monkeypatch.setattr(
        asyncio, "create_subprocess_exec", AsyncMock(return_value=process)
    )
    task = asyncio.create_task(service._run_pre_check(PreCheckConfig(command="check")))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert process.killed and process.waited
