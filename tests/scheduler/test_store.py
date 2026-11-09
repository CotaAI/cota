"""Tests for cota.executor.scheduler.store — JobStore (JSON-file based)"""

import os
import pytest
import tempfile
import shutil
from cota.executor.scheduler.types import SchedulerJob, ScheduleConfig
from cota.executor.scheduler.store import JobStore, create_job_store


@pytest.fixture
def store_dir():
    d = tempfile.mkdtemp(prefix="cota_scheduler_test_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def store(store_dir):
    path = os.path.join(store_dir, "jobs.json")
    return JobStore(path)


def _make_job(name="test", schedule_type="at", **kwargs):
    return SchedulerJob(
        name=name,
        schedule=ScheduleConfig(type=schedule_type),
        **kwargs,
    )


class TestJobStore:

    def test_initial_empty(self, store):
        assert store.list_all() == []

    def test_add_and_get(self, store):
        job = _make_job("reminder")
        store.add(job)
        retrieved = store.get(job.id)
        assert retrieved is not None
        assert retrieved.name == "reminder"

    def test_get_nonexistent(self, store):
        assert store.get("nonexistent_id") is None

    def test_list_all(self, store):
        store.add(_make_job("a"))
        store.add(_make_job("b"))
        jobs = store.list_all()
        assert len(jobs) == 2

    def test_remove(self, store):
        job = _make_job("to_delete")
        store.add(job)
        assert store.remove(job.id) is True
        assert store.get(job.id) is None

    def test_remove_nonexistent(self, store):
        assert store.remove("nope") is False

    def test_update(self, store):
        job = _make_job("updatable")
        store.add(job)
        job.name = "updated_name"
        store.update(job)
        retrieved = store.get(job.id)
        assert retrieved.name == "updated_name"

    def test_update_nonexistent(self, store):
        job = _make_job("ghost")
        assert store.update(job) is False

    def test_clear(self, store):
        store.add(_make_job("a"))
        store.add(_make_job("b"))
        store.clear()
        assert store.list_all() == []

    def test_persistence(self, store_dir):
        path = os.path.join(store_dir, "persist.json")
        store1 = JobStore(path)
        job = _make_job("persistent")
        store1.add(job)

        store2 = JobStore(path)
        jobs = store2.list_all()
        assert len(jobs) == 1
        assert jobs[0].name == "persistent"

    def test_list_all_by_user(self, store):
        store.add(_make_job("a", user_id="u1"))
        store.add(_make_job("b", user_id="u2"))
        store.add(_make_job("c", user_id="u1"))
        u1_jobs = store.list_all(user_id="u1")
        assert len(u1_jobs) == 2
        assert all(j.user_id == "u1" for j in u1_jobs)

    def test_corrupt_file_recovery(self, store_dir):
        path = os.path.join(store_dir, "corrupt.json")
        with open(path, "w") as f:
            f.write("{invalid json")
        store = JobStore(path)
        assert store.list_all() == []

    def test_save_atomic(self, store_dir):
        """Verify save uses temp file + rename pattern."""
        path = os.path.join(store_dir, "atomic_test.json")
        store = JobStore(path)
        store.add(_make_job("atomtest"))
        assert os.path.isfile(path)
        assert not os.path.isfile(path + ".tmp")


class TestCreateJobStore:

    def test_create_json_store(self, store_dir):
        store = create_job_store()
        assert isinstance(store, JobStore)
