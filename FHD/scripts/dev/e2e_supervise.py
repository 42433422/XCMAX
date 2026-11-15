"""Fail closed if an isolated browser suite loses any of its owned services."""
from __future__ import annotations

import ctypes
import os
import signal
import subprocess
import sys
import time
from urllib.parse import urlparse

import psutil


def owns_listener(process: psutil.Process, url: str) -> bool:
    target = urlparse(url)
    return any(
        connection.status == psutil.CONN_LISTEN
        and connection.laddr.ip == "127.0.0.1"
        and connection.laddr.port == target.port
        for connection in process.net_connections(kind="tcp")
    )


def run(backend_pid: int, frontend_pid: int, guard_pid: int, api: str, web: str, command: list[str]) -> int:
    services: list[psutil.Process] = []
    try:
        for pid in (backend_pid, frontend_pid, guard_pid):
            services.append(psutil.Process(pid))
    except psutil.Error:
        for process in services:
            try:
                process.kill()
            except psutil.Error:
                pass
        return 1

    def ready() -> bool:
        try:
            return (
                all(process.is_running() and process.status() != psutil.STATUS_ZOMBIE for process in services)
                and owns_listener(services[0], api) and owns_listener(services[1], web)
            )
        except psutil.Error:
            return False

    def stop_services() -> None:
        # Stop credential handling immediately, before waiting for browser workers.
        for process in services[:2]:
            try:
                process.kill()
            except psutil.Error:
                pass

    # Linux retains orphan ownership; Darwin has no equivalent subreaper API.
    # Both platforms keep service/guard supervision and identity-safe cleanup.
    # On Darwin, a detached child missed before its parent exits may remain;
    # failure invalidates its isolated local session by stopping the services.
    if sys.platform == "linux":
        libc = ctypes.CDLL(None, use_errno=True)
        libc.prctl.argtypes = [ctypes.c_int, *([ctypes.c_ulong] * 4)]
        libc.prctl.restype = ctypes.c_int
        if libc.prctl(36, 1, 0, 0, 0) != 0:  # PR_SET_CHILD_SUBREAPER
            stop_services()
            return 1
    elif sys.platform != "darwin":
        stop_services()
        return 1
    if not ready():
        stop_services()
        return 1
    supervisor = psutil.Process(os.getpid())
    child = subprocess.Popen(command, start_new_session=True)
    suite = psutil.Process(child.pid)
    descendants: set[psutil.Process] = set()

    def remember_descendants() -> None:
        for parent in [supervisor, *descendants]:
            try:
                descendants.update(parent.children(recursive=True))
            except psutil.Error:
                pass

    result = 1
    try:
        while child.poll() is None:
            remember_descendants()
            if not ready():
                stop_services()
                return 1
            time.sleep(0.1)
        if not ready():
            stop_services()
            return 1
        result = child.returncode
        return result
    finally:
        if result != 0:
            stop_services()
        # Chromium is detached into a new process group. Track Process identities
        # (PID + creation time), including descendants whose parent has exited.
        # Freeze ancestors before the final traversal so they cannot spawn more
        # browser workers during cleanup. Never signal a raw reused PID/group.
        while True:
            known = set(descendants)
            remember_descendants()
            for process in [suite, *descendants]:
                try:
                    process.suspend()
                except psutil.Error:
                    pass
            remember_descendants()
            if descendants == known:
                break
        for process in [*descendants, suite]:
            try:
                process.kill()
            except psutil.Error:
                pass
        child.wait()
        psutil.wait_procs(list(descendants), timeout=2)


def main() -> int:
    def interrupted(signum, _frame):
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    try:
        return run(int(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3]), sys.argv[4], sys.argv[5], sys.argv[6:])
    except (psutil.Error, OSError, ValueError):
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
