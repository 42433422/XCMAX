"""跨进程互斥文件锁。

Windows 没有 ``fcntl``；历史实现在 ``fcntl is None`` 时直接跳过加锁，
使互斥在 Windows 上静默失效（工单/能力提案写入、迁移备份均受影响）。
本模块在 Windows 走 ``msvcrt.locking``，POSIX 走 ``fcntl.flock``，
两者都是进程级强制锁。

同一线程可重入（按锁文件路径判定），避免调用方嵌套加锁自死锁。
"""

from __future__ import annotations

import os
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

_POLL_SECONDS = 0.1

_held: threading.local = threading.local()


def _held_paths() -> set[str]:
    paths = getattr(_held, "paths", None)
    if paths is None:
        paths = set()
        _held.paths = paths
    return paths


def _try_lock(handle) -> None:
    handle.seek(0)
    if sys.platform == "win32":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock(handle) -> None:
    handle.seek(0)
    if sys.platform == "win32":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def exclusive_file_lock(
    path: Path | str,
    *,
    blocking: bool = False,
    timeout: float | None = None,
    reject_symlink: bool = False,
) -> Iterator[None]:
    """以 ``path`` 为锁文件做进程间互斥。

    ``blocking=False``（默认）时锁被占用立即抛 ``OSError``；
    ``blocking=True`` 时轮询等待，超过 ``timeout`` 秒抛 ``TimeoutError``。
    """
    lock_path = Path(path)
    key = os.path.abspath(str(lock_path))
    if key in _held_paths():  # 同线程重入：避免自死锁
        yield
        return
    if reject_symlink and lock_path.is_symlink():
        raise OSError(f"Invalid lock path: {lock_path}")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as handle:
        handle.seek(0)
        if not handle.read(1):
            handle.write(b"0")
            handle.flush()
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            try:
                _try_lock(handle)
                break
            except OSError:
                if not blocking:
                    raise
                if deadline is not None and time.monotonic() >= deadline:
                    raise TimeoutError(f"timed out waiting for lock: {lock_path}") from None
                time.sleep(_POLL_SECONDS)
        _held_paths().add(key)
        try:
            yield
        finally:
            _held_paths().discard(key)
            _unlock(handle)
