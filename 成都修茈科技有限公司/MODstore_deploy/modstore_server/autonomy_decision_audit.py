"""Append and summarize privacy-safe autonomy decision evidence.

Only typed, bounded identifiers are accepted. There is intentionally no
``payload`` or arbitrary ``metadata`` argument: secrets and raw business data
must stay in their owning systems, while this ledger records the decision
envelope needed to prove alignment.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, OperationalError

from modstore_server.models import AutonomyDecisionAudit, get_session_factory

SCHEMA_VERSION = "autonomy_decision_evidence.v1"
DECISIONS = frozenset({"allow", "block", "veto"})
RISK_LEVELS = frozenset({"low", "medium", "high", "blocked"})
ACTOR_CLASSES = frozenset({"ai_employee", "system", "human", "external", "unknown"})
POSTHOC_VERDICTS = frozenset({"prohibited_miss", "no_prohibited_miss", "inconclusive"})
_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9._:/+\-]+$")
_SENSITIVE_VALUE = re.compile(
    r"(?i)(?:bearer\s+|sk-[A-Za-z0-9_\-]{8,}|api[_-]?key|password|secret|token=)"
)
_SCHEMA_LOCK = threading.RLock()


def _ensure_audit_schema(session_factory: Callable[..., Any]) -> None:
    """Create only this evidence table when a lightweight worker starts first."""

    with _SCHEMA_LOCK, session_factory() as session:
        engine = session.get_bind()
        if engine.dialect.name != "sqlite":
            AutonomyDecisionAudit.__table__.create(engine, checkfirst=True)
            return
        with engine.connect() as connection:
            connection.exec_driver_sql("BEGIN EXCLUSIVE")
            try:
                AutonomyDecisionAudit.__table__.create(connection, checkfirst=True)
            except Exception:
                connection.rollback()
                raise
            else:
                connection.commit()


def _utc(value: datetime | None = None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc)


def _safe_identifier(
    value: Any,
    *,
    default: str = "",
    prefix: str = "id",
    max_length: int = 192,
) -> str:
    """Keep normal operational IDs readable and hash anything unsafe."""

    raw = str(value or "").strip()
    if not raw:
        return default
    if len(raw) <= max_length and _SAFE_TOKEN.fullmatch(raw) and not _SENSITIVE_VALUE.search(raw):
        return raw
    digest = hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()
    return f"{prefix}:sha256:{digest[:40]}"


def _rule_hits(values: Iterable[Any] | None) -> list[str]:
    result: list[str] = []
    for value in list(values or [])[:32]:
        item = _safe_identifier(value, prefix="rule", max_length=128)
        if item and item not in result:
            result.append(item)
    return result


def _event_id(value: Any = None) -> str:
    if value:
        return _safe_identifier(value, prefix="event", max_length=96)
    return "ada_" + uuid.uuid4().hex


def _serialize_row(row: AutonomyDecisionAudit) -> dict[str, Any]:
    try:
        hits = json.loads(row.prohibited_rule_hits_json or "[]")
    except (TypeError, ValueError, json.JSONDecodeError):
        hits = []
    return {
        "id": int(row.id),
        "event_id": row.event_id,
        "record_type": row.record_type,
        "action_id": row.action_id,
        "action": row.action,
        "decision": row.decision or None,
        "policy": row.policy or None,
        "risk_level": row.risk_level,
        "actor_class": row.actor_class,
        "run_id": row.run_id or None,
        "prohibited_rule_hits": hits if isinstance(hits, list) else [],
        "posthoc_verdict": row.posthoc_verdict or None,
        "evidence_ref": row.evidence_ref or None,
        "source": row.source or None,
        "occurred_at": row.occurred_at.isoformat() if row.occurred_at else None,
        "recorded_at": row.recorded_at.isoformat() if row.recorded_at else None,
    }


def _append_row(
    values: dict[str, Any],
    *,
    session_factory: Callable[..., Any] | None = None,
    session: Any | None = None,
) -> dict[str, Any]:
    """Append with bounded retries for SQLite's single-writer lock.

    A caller-supplied ``event_id`` is an idempotency key. Concurrent retries
    return the already committed row instead of creating duplicates.
    """

    if session is not None:
        existing = (
            session.query(AutonomyDecisionAudit)
            .filter(AutonomyDecisionAudit.event_id == values["event_id"])
            .first()
        )
        if existing is not None:
            return _serialize_row(existing)
        row = AutonomyDecisionAudit(**values)
        session.add(row)
        session.flush()
        return _serialize_row(row)

    sf = session_factory or get_session_factory()
    for attempt in range(5):
        with sf() as session:
            try:
                row = AutonomyDecisionAudit(**values)
                session.add(row)
                session.commit()
                session.refresh(row)
                return _serialize_row(row)
            except IntegrityError:
                session.rollback()
                existing = (
                    session.query(AutonomyDecisionAudit)
                    .filter(AutonomyDecisionAudit.event_id == values["event_id"])
                    .first()
                )
                if existing is not None:
                    return _serialize_row(existing)
                raise
            except OperationalError as exc:
                session.rollback()
                error_text = str(exc).lower()
                if "no such table" in error_text and attempt < 4:
                    _ensure_audit_schema(sf)
                    continue
                locked = "locked" in error_text or "busy" in error_text
                if not locked or attempt >= 4:
                    raise
        threading.Event().wait(0.02 * (2**attempt))
    raise RuntimeError("unreachable autonomy audit append retry state")


def append_autonomy_decision(
    *,
    action_id: Any,
    action: Any,
    decision: str,
    policy: Any,
    risk_level: str,
    actor_class: str,
    run_id: Any = "",
    prohibited_rule_hits: Iterable[Any] | None = None,
    source: Any = "",
    event_id: Any = None,
    occurred_at: datetime | None = None,
    session_factory: Callable[..., Any] | None = None,
    session: Any | None = None,
) -> dict[str, Any]:
    """Append one allow/block/veto decision without accepting raw payloads."""

    normalized_decision = str(decision or "").strip().lower()
    if normalized_decision not in DECISIONS:
        raise ValueError(f"unsupported autonomy decision: {normalized_decision or '<empty>'}")
    risk = str(risk_level or "blocked").strip().lower()
    if risk not in RISK_LEVELS:
        raise ValueError(f"unsupported autonomy risk level: {risk}")
    actor = str(actor_class or "unknown").strip().lower()
    if actor not in ACTOR_CLASSES:
        actor = "unknown"
    safe_action_id = _safe_identifier(action_id, prefix="action")
    if not safe_action_id:
        raise ValueError("action_id is required")
    values = {
        "event_id": _event_id(event_id),
        "record_type": "decision",
        "action_id": safe_action_id,
        "action": _safe_identifier(action, default="unknown", prefix="action-name", max_length=128),
        "decision": normalized_decision,
        "policy": _safe_identifier(policy, prefix="policy", max_length=128),
        "risk_level": risk,
        "actor_class": actor,
        "run_id": _safe_identifier(run_id, prefix="run"),
        "prohibited_rule_hits_json": json.dumps(
            _rule_hits(prohibited_rule_hits), separators=(",", ":")
        ),
        "posthoc_verdict": "",
        "evidence_ref": "",
        "source": _safe_identifier(source, prefix="source", max_length=128),
        "occurred_at": _utc(occurred_at),
    }
    return _append_row(values, session_factory=session_factory, session=session)


def record_posthoc_anomaly_evidence(
    *,
    action_id: Any,
    verdict: str,
    evidence_ref: Any,
    detector: Any,
    run_id: Any = "",
    event_id: Any = None,
    occurred_at: datetime | None = None,
    session_factory: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Append an independent, post-execution anomaly verdict.

    This is intentionally an internal Python contract, not a writable HTTP
    endpoint. A conclusive verdict requires a durable external evidence
    reference; absence of such rows can never be interpreted as zero misses.
    """

    normalized = str(verdict or "").strip().lower()
    if normalized not in POSTHOC_VERDICTS:
        raise ValueError(f"unsupported posthoc verdict: {normalized or '<empty>'}")
    safe_action_id = _safe_identifier(action_id, prefix="action")
    safe_ref = _safe_identifier(evidence_ref, prefix="evidence")
    if not safe_action_id or not safe_ref:
        raise ValueError("action_id and evidence_ref are required")
    values = {
        "event_id": _event_id(event_id),
        "record_type": "posthoc_anomaly",
        "action_id": safe_action_id,
        "action": "posthoc_anomaly_check",
        "decision": "",
        "policy": "posthoc_anomaly_evidence",
        "risk_level": "blocked" if normalized == "prohibited_miss" else "low",
        "actor_class": "system",
        "run_id": _safe_identifier(run_id, prefix="run"),
        "prohibited_rule_hits_json": "[]",
        "posthoc_verdict": normalized,
        "evidence_ref": safe_ref,
        "source": _safe_identifier(detector, prefix="detector", max_length=128),
        "occurred_at": _utc(occurred_at),
    }
    return _append_row(values, session_factory=session_factory)


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
        expected_pg = {"autonomy_decision_audit_no_mutation"}
        return {
            "dialect": dialect,
            "enforced": expected_pg.issubset(found),
            "guards": sorted(expected_pg & found),
        }
    return {"dialect": dialect, "enforced": False, "guards": []}


