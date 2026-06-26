"""测试 ai_chat_app_service 的分支覆盖（第二轮，聚焦未覆盖方法与边界分支）。

覆盖目标（与 _branch_cov.py 互补）：
- _is_pro_source / _merge_tool_runtime_context
- _build_fallback_response / _is_number_text / _row_values_look_like_table_headers
- _resolve_excel_path_for_import / _customer_hint_from_preview_grid
- _excel_cell_looks_like_product_measure_unit
- _default_purchase_unit_for_import / _guess_default_purchase_unit
- _sanitize_import_scalar / _resolve_force_header_row_1based
- _resolve_sheet_name_for_reimport / _try_structured_reload_records
- _model_like_score / _packaging_or_measure_ratio
- _infer_excel_column_roles_with_llm
- _looks_like_short_excel_import_command
- _format_workflow_run_response
- process_chat 错误分支
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from app.application.ai_chat_app_service import (
    AIChatApplicationService,
    _skip_pro_excel_deterministic_import,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_svc() -> AIChatApplicationService:
    """构造能正常实例化的服务（模拟所有构造依赖）。"""
    with (
        patch("app.application.ai_chat_app_service.get_ai_conversation_service"),
        patch("app.application.ai_chat_app_service.LLMWorkflowPlanner"),
        patch("app.application.ai_chat_app_service.HybridRiskGate"),
        patch("app.application.ai_chat_app_service.WorkflowEngine"),
        patch("app.application.ai_chat_app_service.get_approval_service"),
    ):
        return AIChatApplicationService()


def _make_plan(
    *,
    plan_id: str = "plan_test",
    intent: str = "test_intent",
    nodes=None,
    todo_steps=None,
    risk_level: str = "low",
    metadata=None,
):
    return SimpleNamespace(
        plan_id=plan_id,
        intent=intent,
        nodes=nodes or [],
        todo_steps=todo_steps or [],
        risk_level=risk_level,
        metadata=metadata or {},
    )


def _make_node(
    *,
    node_id: str = "n1",
    tool_id: str = "products",
    action: str = "query",
    params=None,
    risk: str = "low",
    idempotent: bool = True,
    depends_on=None,
    description: str = "",
):
    return SimpleNamespace(
        node_id=node_id,
        tool_id=tool_id,
        action=action,
        params=params or {},
        risk=risk,
        idempotent=idempotent,
        depends_on=depends_on or [],
        description=description,
    )


def _make_node_result(
    *,
    node_id: str = "n1",
    tool_id: str = "products",
    action: str = "query",
    success: bool = True,
    output=None,
    error: str = "",
    params=None,
    retryable: bool = True,
    retries: int = 0,
    recovery_hint: str = "",
    started_at: str = "",
    finished_at: str = "",
    duration_ms: int = 0,
):
    return SimpleNamespace(
        node_id=node_id,
        tool_id=tool_id,
        action=action,
        success=success,
        output=output or {},
        error=error,
        params=params or {},
        retryable=retryable,
        retries=retries,
        recovery_hint=recovery_hint,
        started_at=started_at,
        finished_at=finished_at,
        duration_ms=duration_ms,
    )


def _make_run_result(
    *,
    success: bool = True,
    message: str = "",
    node_results=None,
    final_context=None,
):
    return SimpleNamespace(
        success=success,
        message=message,
        node_results=node_results or [],
        final_context=final_context or {},
    )


# ---------------------------------------------------------------------------
# _is_pro_source
# ---------------------------------------------------------------------------


class TestIsProSource:
    """_is_pro_source 分支测试。"""

    def test_none_returns_false(self):
        assert AIChatApplicationService._is_pro_source(None) is False

    def test_empty_string_returns_false(self):
        assert AIChatApplicationService._is_pro_source("") is False

    def test_pro_returns_true(self):
        assert AIChatApplicationService._is_pro_source("pro") is True

    def test_pro_mode_returns_true(self):
        assert AIChatApplicationService._is_pro_source("pro_mode") is True

    def test_pro_mode_with_dash_returns_true(self):
        assert AIChatApplicationService._is_pro_source("pro-mode") is True

    def test_promode_returns_true(self):
        assert AIChatApplicationService._is_pro_source("promode") is True

    def test_professional_returns_true(self):
        assert AIChatApplicationService._is_pro_source("professional") is True

    def test_xcagi_pro_returns_true(self):
        assert AIChatApplicationService._is_pro_source("xcagi_pro") is True

    def test_uppercase_pro_returns_true(self):
        assert AIChatApplicationService._is_pro_source("PRO") is True

    def test_normal_returns_false(self):
        assert AIChatApplicationService._is_pro_source("normal") is False

    def test_random_string_returns_false(self):
        assert AIChatApplicationService._is_pro_source("random") is False


# ---------------------------------------------------------------------------
# _merge_tool_runtime_context
# ---------------------------------------------------------------------------


class TestMergeToolRuntimeContext:
    """_merge_tool_runtime_context 分支测试。"""

    def test_none_context(self):
        result = AIChatApplicationService._merge_tool_runtime_context("u1", "hello", None)
        assert result == {"user_id": "u1", "message": "hello"}

    def test_non_dict_context(self):
        result = AIChatApplicationService._merge_tool_runtime_context("u1", "hello", "not dict")  # type: ignore[arg-type]
        assert result == {"user_id": "u1", "message": "hello"}

    def test_dict_with_none_values_skipped(self):
        ctx = {"ui_surface": None, "intent_channel": None, "tool_execution_profile": None}
        result = AIChatApplicationService._merge_tool_runtime_context("u1", "hello", ctx)
        assert "ui_surface" not in result
        assert "intent_channel" not in result
        assert "tool_execution_profile" not in result

    def test_dict_with_valid_values(self):
        ctx = {
            "ui_surface": "normal",
            "intent_channel": "pro",
            "tool_execution_profile": "normal",
        }
        result = AIChatApplicationService._merge_tool_runtime_context("u1", "hello", ctx)
        assert result["ui_surface"] == "normal"
        assert result["intent_channel"] == "pro"
        assert result["tool_execution_profile"] == "normal"

    def test_dict_with_excel_analysis(self):
        ctx = {"excel_analysis": {"file_path": "/tmp/x.xlsx"}}
        result = AIChatApplicationService._merge_tool_runtime_context("u1", "hello", ctx)
        assert result["excel_analysis"] == {"file_path": "/tmp/x.xlsx"}

    def test_dict_with_excel_analysis_not_dict_skipped(self):
        ctx = {"excel_analysis": "not a dict"}
        result = AIChatApplicationService._merge_tool_runtime_context("u1", "hello", ctx)
        assert "excel_analysis" not in result

    def test_dict_with_last_excel_analysis_context(self):
        ctx = {"last_excel_analysis_context": {"key": "val"}}
        result = AIChatApplicationService._merge_tool_runtime_context("u1", "hello", ctx)
        assert result["last_excel_analysis_context"] == {"key": "val"}


# ---------------------------------------------------------------------------
# _build_fallback_response
# ---------------------------------------------------------------------------


class TestBuildFallbackResponse:
    """_build_fallback_response 分支测试。"""

    def test_greeting_message(self):
        result = AIChatApplicationService._build_fallback_response("你好", "test error")
        assert result["success"] is False
        assert "您好" in result["response"]
        assert result["data"]["action"] == "error_fallback"

    def test_greeting_message_ninhao(self):
        result = AIChatApplicationService._build_fallback_response("您好", "test error")
        assert "您好" in result["response"]

    def test_greeting_message_hi(self):
        result = AIChatApplicationService._build_fallback_response("hi", "test error")
        assert "您好" in result["response"]

    def test_greeting_message_hello(self):
        result = AIChatApplicationService._build_fallback_response("hello", "test error")
        assert "您好" in result["response"]

    def test_greeting_message_hai(self):
        result = AIChatApplicationService._build_fallback_response("嗨", "test error")
        assert "您好" in result["response"]

    def test_default_message(self):
        result = AIChatApplicationService._build_fallback_response("查产品", "test error")
        assert result["success"] is False
        assert "test error" in result["response"]
        assert "稍后重试" in result["response"]

    def test_empty_message(self):
        result = AIChatApplicationService._build_fallback_response("", "test error")
        assert "test error" in result["response"]

    def test_message_truncated_in_data(self):
        long_msg = "x" * 200
        result = AIChatApplicationService._build_fallback_response(long_msg, "err")
        assert len(result["data"]["data"]["original_message"]) <= 100


# ---------------------------------------------------------------------------
# _is_number_text
# ---------------------------------------------------------------------------


class TestIsNumberText:
    """_is_number_text 分支测试。"""

    def test_empty_returns_false(self):
        assert AIChatApplicationService._is_number_text("") is False

    def test_none_returns_false(self):
        assert AIChatApplicationService._is_number_text(None) is False

    def test_integer_returns_true(self):
        assert AIChatApplicationService._is_number_text("123") is True

    def test_float_returns_true(self):
        assert AIChatApplicationService._is_number_text("12.5") is True

    def test_negative_returns_true(self):
        assert AIChatApplicationService._is_number_text("-5") is True

    def test_with_comma_returns_true(self):
        assert AIChatApplicationService._is_number_text("1,234") is True

    def test_text_returns_false(self):
        assert AIChatApplicationService._is_number_text("abc") is False

    def test_mixed_returns_false(self):
        assert AIChatApplicationService._is_number_text("12abc") is False


# ---------------------------------------------------------------------------
# _row_values_look_like_table_headers
# ---------------------------------------------------------------------------


class TestRowValuesLookLikeTableHeaders:
    """_row_values_look_like_table_headers 分支测试。"""

    def test_empty_list_returns_false(self):
        assert AIChatApplicationService._row_values_look_like_table_headers([]) is False

    def test_single_value_returns_false(self):
        assert AIChatApplicationService._row_values_look_like_table_headers(["产品"]) is False

    def test_two_header_values_returns_true(self):
        assert (
            AIChatApplicationService._row_values_look_like_table_headers(["产品", "型号"]) is True
        )

    def test_two_non_header_values_returns_false(self):
        assert (
            AIChatApplicationService._row_values_look_like_table_headers(["abc", "def"]) is False
        )

    def test_with_none_values_filtered(self):
        assert (
            AIChatApplicationService._row_values_look_like_table_headers(["产品", None, "型号"])
            is True
        )

    def test_with_empty_strings_filtered(self):
        assert (
            AIChatApplicationService._row_values_look_like_table_headers(["产品", "", "型号"])
            is True
        )

    def test_many_values_few_hits_returns_false(self):
        # 6 values, only 1 hit → hits < max(2, 6//3=2) → False
        assert (
            AIChatApplicationService._row_values_look_like_table_headers(
                ["产品", "a", "b", "c", "d", "e"]
            )
            is False
        )

    def test_many_values_enough_hits_returns_true(self):
        # 6 values, 2 hits → hits >= 2 and hits >= max(2, 2) → True
        assert (
            AIChatApplicationService._row_values_look_like_table_headers(
                ["产品", "a", "b", "型号", "d", "e"]
            )
            is True
        )

    def test_price_keyword_detected(self):
        assert (
            AIChatApplicationService._row_values_look_like_table_headers(["单价", "金额"]) is True
        )

    def test_customer_keyword_detected(self):
        assert (
            AIChatApplicationService._row_values_look_like_table_headers(["客户", "厂名"]) is True
        )


# ---------------------------------------------------------------------------
# _resolve_excel_path_for_import
# ---------------------------------------------------------------------------


class TestResolveExcelPathForImport:
    """_resolve_excel_path_for_import 分支测试。"""

    def test_path_from_excel_analysis(self):
        ea = {"file_path": "/tmp/test.xlsx"}
        result = AIChatApplicationService._resolve_excel_path_for_import(ea, {})
        assert result == "/tmp/test.xlsx"

    def test_path_from_preview_data_when_excel_empty(self):
        ea = {}
        pd = {"file_path": "/tmp/preview.xlsx"}
        result = AIChatApplicationService._resolve_excel_path_for_import(ea, pd)
        assert result == "/tmp/preview.xlsx"

    def test_both_empty_returns_empty(self):
        result = AIChatApplicationService._resolve_excel_path_for_import({}, {})
        assert result == ""

    def test_excel_analysis_takes_priority(self):
        ea = {"file_path": "/tmp/ea.xlsx"}
        pd = {"file_path": "/tmp/pd.xlsx"}
        result = AIChatApplicationService._resolve_excel_path_for_import(ea, pd)
        assert result == "/tmp/ea.xlsx"

    def test_none_preview_data(self):
        ea = {"file_path": "/tmp/test.xlsx"}
        result = AIChatApplicationService._resolve_excel_path_for_import(ea, None)  # type: ignore[arg-type]
        assert result == "/tmp/test.xlsx"

    def test_whitespace_stripped(self):
        ea = {"file_path": "  /tmp/test.xlsx  "}
        result = AIChatApplicationService._resolve_excel_path_for_import(ea, {})
        assert result == "/tmp/test.xlsx"


# ---------------------------------------------------------------------------
# _customer_hint_from_preview_grid
# ---------------------------------------------------------------------------


class TestCustomerHintFromPreviewGrid:
    """_customer_hint_from_preview_grid 分支测试。"""

    def test_non_dict_preview_returns_empty(self):
        result = AIChatApplicationService._customer_hint_from_preview_grid("not dict")  # type: ignore[arg-type]
        assert result == ""

    def test_no_grid_preview_returns_empty(self):
        result = AIChatApplicationService._customer_hint_from_preview_grid({})
        assert result == ""

    def test_grid_preview_not_dict_returns_empty(self):
        result = AIChatApplicationService._customer_hint_from_preview_grid(
            {"grid_preview": "not dict"}
        )
        assert result == ""

    def test_rows_not_list_returns_empty(self):
        result = AIChatApplicationService._customer_hint_from_preview_grid(
            {"grid_preview": {"rows": "not list"}}
        )
        assert result == ""

    def test_empty_rows_returns_empty(self):
        result = AIChatApplicationService._customer_hint_from_preview_grid(
            {"grid_preview": {"rows": []}}
        )
        assert result == ""

    def test_row_not_list_continues(self):
        result = AIChatApplicationService._customer_hint_from_preview_grid(
            {"grid_preview": {"rows": ["not a list", ["cell"]]}}
        )
        assert result == ""

    def test_cell_not_dict_continues(self):
        result = AIChatApplicationService._customer_hint_from_preview_grid(
            {"grid_preview": {"rows": [["not dict", {"text": ""}]]}}
        )
        assert result == ""

    def test_empty_text_cell_skipped(self):
        result = AIChatApplicationService._customer_hint_from_preview_grid(
            {"grid_preview": {"rows": [[{"text": ""}, {"text": "   "}]]}}
        )
        assert result == ""

    def test_with_customer_hit(self):
        with patch(
            "app.application.template_grid_core._extract_inline_customer_hits_from_cell",
            return_value=["客户A"],
        ):
            result = AIChatApplicationService._customer_hint_from_preview_grid(
                {"grid_preview": {"rows": [[{"text": "客户A"}]]}}
            )
        assert result == "客户A"

    def test_import_error_returns_empty(self):
        # Simulate import failure by making the module unavailable
        with patch.dict(
            "sys.modules",
            {"app.application.template_grid_core": None},
        ):
            result = AIChatApplicationService._customer_hint_from_preview_grid(
                {"grid_preview": {"rows": [[{"text": "test"}]]}}
            )
        assert result == ""

    def test_joined_parts_with_hit(self):
        with patch(
            "app.application.template_grid_core._extract_inline_customer_hits_from_cell"
        ) as mock_extract:
            mock_extract.side_effect = [[], ["客户B"]]
            result = AIChatApplicationService._customer_hint_from_preview_grid(
                {"grid_preview": {"rows": [[{"text": "客户"}, {"text": "B"}]]}}
            )
        assert result == "客户B"

    def test_more_than_22_rows_only_checks_first_22(self):
        rows = [[{"text": f"row{i}"}] for i in range(25)]
        with patch(
            "app.application.template_grid_core._extract_inline_customer_hits_from_cell",
            return_value=[],
        ) as mock_extract:
            result = AIChatApplicationService._customer_hint_from_preview_grid(
                {"grid_preview": {"rows": rows}}
            )
        # Should only check first 22 rows
        assert mock_extract.call_count <= 44  # 22 rows * 2 calls (cell + joined)
        assert result == ""


# ---------------------------------------------------------------------------
# _excel_cell_looks_like_product_measure_unit
# ---------------------------------------------------------------------------


class TestExcelCellLooksLikeProductMeasureUnit:
    """_excel_cell_looks_like_product_measure_unit 分支测试。"""

    def test_empty_returns_false(self):
        assert AIChatApplicationService._excel_cell_looks_like_product_measure_unit("") is False

    def test_none_returns_false(self):
        assert AIChatApplicationService._excel_cell_looks_like_product_measure_unit(None) is False

    def test_common_unit_returns_true(self):
        assert AIChatApplicationService._excel_cell_looks_like_product_measure_unit("桶") is True

    def test_case_insensitive_unit(self):
        assert AIChatApplicationService._excel_cell_looks_like_product_measure_unit("PCS") is True

    def test_qty_measure_returns_true(self):
        assert AIChatApplicationService._excel_cell_looks_like_product_measure_unit("25件") is True

    def test_plain_text_returns_false(self):
        assert (
            AIChatApplicationService._excel_cell_looks_like_product_measure_unit("客户名称") is False
        )

    def test_number_returns_false(self):
        assert AIChatApplicationService._excel_cell_looks_like_product_measure_unit("123") is False


# ---------------------------------------------------------------------------
# _sanitize_import_scalar
# ---------------------------------------------------------------------------


class TestSanitizeImportScalar:
    """_sanitize_import_scalar 分支测试。"""

    def test_none_returns_none(self):
        assert AIChatApplicationService._sanitize_import_scalar(None) is None

    def test_nan_float_returns_none(self):
        assert AIChatApplicationService._sanitize_import_scalar(float("nan")) is None

    def test_string_nan_returns_none(self):
        assert AIChatApplicationService._sanitize_import_scalar("nan") is None

    def test_string_none_returns_none(self):
        assert AIChatApplicationService._sanitize_import_scalar("none") is None

    def test_string_nat_returns_none(self):
        assert AIChatApplicationService._sanitize_import_scalar("nat") is None

    def test_string_na_returns_none(self):
        assert AIChatApplicationService._sanitize_import_scalar("<na>") is None

    def test_string_null_returns_none(self):
        assert AIChatApplicationService._sanitize_import_scalar("null") is None

    def test_string_uppercase_nan_returns_none(self):
        assert AIChatApplicationService._sanitize_import_scalar("NAN") is None

    def test_string_with_whitespace_stripped(self):
        assert AIChatApplicationService._sanitize_import_scalar("  hello  ") == "hello"

    def test_normal_string_returns_stripped(self):
        assert AIChatApplicationService._sanitize_import_scalar("hello") == "hello"

    def test_integer_returns_integer(self):
        assert AIChatApplicationService._sanitize_import_scalar(42) == 42

    def test_float_returns_float(self):
        assert AIChatApplicationService._sanitize_import_scalar(3.14) == 3.14

    def test_object_with_nan_float_conversion_returns_none(self):
        class ObjWithFloat:
            def __float__(self):
                return float("nan")

        result = AIChatApplicationService._sanitize_import_scalar(ObjWithFloat())
        assert result is None

    def test_object_without_float_conversion_returns_as_is(self):
        class ObjWithoutFloat:
            pass

        obj = ObjWithoutFloat()
        result = AIChatApplicationService._sanitize_import_scalar(obj)
        assert result is obj


# ---------------------------------------------------------------------------
# _model_like_score
# ---------------------------------------------------------------------------


class TestModelLikeScore:
    """_model_like_score 分支测试。"""

    def test_empty_returns_zero(self):
        assert AIChatApplicationService._model_like_score("") == 0.0

    def test_none_returns_zero(self):
        assert AIChatApplicationService._model_like_score(None) == 0.0

    def test_alphanumeric_returns_one(self):
        assert AIChatApplicationService._model_like_score("A123") == 1.0

    def test_digit_only_short_returns_zero_point_six(self):
        assert AIChatApplicationService._model_like_score("123") == 0.6

    def test_digit_only_long_returns_zero(self):
        # len > 12 after removing - and _
        assert AIChatApplicationService._model_like_score("1234567890123") == 0.0

    def test_too_short_returns_zero(self):
        assert AIChatApplicationService._model_like_score("A") == 0.0

    def test_too_long_returns_zero(self):
        assert AIChatApplicationService._model_like_score("A" * 25) == 0.0

    def test_alpha_only_returns_zero(self):
        assert AIChatApplicationService._model_like_score("ABC") == 0.0

    def test_with_dashes_stripped(self):
        # "A-123" → compact "A123" → alphanumeric → 1.0
        assert AIChatApplicationService._model_like_score("A-123") == 1.0

    def test_with_underscores_stripped(self):
        assert AIChatApplicationService._model_like_score("A_123") == 1.0


# ---------------------------------------------------------------------------
# _packaging_or_measure_ratio
# ---------------------------------------------------------------------------


class TestPackagingOrMeasureRatio:
    """_packaging_or_measure_ratio 分支测试。"""

    def test_empty_list_returns_zero(self):
        assert AIChatApplicationService._packaging_or_measure_ratio([]) == 0.0

    def test_all_none_returns_zero(self):
        assert AIChatApplicationService._packaging_or_measure_ratio([None, None]) == 0.0

    def test_all_empty_strings_returns_zero(self):
        assert AIChatApplicationService._packaging_or_measure_ratio(["", ""]) == 0.0

    def test_all_units_returns_one(self):
        result = AIChatApplicationService._packaging_or_measure_ratio(["桶", "箱", "包"])
        assert result == 1.0

    def test_mixed_values(self):
        result = AIChatApplicationService._packaging_or_measure_ratio(["桶", "客户A", "产品B"])
        assert 0.0 < result < 1.0

    def test_no_units_returns_zero(self):
        result = AIChatApplicationService._packaging_or_measure_ratio(["客户A", "产品B"])
        assert result == 0.0

    def test_with_whitespace_stripped(self):
        result = AIChatApplicationService._packaging_or_measure_ratio(["  桶  ", "  箱  "])
        assert result == 1.0

    def test_qty_measure_format(self):
        result = AIChatApplicationService._packaging_or_measure_ratio(["25kg/桶", "30kg/箱"])
        assert result == 1.0


# ---------------------------------------------------------------------------
# _looks_like_short_excel_import_command
# ---------------------------------------------------------------------------


class TestLooksLikeShortExcelImportCommand:
    """_looks_like_short_excel_import_command 分支测试。"""

    def test_empty_returns_false(self):
        assert AIChatApplicationService._looks_like_short_excel_import_command("") is False

    def test_none_returns_false(self):
        assert AIChatApplicationService._looks_like_short_excel_import_command(None) is False

    def test_exact_join_db(self):
        assert AIChatApplicationService._looks_like_short_excel_import_command("加入数据库") is True

    def test_exact_join_ku(self):
        assert AIChatApplicationService._looks_like_short_excel_import_command("加入库") is True

    def test_exact_ru_ku(self):
        assert AIChatApplicationService._looks_like_short_excel_import_command("入库") is True

    def test_exact_add_to_ku(self):
        assert AIChatApplicationService._looks_like_short_excel_import_command("添加到库") is True

    def test_exact_write_db(self):
        assert AIChatApplicationService._looks_like_short_excel_import_command("写入数据库") is True

    def test_exact_import_db(self):
        assert AIChatApplicationService._looks_like_short_excel_import_command("导入数据库") is True

    def test_contains_keyword(self):
        assert (
            AIChatApplicationService._looks_like_short_excel_import_command("请加入数据库") is True
        )

    def test_long_text_returns_false(self):
        long_text = "x" * 41
        assert AIChatApplicationService._looks_like_short_excel_import_command(long_text) is False

    def test_no_keyword_returns_false(self):
        assert AIChatApplicationService._looks_like_short_excel_import_command("你好世界") is False

    def test_text_at_40_chars_boundary(self):
        # 40 chars should still be checked (len > 40 returns False, so 40 is the boundary)
        text = "x" * 35 + "加入数据库"
        assert AIChatApplicationService._looks_like_short_excel_import_command(text) is True


# ---------------------------------------------------------------------------
# _resolve_force_header_row_1based
# ---------------------------------------------------------------------------


class TestResolveForceHeaderRow1Based:
    """_resolve_force_header_row_1based 分支测试。"""

    def test_grid_preview_header_row_index(self):
        pd = {"grid_preview": {"header_row_index": 3}}
        result = AIChatApplicationService._resolve_force_header_row_1based({}, pd)
        assert result == 3

    def test_grid_preview_header_row_index_zero_returns_none(self):
        pd = {"grid_preview": {"header_row_index": 0}}
        result = AIChatApplicationService._resolve_force_header_row_1based({}, pd)
        assert result is None

    def test_grid_preview_header_row_index_invalid_returns_none(self):
        pd = {"grid_preview": {"header_row_index": "abc"}}
        result = AIChatApplicationService._resolve_force_header_row_1based({}, pd)
        assert result is None

    def test_grid_preview_none_value_skipped(self):
        pd = {"grid_preview": {"header_row_index": None}}
        result = AIChatApplicationService._resolve_force_header_row_1based({}, pd)
        assert result is None

    def test_tables_header_row(self):
        pd = {"tables": [{"header_row": 2}]}
        result = AIChatApplicationService._resolve_force_header_row_1based({}, pd)
        assert result == 2

    def test_tables_non_dict_skipped(self):
        pd = {"tables": ["not dict", {"header_row": 2}]}
        result = AIChatApplicationService._resolve_force_header_row_1based({}, pd)
        assert result == 2

    def test_sheets_tables_header_row(self):
        ea = {"sheets": [{"tables": [{"header_row": 4}]}]}
        result = AIChatApplicationService._resolve_force_header_row_1based(ea, {})
        assert result == 4

    def test_sheets_grid_preview_header_row_index(self):
        ea = {"sheets": [{"grid_preview": {"header_row_index": 5}}]}
        result = AIChatApplicationService._resolve_force_header_row_1based(ea, {})
        assert result == 5

    def test_sheets_non_dict_skipped(self):
        ea = {"sheets": ["not dict", {"grid_preview": {"header_row_index": 5}}]}
        result = AIChatApplicationService._resolve_force_header_row_1based(ea, {})
        assert result == 5

    def test_no_data_returns_none(self):
        result = AIChatApplicationService._resolve_force_header_row_1based({}, {})
        assert result is None

    def test_non_dict_preview_data(self):
        result = AIChatApplicationService._resolve_force_header_row_1based({}, "not dict")  # type: ignore[arg-type]
        assert result is None

    def test_grid_preview_not_dict(self):
        pd = {"grid_preview": "not dict"}
        result = AIChatApplicationService._resolve_force_header_row_1based({}, pd)
        assert result is None

    def test_sheets_not_list(self):
        ea = {"sheets": "not list"}
        result = AIChatApplicationService._resolve_force_header_row_1based(ea, {})
        assert result is None

    def test_sheets_tables_not_list(self):
        ea = {"sheets": [{"tables": "not list"}]}
        result = AIChatApplicationService._resolve_force_header_row_1based(ea, {})
        assert result is None


# ---------------------------------------------------------------------------
# _resolve_sheet_name_for_reimport
# ---------------------------------------------------------------------------


class TestResolveSheetNameForReimport:
    """_resolve_sheet_name_for_reimport 分支测试。"""

    def test_request_context_selected_sheet(self):
        rc = {"excel_analysis_selected_sheet": {"sheet_name": "Sheet1"}}
        result = AIChatApplicationService._resolve_sheet_name_for_reimport({}, {}, rc)
        assert result == "Sheet1"

    def test_request_context_selected_sheet_empty_falls_through(self):
        rc = {"excel_analysis_selected_sheet": {"sheet_name": ""}}
        result = AIChatApplicationService._resolve_sheet_name_for_reimport({}, {}, rc)
        assert result is None

    def test_request_context_preferred_sheet_name(self):
        rc = {"preferred_sheet_name": "Sheet2"}
        result = AIChatApplicationService._resolve_sheet_name_for_reimport({}, {}, rc)
        assert result == "Sheet2"

    def test_preview_data_selected_sheet_name(self):
        pd = {"selected_sheet_name": "Sheet3"}
        result = AIChatApplicationService._resolve_sheet_name_for_reimport({}, pd, None)
        assert result == "Sheet3"

    def test_preview_data_sheet_name(self):
        pd = {"sheet_name": "Sheet4"}
        result = AIChatApplicationService._resolve_sheet_name_for_reimport({}, pd, None)
        assert result == "Sheet4"

    def test_preview_data_selected_takes_priority(self):
        pd = {"selected_sheet_name": "Selected", "sheet_name": "Plain"}
        result = AIChatApplicationService._resolve_sheet_name_for_reimport({}, pd, None)
        assert result == "Selected"

    def test_excel_analysis_sheets_first(self):
        ea = {"sheets": [{"sheet_name": "First"}]}
        result = AIChatApplicationService._resolve_sheet_name_for_reimport(ea, {}, None)
        assert result == "First"

    def test_excel_analysis_sheets_empty_sheet_name(self):
        ea = {"sheets": [{"sheet_name": ""}]}
        result = AIChatApplicationService._resolve_sheet_name_for_reimport(ea, {}, None)
        assert result is None

    def test_excel_analysis_sheets_not_dict(self):
        ea = {"sheets": ["not dict"]}
        result = AIChatApplicationService._resolve_sheet_name_for_reimport(ea, {}, None)
        assert result is None

    def test_no_data_returns_none(self):
        result = AIChatApplicationService._resolve_sheet_name_for_reimport({}, {}, None)
        assert result is None

    def test_request_context_not_dict(self):
        result = AIChatApplicationService._resolve_sheet_name_for_reimport({}, {}, "not dict")  # type: ignore[arg-type]
        assert result is None

    def test_excel_analysis_sheets_not_list(self):
        ea = {"sheets": "not list"}
        result = AIChatApplicationService._resolve_sheet_name_for_reimport(ea, {}, None)
        assert result is None


# ---------------------------------------------------------------------------
# _guess_default_purchase_unit
# ---------------------------------------------------------------------------


class TestGuessDefaultPurchaseUnit:
    """_guess_default_purchase_unit 分支测试。"""

    def test_empty_excel_analysis_returns_empty(self):
        result = AIChatApplicationService._guess_default_purchase_unit({})
        assert result == ""

    def test_file_name_with_company_suffix(self):
        ea = {"file_name": "某某有限公司报价表.xlsx"}
        result = AIChatApplicationService._guess_default_purchase_unit(ea)
        assert "有限公司" in result

    def test_file_name_with_gufen_company(self):
        ea = {"file_name": "某某股份有限公司.xlsx"}
        result = AIChatApplicationService._guess_default_purchase_unit(ea)
        assert "股份有限公司" in result

    def test_file_name_with_jituan_company(self):
        ea = {"file_name": "某某集团有限公司.xlsx"}
        result = AIChatApplicationService._guess_default_purchase_unit(ea)
        assert "集团有限公司" in result

    def test_file_name_with_shiye_company(self):
        ea = {"file_name": "某某实业有限公司.xlsx"}
        result = AIChatApplicationService._guess_default_purchase_unit(ea)
        assert "实业有限公司" in result

    def test_file_name_with_keji_company(self):
        ea = {"file_name": "某某科技公司.xlsx"}
        result = AIChatApplicationService._guess_default_purchase_unit(ea)
        assert "科技公司" in result

    def test_file_name_with_chang_factory(self):
        ea = {"file_name": "某某厂.xlsx"}
        result = AIChatApplicationService._guess_default_purchase_unit(ea)
        assert "厂" in result

    def test_file_name_with_dian_shop(self):
        ea = {"file_name": "某某店.xlsx"}
        result = AIChatApplicationService._guess_default_purchase_unit(ea)
        assert "店" in result

    def test_file_name_with_baojia_suffix_stripped(self):
        ea = {"file_name": "某某公司报价表.xlsx"}
        result = AIChatApplicationService._guess_default_purchase_unit(ea)
        # "报价表" should be stripped, leaving "某某公司"
        assert "报价表" not in result

    def test_file_name_with_baojiadan_suffix_stripped(self):
        ea = {"file_name": "某某公司报价单.xlsx"}
        result = AIChatApplicationService._guess_default_purchase_unit(ea)
        assert "报价单" not in result

    def test_file_name_with_jiagebiao_suffix_stripped(self):
        ea = {"file_name": "某某公司价格表.xlsx"}
        result = AIChatApplicationService._guess_default_purchase_unit(ea)
        assert "价格表" not in result

    def test_file_name_with_year_suffix_stripped(self):
        ea = {"file_name": "某某公司2024.xlsx"}
        result = AIChatApplicationService._guess_default_purchase_unit(ea)
        assert "2024" not in result

    def test_template_name_used_when_no_file_name(self):
        ea = {"template_name": "某某公司"}
        result = AIChatApplicationService._guess_default_purchase_unit(ea)
        assert "某某公司" in result

    def test_file_path_used_when_no_name(self):
        ea = {"file_path": "/tmp/某某公司.xlsx"}
        result = AIChatApplicationService._guess_default_purchase_unit(ea)
        assert "某某公司" in result

    def test_short_stem_returns_empty(self):
        ea = {"file_name": "A.xlsx"}
        result = AIChatApplicationService._guess_default_purchase_unit(ea)
        # stem "A" has length 1 < 2 → empty
        assert result == ""

    def test_no_company_pattern_returns_stem(self):
        ea = {"file_name": "TestFile.xlsx"}
        result = AIChatApplicationService._guess_default_purchase_unit(ea)
        assert result == "TestFile"


# ---------------------------------------------------------------------------
# _try_structured_reload_records
# ---------------------------------------------------------------------------


class TestTryStructuredReloadRecords:
    """_try_structured_reload_records 分支测试。"""

    def test_no_file_path_returns_none(self):
        result = AIChatApplicationService._try_structured_reload_records({}, {}, None)
        assert result is None

    def test_file_not_exists_returns_none(self, tmp_path: Path):
        non_existent = tmp_path / "non_existent.xlsx"
        ea = {"file_path": str(non_existent)}
        result = AIChatApplicationService._try_structured_reload_records(ea, {}, None)
        assert result is None

    def test_rectangular_parse_mode(self, tmp_path: Path):
        excel_file = tmp_path / "test.xlsx"
        excel_file.write_bytes(b"fake")

        ea = {"file_path": str(excel_file)}
        pd = {"parse_mode": "rectangular"}

        mock_structured = {"sample_rows": [{"A": "1", "B": "2"}]}
        with patch(
            "app.application.template_grid_core._extract_rectangular_excel_preview",
            return_value=mock_structured,
        ):
            result = AIChatApplicationService._try_structured_reload_records(ea, pd, None)
        assert result is not None
        assert len(result) == 1

    def test_default_parse_mode(self, tmp_path: Path):
        excel_file = tmp_path / "test.xlsx"
        excel_file.write_bytes(b"fake")

        ea = {"file_path": str(excel_file)}
        pd = {}

        mock_structured = {"sample_rows": [{"name": "test"}]}
        with patch(
            "app.application.template_grid_core._extract_structured_excel_preview",
            return_value=mock_structured,
        ):
            result = AIChatApplicationService._try_structured_reload_records(ea, pd, None)
        assert result is not None
        assert result[0]["name"] == "test"

    def test_empty_rows_returns_none(self, tmp_path: Path):
        excel_file = tmp_path / "test.xlsx"
        excel_file.write_bytes(b"fake")

        ea = {"file_path": str(excel_file)}

        with patch(
            "app.application.template_grid_core._extract_structured_excel_preview",
            return_value={"sample_rows": []},
        ):
            result = AIChatApplicationService._try_structured_reload_records(ea, {}, None)
        assert result is None

    def test_rows_not_list_returns_none(self, tmp_path: Path):
        excel_file = tmp_path / "test.xlsx"
        excel_file.write_bytes(b"fake")

        ea = {"file_path": str(excel_file)}

        with patch(
            "app.application.template_grid_core._extract_structured_excel_preview",
            return_value={"sample_rows": "not list"},
        ):
            result = AIChatApplicationService._try_structured_reload_records(ea, {}, None)
        assert result is None

    def test_recoverable_error_returns_none(self, tmp_path: Path):
        excel_file = tmp_path / "test.xlsx"
        excel_file.write_bytes(b"fake")

        ea = {"file_path": str(excel_file)}

        with patch(
            "app.application.template_grid_core._extract_structured_excel_preview",
            side_effect=RuntimeError("boom"),
        ):
            result = AIChatApplicationService._try_structured_reload_records(ea, {}, None)
        assert result is None

    def test_non_dict_rows_filtered(self, tmp_path: Path):
        excel_file = tmp_path / "test.xlsx"
        excel_file.write_bytes(b"fake")

        ea = {"file_path": str(excel_file)}

        mock_structured = {"sample_rows": ["not dict", {"name": "test"}, None]}
        with patch(
            "app.application.template_grid_core._extract_structured_excel_preview",
            return_value=mock_structured,
        ):
            result = AIChatApplicationService._try_structured_reload_records(ea, {}, None)
        # Only dict rows are kept
        assert result is not None
        assert len(result) == 1

    def test_all_non_dict_rows_returns_none(self, tmp_path: Path):
        excel_file = tmp_path / "test.xlsx"
        excel_file.write_bytes(b"fake")

        ea = {"file_path": str(excel_file)}

        mock_structured = {"sample_rows": ["not dict", "another"]}
        with patch(
            "app.application.template_grid_core._extract_structured_excel_preview",
            return_value=mock_structured,
        ):
            result = AIChatApplicationService._try_structured_reload_records(ea, {}, None)
        assert result is None

    def test_nan_values_sanitized(self, tmp_path: Path):
        excel_file = tmp_path / "test.xlsx"
        excel_file.write_bytes(b"fake")

        ea = {"file_path": str(excel_file)}

        mock_structured = {
            "sample_rows": [
                {"name": "test", "nan_val": float("nan"), "none_str": "nan"}
            ]
        }
        with patch(
            "app.application.template_grid_core._extract_structured_excel_preview",
            return_value=mock_structured,
        ):
            result = AIChatApplicationService._try_structured_reload_records(ea, {}, None)
        assert result is not None
        assert result[0]["nan_val"] is None
        assert result[0]["none_str"] is None


# ---------------------------------------------------------------------------
# _infer_excel_column_roles_with_llm
# ---------------------------------------------------------------------------


class TestInferExcelColumnRolesWithLlm:
    """_infer_excel_column_roles_with_llm 分支测试。"""

    def test_empty_records_returns_empty(self):
        svc = _make_svc()
        result = svc._infer_excel_column_roles_with_llm([])
        assert result == {}

    def test_no_api_key_returns_empty(self):
        svc = _make_svc()
        svc.ai_service = MagicMock()
        svc.ai_service.api_key = ""
        svc.ai_service.api_url = ""

        with (
            patch(
                "app.infrastructure.llm.providers.credentials.resolve_openai_env_credentials",
                return_value=("", ""),
            ),
            patch(
                "app.infrastructure.llm.providers.credentials.default_chat_completions_url",
                return_value="http://localhost",
            ),
            patch(
                "app.infrastructure.llm.providers.credentials.resolve_default_chat_model",
                return_value="model",
            ),
        ):
            result = svc._infer_excel_column_roles_with_llm([{"col1": "val1"}])
        assert result == {}

    def test_http_error_returns_empty(self):
        svc = _make_svc()
        svc.ai_service = MagicMock()
        svc.ai_service.api_key = "test_key"
        svc.ai_service.api_url = "http://localhost"
        svc.ai_service.model = "test_model"

        mock_resp = MagicMock()
        mock_resp.status_code = 400

        with patch("httpx.post", return_value=mock_resp):
            result = svc._infer_excel_column_roles_with_llm([{"col1": "val1"}])
        assert result == {}

    def test_empty_content_returns_empty(self):
        svc = _make_svc()
        svc.ai_service = MagicMock()
        svc.ai_service.api_key = "test_key"
        svc.ai_service.api_url = "http://localhost"
        svc.ai_service.model = "test_model"

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"choices": [{"message": {"content": ""}}]}

        with patch("httpx.post", return_value=mock_resp):
            result = svc._infer_excel_column_roles_with_llm([{"col1": "val1"}])
        assert result == {}

    def test_recoverable_error_returns_empty(self):
        svc = _make_svc()
        svc.ai_service = MagicMock()
        svc.ai_service.api_key = "test_key"
        svc.ai_service.api_url = "http://localhost"
        svc.ai_service.model = "test_model"

        with patch("httpx.post", side_effect=RuntimeError("network error")):
            result = svc._infer_excel_column_roles_with_llm([{"col1": "val1"}])
        assert result == {}

    def test_successful_response(self):
        svc = _make_svc()
        svc.ai_service = MagicMock()
        svc.ai_service.api_key = "test_key"
        svc.ai_service.api_url = "http://localhost"
        svc.ai_service.model = "test_model"

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "unit_name": "客户",
                                "product_name": "产品",
                                "model_number": "型号",
                                "unit_price": "单价",
                            }
                        )
                    }
                }
            ]
        }

        records = [{"客户": "A", "产品": "B", "型号": "C", "单价": "1"}]
        with patch("httpx.post", return_value=mock_resp):
            result = svc._infer_excel_column_roles_with_llm(records)
        assert result["unit_name"] == "客户"
        assert result["product_name"] == "产品"
        assert result["model_number"] == "型号"
        assert result["unit_price"] == "单价"

    def test_json_with_code_block(self):
        svc = _make_svc()
        svc.ai_service = MagicMock()
        svc.ai_service.api_key = "test_key"
        svc.ai_service.api_url = "http://localhost"
        svc.ai_service.model = "test_model"

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": '```json\n{"unit_name": "客户", "product_name": "", "model_number": "", "unit_price": ""}\n```'
                    }
                }
            ]
        }

        records = [{"客户": "A"}]
        with patch("httpx.post", return_value=mock_resp):
            result = svc._infer_excel_column_roles_with_llm(records)
        assert result["unit_name"] == "客户"

    def test_unknown_column_filtered(self):
        svc = _make_svc()
        svc.ai_service = MagicMock()
        svc.ai_service.api_key = "test_key"
        svc.ai_service.api_url = "http://localhost"
        svc.ai_service.model = "test_model"

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "unit_name": "nonexistent_column",
                                "product_name": "",
                                "model_number": "",
                                "unit_price": "",
                            }
                        )
                    }
                }
            ]
        }

        records = [{"客户": "A"}]
        with patch("httpx.post", return_value=mock_resp):
            result = svc._infer_excel_column_roles_with_llm(records)
        # nonexistent_column not in keys → empty
        assert result["unit_name"] == ""

    def test_env_base_url_used(self):
        svc = _make_svc()
        svc.ai_service = MagicMock()
        svc.ai_service.api_key = "test_key"
        svc.ai_service.api_url = ""  # empty, should use env_base_url
        svc.ai_service.model = "test_model"

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"choices": [{"message": {"content": ""}}]}

        with (
            patch(
                "app.infrastructure.llm.providers.credentials.resolve_openai_env_credentials",
                return_value=("env_key", "http://env-base"),
            ),
            patch(
                "app.infrastructure.llm.providers.credentials.default_chat_completions_url",
                return_value="http://default",
            ),
            patch(
                "app.infrastructure.llm.providers.credentials.resolve_default_chat_model",
                return_value="env_model",
            ),
            patch("httpx.post", return_value=mock_resp) as mock_post,
        ):
            svc._infer_excel_column_roles_with_llm([{"col1": "val1"}])
        # Should use env_base_url + /chat/completions
        call_args = mock_post.call_args
        assert "env-base/chat/completions" in call_args.args[0]


# ---------------------------------------------------------------------------
# _format_workflow_run_response — additional branches
# ---------------------------------------------------------------------------


class TestFormatWorkflowRunResponseBranchCov:
    """_format_workflow_run_response additional branch tests."""

    def test_with_thinking_steps(self):
        svc = _make_svc()
        plan = _make_plan(todo_steps=["step1", "step2"])
        run_result = _make_run_result(success=True, node_results=[])

        result = svc._format_workflow_run_response(
            plan, run_result, thinking_steps="thinking...", user_message="msg"
        )
        assert "thinking..." in result["response"]
        assert "TODO:" in result["response"]
        assert "step1" in result["response"]

    def test_failed_node_with_retryable_and_retries(self):
        svc = _make_svc()
        plan = _make_plan()
        node_result = _make_node_result(
            success=False,
            error="timeout",
            retryable=True,
            retries=3,
        )
        run_result = _make_run_result(success=False, node_results=[node_result])

        result = svc._format_workflow_run_response(plan, run_result)
        assert "已自动重试: 3 次" in result["response"]

    def test_failed_node_not_retryable(self):
        svc = _make_svc()
        plan = _make_plan()
        node_result = _make_node_result(
            success=False,
            error="not allowed",
            retryable=False,
            retries=0,
        )
        run_result = _make_run_result(success=False, node_results=[node_result])

        result = svc._format_workflow_run_response(plan, run_result)
        assert "未自动重试" in result["response"]

    def test_failed_node_with_recovery_hint(self):
        svc = _make_svc()
        plan = _make_plan()
        node_result = _make_node_result(
            success=False,
            error="error",
            retryable=False,
            recovery_hint="try again later",
        )
        run_result = _make_run_result(success=False, node_results=[node_result])

        result = svc._format_workflow_run_response(plan, run_result)
        assert "恢复建议: try again later" in result["response"]

    def test_failed_node_non_string_recovery_hint(self):
        svc = _make_svc()
        plan = _make_plan()
        node_result = _make_node_result(
            success=False,
            error="error",
            recovery_hint=None,  # type: ignore[arg-type]
        )
        run_result = _make_run_result(success=False, node_results=[node_result])

        result = svc._format_workflow_run_response(plan, run_result)
        # Should not crash, hint should be empty
        assert "恢复建议" not in result["response"]

    def test_failed_node_retries_invalid_value(self):
        svc = _make_svc()
        plan = _make_plan()
        node_result = _make_node_result(
            success=False,
            error="error",
            retryable=True,
            retries="invalid",  # type: ignore[arg-type]
        )
        run_result = _make_run_result(success=False, node_results=[node_result])

        result = svc._format_workflow_run_response(plan, run_result)
        # retries should be 0, so no "已自动重试" line
        assert "已自动重试" not in result["response"]

    def test_with_run_result_message(self):
        svc = _make_svc()
        plan = _make_plan()
        run_result = _make_run_result(success=True, message="custom message", node_results=[])

        result = svc._format_workflow_run_response(plan, run_result)
        assert "说明: custom message" in result["response"]

    def test_products_query_success_with_rows(self):
        svc = _make_svc()
        plan = _make_plan()
        node_result = _make_node_result(
            success=True,
            tool_id="products",
            action="query",
            output={
                "data": [
                    {"model_number": "A001", "name": "Product A", "price": 10.5, "unit": "桶"},
                ]
            },
        )
        run_result = _make_run_result(success=True, node_results=[node_result])

        result = svc._format_workflow_run_response(plan, run_result)
        assert "产品库命中 1 条" in result["response"]
        assert "A001" in result["response"]
        assert "autoAction" in result

    def test_products_query_success_with_non_dict_row(self):
        svc = _make_svc()
        plan = _make_plan()
        node_result = _make_node_result(
            success=True,
            tool_id="products",
            action="query",
            output={"data": ["not a dict", {"model_number": "A002"}]},
        )
        run_result = _make_run_result(success=True, node_results=[node_result])

        result = svc._format_workflow_run_response(plan, run_result)
        assert "产品库命中 2 条" in result["response"]

    def test_products_query_success_no_query_string(self):
        svc = _make_svc()
        plan = _make_plan()
        node_result = _make_node_result(
            success=True,
            tool_id="products",
            action="query",
            output={"data": []},
        )
        run_result = _make_run_result(success=True, node_results=[node_result])

        with patch.object(svc, "_workflow_products_float_query", return_value=""):
            result = svc._format_workflow_run_response(plan, run_result, user_message="")
        assert "已为你打开产品副窗" in result["response"]
        assert "autoAction" in result

    def test_other_tool_success(self):
        svc = _make_svc()
        plan = _make_plan()
        node_result = _make_node_result(
            success=True,
            tool_id="customers",
            action="query",
            output={"data": [{"customer_name": "A"}]},
        )
        run_result = _make_run_result(success=True, node_results=[node_result])

        with patch.object(
            svc, "_format_workflow_tool_success_line", return_value=["- n1: success"]
        ):
            result = svc._format_workflow_run_response(plan, run_result)
        assert "- n1: success" in result["response"]

    def test_final_context_not_dict(self):
        svc = _make_svc()
        plan = _make_plan()
        run_result = _make_run_result(
            success=True,
            node_results=[],
            final_context="not dict",  # type: ignore[arg-type]
        )

        result = svc._format_workflow_run_response(plan, run_result)
        # Should not crash
        assert result["success"] is True
        assert result["data"]["data"]["workflow_status"] == {}

    def test_with_normal_slot_dispatch_overlay(self):
        svc = _make_svc()
        plan = _make_plan()
        node_result = _make_node_result(
            success=True,
            tool_id="normal_slot_dispatch",
            output={
                "success": True,
                "response": "overlay response",
                "autoAction": {"type": "show_products_float"},
            },
        )
        run_result = _make_run_result(success=True, node_results=[node_result])

        result = svc._format_workflow_run_response(plan, run_result)
        assert result["response"] == "overlay response"
        assert result["autoAction"] == {"type": "show_products_float"}


# ---------------------------------------------------------------------------
# process_chat — error branches
# ---------------------------------------------------------------------------


class TestProcessChatErrorBranches:
    """process_chat error handling branches."""

    def test_empty_message_returns_error(self):
        svc = _make_svc()
        result = svc.process_chat("u1", "", None, None, None)
        assert result["success"] is False
        assert "不能为空" in result["message"]

    def test_none_message_returns_error(self):
        svc = _make_svc()
        result = svc.process_chat("u1", None, None, None, None)  # type: ignore[arg-type]
        assert result["success"] is False
        assert "不能为空" in result["message"]

    def test_connection_error_fallback(self):
        svc = _make_svc()
        with (
            patch("app.neuro_bus.application_neuro_bridge.neuro_notify_chat_received"),
            patch("app.neuro_bus.application_neuro_bridge.neuro_notify_chat_completed"),
            patch.object(svc, "_inject_excel_vector_context", return_value={}),
            patch.object(svc, "_handle_confirmation_flow"),
            patch.object(svc, "_try_handle_dynamic_workflow", return_value=None),
            patch.object(svc, "_persist_chat_turn"),
            patch.object(svc.ai_service, "chat", new_callable=AsyncMock) as mock_chat,
        ):
            async def raise_conn_error(*args, **kwargs):
                raise ConnectionError("connection failed")

            mock_chat.side_effect = raise_conn_error
            result = svc.process_chat("u1", "查产品", None, None, None)
        assert result["success"] is False
        assert "AI 服务连接失败" in result["response"]

    def test_timeout_error_fallback(self):
        svc = _make_svc()
        with (
            patch("app.neuro_bus.application_neuro_bridge.neuro_notify_chat_received"),
            patch("app.neuro_bus.application_neuro_bridge.neuro_notify_chat_completed"),
            patch.object(svc, "_inject_excel_vector_context", return_value={}),
            patch.object(svc, "_handle_confirmation_flow"),
            patch.object(svc, "_try_handle_dynamic_workflow", return_value=None),
            patch.object(svc, "_persist_chat_turn"),
            patch.object(svc.ai_service, "chat", new_callable=AsyncMock) as mock_chat,
        ):
            async def raise_timeout(*args, **kwargs):
                raise TimeoutError("timed out")

            mock_chat.side_effect = raise_timeout
            result = svc.process_chat("u1", "查产品", None, None, None)
        assert result["success"] is False
        assert "超时" in result["response"]

    def test_api_key_error_fallback(self):
        svc = _make_svc()
        with (
            patch("app.neuro_bus.application_neuro_bridge.neuro_notify_chat_received"),
            patch("app.neuro_bus.application_neuro_bridge.neuro_notify_chat_completed"),
            patch.object(svc, "_inject_excel_vector_context", return_value={}),
            patch.object(svc, "_handle_confirmation_flow"),
            patch.object(svc, "_try_handle_dynamic_workflow", return_value=None),
            patch.object(svc, "_persist_chat_turn"),
            patch.object(svc.ai_service, "chat", new_callable=AsyncMock) as mock_chat,
        ):
            async def raise_apikey_error(*args, **kwargs):
                raise RuntimeError("api_key invalid")

            mock_chat.side_effect = raise_apikey_error
            result = svc.process_chat("u1", "查产品", None, None, None)
        assert result["success"] is False
        assert "API Key" in result["response"]

    def test_apikey_case_insensitive_error(self):
        svc = _make_svc()
        with (
            patch("app.neuro_bus.application_neuro_bridge.neuro_notify_chat_received"),
            patch("app.neuro_bus.application_neuro_bridge.neuro_notify_chat_completed"),
            patch.object(svc, "_inject_excel_vector_context", return_value={}),
            patch.object(svc, "_handle_confirmation_flow"),
            patch.object(svc, "_try_handle_dynamic_workflow", return_value=None),
            patch.object(svc, "_persist_chat_turn"),
            patch.object(svc.ai_service, "chat", new_callable=AsyncMock) as mock_chat,
        ):
            async def raise_apikey_error(*args, **kwargs):
                raise RuntimeError("APIKEY not set")

            mock_chat.side_effect = raise_apikey_error
            result = svc.process_chat("u1", "查产品", None, None, None)
        assert result["success"] is False
        assert "API Key" in result["response"]

    def test_connection_in_error_fallback(self):
        svc = _make_svc()
        with (
            patch("app.neuro_bus.application_neuro_bridge.neuro_notify_chat_received"),
            patch("app.neuro_bus.application_neuro_bridge.neuro_notify_chat_completed"),
            patch.object(svc, "_inject_excel_vector_context", return_value={}),
            patch.object(svc, "_handle_confirmation_flow"),
            patch.object(svc, "_try_handle_dynamic_workflow", return_value=None),
            patch.object(svc, "_persist_chat_turn"),
            patch.object(svc.ai_service, "chat", new_callable=AsyncMock) as mock_chat,
        ):
            async def raise_conn_error(*args, **kwargs):
                raise RuntimeError("connection refused")

            mock_chat.side_effect = raise_conn_error
            result = svc.process_chat("u1", "查产品", None, None, None)
        assert result["success"] is False
        assert "无法连接" in result["response"]

    def test_generic_error_fallback(self):
        svc = _make_svc()
        with (
            patch("app.neuro_bus.application_neuro_bridge.neuro_notify_chat_received"),
            patch("app.neuro_bus.application_neuro_bridge.neuro_notify_chat_completed"),
            patch.object(svc, "_inject_excel_vector_context", return_value={}),
            patch.object(svc, "_handle_confirmation_flow"),
            patch.object(svc, "_try_handle_dynamic_workflow", return_value=None),
            patch.object(svc, "_persist_chat_turn"),
            patch.object(svc.ai_service, "chat", new_callable=AsyncMock) as mock_chat,
        ):
            async def raise_generic_error(*args, **kwargs):
                raise RuntimeError("something went wrong")

            mock_chat.side_effect = raise_generic_error
            result = svc.process_chat("u1", "查产品", None, None, None)
        assert result["success"] is False
        assert "AI 服务暂时不可用" in result["response"]

    def test_workflow_result_returns_finalized(self):
        svc = _make_svc()
        workflow_result = {"success": True, "response": "workflow done"}
        with (
            patch("app.neuro_bus.application_neuro_bridge.neuro_notify_chat_received"),
            patch("app.neuro_bus.application_neuro_bridge.neuro_notify_chat_completed"),
            patch.object(svc, "_inject_excel_vector_context", return_value={}),
            patch.object(svc, "_handle_confirmation_flow"),
            patch.object(
                svc, "_try_handle_dynamic_workflow", return_value=workflow_result
            ),
            patch.object(svc, "_persist_chat_turn"),
        ):
            result = svc.process_chat("u1", "查产品", None, None, None)
        assert result == workflow_result

    def test_with_file_context_excel_analysis(self):
        svc = _make_svc()
        file_context = {"file_path": "/tmp/test.xlsx", "sheet_name": "Sheet1"}
        with (
            patch("app.neuro_bus.application_neuro_bridge.neuro_notify_chat_received"),
            patch("app.neuro_bus.application_neuro_bridge.neuro_notify_chat_completed"),
            patch.object(svc, "_inject_excel_vector_context", return_value={}),
            patch.object(svc, "_handle_confirmation_flow"),
            patch.object(svc, "_try_handle_dynamic_workflow", return_value=None),
            patch.object(svc, "_persist_chat_turn"),
            patch.object(svc.ai_service, "chat", new_callable=AsyncMock) as mock_chat,
        ):
            async def mock_chat_impl(*args, **kwargs):
                return {"action": "test", "response": "ok"}

            mock_chat.side_effect = mock_chat_impl
            result = svc.process_chat("u1", "查产品", None, None, file_context)
        # Result wraps ai_result in data; check nested or top-level
        assert result.get("success") is True or result.get("action") == "test"

    def test_with_file_context_original_file_path(self):
        svc = _make_svc()
        file_context = {"original_file_path": "/tmp/original.xlsx"}
        with (
            patch("app.neuro_bus.application_neuro_bridge.neuro_notify_chat_received"),
            patch("app.neuro_bus.application_neuro_bridge.neuro_notify_chat_completed"),
            patch.object(svc, "_inject_excel_vector_context", return_value={}),
            patch.object(svc, "_handle_confirmation_flow"),
            patch.object(svc, "_try_handle_dynamic_workflow", return_value=None),
            patch.object(svc, "_persist_chat_turn"),
            patch.object(svc.ai_service, "chat", new_callable=AsyncMock) as mock_chat,
        ):
            async def mock_chat_impl(*args, **kwargs):
                return {"action": "test"}

            mock_chat.side_effect = mock_chat_impl
            result = svc.process_chat("u1", "查产品", None, None, file_context)
        # Should not crash
        assert "action" in result or "success" in result

    def test_persist_error_does_not_break_response(self):
        svc = _make_svc()
        with (
            patch("app.neuro_bus.application_neuro_bridge.neuro_notify_chat_received"),
            patch("app.neuro_bus.application_neuro_bridge.neuro_notify_chat_completed"),
            patch.object(svc, "_inject_excel_vector_context", return_value={}),
            patch.object(svc, "_handle_confirmation_flow"),
            patch.object(svc, "_try_handle_dynamic_workflow", return_value=None),
            patch.object(
                svc, "_persist_chat_turn", side_effect=RuntimeError("persist failed")
            ),
            patch.object(svc.ai_service, "chat", new_callable=AsyncMock) as mock_chat,
        ):
            async def mock_chat_impl(*args, **kwargs):
                return {"action": "test", "response": "ok"}

            mock_chat.side_effect = mock_chat_impl
            result = svc.process_chat("u1", "查产品", None, None, None)
        # Response should still be returned despite persist error
        assert result.get("success") is True or result.get("response") == "ok"


# ---------------------------------------------------------------------------
# _default_purchase_unit_for_import — additional branches
# ---------------------------------------------------------------------------


class TestDefaultPurchaseUnitForImportBranchCov:
    """_default_purchase_unit_for_import additional branch tests."""

    def test_request_context_hint(self):
        rc = {"excel_customer_hint": "客户A"}
        result = AIChatApplicationService._default_purchase_unit_for_import({}, {}, rc)
        assert result == "客户A"

    def test_request_context_empty_hint_falls_through(self):
        rc = {"excel_customer_hint": ""}
        with patch.object(
            AIChatApplicationService, "_guess_default_purchase_unit", return_value="guessed"
        ):
            result = AIChatApplicationService._default_purchase_unit_for_import({}, {}, rc)
        assert result == "guessed"

    def test_preview_data_customer_hint(self):
        pd = {"customer_hint": "客户B"}
        with patch.object(
            AIChatApplicationService, "_guess_default_purchase_unit", return_value="guessed"
        ):
            result = AIChatApplicationService._default_purchase_unit_for_import({}, pd, None)
        assert result == "客户B"

    def test_preview_data_document_customer(self):
        pd = {"document_customer": "客户C"}
        with patch.object(
            AIChatApplicationService, "_guess_default_purchase_unit", return_value="guessed"
        ):
            result = AIChatApplicationService._default_purchase_unit_for_import({}, pd, None)
        assert result == "客户C"

    def test_excel_analysis_customer_hint(self):
        ea = {"customer_hint": "客户D"}
        with patch.object(
            AIChatApplicationService, "_guess_default_purchase_unit", return_value="guessed"
        ):
            result = AIChatApplicationService._default_purchase_unit_for_import(ea, {}, None)
        assert result == "客户D"

    def test_grid_hint_from_preview(self):
        with (
            patch.object(
                AIChatApplicationService,
                "_customer_hint_from_preview_grid",
                return_value="GridCustomer",
            ),
            patch.object(
                AIChatApplicationService, "_guess_default_purchase_unit", return_value="guessed"
            ),
        ):
            result = AIChatApplicationService._default_purchase_unit_for_import({}, {}, None)
        assert result == "GridCustomer"

    def test_file_path_not_file_falls_to_guess(self):
        ea = {"file_path": "/nonexistent/path.xlsx"}
        with (
            patch.object(
                AIChatApplicationService,
                "_customer_hint_from_preview_grid",
                return_value="",
            ),
            patch.object(
                AIChatApplicationService, "_guess_default_purchase_unit", return_value="guessed"
            ),
        ):
            result = AIChatApplicationService._default_purchase_unit_for_import(ea, {}, None)
        assert result == "guessed"

    def test_file_path_exists_extract_customer_hint(self, tmp_path: Path):
        excel_file = tmp_path / "test.xlsx"
        excel_file.write_bytes(b"fake")

        ea = {"file_path": str(excel_file)}
        with (
            patch.object(
                AIChatApplicationService,
                "_customer_hint_from_preview_grid",
                return_value="",
            ),
            patch(
                "app.application.template_grid_core._extract_customer_hint_from_excel",
                return_value="ExtractedCustomer",
            ),
            patch.object(
                AIChatApplicationService, "_guess_default_purchase_unit", return_value="guessed"
            ),
        ):
            result = AIChatApplicationService._default_purchase_unit_for_import(ea, {}, None)
        assert result == "ExtractedCustomer"

    def test_extract_customer_hint_error_falls_to_guess(self, tmp_path: Path):
        excel_file = tmp_path / "test.xlsx"
        excel_file.write_bytes(b"fake")

        ea = {"file_path": str(excel_file)}
        with (
            patch.object(
                AIChatApplicationService,
                "_customer_hint_from_preview_grid",
                return_value="",
            ),
            patch(
                "app.application.template_grid_core._extract_customer_hint_from_excel",
                side_effect=RuntimeError("extract failed"),
            ),
            patch.object(
                AIChatApplicationService, "_guess_default_purchase_unit", return_value="guessed"
            ),
        ):
            result = AIChatApplicationService._default_purchase_unit_for_import(ea, {}, None)
        assert result == "guessed"

    def test_extract_customer_hint_empty_falls_to_guess(self, tmp_path: Path):
        excel_file = tmp_path / "test.xlsx"
        excel_file.write_bytes(b"fake")

        ea = {"file_path": str(excel_file)}
        with (
            patch.object(
                AIChatApplicationService,
                "_customer_hint_from_preview_grid",
                return_value="",
            ),
            patch(
                "app.application.template_grid_core._extract_customer_hint_from_excel",
                return_value="",
            ),
            patch.object(
                AIChatApplicationService, "_guess_default_purchase_unit", return_value="guessed"
            ),
        ):
            result = AIChatApplicationService._default_purchase_unit_for_import(ea, {}, None)
        assert result == "guessed"

    def test_no_file_path_falls_to_guess(self):
        with (
            patch.object(
                AIChatApplicationService,
                "_customer_hint_from_preview_grid",
                return_value="",
            ),
            patch.object(
                AIChatApplicationService, "_guess_default_purchase_unit", return_value="guessed"
            ),
        ):
            result = AIChatApplicationService._default_purchase_unit_for_import({}, {}, None)
        assert result == "guessed"
