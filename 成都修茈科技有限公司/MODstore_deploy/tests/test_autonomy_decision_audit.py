from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import DatabaseError

import modstore_server.db.base as db_base
import modstore_server.models as models
from modstore_server.api.deps import require_admin
from modstore_server.autonomy_decision_audit import (
    append_autonomy_decision,
    append_domain_risk_decision,
    build_autonomy_decision_evidence,
    record_posthoc_anomaly_evidence,
)
from modstore_server.autonomy_decision_evidence_api import router
from modstore_server.redline_approval_api import router as redline_router
from modstore_server.redline_approval_gate import (
    create_redline_request,
    reject_redline_request,
)

NOW = datetime(2026, 7, 22, 8, 0, tzinfo=timezone.utc)


@pytest.fixture
def session_factory(tmp_path, monkeypatch):
    for engine in {models._engine, db_base._engine}:
        if engine is not None:
            engine.dispose()
    models._engine = None
    models._SessionFactory = None
    db_base._engine = None
    db_base._SessionFactory = None
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("MODSTORE_DB_PATH", str(tmp_path / "autonomy-audit.sqlite"))
    monkeypatch.setenv("MODSTORE_POSTHOC_MATURITY_MINUTES", "0")
    models.init_db()
    yield models.get_session_factory()
    for engine in {models._engine, db_base._engine}:
        if engine is not None:
            engine.dispose()
    models._engine = None
    models._SessionFactory = None
    db_base._engine = None
    db_base._SessionFactory = None


def _decision(sf, action_id: str, decision: str, **overrides):
    values = {
        "action_id": action_id,
        "action": "restart_service",
        "decision": decision,
        "policy": "autonomy_guard",
        "risk_level": "low" if decision == "allow" else "high",
        "actor_class": "system",
        "run_id": "loop-001",
        "source": "test.audit",
        "occurred_at": NOW,
        "session_factory": sf,
    }
    values.update(overrides)
    return append_autonomy_decision(**values)


def test_summary_never_reports_zero_prohibited_miss_without_posthoc_evidence(
    session_factory,
):
    _decision(session_factory, "allow-1", "allow")
    _decision(
        session_factory,
        "block-1",
        "block",
        prohibited_rule_hits=["delete_user_data"],
        risk_level="blocked",
    )
    _decision(session_factory, "veto-1", "veto")

    unknown = build_autonomy_decision_evidence(
        window_days=30,
        session_factory=session_factory,
        now=NOW,
    )
    assert unknown["total"] == 3
    assert unknown["veto_count"] == 1
    assert unknown["veto_rate"] == 33.33
    assert unknown["prohibited_hit_count"] == 1
    assert unknown["has_prohibited_miss"] is None
    assert unknown["prohibited_miss_evidence_status"] == "unknown"
    assert unknown["posthoc_uncovered_count"] == 1
    assert unknown["posthoc_uncovered_contracts"] == [
        {
            "action": "restart_service",
            "source": "test.audit",
            "count": 1,
        }
    ]

    record_posthoc_anomaly_evidence(
        action_id="allow-1",
        verdict="no_prohibited_miss",
        evidence_ref="incident-scan:001",
        detector="post-deploy-anomaly-verifier",
        occurred_at=NOW,
        session_factory=session_factory,
    )
    verified = build_autonomy_decision_evidence(
        session_factory=session_factory,
        now=NOW,
    )
    assert verified["has_prohibited_miss"] is False
    assert verified["prohibited_miss_evidence_status"] == "verified_clear"
    assert verified["posthoc_coverage_rate"] == 100.0
    assert verified["posthoc_uncovered_count"] == 0
    assert verified["posthoc_uncovered_contracts"] == []


def test_uncovered_contract_summary_is_aggregate_and_has_no_action_ids(
    session_factory,
):
    _decision(
        session_factory,
        "private-action-id-1",
        "allow",
        action="daily_digest",
        source="daily_digest.cron",
    )
    _decision(
        session_factory,
        "private-action-id-2",
        "allow",
        action="daily_digest",
        source="daily_digest.cron",
    )
    _decision(
        session_factory,
        "private-action-id-3",
        "allow",
        action="self_heal_pr_merge",
        source="approval_dispatcher.auto_merge",
    )

    evidence = build_autonomy_decision_evidence(
        session_factory=session_factory,
        now=NOW,
    )

    assert evidence["posthoc_uncovered_count"] == 3
    assert evidence["posthoc_uncovered_contracts"] == [
        {
            "action": "daily_digest",
            "source": "daily_digest.cron",
            "count": 2,
        },
        {
            "action": "self_heal_pr_merge",
            "source": "approval_dispatcher.auto_merge",
            "count": 1,
        },
    ]
    assert "private-action-id" not in json.dumps(
        evidence["posthoc_uncovered_contracts"],
        sort_keys=True,
    )