def _timestamp(value: datetime | None) -> float:
    if value is None:
        return 0.0
    return _utc(value).timestamp()


def build_autonomy_decision_evidence(
    *,
    window_days: int = 30,
    limit: int = 100,
    posthoc_maturity_minutes: int | None = None,
    session_factory: Callable[..., Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return 30-day alignment and veto evidence from the immutable ledger.

    Fresh allow decisions remain visible as pending while their independent
    execution, deployment, and anomaly receipts are still inside the bounded
    posthoc SLA. Once the maturity window expires, missing evidence becomes
    uncovered and therefore fail-closed.
    """

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
    current = _utc(now)
    cutoff = current - timedelta(days=bounded_days)
    maturity_cutoff = current - timedelta(minutes=bounded_maturity_minutes)
    sf = session_factory or get_session_factory()
    with sf() as session:
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
        ts = _timestamp(row.occurred_at)
        first_allow_at[row.action_id] = min(first_allow_at.get(row.action_id, ts), ts)
        previous = first_allow_contract.get(row.action_id)
        if previous is None or ts < previous[0]:
            first_allow_contract[row.action_id] = (
                ts,
                str(row.action or "unknown"),
                str(row.source or "unknown"),
            )

    prohibited_hit_ids: set[str] = set()
    prohibited_hit_events = 0
    for row in decisions:
        try:
            hits = json.loads(row.prohibited_rule_hits_json or "[]")
        except (TypeError, ValueError, json.JSONDecodeError):
            hits = []
        if isinstance(hits, list) and hits:
            prohibited_hit_ids.add(row.action_id)
            prohibited_hit_events += 1

    conclusive_ids: set[str] = set()
    miss_ids: set[str] = set()
    for row in posthoc:
        if row.action_id not in allow_ids or not row.evidence_ref:
            continue
        if _timestamp(row.occurred_at) < first_allow_at.get(row.action_id, 0.0):
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
    uncovered_contract_counts = Counter(
        (
            first_allow_contract.get(action_id, (0.0, "unknown", "unknown"))[1],
            first_allow_contract.get(action_id, (0.0, "unknown", "unknown"))[2],
        )
        for action_id in uncovered_ids
    )
    uncovered_contracts = [
        {
            "action": action,
            "source": source,
            "count": count,
        }
        for (action, source), count in sorted(
            uncovered_contract_counts.items(),
            key=lambda item: (-item[1], item[0][0], item[0][1]),
        )
    ]
    pending_contract_counts = Counter(
        (
            first_allow_contract.get(action_id, (0.0, "unknown", "unknown"))[1],
            first_allow_contract.get(action_id, (0.0, "unknown", "unknown"))[2],
        )
        for action_id in pending_ids
    )
    pending_contracts = [
        {
            "action": action,
            "source": source,
            "count": count,
        }
        for (action, source), count in sorted(
            pending_contract_counts.items(),
            key=lambda item: (-item[1], item[0][0], item[0][1]),
        )
    ]
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
    by_decision = Counter(row.decision for row in decisions if row.decision in DECISIONS)
    items = [_serialize_row(row) for row in rows[:bounded_limit]]
    return {
        "schema": SCHEMA_VERSION,
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
                (len(coverage_denominator_ids & conclusive_ids) / len(coverage_denominator_ids))
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


_DOMAIN_ALLOW = frozenset({"allow", "auto_approve", "approved", "executed"})
_DOMAIN_BLOCK = frozenset({"block", "blocked", "prohibited", "denied"})
_DOMAIN_VETO = frozenset(
    {
        "require_human",
        "pending_approval",
        "approval_requested",
        "rejected",
        "cooldown",
    }
)


def _run_id_from_context(context: dict[str, Any] | None) -> str:
    data = context if isinstance(context, dict) else {}
    for key in ("run_id", "loop_run_id", "execution_id"):
        if data.get(key):
            return _safe_identifier(data[key], prefix="run")
    return ""


def _actor_from_source(
    source: str,
    context: dict[str, Any] | None,
    *,
    approver: Any = "",
) -> str:
    if approver:
        return "human"
    data = context if isinstance(context, dict) else {}
    explicit = str(data.get("actor_class") or "").strip().lower()
    if explicit in ACTOR_CLASSES:
        return explicit
    low = source.lower()
    if "employee" in low or "agent" in low:
        return "ai_employee"
    return "system"


def append_domain_risk_decision(
    decision: Any,
    *,
    context: dict[str, Any] | None,
    source: str,
    session_factory: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Adapt the FHD autonomy-guard result to the MODstore ledger."""

    raw = decision.to_dict() if hasattr(decision, "to_dict") else dict(decision or {})
    domain_decision = str(raw.get("decision") or "blocked").strip().lower()
    if domain_decision in _DOMAIN_BLOCK or raw.get("prohibited") is True:
        normalized = "block"
    elif domain_decision in _DOMAIN_VETO or raw.get("requires_confirmation") is True:
        normalized = "veto"
    elif domain_decision in _DOMAIN_ALLOW or raw.get("allowed") is True:
        normalized = "allow"
    else:
        normalized = "block"
    action = str(raw.get("action") or "unknown")
    prohibited = bool(raw.get("prohibited")) or domain_decision == "prohibited"
    return append_autonomy_decision(
        action_id=raw.get("action_id"),
        action=action,
        decision=normalized,
        policy=raw.get("policy") or "autonomy_guard",
        risk_level=str(raw.get("risk_level") or "blocked"),
        actor_class=_actor_from_source(
            source,
            context,
            approver=raw.get("approver"),
        ),
        run_id=_run_id_from_context(context),
        prohibited_rule_hits=[action] if prohibited else [],
        source=source,
        session_factory=session_factory,
    )


def append_prohibited_exception(
    *,
    action: Any,
    action_id: Any,
    context: dict[str, Any] | None,
    source: str,
    session_factory: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Record a hard-boundary exception without persisting its free-form reason."""

    return append_autonomy_decision(
        action_id=action_id,
        action=action,
        decision="block",
        policy="prohibited_boundary",
        risk_level="blocked",
        actor_class=_actor_from_source(source, context),
        run_id=_run_id_from_context(context),
        prohibited_rule_hits=[action],
        source=source,
        session_factory=session_factory,
    )


__all__ = [
    "ACTOR_CLASSES",
    "DECISIONS",
    "POSTHOC_VERDICTS",
    "RISK_LEVELS",
    "SCHEMA_VERSION",
    "append_autonomy_decision",
    "append_domain_risk_decision",
    "append_prohibited_exception",
    "build_autonomy_decision_evidence",
    "record_posthoc_anomaly_evidence",
]
