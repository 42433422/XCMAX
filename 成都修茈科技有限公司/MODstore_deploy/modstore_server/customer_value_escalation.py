"""Escalate a verified absence of paid customer value without external action.

The reconciler is deliberately strict about what counts as paid customer value.
This module handles the complementary operational question: once the source and
append-only ledger are healthy, a sustained zero must become an auditable
strategic decision rather than silently remaining a dashboard number.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, Callable, Mapping

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from modstore_server.customer_value_evidence import build_customer_value_evidence
from modstore_server.db.strategic import StrategicActionItem, StrategicDecision
from modstore_server.strategic_layer import (
    DecisionProposer,
    DecisionType,
    StrategicDecisionLedger,
)

ESCALATION_SCHEMA = "xcagi.customer_value_escalation/v1"
ESCALATION_SCOPE = "global"
ESCALATION_SCOPE_REF = "customer-value-verified-paid"
ESCALATION_IDEMPOTENCY_KEY = "customer-value-escalation:verified-paid:v1"
ESCALATION_ACTION = "external announce customer-value recovery plan"
ESCALATION_ACTION_ID = "act-customer-value-zero-v1"
ESCALATION_OWNER = "daily-orchestrator"
ESCALATION_BLOCK_REASON = "customer_value_recovery_requires_human_strategy_approval"
UTC = UTC


def _int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _snapshot(evidence: Mapping[str, Any]) -> dict[str, Any]:
    """Keep only aggregate, non-identifying evidence in the strategic ledger."""

    return {
        "window_days": max(1, _int(evidence.get("window_days")) or 90),
        "source_owner": str(evidence.get("source_owner") or "")[:96],
        "source_available": evidence.get("source_available") is True,
        "source_authoritative": evidence.get("source_authoritative") is True,
        "append_only_store_available": evidence.get("append_only_store_available") is True,
        "value_ledger_ready": evidence.get("value_ledger_ready") is True,
        "verified_paid_count": _int(evidence.get("verified_paid_count")),
        "verified_paid_amount_cents": _int(evidence.get("verified_paid_amount_cents")),
        "customer_goal_count": _int(evidence.get("customer_goal_count")),
        "paid_delivery_count": _int(evidence.get("paid_delivery_count")),
        "paid_acceptance_count": _int(evidence.get("paid_acceptance_count")),
        "production_value_verified": evidence.get("production_value_verified") is True,
        "outcome_verified": evidence.get("outcome_verified") is True,
        "customer_acceptance_verified": evidence.get("customer_acceptance_verified") is True,
    }


def _digest(snapshot: Mapping[str, Any]) -> str:
    encoded = json.dumps(dict(snapshot), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _session_factory(factory: Callable[..., Any] | None) -> Callable[..., Any]:
    if factory is not None:
        return factory
    from modstore_server.db.base import get_session_factory

    return get_session_factory


def _decision_id_for_key(key: str) -> str:
    return f"dec-{hashlib.sha256(key.encode('utf-8')).hexdigest()[:16]}"


def _existing_decision_id(factory: Callable[..., Any]) -> str:
    decision_id = _decision_id_for_key(ESCALATION_IDEMPOTENCY_KEY)
    with factory()() as session:
        row = session.execute(
            select(StrategicDecision.decision_id).where(
                StrategicDecision.decision_id == decision_id,
            )
        ).scalar_one_or_none()
    return str(row or "")


def _ensure_blocked_action(
    *,
    decision_id: str,
    snapshot: Mapping[str, Any],
    factory: Callable[..., Any],
) -> bool:
    """Create one strategic action item; the unique key is the race-safe guard."""

    payload = {
        "schema": ESCALATION_SCHEMA,
        "evidence_digest": _digest(snapshot),
        "customer_value": dict(snapshot),
        "external_actions_authorized": False,
        "required_next_step": "human_strategy_approval",
    }
    now = datetime.now(UTC)
    with factory()() as session:
        existing = session.execute(
            select(StrategicActionItem).where(StrategicActionItem.action_id == ESCALATION_ACTION_ID)
        ).scalar_one_or_none()
        if existing is not None:
            if existing.decision_id != decision_id:
                raise RuntimeError("customer-value escalation action id collision")
            return False
        session.add(
            StrategicActionItem(
                action_id=ESCALATION_ACTION_ID,
                decision_id=decision_id,
                meeting_id=None,
                description=(
                    "权威客户价值账本显示已验证付费客户价值为零。"
                    "仅准备内部恢复方案；任何客户触达、价格、合同、支付或对外发布均须先获战略审批。"
                ),
                assigned_to=ESCALATION_OWNER,
                status="blocked",
                due_at=None,
                completed_at=None,
                result_json=json.dumps(payload, ensure_ascii=False, sort_keys=True),
                block_reason=ESCALATION_BLOCK_REASON,
                created_at=now,
                updated_at=now,
            )
        )
        try:
            session.commit()
            return True
        except IntegrityError:
            session.rollback()
            return False


def ensure_customer_value_gap_escalation(
    *,
    evidence: Mapping[str, Any] | None = None,
    window_days: int = 90,
    session_factory: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Create one approval-required strategic record for a real zero-value gap.

    Missing or untrusted evidence never creates an escalation.  This function
    only writes internal strategic records; it cannot send messages, change
    prices, create orders, charge payments, or mutate customer data.
    """

    raw = (
        dict(evidence)
        if isinstance(evidence, Mapping)
        else build_customer_value_evidence(window_days=window_days)
    )
    snapshot = _snapshot(raw)
    source_ready = bool(
        snapshot["source_available"]
        and snapshot["source_authoritative"]
        and snapshot["append_only_store_available"]
        and snapshot["value_ledger_ready"]
    )
    base = {
        "ok": True,
        "schema": ESCALATION_SCHEMA,
        "source_ready": source_ready,
        "evidence_digest": _digest(snapshot),
    }
    if not source_ready:
        return {
            **base,
            "status": "evidence_unready",
            "decision_id": None,
            "action_created": False,
        }
    if snapshot["verified_paid_count"] > 0 or snapshot["production_value_verified"]:
        return {
            **base,
            "status": "value_observed",
            "decision_id": None,
            "action_created": False,
        }
    if snapshot["outcome_verified"] or snapshot["customer_acceptance_verified"]:
        return {
            **base,
            "status": "inconsistent_evidence",
            "decision_id": None,
            "action_created": False,
        }

    factory = _session_factory(session_factory)
    existing_decision_id = _existing_decision_id(factory)
    record = StrategicDecisionLedger(session_factory=factory).propose(
        title="真实付费客户价值为零：请求恢复策略审批",
        action=ESCALATION_ACTION,
        proposer=DecisionProposer(
            actor=ESCALATION_OWNER,
            rationale=(
                "权威支付来源与追加式客户价值账本均可用，但当前窗口没有已验证付费客户价值。"
                "系统不得以测试、内部或未验证订单替代真实客户结果。"
            ),
            payload={
                "schema": ESCALATION_SCHEMA,
                "customer_value": snapshot,
                "evidence_digest": _digest(snapshot),
                "external_actions_authorized": False,
                "prohibited_actions": [
                    "customer_outreach_without_approval",
                    "pricing_change_without_approval",
                    "payment_or_order_mutation",
                    "fabricated_customer_value",
                ],
            },
        ),
        decision_type=DecisionType.STRATEGIC,
        scope=ESCALATION_SCOPE,
        scope_ref=ESCALATION_SCOPE_REF,
        execution_plan={
            "owner": ESCALATION_OWNER,
            "mode": "approval_required",
            "safe_preparation": [
                "read_only_adoption_funnel_review",
                "internal_recovery_plan_draft",
            ],
            "external_actions_authorized": False,
        },
        idempotency_key=ESCALATION_IDEMPOTENCY_KEY,
    )
    decision_id = record.decision_id
    decision_created = not bool(existing_decision_id)

    action_created = _ensure_blocked_action(
        decision_id=decision_id,
        snapshot=snapshot,
        factory=factory,
    )
    return {
        **base,
        "status": "escalated" if action_created or decision_created else "existing",
        "decision_id": decision_id,
        "decision_created": decision_created,
        "action_created": action_created,
    }


__all__ = ["ESCALATION_SCHEMA", "ensure_customer_value_gap_escalation"]
