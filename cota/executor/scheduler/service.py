"""Scheduler service — background asyncio task that triggers jobs on schedule.

Inspired by OpenClaw's cron service. Runs a single background loop that
checks for due jobs every second.

When a job fires, it invokes a callback (typically sending a message
through the Processor so the bot can respond).

Extended with pre_check support: watcher-style jobs run a lightweight
shell script before firing the callback. If the script returns
{"has_new": false}, the callback is skipped entirely (zero LLM cost).

Callbacks are always fired in the BACKGROUND (non-blocking) to prevent
long-running skills (e.g. CustomerService) from blocking the scheduler
tick loop. A per-job lock prevents concurrent callback executions.
"""

import asyncio
import json as _json
import logging
import math
import os
import shlex
import signal
import time
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Callable, Awaitable, Dict, List, Optional, Set

from .types import SchedulerJob, ScheduleConfig, PreCheckConfig
from .store import JobStore, BaseJobStore

logger = logging.getLogger(__name__)

# Type for the callback invoked when a job fires
# Signature: async def callback(job: SchedulerJob) -> None
JobCallback = Callable[[SchedulerJob], Awaitable[None]]


def _parse_iso_to_timestamp(iso_str: str, tz_name: Optional[str] = None) -> Optional[float]:
    """Parse an ISO 8601 datetime string to a Unix timestamp.

    Supports:
    - Full ISO: "2026-02-10T14:00:00+08:00"
    - Date only: "2026-02-10" (assumes midnight in tz or UTC)
    - Relative: "+5m", "+1h", "+30s" (from now)
    """
    if not iso_str:
        return None

    # Handle relative time: "+5m", "+1h", "+30s"
    s = iso_str.strip()
    if s.startswith("+") and len(s) >= 2:
        unit = s[-1]
        try:
            value = float(s[1:-1])
        except ValueError:
            pass
        else:
            multipliers = {"s": 1, "m": 60, "h": 3600, "d": 86400}
            if unit in multipliers:
                return time.time() + value * multipliers[unit]

    # Try standard ISO parse
    try:
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            # Apply timezone if provided
            if tz_name:
                try:
                    import zoneinfo
                    tz = zoneinfo.ZoneInfo(tz_name)
                    dt = dt.replace(tzinfo=tz)
                except Exception:
                    dt = dt.replace(tzinfo=timezone.utc)
            else:
                dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except (ValueError, TypeError):
        pass

    return None


def _compute_next_run(schedule: ScheduleConfig, now: float) -> Optional[float]:
    """Compute the next run timestamp for a schedule.

    Args:
        schedule: The schedule configuration
        now: Current Unix timestamp

    Returns:
        Next run timestamp, or None if no future run
    """
    if schedule.type == "at":
        at_ts = _parse_iso_to_timestamp(schedule.at or "", schedule.tz)
        if at_ts is None:
            return None
        return at_ts if at_ts > now else None

    elif schedule.type == "every":
        interval = schedule.every_seconds or 60
        return now + interval

    elif schedule.type == "cron":
        expr = (schedule.expr or "").strip()
        if not expr:
            return None
        try:
            from croniter import croniter
            tz = None
            if schedule.tz:
                try:
                    import zoneinfo
                    tz = zoneinfo.ZoneInfo(schedule.tz)
                except Exception:
                    pass
            base_dt = datetime.fromtimestamp(now, tz=tz or timezone.utc)
            cron = croniter(expr, base_dt)
            next_dt = cron.get_next(datetime)
            return next_dt.timestamp()
        except Exception as e:
            logger.error(f"Failed to parse cron expression '{expr}': {e}")
            return None

    return None


