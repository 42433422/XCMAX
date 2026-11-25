"""Verified trial deadlines constrain sessions and shared-tenant authorization."""

import json
from datetime import timedelta

import pytest

from app.application import tenant_subscription_app_service as subscriptions
from app.db.models.tenant import Tenant
from app.db.models.user import Session, User
from app.utils.time import utc_now_naive
from tests.test_routes.test_simple_software_purchase import STANDARD, notify
from tests.test_routes.test_simple_software_purchase import market_login as market_login
from tests.test_routes.test_simple_software_purchase import purchase as purchase


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy_session", [False, True])
async def test_trial_deadline_revokes_existing_session_and_business_permission(
    purchase, market_login, monkeypatch, legacy_session
):
    from fastapi import HTTPException
    from starlette.requests import Request

    from app.db.models.permission import Permission, Role
    from app.infrastructure.auth.dependencies import require_permission
    from app.infrastructure.session import session_manager

    _, sessions, _ = purchase
    manager = session_manager.SessionManager()
    original = manager.create_session(1)
    expires = utc_now_naive() + timedelta(hours=2)
    with sessions.begin() as db:
        role = Role(name="trial-operator", description="Trial test operator")
        role.permissions.append(Permission(code="elt.execute", name="Execute ELT"))
        db.add(role)
        db.get(User, 1).role = role.name
    assert (
        await market_login(
            "saas-trial-30",
            session_id=original["session_id"],
            active_plan_expires_at=expires.isoformat() + "Z",
        )
    )["success"]
    with sessions.begin() as db:
        row = db.query(Session).filter_by(session_id=original["session_id"]).one()
        if legacy_session:
            # A session issued before this fix must be checked without another login.
            row.expires_at = expires + timedelta(days=365)
            row.verified_trial_expires_at = None
            db.get(User, 1).account_tier = None
        else:
            assert row.expires_at == expires
            assert row.verified_trial_expires_at == expires
    request = Request(
        {"type": "http", "headers": [(b"x-session-id", original["session_id"].encode())]}
    )
    if legacy_session:
        assert manager.get_session_info(original["session_id"]) is None
    else:
        assert require_permission("elt.execute")(request).id == 1
    monkeypatch.setattr(session_manager, "utc_now_naive", lambda: expires)
    monkeypatch.setattr(subscriptions, "utc_now_naive", lambda: expires)
    assert manager.get_session_info(original["session_id"]) is None
    assert manager.validate_session(original["session_id"]) is None
    with pytest.raises(HTTPException) as denied:
        require_permission("elt.execute")(request)
    assert denied.value.status_code == 401


@pytest.mark.asyncio
async def test_repeated_trial_login_keeps_the_original_session_deadline(
    purchase, market_login, monkeypatch
):
    from app.infrastructure.session import session_manager

    _, sessions, _ = purchase
    manager = session_manager.SessionManager()
    now = utc_now_naive()
    expires = now + timedelta(hours=2)
    for offset in (0, 1):
        monkeypatch.setattr(session_manager, "utc_now_naive", lambda: now + timedelta(hours=offset))
        sid = manager.create_session(1)["session_id"]
        assert (
            await market_login(
                "saas-trial-30",
                session_id=sid,
                active_plan_expires_at=expires.isoformat() + "Z",
            )
        )["success"]
        with sessions() as db:
            row = db.query(Session).filter_by(session_id=sid).one()
            assert row.expires_at == row.verified_trial_expires_at == expires
            assert db.get(Tenant, 1).trial_expires_at == expires


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "grant", [STANDARD, "saas-permanent-ultra", "admin", "superadmin", "platform", "pro"]
)
async def test_trial_session_limit_preserves_permanent_and_existing_admin_grants(
    purchase, market_login, monkeypatch, grant
):
    from app.infrastructure.session import session_manager

    _, sessions, _ = purchase
    manager = session_manager.SessionManager()
    sid = manager.create_session(1)["session_id"]
    expires = utc_now_naive() + timedelta(hours=2)
    if grant.startswith("saas-"):
        assert (await market_login(grant, session_id=sid))["success"]
    else:
        with sessions.begin() as db:
            user = db.get(User, 1)
            user.tier = "admin" if grant == "platform" else "enterprise"
            user.role = grant if grant in {"admin", "superadmin"} else "user"
            user.account_tier = "pro" if grant == "pro" else "normal"
    assert subscriptions.apply_paid_plan_for_user(
        user_id=1,
        plan_id="saas-trial-30",
        sync_from_market=True,
        active_plan_expires_at=expires.isoformat() + "Z",
    )
    monkeypatch.setattr(session_manager, "utc_now_naive", lambda: expires + timedelta(seconds=1))
    assert manager.validate_session(sid).id == 1
    with sessions() as db:
        assert db.query(Session).filter_by(session_id=sid).one().expires_at > expires


