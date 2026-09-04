from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException

import modstore_server.models as models
from modstore_server.customer_value_evidence import (
    append_customer_value_receipt,
    build_customer_value_evidence,
)

NOW = datetime(2026, 9, 4, 8, 0, tzinfo=UTC)


def _init_db(tmp_path, monkeypatch):
    models._engine = None
    models._SessionFactory = None
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("MODSTORE_DB_PATH", str(tmp_path / "lifecycle.sqlite"))
    models.init_db()
    return models.get_session_factory()


def _order():
    return {
        "status": "paid",
        "out_trade_no": "real-customer-order-001",
        "user_id": 11,
        "enterprise_subject_id": "unified-social-credit-code-001",
        "amount_cents": 4_999_900,
        "paid_at": NOW.isoformat(),
        "payment_provider": "bank",
        "provider_trade_no": "bank-settlement-001",
        "provider_verification": "bank_statement_reconciled",
        "payment_environment": "production",
    }


def _append(sf, order, kind, occurred_at, **extra):
    evidence = {"artifact_sha256": "c" * 64, **extra.pop("evidence", {})}
    goal_id = extra.pop("goal_id", "goal-real-001")
    return append_customer_value_receipt(
        {
            "receipt_kind": kind,
            "verification_status": "verified",
            "lifecycle_v2": True,
            "source_event_id": f"{kind}:{occurred_at.isoformat()}",
            "customer_ref": "paid-user:11",
            "customer_goal_id": goal_id,
            "order_no": order["out_trade_no"],
            "artifact_id": f"artifact:{kind}",
            "acceptance_id": "customer-acceptance-001" if kind == "acceptance" else "",
            "occurred_at": occurred_at.isoformat(),
            "environment": "production",
            "evidence": evidence,
        },
        payment_order=order,
        session_factory=sf,
        now=occurred_at,
    )


def test_complete_six_stage_chain_requires_post_acceptance_reuse(
    tmp_path, monkeypatch
) -> None:
    sf = _init_db(tmp_path, monkeypatch)
    sha = "a" * 40
    monkeypatch.setenv("XCMAX_RELEASE_SHA", sha)
    order = _order()
    first = NOW + timedelta(hours=1)
    outcome_at = NOW + timedelta(hours=2)
    acceptance_at = NOW + timedelta(hours=3)
    reuse_at = acceptance_at + timedelta(hours=25)
    with sf() as session:
        session.add(
            models.UpdateInstallationReceipt(
                user_id=11,
                installation_id="external-device-001",
                idempotency_key="external-device-receipt-001",
                channel="stable",
                platform="darwin",
                target_version="1.0.0.1",
                target_build_sha=sha,
                installed_version="1.0.0.1",
                installed_build_sha=sha,
                status="installed",
                source="desktop_ota",
                reported_at=NOW.replace(tzinfo=None),
            )
        )
        session.commit()
    _append(
        sf,
        order,
        "goal",
        NOW + timedelta(minutes=15),
        evidence={
            "baseline": 10,
            "target": 20,
            "comparison": "ge",
            "unit": "documents/hour",
            "measurement_window": "2026-09-04T08:00Z/2026-09-04T10:00Z",
            "agreement_sha256": "b" * 64,
            "customer_confirmed": True,
        },
    )
    _append(
        sf,
        order,
        "first_use",
        first,
        evidence={
            "run_id": "real-run-first",
            "success": True,
            "business_output": True,
            "task_type": "document-processing",
        },
    )
    _append(
        sf,
        order,
        "outcome",
        outcome_at,
        evidence={
            "baseline": 10,
            "target": 20,
            "measured_value": 24,
            "comparison": "ge",
            "unit": "documents/hour",
            "measurement_window": "2026-09-04T08:00Z/2026-09-04T10:00Z",
            "source_material_summary": "Production document throughput export",
            "source_material_sha256": "d" * 64,
        },
    )
    _append(
        sf,
        order,
        "acceptance",
        acceptance_at,
        evidence={"customer_confirmed": True},
    )
    _append(
        sf,
        order,
        "reuse",
        reuse_at,
        evidence={
            "run_id": "real-run-reuse",
            "success": True,
            "business_output": True,
            "task_type": "document-processing",
        },
    )

    result = build_customer_value_evidence(
        orders=[order], session_factory=sf, now=reuse_at
    )

    assert result["six_stage_counts"] == {
        "payment": 1,
        "installation": 1,
        "first_use": 1,
        "outcome": 1,
        "acceptance": 1,
        "reuse": 1,
    }
    assert result["complete_customer_count"] == 1
    assert result["three_customer_loop_verified"] is False
    assert order["out_trade_no"] not in str(result["customers"])
    models._engine = None
    models._SessionFactory = None


