"""Nonblocking process locks for shared Mod installation and receipt state."""

import os
import stat
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


@contextmanager
def state_lock(directory: Path) -> Iterator[None]:
    path = directory / ".state.lock"
    if path.is_symlink():
        raise OSError("Invalid Mod state lock")
    # O_NOFOLLOW closes the check/use window: a symlink swapped in after the
    # lstat above makes the open fail instead of locking an attacker's target.
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    try:
        handle = os.fdopen(fd, "r+b")
    except OSError:
        os.close(fd)
        raise
    with handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise OSError("Invalid Mod state lock")
        handle.seek(0)
        if not handle.read(1):
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        if sys.platform == "win32":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            handle.seek(0)
            if sys.platform == "win32":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
