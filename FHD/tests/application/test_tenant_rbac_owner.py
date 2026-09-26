"""Tenant RBAC authority and market invitation behavior against the host database."""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.rbac_app_service import RbacAppService
from app.application.tenant_rbac_app_service import (
    TenantIdentityError,
    accept_verified_tenant_invitation,
    bind_verified_market_identity,
    create_tenant_invitation,
)
from app.db.models.permission import Permission
from app.db.models.tenant import Tenant
from app.db.models.tenant_invitation import TenantInvitation
from app.db.models.user import Session, User
from app.db.session import get_host_db
from app.errors import AppError
from app.fastapi_routes.rbac import router
from app.utils.time import utc_now_naive


def _market_id() -> int:
    return 1_000_000_000 + (uuid4().int % 1_000_000_000)


def _workspace(*, owned: bool = True) -> tuple[int, int, str, str]:
    username = f"owner-{uuid4().hex[:12]}"
    now = utc_now_naive()
    market_id = _market_id()
    sid = uuid4().hex
    with get_host_db() as db:
        owner = User(
            username=username, password="unused", role="user", tier="enterprise",
            market_user_id=market_id if owned else None, created_at=now,
        )
        db.add(owner)
        db.flush()
        tenant = Tenant(
            code=username, name="Customer", is_active=True, created_at=now,
            owner_user_id=owner.id if owned else None,
        )
        db.add(tenant)
        db.flush()
        owner.tenant_id = tenant.id
        db.add(Session(
            session_id=sid, user_id=owner.id, tenant_id=tenant.id,
            market_user_id=market_id if owned else None, market_is_enterprise=owned,
            account_kind="enterprise", expires_at=now + timedelta(days=1),
        ))
        return owner.id, tenant.id, username, sid


def _client(sid: str) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app, raise_server_exceptions=False)
    client.cookies.set("session_id", sid)
    return client


def test_legacy_owner_requires_live_market_identity_and_single_founder() -> None:
    owner_id, tenant_id, username, _sid = _workspace(owned=False)
    with get_host_db() as db:
        db.get(Tenant, tenant_id).created_at = db.get(User, owner_id).created_at + timedelta(seconds=1)
    bind_verified_market_identity(
        user_id=owner_id, market_user_id=_market_id(), market_username=username,
        market_is_enterprise=False, market_is_admin=False,
    )
    with get_host_db() as db:
        assert db.get(Tenant, tenant_id).owner_user_id is None
    market_id = _market_id()
    bind_verified_market_identity(
        user_id=owner_id, market_user_id=market_id, market_username=username,
        market_is_enterprise=True, market_is_admin=False,
    )
    with get_host_db() as db:
        assert db.get(Tenant, tenant_id).owner_user_id == owner_id
        assert db.get(User, owner_id).market_user_id == market_id

    another_id, another_tenant, another_name, _ = _workspace(owned=False)
    with get_host_db() as db:
        db.add(User(username=f"extra-{uuid4().hex}", password="unused", tenant_id=another_tenant))
    bind_verified_market_identity(
        user_id=another_id, market_user_id=_market_id(), market_username=another_name,
        market_is_enterprise=True, market_is_admin=False,
    )
    with get_host_db() as db:
        assert db.get(Tenant, another_tenant).owner_user_id is None


def test_owner_can_manage_tenant_roles_without_platform_privilege_or_cross_tenant_access() -> None:
    owner_id, tenant_id, _username, sid = _workspace()
    other_id, other_tenant, _other_name, _other_sid = _workspace()
    RbacAppService().seed_missing_permissions()
    client = _client(sid)
    assert client.get("/api/rbac/roles").status_code == 200
    assert client.get("/api/rbac/permissions").status_code == 200
    listed_codes = {item["code"] for item in client.get("/api/rbac/permissions").json()["data"]}
    assert "admin.manage_users" not in listed_codes
    assert "tenant.manage_roles" in listed_codes

    with get_host_db() as db:
        if db.query(Permission.id).filter(Permission.code == "etl.read").first() is None:
            db.add(Permission(code="etl.read", name="Read ETL", module="etl"))
    created = client.post("/api/rbac/roles", json={
        "name": "Auditor", "description": "", "permissions": ["etl.read"],
    })
    assert created.status_code == 201
    role_key = created.json()["data"]["key"]
    assert role_key.startswith(f"tenant:{tenant_id}:")
    assert client.post("/api/rbac/roles", json={
        "name": "Escalated", "permissions": ["admin.manage_users"],
    }).status_code == 403
    assert client.post("/api/rbac/permissions", json={
        "code": f"test.{uuid4().hex}", "name": "Platform",
    }).status_code == 403
    assert client.get(f"/api/rbac/users/{other_id}/permissions").status_code == 404
    assert client.put(f"/api/rbac/users/{other_id}/role", json={"role": role_key}).status_code == 404
    assert [row["id"] for row in client.get("/api/rbac/users").json()["data"]] == [owner_id]

    svc = RbacAppService()
    with pytest.raises(AppError):
        svc.assign_user_role(owner_id, "admin", tenant_id=tenant_id)
    with pytest.raises(AppError):
        svc.assign_user_role(owner_id, f"tenant:{other_tenant}:Auditor", tenant_id=tenant_id)


def test_invitation_binds_only_target_market_identity_once_and_never_moves_other_workspace() -> None:
    owner_id, tenant_id, _owner_name, _sid = _workspace()
    target = f"member-{uuid4().hex[:12]}"
    invite = create_tenant_invitation(inviter_user_id=owner_id, tenant_id=tenant_id, target_username=target)
    with get_host_db() as db:
        assert db.query(TenantInvitation).filter(TenantInvitation.token_sha256 == invite["code"]).first() is None
        member = User(username=target, password="unused", role="user", tier="enterprise")
        db.add(member)
        db.flush()
        member_id = member.id
        sid = uuid4().hex
        db.add(Session(session_id=sid, user_id=member_id, expires_at=utc_now_naive() + timedelta(days=1)))
    with pytest.raises(TenantIdentityError):
        accept_verified_tenant_invitation(
            user_id=member_id, market_user_id=_market_id(), market_username="wrong-account",
            code=invite["code"], session_id=sid,
        )
    market_id = _market_id()
    accepted = accept_verified_tenant_invitation(
        user_id=member_id, market_user_id=market_id, market_username=target,
        code=invite["code"], session_id=sid,
    )
    assert accepted["tenant_id"] == tenant_id
    with get_host_db() as db:
        member = db.get(User, member_id)
        assert (member.tenant_id, member.market_user_id, member.role) == (tenant_id, market_id, f"tenant:{tenant_id}:member")
        assert db.query(Session).filter(Session.session_id == sid).first().tenant_id == tenant_id
    assert _client(sid).get("/api/rbac/roles").status_code == 403
    with pytest.raises(TenantIdentityError):
        accept_verified_tenant_invitation(
            user_id=member_id, market_user_id=market_id, market_username=target,
            code=invite["code"], session_id=sid,
        )

    outsider_id, outsider_tenant, outsider_name, outsider_sid = _workspace()
    second = create_tenant_invitation(inviter_user_id=owner_id, tenant_id=tenant_id, target_username=outsider_name)
    with pytest.raises(TenantIdentityError):
        accept_verified_tenant_invitation(
            user_id=outsider_id, market_user_id=_market_id(), market_username=outsider_name,
            code=second["code"], session_id=outsider_sid,
        )
    with get_host_db() as db:
        assert db.get(User, outsider_id).tenant_id == outsider_tenant
        assert db.get(Tenant, outsider_tenant).owner_user_id == outsider_id
