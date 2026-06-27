from __future__ import annotations

from pathlib import Path
from typing import Protocol

from retort_engine.employee_queue import RetortEmployeeQueue
from retort_engine.history import RetortHistoryStore
from retort_engine.models import EmployeeTaskRecord, ImprovementTask


class EmployeeRuntimeHook(Protocol):
    def __call__(self, record: EmployeeTaskRecord) -> None: ...


class RetortEmployeeRuntimeAdapter:
    """Bridge Retort tasks into an employee_runtime, agent_loop, or workflow_scheduler."""

    def __init__(self, queue_path: str | Path, *, history_store: str | Path = "", dispatch_hook: EmployeeRuntimeHook | None = None) -> None:
        self.queue = RetortEmployeeQueue(queue_path)
        self.history_store = RetortHistoryStore(history_store) if history_store else None
        self.dispatch_hook = dispatch_hook

    def submit_tasks(self, tasks: tuple[ImprovementTask, ...] | list[ImprovementTask], *, source: str) -> tuple[EmployeeTaskRecord, ...]:
        records = self.queue.enqueue_tasks(tasks, source=source)
        for record in records:
            if self.history_store:
                self.history_store.record_employee_task(record)
            self.dispatch_to_employee_runtime(record)
        return records

    def dispatch_to_employee_runtime(self, record: EmployeeTaskRecord) -> bool:
        if self.dispatch_hook is None:
            return False
        self.dispatch_hook(record)
        return True
