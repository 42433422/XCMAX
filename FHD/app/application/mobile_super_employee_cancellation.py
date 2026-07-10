"""Process-local cancellation registry for LAN super-employee streams.

The LAN endpoint and its cancel endpoint run in the same desktop backend
process.  A registry entry is therefore deliberately an in-memory
``threading.Event``.  Keys include tenant and user identity so knowing another
user's client task id never grants cancellation authority.
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from typing import Callable

_CLIENT_TASK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class MobileSuperEmployeeTaskIdError(ValueError):
    """The caller supplied an unusable client task id or principal."""


class MobileSuperEmployeeTaskConflict(RuntimeError):
    """The same principal recently used this client task id."""


@dataclass(frozen=True, slots=True)
class MobileSuperEmployeeCancellationLease:
    """Ownership token used for compare-and-delete cleanup in ``finally``."""

    tenant_id: int
    user_id: int
    client_task_id: str
    event: threading.Event


class MobileSuperEmployeeCancellationRegistry:
    """Thread-safe, identity-scoped registry with optional reuse tombstones."""

    def __init__(
        self,
        *,
        tombstone_ttl_seconds: float = 0.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._tombstone_ttl_seconds = max(0.0, float(tombstone_ttl_seconds))
        self._clock = clock
        self._events: dict[tuple[int, int, str], threading.Event] = {}
        self._tombstones: dict[tuple[int, int, str], float] = {}
        self._lock = threading.RLock()

    @staticmethod
    def normalize_client_task_id(value: object) -> str:
        task_id = str(value or "").strip()
        if not _CLIENT_TASK_ID_RE.fullmatch(task_id):
            raise MobileSuperEmployeeTaskIdError(
                "client_task_id must be 1-128 safe ASCII characters"
            )
        return task_id

    @staticmethod
    def _principal_id(value: object, *, field: str, allow_zero: bool) -> int:
        if isinstance(value, bool):
            raise MobileSuperEmployeeTaskIdError(f"{field} is invalid")
        try:
            parsed = int(value)
        except (TypeError, ValueError) as exc:
            raise MobileSuperEmployeeTaskIdError(f"{field} is invalid") from exc
        minimum = 0 if allow_zero else 1
        if parsed < minimum:
            raise MobileSuperEmployeeTaskIdError(f"{field} is invalid")
        return parsed

    @classmethod
    def _key(
        cls,
        *,
        tenant_id: object,
        user_id: object,
        client_task_id: object,
    ) -> tuple[int, int, str]:
        return (
            cls._principal_id(tenant_id, field="tenant_id", allow_zero=True),
            cls._principal_id(user_id, field="user_id", allow_zero=False),
            cls.normalize_client_task_id(client_task_id),
        )

    def _prune_tombstones_locked(self, now: float) -> None:
        expired = [key for key, deadline in self._tombstones.items() if deadline <= now]
        for key in expired:
            self._tombstones.pop(key, None)

    def acquire(
        self,
        *,
        tenant_id: object,
        user_id: object,
        client_task_id: object,
    ) -> MobileSuperEmployeeCancellationLease:
        """Register one active stream or reject duplicate/recently-finished ids."""

        key = self._key(
            tenant_id=tenant_id,
            user_id=user_id,
            client_task_id=client_task_id,
        )
        with self._lock:
            now = self._clock()
            self._prune_tombstones_locked(now)
            if key in self._events or key in self._tombstones:
                raise MobileSuperEmployeeTaskConflict(
                    "client_task_id is already active or recently completed"
                )
            event = threading.Event()
            self._events[key] = event
        return MobileSuperEmployeeCancellationLease(*key, event)

    def cancel(
        self,
        *,
        tenant_id: object,
        user_id: object,
        client_task_id: object,
    ) -> bool:
        """Set only the exact tenant/user/task event; unknown keys stay opaque."""

        key = self._key(
            tenant_id=tenant_id,
            user_id=user_id,
            client_task_id=client_task_id,
        )
        with self._lock:
            event = self._events.get(key)
            if event is None:
                return False
            event.set()
            return True

    def release(self, lease: MobileSuperEmployeeCancellationLease) -> bool:
        """Remove only ``lease.event`` and optionally leave a late-cancel tombstone."""

        key = (lease.tenant_id, lease.user_id, lease.client_task_id)
        with self._lock:
            current = self._events.get(key)
            if current is not lease.event:
                return False
            self._events.pop(key, None)
            if self._tombstone_ttl_seconds > 0:
                self._tombstones[key] = self._clock() + self._tombstone_ttl_seconds
            return True

    def active_count(self) -> int:
        """Test/diagnostic count without exposing task identifiers."""

        with self._lock:
            return len(self._events)


mobile_super_employee_cancellations = MobileSuperEmployeeCancellationRegistry()


__all__ = [
    "MobileSuperEmployeeCancellationLease",
    "MobileSuperEmployeeCancellationRegistry",
    "MobileSuperEmployeeTaskConflict",
    "MobileSuperEmployeeTaskIdError",
    "mobile_super_employee_cancellations",
]
