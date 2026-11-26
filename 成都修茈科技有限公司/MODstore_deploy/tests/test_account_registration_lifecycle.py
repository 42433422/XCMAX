"""Registration -> payment fulfilment -> desktop access lifecycle contract."""

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier

import pytest
from sqlalchemy.orm import Session, sessionmaker

from modstore_server.account_license_plans import ACCOUNT_LICENSE_PLANS
from modstore_server.account_lifecycle import mark_pending_payment
from modstore_server.api.app_factory import _iter_route_method_signatures
from modstore_server.models import (
    Entitlement,
    PlanTemplate,
    Transaction,
    User,
    UserPlan,
    VerificationCode,
    Wallet,
    get_session_factory,
)
from modstore_server.payment_fulfilment import FulfilContext, PlanFulfilStrategy


@pytest.fixture(autouse=True)
def _fund_personal_allowance(monkeypatch):
    monkeypatch.setenv("MODSTORE_PERSONAL_ALLOWANCE_BUDGET_CENTS", "100000")


def _personal_account(client):
    email = f"personal_{uuid.uuid4().hex[:12]}@example.test"
    with get_session_factory().begin() as session:
        session.add(
            VerificationCode(
                email=email,
                code="742963",
                expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
            )
        )
    registered = client.post(
        "/api/auth/register",
        json={
            "username": f"personal_{uuid.uuid4().hex[:12]}",
            "password": "personal-pass-12",
            "email": email,
            "verification_code": "742963",
        },
    ).json()
    headers = {"Authorization": f"Bearer {registered['access_token']}"}
    return registered["user"]["id"], headers


def test_personal_plan_activation_is_idempotent_and_grants_no_mods(client):
    user_id, headers = _personal_account(client)
    for _ in range(2):
        result = client.post("/api/account/personal-plan", headers=headers)
        assert result.status_code == 200, result.text
        assert result.json()["active_plan_id"] == "saas-personal-free"
        assert result.json()["desktop_access"] is True
    legacy_auth = client.get("/api/auth/me", headers=headers).json()
    assert legacy_auth["active_plan_id"] == "saas-personal-free"
    assert legacy_auth["desktop_access"] is False
    mods = client.get("/api/enterprise/entitled-mod-ids", headers=headers)
    assert mods.status_code == 200, mods.text
    assert mods.json()["mod_ids"] == []
    with get_session_factory()() as session:
        assert session.query(UserPlan).filter_by(user_id=user_id).count() == 1
        assert session.query(Wallet).filter_by(user_id=user_id).one().balance == 5
        credit = (
            session.query(Transaction)
            .filter_by(user_id=user_id, txn_type="account_license_quota")
            .one()
        )
        assert credit.amount == 5
        assert not session.query(User).filter_by(id=user_id).one().is_enterprise


def test_concurrent_personal_activation_credits_once(client):
    user_id, headers = _personal_account(client)
    barrier = Barrier(2)

    def activate(_):
        barrier.wait(timeout=10)
        return client.post("/api/account/personal-plan", headers=headers)

    with ThreadPoolExecutor(max_workers=2) as workers:
        responses = list(workers.map(activate, range(2)))
    assert [response.status_code for response in responses] == [200, 200]
    with get_session_factory()() as session:
        assert session.query(UserPlan).filter_by(user_id=user_id).count() == 1
        assert session.query(Wallet).filter_by(user_id=user_id).one().balance == 5
        assert session.query(Transaction).filter_by(user_id=user_id).one().amount == 5


@pytest.mark.parametrize("committed", [False, True])
def test_personal_activation_commit_failure_or_lost_ack_retries_atomically(
    client, monkeypatch, committed
):
    from modstore_server import account_api

    user_id, headers = _personal_account(client)
    factory = get_session_factory()

    class FailingCommit(Session):
        def commit(self):
            self.flush()
            if committed:
                super().commit()
            raise RuntimeError("synthetic commit failure")

    failing_factory = sessionmaker(bind=factory.kw["bind"], class_=FailingCommit)
    with monkeypatch.context() as scoped:
        scoped.setattr(account_api, "get_session_factory", lambda: failing_factory)
        with pytest.raises(RuntimeError, match="synthetic commit failure"):
            client.post("/api/account/personal-plan", headers=headers)
    with factory() as session:
        assert session.query(UserPlan).filter_by(user_id=user_id).count() == int(committed)
        assert session.query(Transaction).filter_by(user_id=user_id).count() == int(committed)
        wallet = session.query(Wallet).filter_by(user_id=user_id).first()
        assert (wallet.balance if wallet else 0) == (5 if committed else 0)
        user = session.get(User, user_id)
        assert user.account_state == ("active" if committed else "pending_plan")
    assert client.post("/api/account/personal-plan", headers=headers).status_code == 200
    with factory() as session:
        assert session.query(UserPlan).filter_by(user_id=user_id).count() == 1
        assert session.query(Wallet).filter_by(user_id=user_id).one().balance == 5
        assert session.query(Transaction).filter_by(user_id=user_id).one().amount == 5


