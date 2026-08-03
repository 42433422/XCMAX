from __future__ import annotations

import json

import modstore_server.models as models
import pytest
from sqlalchemy import select

from modstore_server.customer_value_escalation import (
    ensure_customer_value_gap_escalation,
)
from modstore_server.db.strategic import StrategicActionItem, StrategicDecision
from modstore_server.strategic_layer.decision_ledger import (
    DecisionLifecycleError,
    DecisionProposer,
    DecisionType,
    StrategicDecisionLedger,
)


def _init_db(tmp_path, monkeypatch):
    models._engine = None
    models._SessionFactory = None
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("MODSTORE_DB_PATH", str(tmp_path / "customer-value-escalation.sqlite"))
    models.init_db()
    return models.get_session_factory()


def _zero_value_evidence(**overrides):
    evidence = {
        "window_days": 90,
        "source_owner": "java_postgresql_internal_api",
        "source_available": True,
        "source_authoritative": True,
        "append_only_store_available": True,
        "value_ledger_ready": True,
        "verified_paid_count": 0,
        "verified_paid_amount_cents": 0,
        "customer_goal_count": 0,
        "paid_delivery_count": 0,
        "paid_acceptance_count": 0,
        "production_value_verified": False,
        "outcome_verified": False,
        "customer_acceptance_verified": False,
    }
    evidence.update(overrides)
    return evidence


def test_zero_authoritative_customer_value_creates_one_human_gated_action(tmp_path, monkeypatch):
    sf = _init_db(tmp_path, monkeypatch)

    first = ensure_customer_value_gap_escalation(
        evidence=_zero_value_evidence(),
        session_factory=lambda: sf,
    )
    second = ensure_customer_value_gap_escalation(
        evidence=_zero_value_evidence(),
        session_factory=lambda: sf,
    )

    assert first["status"] == "escalated"
    assert first["decision_id"]
    assert first["action_created"] is True
    assert second["status"] == "existing"
    assert second["decision_id"] == first["decision_id"]
    assert second["action_created"] is False

    with sf() as session:
        decision = session.execute(
            select(StrategicDecision).where(StrategicDecision.decision_id == first["decision_id"])
        ).scalar_one()
        actions = session.execute(select(StrategicActionItem)).scalars().all()

    assert decision.status == "proposed"
    assert decision.autonomy_action == "require_human"
    assert decision.autonomy_risk_level == "high"
    payload = json.loads(decision.decision_payload_json)
    assert payload["external_actions_authorized"] is False
    assert payload["customer_value"]["verified_paid_count"] == 0
    assert "customer_outreach_without_approval" in payload["prohibited_actions"]
    assert len(actions) == 1
    assert actions[0].status == "blocked"
    assert actions[0].block_reason == "customer_value_recovery_requires_human_strategy_approval"
    assert actions[0].assigned_to == "daily-orchestrator"
    assert "out_trade_no" not in actions[0].result_json
    assert "provider_trade_no" not in actions[0].result_json

    models._engine = None
    models._SessionFactory = None


def test_unready_or_positive_evidence_never_creates_a_customer_value_escalation(
    tmp_path, monkeypatch
):
    sf = _init_db(tmp_path, monkeypatch)

    unready = ensure_customer_value_gap_escalation(
        evidence=_zero_value_evidence(source_available=False, value_ledger_ready=False),
        session_factory=lambda: sf,
    )
    positive = ensure_customer_value_gap_escalation(
        evidence=_zero_value_evidence(
            verified_paid_count=1,
            verified_paid_amount_cents=9900,
            production_value_verified=True,
        ),
        session_factory=lambda: sf,
    )

    assert unready["status"] == "evidence_unready"
    assert positive["status"] == "value_observed"
    with sf() as session:
        assert session.execute(select(StrategicDecision)).scalars().all() == []
        assert session.execute(select(StrategicActionItem)).scalars().all() == []

    models._engine = None
    models._SessionFactory = None


def test_idempotency_key_never_reuses_an_unrelated_decision(tmp_path, monkeypatch):
    sf = _init_db(tmp_path, monkeypatch)
    ledger = StrategicDecisionLedger(session_factory=lambda: sf)
    key = "customer-value-escalation:test-collision"
    first = ledger.propose(
        title="first",
        action="external announce first",
        proposer=DecisionProposer(actor="test", rationale="test"),
        idempotency_key=key,
    )

    with sf() as session:
        row = session.execute(
            select(StrategicDecision).where(StrategicDecision.decision_id == first.decision_id)
        ).scalar_one()
        row.decision_payload_json = "{}"
        session.commit()

    with pytest.raises(DecisionLifecycleError, match="idempotency_key collision"):
        ledger.propose(
            title="second",
            action="external announce second",
            proposer=DecisionProposer(actor="test", rationale="test"),
            idempotency_key=key,
        )

    models._engine = None
    models._SessionFactory = None


def test_gap_escalation_never_reuses_an_unrelated_scope_record(tmp_path, monkeypatch):
    sf = _init_db(tmp_path, monkeypatch)
    unrelated = StrategicDecisionLedger(session_factory=lambda: sf).propose(
        title="unrelated",
        action="external announce unrelated",
        proposer=DecisionProposer(actor="test", rationale="test"),
        decision_type=DecisionType.STRATEGIC,
        scope="global",
        scope_ref="customer-value-verified-paid",
        idempotency_key="unrelated-customer-value-decision",
    )

    result = ensure_customer_value_gap_escalation(
        evidence=_zero_value_evidence(),
        session_factory=lambda: sf,
    )

    assert result["status"] == "escalated"
    assert result["decision_id"] != unrelated.decision_id

    models._engine = None
    models._SessionFactory = None


def test_scheduler_job_reconciles_before_escalating(monkeypatch):
    import modstore_server.customer_value_scheduler_job as customer_value_job

    calls = []
    monkeypatch.setattr(
        customer_value_job,
        "reconcile_paid_customer_value",
        lambda **kwargs: {
            "source_ready": True,
            "evidence": {"source_available": True},
            "window_days": kwargs["window_days"],
        },
    )
    monkeypatch.setattr(
        customer_value_job,
        "ensure_customer_value_gap_escalation",
        lambda **kwargs: calls.append(kwargs) or {"status": "escalated"},
    )
    monkeypatch.setenv("MODSTORE_CUSTOMER_VALUE_WINDOW_DAYS", "91")

    result = customer_value_job.reconcile_customer_value_with_escalation()

    assert result["escalation"]["status"] == "escalated"
    assert calls == [{"evidence": {"source_available": True}, "window_days": 91}]
