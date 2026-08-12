"""Shared types for durable Agent task execution repositories."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol

from app.application.agent_orchestrator.run_models import AgentRun

ExecutionState = Literal[
    "queued",
    "claimed",
    "paused",
    "blocked",
    "completed",
    "failed",
    "cancelled",
]


def _task_id_of(run: AgentRun) -> str:
    context = run.metadata.get("task_context")
    if isinstance(context, dict):
        return str(context.get("task_id") or run.run_id)
    return run.run_id


def _deadline(now: str, seconds: float) -> str:
    parsed = datetime.fromisoformat(now.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return (parsed + timedelta(seconds=max(1.0, float(seconds)))).isoformat()


@dataclass
class AgentTaskExecution:
    run_id: str
    task_id: str
    user_id: str
    tenant_id: str = ""
    state: ExecutionState = "queued"
    priority: int = 100
    available_at: str = ""
    lease_owner: str = ""
    lease_expires_at: str = ""
    heartbeat_at: str = ""
    execution_count: int = 0
    recovery_count: int = 0
    requested_by: str = ""
    last_error_code: str = ""
    created_at: str = ""
    updated_at: str = ""
    finished_at: str = ""

    def to_dict(self) -> dict[str, str | int]:
        return {
            "run_id": self.run_id,
            "task_id": self.task_id,
            "user_id": self.user_id,
            "tenant_id": self.tenant_id,
            "state": self.state,
            "priority": self.priority,
            "available_at": self.available_at,
            "lease_owner": self.lease_owner,
            "lease_expires_at": self.lease_expires_at,
            "heartbeat_at": self.heartbeat_at,
            "execution_count": self.execution_count,
            "recovery_count": self.recovery_count,
            "requested_by": self.requested_by,
            "last_error_code": self.last_error_code,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "finished_at": self.finished_at,
        }


class TaskExecutionRepository(Protocol):
    def enqueue(
        self,
        run: AgentRun,
        *,
        requested_by: str = "",
        priority: int = 100,
    ) -> AgentTaskExecution: ...

    def get(self, run_id: str) -> AgentTaskExecution | None: ...

    def list_for_run_ids(self, run_ids: list[str]) -> dict[str, AgentTaskExecution]: ...

    def claim(
        self,
        owner_id: str,
        *,
        lease_seconds: float,
        now: str | None = None,
    ) -> AgentTaskExecution | None: ...

    def heartbeat(
        self,
        run_id: str,
        owner_id: str,
        *,
        lease_seconds: float,
        now: str | None = None,
    ) -> bool: ...

    def finish(
        self,
        run_id: str,
        owner_id: str,
        state: str,
        *,
        error_code: str = "",
    ) -> AgentTaskExecution | None: ...

    def transition(
        self,
        run_id: str,
        state: str,
        *,
        error_code: str = "",
    ) -> AgentTaskExecution | None: ...

    def clear(self) -> None: ...


__all__ = [
    "AgentTaskExecution",
    "ExecutionState",
    "TaskExecutionRepository",
]
