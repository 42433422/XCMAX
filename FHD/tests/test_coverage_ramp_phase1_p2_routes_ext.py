"""COVERAGE_RAMP Phase 1 round 2: domains routes ext (auth/conversation/misc/static/product compat)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Conversation compat (stream / batch / context)
# ---------------------------------------------------------------------------


@pytest.fixture
def conv_compat_client() -> TestClient:
    from app.fastapi_routes.domains.conversation import compat_routes

    app = FastAPI()
    app.include_router(compat_routes.router)
    return TestClient(app, raise_server_exceptions=False)


@patch(
    "app.fastapi_routes.domains.conversation.compat_routes.execute_compat_chat",
    new_callable=AsyncMock,
)
def test_ai_chat_unified_compat(mock_exec: AsyncMock, conv_compat_client: TestClient) -> None:
    mock_exec.return_value = {"success": True, "response": "ok"}
    r = conv_compat_client.post("/ai/chat", json={"message": "hi"})
    assert r.status_code == 200
    assert r.json()["success"] is True


@patch(
    "app.fastapi_routes.domains.conversation.compat_routes.execute_compat_chat_batch",
    new_callable=AsyncMock,
)
def test_ai_chat_batch_compat(mock_exec: AsyncMock, conv_compat_client: TestClient) -> None:
    mock_exec.return_value = {"success": True, "responses": []}
    r = conv_compat_client.post("/ai/chat/batch", json={"messages": ["a", "b"]})
    assert r.status_code == 200


def test_ai_context_get_clear(conv_compat_client: TestClient) -> None:
    r = conv_compat_client.get("/ai/context", params={"user_id": "u1"})
    assert r.status_code == 200
    assert r.json()["success"] is True
    r2 = conv_compat_client.post("/ai/context/clear", json={})
    assert r2.status_code == 200


@patch("app.middleware.chat_stream_limit.acquire_chat_stream_slot", return_value=False)
def test_ai_stream_limit_429(mock_slot: MagicMock, conv_compat_client: TestClient) -> None:
    r = conv_compat_client.post("/ai/chat/stream", json={"message": "hi"})
    assert r.status_code == 429
    assert r.json()["code"] == "CHAT_STREAM_LIMIT"


# ---------------------------------------------------------------------------
# Auth routes (extended)
# ---------------------------------------------------------------------------


@pytest.fixture
def auth_client() -> TestClient:
    from app.fastapi_routes.domains.auth import routes as auth_routes

    app = FastAPI()
    app.include_router(auth_routes.router)
    return TestClient(app, raise_server_exceptions=False)


@patch("app.application.auth_app_service.get_auth_app_service")
def test_auth_session_validate_no_session(mock_get: MagicMock, auth_client: TestClient) -> None:
    with patch.object(
        __import__("app.fastapi_routes.domains.auth.routes", fromlist=["routes"]),
        "session_id_from_request",
        return_value=None,
    ):
        r = auth_client.get("/api/auth/session/validate")
    assert r.status_code == 200
    body = r.json()
    assert body.get("valid") is False or body.get("success") is False


def test_auth_register_validation(auth_client: TestClient) -> None:
    r = auth_client.post("/api/auth/register", json={})
    assert r.status_code in (400, 422, 200)


def test_auth_login_missing_password(auth_client: TestClient) -> None:
    r = auth_client.post("/api/auth/login", json={"username": "u"})
    assert r.status_code == 200
    body = r.json()
    assert body.get("success") is False or "密码" in str(body.get("message", ""))


# ---------------------------------------------------------------------------
# Static routes (extended)
# ---------------------------------------------------------------------------


@pytest.fixture
def static_client(tmp_path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    from app.fastapi_routes.domains.static import routes as static_routes

    vue_dist = tmp_path / "templates" / "vue-dist"
    vue_dist.mkdir(parents=True)
    (vue_dist / "index.html").write_text("<html>spa</html>", encoding="utf-8")
    (vue_dist / "favicon.ico").write_bytes(b"\x00\x00")
    (vue_dist / "manifest.webmanifest").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(static_routes, "get_base_dir", lambda: str(tmp_path))
    app = FastAPI()
    app.include_router(static_routes.router)
    return TestClient(app, raise_server_exceptions=False)


def test_static_favicon(static_client: TestClient) -> None:
    r = static_client.get("/favicon.ico")
    assert r.status_code == 200
    assert "image" in r.headers.get("content-type", "")


# ---------------------------------------------------------------------------
# Misc routes (extended)
# ---------------------------------------------------------------------------


@pytest.fixture
def misc_client() -> TestClient:
    from app.fastapi_routes.domains.misc import routes as misc_routes

    app = FastAPI()
    app.openapi = lambda: {"openapi": "3.0.0"}
    app.include_router(misc_routes.router)
    return TestClient(app, raise_server_exceptions=False)


def test_preferences_get_post(misc_client: TestClient) -> None:
    r = misc_client.get("/preferences", params={"user_id": "u2"})
    assert r.status_code == 200
    assert r.json()["data"]["user_id"] == "u2"
    r2 = misc_client.post("/preferences", json={"theme": "dark"})
    assert r2.status_code == 200


def test_distillation_and_intent_packages(misc_client: TestClient) -> None:
    assert misc_client.get("/distillation/versions").json()["success"] is True
    assert misc_client.get("/intent-packages").json()["success"] is True
    assert misc_client.get("/intent_packages").json()["success"] is True


def test_tool_categories_list(misc_client: TestClient) -> None:
    r = misc_client.get("/tool-categories")
    assert r.status_code == 200


@patch("app.infrastructure.db.sync_engine.switch_to_test_mode")
@patch("app.infrastructure.db.sync_engine.get_db_status")
@patch("app.infrastructure.db.sync_engine.resolve_mode", return_value="production")
def test_system_test_db_enable(
    mock_mode: MagicMock, mock_status: MagicMock, mock_switch: MagicMock, misc_client: TestClient
) -> None:
    mock_switch.return_value = {"success": True}
    mock_status.return_value = {"mode": "test", "current_db_name": "test.db"}
    r = misc_client.post("/system/test-db/enable", json={"enabled": True})
    assert r.status_code == 200
    assert r.json()["success"] is True


# ---------------------------------------------------------------------------
# Product compat routes
# ---------------------------------------------------------------------------


@pytest.fixture
def product_compat_client() -> TestClient:
    from app.fastapi_routes.domains.product import compat_routes

    app = FastAPI()
    app.include_router(compat_routes.router)
    return TestClient(app, raise_server_exceptions=False)


@patch("app.bootstrap.get_products_service")
def test_product_compat_list(mock_get: MagicMock, product_compat_client: TestClient) -> None:
    mock_get.return_value.get_products.return_value = {"success": True, "data": []}
    r = product_compat_client.get("/products/list")
    assert r.status_code == 200


@patch("app.bootstrap.get_products_service")
def test_product_compat_units(mock_get: MagicMock, product_compat_client: TestClient) -> None:
    mock_get.return_value.get_product_names.return_value = {"success": True, "data": ["A"]}
    r = product_compat_client.get("/products/units")
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# Customer routes (extended, ERP facade disabled)
# ---------------------------------------------------------------------------


@pytest.fixture
def customer_client() -> TestClient:
    from app.fastapi_routes.domains.customer import routes as customer_routes

    app = FastAPI()
    app.include_router(customer_routes.router)
    return TestClient(app, raise_server_exceptions=False)


@patch("app.mod_sdk.erp_customers_facade.is_erp_customers_via_service_enabled", return_value=False)
@patch("app.fastapi_routes.domains.customer.routes._customer_find_by_id")
def test_customers_get_by_id(
    mock_find: MagicMock, _mock_erp: MagicMock, customer_client: TestClient
) -> None:
    mock_find.return_value = {"id": 3, "name": "乙公司", "unit_name": "乙公司"}
    r = customer_client.get("/customers/3")
    assert r.status_code == 200
    assert r.json()["success"] is True


@patch("app.mod_sdk.erp_customers_facade.is_erp_customers_via_service_enabled", return_value=False)
def test_customers_post_missing_name(_mock_erp: MagicMock, customer_client: TestClient) -> None:
    with patch("app.fastapi_routes.domains.customer.routes._customers_write_raise"):
        r = customer_client.post("/customers", json={})
    assert r.status_code == 400


@patch("app.mod_sdk.erp_customers_facade.is_erp_customers_via_service_enabled", return_value=False)
@patch("app.fastapi_routes.domains.customer.routes._customer_pg_insert")
def test_customers_post_ok(
    mock_insert: MagicMock, _mock_erp: MagicMock, customer_client: TestClient
) -> None:
    mock_insert.return_value = {"id": 5, "name": "丙公司"}
    with patch("app.fastapi_routes.domains.customer.routes._customers_write_raise"):
        r = customer_client.post(
            "/customers",
            json={"name": "丙公司", "contact_person": "李"},
        )
    assert r.status_code == 200
    assert r.json()["data"]["id"] == 5


# ---------------------------------------------------------------------------
# System routes (extended)
# ---------------------------------------------------------------------------


@pytest.fixture
def system_client() -> TestClient:
    from app.fastapi_routes.domains.system import routes as system_routes

    app = FastAPI()
    app.include_router(system_routes.router)
    return TestClient(app, raise_server_exceptions=False)


@patch("app.application.facades.session_facade.get_system_service")
def test_system_health_and_version(mock_get: MagicMock, system_client: TestClient) -> None:
    mock_get.return_value.get_system_info.return_value = {"version": "10.0.0"}
    r = system_client.get("/api/system/info")
    assert r.status_code == 200
    assert r.json()["data"]["version"] == "10.0.0"


@patch("app.application.facades.session_facade.get_database_service")
def test_database_backup_create(mock_get: MagicMock, system_client: TestClient) -> None:
    mock_get.return_value.backup_database.return_value = {
        "success": True,
        "data": {"path": "/tmp/bak"},
    }
    r = system_client.post("/api/database/backup")
    assert r.status_code == 200
    assert r.json()["success"] is True
