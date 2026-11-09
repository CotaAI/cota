"""Tests for cota.executor.scheduler.types"""

from cota.executor.scheduler.types import (
    ScheduleConfig,
    PreCheckConfig,
    SchedulerJob,
)


class TestScheduleConfig:

    def test_at_config(self):
        c = ScheduleConfig(type="at", at="2025-01-01T12:00:00")
        assert c.type == "at"
        assert c.at == "2025-01-01T12:00:00"

    def test_every_config(self):
        c = ScheduleConfig(type="every", every_seconds=60.0)
        assert c.every_seconds == 60.0

    def test_cron_config(self):
        c = ScheduleConfig(type="cron", expr="0 12 * * *", tz="Asia/Shanghai")
        assert c.expr == "0 12 * * *"
        assert c.tz == "Asia/Shanghai"

    def test_to_dict_minimal(self):
        c = ScheduleConfig(type="at")
        d = c.to_dict()
        assert d == {"type": "at"}

    def test_to_dict_full(self):
        c = ScheduleConfig(type="cron", expr="*/5 * * * *", tz="UTC")
        d = c.to_dict()
        assert d["type"] == "cron"
        assert d["expr"] == "*/5 * * * *"
        assert d["tz"] == "UTC"

    def test_from_dict(self):
        d = {"type": "every", "every_seconds": 30}
        c = ScheduleConfig.from_dict(d)
        assert c.type == "every"
        assert c.every_seconds == 30

    def test_from_dict_defaults(self):
        c = ScheduleConfig.from_dict({})
        assert c.type == "at"


class TestPreCheckConfig:

    def test_defaults(self):
        c = PreCheckConfig()
        assert c.command == ""
        assert c.timeout == 15

    def test_to_dict_minimal(self):
        c = PreCheckConfig(command="check.sh")
        d = c.to_dict()
        assert d["command"] == "check.sh"
        assert "timeout" not in d  # default not serialized

    def test_to_dict_full(self):
        c = PreCheckConfig(
            command="check.sh",
            cwd="/tmp",
            env={"API_KEY": "xxx"},
            state_file="/tmp/state.json",
            timeout=30,
        )
        d = c.to_dict()
        assert d["cwd"] == "/tmp"
        assert d["timeout"] == 30

    def test_from_dict_roundtrip(self):
        original = PreCheckConfig(command="test.sh", cwd="/home", timeout=20)
        restored = PreCheckConfig.from_dict(original.to_dict())
        assert restored.command == "test.sh"
        assert restored.cwd == "/home"
        assert restored.timeout == 20


class TestSchedulerJob:

    def test_auto_id(self):
        job = SchedulerJob(name="test")
        assert len(job.id) == 12
        assert job.created_at > 0

    def test_explicit_id(self):
        job = SchedulerJob(id="custom_id_123", name="test")
        assert job.id == "custom_id_123"

    def test_to_dict(self):
        job = SchedulerJob(
            id="j1",
            name="reminder",
            user_id="u1",
            schedule=ScheduleConfig(type="every", every_seconds=60),
            payload={"text": "吃饭提醒"},
            session_id="s1",
        )
        d = job.to_dict()
        assert d["id"] == "j1"
        assert d["name"] == "reminder"
        assert d["user_id"] == "u1"
        assert d["schedule"]["type"] == "every"
        assert d["payload"]["text"] == "吃饭提醒"
        assert "pre_check" not in d

    def test_to_dict_with_precheck(self):
        job = SchedulerJob(
            name="watcher",
            pre_check=PreCheckConfig(command="check.sh"),
        )
        d = job.to_dict()
        assert "pre_check" in d
        assert d["pre_check"]["command"] == "check.sh"

    def test_from_dict_roundtrip(self):
        original = SchedulerJob(
            name="test_job",
            user_id="u1",
            schedule=ScheduleConfig(type="cron", expr="0 9 * * *"),
            payload={"text": "morning"},
            pre_check=PreCheckConfig(command="pre.sh"),
        )
        d = original.to_dict()
        restored = SchedulerJob.from_dict(d)
        assert restored.name == "test_job"
        assert restored.schedule.type == "cron"
        assert restored.schedule.expr == "0 9 * * *"
        assert restored.pre_check is not None
        assert restored.pre_check.command == "pre.sh"

    def test_from_dict_defaults(self):
        job = SchedulerJob.from_dict({})
        assert job.schedule.type == "at"
        assert job.enabled is True
        assert job.pre_check is None

    def test_summary_at(self):
        job = SchedulerJob(
            id="abc",
            name="once",
            schedule=ScheduleConfig(type="at", at="2025-12-31T23:59:00"),
        )
        s = job.summary()
        assert "abc" in s
        assert "once" in s
        assert "one-shot" in s

    def test_summary_every(self):
        job = SchedulerJob(
            id="def",
            name="ticker",
            schedule=ScheduleConfig(type="every", every_seconds=10),
        )
        assert "every 10" in job.summary()

    def test_summary_cron(self):
        job = SchedulerJob(
            id="ghi",
            name="daily",
            schedule=ScheduleConfig(type="cron", expr="0 9 * * *", tz="UTC"),
        )
        s = job.summary()
        assert "cron" in s
        assert "UTC" in s

    def test_summary_watcher(self):
        job = SchedulerJob(
            name="watch",
            pre_check=PreCheckConfig(command="check.sh"),
        )
        assert "[watcher]" in job.summary()

    def test_summary_disabled(self):
        job = SchedulerJob(name="off", enabled=False)
        assert "disabled" in job.summary()