@pytest.mark.asyncio
@pytest.mark.parametrize("permanent_first", [False, True])
async def test_trial_deadline_survives_a_shared_permanent_license_and_session_refresh(
    purchase, market_login, monkeypatch, permanent_first
):
    from app.infrastructure.session import session_manager

    _, sessions, _ = purchase
    manager = session_manager.SessionManager()
    with sessions.begin() as db:
        db.add(User(id=2, username="licensed-member", password="unused", tenant_id=1))
    if permanent_first:
        assert subscriptions.apply_paid_plan_for_user(user_id=2, plan_id=STANDARD)
    session_ids = [manager.create_session(uid)["session_id"] for uid in (1, 2)]
    expires = utc_now_naive() + timedelta(hours=2)
    assert (
        await market_login(
            "saas-trial-30",
            session_id=session_ids[0],
            active_plan_expires_at=expires.isoformat() + "Z",
        )
    )["success"]
    if not permanent_first:
        assert subscriptions.apply_paid_plan_for_user(user_id=2, plan_id=STANDARD)
    with sessions.begin() as db:
        trial_session = db.query(Session).filter_by(session_id=session_ids[0]).one()
        assert trial_session.verified_trial_expires_at == expires
        trial_session.expires_at = expires + timedelta(days=365)
    monkeypatch.setattr(session_manager, "utc_now_naive", lambda: expires + timedelta(seconds=1))
    assert manager.validate_session(session_ids[0]) is None
    assert manager.validate_session(session_ids[1]).id == 2
    with sessions() as db:
        assert db.get(Tenant, 1).plan_id == STANDARD
        assert db.get(User, 2).account_tier == "normal"
        assert all(
            row.expires_at > expires for row in db.query(Session).filter(Session.user_id == 2)
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["market", "payment", "unverified"])
async def test_only_verified_own_permanent_grant_clears_trial_evidence_without_extending_ttl(
    purchase, market_login, monkeypatch, source
):
    from app.infrastructure.session import session_manager

    client, sessions, _ = purchase
    manager = session_manager.SessionManager()
    sid = manager.create_session(1)["session_id"]
    expires = utc_now_naive() + timedelta(hours=2)
    expired_at = utc_now_naive() - timedelta(minutes=1)
    with sessions.begin() as db:
        db.add(Session(session_id="expired-token", user_id=1, expires_at=expired_at))
        shorter_ttl = db.query(Session).filter_by(session_id="purchase-session").one().expires_at
    assert (
        await market_login(
            "saas-trial-30", session_id=sid, active_plan_expires_at=expires.isoformat() + "Z"
        )
    )["success"]
    if source == "market":
        assert (await market_login(STANDARD, session_id=sid))["success"]
    elif source == "payment":
        response = client.post("/api/model-payment/checkout", json={"plan_id": STANDARD})
        assert response.status_code == 200, response.text
        assert notify(client, response.json()["data"]["order_id"]).text == "success"
    else:
        assert subscriptions.apply_paid_plan_for_user(user_id=1, plan_id=STANDARD)
    with sessions.begin() as db:
        rows = {row.session_id: row for row in db.query(Session).filter_by(user_id=1)}
        assert rows["expired-token"].expires_at == expired_at
        assert rows["purchase-session"].expires_at == shorter_ttl
        assert rows[sid].expires_at == expires
        assert all(
            row.verified_trial_expires_at == (expires if source == "unverified" else None)
            for row in rows.values()
        )
        rows[sid].expires_at = expires + timedelta(days=365)
    assert manager.validate_session("expired-token") is None
    monkeypatch.setattr(session_manager, "utc_now_naive", lambda: expires)
    user = manager.validate_session(sid)
    assert (user.id if user else None) == (None if source == "unverified" else 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ["actor", "mod", "elt", "mobile", "entitlements"])