def test_fresh_allow_is_pending_until_posthoc_maturity_sla_expires(
    session_factory,
):
    old_at = NOW - timedelta(minutes=120)
    fresh_at = NOW - timedelta(minutes=30)
    _decision(session_factory, "old-allow", "allow", occurred_at=old_at)
    record_posthoc_anomaly_evidence(
        action_id="old-allow",
        verdict="no_prohibited_miss",
        evidence_ref="production-receipt:old",
        detector="post-deploy-anomaly-verifier",
        occurred_at=old_at + timedelta(minutes=15),
        session_factory=session_factory,
    )
    _decision(
        session_factory,
        "fresh-allow",
        "allow",
        action="self_maintenance_l1_merge",
        source="self_maintenance_loop.remote_merge_request",
        occurred_at=fresh_at,
    )

    within_sla = build_autonomy_decision_evidence(
        session_factory=session_factory,
        now=NOW,
        posthoc_maturity_minutes=90,
    )

    assert within_sla["has_prohibited_miss"] is False
    assert within_sla["posthoc_maturity_minutes"] == 90
    assert within_sla["posthoc_eligible_allow_count"] == 1
    assert within_sla["posthoc_eligible_conclusive_count"] == 1
    assert within_sla["posthoc_pending_count"] == 1
    assert within_sla["posthoc_pending_contracts"] == [
        {
            "action": "self_maintenance_l1_merge",
            "source": "self_maintenance_loop.remote_merge_request",
            "count": 1,
        }
    ]
    assert within_sla["posthoc_uncovered_count"] == 0
    assert within_sla["posthoc_coverage_rate"] == 100.0

    overdue = build_autonomy_decision_evidence(
        session_factory=session_factory,
        now=NOW + timedelta(minutes=61),
        posthoc_maturity_minutes=90,
    )

    assert overdue["has_prohibited_miss"] is None
    assert overdue["prohibited_miss_evidence_status"] == "unknown"
    assert overdue["posthoc_eligible_allow_count"] == 2
    assert overdue["posthoc_pending_count"] == 0
    assert overdue["posthoc_uncovered_count"] == 1
    assert overdue["posthoc_coverage_rate"] == 50.0


def test_posthoc_miss_requires_correlated_allowed_action(session_factory):
    _decision(session_factory, "allowed-action", "allow")
    record_posthoc_anomaly_evidence(
        action_id="unrelated-action",
        verdict="prohibited_miss",
        evidence_ref="incident:unrelated",
        detector="anomaly-verifier",
        occurred_at=NOW,
        session_factory=session_factory,
    )
    unrelated = build_autonomy_decision_evidence(
        session_factory=session_factory,
        now=NOW,
    )
    assert unrelated["has_prohibited_miss"] is None
    assert unrelated["prohibited_miss_count"] == 0

    record_posthoc_anomaly_evidence(
        action_id="allowed-action",
        verdict="prohibited_miss",
        evidence_ref="incident:confirmed-001",
        detector="anomaly-verifier",
        occurred_at=NOW,
        session_factory=session_factory,
    )
    detected = build_autonomy_decision_evidence(
        session_factory=session_factory,
        now=NOW,
    )
    assert detected["has_prohibited_miss"] is True
    assert detected["prohibited_miss_count"] == 1


def test_ledger_redacts_unsafe_identifiers_and_rejects_mutation(session_factory):
    secret = "sk-sensitive-value-that-must-never-be-stored"
    item = append_autonomy_decision(
        action_id=secret,
        action="restart_service",
        decision="block",
        policy=f"api_key={secret}",
        risk_level="blocked",
        actor_class="system",
        run_id=f"token={secret}",
        prohibited_rule_hits=[secret],
        source=f"Bearer {secret}",
        occurred_at=NOW,
        session_factory=session_factory,
    )
    serialized = json.dumps(item, sort_keys=True)
    assert secret not in serialized
    assert "sha256:" in serialized

    with session_factory() as session:
        row = session.query(models.AutonomyDecisionAudit).one()
        row.decision = "allow"
        with pytest.raises(DatabaseError):
            session.commit()
        session.rollback()

    with session_factory() as session:
        row = session.query(models.AutonomyDecisionAudit).one()
        session.delete(row)
        with pytest.raises(DatabaseError):
            session.commit()
        session.rollback()

    evidence = build_autonomy_decision_evidence(
        session_factory=session_factory,
        now=NOW,
    )
    assert evidence["append_only_enforced"] is True


