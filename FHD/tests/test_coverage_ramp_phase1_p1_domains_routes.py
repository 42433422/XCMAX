"""COVERAGE_RAMP Phase 1 (p1-p0-core): system/product/excel/conversation/shipment/misc routes."""

from __future__ import annotations

import io
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.agent_orchestrator import InMemoryAgentRunRepository

# ---------------------------------------------------------------------------
# System routes
# ---------------------------------------------------------------------------


@pytest.fixture
def system_client() -> TestClient:
    from app.fastapi_routes.domains.system import routes as system_routes

    app = FastAPI()
    app.include_router(system_routes.router)
    return TestClient(app, raise_server_exceptions=False)


def test_system_config_get(system_client: TestClient) -> None:
    r = system_client.get("/api/system/config")
    assert r.status_code == 200
    assert r.json()["success"] is True


@patch("app.application.facades.session_facade.get_system_service")
def test_system_info_get(mock_get: MagicMock, system_client: TestClient) -> None:
    mock_get.return_value.get_system_info.return_value = {"version": "10.0.0"}
    r = system_client.get("/api/system/info")
    assert r.status_code == 200
    assert r.json()["data"]["version"] == "10.0.0"


@patch("app.application.facades.session_facade.get_system_service")
def test_system_printer_get(mock_get: MagicMock, system_client: TestClient) -> None:
    mock_get.return_value.get_printer_config.return_value = {"name": "HP"}
    r = system_client.get("/api/system/printer")
    assert r.status_code == 200


def test_system_printer_post_empty(system_client: TestClient) -> None:
    r = system_client.post("/api/system/printer", json={})
    assert r.status_code == 400


@patch("app.application.facades.session_facade.get_system_service")
def test_system_printer_post_ok(mock_get: MagicMock, system_client: TestClient) -> None:
    mock_get.return_value.set_default_printer.return_value = {"success": True}
    r = system_client.post("/api/system/printer", json={"printer_name": "HP"})
    assert r.status_code == 200


@patch("app.application.facades.session_facade.get_system_service")
def test_system_startup_get(mock_get: MagicMock, system_client: TestClient) -> None:
    mock_get.return_value.get_startup_config.return_value = {"enabled": False}
    r = system_client.get("/api/system/startup")
    assert r.status_code == 200


@patch("app.application.facades.session_facade.get_database_service")
def test_database_backups_list(mock_get: MagicMock, system_client: TestClient) -> None:
    mock_get.return_value.list_backups.return_value = {"success": True, "data": []}
    r = system_client.get("/api/database/backups")
    assert r.status_code == 200


def test_database_restore_missing_file(system_client: TestClient) -> None:
    r = system_client.post("/api/database/restore", json={})
    assert r.status_code == 400


@patch("app.utils.performance_initializer.get_performance_optimizer")
def test_performance_status_uninitialized(mock_get: MagicMock, system_client: TestClient) -> None:
    opt = MagicMock()
    opt._initialized = False
    mock_get.return_value = opt
    r = system_client.get("/api/performance/status")
    assert r.status_code == 503


# ---------------------------------------------------------------------------
# Product routes
# ---------------------------------------------------------------------------


@pytest.fixture
def product_client() -> TestClient:
    from app.fastapi_routes.domains.product import routes as product_routes

    app = FastAPI()
    app.include_router(product_routes.router)
    return TestClient(app, raise_server_exceptions=False)


@patch("app.bootstrap.get_products_service")
def test_products_search(mock_get: MagicMock, product_client: TestClient) -> None:
    mock_get.return_value.get_products.return_value = {"success": True, "data": []}
    r = product_client.get("/api/products/search", params={"keyword": "x"})
    assert r.status_code == 200


@patch("app.bootstrap.get_products_service")
def test_products_product_names(mock_get: MagicMock, product_client: TestClient) -> None:
    mock_get.return_value.get_product_names.return_value = {"success": True, "data": ["A"]}
    r = product_client.get("/api/products/product_names")
    assert r.status_code == 200


@patch("app.bootstrap.get_products_service")
def test_products_batch_empty(mock_get: MagicMock, product_client: TestClient) -> None:
    r = product_client.post("/api/products/batch", json={"products": []})
    assert r.status_code == 400


@patch("app.bootstrap.get_products_service")
def test_products_update(mock_get: MagicMock, product_client: TestClient) -> None:
    mock_get.return_value.update_product.return_value = {"success": True}
    r = product_client.put("/api/products/1", json={"name": "N"})
    assert r.status_code == 200


@patch("app.bootstrap.get_products_service")
def test_products_delete(mock_get: MagicMock, product_client: TestClient) -> None:
    mock_get.return_value.delete_product.return_value = {"success": True}
    r = product_client.delete("/api/products/9")
    assert r.status_code == 200


def test_products_import_price_list_no_file(product_client: TestClient) -> None:
    r = product_client.post("/api/products/import/price-list-template")
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# Excel routes
# ---------------------------------------------------------------------------


