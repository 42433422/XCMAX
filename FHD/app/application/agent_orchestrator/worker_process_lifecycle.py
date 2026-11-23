"""Spawned worker ownership and verified cleanup, without business execution policy."""

from __future__ import annotations

import importlib
import json
import logging
import multiprocessing
import os
import sys
import threading
import time
from collections.abc import Callable
from multiprocessing.connection import wait

import psutil


def _stop_owned_descendants(root):
    children = []
    # Freeze parents before collecting descendants to stop ordinary spawn races.
    for _ in range(2):
        for child in root.children(recursive=True):
            if child not in children:
                children.append(child)
                try:
                    child.suspend()
                except psutil.NoSuchProcess:
                    pass
    for child in reversed(children):
        try:
            child.kill()
        except psutil.NoSuchProcess:
            pass
    return children


def _descendants_stopped(children) -> bool:
    try:
        _, alive = psutil.wait_procs(children, timeout=1)
        for child in alive:
            try:
                if child.is_running() and child.status() != psutil.STATUS_ZOMBIE:
                    return False
            except psutil.NoSuchProcess:
                pass
    except psutil.Error:
        return False
    return True


def enable_orphan_adoption() -> bool:
    """Reuse the Linux subreaper contract already used by e2e_supervise.py."""
    if sys.platform != "linux":
        return False
    import ctypes

    libc = ctypes.CDLL(None, use_errno=True)
    try:
        prctl = libc.prctl
    except AttributeError:
        raise RuntimeError("worker orphan ownership is unavailable") from None
    prctl.argtypes = [ctypes.c_int, *([ctypes.c_ulong] * 4)]
    prctl.restype = ctypes.c_int
    enabled = ctypes.c_int()
    if (
        prctl(36, 1, 0, 0, 0) != 0  # PR_SET_CHILD_SUBREAPER
        or prctl(37, ctypes.addressof(enabled), 0, 0, 0) != 0  # PR_GET_CHILD_SUBREAPER
        or enabled.value != 1
    ):
        raise RuntimeError("worker orphan ownership is unverified")
    return True


def _reap_adopted_descendants(namespace_matches) -> bool:
    if not namespace_matches():
        return False
    try:
        root = psutil.Process(os.getpid())
        # This supervisor has no business thread or further spawn. It must keep
        # running to freeze/reap adopted children, never suspend itself.
        children = _stop_owned_descendants(root)
        return _descendants_stopped(children) and not root.children()
    except psutil.Error:
        return False


def _run_owned_worker(target, executor, args):
    # Resolve trusted spawn callables only here, not in the lightweight supervisor.
    # Tool payloads never select either reference or enter this lifecycle channel.
    def resolve(reference):
        value = importlib.import_module(reference[0])
        for name in reference[1].split("."):
            value = getattr(value, name)
        return value

    resolve(target)(resolve(executor), *args)


def supervise_worker(
    target, executor, args, connections, lifecycle, *, reap, namespace_matches, adopt
):
    """Own the real worker so parent loss can use the original frozen-tree reap."""
    owner = multiprocessing.parent_process()
    worker = None
    exited = False
    adopts_orphans = False
    try:
        if (
            owner is not None
            and not wait((owner.sentinel,), timeout=0)
            and not lifecycle.poll()
            and namespace_matches()
        ):
            adopts_orphans = adopt()
            worker = multiprocessing.get_context("spawn").Process(
                target=_run_owned_worker, args=(target, executor, args), daemon=False
            )
            worker.start()
            for connection in connections:
                connection.close()  # Only the consumer may retain these pipe ends.
            if not wait((owner.sentinel,), timeout=0):
                lifecycle.send_bytes(json.dumps({"kind": "ready", "pid": worker.pid}).encode())
                readable = wait((owner.sentinel, worker.sentinel, lifecycle))
                # Parent death always wins over a concurrent normal receipt/stop.
                exited = owner.sentinel not in readable and worker.sentinel in readable
                if exited:
                    lifecycle.send_bytes(b'{"kind":"exited"}')
    except (OSError, ValueError, RuntimeError) as exc:
        logging.getLogger(__name__).warning(
            "tool worker supervision interrupted: %s", type(exc).__name__
        )
    finally:
        for connection in connections:
            connection.close()
        clean = True
        exitcode = None
        if worker is not None and worker.pid is not None:
            try:
                # Do not poll exitcode/is_alive before the tree is frozen and reaped:
                # waitpid could otherwise release the PID before psutil inspects it.
                clean = reap(worker, allow_exited_root=adopts_orphans)
                exitcode = worker.exitcode
                if clean:
                    worker.close()
            except (OSError, ValueError):
                clean = False
        if adopts_orphans:
            adopted_clean = _reap_adopted_descendants(namespace_matches)
            clean = clean and adopted_clean
        try:
            if owner is not None and not wait((owner.sentinel,), timeout=0):
                lifecycle.send_bytes(
                    json.dumps(
                        {"kind": "closed", "clean": clean, "exited": exited, "exitcode": exitcode}
                    ).encode()
                )
                # Keep our own ancestry/PID until the caller's original _reap runs.
                # Its namespace and kill/join checks remain a separate requirement.
                wait((owner.sentinel,))
        except (OSError, ValueError):
            pass
        finally:
            lifecycle.close()


