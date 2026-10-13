"""#439: exactly one scheduler per container, and it survives a worker kill.

gunicorn runs several workers; only one may run APScheduler (else every
digest is sent twice). The old rule was "the worker with age 1", but
``age`` is a spawn counter, so the replacement for a killed worker 1 is
age 3 and nobody ran the scheduler until the next deploy.

Now each worker tries an exclusive, non-blocking lock on one file when it
boots. The winner keeps the handle open for its lifetime and runs the
scheduler. The OS releases the lock when that process exits — however it
exits — so the next worker to boot (its replacement) wins it.
"""
from __future__ import annotations

import os
import tempfile
from typing import IO

DEFAULT_PATH = os.path.join(tempfile.gettempdir(), "taskmanager-scheduler.lock")


def try_acquire(path: str = DEFAULT_PATH) -> IO | None:
    """Return an open handle holding the lock, or None if another process
    (or another handle) holds it. Keep the handle alive to keep the lock.
    """
    fh = open(path, "a+")  # noqa: SIM115 — must stay open to hold the lock
    try:
        if os.name == "nt":
            import msvcrt

            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        return None
    return fh


def release(fh: IO | None) -> None:
    """Drop a lock taken by try_acquire (closing the handle releases it)."""
    if fh is None:
        return
    try:
        if os.name == "nt":
            import msvcrt

            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
    except OSError:
        pass
    fh.close()