async def test_trial_session_is_rechecked_by_existing_task_authorization(
    purchase, market_login, monkeypatch, entry
):
    from fastapi import HTTPException

    from app.application.elt_login_authorization import _active_session
    from app.enterprise import mod_entitlements
    from app.infrastructure.auth import agent_mod_scope, agent_principal
    from app.infrastructure.session import session_manager

    _, sessions, _ = purchase
    manager = session_manager.SessionManager()
    sid = manager.create_session(1)["session_id"]
    expires = utc_now_naive() + timedelta(hours=2)
    assert (
        await market_login(
            "saas-trial-30", session_id=sid, active_plan_expires_at=expires.isoformat() + "Z"
        )
    )["success"]
    with sessions.begin() as db:
        db.query(Session).filter_by(
            session_id=sid
        ).one().entitled_mod_ids_json = '["trial-fixture"]'
    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
    actor = agent_mod_scope.bind_agent_actor_scope(session_id=sid, user_id="1")
    mod = agent_mod_scope.bind_agent_mod_scope(session_id=sid, user_id="1", mod_id="trial-fixture")

    def authorized():
        if entry == "actor":
            return (
                agent_mod_scope.validate_actor_context(
                    {"_actor_authorization": actor, "user_id": "1", "tenant_id": "1"}
                )
                is None
            )
        if entry == "elt":
            return _active_session(sid) is not None
        if entry == "entitlements":
            return mod_entitlements.restore_entitlements_from_session_row(sid)
        try:
            if entry == "mobile":
                agent_principal._mobile_principal({"session_id": sid, "user_id": "1"})
            else:
                with agent_mod_scope.agent_mod_execution_scope(mod):
                    pass
            return True
        except (HTTPException, agent_mod_scope.AgentModAuthorizationError):
            return False

    try:
        assert authorized()
        with sessions.begin() as db:
            # Ordinary TTL refresh cannot replace the independently verified deadline.
            db.query(Session).filter_by(session_id=sid).one().expires_at = expires + timedelta(
                days=365
            )
        monkeypatch.setattr(session_manager, "utc_now_naive", lambda: expires)
        assert not authorized()
    finally:
        mod_entitlements.clear_session_entitlements()


@pytest.mark.asyncio
@pytest.mark.parametrize("other_state", ["active", "disabled", "personal"])
async def test_shorter_trial_login_does_not_shorten_another_members_verified_session(
    purchase, market_login, monkeypatch, other_state
):
    from app.infrastructure.session import session_manager

    _, sessions, _ = purchase
    manager = session_manager.SessionManager()
    first_expiry = utc_now_naive() + timedelta(hours=2)
    second_expiry = first_expiry + timedelta(days=1)
    with sessions.begin() as db:
        db.add(User(id=2, username="other-trial-member", password="unused", tenant_id=1))
    other = manager.create_session(2)["session_id"]
    assert subscriptions.apply_paid_plan_for_user(
        user_id=2,
        plan_id="saas-trial-30",
        sync_from_market=True,
        active_plan_expires_at=second_expiry.isoformat() + "Z",
        verified_account_sync=True,
    )
    current = manager.create_session(1)["session_id"]
    assert (
        await market_login(
            "saas-trial-30",
            session_id=current,
            active_plan_expires_at=first_expiry.isoformat() + "Z",
        )
    )["success"]
    with sessions.begin() as db:
        current_user = db.get(User, 1)
        if other_state == "disabled":
            current_user.is_active = False
        elif other_state == "personal":
            current_user.account_tier = "personal"
    monkeypatch.setattr(
        session_manager, "utc_now_naive", lambda: first_expiry + timedelta(seconds=1)
    )
    assert manager.validate_session(other).id == 2
    assert manager.validate_session(current) is None
    with sessions() as db:
        assert db.query(Session).filter_by(session_id=other).one().expires_at == second_expiry


