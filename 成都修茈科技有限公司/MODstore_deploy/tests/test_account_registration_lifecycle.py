"""Registration -> payment fulfilment -> desktop access lifecycle contract."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from modstore_server.account_license_plans import ACCOUNT_LICENSE_PLANS
from modstore_server.account_lifecycle import mark_pending_payment
from modstore_server.api.app_factory import _iter_route_method_signatures
from modstore_server.models import (
    Entitlement,
    PlanTemplate,
    User,
    UserPlan,
    get_session_factory,
)
from modstore_server.payment_fulfilment import FulfilContext, PlanFulfilStrategy


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
    mark_pending_payment(user_id, plan_id="saas-trial-30")
    awaiting_payment = client.get("/api/auth/me", headers=headers)
    assert awaiting_payment.status_code == 200, awaiting_payment.text
    assert awaiting_payment.json()["account_state"] == "pending_payment"
    assert awaiting_payment.json()["next_action"] == "complete_payment"
    assert awaiting_payment.json()["desktop_access"] is False

    plan_id = "saas-trial-30"
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
        assert session.query(User).filter(User.id == user_id).one().account_state == "active"

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


def test_vip_membership_never_grants_desktop_access_and_coexists_with_license(client):
    username = f"separate_{uuid.uuid4().hex[:12]}"
    registration = client.post(
        "/api/auth/register",
        json={"username": username, "password": "separate-pass-12"},
    ).json()
    user_id = int(registration["user"]["id"])
    token = registration["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    sf = get_session_factory()
    strategy = PlanFulfilStrategy()

    with sf() as session:
        membership = session.query(PlanTemplate).filter(PlanTemplate.id == "plan_enterprise").one()
        ctx = FulfilContext(
            out_trade_no=f"MEMBERSHIP-{uuid.uuid4().hex[:12]}",
            user_id=user_id,
            total_amount=float(membership.price),
            item_id=0,
            plan_id=membership.id,
            kind="plan",
            order={"subject": membership.name},
        )
        strategy.fulfill(
            session,
            ctx,
            now=datetime.now(timezone.utc),
            description="VIP/SVIP 额度会员",
            txn_type="plan_purchase",
        )
        session.commit()

    after_membership = client.get("/api/auth/me", headers=headers).json()
    assert after_membership["desktop_access"] is False
    assert after_membership["active_plan_id"] == ""

    with sf() as session:
        license_plan = session.query(PlanTemplate).filter(PlanTemplate.id == "saas-trial-30").one()
        ctx = FulfilContext(
            out_trade_no=f"LICENSE-{uuid.uuid4().hex[:12]}",
            user_id=user_id,
            total_amount=float(license_plan.price),
            item_id=0,
            plan_id=license_plan.id,
            kind="plan",
            order={"subject": license_plan.name},
        )
        strategy.fulfill(
            session,
            ctx,
            now=datetime.now(timezone.utc),
            description="XCAGI 账号授权",
            txn_type="plan_purchase",
        )
        session.commit()
        active_ids = {
            row.plan_id
            for row in session.query(UserPlan)
            .filter(UserPlan.user_id == user_id, UserPlan.is_active.is_(True))
            .all()
        }
        assert active_ids == {"plan_enterprise", "saas-trial-30"}

    after_license = client.get("/api/auth/me", headers=headers).json()
    assert after_license["desktop_access"] is True
    assert after_license["active_plan_id"] == "saas-trial-30"
    assert after_license["account_tier"] == "normal"

    my_membership = client.get("/api/payment/my-plan", headers=headers).json()
    assert my_membership["plan"]["id"] == "plan_enterprise"


def test_account_license_catalog_is_separate_from_usage_memberships(client):
    memberships = client.get("/api/payment/plans").json()["plans"]
    licenses = client.get("/api/payment/account-plans").json()["plans"]
    membership_ids = {row["id"] for row in memberships}
    license_ids = {row["id"] for row in licenses}
    expected_license_ids = {str(row["id"]) for row in ACCOUNT_LICENSE_PLANS}

    assert license_ids == expected_license_ids
    assert membership_ids.isdisjoint(license_ids)
    assert "plan_enterprise" in membership_ids
    assert "saas-trial-30" in license_ids
