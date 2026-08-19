"""Read projection for append-only autonomy decision evidence."""

from __future__ import annotations

import os
from collections import Counter
from datetime import datetime, timedelta
from typing import Any, Callable

from sqlalchemy import text

from modstore_server.models import AutonomyDecisionAudit, get_session_factory


def _append_only_guard_status(session: Any) -> dict[str, Any]:
    dialect = session.get_bind().dialect.name
    expected = {
        "autonomy_decision_audit_no_update",
        "autonomy_decision_audit_no_delete",
    }
    if dialect == "sqlite":
        rows = session.execute(
            text(
                "SELECT name FROM sqlite_master "
                "WHERE type='trigger' AND tbl_name='autonomy_decision_audit'"
            )
        ).fetchmany(32)
        found = {str(row[0]) for row in rows}
        return {
            "dialect": dialect,
            "enforced": expected.issubset(found),
            "guards": sorted(expected & found),
        }
    if dialect == "postgresql":
        rows = session.execute(
            text(
                "SELECT tgname FROM pg_trigger "
                "WHERE tgrelid = 'autonomy_decision_audit'::regclass "
                "AND NOT tgisinternal"
            )
        ).fetchmany(32)
        found = {str(row[0]) for row in rows}
        expected_postgres = {"autonomy_decision_audit_no_mutation"}
        return {
            "dialect": dialect,
            "enforced": expected_postgres.issubset(found),
            "guards": sorted(expected_postgres & found),
        }
    return {"dialect": dialect, "enforced": False, "guards": []}


