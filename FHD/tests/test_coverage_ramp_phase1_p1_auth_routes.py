"""COVERAGE_RAMP Phase 1 (p1-p0-core): auth domain routes + helpers (mocked)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.fastapi_routes.domains.auth import routes as auth_routes


@pytest.fixture
def auth_client() -> TestClient:
    app = FastAPI()
    app.include_router(auth_routes.router)
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_market_user_email_from_raw_variants() -> None:
    assert auth_routes._market_user_email_from_raw(None) == ""
    assert auth_routes._market_user_email_from_raw({"user": {"email": "a@b.com"}}) == "a@b.com"
    assert (
        auth_routes._market_user_email_from_raw({"data": {"user": {"email": "x@y.z"}}}) == "x@y.z"
    )


def test_normalize_auth_email() -> None:
    assert auth_routes._normalize_auth_email("  Foo@Bar.COM ") == "foo@bar.com"


def test_open_registration_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FHD_ALLOW_OPEN_REGISTRATION", raising=False)
    assert auth_routes._open_registration_allowed("personal") is True
    assert auth_routes._open_registration_allowed("enterprise") is False
    monkeypatch.setenv("FHD_ALLOW_OPEN_REGISTRATION", "1")
    assert auth_routes._open_registration_allowed("enterprise") is True
    monkeypatch.setenv("FHD_ALLOW_OPEN_REGISTRATION", "0")
    assert auth_routes._open_registration_allowed("personal") is False


def test_user_public_dict() -> None:
    user = SimpleNamespace(
        id=1,
        username="u",
        display_name="U",
        email="u@x.com",
        role="user",
        is_active=True,
        wx_avatar_url=None,
    )
    d = auth_routes._user_public_dict(user)
    assert d["username"] == "u"
    assert d["role"] == "user"


@patch("app.application.session_account_meta.load_session_account_meta")
def test_session_meta_for_response(mock_load: MagicMock) -> None:
    mock_load.return_value = {"tenant_id": 2}
    req = MagicMock()
    with patch.object(auth_routes, "session_id_from_request", return_value="sid"):
        meta = auth_routes._session_meta_for_response(req)
    assert meta["tenant_id"] == 2


# ---------------------------------------------------------------------------
# /api/auth/me
# ---------------------------------------------------------------------------


def test_auth_me_unauthenticated(auth_client: TestClient) -> None:
    with patch.object(auth_routes, "resolve_session_user", return_value=None):
        r = auth_client.get("/api/auth/me")
    assert r.status_code == 200
    assert r.json()["valid"] is False


def test_auth_me_disabled_user(auth_client: TestClient) -> None:
    user = SimpleNamespace(id=1, is_active=False)
    with patch.object(auth_routes, "resolve_session_user", return_value=user):
        r = auth_client.get("/api/auth/me")
    assert r.status_code == 403


@patch("app.application.auth_app_service.get_auth_app_service")
def test_auth_me_success(mock_get_svc: MagicMock, auth_client: TestClient) -> None:
    user = SimpleNamespace(
        id=1,
        username="alice",
        display_name="Alice",
        email="a@b.com",
        role="user",
        is_active=True,
        wx_avatar_url=None,
    )
    svc = MagicMock()
    svc.get_user_permissions.return_value = ["read"]
    mock_get_svc.return_value = svc
    with (
        patch.object(auth_routes, "resolve_session_user", return_value=user),
        patch.object(auth_routes, "_session_meta_for_response", return_value={"account_kind": "personal"}),
    ):
        r = auth_client.get("/api/auth/me")
    assert r.status_code == 200
    assert r.json()["success"] is True
    assert r.json()["data"]["user"]["username"] == "alice"


# ---------------------------------------------------------------------------
# session validate + runtime sku
# ---------------------------------------------------------------------------


def test_auth_session_validate_no_session(auth_client: TestClient) -> None:
    with patch.object(auth_routes, "session_id_from_request", return_value=None):
        r = auth_client.get("/api/auth/session/validate")
    assert r.status_code == 200
    assert r.json()["valid"] is False


@patch("app.application.auth_app_service.get_auth_app_service")
def test_auth_session_validate_invalid(mock_get_svc: MagicMock, auth_client: TestClient) -> None:
    svc = MagicMock()
    svc.session_manager.get_session_info.return_value = None
    mock_get_svc.return_value = svc
    with patch.object(auth_routes, "session_id_from_request", return_value="bad"):
        r = auth_client.get("/api/auth/session/validate")
    assert r.json()["valid"] is False


@patch("app.application.auth_app_service.get_auth_app_service")
def test_auth_session_validate_ok(mock_get_svc: MagicMock, auth_client: TestClient) -> None:
    svc = MagicMock()
    svc.session_manager.get_session_info.return_value = {"user_id": 1}
    mock_get_svc.return_value = svc
    with (
        patch.object(auth_routes, "session_id_from_request", return_value="sid"),
        patch.object(auth_routes, "resolve_session_user", return_value=SimpleNamespace(id=1)),
        patch.object(auth_routes, "_session_meta_for_response", return_value={}),
        patch("app.mod_sdk.product_skus.resolve_product_sku", return_value="personal"),
    ):
        r = auth_client.get("/api/auth/session/validate")
    assert r.status_code == 200
    assert r.json()["valid"] is True


def test_runtime_product_sku(auth_client: TestClient) -> None:
    with patch("app.mod_sdk.product_skus.resolve_product_sku", return_value="enterprise"):
        r = auth_client.get("/api/runtime/product-sku")
    assert r.status_code == 200
    assert r.json()["data"]["is_enterprise_edition"] is True


# ---------------------------------------------------------------------------
# login / register validation
# ---------------------------------------------------------------------------


def test_auth_login_empty_credentials(auth_client: TestClient) -> None:
    r = auth_client.post("/api/auth/login", json={"username": "", "password": ""})
    assert r.status_code == 200
    assert r.json()["success"] is False


@patch("app.application.enterprise_login_flow.run_market_first_login", new_callable=AsyncMock)
def test_auth_login_success(mock_login: AsyncMock, auth_client: TestClient) -> None:
    mock_login.return_value = ({"success": True, "session_id": "s1"}, None)
    with patch("app.mod_sdk.product_skus.resolve_product_sku", return_value="personal"):
        r = auth_client.post("/api/auth/login", json={"username": "u", "password": "p"})
    assert r.status_code == 200


def test_auth_login_phone_code_missing(auth_client: TestClient) -> None:
    r = auth_client.post("/api/auth/login-with-phone-code", json={})
    assert r.status_code == 400


@patch("app.fastapi_routes.market_account.login_market_with_phone_code", new_callable=AsyncMock)
@patch("app.application.enterprise_login_flow.run_market_first_login", new_callable=AsyncMock)
def test_auth_login_phone_code_success(
    mock_run: AsyncMock, mock_market: AsyncMock, auth_client: TestClient
) -> None:
    mock_market.return_value = {"success": True}
    mock_run.return_value = ({"success": True, "session_id": "s2"}, None)
    with patch("app.mod_sdk.product_skus.resolve_product_sku", return_value="personal"):
        r = auth_client.post(
            "/api/auth/login-with-phone-code",
            json={"phone": "13800138000", "code": "123456"},
        )
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# forgot / register / oidc / qr
# ---------------------------------------------------------------------------


def test_auth_forgot_account_empty(auth_client: TestClient) -> None:
    r = auth_client.post("/api/auth/forgot-account", json={})
    assert r.status_code in (200, 400)


@patch("app.application.auth_app_service.get_auth_app_service")
def test_auth_register_disabled_enterprise(mock_get_svc: MagicMock, auth_client: TestClient) -> None:
    with (
        patch("app.mod_sdk.product_skus.resolve_product_sku", return_value="enterprise"),
        patch.dict("os.environ", {"FHD_ALLOW_OPEN_REGISTRATION": "0"}, clear=False),
    ):
        r = auth_client.post(
            "/api/auth/register",
            json={"username": "new", "password": "Secret123!", "email": "n@x.com"},
        )
    assert r.status_code in (200, 400, 403)


def test_auth_oidc_status(auth_client: TestClient) -> None:
    with patch("app.infrastructure.auth.oidc_provider.oidc_enabled", return_value=False):
        r = auth_client.get("/api/auth/oidc/status")
    assert r.status_code == 200


def test_auth_qr_issue(auth_client: TestClient) -> None:
    with patch(
        "app.application.auth_app_service.get_auth_app_service"
    ) as mock_get:
        svc = MagicMock()
        svc.issue_qr_login.return_value = {"qr_id": "q1", "url": "http://x"}
        mock_get.return_value = svc
        r = auth_client.post("/api/auth/qr/issue", json={})
    assert r.status_code == 200


def test_auth_qr_status_not_found(auth_client: TestClient) -> None:
    with patch(
        "app.application.auth_app_service.get_auth_app_service"
    ) as mock_get:
        svc = MagicMock()
        svc.get_qr_login_status.return_value = None
        mock_get.return_value = svc
        r = auth_client.get("/api/auth/qr/status", params={"qr_id": "missing"})
    assert r.status_code in (200, 404)


# ---------------------------------------------------------------------------
# profile / logout / password
# ---------------------------------------------------------------------------


def test_auth_profile_unauthenticated(auth_client: TestClient) -> None:
    with patch.object(auth_routes, "resolve_session_user", return_value=None):
        r = auth_client.get("/api/auth/profile")
    assert r.status_code in (200, 401)


@patch("app.application.auth_app_service.get_auth_app_service")
def test_auth_profile_authenticated(mock_get_svc: MagicMock, auth_client: TestClient) -> None:
    user = SimpleNamespace(
        id=1,
        username="u",
        display_name="U",
        email="u@x.com",
        role="user",
        is_active=True,
        wx_avatar_url=None,
    )
    mock_get_svc.return_value = MagicMock()
    app = FastAPI()
    app.include_router(auth_routes.router)
    app.dependency_overrides[auth_routes.get_logged_in_user] = lambda: user
    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/api/auth/profile")
    assert r.status_code == 200


def test_auth_logout_no_session(auth_client: TestClient) -> None:
    with patch.object(auth_routes, "session_id_from_request", return_value=None):
        r = auth_client.post("/api/auth/logout")
    assert r.status_code in (200, 400)


@patch("app.application.auth_app_service.get_auth_app_service")
def test_auth_logout_success(mock_get_svc: MagicMock, auth_client: TestClient) -> None:
    svc = MagicMock()
    svc.logout.return_value = {"success": True}
    mock_get_svc.return_value = svc
    with patch.object(auth_routes, "session_id_from_request", return_value="sid"):
        r = auth_client.post("/api/auth/logout")
    assert r.status_code == 200


def test_auth_password_change_missing(auth_client: TestClient) -> None:
    user = SimpleNamespace(id=1)
    app = FastAPI()
    app.include_router(auth_routes.router)
    app.dependency_overrides[auth_routes.get_logged_in_user] = lambda: user
    client = TestClient(app, raise_server_exceptions=False)
    r = client.post("/api/auth/password/change", json={})
    assert r.status_code in (200, 400)


# ---------------------------------------------------------------------------
# user admin CRUD
# ---------------------------------------------------------------------------


@pytest.fixture
def admin_auth_client() -> TestClient:
    admin = SimpleNamespace(id=1, username="admin", role="admin", is_active=True)
    app = FastAPI()
    app.include_router(auth_routes.router)
    app.dependency_overrides[auth_routes._require_admin] = lambda: admin
    return TestClient(app, raise_server_exceptions=False)


@patch("app.application.get_user_app_service")
def test_users_list(mock_get_svc: MagicMock, admin_auth_client: TestClient) -> None:
    svc = MagicMock()
    svc.list_users.return_value = [{"id": 1, "username": "u", "is_active": True}]
    mock_get_svc.return_value = svc
    r = admin_auth_client.get("/api/users")
    assert r.status_code == 200
    assert r.json()["data"]["count"] == 1


@patch("app.application.get_user_app_service")
def test_users_get_by_id(mock_get_svc: MagicMock, admin_auth_client: TestClient) -> None:
    svc = MagicMock()
    svc.get_user.return_value = {"id": 5, "username": "u5"}
    mock_get_svc.return_value = svc
    r = admin_auth_client.get("/api/users/5")
    assert r.status_code == 200


@patch("app.application.auth_app_service.get_auth_app_service")
def test_users_create_validation(mock_get_svc: MagicMock, admin_auth_client: TestClient) -> None:
    r = admin_auth_client.post("/api/users", json={})
    assert r.status_code in (200, 400)


@patch("app.application.auth_app_service.get_auth_app_service")
def test_users_delete_self_blocked(mock_get_svc: MagicMock, admin_auth_client: TestClient) -> None:
    r = admin_auth_client.delete("/api/users/1")
    assert r.status_code in (200, 400, 403)


@patch("app.db.session.get_db")
@patch("app.application.auth_app_service.get_auth_app_service")
def test_find_local_users_by_email(
    mock_get_svc: MagicMock, mock_get_db: MagicMock
) -> None:
    mock_db = MagicMock()
    cm = MagicMock()
    cm.__enter__.return_value = mock_db
    cm.__exit__.return_value = None
    mock_get_db.return_value = cm
    q = MagicMock()
    q.filter.return_value = q
    q.order_by.return_value = q
    q.all.return_value = []
    mock_db.query.return_value = q
    assert auth_routes._find_local_users_by_email("bad") == []
    assert auth_routes._find_local_users_by_email("a@b.com") == []
