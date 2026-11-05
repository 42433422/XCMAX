"""跨平台进程级文件锁（app.utils.process_lock）测试。

覆盖：
- 同线程重入不死锁
- 跨进程互斥：持锁进程未释放时子进程非阻塞获取失败，释放后可获取
- reject_symlink 拒绝符号链接锁路径
- Windows 分支走 msvcrt.locking（而非历史实现的静默 no-op）
"""

from __future__ import annotations

import os
import subprocess
import sys
import types
from pathlib import Path

import pytest

from app.utils.process_lock import exclusive_file_lock

_FHD_ROOT = Path(__file__).resolve().parents[2]

_CHILD_TRY_LOCK = """
import sys
from pathlib import Path

from app.utils.process_lock import exclusive_file_lock

lock_path = Path(sys.argv[1])
try:
    with exclusive_file_lock(lock_path, blocking=False):
        print("ACQUIRED")
except OSError:
    print("BUSY")
"""

_CHILD_HOLD_LOCK = """
import sys
import time
from pathlib import Path

from app.utils.process_lock import exclusive_file_lock

lock_path = Path(sys.argv[1])
with exclusive_file_lock(lock_path, blocking=False):
    print("ACQUIRED", flush=True)
    time.sleep(float(sys.argv[2]))
"""


def _child_env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(_FHD_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    return env


def _child_try_lock(lock_path: Path) -> str:
    proc = subprocess.run(
        [sys.executable, "-c", _CHILD_TRY_LOCK, str(lock_path)],
        capture_output=True,
        text=True,
        env=_child_env(),
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip().splitlines()[-1]


def test_same_thread_reentrant(tmp_path: Path) -> None:
    lock = tmp_path / "reentrant.lock"
    with exclusive_file_lock(lock, blocking=False):
        with exclusive_file_lock(lock, blocking=False):
            pass


def test_cross_process_lock_is_enforced(tmp_path: Path) -> None:
    lock = tmp_path / "shared.lock"
    with exclusive_file_lock(lock, blocking=False):
        assert _child_try_lock(lock) == "BUSY"


def test_cross_process_lock_released_after_exit(tmp_path: Path) -> None:
    lock = tmp_path / "shared.lock"
    with exclusive_file_lock(lock, blocking=False):
        pass
    assert _child_try_lock(lock) == "ACQUIRED"


def test_rejects_symlink_lock_path(tmp_path: Path) -> None:
    target = tmp_path / "real.lock"
    target.write_text("", encoding="utf-8")
    link = tmp_path / "link.lock"
    link.symlink_to(target)
    with pytest.raises(OSError):
        with exclusive_file_lock(link, reject_symlink=True):
            pass


def test_blocking_timeout_when_another_process_holds_lock(tmp_path: Path) -> None:
    lock = tmp_path / "contended.lock"
    with subprocess.Popen(
        [sys.executable, "-c", _CHILD_HOLD_LOCK, str(lock), "10"],
        stdout=subprocess.PIPE,
        text=True,
        env=_child_env(),
    ) as holder:
        assert holder.stdout is not None
        with holder.stdout:
            assert holder.stdout.readline().strip() == "ACQUIRED"
            with pytest.raises(TimeoutError):
                with exclusive_file_lock(lock, blocking=True, timeout=0.2):
                    pass
        holder.terminate()
        holder.wait(timeout=30)


def test_windows_platform_uses_msvcrt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Windows 必须真正加锁：历史实现在 fcntl 缺失时静默退化为无锁。"""
    calls: list[tuple[int, int]] = []
    fake_msvcrt = types.ModuleType("msvcrt")
    fake_msvcrt.LK_NBLCK = 2  # type: ignore[attr-defined]
    fake_msvcrt.LK_UNLCK = 0  # type: ignore[attr-defined]

    def _locking(_fd: int, mode: int, nbytes: int) -> None:
        calls.append((mode, nbytes))

    fake_msvcrt.locking = _locking  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "msvcrt", fake_msvcrt)
    monkeypatch.setattr(sys, "platform", "win32")

    lock = tmp_path / "windows.lock"
    with exclusive_file_lock(lock, blocking=False):
        pass

    assert [mode for mode, _ in calls] == [fake_msvcrt.LK_NBLCK, fake_msvcrt.LK_UNLCK]
