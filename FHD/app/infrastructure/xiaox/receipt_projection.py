"""Reconcile a stopped runtime parent from existing business receipts only."""

from __future__ import annotations

import copy
import json
import logging
import re
import time
from collections.abc import Callable
from typing import Any

from app.application.agent_orchestrator.run_lifecycle import (
    requires_retry_reconciliation,
)
from app.application.agent_orchestrator.run_models import AgentRun
from app.application.agent_orchestrator.run_repository import (
    AgentRunRepository,
    get_agent_run_repository,
)
from app.application.agent_orchestrator.run_sql_repository import (
    SQLAlchemyAgentRunRepository,
)
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
    receipt_artifact_failure,
    receipt_settled_failure,
    receipt_state,
    receipt_verified,
)
from app.infrastructure.xiaox.binding import XiaoxBindingError, XiaoxBindingStore
from app.infrastructure.xiaox.receipts import project_child_calls, resume_error

logger = logging.getLogger(__name__)


def reconcile_model_receipts(store: XiaoxBindingStore, run: AgentRun) -> AgentRun:
    """Recover accounting only; a late tool proposal never executes from this read."""
    import httpx

    from app.application.agent_runtime.configuration import _account_connection
    from app.infrastructure.billing.model_reservation import (
        ModelReservationError,
        PlatformModelReceiptScope,
    )
    from app.infrastructure.xiaox.model_gateway import (
        _finish,
        _validate_model_output,
        response_usage,
    )
    from app.utils.operational_errors import RECOVERABLE_ERRORS

    metadata = run.metadata.get("xiaox_runtime") or {}
    if metadata.get("coordinator_active") or not model_unsettled(metadata):
        return run
    for key, call in (metadata.get("model_requests") or {}).items():
        if (
            call.get("state") not in {"unknown", "reserved"}
            or call.get("gateway_kind") != "market"
            or call.get("reconciliation_after", 0) > time.time()
            or re.fullmatch(r"[A-Za-z0-9_.:-]{8,128}", key) is None
        ):
            continue
        scope = call.get("receipt_scope")
        config = metadata.get("runtime_config") or {}
        if (
            scope is None
            and call.get("route_identity") == config.get("route_identity")
            and call.get("model") == config.get("model")
        ):
            scope = {
                name: config.get(name) for name in PlatformModelReceiptScope.__dataclass_fields__
            }
        if not isinstance(scope, dict) or any(
            not isinstance(scope.get(name), str) or not scope[name]
            for name in PlatformModelReceiptScope.__dataclass_fields__
        ):
            continue  # Legacy requests without exact billing identity stay unknown.
        expected = PlatformModelReceiptScope(
            **{name: scope[name] for name in PlatformModelReceiptScope.__dataclass_fields__}
        )
        try:
            connection = _account_connection(run.user_id)
            if not connection.auth_token:
                continue
            store.update(
                run.run_id,
                lambda _run, current: current["model_requests"][key].update(
                    reconciliation_after=time.time() + 30
                ),
            )
            with httpx.Client(
                timeout=min(connection.timeout, 3.0),
                follow_redirects=False,
                trust_env=False,
            ) as client:
                with client.stream(
                    "GET",
                    connection.platform_url.rstrip("/") + "/api/llm/chat/requests/" + key,
                    headers=connection.headers(),
                ) as response:
                    response.raise_for_status()
                    raw = bytearray()
                    for chunk in response.iter_bytes():
                        raw.extend(chunk)
                        if len(raw) > 16_777_216:
                            raise ValueError("Original model receipt exceeds its byte limit")
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                continue
            terminal = payload.get("response")
            if (
                payload.get("state") != "completed"
                or payload.get("client_request_id") != key
                or not isinstance(terminal, dict)
            ):
                continue
            if terminal.get("model") != expected.response_model or terminal.get("status") not in {
                "completed",
                "failed",
                "incomplete",
            }:
                continue
            headers = httpx.Headers(payload.get("headers") or {})
            if headers.get_list("x-xcmax-upstream-attempts") != ["1"] or headers.get_list(
                "x-xcmax-upstream-fallbacks"
            ) != ["0"]:
                continue
            _validate_model_output(terminal)
            usage = response_usage(terminal)
            if usage is None:
                continue
            _finish(
                store,
                run.run_id,
                key,
                usage=usage,
                usage_key=call.get("usage_key") or f"xiaox:{run.run_id}:{key}",
                state="completed" if terminal["status"] == "completed" else "failed",
                market_route=expected,
                platform_receipt=terminal.get("xcagi"),
                reconciled_response=terminal,
            )
        except (ModelReservationError, *RECOVERABLE_ERRORS):
            logger.warning("原模型请求回执尚未核对；保留未知状态，不重发", exc_info=False)
    return store.get(run.run_id).run