@pytest.mark.asyncio
@pytest.mark.parametrize("unknown", [False, True])
@pytest.mark.parametrize("shared_tenant", [False, True])
async def test_trial_session_refresh_or_unknown_evidence_cannot_extend_access(
    purchase, market_login, monkeypatch, unknown, shared_tenant
):
    from app.infrastructure.session import session_manager

    _, sessions, _ = purchase
    manager = session_manager.SessionManager()
    expires = utc_now_naive() + timedelta(hours=2)
    if shared_tenant:
        with sessions.begin() as db:
            db.add(
                User(
                    id=2,
                    username="other-member",
                    password="unused",
                    tenant_id=1,
                    account_tier="normal",
                )
            )
    old = manager.create_session(1)["session_id"]
    assert (
        await market_login(
            "saas-trial-30", session_id=old, active_plan_expires_at=expires.isoformat() + "Z"
        )
    )["success"]
    with sessions.begin() as db:
        row = db.query(Session).filter_by(session_id=old).one()
        row.expires_at = expires + timedelta(days=365)
        if unknown:
            row.verified_trial_expires_at = None
    if unknown:
        assert manager.validate_session(old) is None
        new = manager.create_session(1)["session_id"]
        assert (
            await market_login(
                "saas-trial-30", session_id=new, active_plan_expires_at=expires.isoformat() + "Z"
            )
        )["success"]
        assert manager.validate_session(new).id == 1
        with sessions() as db:
            row = db.query(Session).filter_by(session_id=new).one()
            assert row.expires_at == row.verified_trial_expires_at == expires
    else:
        monkeypatch.setattr(session_manager, "utc_now_naive", lambda: expires)
        assert manager.validate_session(old) is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides",
    [
        {"token": ""},
        {"token": "xcagi-local-surface-audit-demo"},
        {"account_state": "pending_plan"},
        {"desktop_access": False},
    ],
)
async def test_unverified_trial_login_cannot_certify_a_session_deadline(
    purchase, market_login, overrides
):
    _, sessions, _ = purchase
    expires = utc_now_naive() + timedelta(days=1)
    result = await market_login(
        "saas-trial-30", active_plan_expires_at=expires.isoformat() + "Z", **overrides
    )
    assert result["success"] is False
    assert result["error"]["code"] == "TENANT_IDENTITY_REJECTED"
    with sessions() as db:
        assert db.query(Session).filter_by(session_id="purchase-session").one_or_none() is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fault",
    [
        None,
        "token",
        "demo",
        "pending",
        "desktop",
        "admin",
        "missing_id",
        "username",
        "bound_identity",
    ],
)
async def test_active_market_trial_registration_binds_identity_before_certifying_session(
    purchase, monkeypatch, fault
):
    from starlette.requests import Request

    from app.fastapi_routes import market_account
    from app.fastapi_routes.domains.auth.auth_routes import auth_register
    from app.infrastructure.session.session_manager import SessionManager

    _, sessions, _ = purchase
    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
    expires = utc_now_naive() + timedelta(days=2)
    profile = {
        "id": 141,
        "username": "trial-created",
        "is_enterprise": True,
        "account_state": "active",
        "active_plan_id": "saas-trial-30",
        "active_plan_expires_at": expires.isoformat() + "Z",
        "account_tier": "normal",
        "desktop_access": True,
    }
    if fault == "pending":
        profile["account_state"] = "pending_plan"
    elif fault == "desktop":
        profile["desktop_access"] = False
    elif fault == "admin":
        profile["is_admin"] = True
    elif fault == "missing_id":
        profile.pop("id")
    elif fault == "username":
        profile["username"] = "different-owner"
    elif fault == "bound_identity":
        with sessions.begin() as db:
            db.get(User, 1).market_user_id = 141

    async def upstream(method, path, **kwargs):
        if (method, path) == ("POST", "/api/auth/register"):
            if fault == "token":
                return {"ok": True}
            token = "xcagi-local-surface-audit-demo" if fault == "demo" else "registration-token"
            return {"access_token": token}
        assert (method, path) == ("GET", "/api/auth/me")
        return profile

    monkeypatch.setattr(market_account, "_proxy_json", upstream)
    response = await auth_register(
        Request({"type": "http", "method": "POST", "path": "/api/auth/register", "headers": []}),
        {"username": "trial-created", "password": "fixture-password"},
    )
    payload = json.loads(response.body)
    with sessions() as db:
        user = db.query(User).filter_by(username="trial-created").first()
        rows = db.query(Session).filter_by(user_id=user.id).all() if user else []
        if fault is not None:
            assert all(row.verified_trial_expires_at is None for row in rows)
            assert "session_id" not in payload
        else:
            assert response.status_code == 200, payload
            assert user.market_user_id == 141
            assert len(rows) == 1
            assert rows[0].expires_at == rows[0].verified_trial_expires_at == expires
            assert SessionManager().validate_session(payload["session_id"]).id == user.id


