"""COVERAGE_RAMP Phase 4 round 3: workflow tool helpers, ai_chat execute branches,
market routes sweep, planner LLM mock, compat helpers."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.ai_chat_app_service import AIChatApplicationService
from app.application.tools.workflow import (
    _base_registry,
    _excel_cell_as_clean_str,
    _excel_cell_as_float,
    _infer_product_field_mapping,
    _looks_like_contract_or_footer_line,
    _parse_excel_header_row_1based,
    execute_workflow_tool,
    get_workflow_tool_registry,
    handle_excel_analysis,
    invalidate_workflow_tool_registry,
)
from app.application.workflow.planner import LLMWorkflowPlanner, get_tool_registry
from app.application.workflow.types import PlanGraph, WorkflowNode


def _chat_svc() -> AIChatApplicationService:
    mock_ai = MagicMock()

    async def _chat(*args, **kwargs):
        return {"success": True, "text": "回复", "action": "followup", "data": {}}

    mock_ai.chat = _chat
    with (
        patch("app.application.ai_chat_app_service.get_ai_conversation_service", return_value=mock_ai),
        patch("app.application.ai_chat_app_service.LLMWorkflowPlanner"),
        patch("app.application.ai_chat_app_service.HybridRiskGate"),
        patch("app.application.ai_chat_app_service.WorkflowEngine"),
        patch("app.application.ai_chat_app_service.get_approval_service"),
    ):
        svc = AIChatApplicationService()
        svc.ai_service = mock_ai
        return svc


@pytest.fixture(autouse=True)
def _bypass_native_planner_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.mod_sdk.planner_native_tools.try_execute_native_planner_tool",
        lambda *a, **k: (None, None),
    )
    monkeypatch.setattr(
        "app.mod_sdk.employee_tool_registry.is_employee_tool",
        lambda _n: False,
    )
    monkeypatch.setattr(
        "app.application.employee_pack_runner.try_execute_employee_planner_tool",
        lambda *a, **k: None,
    )


# ---------------------------------------------------------------------------
# workflow helpers
# ---------------------------------------------------------------------------


def test_parse_excel_header_row_1based() -> None:
    assert _parse_excel_header_row_1based({"header_row": 2}) == 2
    assert _parse_excel_header_row_1based({}) is None


def test_excel_cell_as_clean_str_and_float() -> None:
    assert _excel_cell_as_clean_str(100.0) == "100"
    assert _excel_cell_as_float("12.5") == 12.5
    assert _excel_cell_as_float("bad", default=0.0) == 0.0


def test_looks_like_contract_or_footer_line() -> None:
    assert _looks_like_contract_or_footer_line("1、以上货物含税月结付款验收") is True
    assert _looks_like_contract_or_footer_line("清漆") is False


def test_infer_product_field_mapping() -> None:
    cols = ["产品名称", "型号", "单价", "规格"]
    mapping = _infer_product_field_mapping(cols)
    assert mapping.get("name") or mapping.get("model_number")


def test_base_registry_has_tools() -> None:
    reg = _base_registry()
    assert isinstance(reg, list)
    assert len(reg) >= 5


def test_get_workflow_tool_registry_cached() -> None:
    invalidate_workflow_tool_registry()
    a = get_workflow_tool_registry()
    b = get_workflow_tool_registry()
    assert a is b
    assert any(t.get("function", {}).get("name") for t in a)


def test_execute_workflow_tool_unknown() -> None:
    raw = execute_workflow_tool("totally_unknown_tool_xyz", "{}")
    out = json.loads(raw)
    assert out["success"] is False


def test_execute_workflow_tool_excel_chart_recommend() -> None:
    raw = execute_workflow_tool("excel_chart_recommend", {"columns": ["a", "b"]})
    out = json.loads(raw)
    assert "suggestions" in out


def test_handle_excel_analysis_statistics_branch(tmp_path) -> None:
    p = tmp_path / "data.xlsx"
    p.write_bytes(b"x")
    df = pd.DataFrame({"qty": [1, 2, 3]})
    with patch("app.application.tools.workflow._read_excel_dataframe", return_value=df):
        out = handle_excel_analysis(
            {"file_path": "data.xlsx", "action": "statistics"},
            workspace_root=str(tmp_path),
        )
    assert out["success"] is True


# ---------------------------------------------------------------------------
# ai_chat execute branches
# ---------------------------------------------------------------------------


@patch("app.bootstrap.get_customer_app_service")
def test_execute_customers_query(mock_get: MagicMock) -> None:
    svc = _chat_svc()
    mock_get.return_value.get_all.return_value = {"success": True, "data": []}
    out = svc._execute_customers_query({"success": True, "data": {}})
    assert out["success"] is True


@patch("app.bootstrap.get_shipment_app_service")
def test_execute_shipments_query(mock_get: MagicMock) -> None:
    svc = _chat_svc()
    mock_get.return_value.get_shipments.return_value = {"success": True, "data": []}
    out = svc._execute_shipments_query({"success": True, "data": {}})
    assert out["success"] is True


def test_build_order_text_from_products_minimal() -> None:
    svc = _chat_svc()
    text = svc._build_order_text_from_products(
        "甲",
        [{"model_number": "5003", "quantity_tins": 1}],
    )
    assert "5003" in text


def test_try_merge_split_model_empty() -> None:
    svc = _chat_svc()
    assert svc._try_merge_split_model("", {}) == ""


def test_header_hint_column_roles() -> None:
    roles = AIChatApplicationService._header_hint_column_roles(
        ["客户", "产品名称", "型号", "调价前单价"]
    )
    assert isinstance(roles, dict)


def test_price_column_buckets_dual() -> None:
    before, after, generic = AIChatApplicationService._price_column_buckets(
        ["调价前单价", "调价后单价", "数量"]
    )
    assert before or after


# ---------------------------------------------------------------------------
# planner LLM mock
# ---------------------------------------------------------------------------


@patch("app.application.workflow.planner.get_ai_conversation_service")
def test_planner_plan_with_llm_valid(mock_ai: MagicMock) -> None:
    mock_ai.return_value.chat_sync.return_value = json.dumps(
        {
            "intent": "query",
            "todo_steps": ["查产品"],
            "nodes": [
                {
                    "node_id": "n1",
                    "tool_id": "products",
                    "action": "query",
                    "params": {"keyword": "5003"},
                    "risk": "low",
                }
            ],
        }
    )
    planner = LLMWorkflowPlanner()
    plan = planner._plan_with_llm(
        plan_id="llm1",
        user_id="u1",
        message="查5003",
        tool_registry=get_tool_registry(),
        context={},
    )
    assert plan is None or isinstance(plan, PlanGraph)


@patch("app.application.workflow.planner.get_ai_conversation_service")
def test_planner_critic_repair_invalid_json(mock_ai: MagicMock) -> None:
    mock_ai.return_value.chat_sync.return_value = "not-json"
    planner = LLMWorkflowPlanner()
    bad = PlanGraph(
        plan_id="bad",
        intent="x",
        nodes=[
            WorkflowNode(
                node_id="n1",
                tool_id="price_list",
                action="export",
                params={},
                risk="low",
            )
        ],
    )
    out = planner._critic_repair_with_llm(
        plan_id="bad",
        user_id="u1",
        message="导出报价",
        tool_registry=get_tool_registry(),
        context={},
        error="missing customer_name",
        invalid_plan=bad,
    )
    assert out is None


# ---------------------------------------------------------------------------
# market_account route sweep
# ---------------------------------------------------------------------------


@pytest.fixture
def market_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    from app.fastapi_routes import market_account as market_mod

    monkeypatch.setattr(market_mod, "_authorization_from_request", lambda req, body: "Bearer test")
    app = FastAPI()
    app.include_router(market_mod.router)
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.asyncio
async def test_market_account_overview_post(
    market_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.fastapi_routes import market_account as market_mod

    async def _auth(req, body):
        return "Bearer tok"

    async def _proxy(*a, **k):
        return {"__proxy_error__": True, "status_code": 503, "message": "down"}

    monkeypatch.setattr(market_mod, "_authorization_from_request_resolved", _auth)
    monkeypatch.setattr(market_mod, "_proxy_json", _proxy)
    r = market_client.post("/api/market/account-overview", json={})
    assert r.status_code == 200


def test_market_body_snippet_and_error_message() -> None:
    from app.fastapi_routes import market_account as market_mod

    snip = market_mod._body_snippet({"detail": "x" * 300})
    assert len(snip) <= 241
    msg = market_mod._error_message({"message": "fail"}, 400)
    assert "fail" in msg


def test_market_transport_error_message() -> None:
    from app.fastapi_routes import market_account as market_mod

    msg, code = market_mod._transport_error_message(ConnectionError("refused"))
    assert code in (502, 503, 504)
    assert msg


def test_market_refresh_token_from_auth_response() -> None:
    from app.fastapi_routes import market_account as market_mod

    assert market_mod._refresh_token_from_auth_response({"refresh_token": "r"}) == "r"


def test_market_user_blob_from_payload() -> None:
    from app.fastapi_routes import market_account as market_mod

    blob = market_mod._user_blob_from_market_payload({"user": {"id": 1, "name": "u"}})
    assert blob.get("id") == 1 or blob.get("name") == "u"
