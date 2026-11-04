"""Nonblocking live replay ownership, independent of SQLite transactions.

SQLite queues sharing a resolved database path serialize callbacks. The OS
releases the lock after process death, but a crash after a callback and before
the replay fingerprint is persisted can cause that callback to run again.
"""

from __future__ import annotations

import errno
import os
import threading
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path

from app.utils.process_lock import exclusive_file_lock


class _ActiveEntries(threading.local):
    def __init__(self) -> None:
        self.entries: set[tuple[str, str]] = set()


_active = _ActiveEntries()


class ReplayClaim:
    def __init__(self, storage_path: str | None):
        self._memory_lock = threading.RLock()
        self._lock_path: Path | None = None
        self._scope = f"memory:{id(self)}"
        if storage_path is not None and storage_path != ":memory:":
            database = Path(storage_path).resolve()
            self._scope = os.path.normcase(str(database))
            self._lock_path = database.with_name(database.name + ".dlq-replay.lock")

    @contextmanager
    def acquire(self, entry_id: str) -> Iterator[bool]:
        key = (self._scope, entry_id)
        # The canonical file lock deliberately permits same-thread reentry.
        # Guard entries across queue instances before acquiring that lock.
        if key in _active.entries:
            yield False
            return
        with ExitStack() as held:
            if self._lock_path is None:
                if not self._memory_lock.acquire(blocking=False):
                    yield False
                    return
                held.callback(self._memory_lock.release)
            else:
                try:
                    held.enter_context(
                        exclusive_file_lock(self._lock_path, blocking=False, reject_symlink=True)
                    )
                except OSError as error:
                    # Only advisory-lock contention is a skipped replay.
                    # Permission/path/symlink failures remain visible.
                    if (
                        error.errno not in (errno.EAGAIN, errno.EACCES)
                        or error.filename is not None
                    ):
                        raise
                    yield False
                    return
            _active.entries.add(key)
            try:
                yield True
            finally:
                _active.entries.remove(key)