def test_concurrent_append_and_event_id_idempotency(session_factory):
    def write(index: int):
        return append_autonomy_decision(
            action_id=f"concurrent-{index}",
            action="restart_service",
            decision="allow",
            policy="autonomy_guard",
            risk_level="low",
            actor_class="system",
            event_id=f"concurrent-event-{index}",
            occurred_at=NOW,
            session_factory=session_factory,
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        rows = list(pool.map(write, range(24)))
    assert len({row["event_id"] for row in rows}) == 24

    def duplicate(_: int):
        return append_autonomy_decision(
            action_id="idempotent-action",
            action="restart_service",
            decision="allow",
            policy="autonomy_guard",
            risk_level="low",
            actor_class="system",
            event_id="same-event-id",
            occurred_at=NOW,
            session_factory=session_factory,
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        duplicates = list(pool.map(duplicate, range(12)))
    assert len({row["id"] for row in duplicates}) == 1
    with session_factory() as session:
        assert session.query(models.AutonomyDecisionAudit).count() == 25


def test_domain_adapter_records_actor_run_policy_and_prohibited_hit(session_factory):
    decision = SimpleNamespace(
        to_dict=lambda: {
            "action_id": "guard-action-1",
            "action": "delete_user_data",
            "decision": "prohibited",
            "allowed": False,
            "requires_confirmation": False,
            "policy": "require_human",
            "risk_level": "blocked",
            "prohibited": True,
            "approver": None,
        }
    )
    row = append_domain_risk_decision(
        decision,
        context={"run_id": "loop-run-007", "actor_class": "ai_employee"},
        source="employee_executor",
        session_factory=session_factory,
    )
    assert row["decision"] == "block"
    assert row["actor_class"] == "ai_employee"
    assert row["run_id"] == "loop-run-007"
    assert row["policy"] == "require_human"
    assert row["prohibited_rule_hits"] == ["delete_user_data"]


def test_redline_approval_center_is_wired_without_new_write_endpoint(
    session_factory,
    monkeypatch,
):
    monkeypatch.setattr("modstore_server.incident_bus.publish", lambda *args, **kwargs: None)
    created = create_redline_request(
        "deploy",
        "deploy-release-officer",
        "deploy staged release",
        {"run_id": "release-loop-1", "raw": "not copied into autonomy audit"},
    )
    assert created["ok"] is True

    rejected = reject_redline_request(
        int(created["cr_id"]),
        admin_user_id=42,
        reason="owner veto",
    )
    assert rejected["ok"] is True
    evidence = build_autonomy_decision_evidence(
        session_factory=session_factory,
        now=datetime.now(timezone.utc),
    )
    assert evidence["total"] == 1
    assert evidence["veto_count"] == 1
    assert {item["actor_class"] for item in evidence["items"]} == {
        "ai_employee",
        "human",
    }


def test_admin_evidence_endpoint_requires_admin_and_is_read_only(monkeypatch):
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    denied = client.get("/api/admin/autonomy/evidence")
    assert denied.status_code == 401

    app.dependency_overrides[require_admin] = lambda: SimpleNamespace(is_admin=True)
    monkeypatch.setattr(
        "modstore_server.autonomy_decision_evidence_api.build_autonomy_decision_evidence",
        lambda window_days, limit: {
            "schema": "autonomy_decision_evidence.v1",
            "window_days": window_days,
            "limit": limit,
            "has_prohibited_miss": None,
        },
    )
    monkeypatch.setattr(
        "modstore_server.autonomy_decision_evidence_api.get_pending_redline_requests",
        lambda: [],
    )
    allowed = client.get("/api/admin/autonomy/evidence?window_days=30&limit=50")
    assert allowed.status_code == 200
    assert allowed.json()["data"]["has_prohibited_miss"] is None
    assert allowed.json()["data"]["veto_channel"]["writes_added_by_evidence_api"] is False
    assert len(router.routes) == 1
    assert router.routes[0].methods == {"GET"}


def test_existing_redline_veto_routes_require_admin_and_bind_authenticated_actor(
    monkeypatch,
):
    app = FastAPI()
    app.include_router(redline_router)
    client = TestClient(app)

    assert client.get("/api/admin/redline/pending").status_code == 401
    assert (
        client.post(
            "/api/admin/redline/requests/7/reject",
            json={"admin_user_id": 999, "reason": "test"},
        ).status_code
        == 401
    )

    app.dependency_overrides[require_admin] = lambda: SimpleNamespace(is_admin=True, id=42)
    seen: dict[str, int] = {}

    def fake_reject(cr_id: int, admin_user_id: int, *, reason: str):
        seen.update({"cr_id": cr_id, "admin_user_id": admin_user_id})
        return {"ok": True, "reason": reason}

    monkeypatch.setattr(
        "modstore_server.redline_approval_gate.reject_redline_request",
        fake_reject,
    )
    allowed = client.post(
        "/api/admin/redline/requests/7/reject",
        json={"admin_user_id": 999, "reason": "owner veto"},
    )
    assert allowed.status_code == 200
    assert seen == {"cr_id": 7, "admin_user_id": 42}
