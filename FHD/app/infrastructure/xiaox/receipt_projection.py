"""Reconcile a stopped runtime parent from existing business receipts only."""

from __future__ import annotations

import copy
import logging
from collections.abc import Callable
from typing import Any

from app.application.agent_orchestrator.run_lifecycle import requires_retry_reconciliation
from app.application.agent_orchestrator.run_models import AgentRun
from app.application.agent_orchestrator.run_repository import (
    AgentRunRepository,
    get_agent_run_repository,
)
from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
from app.application.agent_orchestrator.task_execution_repository import (
    get_task_execution_repository,
)
from app.application.agent_orchestrator.task_execution_sql_repository import (
    SQLAlchemyTaskExecutionRepository,
)
from app.domain.task_lifecycle.agent_runtime_contract import canonical_digest
from app.domain.task_lifecycle.agent_runtime_results import (
    ACTIVE_STATES,
    WAITING_STATES,
    base_runtime_result,
    classification_metadata,
    classify_runtime_result,
    failure_diagnostics,
    model_unsettled,
    receipt_state,
)
from app.infrastructure.xiaox.binding import XiaoxBindingError, XiaoxBindingStore
from app.infrastructure.xiaox.receipts import project_child_calls, resume_error

logger = logging.getLogger(__name__)


def projection_allowed(run: AgentRun) -> bool:
    metadata = run.metadata.get("xiaox_runtime") or {}
    queued = run.metadata.get("_xiaox_queued_request") or {}
    return bool(
        run.metadata.get("runtime_type") == "xiaox"
        and run.status in {"waiting_user", "running", "blocked"}
        and run.metadata.get("runtime_goal_contract")
        and metadata.get("calls")
        and not metadata.get("coordinator_active")
        and metadata.get("revoked") is True
        and not model_unsettled(metadata)
        and queued.get("state") != "queued"
    )


def _continuation_ready(run: AgentRun, rows: list[dict[str, Any]]) -> bool:
    """Resume new approved evidence; settled failed exploration is not a new effect."""
    completed = []
    for row in rows:
        receipt = row.get("receipt") or {}
        state = receipt_state(row)
        if (
            state == "completed"
            and receipt.get("verified") is True
            and receipt.get("success") is True
        ):
            completed.append(row)
        elif not (
            state in {"failed", "not_started", "not_executed"}
            and row.get("read_only") is True
            and receipt.get("success") is False
        ):
            return False
    if not completed:
        return False
    previous = run.final_output.get("xiaox_result") or {}
    if previous.get("exit_status") == "continuation_pending":
        return True
    prior = {str(row.get("call_id")): row for row in previous.get("business_receipts") or []}
    return any(
        receipt_state(prior[str(row["call_id"])]) in WAITING_STATES | ACTIVE_STATES
        for row in completed
        if str(row.get("call_id")) in prior
    )


def project_receipt_state(run: AgentRun, rows: list[dict[str, Any]]) -> AgentRun | None:
    """Build a projection; the SQL queue boundary independently verifies its inputs."""
    if not projection_allowed(run):
        return None
    if requires_retry_reconciliation(run) and not any(
        receipt_state(row) == "unknown" for row in rows
    ):
        return None  # Later receipts cannot silently clear an earlier unknown outcome.
    metadata = run.metadata["xiaox_runtime"]
    XiaoxBindingStore._validate_goal(run, metadata)
    result = base_runtime_result(run.run_id)
    previous = run.final_output.get("xiaox_result") or {}
    for key in (
        "thread_id",
        "turn_id",
        "rounds",
        "trajectory",
        "session_messages",
        "run_events",
        "output",
        "goal_response",
        "active_seconds",
        "model_request_attempts",
    ):
        if key in previous:
            result[key] = copy.deepcopy(previous[key])
    status = classify_runtime_result(
        result,
        rows,
        classification_metadata(run),
        str(run.metadata.get("runtime_completion_mode") or "auto"),
        str(metadata.get("runtime_status") or "interrupted"),
    )
    if result.get("exit_status") == "goal_verification_required" and _continuation_ready(run, rows):
        # A completed child is new evidence for the same runtime, never proof
        # that every original goal is complete. The dispatcher owns continuation.
        status = "running"
        result.update(
            execution_state="running",
            exit_status="continuation_pending",
            resume_required=True,
            output="已核对原业务回执，正在继续完成和核验原任务。",
            error="",
        )
    result["artifacts"] = [artifact.to_dict() for artifact in run.artifacts]
    result.update(failure_diagnostics(run, result))
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
    project_child_calls(projected, rows)
    projected.status = status
    projected.error = str(result.get("error") or "")
    projected.final_output["xiaox_result"] = result
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


