"""COVERAGE_RAMP Phase 4 round 30: ai_chat excel vector inject, im error paths,
wechat groups sync, normal_chat empty responses."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.ai_chat_app_service import AIChatApplicationService
from app.application.normal_chat_dispatch import (
    build_customers_query_response_dict,
    build_inventory_alert_response_dict,
    route_normal_mode_message,
)
from app.infrastructure.auth.dependencies import CurrentUser, require_identified_user


def _chat_svc() -> AIChatApplicationService:
    mock_ai = MagicMock()
    with (
        patch(
            "app.application.ai_chat_app_service.get_ai_conversation_service", return_value=mock_ai
        ),
        patch("app.application.ai_chat_app_service.LLMWorkflowPlanner"),
        patch("app.application.ai_chat_app_service.HybridRiskGate"),
        patch("app.application.ai_chat_app_service.WorkflowEngine"),
        patch("app.application.ai_chat_app_service.get_approval_service"),
    ):
        return AIChatApplicationService()


# ---------------------------------------------------------------------------
# ai_chat — excel vector context
# ---------------------------------------------------------------------------


def test_inject_excel_vector_no_index_id() -> None:
    svc = _chat_svc()
    ctx = {"excel_analysis": {"summary": "x"}}
    out = svc._inject_excel_vector_context("查报价", ctx)
    assert out is ctx


def test_inject_excel_vector_invalid_top_k_fallback() -> None:
    svc = _chat_svc()
    with patch("app.application.get_excel_vector_search_app_service") as mock_get:
        mock_get.return_value.query.return_value = {"success": True, "hits": []}
        out = svc._inject_excel_vector_context(
            "查",
            {"excel_index_id": "idx-1", "excel_top_k": "bad"},
        )
    assert out["excel_vector_context"]["index_id"] == "idx-1"


@patch("app.application.get_excel_vector_search_app_service")
def test_inject_excel_vector_search_failure(mock_get: MagicMock) -> None:
    mock_get.return_value.query.return_value = {"success": False}
    svc = _chat_svc()
    ctx = {"excel_index_id": "idx-2"}
    out = svc._inject_excel_vector_context("问", ctx)
    assert "excel_vector_context" not in out


@patch("app.application.get_excel_vector_search_app_service")
def test_inject_excel_vector_service_exception(mock_get: MagicMock) -> None:
    mock_get.side_effect = RuntimeError("search down")
    svc = _chat_svc()
    ctx = {"excel_vector_index_id": "idx-3"}
    out = svc._inject_excel_vector_context("问", ctx)
    assert out == ctx


def test_excel_analysis_payload_present_grid_only() -> None:
    ctx = {
        "excel_analysis": {
            "preview_data": {"grid_preview": {"rows": [["客户", "产品"], ["甲", "漆"]]}},
        }
    }
    assert AIChatApplicationService._excel_analysis_payload_present(ctx) is True


# ---------------------------------------------------------------------------
# im_routes — error branches
# ---------------------------------------------------------------------------


@pytest.fixture
def im_client_error():
    from app.fastapi_routes import im_routes

    app = FastAPI()
    app.include_router(im_routes.router)
    app.dependency_overrides[require_identified_user] = lambda: CurrentUser(1)

    mock_db = MagicMock()
    mock_svc = MagicMock()
    mock_svc.list_conversations.side_effect = RuntimeError("db broken")

    with (
        patch.object(im_routes, "_ensure_schema"),
        patch.object(im_routes, "HostSessionLocal", return_value=mock_db),
        patch.object(im_routes, "ImApplicationService", return_value=mock_svc),
    ):
        yield TestClient(app)


def test_im_list_conversations_server_error(im_client_error: TestClient) -> None:
    resp = im_client_error.get("/api/im/conversations")
    assert resp.status_code == 500
    assert resp.json()["success"] is False


# ---------------------------------------------------------------------------
# wechat — groups sync
# ---------------------------------------------------------------------------


@patch("app.services.wechat_group_customer_bridge.sync_group_messages")
def test_wechat_groups_sync_success(mock_sync: MagicMock) -> None:
    from app.fastapi_routes.domains.wechat import routes as wechat_routes

    mock_sync.return_value = {"success": True, "synced": 2, "failed": 0}
    out = wechat_routes.wechat_groups_sync_messages(body={"group_limit": 10}, market_user_id=None)
    assert out.status_code == 200
    body = out.body.decode()
    assert "success" in body


@patch("app.services.wechat_group_customer_bridge.sync_group_messages")
def test_wechat_groups_sync_all_failed(mock_sync: MagicMock) -> None:
    from app.fastapi_routes.domains.wechat import routes as wechat_routes

    mock_sync.return_value = {"success": True, "synced": 0, "failed": 3}
    out = wechat_routes.wechat_groups_sync_messages(body=None, market_user_id=None)
    payload = out.body.decode()
    assert "false" in payload.lower() or "失败" in payload


# ---------------------------------------------------------------------------
# normal_chat — empty result messages
# ---------------------------------------------------------------------------


@patch("app.application.get_material_application_service")
def test_build_inventory_alert_no_low_stock(mock_get: MagicMock) -> None:
    mock_get.return_value.get_low_stock_materials.return_value = {"data": []}
    rr = route_normal_mode_message("库存预警")
    body = build_inventory_alert_response_dict(rr)
    assert body is not None
    assert "正常" in body["response"]


def test_build_customers_query_empty_list(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys
    import types

    mock_cls = MagicMock()
    mock_cls.return_value.search.return_value = []
    fake_mod = types.ModuleType("app.services.customers_service")
    fake_mod.CustomerService = mock_cls  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.services.customers_service", fake_mod)

    rr = {"intent": "customers_query", "slots": {"keyword": "不存在公司"}}
    body = build_customers_query_response_dict(rr)
    assert body is not None
    assert "未找到" in body["response"]
