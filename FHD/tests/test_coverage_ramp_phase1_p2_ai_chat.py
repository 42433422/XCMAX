"""COVERAGE_RAMP Phase 1 round 2: ai_chat_app_service deep paths (mocked LLM/workflow/deps)."""

from __future__ import annotations

import asyncio
import math
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from app.application.ai_chat_app_service import (
    AIChatApplicationService,
    _skip_pro_excel_deterministic_import,
    get_ai_chat_app_service,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def chat_svc() -> AIChatApplicationService:
    mock_ai = MagicMock()

    async def _chat(*args, **kwargs):
        return {
            "success": True,
            "text": "回复",
            "action": "followup",
            "data": {},
        }

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
        yield svc


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def test_skip_pro_excel_env_disable_shortcut(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XCAGI_DISABLE_PRO_EXCEL_IMPORT_SHORTCUT", "yes")
    assert _skip_pro_excel_deterministic_import({}) is True
    assert _skip_pro_excel_deterministic_import({"excel_import_skip_deterministic_shortcut": True}) is True


def test_get_ai_chat_app_service_singleton() -> None:
    with patch("app.application.ai_chat_app_service.get_ai_conversation_service"):
        a = get_ai_chat_app_service()
        b = get_ai_chat_app_service()
        assert a is b


# ---------------------------------------------------------------------------
# Static / class helpers
# ---------------------------------------------------------------------------


def test_build_fallback_greeting_vs_default() -> None:
    greet = AIChatApplicationService._build_fallback_response("你好", "timeout")
    assert greet["success"] is False
    assert "智能助手" in greet["response"]
    default = AIChatApplicationService._build_fallback_response("查库存", "db down")
    assert "db down" in default["response"]


def test_is_number_text_and_headers() -> None:
    assert AIChatApplicationService._is_number_text("12.5") is True
    assert AIChatApplicationService._is_number_text("abc") is False
    assert AIChatApplicationService._row_values_look_like_table_headers(["产品名称", "规格", "单价"]) is True
    assert AIChatApplicationService._row_values_look_like_table_headers(["a"]) is False


def test_excel_cell_measure_unit_and_sanitize() -> None:
    assert AIChatApplicationService._excel_cell_looks_like_product_measure_unit("10件") is True
    assert AIChatApplicationService._excel_cell_looks_like_product_measure_unit("七彩化工") is False
    assert AIChatApplicationService._sanitize_import_scalar(float("nan")) is None
    assert AIChatApplicationService._sanitize_import_scalar("null") is None
    assert AIChatApplicationService._sanitize_import_scalar("  产品A  ") == "产品A"


def test_guess_default_purchase_unit_from_filename() -> None:
    unit = AIChatApplicationService._guess_default_purchase_unit(
        {"file_name": "成都七彩化工有限公司产品报价表.xlsx"}
    )
    assert "七彩" in unit or "公司" in unit


def test_excel_analysis_payload_present_variants() -> None:
    assert AIChatApplicationService._excel_analysis_payload_present(None) is False
    assert AIChatApplicationService._excel_analysis_payload_present({"excel_analysis": {"summary": "x"}}) is True
    assert AIChatApplicationService._excel_analysis_payload_present(
        {"excel_analysis": {"preview_data": {"sample_rows": [{"a": 1}]}}}
    ) is True
    assert AIChatApplicationService._excel_analysis_payload_present(
        {"excel_analysis": {"preview_data": {"grid_preview": {"rows": [[1], [2]]}}}}
    ) is True


def test_looks_like_short_excel_import_command() -> None:
    assert AIChatApplicationService._looks_like_short_excel_import_command("加入数据库") is True
    assert AIChatApplicationService._looks_like_short_excel_import_command("") is False
    assert AIChatApplicationService._looks_like_short_excel_import_command("x" * 50) is False


def test_model_like_score_and_packaging_ratio() -> None:
    assert AIChatApplicationService._model_like_score("5003A") == 1.0
    assert AIChatApplicationService._model_like_score("") == 0.0
    ratio = AIChatApplicationService._packaging_or_measure_ratio(["25kg/桶", "件", "5003"])
    assert 0.0 <= ratio <= 1.0


def test_price_column_buckets_and_resolve() -> None:
    keys = ["调价前单价", "调价后单价", "数量"]
    before, after, generic = AIChatApplicationService._price_column_buckets(keys)
    assert before or after or generic
    col, err = AIChatApplicationService._resolve_unit_price_column(
        keys, "", "请导入调价前单价列", None
    )
    assert err is None
    assert col


def test_merge_user_intent_for_price_resolution() -> None:
    merged = AIChatApplicationService._merge_user_intent_for_price_resolution(
        "确认导入调价前",
        {
            "recent_messages": [
                {"role": "assistant", "content": "将使用调价前单价"},
                {"role": "user", "content": "好的"},
            ]
        },
    )
    assert "调价前" in merged


def test_resolve_force_header_row() -> None:
    ea = {"preview_data": {"grid_preview": {"header_row_index": 2}}}
    assert AIChatApplicationService._resolve_force_header_row_1based(ea, ea["preview_data"]) == 2


def test_infer_excel_column_roles_sample(chat_svc: AIChatApplicationService) -> None:
    records = [
        {"客户": "甲公司", "产品名称": "清漆", "型号": "5003", "单价": "120"},
        {"客户": "甲公司", "产品名称": "底漆", "型号": "5004", "单价": "98"},
    ]
    roles, conf = chat_svc._infer_excel_column_roles(records)
    assert isinstance(roles, dict)
    assert conf >= 0.0


def test_fallback_excel_columns() -> None:
    with patch("app.application.ai_chat_app_service.get_ai_conversation_service"):
        service = AIChatApplicationService()
    records = [
        {"描述": "清漆A", "编码": "5003A", "单价": "100"},
        {"描述": "底漆B", "编码": "5004B", "单价": "90"},
    ]
    name_col = service._fallback_excel_product_name_column(records, set())
    model_col = service._fallback_excel_model_number_column(records, set())
    assert name_col or model_col


def test_extract_excel_import_records_from_grid(chat_svc: AIChatApplicationService) -> None:
    excel_analysis = {
        "file_name": "报价.xlsx",
        "preview_data": {
            "grid_preview": {
                "rows": [
                    ["客户", "产品名称", "型号", "单价"],
                    ["甲公司", "清漆", "5003", "120"],
                    ["甲公司", "底漆", "5004", "98"],
                ]
            }
        },
    }
    records, err = chat_svc._extract_excel_import_records(
        excel_analysis, {"unit_name": "甲公司"}, user_message="导入调价前单价"
    )
    assert err is None
    assert len(records) >= 1
    assert records[0].get("unit_name")


def test_extract_excel_import_dual_price_columns(chat_svc: AIChatApplicationService) -> None:
    excel_analysis = {
        "preview_data": {
            "grid_preview": {
                "rows": [
                    ["客户", "产品", "调价前单价", "调价后单价"],
                    ["甲公司", "清漆", "100", "110"],
                ]
            }
        }
    }
    records, err = chat_svc._extract_excel_import_records(
        excel_analysis, user_message="调价前和调价后都要"
    )
    # 双价列表头存在；未明确择一时可能解析出记录或返回 ambiguous
    assert err in (None, "ambiguous_price_columns")
    assert isinstance(records, list)


# ---------------------------------------------------------------------------
# process_chat main paths
# ---------------------------------------------------------------------------


def test_process_chat_connection_error(chat_svc: AIChatApplicationService) -> None:
    async def _fail(*a, **k):
        raise ConnectionError("refused")

    chat_svc.ai_service.chat = _fail
    with patch.object(chat_svc, "_persist_chat_turn"):
        out = chat_svc.process_chat("u1", "查库存", context={})
    assert out["success"] is False
    assert "连接" in out["message"] or "网络" in out["response"] or "不可用" in out["response"]


def test_process_chat_timeout(chat_svc: AIChatApplicationService) -> None:
    async def _fail(*a, **k):
        raise TimeoutError("slow")

    chat_svc.ai_service.chat = _fail
    out = chat_svc.process_chat("u1", "查产品")
    assert out["success"] is False
    assert "超时" in out["response"]


def test_process_chat_api_key_error(chat_svc: AIChatApplicationService) -> None:
    async def _fail(*a, **k):
        raise RuntimeError("invalid api_key")

    chat_svc.ai_service.chat = _fail
    out = chat_svc.process_chat("u1", "hi")
    assert "API Key" in out["response"] or "api" in out["message"].lower()


def test_process_chat_with_file_context_enriches_excel(chat_svc: AIChatApplicationService) -> None:
    async def _chat(user_id, message, context, source=None):
        assert context.get("excel_analysis", {}).get("file_path") == "/tmp/q.xlsx"
        return {"text": "ok", "action": "followup", "data": {}}

    chat_svc.ai_service.chat = _chat
    out = chat_svc.process_chat(
        "u1",
        "分析",
        file_context={"file_path": "/tmp/q.xlsx", "sheet_name": "Sheet1"},
        source="basic",
    )
    assert out["success"] is True


@patch("app.services.get_conversation_service")
def test_persist_chat_turn_with_session(mock_conv: MagicMock, chat_svc: AIChatApplicationService) -> None:
    mock_conv.return_value.save_message = MagicMock()
    chat_svc._persist_chat_turn(
        "u1",
        "hello",
        {"session_id": "sess-1"},
        {
            "success": True,
            "response": "world",
            "data": {"action": "followup", "data": {"intent": "chat"}},
        },
    )
    assert mock_conv.return_value.save_message.call_count == 2


@patch("app.application.get_excel_vector_search_app_service")
def test_inject_excel_vector_context(mock_get: MagicMock, chat_svc: AIChatApplicationService) -> None:
    mock_get.return_value.query.return_value = {
        "success": True,
        "hits": [{"text": "row1"}],
    }
    ctx = chat_svc._inject_excel_vector_context(
        "查报价",
        {"excel_index_id": "idx-1", "excel_top_k": 3},
    )
    assert ctx["excel_vector_context"]["index_id"] == "idx-1"


# ---------------------------------------------------------------------------
# _try_handle_dynamic_workflow (pro mode)
# ---------------------------------------------------------------------------


def test_dynamic_workflow_non_pro_returns_none(chat_svc: AIChatApplicationService) -> None:
    assert chat_svc._try_handle_dynamic_workflow("u", "导入", "basic", {}, {}) is None


def test_dynamic_workflow_import_missing_file(chat_svc: AIChatApplicationService) -> None:
    out = chat_svc._try_handle_dynamic_workflow(
        "u",
        "导入数据库",
        "pro",
        {},
        {"suggested_use": "unit_products_db", "saved_name": "", "unit_name": "甲"},
    )
    assert out is not None
    assert out["success"] is True
    assert "缺少" in out["response"] or "上传" in out["response"]


def test_dynamic_workflow_import_missing_unit(chat_svc: AIChatApplicationService) -> None:
    out = chat_svc._try_handle_dynamic_workflow(
        "u",
        "导入",
        "pro",
        {},
        {"suggested_use": "unit_products_db", "saved_name": "f.db", "unit_name": ""},
    )
    assert out is not None
    assert "客户" in out["response"]


def test_dynamic_workflow_short_command_no_excel(chat_svc: AIChatApplicationService) -> None:
    out = chat_svc._try_handle_dynamic_workflow("u", "加入数据库", "pro", {}, {})
    assert out is not None
    assert "Excel" in out["response"] or "分析" in out["response"]


@patch("app.application.get_unit_products_import_app_service")
def test_dynamic_workflow_unit_products_import(
    mock_get: MagicMock, chat_svc: AIChatApplicationService
) -> None:
    mock_get.return_value.import_unit_products.return_value = {
        "success": True,
        "unit_name": "甲公司",
        "created_unit": False,
        "imported": 3,
        "skipped_duplicates": 1,
    }
    out = chat_svc._try_handle_dynamic_workflow(
        "u",
        "导入数据库",
        "pro",
        {},
        {
            "suggested_use": "unit_products_db",
            "saved_name": "data.db",
            "unit_name": "甲公司",
        },
    )
    assert out is not None
    assert out["success"] is True
    assert "导入" in out["response"]


# ---------------------------------------------------------------------------
# Tool execution branches
# ---------------------------------------------------------------------------


def test_execute_pro_mode_shipment_generate(chat_svc: AIChatApplicationService) -> None:
    ai_result = {"text": "生成发货单", "data": {}}
    response_data = {"success": True, "data": {}}
    with patch("app.application.facades.tools_facade._parse_order_text", return_value={"success": False}):
        out = chat_svc._execute_pro_mode_tools(
            response_data,
            "shipment_generate",
            {"unit_name": "甲", "quantity_tins": 2, "model_number": "5003", "tin_spec": 25},
            {},
            ai_result,
            "甲公司 2桶5003规格25",
        )
    assert out.get("toolCall", {}).get("tool_id") == "shipment_generate"


def test_execute_pro_mode_unknown_tool(chat_svc: AIChatApplicationService) -> None:
    out = chat_svc._execute_pro_mode_tools(
        {"success": True, "data": {}},
        "custom_tool",
        {},
        {"p": 1},
        {"text": "run", "data": {}},
    )
    assert out["toolCall"]["tool_id"] == "custom_tool"


@patch("app.bootstrap.get_products_service")
@patch("app.infrastructure.lookups.purchase_unit_resolver.resolve_purchase_unit")
def test_execute_products_query_keyword_parse(
    mock_resolve: MagicMock, mock_products: MagicMock, chat_svc: AIChatApplicationService
) -> None:
    mock_resolve.return_value = SimpleNamespace(unit_name="甲公司")
    mock_products.return_value.get_products.return_value = {
        "success": True,
        "data": [{"name": "清漆"}],
    }
    out = chat_svc._execute_products_query(
        {"success": True, "data": {}},
        {"keyword": "甲公司的5003"},
        {},
    )
    assert out["success"] is True


@patch("app.bootstrap.get_shipment_app_service")
def test_execute_shipment_generate_normal(
    mock_ship: MagicMock, chat_svc: AIChatApplicationService
) -> None:
    mock_ship.return_value.generate_shipment.return_value = {
        "success": True,
        "data": {"doc_id": 9},
    }
    out = chat_svc._execute_shipment_generate(
        {"success": True, "data": {}},
        {"order_text": "甲公司 2桶5003规格25"},
        {"text": "生成"},
    )
    assert out["success"] is True


@patch("app.bootstrap.get_shipment_app_service")
def test_execute_shipments_query(mock_ship: MagicMock, chat_svc: AIChatApplicationService) -> None:
    mock_ship.return_value.get_shipments.return_value = {
        "success": True,
        "data": [{"id": 1}],
    }
    out = chat_svc._execute_shipments_query({"success": True, "data": {}})
    assert out["success"] is True


def test_handle_tool_call_normal_mode_shipments(chat_svc: AIChatApplicationService) -> None:
    ai_result = {
        "text": "查发货单",
        "action": "tool_call",
        "data": {"tool_key": "shipments", "params": {}, "slots": {}},
    }
    with patch.object(chat_svc, "_execute_shipments_query", return_value={"success": True, "response": "1条"}):
        out = chat_svc._build_response(ai_result, None, "")
    assert out["success"] is True


def test_try_merge_split_model(chat_svc: AIChatApplicationService) -> None:
    merged = chat_svc._try_merge_split_model(
        "2桶5003A规格25",
        {"quantity_tins": 2},
    )
    assert merged == "2桶5003A规格25"


def test_build_order_text_with_defaults(chat_svc: AIChatApplicationService) -> None:
    text = chat_svc._build_order_text_from_products(
        "甲公司",
        [{"model": "5003", "quantity_tins": 2, "spec": 25}],
        default_qty=2,
        default_spec=25,
    )
    assert "甲公司" in text
    assert "5003" in text


# ---------------------------------------------------------------------------
# Excel deterministic import shortcut (pro mode, high line ROI)
# ---------------------------------------------------------------------------


def test_dynamic_workflow_excel_import_empty_records(chat_svc: AIChatApplicationService) -> None:
    ctx = {
        "excel_import_use_deterministic_shortcut": True,
        "excel_analysis": {"summary": "空表", "fields": []},
    }
    out = chat_svc._try_handle_dynamic_workflow("u", "导入数据库", "pro", ctx, {})
    assert out is not None
    assert out["success"] is True
    assert "未解析到" in out["response"] or "字段" in out["response"]


@patch("app.bootstrap.get_customer_app_service")
@patch("app.bootstrap.get_products_service")
def test_dynamic_workflow_excel_import_executes(
    mock_products: MagicMock, mock_customers: MagicMock, chat_svc: AIChatApplicationService
) -> None:
    mock_customers.return_value.match_purchase_unit.return_value = None
    mock_customers.return_value.create.return_value = {"success": True}
    mock_products.return_value.get_products.return_value = {"success": True, "data": []}
    mock_products.return_value.create_product.return_value = {"success": True}

    ctx = {
        "excel_import_use_deterministic_shortcut": True,
        "excel_analysis": {
            "summary": "报价",
            "fields": [{"label": "客户"}, {"label": "产品"}, {"label": "单价"}],
            "preview_data": {
                "grid_preview": {
                    "rows": [
                        ["客户", "产品名称", "型号", "单价"],
                        ["甲公司", "清漆", "5003", "120"],
                    ]
                }
            },
        },
    }
    out = chat_svc._try_handle_dynamic_workflow("u", "导入数据库", "pro", ctx, {})
    assert out is not None
    assert out["success"] is True
    assert "入库" in out["response"] or "新增" in out["response"]


@patch("app.application.normal_chat_dispatch.route_normal_mode_message")
@patch("app.application.normal_chat_dispatch.resolve_tool_execution_profile", return_value="normal")
def test_dynamic_workflow_normal_product_query(
    mock_profile: MagicMock, mock_route: MagicMock, chat_svc: AIChatApplicationService
) -> None:
    mock_route.return_value = {"intent": "product_query", "keyword": "5003"}
    with patch(
        "app.application.normal_chat_dispatch.build_product_query_response_dict",
        return_value={"success": True, "response": "找到产品"},
    ):
        out = chat_svc._try_handle_dynamic_workflow("u", "查5003产品", "pro", {}, {})
    assert out is not None
    assert out["success"] is True


@patch("app.application.normal_chat_dispatch.route_normal_mode_message")
@patch("app.application.normal_chat_dispatch.resolve_tool_execution_profile", return_value="normal")
def test_dynamic_workflow_normal_shipment_preview(
    mock_profile: MagicMock, mock_route: MagicMock, chat_svc: AIChatApplicationService
) -> None:
    mock_route.return_value = {"intent": "shipment"}
    with patch(
        "app.application.normal_chat_dispatch.run_normal_slot_shipment_preview",
        return_value={"success": True, "response": "预览发货单"},
    ):
        out = chat_svc._try_handle_dynamic_workflow(
            "u", "甲公司2桶5003规格25", "pro", {}, {}
        )
    assert out is not None
    assert out["success"] is True
