from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import DatabaseError

import modstore_server.models as models
from modstore_server.api.deps import require_admin
from modstore_server.customer_value_evidence import (
    _load_java_payment_orders,
    append_customer_value_receipt,
    build_customer_value_evidence,
    classify_payment_order,
)
from modstore_server.customer_value_evidence_api import router
from modstore_server.customer_value_reconciler import reconcile_paid_customer_value

NOW = datetime(2026, 7, 22, 6, 0, tzinfo=timezone.utc)


def _init_db(tmp_path, monkeypatch):
    models._engine = None
    models._SessionFactory = None
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("MODSTORE_DB_PATH", str(tmp_path / "customer-value.sqlite"))
    models.init_db()
    return models.get_session_factory()


def _verified_payment(order_no: str = "customer_order_001", **overrides):
    order = {
        "status": "paid",
        "out_trade_no": order_no,
        "amount_cents": 9900,
        "paid_at": NOW.isoformat(),
        "payment_provider": "alipay",
        "provider_trade_no": "provider_trade_001",
        "provider_verification": "alipay_remote_query",
        "payment_environment": "production",
        "fulfillment_verified": True,
        "fulfillment_artifact_id": "catalog:customer-value-pack@1.2.3",
        "fulfillment_artifact_sha256": "a" * 64,
        "fulfilled_at": NOW.isoformat(),
    }
    order.update(overrides)
    return order


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"subject": "pilot smoke order"}, "test_record"),
        ({"out_trade_no": "renew_internal_001"}, "internal_order"),
        ({"refunded": True}, "refunded"),
        ({"amount_cents": 0}, "nonpositive_amount"),
        ({"paid_at": ""}, "missing_paid_at"),
        ({"provider_trade_no": ""}, "missing_provider_proof"),
        ({"payment_environment": "sandbox"}, "nonproduction"),
    ],
)
def test_payment_classifier_rejects_non_customer_evidence(overrides, reason) -> None:
    eligible, actual_reason = classify_payment_order(_verified_payment(**overrides))

    assert eligible is False
    assert actual_reason == reason


def test_customer_value_ledger_is_append_only_and_links_paid_delivery(
    tmp_path, monkeypatch
):
    sf = _init_db(tmp_path, monkeypatch)
    order = _verified_payment()
    common = {
        "verification_status": "verified",
        "customer_ref": "external-customer-001",
        "customer_goal_id": "goal-001",
        "order_no": order["out_trade_no"],
        "source_employee_id": "delivery-receipt-officer",
        "occurred_at": NOW.isoformat(),
    }
    goal = append_customer_value_receipt(
        {**common, "receipt_kind": "goal", "source_event_id": "goal:event:001"},
        payment_order=order,
        session_factory=sf,
        now=NOW,
    )
    delivery = append_customer_value_receipt(
        {
            **common,
            "receipt_kind": "delivery",
            "source_event_id": "delivery:event:001",
            "artifact_id": "artifact:001",
            "evidence": {"artifact_sha256": "b" * 64},
        },
        payment_order=order,
        session_factory=sf,
        now=NOW,
    )
    duplicate = append_customer_value_receipt(
        {
            **common,
            "receipt_kind": "delivery",
            "source_event_id": "delivery:event:001",
            "artifact_id": "artifact:001",
            "evidence": {"artifact_sha256": "b" * 64},
        },
        payment_order=order,
        session_factory=sf,
        now=NOW,
    )

    assert goal["created"] is True
    assert delivery["created"] is True
    assert duplicate == {
        "ok": True,
        "created": False,
        "receipt_id": delivery["receipt_id"],
    }

    evidence = build_customer_value_evidence(
        orders=[order],
        session_factory=sf,
        now=NOW,
    )
    assert evidence["value_ledger_ready"] is True
    assert evidence["verified_paid_count"] == 1
    assert evidence["verified_paid_amount_cents"] == 9900
    assert evidence["customer_goal_count"] == 1
    assert evidence["delivered_count"] == 1
    assert evidence["paid_delivery_count"] == 1
    assert evidence["unproven_delivery_count"] == 0
    assert evidence["paid_acceptance_count"] == 0
    assert evidence["customer_acceptance_verified"] is False
    assert evidence["production_value_verified"] is True
    assert evidence["outcome_verified"] is True

    with sf() as session:
        row = (
            session.query(models.CustomerValueReceipt)
            .filter_by(receipt_id=goal["receipt_id"])
            .one()
        )
        row.customer_ref = "mutated"
        with pytest.raises(DatabaseError):
            session.commit()
        session.rollback()

    with sf() as session:
        row = (
            session.query(models.CustomerValueReceipt)
            .filter_by(receipt_id=goal["receipt_id"])
            .one()
        )
        session.delete(row)
        with pytest.raises(DatabaseError):
            session.commit()
        session.rollback()

    models._engine = None
    models._SessionFactory = None