def _validated_schedule(data):
    schedule = ScheduleConfig.from_dict(data)
    if schedule.tz:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
        try:
            ZoneInfo(schedule.tz)
        except (ZoneInfoNotFoundError, ValueError, TypeError) as exc:
            raise ValueError("Invalid schedule timezone") from exc
    if schedule.type == "every":
        value = schedule.every_seconds
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError("every_seconds must be a finite positive number")
    elif schedule.type == "cron":
        from croniter import croniter
        if not schedule.expr or not croniter.is_valid(schedule.expr):
            raise ValueError("Invalid cron expression")
    elif schedule.type == "at":
        timestamp = _parse_iso_to_timestamp(schedule.at or "", schedule.tz)
        if timestamp is None or not math.isfinite(timestamp) or timestamp <= time.time():
            raise ValueError("at must specify a valid future time")
        # Resolve relative timestamps once, including across restarts.
        schedule.at = datetime.fromtimestamp(timestamp, timezone.utc).isoformat()
    else:
        raise ValueError("Unknown schedule type")
    return schedule


class SchedulerService:
    """Background service that manages and fires scheduled jobs.

    Usage:
        service = SchedulerService(store_path="scheduler_jobs.json")
        service.set_callback(my_callback)
        await service.start()
        # ... later
        await service.stop()

    Concurrency control:
        max_concurrent_callbacks limits how many job callbacks can run
        simultaneously, preventing LLM request storms when many jobs
        fire at once.
    """

    PRECHECK_REAP_TIMEOUT = 1.0
    TICK_INTERVAL = 1.0  # Check every second
    DEFAULT_MAX_CONCURRENT = 5  # Max concurrent callback executions

    def __init__(
        self,
        store_path: str = "scheduler_jobs.json",
        config_path: str = "",
        store: Optional[BaseJobStore] = None,
        max_concurrent_callbacks: int = DEFAULT_MAX_CONCURRENT,
    ):
        # Use provided store or create a default JSON file store
        self._store: BaseJobStore = store or JobStore(path=store_path)
        self._callback: Optional[JobCallback] = None
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._config_path = config_path or os.path.dirname(store_path) or os.getcwd()
        # Per-job lock: prevents concurrent callback executions for the same job
        self._busy_jobs: Set[str] = set()
        self._callback_tasks: Set[asyncio.Task] = set()
        # Semaphore: limits total concurrent callback executions
        self._semaphore = asyncio.Semaphore(max_concurrent_callbacks)

    @property
    def store(self) -> BaseJobStore:
        return self._store

    def set_callback(self, callback: JobCallback) -> None:
        """Set the callback invoked when a job fires."""
        self._callback = callback

    async def start(self) -> None:
        """Start the background scheduler loop."""
        if self._running:
            return
        self._store.load()

        # Recompute next_run_at for all jobs on start
        now = time.time()
        for job in self._store.list_all():
            if job.enabled and job.next_run_at is None:
                job.next_run_at = _compute_next_run(job.schedule, now)
                self._store.update(job)

        self._running = True
        self._task = asyncio.ensure_future(self._run_loop())
        logger.info(
            f"SchedulerService started with {len(self._store.list_all())} jobs"
        )

    async def stop(self) -> None:
        """Stop the background scheduler loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        tasks = list(self._callback_tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._callback_tasks.clear()
        self._busy_jobs.clear()
        logger.info("SchedulerService stopped")

    async def _run_loop(self) -> None:
        """Main loop: check for due jobs every TICK_INTERVAL seconds."""
        while self._running:
            try:
                await self._tick()
            except Exception as e:
                logger.error(f"Scheduler tick error: {e}", exc_info=True)
            await asyncio.sleep(self.TICK_INTERVAL)

    async def _tick(self) -> None:
        """Check due jobs; commit their next state before dispatching effects."""
        now = time.time()
        for job in self._store.list_all():
            if not job.enabled or job.next_run_at is None or job.next_run_at > now:
                continue
            if not self._callback or job.id in self._busy_jobs:
                continue
            if job.pre_check and job.pre_check.command:
                await self._handle_precheck_job(job, now)
            else:
                self._fire_callback_bg(job, now)

    async def _handle_precheck_job(self, job: SchedulerJob, now: float) -> None:
        """Check for changes, then commit state before dispatch or dedup writes."""
        check_result = await self._run_pre_check(job.pre_check)
        # While the subprocess was awaited, a manual trigger/update/removal can
        # have replaced this job. Never dispatch the obsolete snapshot.
        if self._store.get(job.id) is not job or job.id in self._busy_jobs:
            return
        candidate = deepcopy(job)
        if check_result is None:
            candidate.last_status = "check_error"
            self._persist_run(candidate, now, fired=False)
            return

        has_new = check_result.get("has_new", False)
        bypass_dedup = check_result.get("reason", "") in (
            "browser_not_running", "not_on_im_page"
        )
        if has_new and job.pre_check.state_file and not bypass_dedup:
            has_new = self._is_state_changed(job.pre_check.state_file, check_result)
        if not has_new:
            candidate.last_status = "check_no_change"
            self._persist_run(candidate, now, fired=False)
            return

        candidate.last_status = "check_triggered"
        if self._fire_callback_bg(candidate, now):
            if job.pre_check.state_file and not bypass_dedup:
                self._save_state(job.pre_check.state_file, check_result)

    def _persist_run(self, job: SchedulerJob, now: float, fired: bool) -> Optional[SchedulerJob]:
        """Atomically advance a detached job and return its committed snapshot."""
        candidate = deepcopy(job)
        candidate.last_run_at = now
        if fired:
            candidate.run_count += 1
        if candidate.delete_after_run or candidate.schedule.type == "at":
            saved = self._store.remove(candidate.id)
        else:
            candidate.next_run_at = _compute_next_run(candidate.schedule, now)
            saved = self._store.update(candidate)
        return candidate if saved else None

    def _fire_callback_bg(self, job: SchedulerJob, now: float) -> bool:
        """Reserve, commit, then launch a callback without yielding in between.

        Failed persistence creates no task and releases the reservation. This
        ensures a failed trigger cannot execute an uncommitted external effect.
        """
        if not self._callback or job.id in self._busy_jobs:
            return False
        self._busy_jobs.add(job.id)
        try:
            committed = self._persist_run(job, now, fired=True)
            if committed is None:
                self._busy_jobs.discard(job.id)
                return False
            # Callback status changes must not mutate the store's cached object.
            task = asyncio.create_task(self._run_callback_locked(deepcopy(committed)))
        except BaseException:
            self._busy_jobs.discard(job.id)
            raise
        self._callback_tasks.add(task)
        task.add_done_callback(self._callback_tasks.discard)
        task.add_done_callback(lambda _: self._busy_jobs.discard(job.id))
        return True

    async def _run_callback_locked(self, job: SchedulerJob) -> None:
        """Run callback with per-job lock and global semaphore (background coroutine)."""
        try:
            async with self._semaphore:
                logger.info(f"[BG] Starting callback for: {job.name}")
                await self._callback(job)
                job.last_status = "ok"
                logger.info(f"[BG] Callback completed for: {job.name}")
        except Exception as e:
            logger.error(
                f"[BG] Callback for {job.name} failed: {e}", exc_info=True
            )
            job.last_status = "error"
        finally:
            self._busy_jobs.discard(job.id)
            # Persist status update to disk
            try:
                current = self._store.get(job.id)
                if current is not None:
                    # An update can replace the cached job while this callback
                    # is running. Merge only execution status into that version.
                    candidate = deepcopy(current)
                    candidate.last_status = job.last_status
                    self._store.update(candidate)
            except Exception:
                pass

    # ─── Pre-check execution ─────────────────────────────────────────

    async def _stop_pre_check(self, process) -> None:
        """Kill the owned process group, then reap under a separate deadline."""
        try:
            if os.name == "posix" and getattr(process, "pid", None):
                # Descendants can retain stdout/stderr even after their launcher
                # exits; kill the group regardless of the launcher's returncode.
                os.killpg(process.pid, signal.SIGKILL)
            elif process.returncode is None:
                process.kill()
        except ProcessLookupError:
            pass
        try:
            await asyncio.wait_for(process.wait(), self.PRECHECK_REAP_TIMEOUT)
        except asyncio.TimeoutError:
            # An escaped descendant may still own a pipe. Close asyncio's pipe
            # transport rather than allowing scheduler shutdown to hang forever.
            transport = getattr(process, "_transport", None)
            if transport is not None:
                transport.close()
            logger.warning("Pre-check process did not reap before cleanup deadline")

    async def _run_pre_check(
        self, config: PreCheckConfig
    ) -> Optional[Dict[str, Any]]:
        """Run pre-check command and parse JSON output.

        Returns parsed JSON dict, or None if the command failed.
        """
        try:
            env = os.environ.copy()
            if config.env:
                env.update(config.env)

            # Resolve cwd: default to bot's config_path
            cwd = config.cwd or self._config_path or None

            args = shlex.split(config.command)
            process = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=env,
                start_new_session=os.name == "posix",
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), timeout=config.timeout
                )
            except (asyncio.TimeoutError, asyncio.CancelledError) as exc:
                await self._stop_pre_check(process)
                if isinstance(exc, asyncio.CancelledError):
                    raise
                logger.warning(
                    f"Pre-check command timed out after {config.timeout}s: "
                    f"{config.command}"
                )
                return None

            if process.returncode != 0:
                stderr_str = stderr.decode("utf-8", errors="replace")[:500]
                logger.warning(
                    f"Pre-check command failed (exit {process.returncode}): "
                    f"{stderr_str}"
                )
                return None

            stdout_str = stdout.decode("utf-8", errors="replace").strip()
            if not stdout_str:
                return {"has_new": False}

            # Parse the last non-empty line as JSON
            # (script may print debug info to stderr, only stdout matters)
            lines = [l.strip() for l in stdout_str.splitlines() if l.strip()]
            if not lines:
                return {"has_new": False}

            result = _json.loads(lines[-1])
            return result if isinstance(result, dict) else None

        except _json.JSONDecodeError as e:
            logger.warning(f"Pre-check output not valid JSON: {e}")
            return None
        except Exception as e:
            logger.error(f"Pre-check execution error: {e}", exc_info=True)
            return None

    # ─── State dedup ──────────────────────────────────────────────────

    def _is_state_changed(
        self, state_file: str, current: Dict[str, Any]
    ) -> bool:
        """Check if state has changed using generic JSON comparison."""
        old_state = None
        try:
            # Resolve relative path against config_path
            if not os.path.isabs(state_file) and self._config_path:
                state_file = os.path.join(self._config_path, state_file)

            if os.path.exists(state_file):
                with open(state_file, "r") as f:
                    old_state = _json.load(f)
        except Exception:
            # If we can't read saved state, treat as changed
            return True

        if old_state is None and current is not None:
            return True
        if old_state is None or current is None:
            return False
        try:
            return _json.dumps(old_state, sort_keys=True) != _json.dumps(
                current, sort_keys=True
            )
        except (TypeError, ValueError):
            return str(old_state) != str(current)

    def _save_state(
        self, state_file: str, state: Dict[str, Any]
    ) -> None:
        """Save check result to state file for future comparison."""
        try:
            # Resolve relative path against config_path
            if not os.path.isabs(state_file) and self._config_path:
                state_file = os.path.join(self._config_path, state_file)
            state_dir = os.path.dirname(state_file)
            if state_dir:
                os.makedirs(state_dir, exist_ok=True)
            with open(state_file, "w") as f:
                _json.dump(state, f, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"Failed to save pre-check state: {e}")

    # =========================================================================
    # Public API for the scheduler tool
    # =========================================================================

    async def add_job(
        self,
        name: str,
        schedule: Dict[str, Any],
        payload: Dict[str, Any],
        session_id: str = "default",
        delete_after_run: bool = False,
        pre_check: Optional[Dict[str, Any]] = None,
        user_id: str = "",
    ) -> SchedulerJob:
        """Add a new scheduled job.

        Args:
            name: Human-readable job name
            schedule: Schedule config dict, e.g. {"type": "cron", "expr": "0 12 * * *"}
            payload: Arbitrary data (e.g. {"text": "吃饭提醒"})
            session_id: Target session for message delivery
            delete_after_run: Auto-delete after first run (for one-shot)
            pre_check: Optional pre-check config for watcher-style jobs.
            user_id: Owner user ID (for multi-user isolation)

        Returns:
            The created SchedulerJob
        """
        sched = _validated_schedule(schedule)
        now = time.time()

        # For "at" jobs, auto-set delete_after_run
        if sched.type == "at":
            delete_after_run = True

        pre_check_config = (
            PreCheckConfig.from_dict(pre_check) if pre_check else None
        )

        job = SchedulerJob(
            name=name,
            user_id=user_id,
            schedule=sched,
            payload=payload,
            session_id=session_id,
            delete_after_run=delete_after_run,
            next_run_at=_compute_next_run(sched, now),
            pre_check=pre_check_config,
        )

        self._store.add(job)
        logger.info(f"Added job: {job.summary()}")
        return job

    async def remove_job(self, job_id: str) -> bool:
        """Remove a job by ID."""
        removed = self._store.remove(job_id)
        if removed:
            logger.info(f"Removed job: {job_id}")
        return removed

    async def list_jobs(self, user_id: Optional[str] = None) -> List[SchedulerJob]:
        """List all jobs, optionally filtered by user_id."""
        return self._store.list_all(user_id=user_id)

    async def update_job(
        self,
        job_id: str,
        name: Optional[str] = None,
        schedule: Optional[Dict[str, Any]] = None,
        payload: Optional[Dict[str, Any]] = None,
        enabled: Optional[bool] = None,
    ) -> Optional[SchedulerJob]:
        """Update an existing job."""
        job = self._store.get(job_id)
        if not job:
            return None

        # Build a detached candidate: validation and persistence can fail.
        job = deepcopy(job)

        if name is not None:
            job.name = name
        if schedule is not None:
            job.schedule = _validated_schedule(schedule)
            job.delete_after_run = job.schedule.type == "at"
            job.next_run_at = _compute_next_run(job.schedule, time.time())
        if payload is not None:
            job.payload = payload
        if enabled is not None:
            job.enabled = enabled
            if enabled and job.next_run_at is None:
                job.next_run_at = _compute_next_run(job.schedule, time.time())

        self._store.update(job)
        logger.info(f"Updated job: {job.summary()}")
        return job

    async def trigger_job(
        self,
        job_id: Optional[str] = None,
        name: Optional[str] = None,
    ) -> bool:
        """Manually trigger a job immediately (bypass schedule AND pre_check).

        The callback is fired in the BACKGROUND (non-blocking), so this
        method returns immediately. The caller (e.g. TaskManager) gets a
        quick response while the actual skill execution happens in background.

        Args:
            job_id: Job ID to trigger
            name: Job name to trigger (if ID not provided)

        Returns:
            True if job was found and trigger was initiated, False otherwise
        """
        job = None
        if job_id:
            job = self._store.get(job_id)
        elif name:
            # Find by name
            for j in self._store.list_all():
                if j.name == name:
                    job = j
                    break

        if not job:
            logger.warning(f"Job not found for trigger: id={job_id}, name={name}")
            return False

        if not job.enabled:
            logger.warning(f"Job {job.id} is disabled, cannot trigger")
            return False

        logger.info(f"Manually triggering job: {job.name} ({job.id})")
        now = time.time()

        return self._fire_callback_bg(job, now)

    async def get_status(self, user_id: Optional[str] = None) -> Dict[str, Any]:
        """Get scheduler status."""
        jobs = self._store.list_all(user_id=user_id)
        return {
            "running": self._running,
            "total_jobs": len(jobs),
            "enabled_jobs": sum(1 for j in jobs if j.enabled),
            "busy_jobs": [j.id for j in jobs if j.id in self._busy_jobs],
            "max_concurrent": self._semaphore._value if hasattr(self._semaphore, '_value') else self.DEFAULT_MAX_CONCURRENT,
            "jobs": [j.to_dict() for j in jobs],
        }