@pytest.fixture
def excel_client() -> TestClient:
    from app.fastapi_routes.domains.excel import routes as excel_routes

    app = FastAPI()
    app.include_router(excel_routes.router)
    return TestClient(app, raise_server_exceptions=False)


def test_ai_parse_single_empty(excel_client: TestClient) -> None:
    r = excel_client.post("/api/ai/parse-single", json={"text": ""})
    assert r.status_code == 400


@patch("app.application.facades.excel_facade.get_ai_product_parser")
def test_ai_parse_single_ok(mock_get: MagicMock, excel_client: TestClient) -> None:
    mock_get.return_value.parse_single.return_value = {"success": True, "data": {}}
    r = excel_client.post("/api/ai/parse-single", json={"text": "产品A 10kg"})
    assert r.status_code == 200


def test_ai_parse_products_empty(excel_client: TestClient) -> None:
    r = excel_client.post("/api/ai/parse-products", json={"texts": []})
    assert r.status_code == 400


@patch("app.application.facades.excel_facade.get_ai_product_parser")
def test_ai_parse_products_ok(mock_get: MagicMock, excel_client: TestClient) -> None:
    mock_get.return_value.parse_batch.return_value = {"success": True, "data": []}
    r = excel_client.post("/api/ai/parse-products", json={"texts": ["a", "b"]})
    assert r.status_code == 200


@patch("app.application.facades.conversation_facade.get_data_analysis_service")
def test_ai_analyze_query_only(mock_get: MagicMock, excel_client: TestClient) -> None:
    r = excel_client.post("/api/ai/analyze", data={"query": "销量趋势"})
    assert r.status_code == 200
    assert r.json()["success"] is True


# ---------------------------------------------------------------------------
# Conversation routes
# ---------------------------------------------------------------------------


@pytest.fixture
def conversation_client() -> TestClient:
    from app.fastapi_routes.domains.conversation import routes as conv_routes

    app = FastAPI()
    app.include_router(conv_routes.router)
    return TestClient(app, raise_server_exceptions=False)


@patch("app.application.facades.conversation_facade.get_conversation_service")
def test_conversations_get(mock_get: MagicMock, conversation_client: TestClient) -> None:
    svc = MagicMock()
    svc.get_session_messages.return_value = []
    svc.get_sessions.return_value = []
    mock_get.return_value = svc
    r = conversation_client.get("/api/conversations/s1")
    assert r.status_code == 200


@patch("app.application.facades.conversation_facade.get_conversation_service")
def test_conversations_delete(mock_get: MagicMock, conversation_client: TestClient) -> None:
    mock_get.return_value.delete_session.return_value = True
    r = conversation_client.delete("/api/conversations/s1")
    assert r.status_code == 200
    assert r.json()["success"] is True


@patch("app.application.facades.conversation_facade.get_conversation_service")
def test_conversations_title(mock_get: MagicMock, conversation_client: TestClient) -> None:
    mock_get.return_value.update_session_title.return_value = True
    r = conversation_client.put("/api/conversations/s1/title", json={"title": "新标题"})
    assert r.status_code == 200


def test_ai_message_save_validation(conversation_client: TestClient) -> None:
    r = conversation_client.post("/api/ai/message/save", json={})
    assert r.status_code == 400


@patch("app.application.facades.conversation_facade.get_conversation_service")
def test_ai_message_save_ok(mock_get: MagicMock, conversation_client: TestClient) -> None:
    mock_get.return_value.save_message.return_value = 99
    r = conversation_client.post(
        "/api/ai/message/save",
        json={
            "session_id": "s1",
            "role": "user",
            "content": "hi",
            "user_id": 1,
        },
    )
    assert r.status_code == 200
    assert r.json()["message_id"] == 99


@patch("app.application.facades.conversation_facade.get_conversation_service")
def test_ai_message_save_attaches_agent_run(
    mock_get: MagicMock, conversation_client: TestClient
) -> None:
    repo = InMemoryAgentRunRepository()
    mock_get.return_value.save_message.return_value = 99
    with patch(
        "app.application.agent_orchestrator.chat_trace.get_agent_run_repository",
        return_value=repo,
    ):
        r = conversation_client.post(
            "/api/ai/message/save",
            json={
                "session_id": "s1",
                "role": "bot",
                "content": "hi",
                "user_id": 1,
                "intent": "smalltalk",
            },
        )

    assert r.status_code == 200
    body = r.json()
    run_id = body["run_id"]
    assert body["agent_run_id"] == run_id
    run = repo.get(run_id)
    assert run is not None
    assert run.user_id == "1"
    assert run.intent == "conversation_message_save"
    assert run.metadata["channel"] == "ai_message_save"
    assert run.metadata["runtime_context"]["route"] == "/api/ai/message/save"
    assert run.metadata["runtime_context"]["request"]["role"] == "bot"
    assert run.metadata["runtime_context"]["request"]["content_preview"] == "hi"


