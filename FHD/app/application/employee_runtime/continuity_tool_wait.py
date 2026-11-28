"""Short ledger critical sections around durable, non-replayed tool claims."""

from __future__ import annotations

import errno
import math
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from types import ModuleType
from typing import IO, Any

# Windows durable ledgers reject writes before POSIX flock is required.
# Do not import fcntl on Windows: even read-only runtime imports must work.
from app.application.tool_execution_deadline import remaining_invocation_seconds

fcntl: ModuleType | None = None
if os.name != "nt":
    import fcntl as _fcntl

    fcntl = _fcntl


class ToolNotStarted(TimeoutError):
    """The trusted budget expired before any worker was spawned."""


class ContinuityClaimChanged(RuntimeError):
    """Late results cannot overwrite a different durable claim."""


class ProcessLimitsUnavailable(RuntimeError):
    """A requested child resource boundary could not be established."""


class ProcessLimitsExceeded(RuntimeError):
    """The existing process-tree monitor observed a resource budget violation."""


@dataclass(frozen=True)
class ProcessLimits:
    cpu_seconds: int
    address_space_bytes: int
    file_size_bytes: int
    open_files: int = 256


def _limited_command(
    command: Sequence[str], limits: ProcessLimits, *, start_fd: int | None = None
) -> list[str]:
    # prlimit applies limits before exec without a preexec_fn in a threaded host.
    # These are per-process/per-file limits, not aggregate PID or cgroup limits.
    darwin = sys.platform == "darwin"
    limiter = shutil.which("prlimit") if sys.platform == "linux" else None
    if (not darwin and limiter is None) or (darwin and start_fd is None):
        raise ProcessLimitsUnavailable("no supported child resource boundary")
    import resource

    options = (
        ("cpu", resource.RLIMIT_CPU, limits.cpu_seconds),
        ("as", resource.RLIMIT_AS, limits.address_space_bytes),
        ("fsize", resource.RLIMIT_FSIZE, limits.file_size_bytes),
        ("nofile", resource.RLIMIT_NOFILE, limits.open_files),
    )
    bounded: list[str] = []
    caps: list[tuple[int, int]] = []
    try:
        for name, kind, cap in options:
            if type(cap) is not int or cap <= 0:
                raise ValueError("invalid child resource limit")
            if darwin and name == "as":
                # Darwin cannot enforce RLIMIT_AS; the existing parent-owned
                # process-tree RSS guard gates startup and monitors execution.
                continue
            inherited = resource.getrlimit(kind)
            effective = min(
                [cap, *(value for value in inherited if value != resource.RLIM_INFINITY)]
            )
            bounded.append(f"--{name}={effective}:{effective}")
            caps.append((kind, effective))
    except (OSError, ValueError) as exc:
        raise ProcessLimitsUnavailable("cannot establish inherited child limits") from exc
    if darwin:
        # A fresh interpreter sets kernel limits before exec. preexec_fn can
        # deadlock in the threaded server; the pipe prevents unmonitored startup.
        script = (
            "import os,resource,sys\n"
            f"for kind,cap in {caps!r}: resource.setrlimit(kind,(cap,cap))\n"
            f"if os.read({start_fd},1) != b'1': sys.exit(125)\n"
            f"os.close({start_fd})\n"
            "os.execvp(sys.argv[1],sys.argv[1:])\n"
        )
        return [sys.executable, "-c", script, *command]
    assert limiter is not None
    return [limiter, *bounded, "--", *command]


def _memory_check(pid: int, cap: int) -> Callable[[], None]:
    from app.application.agent_orchestrator.tool_process import (
        _ProcessTreeMemoryGuard,
        _WorkerResourceError,
    )

    try:
        guard = _ProcessTreeMemoryGuard(pid, cap)
    except _WorkerResourceError as exc:
        raise ProcessLimitsUnavailable(str(exc)) from exc

    def check() -> None:
        try:
            guard.check()
        except _WorkerResourceError as exc:
            error = (
                ProcessLimitsExceeded
                if exc.code == "tool_memory_limit_exceeded"
                else ProcessLimitsUnavailable
            )
            raise error(str(exc)) from exc

    return check


@dataclass
class _RequestFrame:
    state: dict[str, Any] = field(default_factory=dict)
    fd: int | None = None
    handle: IO[str] | None = None