def test_aggregate_selects_a_complete_goal_without_mixing_earlier_goal(
    tmp_path, monkeypatch
) -> None:
    sf = _init_db(tmp_path, monkeypatch)
    sha = "9" * 40
    monkeypatch.setenv("XCMAX_RELEASE_SHA", sha)
    order = _order()
    with sf() as session:
        session.add(
            models.UpdateInstallationReceipt(
                user_id=11,
                installation_id="external-device-goal-selection",
                idempotency_key="external-device-goal-selection-receipt",
                channel="stable",
                platform="darwin",
                target_version="1.0.0.1",
                target_build_sha=sha,
                installed_version="1.0.0.1",
                installed_build_sha=sha,
                status="installed",
                source="desktop_ota",
                reported_at=NOW.replace(tzinfo=None),
            )
        )
        session.commit()

    def append_goal(goal_id, start, measured):
        _append(
            sf,
            order,
            "goal",
            start - timedelta(minutes=15),
            goal_id=goal_id,
            evidence={
                "baseline": 10,
                "target": 20,
                "comparison": "ge",
                "unit": "documents/hour",
                "measurement_window": "two-hour-production-window",
                "agreement_sha256": "b" * 64,
                "customer_confirmed": True,
            },
        )
        _append(
            sf,
            order,
            "first_use",
            start,
            goal_id=goal_id,
            evidence={
                "run_id": f"{goal_id}-first",
                "success": True,
                "business_output": True,
                "task_type": "document-processing",
            },
        )
        _append(
            sf,
            order,
            "outcome",
            start + timedelta(hours=1),
            goal_id=goal_id,
            evidence={
                "baseline": 10,
                "target": 20,
                "measured_value": measured,
                "comparison": "ge",
                "unit": "documents/hour",
                "measurement_window": "two-hour-production-window",
                "source_material_summary": "Production document throughput export",
                "source_material_sha256": "d" * 64,
            },
        )
        accepted_at = start + timedelta(hours=2)
        _append(
            sf,
            order,
            "acceptance",
            accepted_at,
            goal_id=goal_id,
            evidence={"customer_confirmed": True},
        )
        _append(
            sf,
            order,
            "reuse",
            accepted_at + timedelta(hours=25),
            goal_id=goal_id,
            evidence={
                "run_id": f"{goal_id}-reuse",
                "success": True,
                "business_output": True,
                "task_type": "document-processing",
            },
        )

    append_goal("goal-below-target", NOW + timedelta(hours=1), 19)
    append_goal("goal-achieved", NOW + timedelta(hours=40), 24)
    result = build_customer_value_evidence(
        orders=[order],
        session_factory=sf,
        now=NOW + timedelta(hours=70),
    )

    assert result["complete_customer_count"] == 1
    assert result["customers"][0]["complete"] is True
    models._engine = None
    models._SessionFactory = None


def test_reuse_before_24_hours_is_rejected(tmp_path, monkeypatch) -> None:
    sf = _init_db(tmp_path, monkeypatch)
    order = _order()
    _append(
        sf,
        order,
        "first_use",
        NOW,
        evidence={
            "run_id": "first-run",
            "success": True,
            "business_output": True,
            "task_type": "document-processing",
        },
    )
    _append(
        sf,
        order,
        "acceptance",
        NOW + timedelta(hours=1),
        evidence={"customer_confirmed": True},
    )
    with pytest.raises(ValueError, match="at least 24 hours"):
        _append(
            sf,
            order,
            "reuse",
            NOW + timedelta(hours=2),
            evidence={
                "run_id": "second-run",
                "success": True,
                "business_output": True,
                "task_type": "document-processing",
            },
        )
    models._engine = None
    models._SessionFactory = None