@pytest.mark.parametrize("grant", ["saas-trial-30", "saas-permanent-starter", "legacy", "admin"])
def test_free_activation_preserves_existing_access_and_never_credits(client, grant):
    user_id, headers = _personal_account(client)
    with get_session_factory().begin() as session:
        user = session.get(User, user_id)
        if grant == "legacy":
            user.is_enterprise = True
        elif grant == "admin":
            user.is_admin = True
        else:
            # A historical active free row must not outrank an active paid grant.
            session.add_all(
                [
                    UserPlan(user_id=user_id, plan_id="saas-personal-free"),
                    UserPlan(user_id=user_id, plan_id=grant),
                ]
            )
    before = client.get("/api/auth/me", headers=headers).json()
    for _ in range(2):
        response = client.post("/api/account/personal-plan", headers=headers)
        assert response.status_code == 409, response.text
    assert client.get("/api/auth/me", headers=headers).json() == before
    with get_session_factory()() as session:
        assert session.query(Transaction).filter_by(user_id=user_id).count() == 0
        assert session.query(UserPlan).filter_by(user_id=user_id).count() == (
            0 if grant in {"legacy", "admin"} else 2
        )
        wallet = session.query(Wallet).filter_by(user_id=user_id).first()
        assert wallet is None or wallet.balance == 0


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
    account_catalog = client.get("/api/payment/account-plans").json()
    licenses = account_catalog["plans"]
    assert account_catalog["commercial_terms"]["customization_from_cents"] == 99900
    membership_ids = {row["id"] for row in memberships}
    license_ids = {row["id"] for row in licenses}
    expected_license_ids = {str(row["id"]) for row in ACCOUNT_LICENSE_PLANS}

    assert license_ids == expected_license_ids
    assert membership_ids.isdisjoint(license_ids)
    assert "plan_enterprise" in membership_ids
    assert "saas-trial-30" in license_ids

    expected_titles = {
        "saas-personal-free": "个人使用版",
        "saas-trial-30": "30 天全功能体验",
        "saas-permanent-standard": "XCAGI 软件买断",
    }
    expected_prices = {
        "saas-personal-free": 0.0,
        "saas-trial-30": 99.0,
        "saas-permanent-standard": 3000.0,
    }
    by_id = {row["id"]: row for row in licenses}
    assert {plan_id: by_id[plan_id]["name"] for plan_id in expected_titles} == expected_titles
    assert {plan_id: by_id[plan_id]["price"] for plan_id in expected_prices} == expected_prices

    public_copy = " ".join(
        " ".join(
            [
                str(row.get("name") or ""),
                str(row.get("description") or ""),
                str(row.get("badge") or ""),
                *[str(feature) for feature in row.get("features") or []],
            ]
        )
        for row in licenses
    )
    for prohibited in (
        "VIP / SVIP",
        "不代替账号授权",
        "桌面端账号授权",
        "永久账号授权",
        "永久授权 ·",
    ):
        assert prohibited not in public_copy


def test_java_plan_copy_migration_matches_public_catalog():
    migration = (
        Path(__file__).resolve().parent.parent
        / "java_payment_service"
        / "src"
        / "main"
        / "resources"
        / "db"
        / "migration"
        / "V19__simple_software_buyout.sql"
    ).read_text(encoding="utf-8")

    assert "saas-permanent-standard" in migration
    assert "XCAGI 软件买断" in migration
    assert "6800.00" in migration
    assert "DELETE" not in migration
    assert "UPDATE orders" not in migration
    assert "ON CONFLICT (id) DO UPDATE" in migration
    assert "永久授权 ·" not in migration
    assert "VIP / SVIP" not in migration
