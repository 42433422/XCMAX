"""Audit persisted state changes and count committed terminal transitions."""

from __future__ import annotations

import copy
import hashlib
import logging
from functools import lru_cache
from typing import TYPE_CHECKING

from sqlalchemy import event
from sqlalchemy.orm import Session

from app.infrastructure.observability.metrics import observe_run_terminal
from app.utils.operational_errors import BOUNDARY_ERRORS

if TYPE_CHECKING:
    from app.application.agent_orchestrator.run_models import AgentRun

_TERMINAL = {"completed", "failed", "cancelled", "rejected"}
_PENDING = "agent_run_terminal_metrics"
_STATE_EVENT = "run.state_changed"
_REASON_EVENTS = {
    "run.created",
    "run.started",
    "run.completed",
    "run.failed",
    "run.cancelled",
    "run.paused",
    "run.clarification_resumed",
    "run.retrying",
    "run.interrupted",
    "run.waiting_user",
    "runtime.xiaox.started",
    "runtime.xiaox.finished",
    "tool.failed",
    "tool.completed",
    "approval.requested",
    "approval.resolved",
    "workflow.graph_rejected",
    "planner.blocked",
}
_PUBLIC_ERRORS = {
    "agent_run_internal_error",
    "agent_run_failed",
    "agent_phase_failed",
    "agent_phase_cancelled",
    "interrupted_by_restart",
}
logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def observed_source_sha() -> str | None:
    from app.build_identity import verified_source_sha

    try:
        return verified_source_sha()
    except ValueError:
        return None


def record_state_transition(
    run: AgentRun,
    previous: AgentRun | None,
    *,
    requested_status: str,
    session=None,
    original_output=None,
) -> None:
    """Append to the existing ledger only after persistence fences are applied.

    A retry may reuse an object mutated by a rolled-back transaction. Only the
    locked persisted snapshot can supply prior audit records; discard candidate
    audit entries before deciding whether a new transition actually occurred.
    """
    prior = previous.events if previous is not None else []
    prior_ids = {event.event_id for event in prior}
    audited = {event.event_id: event for event in prior if event.event_type == _STATE_EVENT}
    run.events = [
        copy.deepcopy(audited[event.event_id]) if event.event_id in audited else event
        for event in run.events
        if event.event_type != _STATE_EVENT or event.event_id in audited
    ]
    retained = {event.event_id for event in run.events}
    run.events[:0] = [copy.deepcopy(event) for key, event in audited.items() if key not in retained]
    if previous is not None and previous.status == run.status:
        return
    cause = next(
        (
            event
            for event in reversed(run.events)
            if event.event_id not in prior_ids
            and event.event_type not in {_STATE_EVENT, "run.observed"}
        ),
        None,
    )
    reason = "initial_persistence" if previous is None else "reason_not_recorded"
    raw_code = str(cause.data.get("error_code") or "") if cause else ""
    event_type = cause.event_type if cause and cause.event_type in _REASON_EVENTS else "other"
    # Error messages, model text and tool payloads never enter the audit summary.
    code = raw_code if raw_code in _PUBLIC_ERRORS else ""
    if cause is not None:
        reason = code or (event_type if event_type != "other" else "event_reference")
    if requested_status != run.status:
        reason = "persistence_evidence_reconciled"
    from app.application.agent_orchestrator.business_harness import harness_event_context
    from app.application.agent_orchestrator.run_events import RunEvent
    from app.application.agent_orchestrator.task_context import ensure_run_trace

    # Do not emit an uncommitted transition to the log stream. The original
    # task ledger publishes this event only if the enclosing transaction commits.
    audit_event = RunEvent(
        run_id=run.run_id,
        event_type=_STATE_EVENT,
        message="任务状态转换；原因引用原事件",
        data={
            **ensure_run_trace(run),
            "harness": harness_event_context(run),
            "from_status": previous.status if previous is not None else None,
            "to_status": run.status,
            "requested_status": requested_status,
            "sequence": len(audited) + 1,
            "source_sha": observed_source_sha(),
            "reason_code": reason,
            "reason_recorded": reason != "reason_not_recorded",
            "reason_event_id": cause.event_id if cause else None,
            "reason_event_type": event_type if cause else None,
            "error_code": code,
            "reported_code_sha256": hashlib.sha256(raw_code.encode()).hexdigest()
            if raw_code
            else None,
        },
    )
    run.events.append(audit_event)
    if session is not None:
        _transaction_observations(session)["audits"].append(
            (run, audit_event.event_id, original_output, copy.deepcopy(run.final_output))
        )


def record_terminal_transition(run, previous, session=None):
    # Comparing the locked persisted status deduplicates repeat saves and CAS
    # retries, while allowing a genuinely restarted run to terminate again.
    if run.status not in _TERMINAL or (previous and previous.status == run.status):
        return
    if session is None:
        _observe_terminal(run.status)
    else:
        _transaction_observations(session)["statuses"].append(run.status)


def _transaction_observations(session):
    transaction = session.get_nested_transaction() or session.get_transaction()
    return session.info.setdefault(_PENDING, {}).setdefault(
        transaction, {"statuses": [], "audits": []}
    )


def _observe_terminal(status):
    try:
        observe_run_terminal(status=status)
    except BOUNDARY_ERRORS as exc:
        # The business commit has already succeeded. A broken metric exporter
        # must not report execution failure and invite a duplicate business retry.
        logger.warning("agent terminal metric unavailable (%s)", type(exc).__name__)


@event.listens_for(Session, "after_commit")
def _after_commit(session):
    transaction = session.get_nested_transaction() or session.get_transaction()
    pending = session.info.get(_PENDING, {})
    observations = pending.pop(transaction, {"statuses": [], "audits": []})
    if transaction is not None and transaction.nested:
        parent = pending.setdefault(transaction.parent, {"statuses": [], "audits": []})
        for key in observations:
            parent[key].extend(observations[key])
    else:
        for status in observations["statuses"]:
            _observe_terminal(status)


@event.listens_for(Session, "after_transaction_end")
def _after_transaction_end(session, transaction):
    pending = session.info.get(_PENDING, {})
    observations = pending.pop(transaction, {})
    for run, event_id, original_output, projected in reversed(observations.get("audits", [])):
        run.events[:] = [event for event in run.events if event.event_id != event_id]
        if original_output is not None and run.final_output == projected:
            run.final_output = original_output
    if not pending:
        session.info.pop(_PENDING, None)