class OwnedWorker:
    """A standard spawn supervisor plus a small, private lifecycle receipt."""

    def __init__(self, ctx, target, executor, args, connections, *, supervisor, reap):
        self._lifecycle, self._child_lifecycle = ctx.Pipe()
        self._read_lock = threading.Lock()
        self._reap = reap
        self.worker_pid: int | None = None
        self.worker_exited: bool = False
        self.worker_exitcode: int | None = None
        self._worker_clean: bool | None = None
        self._closed = False
        self.clean: bool | None = None
        self.process = ctx.Process(
            target=supervisor,
            args=(
                (target.__module__, target.__qualname__),
                (executor.__module__, executor.__qualname__),
                args,
                tuple(connection for connection in connections if connection is not None),
                self._child_lifecycle,
            ),
            daemon=False,
        )

    @property
    def pid(self):
        return self.process.pid

    @property
    def sentinel(self):
        # After ready, only actual exit/cleanup or a broken supervisor can signal.
        return self._lifecycle

    def start(self):
        try:
            self.process.start()
        finally:
            self._child_lifecycle.close()

    def _poll_lifecycle(self):
        with self._read_lock:
            while not self._closed and self._lifecycle.poll():
                try:
                    frame = json.loads(self._lifecycle.recv_bytes(256))
                except EOFError:
                    self._closed = True
                    break  # Supervisor exit alone proves neither execution nor cleanup.
                if not isinstance(frame, dict):
                    raise ValueError("invalid worker lifecycle receipt")
                if frame.get("kind") == "ready" and type(frame.get("pid")) is int:
                    self.worker_pid = frame["pid"]
                elif frame.get("kind") == "exited":
                    self.worker_exited = True
                elif frame.get("kind") == "closed":
                    self._closed = True
                    self._worker_clean = frame.get("clean") is True
                    self.worker_exited = frame.get("exited") is True
                    code = frame.get("exitcode")
                    self.worker_exitcode = code if type(code) is int else None
                else:
                    raise ValueError("invalid worker lifecycle receipt")

    def wait_ready(self, deadline: float, *, check: Callable[[], None] | None = None) -> bool:
        while self.worker_pid is None and not self._closed:
            if check is not None:
                check()
            remaining = max(0, deadline - time.monotonic())
            if not wait(
                (self._lifecycle, self.process.sentinel),
                timeout=min(remaining, 0.1) if check is not None else remaining,
            ):
                if check is not None and time.monotonic() < deadline:
                    continue
                return False
            self._poll_lifecycle()
        if check is not None:
            check()
        return self.worker_pid is not None and not self._closed

    def exited(self) -> bool:
        self._poll_lifecycle()
        return self.worker_exited

    def close(self, *, observed=()) -> bool:
        if self.clean is not None:
            return self.clean
        clean = self.process.pid is None
        try:
            if self.process.pid is not None:
                try:
                    # At most one byte is sent; the other direction has three small
                    # frames. Neither pipe can fill while the consumer is stopped.
                    self._lifecycle.send_bytes(b"x")
                    deadline = time.monotonic() + 3
                    while not self._closed and time.monotonic() < deadline:
                        if not wait(
                            (self._lifecycle, self.process.sentinel),
                            timeout=max(0, deadline - time.monotonic()),
                        ):
                            break
                        self._poll_lifecycle()
                except (OSError, EOFError, ValueError):
                    pass
                # Also runs when the supervisor/receipt failed. A missing or false
                # child cleanup proof cannot become true by killing the supervisor.
                reaped = (
                    self._reap(self.process, observed=observed)
                    if observed
                    else self._reap(self.process)
                )
                clean = reaped and self._worker_clean is True
                if clean:
                    self.process.close()
        except (OSError, ValueError):
            clean = False
        finally:
            with self._read_lock:
                self._lifecycle.close()
            self._child_lifecycle.close()
            self.clean = clean
        return clean
