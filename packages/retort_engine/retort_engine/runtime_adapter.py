from __future__ import annotations

from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from retort_engine.employee_queue import RetortEmployeeQueue
from retort_engine.models import EmployeeTaskRecord, ImprovementTask

if TYPE_CHECKING:
    from retort_engine.history import RetortHistoryStore


class EmployeeRuntimeHook(Protocol):
    def __call__(self, record: EmployeeTaskRecord) -> None: ...


class RetortEmployeeRuntimeAdapter:
    """Bridge durable logical tasks into an employee runtime without replaying hooks."""

    def __init__(
        self,
        queue_path: str | Path,
        *,
        history_store: str | Path = "",
        dispatch_hook: EmployeeRuntimeHook | None = None,
    ) -> None:
        self.queue = RetortEmployeeQueue(queue_path)
        self.history_store: RetortHistoryStore | None = None
        if history_store:
            from retort_engine.history import RetortHistoryStore

            self.history_store = RetortHistoryStore(history_store)
        self.dispatch_hook = dispatch_hook

    def submit_tasks(
        self, tasks: tuple[ImprovementTask, ...] | list[ImprovementTask], *, source: str
    ) -> tuple[EmployeeTaskRecord, ...]:
        records = self.queue.enqueue_tasks(tasks, source=source)
        for record in records:
            self.dispatch_to_employee_runtime(record)
        return records

    def dispatch_to_employee_runtime(self, record: EmployeeTaskRecord) -> bool:
        # A history failure here is known to precede any dispatch claim/hook.
        # Retry remains safe, including queue-only submissions and concurrent callers.
        if self.history_store:
            self.history_store.record_employee_task(record, idempotent=True)
        if self.dispatch_hook is None:
            return False
        claimed = self.queue.claim_dispatch(record)
        if claimed is None:
            return False
        try:
            self.dispatch_hook(claimed)
        except BaseException:
            # A hook may have acted before raising. Do not automatically repeat
            # a side effect whose outcome is unknown, including after restart.
            with suppress(OSError, ValueError):
                self.queue.finish_dispatch(claimed.queue_id, status="dispatch_unknown")
            raise
        self.queue.finish_dispatch(claimed.queue_id, status="dispatched")
        return True