def test_verified_delivery_rejects_mutable_or_unidentified_artifact(
    tmp_path, monkeypatch
):
    sf = _init_db(tmp_path, monkeypatch)
    order = _verified_payment()

    with pytest.raises(ValueError, match="artifact_sha256"):
        append_customer_value_receipt(
            {
                "receipt_kind": "delivery",
                "verification_status": "verified",
                "source_event_id": "delivery:missing-digest",
                "customer_ref": "external-customer-001",
                "customer_goal_id": "goal-001",
                "order_no": order["out_trade_no"],
                "artifact_id": "artifact:mutable",
                "evidence": {},
            },
            payment_order=order,
            session_factory=sf,
            now=NOW,
        )

    models._engine = None
    models._SessionFactory = None


def test_evidence_excludes_test_internal_refund_and_unproved_orders(
    tmp_path, monkeypatch
):
    sf = _init_db(tmp_path, monkeypatch)
    orders = [
        _verified_payment("customer_order_001"),
        _verified_payment("pilot_001"),
        _verified_payment("renew_internal_001"),
        _verified_payment("refunded_001", refunded=True),
        _verified_payment("unproved_001", provider_trade_no=""),
        _verified_payment("sandbox_001", payment_environment="sandbox"),
    ]

    evidence = build_customer_value_evidence(orders=orders, session_factory=sf, now=NOW)

    assert evidence["verified_paid_count"] == 1
    assert evidence["production_value_verified"] is True
    assert evidence["outcome_verified"] is False
    assert evidence["excluded"] == {
        "test_record": 2,
        "internal_order": 1,
        "refunded": 1,
        "nonpositive_amount": 0,
        "missing_paid_at": 0,
        "missing_provider_proof": 1,
        "nonproduction": 0,
        "outside_window": 0,
    }

    models._engine = None
    models._SessionFactory = None


def test_admin_customer_value_endpoint_requires_admin_and_returns_aggregate(
    monkeypatch,
):
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    denied = client.get("/api/admin/customer-value/evidence")
    assert denied.status_code == 401

    app.dependency_overrides[require_admin] = lambda: SimpleNamespace(is_admin=True)
    monkeypatch.setattr(
        "modstore_server.customer_value_evidence_api.build_customer_value_evidence",
        lambda window_days: {
            "schema": "customer_value_evidence.v1",
            "window_days": window_days,
            "value_ledger_ready": True,
            "verified_paid_count": 0,
        },
    )
    allowed = client.get("/api/admin/customer-value/evidence?window_days=90")

    assert allowed.status_code == 200
    assert allowed.json() == {
        "ok": True,
        "data": {
            "schema": "customer_value_evidence.v1",
            "window_days": 90,
            "value_ledger_ready": True,
            "verified_paid_count": 0,
        },
    }


def test_java_postgresql_orders_are_authoritative_customer_value_source(
    tmp_path,
    monkeypatch,
) -> None:
    sf = _init_db(tmp_path, monkeypatch)
    monkeypatch.setenv("PAYMENT_BACKEND", "java")
    monkeypatch.setattr(
        "modstore_server.customer_value_evidence._load_java_payment_orders",
        lambda window_days: [
            _verified_payment(
                "java_customer_order_001",
                provider_verification="java_gateway_verified",
            )
        ],
    )

    evidence = build_customer_value_evidence(session_factory=sf, now=NOW)

    assert evidence["source_owner"] == "java_postgresql_internal_api"
    assert evidence["source_available"] is True
    assert evidence["source_authoritative"] is True
    assert evidence["value_ledger_ready"] is True
    assert evidence["verified_paid_count"] == 1
    assert evidence["production_value_verified"] is True

    models._engine = None
    models._SessionFactory = None


