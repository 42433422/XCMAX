"""Short ledger critical sections around durable, non-replayed tool claims."""

from __future__ import annotations

import fcntl
import math
import os
import signal
import subprocess
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import IO, Any

from app.application.tool_execution_deadline import remaining_invocation_seconds


class ToolNotStarted(TimeoutError):
    """The trusted budget expired before any worker was spawned."""


class ContinuityClaimChanged(RuntimeError):
    """Late results cannot overwrite a different durable claim."""


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


def run_process(command, *, input, cwd, timeout):
    """Reap the process group on timeout/interruption; effects remain unknown."""
    # Reuse the server-bound budget, never a client-supplied duration. No new
    # arbitrary ceiling for legitimate large ELT files when no budget exists.
    budget = remaining_invocation_seconds(timeout if timeout is not None else math.inf)
    if budget <= 0:
        raise ToolNotStarted("invocation budget expired before process start")
    with subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=cwd,
        start_new_session=True,
    ) as process:
        completed = False
        try:
            stdout, stderr = process.communicate(
                input=input,
                timeout=budget if math.isfinite(budget) else None,
            )
            completed = True
            return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
        finally:
            if not completed:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.communicate()


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
