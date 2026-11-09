"""Failed scheduler mutations leave the last committed view intact."""

import json
from dataclasses import replace

import pytest

from cota.executor.scheduler.service import SchedulerService
from cota.executor.scheduler.store import JobStore, SQLJobStore
from cota.executor.scheduler.types import SchedulerJob


@pytest.fixture(params=["json", "sql"])
def store(request, tmp_path):
    if request.param == "json":
        yield JobStore(str(tmp_path / "jobs.json"))
    else:
        value = SQLJobStore(db=str(tmp_path / "jobs.db"))
        yield value
        value._engine.dispose()


def fail_writes(store, monkeypatch):
    def fail(*args, **kwargs):
        raise OSError("persistence unavailable")

    if isinstance(store, JobStore):
        monkeypatch.setattr(store, "save", fail)
    else:
        # Fail the real transaction at commit, exercising its rollback path.
        monkeypatch.setattr(store._session_factory.class_, "commit", fail)


async def test_invalid_update_preserves_original_job(store):
    service = SchedulerService(store=store)
    job = await service.add_job(
        "original", {"type": "every", "every_seconds": 10}, {"nested": {"a": 1}}
    )
    original = job.to_dict()
    with pytest.raises(ValueError):
        await service.update_job(
            job.id, name="changed", schedule={"type": "every", "every_seconds": -1}
        )
    assert job.to_dict() == original
    assert store.get(job.id).to_dict() == original


async def test_failed_update_preserves_cache_and_disk(store, monkeypatch):
    service = SchedulerService(store=store)
    job = await service.add_job("original", {"type": "every", "every_seconds": 10}, {})
    original = job.to_dict()
    with monkeypatch.context() as scoped:
        fail_writes(store, scoped)
        with pytest.raises(OSError, match="persistence unavailable"):
            await service.update_job(
                job.id, name="changed", payload={"new": 1}, enabled=False
            )
        assert job.to_dict() == original
        assert store.get(job.id).to_dict() == original
    store.load()
    assert store.get(job.id).to_dict() == original


@pytest.mark.parametrize("action", ["add", "update", "remove", "clear"])
def test_store_mutation_failure_preserves_cache_and_disk(store, monkeypatch, action):
    original = SchedulerJob(name="original")
    store.add(original)
    candidate = replace(original, name="changed")
    with monkeypatch.context() as scoped:
        fail_writes(store, scoped)
        with pytest.raises(OSError):
            if action == "add":
                store.add(candidate)
            elif action == "update":
                store.update(candidate)
            elif action == "remove":
                store.remove(original.id)
            else:
                store.clear()
        assert store.get(original.id) is original
    store.load()
    assert store.get(original.id).name == "original"


@pytest.mark.parametrize(
    "document", [[], None, 7, {"jobs": None}, {"jobs": {}}, {"jobs": "invalid"}]
)
def test_json_invalid_container_reports_error_without_replacing_cache(
    tmp_path, document
):
    path = tmp_path / "jobs.json"
    store = JobStore(str(path))
    original = SchedulerJob(name="original")
    store.add(original)
    path.write_text(json.dumps(document))
    with pytest.raises(ValueError, match="scheduler store"):
        store.load()
    assert store.get(original.id) is original
    assert json.loads(path.read_text()) == document


async def test_callback_completion_preserves_concurrent_job_update(store):
    import asyncio

    service = SchedulerService(store=store)
    started, finish = asyncio.Event(), asyncio.Event()

    async def callback(job):
        started.set()
        await finish.wait()

    service.set_callback(callback)
    job = await service.add_job("original", {"type": "every", "every_seconds": 10}, {})
    await service.trigger_job(job.id)
    await started.wait()
    await service.update_job(job.id, name="changed", payload={"new": 1})
    finish.set()
    await asyncio.gather(*service._callback_tasks)
    assert store.get(job.id).name == "changed"
    assert store.get(job.id).payload == {"new": 1}
    assert store.get(job.id).last_status == "ok"
    await service.stop()


@pytest.mark.parametrize("action", ["trigger", "tick", "precheck"])
@pytest.mark.parametrize("one_shot", [False, True])
async def test_failed_dispatch_persistence_never_runs_callback(
    store, monkeypatch, action, one_shot
):
    import asyncio
    from unittest.mock import AsyncMock

    service = SchedulerService(store=store)
    callback = AsyncMock()
    service.set_callback(callback)
    schedule = (
        {"type": "at", "at": "+1m"}
        if one_shot
        else {"type": "every", "every_seconds": 10}
    )
    job = await service.add_job(
        "original",
        schedule,
        {},
        pre_check={"command": "test"} if action == "precheck" else None,
    )
    if action != "trigger":
        job.next_run_at = 0
        store.update(job)
    before = job.to_dict()
    service._run_pre_check = AsyncMock(return_value={"has_new": True})
    try:
        with monkeypatch.context() as scoped:
            fail_writes(store, scoped)
            with pytest.raises(OSError, match="persistence unavailable"):
                if action == "trigger":
                    await service.trigger_job(job.id)
                else:
                    await service._tick()
            await asyncio.gather(*service._callback_tasks, return_exceptions=True)
            callback.assert_not_awaited()
            assert not service._busy_jobs
            assert store.get(job.id).to_dict() == before
        store.load()
        assert store.get(job.id).to_dict() == before
    finally:
        await service.stop()
