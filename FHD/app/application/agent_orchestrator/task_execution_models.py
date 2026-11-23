"""Shared types for durable Agent task execution repositories."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Protocol

from app.application.agent_orchestrator.run_models import AgentRun

ExecutionState = Literal[
    "queued",
    "running",
    "waiting_approval",
    "waiting_input",
    "waiting_auth",
    "unknown",
    "succeeded",
    "failed",
    "timed_out",
    "cancelled",
    "rejected",
    "claimed",
    "paused",
    "blocked",
    "completed",
]

ADMITTED_STATES = frozenset(
    {
        "queued",
        "running",
        "claimed",
        "waiting_approval",
        "waiting_input",
        "waiting_auth",
        "unknown",
        "paused",
        "blocked",
    }
)


class TaskQueueCapacityError(RuntimeError):
    """The original queue refused admission before any task execution."""

    code = "task_queue_capacity"
    retry_after = 1

    def __init__(self, scope: str) -> None:
        super().__init__("任务队列暂时繁忙，请稍后重试。")
        self.scope = scope

    def result(self) -> dict[str, Any]:
        return {
            "success": False,
            "error_code": self.code,
            "message": str(self),
            "retryable": True,
            "retry_after": self.retry_after,
            "outcome": "not_started",
            "admission_scope": self.scope,
        }


def _bounded_setting(name: str, default: int, maximum: int) -> int:
    try:
        return max(1, min(maximum, int(os.environ.get(name, str(default)))))
    except ValueError:
        return default


@dataclass(frozen=True)
class TaskDispatchLimits:
    admitted: int
    tenant_admitted: int
    running: int
    tenant_running: int
    interactive_seconds: int
    aging_seconds: int

    @classmethod
    def configured(cls) -> TaskDispatchLimits:
        workers = _bounded_setting("XCAGI_AGENT_TASK_WORKERS", 4, 16)
        running = _bounded_setting("XCAGI_AGENT_TASK_MAX_INFLIGHT", workers, 128)
        admitted = _bounded_setting("XCAGI_AGENT_TASK_MAX_ADMITTED", 1024, 4096)
        return cls(
            admitted,
            _bounded_setting("XCAGI_AGENT_TASK_TENANT_MAX_ADMITTED", min(128, admitted), admitted),
            running,
            _bounded_setting("XCAGI_AGENT_TASK_TENANT_MAX_INFLIGHT", max(1, running - 1), running),
            _bounded_setting("XCAGI_AGENT_TASK_INTERACTIVE_SECONDS", 10, 60),
            _bounded_setting("XCAGI_AGENT_TASK_AGING_SECONDS", 30, 300),
        )


def dispatch_tenant(row: Any) -> str:
    return f"tenant:{row.tenant_id}" if row.tenant_id else f"actor:{row.user_id}"


def freeze_dispatch_policy(run: AgentRun, specs: dict[tuple[str, str], Any]) -> dict[str, Any]:
    """Derive bounded single-read capacity from host contracts, never caller priority."""
    from app.application.agent_orchestrator.business_action_ledger import canonical_hash
    from app.application.agent_orchestrator.tool_timeouts import uses_elt_file_deadlines
    from app.application.workflow.workflow_types import plan_from_dict, validate_plan_graph

    background = {"class": "background"}
    if (
        len(run.steps) != 1
        or run.metadata.get("runtime_type") == "codex"
        or run.metadata.get("cross_module_dispatch") == "approved"
    ):
        return background
    step = run.steps[0]
    plan = plan_from_dict(run.metadata.get("plan"))
    if plan is None or len(plan.nodes) != 1 or validate_plan_graph(plan):
        return background
    node = plan.nodes[0]
    if (
        (node.node_id, node.tool_id, node.action, node.params)
        != (step.node_id, step.tool_id, step.action, step.params)
        or node.depends_on
        or node.next
        or node.branches
    ):
        return background
    spec = specs.get((step.tool_id, step.action))
    if (
        spec is None
        or not spec.idempotent
        or not spec.is_read_only_call(step.params)
        or step.depends_on
        or uses_elt_file_deadlines(step.tool_id, step.action, step.params)
        or type(spec.timeout_seconds) is not int
        or spec.timeout_seconds <= 0
    ):
        return background
    return {
        "class": "interactive",
        "step_id": step.step_id,
        "tool_id": step.tool_id,
        "action": step.action,
        "contract_sha256": spec.schema_digest,
        "params_sha256": canonical_hash(step.params),
        "plan_sha256": canonical_hash(run.metadata["plan"]),
        "deadline_seconds": min(
            spec.timeout_seconds, TaskDispatchLimits.configured().interactive_seconds
        ),
    }


def dispatch_capacity_allows(
    active: list[AgentTaskExecution],
    candidate: AgentTaskExecution,
    limits: TaskDispatchLimits,
) -> bool:
    tenant = [row for row in active if dispatch_tenant(row) == dispatch_tenant(candidate)]
    if len(active) >= limits.running or len(tenant) >= limits.tenant_running:
        return False
    if candidate.dispatch_class != "interactive":
        # A background operation cannot consume the last bounded-read slot.
        return sum(row.dispatch_class != "interactive" for row in active) < max(
            1, limits.running - 1
        ) and sum(row.dispatch_class != "interactive" for row in tenant) < max(
            1, limits.tenant_running - 1
        )
    return True


def dispatch_order_key(
    row: AgentTaskExecution,
    active: list[AgentTaskExecution],
    last_served: dict[str, str],
    now: str,
    limits: TaskDispatchLimits,
) -> tuple[Any, ...]:
    tenant = dispatch_tenant(row)
    try:
        aged = (
            datetime.fromisoformat(now) - datetime.fromisoformat(row.available_at)
        ).total_seconds() >= limits.aging_seconds
    except (TypeError, ValueError):
        aged = False
    return (
        sum(dispatch_tenant(item) == tenant for item in active),
        last_served.get(tenant, ""),
        not aged,
        0 if aged else row.priority,
        row.available_at,
        row.created_at,
        row.run_id,
    )


def dispatched_run_state(run: AgentRun) -> tuple[str, str]:
    """Project the persisted run receipt when its worker yields execution."""
    from app.application.agent_orchestrator.result_verification import verified_step_output
    from app.domain.task_lifecycle.adapters import LegacyTransitionError, canonicalize
    from app.domain.task_lifecycle.results import execution_result_pending_state

    recovery = run.metadata.get("recovery")
    pending = execution_result_pending_state(
        {
            "final_output": run.final_output,
            "outputs": [verified_step_output(run, step) for step in run.steps if step.output],
        }
    )
    if (
        isinstance(recovery, dict) and recovery.get("state") == "manual_reconciliation_required"
    ) or pending == "unknown":
        return "unknown", "needs_verification"
    if pending in {"waiting_input", "waiting_auth", "waiting_approval", "paused", "blocked"}:
        return pending, ""
    if pending:
        return "unknown", "worker_incomplete_state"
    if run.status == "waiting_user":
        waiting = next((step for step in run.steps if step.status == "waiting_user"), None)
        if waiting is None or waiting.tool_id == "clarify":
            return "waiting_input", ""
        return "waiting_approval", ""
    try:
        state = canonicalize("agent", run.status)
    except LegacyTransitionError:
        return "unknown", "worker_incomplete_state"
    if state in {"created", "queued", "running"}:
        # A worker returning is not a completion receipt for the work it accepted.
        return "unknown", "worker_incomplete_state"
    return state, "needs_verification" if state == "unknown" else ""


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
    dispatch_class: str = "background"
    dispatch_deadline_seconds: int = 0

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

    def enqueue_waiting_approval(
        self,
        run: AgentRun,
        *,
        requested_by: str = "",
        priority: int = 100,
        approver: str = "",
    ) -> AgentTaskExecution: ...

    def get(self, run_id: str) -> AgentTaskExecution | None: ...

    def list_for_run_ids(self, run_ids: list[str]) -> dict[str, AgentTaskExecution]: ...

    def claim(
        self,
        owner_id: str,
        *,
        lease_seconds: float,
        now: str | None = None,
        run_id: str | None = None,
        tenant_id: str | None = None,
        interactive_only: bool = False,
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
    "dispatched_run_state",
]