class ContinuityRequestContext:
    """Keep request state and pinned descriptors separate on a shared runtime."""

    def __init__(self) -> None:
        self._requests = threading.local()
        self._idle = _RequestFrame()

    def _request_values(self) -> _RequestFrame:
        frame = getattr(self._requests, "frame", self._idle)
        if not isinstance(frame, _RequestFrame):
            raise RuntimeError("invalid continuity request frame")
        return frame

    @property
    def state(self) -> dict[str, Any]:
        return self._request_values().state

    @state.setter
    def state(self, value: dict[str, Any]) -> None:
        self._request_values().state = value

    @property
    def ledger_fd(self) -> int | None:
        return self._request_values().fd

    @ledger_fd.setter
    def ledger_fd(self, value: int | None) -> None:
        self._request_values().fd = value

    @property
    def ledger_lock_handle(self) -> IO[str] | None:
        return self._request_values().handle

    @ledger_lock_handle.setter
    def ledger_lock_handle(self, value: IO[str] | None) -> None:
        self._request_values().handle = value

    @contextmanager
    def scope(self) -> Iterator[None]:
        nested = hasattr(self._requests, "frame")
        previous = self._request_values()
        self._requests.frame = _RequestFrame(state=self.state)
        try:
            yield
        finally:
            self._idle.state = self.state
            if nested:
                self._requests.frame = previous
            else:
                del self._requests.frame


def run_process(command, *, input, cwd, timeout, env=None, limits: ProcessLimits | None = None):
    """Reap the process group on timeout/interruption; effects remain unknown."""
    # Reuse the server-bound budget, never a client-supplied duration. No new
    # arbitrary ceiling for legitimate large ELT files when no budget exists.
    budget = remaining_invocation_seconds(timeout if timeout is not None else math.inf)
    if budget <= 0:
        raise ToolNotStarted("invocation budget expired before process start")
    gate = os.pipe() if limits is not None and sys.platform == "darwin" else ()
    deadline = time.monotonic() + budget
    try:
        if limits is not None:
            command = _limited_command(command, limits, start_fd=gate[0] if gate else None)
        with subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=cwd,
            env=env,
            start_new_session=True,
            pass_fds=gate[:1],
        ) as process:
            completed = False
            try:
                check_memory = None
                if gate:
                    assert limits is not None
                    check_memory = _memory_check(process.pid, limits.address_space_bytes)
                    check_memory()
                    os.write(gate[1], b"1")
                while True:
                    if check_memory is not None:
                        check_memory()
                    remaining = max(0, deadline - time.monotonic())
                    try:
                        stdout, stderr = process.communicate(
                            input=input,
                            timeout=min(0.1, remaining)
                            if check_memory
                            else remaining
                            if math.isfinite(remaining)
                            else None,
                        )
                        completed = True
                        return subprocess.CompletedProcess(
                            command, process.returncode, stdout, stderr
                        )
                    except subprocess.TimeoutExpired:
                        input = None
                        if time.monotonic() >= deadline:
                            raise
            finally:
                if not completed:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.communicate()
    finally:
        for fd in gate:
            os.close(fd)


def has_running_claim(state, task_ids, pid_alive):
    return any(
        call.get("status") == "running"
        and call.get("task_id") in task_ids
        and pid_alive(int(call.get("submit_pid") or 0))
        for call in state["tool_calls"].values()
    )


@contextmanager
def unlocked_claim(runtime, task, step, call, path_lock):
    """Keep the durable claim, release both locks, then reload before merging.

    Dispatch admits only read/pause/restart while a claim is running. No caller
    may rebind its identity, replace its steps or retry its unknown side effects.
    """
    if fcntl is None:
        raise OSError(errno.ENOTSUP, "Windows workspace ledger writes are unavailable")
    handle = runtime._ledger_lock_handle
    identity = tuple(task[key] for key in ("task_id", "tenant_id", "user_id", "owner_employee"))
    original_tasks = dict(runtime.state["tasks"])
    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    path_lock.release()
    try:
        yield
    finally:
        path_lock.acquire()
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        runtime._read()
        current = runtime.state["tasks"].get(task["task_id"], {})
        current_call = runtime.state["tool_calls"].get(call["tool_call_id"], {})
        current_steps = {item["step_id"]: item for item in current.get("steps", [])}
        if (
            tuple(current.get(key) for key in ("task_id", "tenant_id", "user_id", "owner_employee"))
            != identity
            or current_call != call
            or current_steps.get(step["step_id"]) != step
            or current_steps.get(step["step_id"], {}).get("tool_call_id") != call["tool_call_id"]
        ):
            raise ContinuityClaimChanged("continuity claim changed while tool was running")
        # Preserve local references held by the caller, but never write an old
        # ledger snapshot over concurrent pause/read/restart operations.
        for task_id, original_task in original_tasks.items():
            fresh = runtime.state["tasks"].get(task_id)
            if fresh is None:
                continue
            original_steps = original_task["steps"]
            fresh_steps = {item["step_id"]: item for item in fresh["steps"]}
            if {item["step_id"] for item in original_steps} == set(fresh_steps):
                for original in original_steps:
                    original.update(fresh_steps[original["step_id"]])
            else:
                original_steps = fresh["steps"]
            original_task.clear()
            original_task.update(fresh)
            original_task["steps"] = original_steps
            runtime.state["tasks"][task_id] = original_task
        call.update(current_call)
        runtime.state["tool_calls"][call["tool_call_id"]] = call
