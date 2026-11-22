"""Reconcile a stopped runtime parent from existing business receipts only."""

from __future__ import annotations

import copy
from typing import Any

from app.application.agent_orchestrator.run_lifecycle import requires_retry_reconciliation
from app.application.agent_orchestrator.run_models import AgentRun
from app.application.agent_orchestrator.run_repository import get_agent_run_repository
from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
from app.application.agent_orchestrator.task_execution_repository import (
    get_task_execution_repository,
)
from app.application.agent_orchestrator.task_execution_sql_repository import (
    SQLAlchemyTaskExecutionRepository,
)
from app.domain.task_lifecycle.agent_runtime_contract import canonical_digest
from app.domain.task_lifecycle.agent_runtime_results import (
    base_runtime_result,
    model_unsettled,
    receipt_state,
)
from app.infrastructure.codex.binding import CodexBindingError, CodexBindingStore


def projection_allowed(run: AgentRun) -> bool:
    metadata = run.metadata.get("codex_runtime") or {}
    queued = run.metadata.get("_codex_queued_request") or {}
    return bool(
        run.metadata.get("runtime_type") == "codex"
        and run.status in {"waiting_user", "running", "blocked"}
        and run.metadata.get("runtime_expected_operations")
        and metadata.get("calls")
        and not metadata.get("coordinator_active")
        and metadata.get("revoked") is True
        and not model_unsettled(metadata)
        and queued.get("state") != "queued"
    )


def project_receipt_state(run: AgentRun, rows: list[dict[str, Any]]) -> AgentRun | None:
    """Build a projection; the SQL queue boundary independently verifies its inputs."""
    from app.application.agent_runtime.codex_runtime import (
        _classify,
        _project_child_calls,
    )

    if not projection_allowed(run):
        return None
    if requires_retry_reconciliation(run) and not any(
        receipt_state(row) == "unknown" for row in rows
    ):
        return None  # Later receipts cannot silently clear an earlier unknown outcome.
    metadata = run.metadata["codex_runtime"]
    CodexBindingStore._validate_goal(run, metadata)
    result = base_runtime_result(run.run_id)
    previous = run.final_output.get("codex_result") or {}
    for key in ("thread_id", "turn_id", "rounds", "trajectory", "session_messages", "run_events"):
        if key in previous:
            result[key] = copy.deepcopy(previous[key])
    status = _classify(
        result,
        rows,
        {**metadata, "expected_operations": run.metadata["runtime_expected_operations"]},
        "business",
        str(metadata.get("runtime_status") or "interrupted"),
    )
    if result.get("business_completed"):
        required = result["goal_coverage"]["required"]
        result["output"] = f"已根据业务回执核验全部 {required} 项冻结目标，任务已完成。"
    result["artifacts"] = [artifact.to_dict() for artifact in run.artifacts]
    fingerprint = canonical_digest(
        {
            "goal": run.metadata.get("runtime_goal_digest"),
            "generation": metadata.get("generation"),
            "status": status,
            "result": {key: value for key, value in result.items() if key != "run_events"},
        }
    )
    if run.metadata.get("runtime_receipt_projection") == fingerprint:
        return None
    projected = copy.deepcopy(run)
    _project_child_calls(projected, rows)
    projected.status = status
    projected.error = str(result.get("error") or "")
    projected.final_output["codex_result"] = result
    projected.metadata["runtime_receipt_projection"] = fingerprint
    if result.get("reconciliation_required"):
        projected.metadata.update(
            non_retryable=True, recovery={"state": "manual_reconciliation_required"}
        )
    projected.add_event(
        "runtime.receipts.refreshed",
        "已核对原业务任务回执",
        {
            "execution_state": result["execution_state"],
            "business_completed": result["business_completed"],
        },
    )
    return projected


def refresh_codex_receipts(
    run: AgentRun, *, repository: SQLAlchemyAgentRunRepository | None = None
) -> AgentRun:
    """Call after owner/tenant/Mod authorization; never start any runtime or tool."""
    resolved = repository or get_agent_run_repository()
    queue = get_task_execution_repository()
    if not isinstance(resolved, SQLAlchemyAgentRunRepository) or not isinstance(
        queue, SQLAlchemyTaskExecutionRepository
    ):
        return run
    repository = resolved
    current = repository.get(run.run_id)
    if current is None or not projection_allowed(current):
        return current or run
    execution = queue.get(run.run_id)
    if execution is not None and (
        execution.state not in {"waiting_approval", "paused", "blocked"}
        or execution.lease_owner
        or execution.lease_expires_at
    ):
        return current
    store = CodexBindingStore(repository)
    try:
        store.receipt_snapshot(current.run_id)
        current = store.get(current.run_id).run
        return queue.reconcile_codex_receipts(repository, current) or current
    except CodexBindingError:
        # Invalid/foreign evidence cannot promote the task. Keep the original
        # durable state available for inspection, without model or tool retries.
        return repository.get(run.run_id) or current
