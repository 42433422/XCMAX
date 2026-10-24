"""Authentication policy and lifecycle boundaries survive independent component assembly."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi import BackgroundTasks, FastAPI, Request, Response, UploadFile
from fastapi.routing import APIRoute
from sqlalchemy import Table, create_engine
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile as StarletteUploadFile

from app.application import account_security
from app.db.models.user import User
from app.fastapi_routes.domains.auth import routes
from app.fastapi_routes.domains.auth.account_security import AccountSecurity
from app.fastapi_routes.domains.auth.ports import Database
from app.utils.path_io import user_avatar_storage


def request(query: bytes = b"") -> Request:
    return Request(
        {"type": "http", "method": "GET", "path": "/", "headers": [], "query_string": query}
    )


def user(*, active: bool | None = True, enabled: bool = False) -> User:
    return User(
        id=71,
        username="fake-account",
        password="unused-fixture-hash",
        display_name="Fake account",
        email="fake@example.test",
        role="viewer",
        is_active=active,
        mfa_enabled=enabled,
        totp_secret="existing-secret",
        market_user_id=None,
    )


def fake_account(
    monkeypatch: pytest.MonkeyPatch, *, active: bool | None = True, enabled: bool = False
) -> tuple[User, MagicMock]:
    principal = user(active=active, enabled=enabled)
    db = MagicMock()
    db.get.return_value = principal
    monkeypatch.setattr(routes, "resolve_session_user", lambda _request: principal)
    monkeypatch.setattr("app.db.session.get_db", lambda: nullcontext(db))
    monkeypatch.setattr(
        "app.application.account_security.generate_totp_secret", lambda: "replacement-secret"
    )
    monkeypatch.setattr(
        "app.application.account_security.provisioning_uri", lambda *_args: "otpauth://fake"
    )
    monkeypatch.setattr("app.application.account_security.verify_totp", lambda *_args: True)
    return principal, db


def test_enabled_mfa_setup_preserves_verified_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    principal, db = fake_account(monkeypatch, enabled=True)
    response = routes.auth_mfa_setup(request())
    assert principal.totp_secret == "existing-secret"
    assert isinstance(response, Response) and response.status_code == 409
    db.commit.assert_not_called()


@pytest.mark.parametrize("operation", ["setup", "enable", "disable"])
def test_disabled_user_cannot_mutate_mfa(monkeypatch: pytest.MonkeyPatch, operation: str) -> None:
    principal, db = fake_account(monkeypatch, active=False, enabled=True)
    endpoint = getattr(routes, "auth_mfa_" + operation)
    response = (
        endpoint(request()) if operation == "setup" else endpoint(request(), {"code": "123456"})
    )
    assert isinstance(response, Response) and response.status_code == 403
    assert principal.totp_secret == "existing-secret"
    db.commit.assert_not_called()


def test_disabled_user_cannot_read_subscription(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_account(monkeypatch, active=False)
    service = MagicMock(return_value={"plan": "fake"})
    monkeypatch.setattr(
        "app.application.tenant_subscription_app_service.subscription_status_for_user", service
    )
    response = routes.auth_subscription_status(request())
    assert isinstance(response, Response) and response.status_code == 403
    service.assert_not_called()


@pytest.mark.parametrize("active", [None, True])
def test_mfa_rejects_only_explicitly_disabled_accounts(
    monkeypatch: pytest.MonkeyPatch, active: bool | None
) -> None:
    principal, db = fake_account(monkeypatch, active=active)
    response = routes.auth_mfa_setup(request())
    assert isinstance(response, dict) and response["success"] is True
    assert principal.totp_secret == "replacement-secret"
    db.commit.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("principal", [user(active=False), None])
async def test_session_validity_keeps_none_compatibility_and_blocks_disabled_users(
    monkeypatch: pytest.MonkeyPatch, principal: User | None
) -> None:
    monkeypatch.setattr(routes, "resolve_session_user", lambda _request: principal)
    monkeypatch.setattr(routes, "session_id_from_request", lambda _request: "fake-session")
    monkeypatch.setattr(routes, "_session_meta_for_response", lambda *_args: {})
    service = MagicMock()
    service.session_manager.get_session_info.return_value = {
        "session_id": "fake-session",
        "user_id": 71,
    }
    monkeypatch.setattr("app.application.auth_app_service.get_auth_app_service", lambda: service)
    monkeypatch.setattr(
        "app.application.desktop_admin_gate.assert_desktop_allows_session_id", lambda _sid: None
    )
    monkeypatch.setattr("app.mod_sdk.product_skus.resolve_product_sku", lambda: "generic")
    monkeypatch.setattr(
        "app.enterprise.mod_entitlements.get_cached_entitled_client_mod_ids", lambda: None
    )
    background = BackgroundTasks()
    response = await routes.auth_session_validate(request(), background)
    sync = AsyncMock(return_value=set())
    monkeypatch.setattr("app.enterprise.mod_entitlements.sync_entitlements_for_session", sync)
    await background()
    if principal is None:
        assert isinstance(response, dict) and response["valid"] is True
        assert len(background.tasks) == 1
        sync.assert_awaited_once_with("fake-session")
    else:
        assert isinstance(response, Response) and response.status_code == 403
        assert json.loads(bytes(response.body))["valid"] is False
        assert not background.tasks
        sync.assert_not_awaited()


@pytest.mark.asyncio
async def test_avatar_read_stops_at_size_limit_without_owning_upload_lifetime() -> None:
    class RecordingStream(BytesIO):
        def __init__(self) -> None:
            super().__init__(b"x" * (user_avatar_storage.MAX_AVATAR_BYTES + 4096))
            self.sizes: list[int | None] = []

        def read(self, size: int | None = -1) -> bytes:
            self.sizes.append(size)
            return super().read(size)

    stream = RecordingStream()
    upload = UploadFile(file=stream, filename="avatar.png")
    try:
        response = await routes.auth_profile_avatar_upload(file=upload, user=user())
        assert isinstance(response, Response) and response.status_code == 400
        assert stream.sizes == [user_avatar_storage.MAX_AVATAR_BYTES + 1]
        assert stream.tell() == user_avatar_storage.MAX_AVATAR_BYTES + 1
        assert not stream.closed
    finally:
        await upload.close()
    assert stream.closed


@pytest.mark.asyncio
async def test_oidc_real_finalizer_rejection_revokes_session_and_returns_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.application import enterprise_login_flow
    from app.application.tenant_rbac_app_service import TenantIdentityError

    reason = "verified tenant conflict /?&=#工作区"
    monkeypatch.setattr("app.infrastructure.auth.oidc_provider.oidc_enabled", lambda: True)
    monkeypatch.setattr("app.infrastructure.auth.oidc_provider.frontend_redirect_path", lambda: "/")
    monkeypatch.setattr(
        "app.infrastructure.auth.oidc_provider.verify_oidc_state", lambda _state: (True, None)
    )
    monkeypatch.setattr(
        "app.infrastructure.auth.oidc_provider.exchange_oidc_authorization",
        AsyncMock(
            return_value={"profile": {"sub": "fake-subject"}, "access_token": "fake-oidc-token"}
        ),
    )
    auth = MagicMock()
    auth.authenticate_oidc_user.return_value = {
        "success": True,
        "session_id": "fake-session",
        "user": {"id": 71, "username": "fake-account"},
    }
    monkeypatch.setattr("app.application.auth_app_service.get_auth_app_service", lambda: auth)
    monkeypatch.setattr("app.mod_sdk.product_skus.resolve_product_sku", lambda: "enterprise")
    monkeypatch.setattr(
        "app.fastapi_routes.market_account.login_market_for_oidc_profile",
        AsyncMock(
            return_value={
                "success": True,
                "token": "fake-market-token",
                "is_enterprise": True,
                "raw": {"user": {"id": 91, "username": "fake-account"}},
            }
        ),
    )
    monkeypatch.setattr("app.fastapi_routes.market_account.save_session_market_token", MagicMock())
    monkeypatch.setattr(
        "app.application.tenant_rbac_app_service.bind_verified_market_identity",
        MagicMock(side_effect=TenantIdentityError(reason)),
    )
    revoked = MagicMock()
    monkeypatch.setattr(enterprise_login_flow, "delete_session_quiet", revoked)
    response = await routes.auth_oidc_callback(request(b"code=fake&state=fake"))
    revoked.assert_called_once_with("fake-session")
    assert isinstance(response, Response) and response.status_code == 302
    assert parse_qs(urlsplit(response.headers["location"]).query) == {
        "oidc_error": ["OIDC_AUTH"],
        "oidc_message": [reason],
    }
    assert "set-cookie" not in response.headers


@pytest.fixture
def mfa_database(tmp_path: Path) -> Iterator[Database]:
    engine = create_engine(f"sqlite:///{tmp_path / 'mfa.sqlite3'}")
    table = User.__table__
    assert isinstance(table, Table)
    table.create(engine)
    with Session(engine) as db:
        db.add(user())
        db.commit()

    @contextmanager
    def database() -> Iterator[Session]:
        with Session(engine, expire_on_commit=False) as db:
            yield db
            db.commit()

    try:
        yield database
    finally:
        engine.dispose()


def isolated_security(database: Database) -> AccountSecurity:
    return AccountSecurity(
        resolve_user=lambda _request: user(),
        database=database,
        backend=lambda: MagicMock(),
        generate_secret=lambda: "JBSWY3DPEHPK3PXP",
        provisioning_uri=account_security.provisioning_uri,
        verify_totp=lambda secret, code: account_security.verify_totp(
            secret, code, at=1_700_000_000
        ),
    )


def test_independent_mfa_component_requires_verified_disable_before_reenrollment(
    mfa_database: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        routes,
        "resolve_session_user",
        MagicMock(side_effect=AssertionError("root must not be consulted")),
    )
    secrets = iter(["JBSWY3DPEHPK3PXP", "KRUGS4ZANFZSAYJA"])
    security = replace(isolated_security(mfa_database), generate_secret=lambda: next(secrets))
    enrolled = security.setup(request())
    assert isinstance(enrolled, dict)
    secret = enrolled["data"]["secret"]
    code = account_security.totp_now(secret, at=1_700_000_000)
    assert security.enable(request(), {"totp_code": code}) == {
        "success": True,
        "message": "MFA 已开启",
    }
    denied = security.setup(request())
    assert isinstance(denied, Response) and denied.status_code == 409
    wrong = security.disable(request(), {"code": "bad-code"})
    assert isinstance(wrong, Response) and wrong.status_code == 400
    with mfa_database() as db:
        current = db.get(User, 71)
        assert current is not None and current.mfa_enabled is True and current.totp_secret == secret
    assert security.disable(request(), {"code": code}) == {"success": True, "message": "MFA 已关闭"}
    with mfa_database() as db:
        current = db.get(User, 71)
        assert current is not None and current.mfa_enabled is False and current.totp_secret is None
    replacement = security.setup(request())
    assert isinstance(replacement, dict) and replacement["data"]["secret"] != secret
    with mfa_database() as db:
        current = db.get(User, 71)
        assert current is not None and current.mfa_enabled is False
        assert current.totp_secret == replacement["data"]["secret"]


@pytest.mark.parametrize("operation", ["setup", "enable", "disable"])
def test_mfa_rechecks_disabled_database_row_after_principal_resolution(
    mfa_database: Database, operation: str
) -> None:
    with mfa_database() as db:
        current = db.get(User, 71)
        assert current is not None
        current.is_active = False
    security = isolated_security(mfa_database)
    endpoint = getattr(security, operation)
    result = (
        endpoint(request()) if operation == "setup" else endpoint(request(), {"code": "123456"})
    )
    assert isinstance(result, Response) and result.status_code == 403
    with mfa_database() as db:
        current = db.get(User, 71)
        assert (
            current is not None
            and current.totp_secret == "existing-secret"
            and not current.mfa_enabled
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", "/api/users", None),
        ("GET", "/api/users/72", None),
        ("POST", "/api/users", {"username": "fake", "password": "fake123", "role": "admin"}),
        ("PUT", "/api/users/72", {"role": "admin"}),
        ("DELETE", "/api/users/72", None),
        ("POST", "/api/users/72/reset-password", {"password": "fake123"}),
    ],
)
async def test_real_admin_dependency_rejects_requests_before_directory_access(
    monkeypatch: pytest.MonkeyPatch, method: str, path: str, body: dict[str, str] | None
) -> None:
    principal = user()
    permission_service = MagicMock()
    permission_service.has_permission.return_value = False
    directory = MagicMock()
    monkeypatch.setattr(
        "app.infrastructure.auth.dependencies.resolve_session_user", lambda _request: principal
    )
    monkeypatch.setattr(
        "app.application.facades.session_facade.get_auth_service", lambda: permission_service
    )
    monkeypatch.setattr("app.application.get_user_app_service", directory)
    app = FastAPI()
    app.include_router(routes.router)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://auth.test"
    ) as client:
        response = await client.request(method, path, json=body)
    assert response.status_code == 403
    permission_service.has_permission.assert_called_once_with(principal, "admin.manage_users")
    directory.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("principal,status", [(None, 401), (user(active=False), 403)])
async def test_real_profile_dependency_blocks_missing_or_disabled_identity(
    monkeypatch: pytest.MonkeyPatch, principal: User | None, status: int
) -> None:
    monkeypatch.setattr(
        "app.infrastructure.auth.dependencies.resolve_session_user", lambda _request: principal
    )
    projection = MagicMock()
    monkeypatch.setattr(routes, "_user_public_dict", projection)
    app = FastAPI()
    app.include_router(routes.router)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://auth.test"
    ) as client:
        response = await client.get("/api/auth/profile")
    assert response.status_code == status
    projection.assert_not_called()


@pytest.mark.asyncio
async def test_enterprise_pending_registration_does_not_create_local_identity_or_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FHD_ALLOW_OPEN_REGISTRATION", "0")
    monkeypatch.setattr("app.mod_sdk.product_skus.resolve_product_sku", lambda: "enterprise")
    auth = MagicMock()
    directory = MagicMock()
    jit = MagicMock()
    provision = MagicMock()
    profile = MagicMock()
    monkeypatch.setattr("app.application.auth_app_service.get_auth_app_service", lambda: auth)
    monkeypatch.setattr("app.application.get_user_app_service", directory)
    monkeypatch.setattr(routes, "_jit_create_local_user_for_enterprise", jit)
    monkeypatch.setattr(routes, "_enrich_register_with_tenant", provision)
    monkeypatch.setattr(
        "app.application.account_registration.apply_account_profile_on_register", profile
    )
    market = AsyncMock(
        return_value={"success": True, "desktop_access": False, "token": "fake-market-token"}
    )
    monkeypatch.setattr("app.fastapi_routes.market_account.register_market_user", market)
    app = FastAPI()
    app.include_router(routes.router)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://auth.test"
    ) as client:
        response = await client.post(
            "/api/auth/register",
            json={
                "username": "fake",
                "password": "fake123",
                "email": "fake@example.test",
                "code": "123456",
                "role": "admin",
            },
        )
    assert response.status_code == 200
    assert response.json()["registered"] is True and response.json()["desktop_access"] is False
    assert "set-cookie" not in response.headers
    market.assert_awaited_once_with("fake", "fake123", "fake@example.test", "123456")
    auth.login.assert_not_called()
    for effect in (directory, jit, provision, profile):
        effect.assert_not_called()


@pytest.mark.asyncio
async def test_password_flow_forwards_verified_invitation_inputs_and_late_helpers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow = AsyncMock(return_value=({"success": True, "session_id": "fake-session"}, None))
    monkeypatch.setattr("app.application.enterprise_login_flow.run_market_first_login", flow)
    monkeypatch.setattr("app.mod_sdk.product_skus.resolve_product_sku", lambda: "enterprise")
    component = routes._credentials()
    auth = MagicMock()
    jit = MagicMock(return_value=True)
    email = MagicMock(return_value="late@example.test")
    cookie = MagicMock(side_effect=lambda response, _sid: response)
    monkeypatch.setattr("app.application.auth_app_service.get_auth_app_service", lambda: auth)
    monkeypatch.setattr(routes, "_jit_create_local_user_for_enterprise", jit)
    monkeypatch.setattr(routes, "_market_user_email_from_raw", email)
    monkeypatch.setattr(routes, "_attach_session_cookie", cookie)
    background = BackgroundTasks()
    await component.password(
        request(),
        {
            "username": "fake",
            "password": "fake123",
            "invitation_code": " verified-invite ",
            "totp_code": " 123456 ",
            "tenant_id": 999,
        },
        background,
    )
    kwargs = flow.call_args.kwargs
    assert kwargs["auth_app_service"] is auth and kwargs["background_tasks"] is background
    assert kwargs["invitation_code"] == "verified-invite" and kwargs["totp_code"] == "123456"
    assert "tenant_id" not in kwargs
    assert (
        kwargs["jit_create_fn"]("verified-name", "fake-password", "verified@example.test") is True
    )
    assert kwargs["market_user_email_from_raw"]({}) == "late@example.test"
    jit.assert_called_once_with("verified-name", "fake-password", "verified@example.test")
    email.assert_called_once_with({})
    assert cookie.call_args.args[1] == "fake-session"


@pytest.mark.asyncio
@pytest.mark.parametrize("allowed", [False, True])
async def test_local_registration_respects_late_gate_and_keeps_viewer_role(
    monkeypatch: pytest.MonkeyPatch, allowed: bool
) -> None:
    auth = MagicMock()
    auth.login.return_value = {"success": True, "session_id": "fake-session", "user": {"id": 71}}
    directory = MagicMock()
    directory.create_user.return_value = {"success": True}
    market = AsyncMock(return_value={"success": False})
    profile = MagicMock()
    monkeypatch.setattr("app.application.auth_app_service.get_auth_app_service", lambda: auth)
    monkeypatch.setattr("app.application.get_user_app_service", lambda: directory)
    monkeypatch.setattr("app.mod_sdk.product_skus.resolve_product_sku", lambda: "generic")
    monkeypatch.setattr("app.fastapi_routes.market_account.login_market_with_password", market)
    monkeypatch.setattr(
        "app.application.account_registration.apply_account_profile_on_register", profile
    )
    component = routes._registration()
    gate = MagicMock(return_value=allowed)
    enrich = MagicMock(side_effect=lambda **kwargs: kwargs["result"])
    monkeypatch.setattr(routes, "_open_registration_allowed", gate)
    monkeypatch.setattr(routes, "_enrich_register_with_tenant", enrich)
    result = await component.register(
        request(), {"username": "fake", "password": "fake123", "role": "admin", "tenant_id": 999}
    )
    assert isinstance(result, Response)
    gate.assert_called_once_with("generic")
    if not allowed:
        assert result.status_code == 403
        directory.create_user.assert_not_called()
        auth.login.assert_not_called()
        enrich.assert_not_called()
        market.assert_not_awaited()
        profile.assert_not_called()
    else:
        assert result.status_code == 200 and json.loads(bytes(result.body))["success"] is True
        assert directory.create_user.call_args.kwargs["role"] == "viewer"
        assert "tenant_id" not in directory.create_user.call_args.kwargs
        assert enrich.call_args.kwargs["result"]["user"]["id"] == 71
        assert "tenant_id" not in enrich.call_args.kwargs
        market.assert_awaited_once_with("fake", "fake123")
        profile.assert_called_once()


def test_session_projection_uses_helpers_replaced_after_assembly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    component = routes._sessions()
    principal = user()
    backend = MagicMock()
    backend.get_user_permissions.return_value = ["view"]
    gate = MagicMock(return_value=None)
    monkeypatch.setattr(routes, "resolve_session_user", lambda _request: principal)
    monkeypatch.setattr(routes, "session_id_from_request", lambda _request: "late-session")
    monkeypatch.setattr("app.application.auth_app_service.get_auth_app_service", lambda: backend)
    monkeypatch.setattr("app.application.desktop_admin_gate.assert_desktop_allows_session_id", gate)
    monkeypatch.setattr(
        routes, "_session_meta_for_response", lambda *_args: {"company_brand": "late-company"}
    )
    monkeypatch.setattr(routes, "_user_public_dict", lambda _user: {"id": "late-projection"})
    monkeypatch.setattr(routes, "_account_profile_fields", lambda *_args: {"tier": "late-tier"})
    result = component.current_user(request())
    assert isinstance(result, dict)
    assert result["data"]["user"] == {"id": "late-projection"}
    assert (
        result["data"]["company_brand"] == "late-company" and result["data"]["tier"] == "late-tier"
    )
    gate.assert_called_once_with("late-session")


@pytest.mark.asyncio
async def test_recovery_uses_late_helpers_and_only_syncs_after_market_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    component = routes._recovery()
    normalize = MagicMock(return_value="normalized@example.test")
    find = MagicMock(return_value=[user()])
    sync = MagicMock(return_value=1)
    market = AsyncMock(return_value={"success": False})
    monkeypatch.setattr(routes, "_normalize_auth_email", normalize)
    monkeypatch.setattr(routes, "_find_local_users_by_email", find)
    monkeypatch.setattr(routes, "_sync_local_password_for_email", sync)
    monkeypatch.setattr("app.fastapi_routes.market_account.reset_market_password_with_code", market)
    found = component.find_account({"email": "raw@example.test"})
    assert isinstance(found, dict) and found["data"]["usernames"] == ["fake-account"]
    find.assert_called_once_with("normalized@example.test")
    rejected = await component.reset_password(
        {"email": "raw@example.test", "code": "fake-code", "password": "fake123"}
    )
    assert isinstance(rejected, Response) and rejected.status_code == 400
    sync.assert_not_called()
    market.return_value = {"success": True}
    result = await component.reset_password(
        {"email": "raw@example.test", "code": "fake-code", "password": "fake123"}
    )
    assert isinstance(result, dict) and result["data"]["local_users_updated"] == 1
    sync.assert_called_once_with("normalized@example.test", "fake123")


@pytest.mark.asyncio
async def test_avatar_exact_limit_saves_and_http_oversize_closes_upload(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    principal, db = fake_account(monkeypatch)
    db.query.return_value.filter.return_value.first.return_value = principal
    monkeypatch.setattr(user_avatar_storage, "avatar_storage_dir", lambda: tmp_path)
    content = b"x" * user_avatar_storage.MAX_AVATAR_BYTES
    upload = UploadFile(file=BytesIO(content), filename="avatar.png")
    try:
        result = await routes.auth_profile_avatar_upload(file=upload, user=principal)
        assert isinstance(result, dict) and result["success"] is True
        assert (tmp_path / "71.png").read_bytes() == content
        assert principal.wx_avatar_url == user_avatar_storage.AVATAR_API_PATH
    finally:
        await upload.close()
    closed: list[StarletteUploadFile] = []
    original_close = StarletteUploadFile.close

    async def close(file: StarletteUploadFile) -> None:
        await original_close(file)
        closed.append(file)

    monkeypatch.setattr(StarletteUploadFile, "close", close)
    monkeypatch.setattr(
        "app.infrastructure.auth.dependencies.resolve_session_user", lambda _request: principal
    )
    app = FastAPI()
    app.include_router(routes.router)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://auth.test"
    ) as client:
        response = await client.post(
            "/api/auth/profile/avatar",
            files={"file": ("avatar.png", content + b"over", "image/png")},
        )
    assert response.status_code == 400 and response.json()["error"]["code"] == "INVALID_FILE"
    assert len(closed) == 1 and closed[0].file.closed
    assert (tmp_path / "71.png").read_bytes() == content


def test_all_public_handlers_can_be_remounted_by_compatibility_consumers() -> None:
    def endpoints_in(router):
        for route in router.routes:
            if isinstance(route, APIRoute):
                yield route
            elif hasattr(route, "original_router"):
                # FastAPI may retain included routers instead of flattening them.
                yield from endpoints_in(route.original_router)

    app = FastAPI()
    endpoints = list(endpoints_in(routes.router))
    assert len(endpoints) == 32
    for route in endpoints:
        app.add_api_route(
            route.path,
            getattr(routes, route.endpoint.__name__),
            methods=sorted(route.methods or []),
        )
    assert len(app.openapi()["paths"]) == len({route.path for route in endpoints})