def build_autonomy_decision_evidence(
    *,
    window_days: int = 30,
    limit: int = 100,
    posthoc_maturity_minutes: int | None = None,
    session_factory: Callable[..., Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build alignment, veto, and post-hoc coverage evidence from the ledger."""
    from modstore_server import autonomy_decision_audit as audit

    bounded_days = max(1, min(int(window_days), 3650))
    bounded_limit = max(1, min(int(limit), 1000))
    if posthoc_maturity_minutes is None:
        try:
            configured_maturity = int(
                str(os.environ.get("MODSTORE_POSTHOC_MATURITY_MINUTES") or "90")
            )
        except (TypeError, ValueError):
            configured_maturity = 90
    else:
        configured_maturity = int(posthoc_maturity_minutes)
    bounded_maturity_minutes = max(0, min(configured_maturity, 1440))
    current = audit._utc(now)
    cutoff = current - timedelta(days=bounded_days)
    maturity_cutoff = current - timedelta(minutes=bounded_maturity_minutes)
    session_provider = session_factory or get_session_factory()
    with session_provider() as session:
        rows = (
            session.query(AutonomyDecisionAudit)
            .filter(AutonomyDecisionAudit.occurred_at >= cutoff)
            .order_by(AutonomyDecisionAudit.occurred_at.desc(), AutonomyDecisionAudit.id.desc())
            .all()
        )
        append_only = _append_only_guard_status(session)

    decisions = [row for row in rows if row.record_type == "decision"]
    posthoc = [row for row in rows if row.record_type == "posthoc_anomaly"]
    action_ids = {row.action_id for row in decisions}
    allow_ids = {row.action_id for row in decisions if row.decision == "allow"}
    block_ids = {row.action_id for row in decisions if row.decision == "block"}
    veto_ids = {row.action_id for row in decisions if row.decision == "veto"}
    first_allow_at: dict[str, float] = {}
    first_allow_contract: dict[str, tuple[float, str, str]] = {}
    for row in decisions:
        if row.decision != "allow":
            continue
        timestamp = audit._utc(row.occurred_at).timestamp() if row.occurred_at else 0.0
        first_allow_at[row.action_id] = min(first_allow_at.get(row.action_id, timestamp), timestamp)
        previous = first_allow_contract.get(row.action_id)
        if previous is None or timestamp < previous[0]:
            first_allow_contract[row.action_id] = (
                timestamp,
                str(row.action or "unknown"),
                str(row.source or "unknown"),
            )

    prohibited_hit_ids: set[str] = set()
    prohibited_hit_events = 0
    for row in decisions:
        try:
            import json

            hits = json.loads(row.prohibited_rule_hits_json or "[]")
        except (TypeError, ValueError):
            hits = []
        if isinstance(hits, list) and hits:
            prohibited_hit_ids.add(row.action_id)
            prohibited_hit_events += 1

    conclusive_ids: set[str] = set()
    miss_ids: set[str] = set()
    for row in posthoc:
        if row.action_id not in allow_ids or not row.evidence_ref:
            continue
        timestamp = audit._utc(row.occurred_at).timestamp() if row.occurred_at else 0.0
        if timestamp < first_allow_at.get(row.action_id, 0.0):
            continue
        if row.posthoc_verdict in {"prohibited_miss", "no_prohibited_miss"}:
            conclusive_ids.add(row.action_id)
        if row.posthoc_verdict == "prohibited_miss":
            miss_ids.add(row.action_id)

    eligible_allow_ids = {
        action_id
        for action_id in allow_ids
        if first_allow_at.get(action_id, float("inf")) <= maturity_cutoff.timestamp()
    }
    eligible_conclusive_ids = eligible_allow_ids & conclusive_ids
    pending_ids = (allow_ids - eligible_allow_ids) - conclusive_ids
    uncovered_ids = eligible_allow_ids - conclusive_ids
    coverage_denominator_ids = eligible_allow_ids | (allow_ids & conclusive_ids)
    coverage_complete = bool(coverage_denominator_ids) and not uncovered_ids

    def contract_counts(action_id_set: set[str]) -> list[dict[str, Any]]:
        counts = Counter(
            (
                first_allow_contract.get(action_id, (0.0, "unknown", "unknown"))[1],
                first_allow_contract.get(action_id, (0.0, "unknown", "unknown"))[2],
            )
            for action_id in action_id_set
        )
        return [
            {"action": action, "source": source, "count": count}
            for (action, source), count in sorted(
                counts.items(), key=lambda item: (-item[1], item[0][0], item[0][1])
            )
        ]

    uncovered_contracts = contract_counts(uncovered_ids)
    pending_contracts = contract_counts(pending_ids)
    if miss_ids:
        has_prohibited_miss: bool | None = True
        miss_status = "detected"
        unknown_reason = None
    elif coverage_complete:
        has_prohibited_miss = False
        miss_status = "verified_clear"
        unknown_reason = None
    else:
        has_prohibited_miss = None
        miss_status = "unknown"
        unknown_reason = (
            "no_allow_decisions_to_observe"
            if not allow_ids
            else (
                "posthoc_evidence_within_maturity_window"
                if not coverage_denominator_ids and pending_ids
                else "incomplete_posthoc_anomaly_coverage"
            )
        )

    total = len(action_ids)
    veto_count = len(veto_ids)
    by_decision = Counter(row.decision for row in decisions if row.decision in audit.DECISIONS)
    items = [audit._serialize_row(row) for row in rows[:bounded_limit]]
    return {
        "schema": audit.SCHEMA_VERSION,
        "source_authoritative": bool(append_only["enforced"]),
        "append_only": True,
        "append_only_enforced": bool(append_only["enforced"]),
        "append_only_guard": append_only,
        "window_days": bounded_days,
        "since": cutoff.isoformat(),
        "as_of": current.isoformat(),
        "total": total,
        "allow_count": len(allow_ids),
        "block_count": len(block_ids),
        "veto_count": veto_count,
        "veto_rate": round((veto_count / total) * 100, 2) if total else 0.0,
        "by_decision_events": dict(sorted(by_decision.items())),
        "prohibited_hit_count": len(prohibited_hit_ids),
        "prohibited_hit_event_count": prohibited_hit_events,
        "posthoc_conclusive_count": len(conclusive_ids),
        "posthoc_eligible_allow_count": len(eligible_allow_ids),
        "posthoc_eligible_conclusive_count": len(eligible_conclusive_ids),
        "posthoc_pending_count": len(pending_ids),
        "posthoc_pending_contracts": pending_contracts,
        "posthoc_maturity_minutes": bounded_maturity_minutes,
        "posthoc_uncovered_count": len(uncovered_ids),
        "posthoc_uncovered_contracts": uncovered_contracts,
        "posthoc_coverage_rate": (
            round(
                len(coverage_denominator_ids & conclusive_ids)
                / len(coverage_denominator_ids)
                * 100,
                2,
            )
            if coverage_denominator_ids
            else 0.0
        ),
        "prohibited_miss_count": len(miss_ids),
        "has_prohibited_miss": has_prohibited_miss,
        "prohibited_miss_evidence_status": miss_status,
        "prohibited_miss_unknown_reason": unknown_reason,
        "counting_rule": (
            "unique action_id in the window; veto_rate counts action_ids with a veto decision. "
            "Fresh allow actions without receipts are pending until the bounded posthoc maturity "
            "window expires. has_prohibited_miss is false only when every mature allowed action "
            "has conclusive post-execution anomaly evidence; overdue missing evidence yields null, "
            "never false"
        ),
        "items": items,
        "item_count": len(items),
    }
