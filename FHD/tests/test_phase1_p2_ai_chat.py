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
        patch(
            "app.application.ai_chat_app_service.get_ai_conversation_service", return_value=mock_ai
        ),
        patch("app.application.ai_chat_app_service.LLMWorkflowPlanner"),
        patch("app.application.ai_chat_app_service.HybridRiskGate"),
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
    assert (
        _skip_pro_excel_deterministic_import({"excel_import_skip_deterministic_shortcut": True})
        is True
    )


def test_get_ai_chat_app_service_singleton() -> None:
    with patch("app.application.ai_chat_app_service.get_ai_conversation_service"):
        a = get_ai_chat_app_service()
        b = get_ai_chat_app_service()
        assert a is b


# ---------------------------------------------------------------------------
# Static / class helpers
# ---------------------------------------------------------------------------


def test_is_number_text_and_headers() -> None:
    assert AIChatApplicationService._is_number_text("12.5") is True
    assert AIChatApplicationService._is_number_text("abc") is False
    assert (
        AIChatApplicationService._row_values_look_like_table_headers(["产品名称", "规格", "单价"])
        is True
    )
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
    assert (
        AIChatApplicationService._excel_analysis_payload_present(
            {"excel_analysis": {"summary": "x"}}
        )
        is True
    )
    assert (
        AIChatApplicationService._excel_analysis_payload_present(
            {"excel_analysis": {"preview_data": {"sample_rows": [{"a": 1}]}}}
        )
        is True
    )
    assert (
        AIChatApplicationService._excel_analysis_payload_present(
            {"excel_analysis": {"preview_data": {"grid_preview": {"rows": [[1], [2]]}}}}
        )
        is True
    )


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


@patch("app.services.get_conversation_service")
def test_persist_chat_turn_with_session(
    mock_conv: MagicMock, chat_svc: AIChatApplicationService
) -> None:
    mock_conv.return_value.save_message = MagicMock()
    chat_svc._persist_chat_turn(
        "u1",
        "hello",
        {"session_id": "sess-1", "local_user_id": 17},
        {
            "success": True,
            "response": "world",
            "data": {"action": "followup", "data": {"intent": "chat"}},
        },
    )
    assert mock_conv.return_value.save_message.call_count == 2


@patch("app.application.get_excel_vector_search_app_service")
def test_inject_excel_vector_context(
    mock_get: MagicMock, chat_svc: AIChatApplicationService
) -> None:
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


# ---------------------------------------------------------------------------
# Tool execution branches
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Excel deterministic import shortcut (pro mode, high line ROI)
# ---------------------------------------------------------------------------
