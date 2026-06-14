"""PID file lock using fcntl."""
from __future__ import annotations

import fcntl
import logging
import os
from contextlib import contextmanager
from pathlib import Path


logger = logging.getLogger("jellyfin_watcher")


@contextmanager
def acquire_lock(lock_path: Path):
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            try:
                os.lseek(fd, 0, os.SEEK_SET)
                other_pid = os.read(fd, 64).decode().strip() or "unknown"
            except Exception:
                other_pid = "unknown"
            logger.warning("lock_held", extra={"event": "lock_held", "lock_held_by": other_pid})
            yield False
            return

        os.ftruncate(fd, 0)
        os.write(fd, str(os.getpid()).encode())
        os.fsync(fd)
        yield True
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except Exception:
            pass
        os.close(fd)
