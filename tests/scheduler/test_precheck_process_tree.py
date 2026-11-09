"""Timeout and cancellation reap pre-check descendants holding stdout open."""

import asyncio
import os
import shlex
import signal
import sys
import time

import pytest

from cota.executor.scheduler.service import SchedulerService
from cota.executor.scheduler.types import PreCheckConfig


@pytest.mark.skipif(os.name != "posix", reason="POSIX process-group ownership")
@pytest.mark.parametrize("reason", ["timeout", "cancel"])
async def test_precheck_reaps_descendants_and_returns_promptly(tmp_path, reason, monkeypatch):
    pid_file = tmp_path / "child.pid"
    child_code = "import time; time.sleep(30)"
    launcher = (
        "import subprocess,sys,time; from pathlib import Path; "
        f'child=subprocess.Popen([sys.executable,"-c",{child_code!r}]); '
        f"Path({str(pid_file)!r}).write_text(str(child.pid)); "
        "time.sleep(10)"
    )
    service = SchedulerService(store_path=str(tmp_path / "jobs.json"))
    config = PreCheckConfig(
        command=shlex.join([sys.executable, "-c", launcher]),
        timeout=0.2 if reason == "timeout" else 10,
    )
    # Start the timeout after the real subprocess tree is ready. Under coverage
    # or CI load, Python startup can exceed the deliberately short deadline.
    create_process = asyncio.create_subprocess_exec
    ready = asyncio.Event()

    async def start_tree(*args, **kwargs):
        process = await create_process(*args, **kwargs)
        try:
            async with asyncio.timeout(5):
                while not pid_file.exists() or not pid_file.read_text().strip():
                    await asyncio.sleep(0.005)
        except BaseException:
            os.killpg(process.pid, signal.SIGKILL)
            await process.communicate()
            raise
        ready.set()
        return process

    monkeypatch.setattr(asyncio, 'create_subprocess_exec', start_tree)
    task = asyncio.create_task(service._run_pre_check(config))
    try:
        await asyncio.wait_for(ready.wait(), timeout=6)
        started = time.monotonic()
        if reason == "cancel":
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            assert await task is None
        assert time.monotonic() - started < 1.2, (
            "descendant pipes must not delay cleanup"
        )
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        if pid_file.exists():
            try:
                os.kill(int(pid_file.read_text()), signal.SIGKILL)
            except ProcessLookupError:
                pass


async def test_precheck_reap_is_bounded_when_pipe_remains_open(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, Mock

    service = SchedulerService(store_path=str(tmp_path / "jobs.json"))
    process = SimpleNamespace(
        returncode=None, pid=None, kill=Mock(), _transport=SimpleNamespace(close=Mock())
    )

    async def blocked():
        await asyncio.Event().wait()

    process.communicate = blocked
    process.wait = blocked
    monkeypatch.setattr(
        asyncio, "create_subprocess_exec", AsyncMock(return_value=process)
    )
    monkeypatch.setattr(service, "PRECHECK_REAP_TIMEOUT", 0.01, raising=False)
    task = asyncio.create_task(
        service._run_pre_check(PreCheckConfig(command="test", timeout=0.01))
    )
    done, _ = await asyncio.wait({task}, timeout=0.2)
    try:
        assert task in done, "reaping must have its own deadline"
        assert await task is None
        process._transport.close.assert_called_once()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