def projection_allowed(run: AgentRun) -> bool:
    from app.application.agent_runtime.verification_budget import JOB_KEY

    metadata = run.metadata.get("xiaox_runtime") or {}
    queued = run.metadata.get("_xiaox_queued_request") or {}
    verification = run.metadata.get(JOB_KEY) or {}
    return bool(
        run.metadata.get("runtime_type") == "xiaox"
        and run.status in {"waiting_user", "running", "blocked", "unknown"}
        # A receipt refresh cannot reopen a terminal verification budget or
        # change the final reason recorded by the coordinator.
        and not (run.status == "blocked" and verification.get("state") == "blocked")
        and run.metadata.get("runtime_goal_contract")
        and metadata.get("calls")
        and not metadata.get("coordinator_active")
        and metadata.get("revoked") is True
        and metadata.get("close_reason") not in {"cancelled", "paused"}
        and not model_unsettled(metadata)
        and queued.get("state") != "queued"
    )


def _continuation_ready(run: AgentRun, rows: list[dict[str, Any]]) -> bool:
    """Resume once on new settled child evidence; never replay the child itself."""
    if not rows or not all(receipt_verified(row) or receipt_settled_failure(row) for row in rows):
        return False
    previous = run.final_output.get("xiaox_result") or {}
    if previous.get("exit_status") == "continuation_pending":
        return True
    prior = {str(row.get("call_id")): row for row in previous.get("business_receipts") or []}
    return any(
        receipt_state(prior[str(row["call_id"])]) in WAITING_STATES | ACTIVE_STATES
        or (
            receipt_state(prior[str(row["call_id"])]) == "unknown" and receipt_artifact_failure(row)
        )
        for row in rows
        if str(row.get("call_id")) in prior
    )


def project_receipt_state(
    run: AgentRun,
    rows: list[dict[str, Any]],
    *,
    verified_child_recovery: bool = False,
) -> AgentRun | None:
    """Build a projection; the SQL queue boundary independently verifies its inputs."""
    if not projection_allowed(run):
        return None
    if (
        requires_retry_reconciliation(run)
        and not verified_child_recovery
        and not any(receipt_state(row) == "unknown" for row in rows)
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
    if (
        result.get("exit_status") in {"goal_verification_required", "partial"}
        or (
            (verified_child_recovery or previous.get("exit_status") == "continuation_pending")
            and result.get("exit_status") == "failed"
            and any(receipt_artifact_failure(row) for row in rows)
        )
    ) and _continuation_ready(run, rows):
        # A completed child is new evidence for the same runtime, never proof
        # that every original goal is complete. The dispatcher owns continuation.
        status = "running"
        result.update(
            execution_state="running",
            exit_status="continuation_pending",
            resume_required=True,
            reconciliation_required=False,
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
    if verified_child_recovery:
        projected.metadata.pop("non_retryable", None)
        projected.metadata.pop("recovery", None)
        projected.add_event(
            "runtime.reconciliation.verified",
            "原子任务已由独立回执核实，无需重放写入",
            {"child_run_ids": sorted({str(row["child_run_id"]) for row in rows})},
        )
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
    if current is None:
        return current or run
    execution = queue.get(run.run_id)
    if execution is not None and (
        execution.state
        not in {"waiting_approval", "waiting_input", "waiting_auth", "paused", "blocked", "unknown"}
        or execution.lease_owner
        or execution.lease_expires_at
    ):
        return current
    store = XiaoxBindingStore(repository)
    current = reconcile_model_receipts(store, current)
    if not projection_allowed(current):
        return current
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
    from app.infrastructure.xiaox.queued_runtime import (
        enqueue_resume,
        stage_queued_request,
    )
    from app.utils.operational_errors import RECOVERABLE_ERRORS

    if not isinstance(repository, SQLAlchemyAgentRunRepository):
        return 0
    from sqlalchemy import and_, or_

    with repository.transaction(read_only=True) as db:
        query = db.query(AgentRunRecord).filter(
            AgentRunRecord.intent == "xiaox.runtime",
            AgentRunRecord.status.in_(("waiting_user", "running", "unknown", "blocked")),
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
        if candidate is None:
            continue
        if model_unsettled(candidate.metadata.get("xiaox_runtime") or {}):
            candidate = refresh_xiaox_receipts(candidate, repository=repository)
        if not projection_allowed(candidate):
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
