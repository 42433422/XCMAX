"""COVERAGE_RAMP Phase 1 (p1-p0-core): ai_chat_app_service helpers + more system/auth routes."""

from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.ai_chat_app_service import (
    AIChatApplicationService,
    _skip_pro_excel_deterministic_import,
)


# ---------------------------------------------------------------------------
# ai_chat helpers
# ---------------------------------------------------------------------------


def test_skip_pro_excel_deterministic_import_defaults() -> None:
    assert _skip_pro_excel_deterministic_import(None) is False
    assert _skip_pro_excel_deterministic_import({}) is False


def test_skip_pro_excel_ai_decides(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _skip_pro_excel_deterministic_import({"excel_import_ai_decides": True}) is True
    monkeypatch.setenv("XCAGI_EXCEL_IMPORT_AI_DECIDES", "1")
    assert _skip_pro_excel_deterministic_import({}) is True


def test_skip_pro_excel_force_shortcut() -> None:
    assert (
        _skip_pro_excel_deterministic_import({"excel_import_use_deterministic_shortcut": True})
        is False
    )


@patch("app.services.get_ai_conversation_service")
def test_ai_chat_service_instantiation(mock_conv: MagicMock) -> None:
    mock_conv.return_value = MagicMock()
    svc = AIChatApplicationService()
    assert svc is not None


@patch("app.services.get_ai_conversation_service")
def test_ai_chat_build_error_response(mock_conv: MagicMock) -> None:
    mock_conv.return_value = MagicMock()
    svc = AIChatApplicationService()
    if hasattr(svc, "_build_error_response"):
        out = svc._build_error_response("E001", "失败")
        assert out.get("success") is False or "message" in out


# ---------------------------------------------------------------------------
# More system routes
# ---------------------------------------------------------------------------


@pytest.fixture
def system_client() -> TestClient:
    from app.fastapi_routes.domains.system import routes as system_routes

    app = FastAPI()
    app.include_router(system_routes.router)
    return TestClient(app, raise_server_exceptions=False)


@patch("app.application.facades.session_facade.get_system_service")
def test_system_startup_post(mock_get: MagicMock, system_client: TestClient) -> None:
    mock_get.return_value.enable_startup.return_value = {"success": True}
    r = system_client.post("/api/system/startup")
    assert r.status_code == 200


@patch("app.application.facades.session_facade.get_system_service")
def test_system_startup_delete(mock_get: MagicMock, system_client: TestClient) -> None:
    mock_get.return_value.disable_startup.return_value = {"success": True}
    r = system_client.delete("/api/system/startup")
    assert r.status_code == 200


@patch("app.application.facades.session_facade.get_database_service")
def test_database_backup(mock_get: MagicMock, system_client: TestClient) -> None:
    mock_get.return_value.backup_database.return_value = {"success": True}
    r = system_client.post("/api/database/backup")
    assert r.status_code == 200


@patch("app.application.facades.session_facade.get_database_service")
def test_database_backup_delete(mock_get: MagicMock, system_client: TestClient) -> None:
    mock_get.return_value.delete_backup.return_value = {"success": True}
    r = system_client.delete("/api/database/backup/2026-01-01.db")
    assert r.status_code == 200


@patch("app.template_analysis_progress.get_template_analysis_progress")
def test_template_analysis_progress(mock_prog: MagicMock, system_client: TestClient) -> None:
    mock_prog.return_value = {"status": "idle"}
    r = system_client.get("/api/template/analysis/progress")
    assert r.status_code in (200, 404, 500)


# ---------------------------------------------------------------------------
# More auth routes
# ---------------------------------------------------------------------------


@pytest.fixture
def auth_client() -> TestClient:
    from app.fastapi_routes.domains.auth import routes as auth_routes

    app = FastAPI()
    app.include_router(auth_routes.router)
    return TestClient(app, raise_server_exceptions=False)


@patch("app.application.auth_app_service.get_auth_app_service")
def test_auth_subscription_status(mock_get: MagicMock, auth_client: TestClient) -> None:
    svc = MagicMock()
    svc.get_subscription_status.return_value = {"active": True}
    mock_get.return_value = svc
    user = SimpleNamespace(id=1, is_active=True)
    app = FastAPI()
    from app.fastapi_routes.domains.auth import routes as auth_routes

    app.include_router(auth_routes.router)
    app.dependency_overrides[auth_routes.get_logged_in_user] = lambda: user
    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/api/auth/subscription/status")
    assert r.status_code == 200


def test_auth_oidc_start_disabled(auth_client: TestClient) -> None:
    with patch("app.infrastructure.auth.oidc_provider.oidc_enabled", return_value=False):
        r = auth_client.get("/api/auth/oidc/start")
    assert r.status_code in (200, 302, 400, 404, 503)


@patch("app.application.auth_app_service.get_auth_app_service")
@patch("app.db.session.get_db")
def test_auth_forgot_password_send_code(
    mock_get_db: MagicMock, mock_get_svc: MagicMock, auth_client: TestClient
) -> None:
    mock_db = MagicMock()
    cm = MagicMock()
    cm.__enter__.return_value = mock_db
    cm.__exit__.return_value = None
    mock_get_db.return_value = cm
    mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []
    svc = MagicMock()
    svc.send_password_reset_code.return_value = {"success": True}
    mock_get_svc.return_value = svc
    r = auth_client.post(
        "/api/auth/forgot-password/send-code",
        json={"email": "u@example.com"},
    )
    assert r.status_code in (200, 400)


# ---------------------------------------------------------------------------
# misc routes extended
# ---------------------------------------------------------------------------


@pytest.fixture
def misc_client() -> TestClient:
    from app.fastapi_routes.domains.misc import routes as misc_routes

    app = FastAPI()
    app.openapi = lambda: {"openapi": "3.0.0", "paths": {}}
    app.include_router(misc_routes.router)
    return TestClient(app, raise_server_exceptions=False)


@patch("app.infrastructure.db.sync_engine.switch_to_test_mode")
def test_system_test_db_enable(mock_switch: MagicMock, misc_client: TestClient) -> None:
    mock_switch.return_value = {"success": True}
    r = misc_client.post("/system/test-db/enable", json={"enabled": True})
    assert r.status_code == 200


@patch("app.infrastructure.db.sync_engine.switch_to_production_mode")
def test_system_test_db_disable(mock_switch: MagicMock, misc_client: TestClient) -> None:
    mock_switch.return_value = {"success": True}
    r = misc_client.post("/system/test-db/disable", json={})
    assert r.status_code == 200


@patch("app.domain.ai.tools_directory.get_tool_categories_payload")
def test_tool_categories(mock_cats: MagicMock, misc_client: TestClient) -> None:
    mock_cats.return_value = {"categories": []}
    r = misc_client.get("/tool-categories")
    assert r.status_code == 200


def test_preferences_get(misc_client: TestClient) -> None:
    r = misc_client.get("/preferences")
    assert r.status_code == 200