def test_ai_message_save_bot_role_normalized(
    conversation_client: TestClient,
) -> None:
    with patch(
        "app.application.facades.conversation_facade.get_conversation_service"
    ) as mock_get:
        mock_get.return_value.save_message.return_value = 1
        r = conversation_client.post(
            "/api/ai/message/save",
            json={"session_id": "s", "role": "bot", "content": "ok"},
        )
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# Shipment / approval workflow routes
# ---------------------------------------------------------------------------


@pytest.fixture
def shipment_client() -> TestClient:
    from app.fastapi_routes.domains.shipment import routes as shipment_routes

    app = FastAPI()
    app.include_router(shipment_routes.router)
    return TestClient(app, raise_server_exceptions=False)


def test_ai_approval_pending(shipment_client: TestClient) -> None:
    r = shipment_client.get("/api/ai/approval/pending")
    assert r.status_code == 200
    assert "pending_approvals" in r.json()["data"]


def test_ai_config_approval_get(shipment_client: TestClient) -> None:
    r = shipment_client.get("/api/ai/config/approval")
    assert r.status_code == 200
    assert "enabled" in r.json()


def test_ai_approval_request_missing_ids(shipment_client: TestClient) -> None:
    r = shipment_client.post("/api/ai/approval/request", json={})
    assert r.status_code == 400


def test_ai_approval_request_create(shipment_client: TestClient) -> None:
    r = shipment_client.post(
        "/api/ai/approval/request",
        json={"plan_id": "p1", "node_id": "n1", "tool_id": "t1", "action": "run"},
    )
    assert r.status_code == 200
    assert r.json()["success"] is True


def test_ai_approval_approve_missing(shipment_client: TestClient) -> None:
    r = shipment_client.post("/api/ai/approval/approve", json={})
    assert r.status_code == 400


def test_ai_approval_reject_missing(shipment_client: TestClient) -> None:
    r = shipment_client.post("/api/ai/approval/reject", json={})
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# Admin audit routes
# ---------------------------------------------------------------------------


@pytest.fixture
def audit_client() -> TestClient:
    from app.fastapi_routes.domains.admin_audit import routes as audit_routes

    admin = SimpleNamespace(id=1, username="admin", role="admin")
    app = FastAPI()
    app.include_router(audit_routes.router)
    app.dependency_overrides[audit_routes._require_admin_user] = lambda: admin
    return TestClient(app, raise_server_exceptions=False)


@patch("app.application.audit_log_reader.list_audit_log_entries")
def test_admin_audit_logs_json(mock_list: MagicMock, audit_client: TestClient) -> None:
    mock_list.return_value = {"entries": [], "total": 0}
    r = audit_client.get("/api/admin/audit-logs")
    assert r.status_code == 200
    assert r.json()["success"] is True


@patch("app.application.audit_log_reader.export_audit_log_csv")
def test_admin_audit_logs_csv(mock_export: MagicMock, audit_client: TestClient) -> None:
    mock_export.return_value = "id,action\n"
    r = audit_client.get("/api/admin/audit-logs", params={"format": "csv"})
    assert r.status_code == 200
    assert "text/csv" in r.headers.get("content-type", "")


# ---------------------------------------------------------------------------
# Misc compat routes
# ---------------------------------------------------------------------------


@pytest.fixture
def misc_client() -> TestClient:
    from app.fastapi_routes.domains.misc import routes as misc_routes

    app = FastAPI()

    @app.get("/openapi.json")
    def fake_openapi():
        return {"openapi": "3.0.0"}

    app.openapi = lambda: {"openapi": "3.0.0", "paths": {}}
    app.include_router(misc_routes.router)
    return TestClient(app, raise_server_exceptions=False)


def test_fhd_db_write_token_verify_no_config(misc_client: TestClient) -> None:
    with patch(
        "app.fastapi_routes.domains.misc.routes.configured_db_write_token",
        return_value="",
    ):
        r = misc_client.post("/fhd/db-write-token/verify", json={"token": "x"})
    assert r.json()["write_token_required"] is False


def test_fhd_db_read_token_verify(misc_client: TestClient) -> None:
    with patch(
        "app.fastapi_routes.domains.misc.routes.effective_db_read_token",
        return_value="secret",
    ):
        r = misc_client.post("/fhd/db-read-token/verify", json={"token": "secret"})
    assert r.json()["valid"] is True


def test_system_openapi(misc_client: TestClient) -> None:
    r = misc_client.get("/system/openapi")
    assert r.status_code == 200
    assert "openapi" in r.json()


@patch("app.infrastructure.db.sync_engine.get_db_status")
def test_system_test_db_status(mock_status: MagicMock, misc_client: TestClient) -> None:
    mock_status.return_value = {"mode": "test"}
    r = misc_client.get("/system/test-db/status")
    assert r.status_code == 200


@patch("app.domain.ai.tools_directory.get_tools_payload")
def test_tools_directory(mock_tools: MagicMock, misc_client: TestClient) -> None:
    mock_tools.return_value = {"tools": []}
    r = misc_client.get("/tools")
    assert r.status_code == 200