@pytest.mark.asyncio
async def test_unknown_trial_session_cannot_borrow_shared_tenant_permanent_license(
    purchase, market_login
):
    from app.infrastructure.session import session_manager

    _, sessions, _ = purchase
    manager = session_manager.SessionManager()
    with sessions.begin() as db:
        db.add(User(id=2, username="permanent-colleague", password="unused", tenant_id=1))
    assert subscriptions.apply_paid_plan_for_user(user_id=2, plan_id=STANDARD)
    sid = manager.create_session(1)["session_id"]
    expires = utc_now_naive() + timedelta(hours=2)
    assert (
        await market_login(
            "saas-trial-30", session_id=sid, active_plan_expires_at=expires.isoformat() + "Z"
        )
    )["success"]
    assert manager.validate_session(sid).id == 1
    with sessions.begin() as db:
        assert db.get(Tenant, 1).plan_id == STANDARD
        assert db.get(User, 1).account_license_plan_id == "saas-trial-30"
        assert db.get(User, 1).account_license_expires_at == expires
        row = db.query(Session).filter_by(session_id=sid).one()
        row.verified_trial_expires_at = None
        row.expires_at = expires + timedelta(days=365)
    assert manager.get_session_info(sid) is None
    assert manager.validate_session(sid) is None
    with sessions() as db:
        assert db.query(Session).filter_by(session_id=sid).one_or_none() is None


@pytest.mark.asyncio
@pytest.mark.parametrize("earlier", ["account", "session"])
async def test_trial_session_uses_earlier_account_or_verified_session_deadline(
    purchase, market_login, monkeypatch, earlier
):
    from app.infrastructure.session import session_manager

    _, sessions, _ = purchase
    manager = session_manager.SessionManager()
    sid = manager.create_session(1)["session_id"]
    now = utc_now_naive()
    shorter = now + timedelta(hours=1)
    longer = now + timedelta(hours=3)
    verified = longer if earlier == "account" else shorter
    assert (
        await market_login(
            "saas-trial-30", session_id=sid, active_plan_expires_at=verified.isoformat() + "Z"
        )
    )["success"]
    with sessions.begin() as db:
        user = db.get(User, 1)
        assert user.account_license_plan_id == "saas-trial-30"
        user.account_license_expires_at = shorter if earlier == "account" else longer
        row = db.query(Session).filter_by(session_id=sid).one()
        assert row.verified_trial_expires_at == verified
        row.expires_at = longer + timedelta(days=365)
    assert manager.validate_session(sid).id == 1
    monkeypatch.setattr(session_manager, "utc_now_naive", lambda: shorter + timedelta(seconds=1))
    assert manager.get_session_info(sid) is None
    assert manager.validate_session(sid) is None
