"""Local executor ownership shared by Python and its Pi worker.

No expiry or PID heuristics: recovery requires the same host/Store binding and
an exclusive OS lock. Keep lock files stable; unlinking a held file would allow
another process to lock a different inode for the same session.
"""
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
import os
import socket
from uuid import getnode


@dataclass(frozen=True)
class ExecutionGuard:
    fd: int
    identity: dict


@contextmanager
def local_execution_guard(directory, session_id):
    import fcntl
    from cota.runtime.pi_runtime import RunInProgress

    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    name = sha256(session_id.encode()).hexdigest() + '.lock'
    fd = os.open(directory / name, os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RunInProgress('The session still has a live executor') from None
        identity = {
            'host': sha256(f'{socket.gethostname()}:{getnode()}'.encode()).hexdigest(),
            'scope': sha256(str(directory.resolve()).encode()).hexdigest(),
        }
        yield ExecutionGuard(fd, identity)
    finally:
        # Do not LOCK_UN: a surviving Pi child must keep this shared lock until
        # its inherited descriptor closes, even if Python exits first.
        os.close(fd)