def refresh_xiaox_receipts(
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
    store = XiaoxBindingStore(repository)
    try:
        store.receipt_snapshot(current.run_id)
        current = store.get(current.run_id).run
        return queue.reconcile_xiaox_receipts(repository, current) or current
    except XiaoxBindingError:
        # Invalid/foreign evidence cannot promote the task. Keep the original
        # durable state available for inspection, without model or tool retries.
        return repository.get(run.run_id) or current


def resume_ready_xiaox_runs(
    *,
    repository: AgentRunRepository,
    stopped: Callable[[], bool] = lambda: False,
    limit: int = 50,
    cursor: dict[str, str] | None = None,
) -> int:
    """Queue original threads after approval/readback, independently of HTTP GETs.

    The existing queue transaction fences owner, control, prior request, lease
    and unresolved effects. Its worker rechecks the fresh child evidence before
    starting Xiaox; neither this scan nor a result read executes business tools.
    """
    from app.application.agent_orchestrator.run_models import utc_now_iso
    from app.db.models.agent import AgentRunRecord
    from app.infrastructure.xiaox.queued_runtime import enqueue_resume, stage_queued_request
    from app.utils.operational_errors import RECOVERABLE_ERRORS

    if not isinstance(repository, SQLAlchemyAgentRunRepository):
        return 0
    from sqlalchemy import and_, or_

    with repository.transaction(read_only=True) as db:
        query = db.query(AgentRunRecord).filter(
            AgentRunRecord.intent == "xiaox.runtime",
            AgentRunRecord.status.in_(("waiting_user", "running")),
        )
        if cursor:
            query = query.filter(
                or_(
                    AgentRunRecord.updated_at > cursor["updated_at"],
                    and_(
                        AgentRunRecord.updated_at == cursor["updated_at"],
                        AgentRunRecord.run_id > cursor["run_id"],
                    ),
                )
            )
        records = (
            query.order_by(AgentRunRecord.updated_at, AgentRunRecord.run_id)
            .limit(max(0, min(limit, 200)))
            .all()
        )
        candidates = [
            (repository._record_to_run(record), record.updated_at, record.run_id)
            for record in records
        ]
    if not candidates and cursor is not None:
        cursor.clear()
    count = 0
    store = XiaoxBindingStore(repository)
    for candidate, updated_at, candidate_id in candidates:
        if stopped():
            break
        # A scheduling hint only: restart may safely scan from the beginning.
        # Old waiting-input/approval rows must not starve later ready parents.
        if cursor is not None:
            cursor.update(updated_at=updated_at, run_id=candidate_id)
        if candidate is None or not projection_allowed(candidate):
            continue
        try:
            current = refresh_xiaox_receipts(candidate, repository=repository)
            binding = store.get(current.run_id)
            metadata = binding.metadata
            if not projection_allowed(current) or metadata.get("waiting_input"):
                continue
            rows = store.receipt_snapshot(current.run_id)
            binding = store.get(current.run_id)
            if not _continuation_ready(binding.run, rows) or resume_error(store, binding, rows):
                continue
            key = "receipt_" + canonical_digest(
                {"goal": binding.run.metadata.get("runtime_goal_digest"), "receipts": rows}
            )
            if key in (binding.run.metadata.get("runtime_requests") or {}):
                continue

            def enqueue(parent: AgentRun, current_metadata: dict[str, Any]) -> None:
                if len(parent.metadata.get("runtime_requests") or {}) >= 256:
                    raise XiaoxBindingError("request_limit", "原任务续跑次数已达到上限")
                if current_metadata.get("waiting_input"):
                    raise XiaoxBindingError("binding_conflict", "原任务仍等待用户补充")
                parent.metadata.setdefault("runtime_requests", {})[key] = {
                    "digest": canonical_digest(rows),
                    "state": "admitted",
                    "created_at": utc_now_iso(),
                    "source": "verified_child_receipts",
                }
                stage_queued_request(
                    parent,
                    key,
                    {
                        "task": parent.message,
                        "input_data": copy.deepcopy(parent.metadata.get("_xiaox_input_data")),
                        "history": copy.deepcopy(parent.metadata.get("_xiaox_history")),
                        "answer_to_waiting_input": False,
                    },
                )

            enqueue_resume(store, binding.run, enqueue)
            count += 1
        except XiaoxBindingError:
            continue  # A concurrent control, changed owner or unknown effect wins.
        except RECOVERABLE_ERRORS:
            logger.warning("原 Xiaox 任务续跑尚待核对", exc_info=True)
    return count
