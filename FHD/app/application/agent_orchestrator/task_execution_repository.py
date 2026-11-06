"""Durable background queue and renewable execution leases for Agent tasks."""

from __future__ import annotations

import copy
import logging
import os
import random
import threading
import weakref
from datetime import datetime
from typing import cast

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
from app.domain.task_lifecycle.adapters import LEASED_STATES, WAITING_STATES


class InMemoryTaskExecutionRepository:
    def __init__(
        self,
        *,
        jitter_ratio: float = 0.2,
        approval_timeout_seconds: float = 86400.0,
        rng: random.Random | None = None,
    ) -> None:
        self._rows: dict[str, AgentTaskExecution] = {}
        self._lock = threading.RLock()
        self._jitter_ratio = jitter_ratio
        self._approval_timeout_seconds = approval_timeout_seconds
        self._rng = rng or random.Random()
        from app.domain.task_lifecycle.control import MemoryBook

        self._book = MemoryBook()
        remember_open_repository(self)

    def enqueue(
        self,
        run: AgentRun,
        *,
        requested_by: str = "",
        priority: int = 100,
        idempotency_key: str = "",
        fingerprint: str = "",
    ) -> AgentTaskExecution:
        now = utc_now_iso()
        with self._lock:
            if idempotency_key:
                prior = self._book.claim_key(
                    "agent",
                    tenant_id_of_run(run),
                    idempotency_key,
                    fingerprint or run.message,
                    run.run_id,
                )
                if prior and prior in self._rows:
                    return copy.deepcopy(self._rows[prior])
            row = self._rows.get(run.run_id)
            if row is None:
                row = AgentTaskExecution(
                    run_id=run.run_id,
                    task_id=_task_id_of(run),
                    user_id=run.user_id,
                    tenant_id=tenant_id_of_run(run),
                    created_at=now,
                )
            from app.domain.task_lifecycle.adapters import execution_requeue_allowed

            if row.state not in LEASED_STATES and not execution_requeue_allowed(row.state):
                return copy.deepcopy(row)
            if row.state not in LEASED_STATES:
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

    def enqueue_waiting_approval(
        self,
        run: AgentRun,
        *,
        requested_by: str = "",
        priority: int = 100,
        approver: str = "",
    ) -> AgentTaskExecution:
        """Queue then park before any other worker can observe the queued row."""
        with self._lock:
            self.enqueue(run, requested_by=requested_by, priority=priority)
            parked = self.request_approval(run.run_id, approver or run.user_id)
            if parked is None:
                raise RuntimeError("审批队列行未能持久化")
            return parked

    def claim(
        self,
        owner_id: str,
        *,
        lease_seconds: float,
        now: str | None = None,
        run_id: str | None = None,
        tenant_id: str | None = None,
    ) -> AgentTaskExecution | None:
        current = str(now or utc_now_iso())
        wanted = str(run_id or "")
        with self._lock:
            from app.domain.task_lifecycle.machine import DEFAULT_MAX_ATTEMPTS

            self._expire_approvals_locked(current)
            eligible = [
                row
                for row in self._rows.values()
                if (not wanted or row.run_id == wanted)
                and (tenant_id is None or row.tenant_id == str(tenant_id))
                and row.available_at <= current
                and (
                    row.state == "queued"
                    or (
                        row.state in LEASED_STATES
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
            for row in eligible:
                recovered = row.state in LEASED_STATES
                body = self._book.get("agent", row.tenant_id, row.run_id)
                if recovered and body.get("effects"):
                    self._stop_locked(row, current, "failed", "needs_verification")
                    continue
                if recovered and row.execution_count + 1 > DEFAULT_MAX_ATTEMPTS:
                    row.state = "failed"
                    row.lease_owner = ""
                    row.lease_expires_at = ""
                    row.last_error_code = "retries_exhausted"
                    row.finished_at = current
                    row.updated_at = current
                    self._rows[row.run_id] = copy.deepcopy(row)
                    continue
                row.state = "running"
                row.lease_owner = str(owner_id or "")
                row.lease_expires_at = _deadline(current, lease_seconds)
                row.heartbeat_at = current
                row.execution_count += 1
                row.recovery_count += int(recovered)
                row.updated_at = current
                self._rows[row.run_id] = copy.deepcopy(row)
                return copy.deepcopy(row)
            return None

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
            if (
                row is None
                or row.state not in LEASED_STATES
                or row.lease_owner != owner_id
                or not row.lease_expires_at
                or row.lease_expires_at <= current
            ):
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
            if (
                row is None
                or row.state not in LEASED_STATES
                or row.lease_owner != owner_id
                or not row.lease_expires_at
                or row.lease_expires_at <= utc_now_iso()
            ):
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
    ) -> AgentTaskExecution | None:
        from app.domain.task_lifecycle.adapters import (
            WAITING_STATES,
            canonical_execution_state,
            execution_transition_allowed,
        )
        from app.domain.task_lifecycle.control import jittered_delay, remember, settle_target

        body = self._book.get("agent", row.tenant_id, row.run_id)
        requested = canonical_execution_state(state)
        if not execution_transition_allowed(row.state, requested):
            return None
        visible, error_code = settle_target(
            state,
            error_code,
            row.execution_count,
            open_effects=bool(body.get("effects")),
        )
        now = utc_now_iso()
        if visible == "queued" and canonical_execution_state(state) == "failed":
            delay = jittered_delay(
                row.execution_count, jitter_ratio=self._jitter_ratio, rng=self._rng
            )
            previous = row.state
            row.state = "queued"
            row.available_at = _deadline(now, delay)
            row.lease_owner = ""
            row.lease_expires_at = ""
            row.heartbeat_at = ""
            row.finished_at = ""
            row.last_error_code = str(error_code or "")[:64]
            row.updated_at = now
            body["effects"] = []
            body["available_at"] = row.available_at
            remember(
                body,
                at=now,
                source=previous,
                target="queued",
                code=str(error_code or ""),
                actor="",
            )
            self._book.put("agent", row.tenant_id, row.run_id, body)
            self._rows[row.run_id] = copy.deepcopy(row)
            return copy.deepcopy(row)
        previous = row.state
        row.state = cast(ExecutionState, visible)
        row.lease_owner = ""
        row.lease_expires_at = ""
        row.heartbeat_at = ""
        row.last_error_code = str(error_code or "")[:64]
        row.updated_at = now
        if visible in {"succeeded", "failed", "timed_out", "cancelled", "rejected"}:
            row.finished_at = now
        if error_code != "needs_verification":
            body["effects"] = []
        if visible in WAITING_STATES or visible == "waiting_approval":
            body["approver"] = body.get("approver") or row.user_id
            body["approval_requested_at"] = now
        remember(
            body,
            at=now,
            source=previous,
            target=visible,
            code=str(error_code or ""),
            actor="",
        )
        self._book.put("agent", row.tenant_id, row.run_id, body)
        self._rows[row.run_id] = copy.deepcopy(row)
        return copy.deepcopy(row)

    def mark_open_effect(self, run_id: str, effect_id: str = "dispatch") -> None:
        with self._lock:
            row = self._rows.get(str(run_id or ""))
            if row is None or row.state not in LEASED_STATES:
                return
            body = self._book.get("agent", row.tenant_id, row.run_id)
            effects = set(body.get("effects") or [])
            effects.add(str(effect_id or "dispatch"))
            body["effects"] = sorted(effects)
            self._book.put("agent", row.tenant_id, row.run_id, body)

    def request_approval(self, run_id: str, approver: str) -> AgentTaskExecution | None:
        with self._lock:
            row = self._rows.get(str(run_id or ""))
            if row is None:
                return None
            body = self._book.get("agent", row.tenant_id, row.run_id)
            body["approver"] = str(approver or "")
            self._book.put("agent", row.tenant_id, row.run_id, body)
            return self._transition_locked(row, "paused", error_code="approval_requested")

    def resolve_approval(self, run_id: str, decision: str, actor: str) -> AgentTaskExecution | None:
        from app.domain.task_lifecycle.control import TaskLifecycleError, approval_actor_allowed

        with self._lock:
            row = self._rows.get(str(run_id or ""))
            if row is None:
                return None
            body = self._book.get("agent", row.tenant_id, row.run_id)
            if not approval_actor_allowed(body, actor):
                raise TaskLifecycleError("无权审批该任务")
            target = "queued" if decision == "approve" else "rejected"
            if decision not in {"approve", "reject"}:
                raise TaskLifecycleError("未知审批决定")
            if target == "queued":
                from app.domain.task_lifecycle.adapters import execution_transition_allowed

                if not execution_transition_allowed(row.state, "queued"):
                    return None
                previous = row.state
                now = utc_now_iso()
                row.state = "queued"
                row.available_at = now
                row.lease_owner = ""
                row.lease_expires_at = ""
                row.finished_at = ""
                row.last_error_code = ""
                row.updated_at = now
                from app.domain.task_lifecycle.control import remember

                remember(
                    body, at=now, source=previous, target="queued", code="approved", actor=actor
                )
                self._book.put("agent", row.tenant_id, row.run_id, body)
                self._rows[row.run_id] = copy.deepcopy(row)
                return copy.deepcopy(row)
            return self._transition_locked(row, target, error_code="approval_rejected")

    def lifecycle(self, run_id: str) -> dict[str, object]:
        with self._lock:
            row = self._rows.get(str(run_id or ""))
            tenant = row.tenant_id if row is not None else ""
            return copy.deepcopy(self._book.get("agent", tenant, str(run_id or "")))

    def _stop_locked(self, row: AgentTaskExecution, current: str, state: str, code: str) -> None:
        from app.domain.task_lifecycle.control import remember

        previous = row.state
        row.state = cast(ExecutionState, state)
        row.lease_owner = ""
        row.lease_expires_at = ""
        row.last_error_code = code
        row.finished_at = current
        row.updated_at = current
        body = self._book.get("agent", row.tenant_id, row.run_id)
        remember(body, at=current, source=previous, target=state, code=code, actor="")
        self._book.put("agent", row.tenant_id, row.run_id, body)
        self._rows[row.run_id] = copy.deepcopy(row)

    def _expire_approvals_locked(self, current: str) -> None:
        from app.domain.task_lifecycle.control import remember

        moment = datetime.fromisoformat(current.replace("Z", "+00:00"))
        for row in list(self._rows.values()):
            if row.state not in WAITING_STATES:
                continue
            body = self._book.get("agent", row.tenant_id, row.run_id)
            started = str(body.get("approval_requested_at") or row.updated_at or "")
            if not started:
                continue
            age = (moment - datetime.fromisoformat(started.replace("Z", "+00:00"))).total_seconds()
            if age < self._approval_timeout_seconds:
                continue
            previous = row.state
            row.state = "rejected"
            row.last_error_code = "approval_timeout"
            row.finished_at = current
            row.updated_at = current
            remember(
                body,
                at=current,
                source=previous,
                target="rejected",
                code="approval_timeout",
                actor="",
            )
            self._book.put("agent", row.tenant_id, row.run_id, body)
            self._rows[row.run_id] = copy.deepcopy(row)

    def clear(self) -> None:
        with self._lock:
            self._rows.clear()


_task_execution_repository: TaskExecutionRepository | None = None
_OPEN_REPOSITORIES: weakref.WeakSet = weakref.WeakSet()


def remember_open_repository(repository: object) -> None:
    """Keep a live queue visible to the executor without a second state machine."""
    _OPEN_REPOSITORIES.add(repository)


def locate_task_execution(run_id: str, *, fallback_id: str = ""):
    """Return the open queue row for this task, or nothing when no lifecycle exists."""
    wanted = str(run_id or "")
    if not wanted:
        return None, None
    candidates = tuple(dict.fromkeys(item for item in (wanted, str(fallback_id or "")) if item))
    repositories = list(_OPEN_REPOSITORIES)
    if _task_execution_repository is not None:
        repositories.append(_task_execution_repository)
    for candidate in candidates:
        for repository in repositories:
            row = repository.get(candidate)
            if row is not None:
                return repository, row
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return None, None
    repository = get_task_execution_repository()
    for candidate in candidates:
        row = repository.get(candidate)
        if row is not None:
            return repository, row
    return None, None


def get_task_execution_repository() -> TaskExecutionRepository:
    from app.application.agent_orchestrator.run_repository import agent_memory_mode_enabled

    global _task_execution_repository
    if _task_execution_repository is None:
        if agent_memory_mode_enabled():
            _task_execution_repository = InMemoryTaskExecutionRepository()
        else:
            try:
                repository = SQLAlchemyTaskExecutionRepository()
                repository.get("")
            except RECOVERABLE_ERRORS as exc:
                raise RuntimeError("durable task execution queue unavailable") from exc
            _task_execution_repository = repository
    return _task_execution_repository


def set_task_execution_repository_for_tests(
    repository: TaskExecutionRepository | None,
) -> None:
    global _task_execution_repository
    _task_execution_repository = repository
    if repository is not None:
        remember_open_repository(repository)


__all__ = [
    "AgentTaskExecution",
    "ExecutionState",
    "InMemoryTaskExecutionRepository",
    "SQLAlchemyTaskExecutionRepository",
    "TaskExecutionRepository",
    "get_task_execution_repository",
    "set_task_execution_repository_for_tests",
]
