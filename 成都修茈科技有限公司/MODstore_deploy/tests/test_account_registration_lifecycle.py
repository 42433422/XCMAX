"""Registration -> payment fulfilment -> desktop access lifecycle contract."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from modstore_server.models import (
    Entitlement,
    PlanTemplate,
    User,
    UserPlan,
    get_session_factory,
)
from modstore_server.account_lifecycle import mark_pending_payment
from modstore_server.payment_fulfilment import FulfilContext, PlanFulfilStrategy
from modstore_server.api.app_factory import _iter_route_method_signatures


def test_registration_payment_and_expiry_drive_desktop_access(client):
    username = f"lifecycle_{uuid.uuid4().hex[:12]}"
    registered = client.post(
        "/api/auth/register",
        json={"username": username, "password": "lifecycle-pass-12"},
    )
    assert registered.status_code == 200, registered.text
    registration = registered.json()
    assert registration["account_state"] == "pending_plan"
    assert registration["next_action"] == "select_plan"
    assert registration["desktop_access"] is False
    assert registration["user"]["desktop_access"] is False

    token = registration["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    before = client.get("/api/auth/me", headers=headers)
    assert before.status_code == 200, before.text
    assert before.json()["desktop_access"] is False

    user_id = int(registration["user"]["id"])
    mark_pending_payment(user_id)
    awaiting_payment = client.get("/api/auth/me", headers=headers)
    assert awaiting_payment.status_code == 200, awaiting_payment.text
    assert awaiting_payment.json()["account_state"] == "pending_payment"
    assert awaiting_payment.json()["next_action"] == "complete_payment"
    assert awaiting_payment.json()["desktop_access"] is False

    plan_id = "plan_enterprise"
    out_trade_no = f"LIFECYCLE-{uuid.uuid4().hex[:16]}"
    now = datetime.now(timezone.utc)
    sf = get_session_factory()
    with sf() as session:
        plan = session.query(PlanTemplate).filter(PlanTemplate.id == plan_id).first()
        if plan is None:
            plan = PlanTemplate(
                id=plan_id,
                name="企业套餐",
                price=99.9,
                quotas_json="{}",
                is_active=True,
            )
            session.add(plan)
            session.flush()
        strategy = PlanFulfilStrategy()
        ctx = FulfilContext(
            out_trade_no=out_trade_no,
            user_id=user_id,
            total_amount=99.9,
            item_id=0,
            plan_id=plan_id,
            kind="plan",
            order={"subject": "企业套餐"},
        )
        strategy.fulfill(
            session,
            ctx,
            now=now,
            description="企业套餐",
            txn_type="plan_purchase",
        )
        session.commit()
        assert strategy.is_already_fulfilled(session, ctx) is True
        assert session.query(UserPlan).filter(UserPlan.user_id == user_id).count() == 1
        assert (
            session.query(Entitlement)
            .filter(
                Entitlement.user_id == user_id,
                Entitlement.source_order_id == out_trade_no,
            )
            .count()
            == 1
        )
        assert (
            session.query(User).filter(User.id == user_id).one().account_state
            == "active"
        )

    after = client.get("/api/auth/me", headers=headers)
    assert after.status_code == 200, after.text
    assert after.json()["account_state"] == "active"
    assert after.json()["next_action"] == "return_desktop_login"
    assert after.json()["desktop_access"] is True
    assert after.json()["active_plan_id"] == plan_id

    with sf() as session:
        row = session.query(UserPlan).filter(UserPlan.user_id == user_id).one()
        row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        session.commit()

    expired = client.get("/api/auth/me", headers=headers)
    assert expired.status_code == 200, expired.text
    assert expired.json()["account_state"] == "pending_plan"
    assert expired.json()["desktop_access"] is False
    assert expired.json()["active_plan_id"] == ""


def test_public_auth_register_has_one_runtime_owner(client):
    owners = [
        signature
        for signature in _iter_route_method_signatures(client.app.routes)
        if signature == ("/api/auth/register", "POST")
    ]
    assert len(owners) == 1
