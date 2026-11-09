"""Scheduler types and data structures.

Inspired by OpenClaw's CronJob types with three schedule kinds:
- at: one-shot at a specific time
- every: repeating at fixed intervals
- cron: standard cron expressions

Extended with PreCheckConfig for watcher-style jobs that run a lightweight
script before deciding whether to fire the full callback.
"""

import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, Any, Optional


@dataclass
class ScheduleConfig:
    """Schedule configuration.

    Attributes:
        type: Schedule type — "at", "every", or "cron"
        at: ISO 8601 datetime string for one-shot (type="at")
        every_seconds: Interval in seconds for recurring (type="every")
        expr: Cron expression string (type="cron"), e.g. "0 12 * * *"
        tz: Timezone name, e.g. "Asia/Shanghai" (default: local)
    """
    type: str  # "at", "every", "cron"
    at: Optional[str] = None
    every_seconds: Optional[float] = None
    expr: Optional[str] = None
    tz: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = {"type": self.type}
        if self.at is not None:
            d["at"] = self.at
        if self.every_seconds is not None:
            d["every_seconds"] = self.every_seconds
        if self.expr is not None:
            d["expr"] = self.expr
        if self.tz is not None:
            d["tz"] = self.tz
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ScheduleConfig":
        return cls(
            type=d.get("type", "at"),
            at=d.get("at"),
            every_seconds=d.get("every_seconds"),
            expr=d.get("expr"),
            tz=d.get("tz"),
        )


@dataclass
class PreCheckConfig:
    """Pre-check configuration for watcher-style jobs.

    When a job has a pre_check, the scheduler runs a lightweight shell command
    DIRECTLY (no LLM, no agent pipeline) before firing the job callback.

    The command must output a JSON line to stdout with at least {"has_new": bool}.
    - If has_new is false → callback is SKIPPED (zero cost).
    - If has_new is true → the normal callback fires.

    This enables high-frequency polling (every 5-10s) at near-zero cost,
    because most checks will return has_new=false and skip the heavy LLM path.

    Attributes:
        command: Shell command to run (e.g. "xianyu-check-new-messages.sh")
        cwd: Working directory for the command
        env: Additional environment variables
        state_file: Path to persist last check state (JSON). Used for
                    deduplication: if the check result is identical to the
                    saved state, treat it as has_new=false.
        timeout: Command timeout in seconds (default 15)
    """
    command: str = ""
    cwd: str = ""
    env: Dict[str, str] = field(default_factory=dict)
    state_file: str = ""
    timeout: int = 15

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"command": self.command}
        if self.cwd:
            d["cwd"] = self.cwd
        if self.env:
            d["env"] = self.env
        if self.state_file:
            d["state_file"] = self.state_file
        if self.timeout != 15:
            d["timeout"] = self.timeout
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "PreCheckConfig":
        if d.get("trigger_job_name"):
            raise ValueError("trigger_job_name is unsupported; use this job payload instead")
        return cls(
            command=d.get("command", ""),
            cwd=d.get("cwd", ""),
            env=d.get("env", {}),
            state_file=d.get("state_file", ""),
            timeout=d.get("timeout", 15),
        )


@dataclass
class SchedulerJob:
    """A scheduled job.

    Attributes:
        id: Unique job identifier
        name: Human-readable name
        user_id: Owner user ID (for multi-user isolation in RaaS mode)
        schedule: Schedule configuration
        payload: Arbitrary data dict (e.g. {"text": "吃饭提醒"})
        enabled: Whether the job is active
        delete_after_run: If True, auto-delete after first execution (for "at" jobs)
        session_id: Target session to deliver the message to
        created_at: Unix timestamp when created
        next_run_at: Unix timestamp of next scheduled run
        last_run_at: Unix timestamp of last run (None if never)
        last_status: "ok", "error", or None
        run_count: Total number of times this job has run
        pre_check: Optional pre-check config. When set, the scheduler runs
                   a lightweight script before firing the callback. If the
                   script returns no changes, the callback is skipped entirely.
    """
    id: str = ""
    name: str = ""
    user_id: str = ""
    schedule: ScheduleConfig = field(default_factory=lambda: ScheduleConfig(type="at"))
    payload: Dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    delete_after_run: bool = False
    session_id: str = "default"
    created_at: float = 0.0
    next_run_at: Optional[float] = None
    last_run_at: Optional[float] = None
    last_status: Optional[str] = None
    run_count: int = 0
    pre_check: Optional[PreCheckConfig] = None

    def __post_init__(self):
        if not self.id:
            self.id = uuid.uuid4().hex[:12]
        if not self.created_at:
            self.created_at = time.time()

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "id": self.id,
            "name": self.name,
            "user_id": self.user_id,
            "schedule": self.schedule.to_dict() if isinstance(self.schedule, ScheduleConfig) else self.schedule,
            "payload": self.payload,
            "enabled": self.enabled,
            "delete_after_run": self.delete_after_run,
            "session_id": self.session_id,
            "created_at": self.created_at,
            "next_run_at": self.next_run_at,
            "last_run_at": self.last_run_at,
            "last_status": self.last_status,
            "run_count": self.run_count,
        }
        if self.pre_check:
            d["pre_check"] = self.pre_check.to_dict()
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "SchedulerJob":
        schedule_raw = d.get("schedule", {"type": "at"})
        if isinstance(schedule_raw, dict):
            schedule = ScheduleConfig.from_dict(schedule_raw)
        else:
            schedule = ScheduleConfig(type="at")

        pre_check_raw = d.get("pre_check")
        pre_check = PreCheckConfig.from_dict(pre_check_raw) if pre_check_raw else None

        return cls(
            id=d.get("id", ""),
            name=d.get("name", ""),
            user_id=d.get("user_id", ""),
            schedule=schedule,
            payload=d.get("payload", {}),
            enabled=d.get("enabled", True),
            delete_after_run=d.get("delete_after_run", False),
            session_id=d.get("session_id", "default"),
            created_at=d.get("created_at", 0.0),
            next_run_at=d.get("next_run_at"),
            last_run_at=d.get("last_run_at"),
            last_status=d.get("last_status"),
            run_count=d.get("run_count", 0),
            pre_check=pre_check,
        )

    def summary(self) -> str:
        """Human-readable summary for LLM output."""
        sched = self.schedule
        if sched.type == "at":
            schedule_desc = f"one-shot at {sched.at}"
        elif sched.type == "every":
            schedule_desc = f"every {sched.every_seconds}s"
        elif sched.type == "cron":
            tz_str = f" ({sched.tz})" if sched.tz else ""
            schedule_desc = f"cron '{sched.expr}'{tz_str}"
        else:
            schedule_desc = str(sched.to_dict())

        status = "enabled" if self.enabled else "disabled"
        pre_check_desc = " [watcher]" if self.pre_check else ""
        user_desc = f" user={self.user_id}" if self.user_id else ""
        return (
            f"[{self.id}] {self.name} — {schedule_desc} — {status} "
            f"— runs: {self.run_count}{pre_check_desc}{user_desc}"
        )
