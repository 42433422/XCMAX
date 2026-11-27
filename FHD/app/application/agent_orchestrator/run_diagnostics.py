"""Observe the existing SQL ledger and open deduplicated support candidates.

This reader never takes a lease, settles a receipt or retries a business action.
The work-order SSOT owns incident persistence; the cursor is only a bounded scan
hint. Losing it may repeat observations, never create another execution owner.
"""

from __future__ import annotations

import hashlib
import logging
import math
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from app.application.agent_orchestrator.run_diagnostic_evidence import (
    build_diagnostic_evidence as _evidence,
)
from app.application.agent_orchestrator.run_diagnostic_evidence import (
    diagnostic_digest as _digest,
)
from app.application.agent_orchestrator.run_models import AgentRun
from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
from app.application.agent_orchestrator.task_models import mod_id_of_run, tenant_id_of_run
from app.domain.task_lifecycle.agent_runtime_results import failure_diagnostics
from app.utils.operational_errors import BOUNDARY_ERRORS

logger = logging.getLogger(__name__)
_WAITING = {"waiting_user", "waiting_input", "waiting_approval", "waiting_auth", "paused"}
_ACTIVE = {"queued", "claimed", "planning", "running", "retrying", "submitted", "accepted"}
# Explicit human/control waits always return None and need no payload hydration.
_CANDIDATES = _ACTIVE | {"blocked", "unknown", "failed", "timed_out"}
_LAYERS = {
    "model": "model",
    "planning": "planning",
    "planner": "planning",
    "tool": "tool",
    "business": "tool",
    "persistence": "persistence",
    "database": "persistence",
    "storage": "persistence",
    "goal_verification": "verification",
    "verification": "verification",
    "quality_control": "verification",
    "collaboration": "collaboration",
    "handoff": "collaboration",
    "delivery": "delivery",
    "runtime": "runtime",
}


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _timestamp(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        if isinstance(value, str):
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            value = (
                parsed.replace(tzinfo=UTC).timestamp()
                if parsed.tzinfo is None
                else parsed.timestamp()
            )
        result = float(value)
        return result if math.isfinite(result) and result > 0 else None
    except (TypeError, ValueError, OverflowError):
        return None


def _waiting_layer(run: AgentRun) -> str:
    runtime = _dict(run.metadata.get("xiaox_runtime"))
    if runtime.get("waiting_input"):
        return "runtime"
    children = list(_dict(run.metadata.get("child_results")).values())
    children += list(_dict(runtime.get("calls")).values())
    if runtime.get("coordinator_active") is not True and any(
        isinstance(child, dict)
        and str(child.get("status") or child.get("state")) in _ACTIVE | _WAITING
        for child in children
    ):
        return "collaboration"
    if any(
        call.status == "completed"
        and _dict(call.metadata.get("verification")).get("status") == "pending"
        for call in run.tool_calls
    ):
        return "verification"
    return ""


def _scope(run: AgentRun) -> tuple[str, str, str]:
    return tenant_id_of_run(run), run.user_id, mod_id_of_run(run)


def _child_refs(run: AgentRun) -> dict[str, tuple[Any, ...]]:
    runtime = _dict(run.metadata.get("xiaox_runtime"))
    return {
        str(row["child_run_id"]): (*_scope(run), run.run_id, row.get("child_task_id"))
        for row in _dict(runtime.get("calls")).values()
        if isinstance(row, dict)
        and row.get("child_run_id")
        and row.get("state") in _ACTIVE | _WAITING
    }


def diagnose_run(
    run: AgentRun,
    execution: Any = None,
    *,
    now: float,
    stale_after_seconds: float = 300.0,
    missing_child_refs: tuple[str, ...] = (),
) -> dict[str, Any] | None:
    """Classify structured evidence; a timeout finding is suspicion, not a verdict."""
    if run.status in {"completed", "succeeded", "cancelled", "rejected"}:
        return None
    queue_state = str(getattr(execution, "state", ""))
    if run.status in _WAITING or queue_state in _WAITING:
        return None
    result = _dict(run.final_output.get("xiaox_result")) or run.final_output
    recovery = _dict(run.metadata.get("verification_recovery"))
    diagnostics = failure_diagnostics(run, result)
    stage, code = diagnostics["failure_stage"], diagnostics["failure_kind"]
    waiting = _waiting_layer(run)
    if waiting:
        updated = _timestamp(run.updated_at)
        if (
            waiting == "collaboration"
            and missing_child_refs
            and updated is not None
            and now - updated > max(30.0, stale_after_seconds)
        ):
            return {
                "layer": "collaboration",
                "kind": "child_receipt_missing",
                "code": "child_receipt_missing",
                "missing_child_refs": missing_child_refs,
            }
        lease = _timestamp(recovery.get("lease_until")) if waiting == "verification" else None
        if lease is not None and lease + 5 < now:
            return {
                "layer": waiting,
                "kind": "deadline_exceeded",
                "code": "verification_lease_expired",
            }
        # Approval, child receipts and active readback are not dead workers.
        # Their owners/children are independently observed in this same ledger.
        if not (
            run.status in {"failed", "blocked", "unknown"}
            and stage
            and code not in {"goal_evidence_pending", "goal_verification_required"}
        ):
            return None
    if code in {"model_usage_unknown", "business_outcome_unknown"}:
        return {
            "layer": "model" if code == "model_usage_unknown" else "tool",
            "kind": code,
            "code": code,
        }
    if run.status == "unknown" or queue_state == "unknown":
        return {"layer": "unknown", "kind": "outcome_unknown", "code": "outcome_unknown"}
    if stage or run.status in {"failed", "timed_out"}:
        layer = _LAYERS.get(
            stage or str(run.metadata.get("runtime_failure_stage") or ""), "unknown"
        )
        return {
            "layer": layer,
            "kind": f"{layer}_failed" if layer != "unknown" else "unclassified_failure",
            "code": code or "unclassified_failure",
        }
    runtime = _dict(run.metadata.get("xiaox_runtime"))
    deadline = (
        _timestamp(runtime.get("deadline_at"))
        if runtime.get("coordinator_active") is True
        else None
    )
    if deadline is not None and deadline + 5 < now:
        return {"layer": "runtime", "kind": "deadline_exceeded", "code": "active_deadline_exceeded"}
    lease = _timestamp(getattr(execution, "lease_expires_at", None))
    if queue_state in {"running", "claimed"} and lease is not None and lease + 5 < now:
        return {"layer": "runtime", "kind": "lease_expired", "code": "worker_lease_expired"}
    updated = _timestamp(run.updated_at)
    available = _timestamp(getattr(execution, "available_at", None))
    threshold = max(30.0, float(stale_after_seconds))
    if queue_state == "queued" or run.status == "queued":
        if available is not None and now - available > threshold:
            return {"layer": "runtime", "kind": "queue_overdue", "code": "queue_overdue"}
        return None
    if run.status in _ACTIVE and updated is not None and now - updated > threshold:
        if deadline is None or deadline + 5 < now:
            return {"layer": "runtime", "kind": "progress_stalled", "code": "progress_stalled"}
    return None


def _eligible(record, cutoff):
    from sqlalchemy import and_, or_

    return or_(
        record.status.in_(_CANDIDATES - {"failed", "timed_out"}),
        and_(record.status.in_(("failed", "timed_out")), record.updated_at >= cutoff),
    )


def scan_agent_diagnostics(
    *,
    repository,
    cursor: dict[str, Any],
    stopped: Callable[[], bool] = lambda: False,
    limit: int = 50,
    now: float | None = None,
    stale_after_seconds: float = 300.0,
) -> int:
    """A bounded, fair sweep; export gauges only at the end of a complete sweep.

    A failed candidate write is retried next sweep without starving later runs.
    The work-order key is independent of observed_at and process-local cursors.
    No raw prompt, params, result, exception text or account identity is exported.
    """
    from sqlalchemy import func

    from app.build_identity import verified_source_sha
    from app.db.models.agent import AgentRunRecord as Record
    from app.db.models.agent import AgentTaskExecutionRecord as Execution
    from app.domain.shared_services.ssot import WO_STATES, derive_wo_id, upsert_candidate
    from app.infrastructure.observability.metrics import (
        observe_diagnostic_fault,
        observe_diagnostic_scan,
        set_diagnostic_findings,
    )

    if not isinstance(repository, SQLAlchemyAgentRunRepository) or stopped():
        return 0
    current = time.time() if now is None else float(now)
    cutoff = (datetime.fromtimestamp(current, UTC) - timedelta(days=1)).isoformat()
    attempted = 0
    failed = False
    batch_limit = max(1, min(int(limit), 200))
    try:
        try:
            observer_sha = verified_source_sha()
        except ValueError:
            observer_sha = None
        # A single read transaction freezes each run and its paired queue row.
        # The upper bound keeps new arrivals from making a sweep unfinishable.
        with repository.transaction(read_only=True) as db:
            if "upper" not in cursor:
                upper = db.query(func.max(Record.run_id)).filter(_eligible(Record, cutoff)).scalar()
                cursor.update(upper=upper or "", after="", counts={})
            records = (
                db.query(Record, Execution)
                .outerjoin(Execution, Execution.run_id == Record.run_id)
                .filter(
                    _eligible(Record, cutoff),
                    Record.run_id > cursor["after"],
                    Record.run_id <= cursor["upper"],
                )
                .order_by(Record.run_id)
                .limit(batch_limit)
                .all()
            )
            # Read-only sessions roll back on exit; detach queue snapshots first.
            from app.application.agent_orchestrator.task_execution_sql_repository import (
                SQLAlchemyTaskExecutionRepository,
            )

            rows = []
            for record, queue in records:
                try:
                    run = repository._record_to_run(record)
                    execution = (
                        SQLAlchemyTaskExecutionRepository._to_model(queue) if queue else None
                    )
                except BOUNDARY_ERRORS:
                    # A malformed historic row is evidence unavailable, not a
                    # reason to starve every later run in the same scan batch.
                    run, execution = None, None
                rows.append(
                    (
                        run,
                        execution,
                        record.run_id,
                        hashlib.sha256(record.payload_json.encode()).hexdigest(),
                    )
                )
            child_scopes: dict[str, tuple[Any, ...] | None] = {}
            child_ids = sorted(
                {identity for run, *_ in rows if run is not None for identity in _child_refs(run)}
            )
            for offset in range(0, len(child_ids), 200):
                for child in db.query(Record).filter(
                    Record.run_id.in_(child_ids[offset : offset + 200])
                ):
                    child_scopes[child.run_id] = None
                    try:
                        child_run = repository._record_to_run(child)
                        if child_run is None:
                            cursor["unreadable"] = True
                        else:
                            child_scopes[child.run_id] = (
                                *_scope(child_run),
                                _dict(child_run.metadata.get("runtime_context")).get(
                                    "parent_run_id"
                                ),
                                _dict(child_run.metadata.get("task_context")).get("task_id"),
                            )
                    except BOUNDARY_ERRORS:
                        cursor["unreadable"] = True
        failed = bool(cursor.get("unreadable"))
        publications = []
        consumed = 0
        for run, execution, identity, payload_sha in rows:
            if stopped():
                break
            consumed += 1
            cursor["after"] = identity
            if run is None:
                failed = True
                cursor["unreadable"] = True
                continue
            try:
                finding = diagnose_run(
                    run,
                    execution,
                    now=current,
                    stale_after_seconds=stale_after_seconds,
                    missing_child_refs=tuple(
                        sorted(
                            identity
                            for identity, expected in _child_refs(run).items()
                            if identity not in child_scopes
                            or child_scopes[identity] is not None
                            and child_scopes[identity] != expected
                        )
                    ),
                )
            except BOUNDARY_ERRORS:
                failed = cursor["unreadable"] = True
                continue
            if finding is None:
                continue
            label = (finding["layer"], finding["kind"])
            cursor["counts"][label] = cursor["counts"].get(label, 0) + 1
            publications.append((run, execution, finding, payload_sha))
            if len(publications) >= 10:
                break  # Bound work-order I/O as well as SQL reads.
        complete = consumed == len(rows) and (
            len(rows) < batch_limit or cursor["after"] == cursor["upper"]
        )
        if complete and not stopped():
            if not cursor.get("unreadable"):
                set_diagnostic_findings(cursor["counts"], observed_at=current)
            cursor.clear()
        # Freeze the observation before calling the possibly slow work-order
        # service. Publication failures do not make a completed SQL read stale.
        for run, execution, finding, payload_sha in publications:
            if stopped():
                break
            attempted += 1
            try:
                evidence = _evidence(
                    run,
                    execution,
                    finding,
                    now=current,
                    observer_sha=observer_sha,
                    payload_sha=payload_sha,
                    stale_after_seconds=stale_after_seconds,
                    missing_child_refs=finding.get("missing_child_refs", ()),
                )
                task = _dict(run.metadata.get("task_context"))
                runtime = _dict(run.metadata.get("xiaox_runtime"))
                key = "agent-diagnostic:v1:" + _digest(
                    (
                        tenant_id_of_run(run),
                        run.user_id,
                        mod_id_of_run(run),
                        run.run_id,
                        task.get("attempt", 1),
                        runtime.get("generation", 0),
                        finding["layer"],
                        finding["kind"],
                    )
                )
                receipt = upsert_candidate(
                    source="agent_diagnostics",
                    dedup_key=key,
                    reason="health_check_failed",
                    context={"diagnostic": evidence},
                    evidence_ref={
                        "kind": "agent_diagnostic_classification_snapshot",
                        "scope": "diagnostic_classification",
                        "sha256": _digest(evidence),
                        "snapshot_sha256": evidence["reproduction"]["sha256"],
                        "source_payload_retained": False,
                        "run_id": evidence["run_id"],
                        "source_payload_sha256": payload_sha,
                    },
                )
                if receipt.get("status") not in WO_STATES or receipt.get("wo_id") != derive_wo_id(
                    key
                ):
                    failed = True
                elif receipt.get("created"):
                    observe_diagnostic_fault(layer=finding["layer"], kind=finding["kind"])
            except BOUNDARY_ERRORS:
                # Plugin/SSOT boundary: a broken diagnostic must not interfere
                # with lease renewal, receipt recovery or business retries.
                failed = True
                logger.warning("agent diagnostic candidate unavailable")
        observe_diagnostic_scan(outcome="error" if failed else "ok")
    except BOUNDARY_ERRORS:
        # This is the autonomous observation boundary, not a new task executor.
        # Do not log raw DB/plugin exceptions which may contain user data.
        logger.warning("agent diagnostic scan unavailable")
        observe_diagnostic_scan(outcome="error")
    return attempted