def test_java_payment_read_failure_fails_closed(tmp_path, monkeypatch) -> None:
    sf = _init_db(tmp_path, monkeypatch)
    monkeypatch.setenv("PAYMENT_BACKEND", "java")

    def _unavailable(_window_days: int):
        raise RuntimeError("unavailable")

    monkeypatch.setattr(
        "modstore_server.customer_value_evidence._load_java_payment_orders",
        _unavailable,
    )

    evidence = build_customer_value_evidence(session_factory=sf, now=NOW)

    assert evidence["source_owner"] == "java_postgresql_internal_api"
    assert evidence["source_available"] is False
    assert evidence["source_authoritative"] is False
    assert evidence["value_ledger_ready"] is False
    assert evidence["verified_paid_count"] == 0
    assert evidence["production_value_verified"] is False

    models._engine = None
    models._SessionFactory = None


def test_java_payment_loader_validates_source_and_paginates(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    class _Response:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    class _Client:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def get(self, _url, *, params, headers):
            calls.append({"params": dict(params), "headers": dict(headers)})
            offset = int(params["offset"])
            page = (
                [_verified_payment(f"java-{index}") for index in range(1000)]
                if offset == 0
                else [_verified_payment("java-1000")]
            )
            return _Response(
                {
                    "ok": True,
                    "source": "java_postgresql",
                    "total": 1001,
                    "orders": page,
                }
            )

    monkeypatch.setenv("MODSTORE_INTERNAL_API_KEY", "unit-test-internal-key")
    monkeypatch.setenv("JAVA_PAYMENT_SERVICE_URL", "http://payment.internal:8080")
    monkeypatch.setattr(
        "modstore_server.customer_value_payment_source.httpx.Client", _Client
    )

    orders = _load_java_payment_orders(90)

    assert len(orders) == 1001
    assert [call["params"]["offset"] for call in calls] == [0, 1000]
    assert all(
        call["headers"]["X-Internal-Api-Key"] == "unit-test-internal-key"
        for call in calls
    )


def test_fulfilled_payment_reconciliation_creates_idempotent_value_loop(
    tmp_path,
    monkeypatch,
) -> None:
    sf = _init_db(tmp_path, monkeypatch)
    order = _verified_payment(
        "customer_fulfilled_001",
        fulfilled=True,
        order_kind="item",
        item_id=42,
    )

    first = reconcile_paid_customer_value(
        orders=[order],
        session_factory=sf,
        now=NOW,
    )
    second = reconcile_paid_customer_value(
        orders=[order],
        session_factory=sf,
        now=NOW,
    )
    evidence = build_customer_value_evidence(
        orders=[order],
        session_factory=sf,
        now=NOW,
    )

    assert first == {
        "ok": True,
        "source_owner": "injected",
        "source_ready": True,
        "checked": 1,
        "created": 2,
        "existing": 0,
        "skipped": {},
    }
    assert second["created"] == 0
    assert second["existing"] == 2
    assert evidence["verified_paid_count"] == 1
    assert evidence["customer_goal_count"] == 1
    assert evidence["delivered_count"] == 1
    assert evidence["paid_delivery_count"] == 1
    assert evidence["outcome_verified"] is True
    with sf() as session:
        delivery = (
            session.query(models.CustomerValueReceipt)
            .filter(models.CustomerValueReceipt.receipt_kind == "delivery")
            .one()
        )
        assert delivery.artifact_id == "catalog:customer-value-pack@1.2.3"
        assert delivery.amount_cents == 9900
        assert '"artifact_sha256":"' + ("a" * 64) + '"' in delivery.evidence_json

    models._engine = None
    models._SessionFactory = None


def test_unverified_plan_payment_never_impersonates_a_customer_delivery(
    tmp_path, monkeypatch
) -> None:
    sf = _init_db(tmp_path, monkeypatch)
    order = _verified_payment(
        "customer_plan_001",
        fulfilled=True,
        order_kind="plan",
        plan_id="plan_pro",
        fulfillment_verified=False,
        fulfillment_artifact_id="",
        fulfillment_artifact_sha256="",
    )

    result = reconcile_paid_customer_value(
        orders=[order],
        session_factory=sf,
        now=NOW,
    )
    evidence = build_customer_value_evidence(
        orders=[order],
        session_factory=sf,
        now=NOW,
    )

    assert result["created"] == 0
    assert result["skipped"] == {"fulfillment_unverified": 1}
    assert evidence["verified_paid_count"] == 1
    assert evidence["customer_goal_count"] == 0
    assert evidence["delivered_count"] == 0
    assert evidence["outcome_verified"] is False

    models._engine = None
    models._SessionFactory = None


def test_verified_plan_activation_and_real_usage_close_customer_value_loop(
    tmp_path, monkeypatch
) -> None:
    sf = _init_db(tmp_path, monkeypatch)
    order = _verified_payment(
        "customer_plan_used_001",
        fulfilled=True,
        order_kind="plan",
        plan_id="plan_pro",
        fulfillment_artifact_id="service-plan:plan_pro@0123456789abcdef",
        fulfillment_artifact_sha256="c" * 64,
        fulfillment_artifact_kind="service_plan_activation",
        acceptance_verified=True,
        acceptance_reason="verified_plan_usage",
        accepted_at=NOW.isoformat(),
    )

    first = reconcile_paid_customer_value(orders=[order], session_factory=sf, now=NOW)
    second = reconcile_paid_customer_value(orders=[order], session_factory=sf, now=NOW)
    evidence = build_customer_value_evidence(
        orders=[order], session_factory=sf, now=NOW
    )

    assert first["created"] == 3
    assert first["existing"] == 0
    assert first["skipped"] == {}
    assert second["created"] == 0
    assert second["existing"] == 3
    assert evidence["customer_goal_count"] == 1
    assert evidence["paid_delivery_count"] == 1
    assert evidence["paid_acceptance_count"] == 1
    assert evidence["outcome_verified"] is True
    assert evidence["customer_acceptance_verified"] is True

    models._engine = None
    models._SessionFactory = None


def test_plan_delivery_rejects_non_activation_artifact(tmp_path, monkeypatch) -> None:
    sf = _init_db(tmp_path, monkeypatch)
    order = _verified_payment(
        "customer_plan_wrong_artifact_001",
        fulfilled=True,
        order_kind="plan",
        plan_id="plan_pro",
        fulfillment_artifact_kind="catalog_item",
    )

    result = reconcile_paid_customer_value(orders=[order], session_factory=sf, now=NOW)

    assert result["created"] == 0
    assert result["skipped"] == {"plan_artifact_kind_invalid": 1}
    models._engine = None
    models._SessionFactory = None


def test_plan_usage_acceptance_requires_verified_usage_reason(
    tmp_path, monkeypatch
) -> None:
    sf = _init_db(tmp_path, monkeypatch)
    order = _verified_payment(
        "customer_plan_bad_acceptance_001",
        fulfilled=True,
        order_kind="plan",
        plan_id="plan_pro",
        fulfillment_artifact_id="service-plan:plan_pro@0123456789abcdef",
        fulfillment_artifact_sha256="c" * 64,
        fulfillment_artifact_kind="service_plan_activation",
        acceptance_verified=True,
        acceptance_reason="payment_received",
        accepted_at=NOW.isoformat(),
    )

    result = reconcile_paid_customer_value(orders=[order], session_factory=sf, now=NOW)
    evidence = build_customer_value_evidence(
        orders=[order], session_factory=sf, now=NOW
    )

    assert result["created"] == 2
    assert result["skipped"] == {"acceptance_evidence_invalid": 1}
    assert evidence["paid_delivery_count"] == 1
    assert evidence["paid_acceptance_count"] == 0
    models._engine = None
    models._SessionFactory = None


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"fulfillment_verified": False}, "fulfillment_unverified"),
        ({"fulfillment_artifact_id": ""}, "artifact_proof_missing"),
        ({"fulfillment_artifact_sha256": "not-a-sha"}, "artifact_proof_missing"),
        ({"fulfillment_artifact_sha256": "g" * 64}, "artifact_proof_invalid"),
        ({"fulfilled_at": ""}, "fulfilled_at_missing"),
    ],
)
def test_paid_item_requires_real_entitlement_artifact_proof(
    tmp_path,
    monkeypatch,
    overrides,
    reason,
) -> None:
    sf = _init_db(tmp_path, monkeypatch)
    order = _verified_payment(
        "customer_unproven_delivery_001",
        fulfilled=True,
        order_kind="item",
        item_id=42,
        **overrides,
    )

    result = reconcile_paid_customer_value(orders=[order], session_factory=sf, now=NOW)

    assert result["created"] == 0
    assert result["skipped"] == {reason: 1}
    models._engine = None
    models._SessionFactory = None
