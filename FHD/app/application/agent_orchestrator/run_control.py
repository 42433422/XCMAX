"""Process-local cooperative control signals for active Agent Runs."""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Iterator, Literal

RunControl = Literal["pause", "cancel"]

_LOCK = threading.RLock()
_CONTROLS: dict[str, RunControl] = {}
_OPERATION_LOCKS: dict[str, tuple[threading.RLock, int]] = {}


def request_run_control(run_id: str, control: RunControl) -> None:
    with _LOCK:
        # Cancellation is terminal and must not be weakened by a later pause request.
        if _CONTROLS.get(run_id) != "cancel":
            _CONTROLS[run_id] = control


def get_run_control(run_id: str) -> RunControl | None:
    with _LOCK:
        return _CONTROLS.get(run_id)


def clear_run_control(run_id: str) -> None:
    with _LOCK:
        _CONTROLS.pop(run_id, None)


@contextmanager
def run_operation_lock(run_id: str) -> Iterator[None]:
    """Serialize state-changing operations for one run within this service process."""
    with _LOCK:
        lock, users = _OPERATION_LOCKS.get(run_id, (threading.RLock(), 0))
        _OPERATION_LOCKS[run_id] = lock, users + 1
    try:
        with lock:
            yield
    finally:
        with _LOCK:
            _, users = _OPERATION_LOCKS[run_id]
            if users == 1:
                del _OPERATION_LOCKS[run_id]
            else:
                _OPERATION_LOCKS[run_id] = lock, users - 1


def clear_run_controls_for_tests() -> None:
    with _LOCK:
        _CONTROLS.clear()
        _OPERATION_LOCKS.clear()


__all__ = [
    "clear_run_control",
    "clear_run_controls_for_tests",
    "get_run_control",
    "request_run_control",
    "run_operation_lock",
]
