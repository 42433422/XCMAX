from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from modstore_server import auth_service
from modstore_server.customer_service_delivery_models import (
    custom_delivery_commerce_blockers,
)
from modstore_server.db.delivery_commerce import UpdateInstallationReceipt
from modstore_server.models import Base, Entitlement, User, UserPlan
from modstore_server.standard_delivery_api import build_standard_delivery_rows


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_standard_delivery_requires_install_and_first_login():
    db = _session()
    try:
        user = User(
            username="permanent_pro",
            email="permanent-pro@example.com",
            password_hash="unused",
            account_state="active",
            created_at=datetime(2026, 8, 29, 10, 0, tzinfo=UTC),
        )
        db.add(user)
        db.flush()
        db.add(
            UserPlan(
                user_id=user.id,
                plan_id="saas-permanent-growth",
                is_active=True,
                started_at=datetime(2026, 8, 29, 10, 5, tzinfo=UTC),
            )
        )
        db.add(
            Entitlement(
                user_id=user.id,
                entitlement_type="plan",
                source_order_id="ORDER-PAID-001",
                metadata_json='{"plan_id":"saas-permanent-growth"}',
                is_active=True,
            )
        )
        db.commit()

        rows = build_standard_delivery_rows(db)
        assert len(rows) == 1
        assert rows[0]["plan"]["title"] == "企业成长版"
        assert rows[0]["status"] == "pending_install"
        assert rows[0]["delivery_no"] == "STD-ORDER-PAID-001"

        db.add(
            UpdateInstallationReceipt(
                user_id=user.id,
                installation_id="installation-0000000000000001",
                idempotency_key="receipt-00000000000000000001",
                platform="darwin",
                installed_version="1.0.0.1",
                installed_build_sha="build-sha-1",
                status="installed",
                source="desktop_inventory",
                reported_at=datetime(2026, 8, 29, 10, 10, tzinfo=UTC),
            )
        )
        db.commit()
        assert build_standard_delivery_rows(db)[0]["status"] == "pending_first_login"

        user.first_login_at = datetime(2026, 8, 29, 10, 12, tzinfo=UTC)
        user.last_login_at = user.first_login_at
        db.add(user)
        db.commit()
        completed = build_standard_delivery_rows(db)[0]
        assert completed["status"] == "completed"
        assert completed["install"]["installed_devices"] == 1
        assert completed["first_login"]["ok"] is True
        assert completed["completion_rule"] == "installed_and_first_login"
    finally:
        db.close()


def test_trial_accounts_are_not_standard_permanent_deliveries():
    db = _session()
    try:
        user = User(username="trial", password_hash="unused")
        db.add(user)
        db.flush()
        db.add(UserPlan(user_id=user.id, plan_id="saas-trial-30", is_active=True))
        db.commit()
        assert build_standard_delivery_rows(db) == []
    finally:
        db.close()


def test_custom_delivery_pricing_switches_after_initial_delivery():
    initial = {
        "delivery_terms": {"pricing_mode": "initial_included"},
        "crm": {},
    }
    assert custom_delivery_commerce_blockers(initial) == []

    addon = {
        "delivery_terms": {"pricing_mode": "post_delivery_addon"},
        "crm": {
            "assignment": {"status": "assigned", "owner_name": "生产员工"},
            "quote": {"status": "draft"},
            "contract": {"status": "waived"},
            "payment": {"status": "unpaid"},
        },
    }
    assert custom_delivery_commerce_blockers(addon) == ["报价尚未确认", "款项尚未结清"]
    addon["crm"]["quote"] = {"status": "accepted", "amount": 1000}
    addon["crm"]["payment"] = {"status": "paid", "amount_paid": 1000}
    assert custom_delivery_commerce_blockers(addon) == []


def test_password_login_records_first_login_once(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(auth_service, "get_session_factory", lambda: factory)
    with factory() as db:
        db.add(
            User(
                username="login_delivery",
                password_hash=auth_service.hash_password("delivery-pass-123"),
            )
        )
        db.commit()

    first = auth_service.authenticate_user("login_delivery", "delivery-pass-123")
    assert first is not None
    assert first.first_login_at is not None
    first_login_at = first.first_login_at

    second = auth_service.authenticate_user("login_delivery", "delivery-pass-123")
    assert second is not None
    assert second.first_login_at == first_login_at
    assert second.last_login_at is not None
