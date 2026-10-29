"""Guarded auth reads only current durable grants; synthetic existing SQLite."""

from contextlib import contextmanager
from dataclasses import fields
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.auth_app_service import AuthApplicationService
from app.db.init_db import ensure_runtime_auth_bootstrap as validate_runtime_auth
from app.db.models import Permission, Role, Tenant, User, UserSession, role_permissions
from app.domain.shared_services.auth_service import AuthService
from app.utils.time import utc_now_naive


@pytest.fixture(params=[AuthApplicationService, AuthService], ids=["application", "domain"])
def service(request):
    return request.param()


@pytest.fixture
def auth_host(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///" + str(tmp_path / "auth-existing.sqlite"))
    for table in (
        User.__table__,
        UserSession.__table__,
        Permission.__table__,
        Role.__table__,
        Tenant.__table__,
        role_permissions,
    ):
        table.create(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory.begin() as db:
        codes = {
            code: Permission(code=code, name=code)
            for code in (
                "product.view",
                "dataset.read",
                "product.edit",
                "tenant.manage_roles",
                "admin.system_config",
                "etl.read",
            )
        }
        db.add_all(codes.values())
        admin = Role(name="admin", permissions=[codes["product.view"], codes["dataset.read"]])
        viewer = Role(name="viewer", permissions=[codes["product.view"]])
        owner_role = Role(name="tenant:7:member", permissions=[codes["etl.read"]])
        db.add_all([admin, viewer, owner_role])
        platform = User(
            username="synthetic-platform",
            password="unused",
            role="admin",
            tier="admin",
            is_active=True,
        )
        owner = User(
            username="synthetic-owner",
            password="unused",
            role=owner_role.name,
            tier="enterprise",
            tenant_id=7,
            market_user_id=71,
            is_active=True,
        )
        db.add_all([platform, owner])
        db.flush()
        db.add(Tenant(id=7, code="synthetic-seven", owner_user_id=owner.id))
        db.add(
            UserSession(
                session_id="synthetic-existing-session",
                user_id=owner.id,
                tenant_id=7,
                account_kind="enterprise",
                market_user_id=71,
                market_is_enterprise=True,
                expires_at=utc_now_naive() + timedelta(hours=1),
            )
        )
    monkeypatch.setenv("XCAGI_OWNED_SOURCE_PROFILE", "guarded-host-v1")
    monkeypatch.setattr("app.db.HostSessionLocal", factory)

    def no_bootstrap(*_args, **_kwargs):
        raise AssertionError("guarded permission lookup must not bootstrap or seed")

    monkeypatch.setattr("app.db.init_db.ensure_runtime_auth_bootstrap", no_bootstrap)
    yield SimpleNamespace(engine=engine, factory=factory, platform=platform, owner=owner)
    engine.dispose()


def images(host):
    with host.engine.connect() as db:
        return {
            "schema": list(
                db.exec_driver_sql("SELECT type,name,sql FROM sqlite_master ORDER BY type,name")
            ),
            **{
                table: list(db.exec_driver_sql("SELECT * FROM " + table))
                for table in (
                    "users",
                    "sessions",
                    "permissions",
                    "roles",
                    "tenants",
                    "role_permissions",
                )
            },
        }


def test_guarded_platform_admin_has_only_explicit_role_grants(service, auth_host):
    before = images(auth_host)
    assert set(service.get_user_permissions(auth_host.platform)) == {"product.view", "dataset.read"}
    assert service.has_permission(auth_host.platform, "product.view")
    assert not service.has_permission(auth_host.platform, "product.edit")
    assert not service.has_permission(auth_host.platform, "admin.system_config")
    assert not service.has_permission(auth_host.platform, "arbitrary.unlisted")
    assert images(auth_host) == before


def test_guarded_owner_does_not_receive_implicit_manage_roles(service, auth_host):
    before = images(auth_host)
    assert service.get_user_permissions(auth_host.owner) == ["etl.read"]
    assert not service.has_permission(auth_host.owner, "tenant.manage_roles")
    assert images(auth_host) == before


def test_guarded_permissions_use_current_user_and_current_grants(service, auth_host):
    stale = auth_host.platform
    with auth_host.factory.begin() as db:
        db.get(User, stale.id).role = "viewer"
    before = images(auth_host)
    assert stale.role == "admin"
    assert service.get_user_permissions(stale) == ["product.view"]
    assert not service.has_permission(stale, "dataset.read")
    assert images(auth_host) == before
    with auth_host.factory.begin() as db:
        db.query(Role).filter_by(name="viewer").one().permissions = []
    before = images(auth_host)
    assert service.get_user_permissions(stale) == []
    assert not service.has_permission(stale, "product.view")
    assert images(auth_host) == before


def test_guarded_missing_admin_role_does_not_fall_back(service, auth_host):
    with auth_host.factory.begin() as db:
        db.delete(db.query(Role).filter_by(name="admin").one())
    before = images(auth_host)
    assert service.get_user_permissions(auth_host.platform) == []
    assert not service.has_permission(auth_host.platform, "product.edit")
    assert images(auth_host) == before


@pytest.mark.parametrize("change", ["inactive", "missing"])
def test_guarded_account_unavailable_raises_instead_of_granting(service, auth_host, change):
    with auth_host.factory.begin() as db:
        user = db.get(User, auth_host.platform.id)
        if change == "inactive":
            user.is_active = False
        else:
            # Synthetic removal without loading unrelated ORM cascade tables.
            db.query(User).filter_by(id=user.id).delete(synchronize_session=False)
    before = images(auth_host)
    with pytest.raises(RuntimeError, match="account is unavailable"):
        service.get_user_permissions(auth_host.platform)
    with pytest.raises(RuntimeError, match="account is unavailable"):
        service.has_permission(auth_host.platform, "product.edit")
    assert images(auth_host) == before


def test_guarded_incomplete_schema_raises_without_repair(service, auth_host):
    with auth_host.engine.begin() as db:
        db.exec_driver_sql("ALTER TABLE roles RENAME COLUMN description TO missing_description")
    before = images(auth_host)
    with pytest.raises(RuntimeError, match="existing complete schema"):
        service.get_user_permissions(auth_host.platform)
    with pytest.raises(RuntimeError, match="existing complete schema"):
        service.has_permission(auth_host.platform, "product.edit")
    assert images(auth_host) == before


def test_guarded_query_failure_is_not_default_admin_grants(service, auth_host, monkeypatch):
    @contextmanager
    def unavailable():
        raise RuntimeError("synthetic host query unavailable")
        yield

    monkeypatch.setattr("app.db.session.get_host_db", unavailable)
    before = images(auth_host)
    with pytest.raises(RuntimeError, match="synthetic host query unavailable"):
        service.get_user_permissions(auth_host.platform)
    with pytest.raises(RuntimeError, match="synthetic host query unavailable"):
        service.has_permission(auth_host.platform, "product.edit")
    assert images(auth_host) == before


def test_default_profile_admin_and_owner_behavior_is_unchanged(service, auth_host, monkeypatch):
    monkeypatch.delenv("XCAGI_OWNED_SOURCE_PROFILE")
    bootstrap = []
    monkeypatch.setattr(
        "app.db.init_db.ensure_runtime_auth_bootstrap", lambda **kwargs: bootstrap.append(kwargs)
    )
    before = images(auth_host)
    assert "product.edit" in service.get_user_permissions(auth_host.platform)
    assert service.has_permission(auth_host.platform, "arbitrary.unlisted")
    assert "tenant.manage_roles" in service.get_user_permissions(auth_host.owner)
    assert images(auth_host) == before
    assert bool(bootstrap) is isinstance(service, AuthApplicationService)


@pytest.mark.parametrize("swallow_errors", [False, True])
def test_central_guarded_bootstrap_validates_without_creating_or_seeding(
    auth_host, monkeypatch, swallow_errors
):
    monkeypatch.setattr("app.db.get_host_engine", lambda: auth_host.engine)
    before = images(auth_host)
    validate_runtime_auth(
        auth_host.engine, database_url=str(auth_host.engine.url), swallow_errors=swallow_errors
    )
    assert images(auth_host) == before


def test_central_guarded_bootstrap_missing_schema_is_hard_failure(auth_host, monkeypatch):
    monkeypatch.setattr("app.db.get_host_engine", lambda: auth_host.engine)
    with auth_host.engine.begin() as db:
        db.exec_driver_sql(
            "ALTER TABLE sessions RENAME COLUMN entitled_mod_ids_json TO missing_mods"
        )
    before = images(auth_host)
    with pytest.raises(RuntimeError, match="existing complete schema"):
        validate_runtime_auth(swallow_errors=True)
    assert images(auth_host) == before


def test_central_guarded_bootstrap_rejects_foreign_engine_before_connection(
    auth_host, monkeypatch, tmp_path
):
    monkeypatch.setattr("app.db.get_host_engine", lambda: auth_host.engine)
    path = tmp_path / "must-not-create.sqlite"
    alternate = create_engine("sqlite:///" + str(path))
    before = images(auth_host)
    try:
        with pytest.raises(RuntimeError, match="must use the admitted HOST"):
            validate_runtime_auth(alternate, swallow_errors=True)
        with pytest.raises(RuntimeError, match="must use the admitted HOST"):
            validate_runtime_auth(database_url=str(alternate.url), swallow_errors=True)
        assert not path.exists()
        assert images(auth_host) == before
    finally:
        alternate.dispose()


def test_guarded_existing_session_metadata_is_read_only(auth_host):
    from app.application.session_account_meta import enrich_session_meta_with_tenant

    before = images(auth_host)
    result = enrich_session_meta_with_tenant("synthetic-existing-session", auth_host.owner)
    assert result["tenant_id"] == 7
    assert result["local_user_id"] == auth_host.owner.id
    assert images(auth_host) == before


@pytest.mark.parametrize(
    "change",
    ["unbound-session", "foreign-session", "unbound-user", "missing-tenant", "inactive-tenant"],
)
def test_guarded_session_tenant_mismatch_never_provisions_or_repairs(auth_host, change):
    from app.application.session_account_meta import enrich_session_meta_with_tenant

    with auth_host.factory.begin() as db:
        session = db.query(UserSession).filter_by(session_id="synthetic-existing-session").one()
        user = db.get(User, auth_host.owner.id)
        if change == "unbound-session":
            session.tenant_id = None
        elif change == "foreign-session":
            session.tenant_id = 8
        elif change == "unbound-user":
            user.tenant_id = session.tenant_id = None
        elif change == "missing-tenant":
            db.query(Tenant).filter_by(id=7).delete(synchronize_session=False)
        else:
            db.get(Tenant, 7).is_active = False
    before = images(auth_host)
    with pytest.raises(RuntimeError, match="guarded authentication"):
        enrich_session_meta_with_tenant("synthetic-existing-session", user)
    assert images(auth_host) == before


@pytest.fixture
def no_login_mutations(monkeypatch):
    """Trip every usual login enrollment/sync port, not just DB row changes."""

    def forbidden(*_args, **_kwargs):
        raise AssertionError("guarded login called a provisioning or refresh port")

    for module, names in (
        (
            "app.fastapi_routes.market_account",
            ["save_session_market_token", "fetch_market_membership_tier"],
        ),
        (
            "app.application.enterprise_login_flow",
            [
                "bind_tenant_for_login",
                "persist_session_account_meta",
                "_derive_and_heal_account_kind",
            ],
        ),
        (
            "app.application.tenant_rbac_app_service",
            ["accept_verified_tenant_invitation", "bind_verified_market_identity"],
        ),
        (
            "app.enterprise.mod_entitlements",
            [
                "refresh_session_entitlements_from_market",
                "persist_entitlements_to_session_row",
                "reload_enterprise_mods_after_login",
                "set_session_entitlements",
            ],
        ),
        ("app.enterprise.account_mod_binding", ["augment_entitled_client_mod_ids_for_username"]),
    ):
        for name in names:
            monkeypatch.setattr(module + "." + name, forbidden)
    return forbidden


def login_payload(host):
    return {"success": True, "user": {"id": host.owner.id, "username": host.owner.username}}


def market_payload(host):
    return {
        "success": True,
        "token": "synthetic-unused-token",
        "is_enterprise": True,
        "is_market_admin": False,
        "raw": {"user": {"id": 71, "username": host.owner.username}},
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("with_market,local_identity", [(False, 71), (True, 71), (False, None)])
async def test_guarded_existing_login_finalizer_is_read_only(
    auth_host, no_login_mutations, with_market, local_identity
):
    from fastapi import BackgroundTasks

    from app.application.enterprise_login_finalize import finalize_enterprise_login

    if local_identity is None:
        with auth_host.factory.begin() as db:
            db.get(User, auth_host.owner.id).market_user_id = None
            db.query(UserSession).filter_by(
                session_id="synthetic-existing-session"
            ).one().market_user_id = None
    before = images(auth_host)
    tasks = BackgroundTasks()
    result = login_payload(auth_host)
    actual = await finalize_enterprise_login(
        result=result,
        session_id="synthetic-existing-session",
        market_result=market_payload(auth_host) if with_market else None,
        account_kind="enterprise",
        username=auth_host.owner.username,
        sku="enterprise",
        background_tasks=tasks,
    )
    assert actual["success"] and actual["tenant_id"] == 7
    assert actual["market_user_id"] == local_identity
    assert "market_access_token" not in actual
    assert result == login_payload(auth_host)
    assert not tasks.tasks
    assert images(auth_host) == before


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change", ["invitation", "market-id", "market-name", "current-market-id", "unbound", "expired"]
)
async def test_guarded_finalizer_refuses_identity_change_without_repair(
    auth_host, no_login_mutations, change
):
    from fastapi import HTTPException

    from app.application.enterprise_login_finalize import finalize_enterprise_login

    market = market_payload(auth_host)
    if change == "market-id":
        market["raw"]["user"]["id"] = 99
    elif change == "market-name":
        market["raw"]["user"]["username"] = "foreign-owner"
    elif change == "current-market-id":
        with auth_host.factory.begin() as db:
            db.get(User, auth_host.owner.id).market_user_id = 99
    elif change in {"unbound", "expired"}:
        with auth_host.factory.begin() as db:
            session = db.query(UserSession).filter_by(session_id="synthetic-existing-session").one()
            if change == "unbound":
                session.tenant_id = None
            else:
                session.expires_at = utc_now_naive() - timedelta(seconds=1)
    before = images(auth_host)
    with pytest.raises((HTTPException, RuntimeError)) as failure:
        await finalize_enterprise_login(
            result=login_payload(auth_host),
            session_id="synthetic-existing-session",
            market_result=market,
            account_kind="enterprise",
            username=auth_host.owner.username,
            sku="enterprise",
            invitation_code="synthetic-invitation" if change == "invitation" else "",
        )
    if isinstance(failure.value, HTTPException):
        assert failure.value.status_code == 409
    assert images(auth_host) == before


@pytest.mark.parametrize(
    "method", ["authenticate", "create_session_for_username", "authenticate_oidc_user"]
)
def test_guarded_auth_bootstrap_error_precedes_session_issuance(auth_host, monkeypatch, method):
    service = AuthApplicationService()
    before = images(auth_host)

    def broken(*_args, **_kwargs):
        raise RuntimeError("synthetic bootstrap schema rejection")

    def forbidden(*_args, **_kwargs):
        raise AssertionError("session issuance reached after rejected bootstrap")

    monkeypatch.setattr("app.db.init_db.ensure_runtime_auth_bootstrap", broken)
    monkeypatch.setattr(service.session_manager, "create_session_with_db", forbidden)
    args = {
        "authenticate": (auth_host.owner.username, "unused"),
        "create_session_for_username": (auth_host.owner.username,),
        "authenticate_oidc_user": ({"preferred_username": auth_host.owner.username},),
    }[method]
    with pytest.raises(RuntimeError, match="synthetic bootstrap schema rejection"):
        getattr(service, method)(*args)
    assert images(auth_host) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ["oidc", "market"])
async def test_guarded_missing_identity_never_jit_creates(auth_host, monkeypatch, entry):
    from app.application.enterprise_login_flow import ensure_local_user_after_market
    from app.db.session import get_host_db

    monkeypatch.setattr("app.db.get_host_engine", lambda: auth_host.engine)
    monkeypatch.setattr("app.db.init_db.ensure_runtime_auth_bootstrap", validate_runtime_auth)
    monkeypatch.setattr("app.db.session.get_db", get_host_db)
    service = AuthApplicationService()

    def forbidden(*_args, **_kwargs):
        raise AssertionError("guarded missing account reached a provisioning port")

    monkeypatch.setattr(service.session_manager, "create_session_with_db", forbidden)
    before = images(auth_host)
    if entry == "oidc":
        result = service.authenticate_oidc_user({"preferred_username": "synthetic-missing"})
        assert result["success"] is False
        assert "existing account" in result["message"]
    else:
        result, response = await ensure_local_user_after_market(
            username="synthetic-missing",
            password=None,
            market_result=market_payload(auth_host),
            auth_app_service=service,
            jit_create_fn=forbidden,
            market_user_email_from_raw=forbidden,
        )
        assert result is None and response.status_code == 409
    assert images(auth_host) == before


@pytest.mark.asyncio
async def test_guarded_registration_refuses_before_any_dependency(auth_host):
    from app.fastapi_routes.domains.auth.registration import Registration

    def forbidden(*_args, **_kwargs):
        raise AssertionError("guarded registration reached an enrollment dependency")

    registration = Registration(**{field.name: forbidden for field in fields(Registration)})
    before = images(auth_host)
    response = await registration.register(None, {"username": "new", "password": "unused"})
    assert response.status_code == 409
    assert images(auth_host) == before
