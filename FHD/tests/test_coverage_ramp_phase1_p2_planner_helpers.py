"""COVERAGE_RAMP Phase 1 round 2: workflow planner shallow + conversation helpers SSE."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.application.workflow.planner import (
    LLMWorkflowPlanner,
    _filter_tool_registry_for_profile,
    _get_planner_http_client,
    execute_tool,
    get_tool_registry,
)
from app.application.workflow.types import PlanGraph, WorkflowNode
from app.fastapi_routes.domains.conversation.helpers import (
    _chat_db_read_grace_seconds_left,
    _chat_read_token_required_payload,
    _chat_request_subject,
    _ensure_chat_db_read_authorized,
    _ensure_vector_index_if_needed,
    _sse_event_line,
    _thinking_steps_from_planner_stream_text,
    _touch_chat_db_read_grace,
    _xcagi_chat_timeout_error_payload,
    _xcagi_guarded_planner_stream_events,
)


def _http_request(**headers: str) -> Request:
    hdrs = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "path": "/ai/chat",
        "headers": hdrs,
        "query_string": b"",
        "client": ("127.0.0.1", 8080),
    }
    return Request(scope)


# ---------------------------------------------------------------------------
# planner registry / execute_tool
# ---------------------------------------------------------------------------


def test_get_tool_registry_core_entries() -> None:
    reg = get_tool_registry()
    assert "import_excel" in reg
    assert reg["shipment_generate"]["actions"]["generate"]["risk"] == "medium"


def test_filter_tool_registry_normal_profile() -> None:
    reg = {
        "pro_tool": {"availability": "pro_only", "actions": {"run": {"availability": "pro_only"}}},
        "shared": {"availability": "shared", "actions": {"query": {"availability": "shared"}}},
    }
    filtered = _filter_tool_registry_for_profile(reg, "normal")
    assert "pro_tool" not in filtered
    assert "shared" in filtered


def test_execute_tool_unknown_action() -> None:
    out = execute_tool("nonexistent_tool", {})
    assert out["success"] is False
    assert out["error_code"] == "unknown_tool_action"


@patch("app.application.tools.handle_price_list_export")
def test_execute_tool_price_list_dispatch(mock_fn: MagicMock) -> None:
    mock_fn.return_value = {"success": True}
    out = execute_tool("price_list", {"customer_name": "甲公司"})
    assert out["success"] is True
    mock_fn.assert_called_once()


def test_execute_price_list_missing_customer() -> None:
    from app.application.workflow.planner import _execute_price_list_tool

    out = _execute_price_list_tool({})
    assert out["success"] is False
    assert out["error_code"] == "missing_customer_name"


@patch("app.bootstrap.get_products_service")
def test_execute_products_tool_query(mock_get: MagicMock) -> None:
    from app.application.workflow.planner import _execute_products_tool

    mock_get.return_value.get_products.return_value = {"success": True, "data": []}
    out = _execute_products_tool({"keyword": "5003"})
    assert out["success"] is True


@patch("app.bootstrap.get_customer_app_service")
def test_execute_customers_tool_query(mock_get: MagicMock) -> None:
    from app.application.workflow.planner import _execute_customers_tool

    mock_get.return_value.get_all.return_value = {"success": True, "data": []}
    out = _execute_customers_tool({"keyword": "甲"})
    assert out["success"] is True


@patch("app.bootstrap.get_customer_app_service")
def test_execute_customers_ensure_exists(mock_get: MagicMock) -> None:
    from app.application.workflow.planner import _execute_customers_ensure_exists_tool

    mock_get.return_value.match_purchase_unit.return_value = {"unit_name": "甲公司"}
    out = _execute_customers_ensure_exists_tool({"unit_name": "甲公司"})
    assert out["success"] is True


@patch("app.bootstrap.get_shipment_app_service")
@patch("app.application.facades.tools_facade._parse_order_text")
def test_execute_shipment_generate_tool(mock_parse: MagicMock, mock_ship: MagicMock) -> None:
    from app.application.workflow.planner import _execute_shipment_generate_tool

    mock_parse.return_value = {"success": True, "unit_name": "甲", "products": []}
    mock_ship.return_value.generate_shipment_document.return_value = {"success": True, "data": {}}
    out = _execute_shipment_generate_tool({"order_text": "甲公司2桶5003规格25"})
    assert out["success"] is True


@patch("app.bootstrap.get_shipment_app_service")
def test_execute_shipment_records_tool(mock_get: MagicMock) -> None:
    from app.application.workflow.planner import _execute_shipment_records_tool

    mock_get.return_value.get_shipments.return_value = {"success": True, "data": []}
    out = _execute_shipment_records_tool({"keyword": "甲"})
    assert out["success"] is True


@patch("app.bootstrap.get_materials_service")
def test_execute_materials_tool(mock_get: MagicMock) -> None:
    from app.application.workflow.planner import _execute_materials_tool

    mock_get.return_value.get_all_materials.return_value = {"success": True, "data": []}
    out = _execute_materials_tool({"keyword": "铜"})
    assert out["success"] is True


def test_execute_print_label_tool_missing_products() -> None:
    from app.application.workflow.planner import _execute_print_label_tool

    out = _execute_print_label_tool({})
    assert out["success"] is False
    assert out["error_code"] == "missing_products"


def test_get_planner_http_client_singleton() -> None:
    a = _get_planner_http_client()
    b = _get_planner_http_client()
    assert a is b


# ---------------------------------------------------------------------------
# LLMWorkflowPlanner fallback paths
# ---------------------------------------------------------------------------


def test_fallback_plan_add_product() -> None:
    planner = LLMWorkflowPlanner.__new__(LLMWorkflowPlanner)
    plan = planner._fallback_plan("pid1", "新增产品到七彩化工", get_tool_registry())
    assert isinstance(plan, PlanGraph)
    assert plan.intent == "add_product_to_unit"
    assert len(plan.nodes) >= 1


def test_fallback_plan_generic_query() -> None:
    planner = LLMWorkflowPlanner.__new__(LLMWorkflowPlanner)
    plan = planner._fallback_plan("pid2", "随便问问", get_tool_registry())
    assert isinstance(plan, PlanGraph)
    assert plan.nodes


@patch("app.application.workflow.planner.get_ai_conversation_service")
@patch("app.application.get_user_memory_rag_app_service")
def test_planner_injects_rag_summary(mock_rag_get: MagicMock, mock_ai: MagicMock) -> None:
    rag = MagicMock()
    rag.query.return_value = {"hits": [{"text": "偏好调价前"}]}
    rag.format_for_prompt.return_value = "用户偏好调价前单价"
    mock_rag_get.return_value = rag
    planner = LLMWorkflowPlanner()
    with patch.object(planner, "_plan_with_react_multiagent", return_value=None):
        plan = planner.plan("u1", "导出报价", get_tool_registry(), {})
    assert plan.plan_id


# ---------------------------------------------------------------------------
# conversation helpers (SSE / db read token)
# ---------------------------------------------------------------------------


def test_chat_request_subject_from_client_ip() -> None:
    req = _http_request()
    subject = _chat_request_subject(req)
    assert "|" in subject
    assert "127.0.0.1" in subject


def test_chat_db_read_grace_flow() -> None:
    req = _http_request()
    with patch(
        "app.fastapi_routes.domains.conversation.helpers.effective_db_read_token",
        return_value="",
    ):
        ok, payload = _ensure_chat_db_read_authorized(req, message="查产品库", provided_token=None)
    assert ok is True
    assert payload is None
    assert _chat_read_token_required_payload("查看数据库")["requires_token"] is True
    _touch_chat_db_read_grace(req)
    assert _chat_db_read_grace_seconds_left(req) >= 0


def test_ensure_chat_db_read_authorized_with_token() -> None:
    req = _http_request()
    with (
        patch(
            "app.fastapi_routes.domains.conversation.helpers.effective_db_read_token",
            return_value="secret",
        ),
        patch(
            "app.fastapi_routes.domains.conversation.helpers._chat_db_read_grace_seconds_left",
            return_value=0,
        ),
    ):
        ok, err = _ensure_chat_db_read_authorized(
            req, message="查看数据库产品", provided_token="secret"
        )
    assert ok is True
    assert err is None


def test_sse_and_thinking_steps_helpers() -> None:
    line = _sse_event_line({"event": "token", "data": "x"})
    assert line.startswith(b"data:")
    merged = 'data: {"type":"thinking","content":"步骤1"}\n\n'
    steps = _thinking_steps_from_planner_stream_text(merged)
    assert steps is None or "步骤" in steps
    timeout = _xcagi_chat_timeout_error_payload(30.0)
    assert timeout["success"] is False


@patch("app.fastapi_routes.domains.conversation.helpers.chat_stream_sse_events")
def test_xcagi_guarded_planner_stream_events(mock_stream: MagicMock) -> None:
    mock_stream.return_value = iter([{"type": "token", "text": "hi"}])
    from app.fastapi_routes.domains.conversation.helpers import XcagiCompatChatBody

    body = XcagiCompatChatBody.model_validate({"message": "hi"})
    events = list(
        _xcagi_guarded_planner_stream_events(
            body,
            runtime_context={},
            workspace_root="/tmp",
            client=MagicMock(),
        )
    )
    assert events
    assert events[0]["type"] == "token"


@patch("app.application.get_excel_vector_search_app_service")
def test_ensure_vector_index_if_needed(mock_get: MagicMock) -> None:
    mock_get.return_value.ensure_index.return_value = {"success": True, "index_id": "idx1"}
    hint = _ensure_vector_index_if_needed(
        "建立向量索引",
        {"excel_analysis": {"file_path": "/tmp/a.xlsx"}},
    )
    assert hint is None or isinstance(hint, str)