def test_enterprise_identity_is_single_assignment(tmp_path, monkeypatch) -> None:
    sf = _init_db(tmp_path, monkeypatch)
    from modstore_server.api.market_routes import (
        EnterpriseIdentityDTO,
        api_admin_verify_enterprise_identity,
    )

    with sf() as session:
        admin = models.User(
            username="identity-admin",
            email="identity-admin@example.invalid",
            password_hash="x",
            is_admin=True,
        )
        customer = models.User(
            username="identity-customer",
            email="identity-customer@example.invalid",
            password_hash="x",
            is_admin=False,
        )
        session.add_all([admin, customer])
        session.commit()
        admin_id = int(admin.id)
        customer_id = int(customer.id)

    admin = type("Admin", (), {"id": admin_id})()
    body = EnterpriseIdentityDTO(
        enterprise_subject_id="credit-code-real-001",
        legal_name="真实客户甲有限公司",
        verification_sha256="e" * 64,
    )
    first = api_admin_verify_enterprise_identity(customer_id, body, admin)
    replay = api_admin_verify_enterprise_identity(customer_id, body, admin)
    assert first["frozen"] is True
    assert replay == first

    with pytest.raises(HTTPException) as exc:
        api_admin_verify_enterprise_identity(
            customer_id,
            EnterpriseIdentityDTO(
                enterprise_subject_id="credit-code-other",
                legal_name="另一个主体",
                verification_sha256="f" * 64,
            ),
            admin,
        )
    assert exc.value.status_code == 409
    models._engine = None
    models._SessionFactory = None


def test_java_payment_identity_is_frozen_before_local_commit(tmp_path, monkeypatch) -> None:
    sf = _init_db(tmp_path, monkeypatch)
    import modstore_server.api.market_routes as market_routes
    import modstore_server.api.market_routes_part04 as routes

    with sf() as session:
        session.add_all(
            [
                models.User(
                    id=31,
                    username="identity-admin-java",
                    email="identity-admin-java@example.invalid",
                    password_hash="x",
                    is_admin=True,
                ),
                models.User(
                    id=32,
                    username="identity-customer-java",
                    email="identity-customer-java@example.invalid",
                    password_hash="x",
                    is_admin=False,
                ),
            ]
        )
        session.commit()

    captured = {}

    class Response:
        status_code = 200

        @staticmethod
        def raise_for_status():
            return None

        @staticmethod
        def json():
            return {
                "ok": True,
                "source": "java_postgresql",
                "enterprise_subject_id": "credit-code-java-001",
                "frozen": True,
            }

    def post(url, *, headers, json, timeout):
        captured.update(url=url, headers=headers, json=json, timeout=timeout)
        return Response()

    monkeypatch.setenv("PAYMENT_BACKEND", "java")
    monkeypatch.setenv("MODSTORE_INTERNAL_API_KEY", "internal-key")
    monkeypatch.setenv("JAVA_PAYMENT_SERVICE_URL", "http://payment-service:8080")
    monkeypatch.setattr(routes.httpx, "post", post)
    result = market_routes.api_admin_verify_enterprise_identity(
        32,
        market_routes.EnterpriseIdentityDTO(
            enterprise_subject_id="credit-code-java-001",
            legal_name="真实客户乙有限公司",
            verification_sha256="a" * 64,
        ),
        type("Admin", (), {"id": 31})(),
    )

    assert result["frozen"] is True
    assert captured["json"]["verified_by_user_id"] == 31
    with sf() as session:
        row = session.query(models.User).filter(models.User.id == 32).one()
        assert row.enterprise_subject_id == "credit-code-java-001"
    models._engine = None
    models._SessionFactory = None
