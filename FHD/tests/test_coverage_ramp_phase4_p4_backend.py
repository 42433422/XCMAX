"""COVERAGE_RAMP Phase 4 round 4: ai_chat customers intent, mod_manager helpers,
xcmax_admin routes, workflow import preview."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.ai_chat_app_service import AIChatApplicationService
from app.application.tools.workflow import _import_products_preview_or_execute
from app.infrastructure.mods.mod_manager import (
    ModManager,
    _short_exc_message,
    get_mod_manager,
    is_mods_disabled,
)


def _chat_svc() -> AIChatApplicationService:
    mock_ai = MagicMock()

    async def _chat(*args, **kwargs):
        return {"success": True, "text": "回复", "action": "followup", "data": {}}

    mock_ai.chat = _chat
    with (
        patch(
            "app.application.ai_chat_app_service.get_ai_conversation_service", return_value=mock_ai
        ),
        patch("app.application.ai_chat_app_service.LLMWorkflowPlanner"),
        patch("app.application.ai_chat_app_service.HybridRiskGate"),
        patch("app.application.ai_chat_app_service.WorkflowEngine"),
        patch("app.application.ai_chat_app_service.get_approval_service"),
    ):
        svc = AIChatApplicationService()
        svc.ai_service = mock_ai
        return svc


# ---------------------------------------------------------------------------
# ai_chat customers intent
# ---------------------------------------------------------------------------


def test_execute_customers_intent_add_missing_unit() -> None:
    svc = _chat_svc()
    base = {"success": True, "data": {"data": {}}}
    out = svc._execute_customers_intent(base, {}, {}, "添加客户")
    assert "单位" in out["response"]


@patch("app.routes.tools.execute_registered_workflow_tool")
def test_execute_customers_intent_add_create(mock_exec: MagicMock) -> None:
    svc = _chat_svc()
    mock_exec.return_value = {"success": True, "created": True}
    base = {"success": True, "data": {"data": {}}}
    out = svc._execute_customers_intent(base, {"unit_name": "甲公司"}, {}, "添加单位甲公司")
    assert "甲公司" in out["response"]


@patch("app.routes.tools.execute_registered_workflow_tool")
def test_execute_customers_intent_query(mock_exec: MagicMock) -> None:
    svc = _chat_svc()
    mock_exec.return_value = {"success": True, "data": [{"unit_name": "甲"}]}
    base = {"success": True, "data": {"data": {}}}
    out = svc._execute_customers_intent(base, {"keyword": "甲"}, {}, "查询客户列表")
    assert out["success"] is True


def test_execute_pro_mode_tools_price_list() -> None:
    svc = _chat_svc()
    with patch("app.application.tools.handle_price_list_export") as mock_export:
        mock_export.return_value = {"success": True, "download_url": "/x.docx"}
        out = svc._execute_pro_mode_tools(
            {"success": True, "data": {}},
            "price_list",
            {"customer_name": "甲公司"},
            {},
            {"text": "导出报价", "data": {}},
            "导出甲公司报价",
        )
    assert out.get("toolCall", {}).get("tool_id") == "price_list"


# ---------------------------------------------------------------------------
# workflow import preview
# ---------------------------------------------------------------------------


def test_import_products_preview_mode() -> None:
    import json as _json

    df = pd.DataFrame(
        {
            "产品名称": ["清漆", "底漆"],
            "型号": ["5003", "5004"],
            "单价": [100, 90],
        }
    )
    raw = _import_products_preview_or_execute(
        df,
        list(df.columns),
        unit_name="甲公司",
        confirm=False,
        row_count=2,
    )
    out = _json.loads(raw) if isinstance(raw, str) else raw
    assert out["success"] is True
    assert out.get("preview") is True


@patch.object(ModManager, "list_mods", return_value=[])
def test_mod_manager_list_mods_empty(_mock: MagicMock) -> None:
    mgr = ModManager()
    assert mgr.list_mods() == []


def test_is_mods_disabled_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XCAGI_DISABLE_MODS", "1")
    assert is_mods_disabled() is True


def test_short_exc_message_truncates() -> None:
    msg = _short_exc_message(RuntimeError("x" * 600))
    assert len(msg) <= 480


def test_get_mod_manager_singleton() -> None:
    a = get_mod_manager()
    b = get_mod_manager()
    assert a is b
    assert isinstance(a, ModManager)


# ---------------------------------------------------------------------------
# xcmax_admin routes
# ---------------------------------------------------------------------------


@pytest.fixture
def xcmax_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    from app.fastapi_routes import xcmax_admin as xcmax_routes

    monkeypatch.setattr(xcmax_routes, "_require_market_admin_session", lambda request: None)

    async def _proxy(request, method, path, *, json_body=None, **kwargs):
        if "/health" in path:
            return {"success": True, "staffing": {"missing_employees": []}}
        return {"success": True, "data": []}

    monkeypatch.setattr(xcmax_routes, "_market_admin_proxy", _proxy)
    app = FastAPI()
    app.include_router(xcmax_routes.router)
    return TestClient(app, raise_server_exceptions=False)


def test_xcmax_admin_modules(xcmax_client: TestClient) -> None:
    r = xcmax_client.get("/api/xcmax/admin/modules")
    assert r.status_code == 200


def test_xcmax_admin_remote_status(xcmax_client: TestClient) -> None:
    r = xcmax_client.get("/api/xcmax/admin/remote-status")
    assert r.status_code == 200
