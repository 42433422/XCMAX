"""Durable background queue and renewable execution leases for Agent tasks."""

from __future__ import annotations

import copy
import logging
import os
import threading

from app.application.agent_orchestrator.run_models import AgentRun, utc_now_iso
from app.application.agent_orchestrator.task_models import tenant_id_of_run
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

from app.application.agent_orchestrator.task_execution_models import (
    AgentTaskExecution,
    ExecutionState,
    TaskExecutionRepository,
    _deadline,
    _task_id_of,
)
from app.application.agent_orchestrator.task_execution_sql_repository import (
    SQLAlchemyTaskExecutionRepository,
)


class InMemoryTaskExecutionRepository:
    def __init__(self) -> None:
        self._rows: dict[str, AgentTaskExecution] = {}
        self._lock = threading.RLock()

    def enqueue(
        self,
        run: AgentRun,
        *,
        requested_by: str = "",
        priority: int = 100,
    ) -> AgentTaskExecution:
        now = utc_now_iso()
        with self._lock:
            row = self._rows.get(run.run_id)
            if row is None:
                row = AgentTaskExecution(
                    run_id=run.run_id,
                    task_id=_task_id_of(run),
                    user_id=run.user_id,
                    tenant_id=tenant_id_of_run(run),
                    created_at=now,
                )
            if row.state != "claimed":
                row.state = "queued"
                row.lease_owner = ""
                row.lease_expires_at = ""
                row.heartbeat_at = ""
                row.finished_at = ""
            row.priority = int(priority)
            row.available_at = now
            row.requested_by = str(requested_by or "")
            row.last_error_code = ""
            row.updated_at = now
            self._rows[row.run_id] = copy.deepcopy(row)
            return copy.deepcopy(row)

    def get(self, run_id: str) -> AgentTaskExecution | None:
        with self._lock:
            row = self._rows.get(str(run_id or ""))
            return copy.deepcopy(row) if row is not None else None

    def list_for_run_ids(self, run_ids: list[str]) -> dict[str, AgentTaskExecution]:
        wanted = {str(run_id or "") for run_id in run_ids if str(run_id or "")}
        with self._lock:
            return {
                run_id: copy.deepcopy(row) for run_id, row in self._rows.items() if run_id in wanted
            }

    def claim(
        self,
        owner_id: str,
        *,
        lease_seconds: float,
        now: str | None = None,
    ) -> AgentTaskExecution | None:
        current = str(now or utc_now_iso())
        with self._lock:
            eligible = [
                row
                for row in self._rows.values()
                if row.available_at <= current
                and (
                    row.state == "queued"
                    or (
                        row.state == "claimed"
                        and bool(row.lease_expires_at)
                        and row.lease_expires_at <= current
                    )
                )
            ]
            if not eligible:
                return None
            eligible.sort(
                key=lambda row: (row.priority, row.available_at, row.created_at, row.run_id)
            )
            row = eligible[0]
            recovered = row.state == "claimed"
            row.state = "claimed"
            row.lease_owner = str(owner_id or "")
            row.lease_expires_at = _deadline(current, lease_seconds)
            row.heartbeat_at = current
            row.execution_count += 1
            row.recovery_count += int(recovered)
            row.updated_at = current
            self._rows[row.run_id] = copy.deepcopy(row)
            return copy.deepcopy(row)

    def heartbeat(
        self,
        run_id: str,
        owner_id: str,
        *,
        lease_seconds: float,
        now: str | None = None,
    ) -> bool:
        current = str(now or utc_now_iso())
        with self._lock:
            row = self._rows.get(str(run_id or ""))
            if row is None or row.state != "claimed" or row.lease_owner != owner_id:
                return False
            row.heartbeat_at = current
            row.lease_expires_at = _deadline(current, lease_seconds)
            row.updated_at = current
            return True

    def finish(
        self,
        run_id: str,
        owner_id: str,
        state: str,
        *,
        error_code: str = "",
    ) -> AgentTaskExecution | None:
        with self._lock:
            row = self._rows.get(str(run_id or ""))
            if row is None or row.state != "claimed" or row.lease_owner != owner_id:
                return None
            return self._transition_locked(row, state, error_code=error_code)

    def transition(
        self,
        run_id: str,
        state: str,
        *,
        error_code: str = "",
    ) -> AgentTaskExecution | None:
        with self._lock:
            row = self._rows.get(str(run_id or ""))
            if row is None:
                return None
            return self._transition_locked(row, state, error_code=error_code)

    def _transition_locked(
        self,
        row: AgentTaskExecution,
        state: str,
        *,
        error_code: str,
    ) -> AgentTaskExecution:
        now = utc_now_iso()
        row.state = str(state)  # type: ignore[assignment]
        row.lease_owner = ""
        row.lease_expires_at = ""
        row.heartbeat_at = ""
        row.last_error_code = str(error_code or "")[:64]
        row.updated_at = now
        if state in {"completed", "failed", "cancelled", "blocked"}:
            row.finished_at = now
        self._rows[row.run_id] = copy.deepcopy(row)
        return copy.deepcopy(row)

    def clear(self) -> None:
        with self._lock:
            self._rows.clear()


_task_execution_repository: TaskExecutionRepository | None = None


def get_task_execution_repository() -> TaskExecutionRepository:
    global _task_execution_repository
    if _task_execution_repository is None:
        try:
            repository = SQLAlchemyTaskExecutionRepository()
            repository.get("")
            _task_execution_repository = repository
        except RECOVERABLE_ERRORS as exc:
            require_durable = os.environ.get(
                "XCAGI_AGENT_RUN_REQUIRE_DURABLE", ""
            ).strip().lower() in {"1", "true", "yes", "on"}
            if require_durable:
                raise RuntimeError("durable task execution queue unavailable") from exc
            logger.warning("Task execution SQL queue unavailable, using memory: %s", exc)
            _task_execution_repository = InMemoryTaskExecutionRepository()
    return _task_execution_repository


def set_task_execution_repository_for_tests(
    repository: TaskExecutionRepository | None,
) -> None:
    global _task_execution_repository
    _task_execution_repository = repository


__all__ = [
    "AgentTaskExecution",
    "ExecutionState",
    "InMemoryTaskExecutionRepository",
    "SQLAlchemyTaskExecutionRepository",
    "TaskExecutionRepository",
    "get_task_execution_repository",
    "set_task_execution_repository_for_tests",
]
