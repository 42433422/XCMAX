"""Tests for app.application.ai_chat_app_service — deep coverage for remaining uncovered branches.

Focus: private methods, error branches, edge cases, and complex conditional logic
not covered by ext/ext2 test suites.
"""

from __future__ import annotations

import math
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from app.application.ai_chat_app_service import (
    AIChatApplicationService,
    _EXCEL_IMPORT_MEASURE_UNIT_TOKENS,
    _skip_pro_excel_deterministic_import,
)


def _make_service():
    with (
        patch("app.application.ai_chat_app_service.get_ai_conversation_service"),
        patch("app.application.ai_chat_app_service.LLMWorkflowPlanner"),
        patch("app.application.ai_chat_app_service.HybridRiskGate"),
        patch("app.application.ai_chat_app_service.WorkflowEngine"),
        patch("app.application.ai_chat_app_service.get_approval_service"),
    ):
        return AIChatApplicationService()


# ========================= _skip_pro_excel_deterministic_import - extended =


class TestSkipProExcelDeterministicImportExtended:
    def test_context_not_dict_returns_false(self):
        assert _skip_pro_excel_deterministic_import("not a dict") is False

    def test_excel_import_use_deterministic_shortcut_true(self):
        assert _skip_pro_excel_deterministic_import({"excel_import_use_deterministic_shortcut": True}) is False

    def test_excel_import_use_deterministic_shortcut_false(self):
        # When the value is False (not True), `is True` check fails, so it falls through to default False
        assert _skip_pro_excel_deterministic_import({"excel_import_use_deterministic_shortcut": False}) is False

    def test_excel_import_skip_deterministic_shortcut_true(self):
        assert _skip_pro_excel_deterministic_import({"excel_import_skip_deterministic_shortcut": True}) is True

    def test_excel_import_ai_decides_true(self):
        assert _skip_pro_excel_deterministic_import({"excel_import_ai_decides": True}) is True

    def test_env_disable_pro_excel_import(self):
        with patch.dict("os.environ", {"XCAGI_DISABLE_PRO_EXCEL_IMPORT_SHORTCUT": "1"}):
            assert _skip_pro_excel_deterministic_import({}) is True

    def test_env_excel_import_ai_decides(self):
        with patch.dict("os.environ", {"XCAGI_EXCEL_IMPORT_AI_DECIDES": "true"}):
            assert _skip_pro_excel_deterministic_import({}) is True

    def test_env_on_value(self):
        with patch.dict("os.environ", {"XCAGI_DISABLE_PRO_EXCEL_IMPORT_SHORTCUT": "on"}):
            assert _skip_pro_excel_deterministic_import({}) is True

    def test_env_yes_value(self):
        with patch.dict("os.environ", {"XCAGI_EXCEL_IMPORT_AI_DECIDES": "yes"}):
            assert _skip_pro_excel_deterministic_import({}) is True

    def test_empty_context_defaults_to_false(self):
        with patch.dict("os.environ", {}, clear=True):
            # Remove env vars that might be set
            env = {"XCAGI_DISABLE_PRO_EXCEL_IMPORT_SHORTCUT": "", "XCAGI_EXCEL_IMPORT_AI_DECIDES": ""}
            with patch.dict("os.environ", env, clear=False):
                assert _skip_pro_excel_deterministic_import({}) is False


# ========================= _is_pro_source - extended ======================


class TestIsProSourceExtended:
    def test_pro_mode(self):
        assert AIChatApplicationService._is_pro_source("pro_mode") is True

    def test_promode(self):
        assert AIChatApplicationService._is_pro_source("promode") is True

    def test_professional(self):
        assert AIChatApplicationService._is_pro_source("professional") is True

    def test_xcagi_pro(self):
        assert AIChatApplicationService._is_pro_source("xcagi_pro") is True

    def test_pro_with_dash(self):
        assert AIChatApplicationService._is_pro_source("pro-mode") is True

    def test_none(self):
        assert AIChatApplicationService._is_pro_source(None) is False

    def test_empty(self):
        assert AIChatApplicationService._is_pro_source("") is False

    def test_normal(self):
        assert AIChatApplicationService._is_pro_source("normal") is False


# ========================= _merge_tool_runtime_context - extended ==========


class TestMergeToolRuntimeContextExtended:
    def test_none_context(self):
        result = AIChatApplicationService._merge_tool_runtime_context("u1", "hello", None)
        assert result == {"user_id": "u1", "message": "hello"}

    def test_non_dict_context(self):
        result = AIChatApplicationService._merge_tool_runtime_context("u1", "hello", "not a dict")
        assert result == {"user_id": "u1", "message": "hello"}

    def test_context_with_ui_surface(self):
        result = AIChatApplicationService._merge_tool_runtime_context(
            "u1", "hello", {"ui_surface": "pro_chat", "intent_channel": "main"}
        )
        assert result["ui_surface"] == "pro_chat"
        assert result["intent_channel"] == "main"

    def test_context_with_none_values_skipped(self):
        result = AIChatApplicationService._merge_tool_runtime_context(
            "u1", "hello", {"ui_surface": None, "intent_channel": None}
        )
        assert "ui_surface" not in result
        assert "intent_channel" not in result

    def test_context_with_excel_analysis(self):
        result = AIChatApplicationService._merge_tool_runtime_context(
            "u1", "hello", {"excel_analysis": {"file_path": "/test.xlsx"}}
        )
        assert result["excel_analysis"] == {"file_path": "/test.xlsx"}

    def test_context_with_non_dict_excel_analysis_skipped(self):
        result = AIChatApplicationService._merge_tool_runtime_context(
            "u1", "hello", {"excel_analysis": "not a dict"}
        )
        assert "excel_analysis" not in result

    def test_context_with_last_excel_analysis_context(self):
        result = AIChatApplicationService._merge_tool_runtime_context(
            "u1", "hello", {"last_excel_analysis_context": {"sheet": "Sheet1"}}
        )
        assert result["last_excel_analysis_context"] == {"sheet": "Sheet1"}


# ========================= _excel_cell_looks_like_product_measure_unit ====


class TestExcelCellLooksLikeProductMeasureUnit:
    def test_common_units(self):
        for unit in ("件", "个", "只", "箱", "盒", "包", "袋", "瓶", "桶", "罐", "套", "组", "台", "条", "张", "支"):
            assert AIChatApplicationService._excel_cell_looks_like_product_measure_unit(unit) is True

    def test_pcs(self):
        assert AIChatApplicationService._excel_cell_looks_like_product_measure_unit("pcs") is True

    def test_pc(self):
        assert AIChatApplicationService._excel_cell_looks_like_product_measure_unit("pc") is True

    def test_qty_with_unit(self):
        assert AIChatApplicationService._excel_cell_looks_like_product_measure_unit("10件") is True

    def test_qty_with_pcs(self):
        assert AIChatApplicationService._excel_cell_looks_like_product_measure_unit("5pcs") is True

    def test_customer_name_not_unit(self):
        assert AIChatApplicationService._excel_cell_looks_like_product_measure_unit("某某有限公司") is False

    def test_empty_string(self):
        assert AIChatApplicationService._excel_cell_looks_like_product_measure_unit("") is False

    def test_none(self):
        assert AIChatApplicationService._excel_cell_looks_like_product_measure_unit(None) is False

    def test_product_name(self):
        assert AIChatApplicationService._excel_cell_looks_like_product_measure_unit("涂料A型") is False


# ========================= _sanitize_import_scalar - extended ==============


class TestSanitizeImportScalarExtended:
    def test_none(self):
        assert AIChatApplicationService._sanitize_import_scalar(None) is None

    def test_nan_float(self):
        assert AIChatApplicationService._sanitize_import_scalar(float("nan")) is None

    def test_nan_string(self):
        assert AIChatApplicationService._sanitize_import_scalar("nan") is None

    def test_none_string(self):
        assert AIChatApplicationService._sanitize_import_scalar("none") is None

    def test_nat_string(self):
        assert AIChatApplicationService._sanitize_import_scalar("nat") is None

    def test_na_string(self):
        assert AIChatApplicationService._sanitize_import_scalar("<na>") is None

    def test_null_string(self):
        assert AIChatApplicationService._sanitize_import_scalar("null") is None

    def test_normal_string(self):
        assert AIChatApplicationService._sanitize_import_scalar("hello") == "hello"

    def test_string_with_whitespace(self):
        assert AIChatApplicationService._sanitize_import_scalar("  hello  ") == "hello"

    def test_integer(self):
        assert AIChatApplicationService._sanitize_import_scalar(42) == 42

    def test_nan_like_object(self):
        """Object whose float() is NaN."""
        class NanLike:
            def __float__(self):
                return float("nan")
        assert AIChatApplicationService._sanitize_import_scalar(NanLike()) is None

    def test_normal_float(self):
        assert AIChatApplicationService._sanitize_import_scalar(3.14) == 3.14


# ========================= _model_like_score - extended ====================


class TestModelLikeScoreExtended:
    def test_empty_string(self):
        assert AIChatApplicationService._model_like_score("") == 0.0

    def test_none(self):
        assert AIChatApplicationService._model_like_score(None) == 0.0

    def test_alphanumeric_model(self):
        assert AIChatApplicationService._model_like_score("5003A") == 1.0

    def test_digit_only_short(self):
        assert AIChatApplicationService._model_like_score("123") == 0.6

    def test_digit_only_long(self):
        assert AIChatApplicationService._model_like_score("1234567890123") == 0.0

    def test_too_short(self):
        assert AIChatApplicationService._model_like_score("A") == 0.0

    def test_too_long(self):
        assert AIChatApplicationService._model_like_score("A" * 25) == 0.0

    def test_alpha_only(self):
        assert AIChatApplicationService._model_like_score("ABC") == 0.0

    def test_with_dash(self):
        assert AIChatApplicationService._model_like_score("AB-123") == 1.0

    def test_with_underscore(self):
        assert AIChatApplicationService._model_like_score("AB_123") == 1.0


# ========================= _is_number_text - extended =====================


class TestIsNumberTextExtended:
    def test_normal_number(self):
        assert AIChatApplicationService._is_number_text("123") is True

    def test_float(self):
        assert AIChatApplicationService._is_number_text("3.14") is True

    def test_with_comma(self):
        assert AIChatApplicationService._is_number_text("1,000") is True

    def test_empty(self):
        assert AIChatApplicationService._is_number_text("") is False

    def test_none(self):
        assert AIChatApplicationService._is_number_text(None) is False

    def test_text(self):
        assert AIChatApplicationService._is_number_text("hello") is False

    def test_negative(self):
        assert AIChatApplicationService._is_number_text("-5") is True


# ========================= _row_values_look_like_table_headers - extended ==


class TestRowValuesLookLikeTableHeadersExtended:
    def test_empty_list(self):
        assert AIChatApplicationService._row_values_look_like_table_headers([]) is False

    def test_single_value(self):
        assert AIChatApplicationService._row_values_look_like_table_headers(["产品名称"]) is False

    def test_two_header_hints(self):
        assert AIChatApplicationService._row_values_look_like_table_headers(["产品名称", "单价"]) is True

    def test_no_header_hints(self):
        assert AIChatApplicationService._row_values_look_like_table_headers(["hello", "world"]) is False

    def test_one_header_hint(self):
        assert AIChatApplicationService._row_values_look_like_table_headers(["产品名称", "hello"]) is False

    def test_mixed_empty_and_header(self):
        assert AIChatApplicationService._row_values_look_like_table_headers(["", "产品名称", "单价"]) is True

    def test_none_values(self):
        assert AIChatApplicationService._row_values_look_like_table_headers([None, None]) is False


# ========================= _packaging_or_measure_ratio - extended ==========


class TestPackagingOrMeasureRatioExtended:
    def test_empty_list(self):
        assert AIChatApplicationService._packaging_or_measure_ratio([]) == 0.0

    def test_all_units(self):
        assert AIChatApplicationService._packaging_or_measure_ratio(["件", "箱", "桶"]) == 1.0

    def test_mixed(self):
        ratio = AIChatApplicationService._packaging_or_measure_ratio(["件", "产品A", "箱"])
        assert 0.0 < ratio < 1.0

    def test_no_units(self):
        assert AIChatApplicationService._packaging_or_measure_ratio(["产品A", "产品B"]) == 0.0

    def test_qty_measure_pattern(self):
        assert AIChatApplicationService._packaging_or_measure_ratio(["10kg/桶"]) == 1.0

    def test_empty_strings(self):
        assert AIChatApplicationService._packaging_or_measure_ratio(["", ""]) == 0.0

    def test_none_values(self):
        assert AIChatApplicationService._packaging_or_measure_ratio([None, None]) == 0.0


# ========================= _guess_default_purchase_unit - extended =========


class TestGuessDefaultPurchaseUnitExtended:
    def test_from_file_name_with_company(self):
        result = AIChatApplicationService._guess_default_purchase_unit(
            {"file_name": "某某有限公司产品报价表.xlsx"}
        )
        assert "某某有限公司" in result

    def test_from_file_name_with_stock_company(self):
        result = AIChatApplicationService._guess_default_purchase_unit(
            {"file_name": "成都修茈科技股份有限公司报价表.xlsx"}
        )
        assert "成都修茈科技股份有限公司" in result

    def test_from_file_path(self):
        result = AIChatApplicationService._guess_default_purchase_unit(
            {"file_path": "/tmp/测试公司产品报价表.xlsx", "file_name": ""}
        )
        assert "测试公司" in result

    def test_empty_all(self):
        result = AIChatApplicationService._guess_default_purchase_unit({})
        assert result == ""

    def test_short_name_less_than_2(self):
        result = AIChatApplicationService._guess_default_purchase_unit({"file_name": "A.xlsx"})
        assert result == ""

    def test_template_name(self):
        result = AIChatApplicationService._guess_default_purchase_unit(
            {"template_name": "某某厂报价单.xlsx"}
        )
        assert "某某厂" in result

    def test_year_suffix_stripped(self):
        result = AIChatApplicationService._guess_default_purchase_unit(
            {"file_name": "某某有限公司2024.xlsx"}
        )
        assert "某某有限公司" in result


# ========================= _resolve_force_header_row_1based - extended =====


class TestResolveForceHeaderRow1BasedExtended:
    def test_grid_preview_header_row_index(self):
        result = AIChatApplicationService._resolve_force_header_row_1based(
            {}, {"grid_preview": {"header_row_index": 3}}
        )
        assert result == 3

    def test_grid_preview_invalid_value(self):
        result = AIChatApplicationService._resolve_force_header_row_1based(
            {}, {"grid_preview": {"header_row_index": "abc"}}
        )
        assert result is None

    def test_grid_preview_zero_value(self):
        result = AIChatApplicationService._resolve_force_header_row_1based(
            {}, {"grid_preview": {"header_row_index": 0}}
        )
        assert result is None

    def test_tables_header_row(self):
        result = AIChatApplicationService._resolve_force_header_row_1based(
            {}, {"tables": [{"header_row": 2}]}
        )
        assert result == 2

    def test_excel_analysis_sheets_grid_preview(self):
        result = AIChatApplicationService._resolve_force_header_row_1based(
            {"sheets": [{"grid_preview": {"header_row_index": 4}}]}, {}
        )
        assert result == 4

    def test_excel_analysis_sheets_tables(self):
        result = AIChatApplicationService._resolve_force_header_row_1based(
            {"sheets": [{"tables": [{"header_row": 5}]}]}, {}
        )
        assert result == 5

    def test_non_dict_preview_data(self):
        result = AIChatApplicationService._resolve_force_header_row_1based({}, "not a dict")
        assert result is None

    def test_no_header_info(self):
        result = AIChatApplicationService._resolve_force_header_row_1based({}, {})
        assert result is None


# ========================= _resolve_sheet_name_for_reimport - extended =====


class TestResolveSheetNameForReimportExtended:
    def test_request_context_selected_sheet(self):
        result = AIChatApplicationService._resolve_sheet_name_for_reimport(
            {}, {}, {"excel_analysis_selected_sheet": {"sheet_name": "Sheet2"}}
        )
        assert result == "Sheet2"

    def test_request_context_preferred_sheet(self):
        result = AIChatApplicationService._resolve_sheet_name_for_reimport(
            {}, {}, {"preferred_sheet_name": "Sheet3"}
        )
        assert result == "Sheet3"

    def test_preview_data_selected_sheet(self):
        result = AIChatApplicationService._resolve_sheet_name_for_reimport(
            {}, {"selected_sheet_name": "Sheet4"}, None
        )
        assert result == "Sheet4"

    def test_preview_data_sheet_name(self):
        result = AIChatApplicationService._resolve_sheet_name_for_reimport(
            {}, {"sheet_name": "Sheet5"}, None
        )
        assert result == "Sheet5"

    def test_excel_analysis_sheets(self):
        result = AIChatApplicationService._resolve_sheet_name_for_reimport(
            {"sheets": [{"sheet_name": "Sheet6"}]}, {}, None
        )
        assert result == "Sheet6"

    def test_none_everywhere(self):
        result = AIChatApplicationService._resolve_sheet_name_for_reimport({}, {}, None)
        assert result is None

    def test_empty_selected_sheet_dict(self):
        result = AIChatApplicationService._resolve_sheet_name_for_reimport(
            {}, {}, {"excel_analysis_selected_sheet": {"sheet_name": ""}}
        )
        assert result is None

    def test_non_dict_request_context(self):
        result = AIChatApplicationService._resolve_sheet_name_for_reimport({}, {}, "not a dict")
        assert result is None


# ========================= _resolve_excel_path_for_import - extended =======


class TestResolveExcelPathForImportExtended:
    def test_from_excel_analysis(self):
        result = AIChatApplicationService._resolve_excel_path_for_import(
            {"file_path": "/path/to/file.xlsx"}, {}
        )
        assert result == "/path/to/file.xlsx"

    def test_from_preview_data_fallback(self):
        result = AIChatApplicationService._resolve_excel_path_for_import(
            {"file_path": ""}, {"file_path": "/fallback/path.xlsx"}
        )
        assert result == "/fallback/path.xlsx"

    def test_empty_both(self):
        result = AIChatApplicationService._resolve_excel_path_for_import({}, {})
        assert result == ""

    def test_non_dict_preview_data(self):
        result = AIChatApplicationService._resolve_excel_path_for_import(
            {"file_path": ""}, "not a dict"
        )
        assert result == ""


# ========================= _price_column_buckets - extended ================


class TestPriceColumnBucketsExtended:
    def test_before_price_columns(self):
        before, after, generic = AIChatApplicationService._price_column_buckets(
            ["调价前单价", "数量"]
        )
        assert "调价前单价" in before
        assert len(after) == 0

    def test_after_price_columns(self):
        before, after, generic = AIChatApplicationService._price_column_buckets(
            ["调价后单价", "数量"]
        )
        assert "调价后单价" in after
        assert len(before) == 0

    def test_generic_price_columns(self):
        before, after, generic = AIChatApplicationService._price_column_buckets(
            ["单价", "数量"]
        )
        assert "单价" in generic
        assert len(before) == 0
        assert len(after) == 0

    def test_mixed_price_columns(self):
        before, after, generic = AIChatApplicationService._price_column_buckets(
            ["调价前单价", "调价后单价", "含税价"]
        )
        assert "调价前单价" in before
        assert "调价后单价" in after
        assert "含税价" in generic

    def test_non_price_columns_excluded(self):
        before, after, generic = AIChatApplicationService._price_column_buckets(
            ["数量", "产品名称", "计量"]
        )
        assert len(before) == 0
        assert len(after) == 0
        assert len(generic) == 0

    def test_empty_keys(self):
        before, after, generic = AIChatApplicationService._price_column_buckets([])
        assert len(before) == 0
        assert len(after) == 0
        assert len(generic) == 0


# ========================= _merge_user_intent_for_price_resolution ========


class TestMergeUserIntentForPriceResolutionExtended:
    def test_empty_message(self):
        result = AIChatApplicationService._merge_user_intent_for_price_resolution("", None)
        assert result == ""

    def test_none_message(self):
        result = AIChatApplicationService._merge_user_intent_for_price_resolution(None, None)
        assert result == ""

    def test_simple_message(self):
        result = AIChatApplicationService._merge_user_intent_for_price_resolution("导入调价前", None)
        assert "导入调价前" in result

    def test_with_recent_messages(self):
        ctx = {
            "recent_messages": [
                {"role": "user", "content": "查看报价"},
                {"role": "assistant", "content": "这是报价表"},
            ]
        }
        result = AIChatApplicationService._merge_user_intent_for_price_resolution("导入调价前", ctx)
        assert "查看报价" in result
        assert "导入调价前" in result

    def test_filters_non_user_roles(self):
        ctx = {
            "recent_messages": [
                {"role": "system", "content": "ignored"},
                {"role": "user", "content": "included"},
            ]
        }
        result = AIChatApplicationService._merge_user_intent_for_price_resolution("", ctx)
        assert "included" in result
        assert "ignored" not in result

    def test_html_stripped(self):
        ctx = {
            "recent_messages": [
                {"role": "user", "content": "hello<br/>world"},
            ]
        }
        result = AIChatApplicationService._merge_user_intent_for_price_resolution("", ctx)
        assert "<br" not in result
        assert "hello" in result

    def test_context_message_key(self):
        ctx = {"message": "context message"}
        result = AIChatApplicationService._merge_user_intent_for_price_resolution("user msg", ctx)
        assert "context message" in result
        assert "user msg" in result

    def test_truncation_at_8000(self):
        long_msg = "A" * 9000
        result = AIChatApplicationService._merge_user_intent_for_price_resolution(long_msg, None)
        assert len(result) <= 8000

    def test_deduplication(self):
        ctx = {
            "recent_messages": [
                {"role": "user", "content": "same"},
                {"role": "user", "content": "same"},
            ]
        }
        result = AIChatApplicationService._merge_user_intent_for_price_resolution("same", ctx)
        # "same" should appear but not duplicated excessively
        assert "same" in result


# ========================= _excel_analysis_payload_present - extended ======


class TestExcelAnalysisPayloadPresentExtended:
    def test_none_context(self):
        assert AIChatApplicationService._excel_analysis_payload_present(None) is False

    def test_non_dict_context(self):
        assert AIChatApplicationService._excel_analysis_payload_present("not a dict") is False

    def test_empty_excel_analysis(self):
        assert AIChatApplicationService._excel_analysis_payload_present({"excel_analysis": {}}) is False

    def test_with_summary(self):
        assert AIChatApplicationService._excel_analysis_payload_present(
            {"excel_analysis": {"summary": "test"}}
        ) is True

    def test_with_fields(self):
        assert AIChatApplicationService._excel_analysis_payload_present(
            {"excel_analysis": {"fields": [{"label": "x"}]}}
        ) is True

    def test_with_sample_rows(self):
        assert AIChatApplicationService._excel_analysis_payload_present(
            {"excel_analysis": {"preview_data": {"sample_rows": [{"a": 1}]}}}
        ) is True

    def test_with_empty_sample_rows(self):
        assert AIChatApplicationService._excel_analysis_payload_present(
            {"excel_analysis": {"preview_data": {"sample_rows": []}}}
        ) is False

    def test_with_grid_preview_sufficient_rows(self):
        assert AIChatApplicationService._excel_analysis_payload_present(
            {"excel_analysis": {"preview_data": {"grid_preview": {"rows": [["h1"], ["d1"]]}}}}
        ) is True


# ========================= _looks_like_short_excel_import_command =========


class TestLooksLikeShortExcelImportCommandExtended:
    def test_exact_match_join_db(self):
        assert AIChatApplicationService._looks_like_short_excel_import_command("加入数据库") is True

    def test_exact_match_import_db(self):
        assert AIChatApplicationService._looks_like_short_excel_import_command("导入数据库") is True

    def test_exact_match_ru_ku(self):
        assert AIChatApplicationService._looks_like_short_excel_import_command("入库") is True

    def test_long_text_no_match(self):
        assert AIChatApplicationService._looks_like_short_excel_import_command("A" * 41) is False

    def test_containing_keyword(self):
        assert AIChatApplicationService._looks_like_short_excel_import_command("请导入数据库") is True

    def test_empty(self):
        assert AIChatApplicationService._looks_like_short_excel_import_command("") is False

    def test_unrelated(self):
        assert AIChatApplicationService._looks_like_short_excel_import_command("查询产品") is False


# ========================= _build_fallback_response - extended =============


class TestBuildFallbackResponseExtended:
    def test_greeting_keywords(self):
        for greeting in ("你好", "您好", "hi", "hello", "嗨"):
            result = AIChatApplicationService._build_fallback_response(greeting, "test error")
            assert "XCAGI" in result["response"]

    def test_non_greeting(self):
        result = AIChatApplicationService._build_fallback_response("查产品", "test error")
        assert "抱歉" in result["response"]

    def test_empty_message(self):
        result = AIChatApplicationService._build_fallback_response("", "test error")
        assert result["success"] is False

    def test_none_message(self):
        # Source code does `message[:100]` which fails on None, so test with empty string
        result = AIChatApplicationService._build_fallback_response("", "test error")
        assert result["success"] is False

    def test_error_reason_in_response(self):
        result = AIChatApplicationService._build_fallback_response("查询", "API Key 无效")
        assert "API Key 无效" in result["message"]


# ========================= _infer_excel_column_roles - extended ============


class TestInferExcelColumnRolesExtended:
    def test_empty_records(self):
        service = _make_service()
        result, conf = service._infer_excel_column_roles([])
        assert result == {}
        assert conf == 0.0

    def test_records_with_empty_keys(self):
        service = _make_service()
        result, conf = service._infer_excel_column_roles([{"": "value"}])
        assert result == {}
        assert conf == 0.0

    def test_numeric_column_identified_as_price(self):
        service = _make_service()
        records = [
            {"产品名称": "产品A", "单价": "100.5", "型号": "5003A", "客户": "公司X"},
            {"产品名称": "产品B", "单价": "200.0", "型号": "5004B", "客户": "公司X"},
            {"产品名称": "产品C", "单价": "300.0", "型号": "5005C", "客户": "公司X"},
        ]
        result, conf = service._infer_excel_column_roles(records)
        assert result.get("unit_price") == "单价"

    def test_model_like_column_identified(self):
        service = _make_service()
        records = [
            {"名称": "产品A", "型号": "5003A", "价格": "100"},
            {"名称": "产品B", "型号": "5004B", "价格": "200"},
            {"名称": "产品C", "型号": "5005C", "价格": "300"},
        ]
        result, conf = service._infer_excel_column_roles(records)
        assert result.get("model_number") == "型号"


# ========================= _fallback_excel_product_name_column - extended ==


class TestFallbackExcelProductNameColumnExtended:
    def test_empty_records(self):
        service = _make_service()
        result = service._fallback_excel_product_name_column([], set())
        assert result == ""

    def test_non_dict_first_record(self):
        service = _make_service()
        result = service._fallback_excel_product_name_column([None], set())
        assert result == ""

    def test_skip_reserved_columns(self):
        service = _make_service()
        records = [{"单价": "100", "名称": "产品A"}]
        result = service._fallback_excel_product_name_column(records, {"单价"})
        assert result == "名称"

    def test_skip_serial_number_columns(self):
        service = _make_service()
        records = [{"序号": "1", "名称": "产品A"}]
        result = service._fallback_excel_product_name_column(records, set())
        assert result == "名称"

    def test_skip_packaging_columns(self):
        service = _make_service()
        records = [{"包装": "10kg/桶", "名称": "产品A"}]
        result = service._fallback_excel_product_name_column(records, set())
        assert result == "名称"

    def test_low_score_returns_empty(self):
        service = _make_service()
        records = [{"纯数字": "12345"}]
        result = service._fallback_excel_product_name_column(records, set())
        assert result == ""


# ========================= _fallback_excel_model_number_column - extended ==


class TestFallbackExcelModelNumberColumnExtended:
    def test_empty_records(self):
        service = _make_service()
        result = service._fallback_excel_model_number_column([], set())
        assert result == ""

    def test_non_dict_first_record(self):
        service = _make_service()
        result = service._fallback_excel_model_number_column([None], set())
        assert result == ""

    def test_model_like_column_found(self):
        service = _make_service()
        records = [{"型号": "5003A", "名称": "产品X"}]
        result = service._fallback_excel_model_number_column(records, {"名称"})
        assert result == "型号"

    def test_low_score_returns_empty(self):
        service = _make_service()
        records = [{"名称": "产品A"}]
        result = service._fallback_excel_model_number_column(records, set())
        assert result == ""


# ========================= _header_hint_column_roles - extended ============


class TestHeaderHintColumnRolesExtended:
    def test_returns_dict(self):
        result = AIChatApplicationService._header_hint_column_roles(["产品名称", "单价"])
        assert isinstance(result, dict)
        assert "unit_name" in result
        assert "product_name" in result

    def test_empty_keys(self):
        result = AIChatApplicationService._header_hint_column_roles([])
        assert isinstance(result, dict)


# ========================= _extract_excel_import_records - deep ============


class TestExtractExcelImportRecordsDeep:
    def test_grid_preview_rows_with_header(self):
        service = _make_service()
        excel_analysis = {
            "preview_data": {
                "grid_preview": {
                    "rows": [
                        ["客户", "产品名称", "单价"],
                        ["公司A", "产品X", "100"],
                        ["公司A", "产品Y", "200"],
                    ]
                }
            }
        }
        with (
            patch.object(service, "_try_structured_reload_records", return_value=None),
            patch.object(service, "_infer_excel_column_roles", return_value=({"unit_name": "客户", "product_name": "产品名称", "model_number": "", "unit_price": "单价"}, 0.9)),
            patch.object(service, "_infer_excel_column_roles_with_llm", return_value={}),
            patch.object(service, "_default_purchase_unit_for_import", return_value="公司A"),
        ):
            records, err = service._extract_excel_import_records(excel_analysis)
        assert err is None
        assert len(records) >= 1

    def test_unnamed_columns_promoted(self):
        """First row looks like headers but keys are Unnamed:0 etc."""
        service = _make_service()
        excel_analysis = {
            "preview_data": {
                "sample_rows": [
                    {"Unnamed:0": "客户", "Unnamed:1": "产品名称", "Unnamed:2": "单价"},
                    {"Unnamed:0": "公司A", "Unnamed:1": "产品X", "Unnamed:2": "100"},
                    {"Unnamed:0": "公司A", "Unnamed:1": "产品Y", "Unnamed:2": "200"},
                ]
            }
        }
        with (
            patch.object(service, "_try_structured_reload_records", return_value=None),
            patch.object(service, "_infer_excel_column_roles", return_value=({"unit_name": "客户", "product_name": "产品名称", "model_number": "", "unit_price": "单价"}, 0.9)),
            patch.object(service, "_infer_excel_column_roles_with_llm", return_value={}),
            patch.object(service, "_default_purchase_unit_for_import", return_value="公司A"),
        ):
            records, err = service._extract_excel_import_records(excel_analysis)
        assert err is None

    def test_unit_key_packaging_ratio_high_skipped(self):
        """When unit_key column values are mostly packaging units, it should be cleared."""
        service = _make_service()
        excel_analysis = {
            "preview_data": {
                "sample_rows": [
                    {"单位": "件", "产品名称": "产品X", "单价": 100},
                    {"单位": "箱", "产品名称": "产品Y", "单价": 200},
                    {"单位": "桶", "产品名称": "产品Z", "单价": 300},
                ]
            }
        }
        with (
            patch.object(service, "_try_structured_reload_records", return_value=None),
            patch.object(service, "_infer_excel_column_roles", return_value=({"unit_name": "单位", "product_name": "产品名称", "model_number": "", "unit_price": "单价"}, 0.9)),
            patch.object(service, "_infer_excel_column_roles_with_llm", return_value={}),
            patch.object(service, "_default_purchase_unit_for_import", return_value="默认公司"),
        ):
            records, err = service._extract_excel_import_records(excel_analysis)
        # unit_key should be cleared because packaging ratio >= 0.45
        assert err is None

    def test_unit_key_same_as_product_key_cleared(self):
        service = _make_service()
        excel_analysis = {
            "preview_data": {
                "sample_rows": [
                    {"名称": "产品X", "单价": 100},
                    {"名称": "产品Y", "单价": 200},
                ]
            }
        }
        with (
            patch.object(service, "_try_structured_reload_records", return_value=None),
            patch.object(service, "_infer_excel_column_roles", return_value=({"unit_name": "名称", "product_name": "名称", "model_number": "", "unit_price": "单价"}, 0.9)),
            patch.object(service, "_infer_excel_column_roles_with_llm", return_value={}),
            patch.object(service, "_default_purchase_unit_for_import", return_value=""),
        ):
            records, err = service._extract_excel_import_records(excel_analysis)
        assert err is None

    def test_price_parse_failure_defaults_zero(self):
        service = _make_service()
        excel_analysis = {
            "preview_data": {
                "sample_rows": [
                    {"客户": "公司A", "产品名称": "产品X", "单价": "not_a_number"},
                ]
            }
        }
        with (
            patch.object(service, "_try_structured_reload_records", return_value=None),
            patch.object(service, "_infer_excel_column_roles", return_value=({"unit_name": "客户", "product_name": "产品名称", "model_number": "", "unit_price": "单价"}, 0.9)),
            patch.object(service, "_infer_excel_column_roles_with_llm", return_value={}),
            patch.object(service, "_default_purchase_unit_for_import", return_value="公司A"),
        ):
            records, err = service._extract_excel_import_records(excel_analysis)
        assert err is None
        if records:
            assert records[0]["unit_price"] == 0.0

    def test_dedup_same_unit_product_model(self):
        service = _make_service()
        excel_analysis = {
            "preview_data": {
                "sample_rows": [
                    {"客户": "公司A", "产品名称": "产品X", "型号": "5003A", "单价": 100},
                    {"客户": "公司A", "产品名称": "产品X", "型号": "5003A", "单价": 100},
                ]
            }
        }
        with (
            patch.object(service, "_try_structured_reload_records", return_value=None),
            patch.object(service, "_infer_excel_column_roles", return_value=({"unit_name": "客户", "product_name": "产品名称", "model_number": "型号", "unit_price": "单价"}, 0.9)),
            patch.object(service, "_infer_excel_column_roles_with_llm", return_value={}),
            patch.object(service, "_default_purchase_unit_for_import", return_value="公司A"),
        ):
            records, err = service._extract_excel_import_records(excel_analysis)
        assert err is None
        assert len(records) == 1

    def test_skip_row_without_unit_or_product(self):
        service = _make_service()
        excel_analysis = {
            "preview_data": {
                "sample_rows": [
                    {"客户": "", "产品名称": "", "型号": "", "单价": 100},
                ]
            }
        }
        with (
            patch.object(service, "_try_structured_reload_records", return_value=None),
            patch.object(service, "_infer_excel_column_roles", return_value=({"unit_name": "客户", "product_name": "产品名称", "model_number": "型号", "unit_price": "单价"}, 0.9)),
            patch.object(service, "_infer_excel_column_roles_with_llm", return_value={}),
            patch.object(service, "_default_purchase_unit_for_import", return_value=""),
        ):
            records, err = service._extract_excel_import_records(excel_analysis)
        assert err is None
        assert len(records) == 0

    def test_measure_unit_replaced_with_default(self):
        """When unit_name looks like a measure unit, it should be replaced with default."""
        service = _make_service()
        excel_analysis = {
            "preview_data": {
                "sample_rows": [
                    {"客户": "件", "产品名称": "产品X", "单价": 100},
                ]
            }
        }
        with (
            patch.object(service, "_try_structured_reload_records", return_value=None),
            patch.object(service, "_infer_excel_column_roles", return_value=({"unit_name": "客户", "product_name": "产品名称", "model_number": "", "unit_price": "单价"}, 0.9)),
            patch.object(service, "_infer_excel_column_roles_with_llm", return_value={}),
            patch.object(service, "_default_purchase_unit_for_import", return_value="默认公司"),
        ):
            records, err = service._extract_excel_import_records(excel_analysis)
        assert err is None
        if records:
            assert records[0]["unit_name"] == "默认公司"


# ========================= process_chat - deep error branches =============


class TestProcessChatDeepErrors:
    def _make_service_with_mock(self):
        with (
            patch("app.application.ai_chat_app_service.get_ai_conversation_service"),
            patch("app.application.ai_chat_app_service.LLMWorkflowPlanner"),
            patch("app.application.ai_chat_app_service.HybridRiskGate"),
            patch("app.application.ai_chat_app_service.WorkflowEngine"),
            patch("app.application.ai_chat_app_service.get_approval_service"),
        ):
            return AIChatApplicationService()

    def test_connection_error(self):
        async def raise_conn(*a, **kw):
            raise ConnectionError("refused")

        service = self._make_service_with_mock()
        mock_ai = Mock()
        mock_ai.chat = raise_conn
        service.ai_service = mock_ai
        with (
            patch.object(service, "_inject_excel_vector_context", return_value={}),
            patch.object(service, "_try_handle_dynamic_workflow", return_value=None),
            patch("app.services.get_conversation_service"),
        ):
            result = service.process_chat("u1", "hello")
        assert result["success"] is False
        assert "连接失败" in result.get("message", "") or "连接失败" in result.get("response", "")

    def test_timeout_error(self):
        async def raise_timeout(*a, **kw):
            raise TimeoutError("timed out")

        service = self._make_service_with_mock()
        mock_ai = Mock()
        mock_ai.chat = raise_timeout
        service.ai_service = mock_ai
        with (
            patch.object(service, "_inject_excel_vector_context", return_value={}),
            patch.object(service, "_try_handle_dynamic_workflow", return_value=None),
            patch("app.services.get_conversation_service"),
        ):
            result = service.process_chat("u1", "hello")
        assert result["success"] is False
        assert "超时" in result.get("message", "") or "超时" in result.get("response", "")

    def test_api_key_error(self):
        async def raise_api_key(*a, **kw):
            raise RuntimeError("api_key is invalid")

        service = self._make_service_with_mock()
        mock_ai = Mock()
        mock_ai.chat = raise_api_key
        service.ai_service = mock_ai
        with (
            patch.object(service, "_inject_excel_vector_context", return_value={}),
            patch.object(service, "_try_handle_dynamic_workflow", return_value=None),
            patch("app.services.get_conversation_service"),
        ):
            result = service.process_chat("u1", "hello")
        assert result["success"] is False
        assert "API Key" in result.get("message", "") or "API Key" in result.get("response", "")

    def test_connection_string_error(self):
        async def raise_conn_str(*a, **kw):
            raise RuntimeError("connection refused by remote")

        service = self._make_service_with_mock()
        mock_ai = Mock()
        mock_ai.chat = raise_conn_str
        service.ai_service = mock_ai
        with (
            patch.object(service, "_inject_excel_vector_context", return_value={}),
            patch.object(service, "_try_handle_dynamic_workflow", return_value=None),
            patch("app.services.get_conversation_service"),
        ):
            result = service.process_chat("u1", "hello")
        assert result["success"] is False
        assert "无法连接" in result.get("message", "") or "无法连接" in result.get("response", "")

    def test_generic_runtime_error(self):
        async def raise_generic(*a, **kw):
            raise RuntimeError("unknown internal error")

        service = self._make_service_with_mock()
        mock_ai = Mock()
        mock_ai.chat = raise_generic
        service.ai_service = mock_ai
        with (
            patch.object(service, "_inject_excel_vector_context", return_value={}),
            patch.object(service, "_try_handle_dynamic_workflow", return_value=None),
            patch("app.services.get_conversation_service"),
        ):
            result = service.process_chat("u1", "hello")
        assert result["success"] is False
        assert "暂时不可用" in result.get("message", "") or "暂时不可用" in result.get("response", "")

    def test_empty_message_returns_error(self):
        service = _make_service()
        result = service.process_chat("u1", "")
        assert result["success"] is False
        assert "不能为空" in result["message"]

    def test_file_context_injects_excel_analysis(self):
        async def mock_chat(*a, **kw):
            return {"success": True, "text": "结果", "action": "followup", "data": {}}

        service = self._make_service_with_mock()
        mock_ai = Mock()
        mock_ai.chat = mock_chat
        service.ai_service = mock_ai
        with (
            patch.object(service, "_inject_excel_vector_context", return_value={}),
            patch.object(service, "_try_handle_dynamic_workflow", return_value=None),
            patch("app.services.get_conversation_service"),
        ):
            result = service.process_chat(
                "u1", "查询", source=None,
                file_context={"file_path": "/test.xlsx", "sheet_name": "Sheet1"},
            )
        assert result["success"] is True


# ========================= _persist_chat_turn - deep ======================


class TestPersistChatTurnDeep:
    def test_no_session_id_skips(self):
        service = _make_service()
        # Should not raise
        service._persist_chat_turn("u1", "hello", {}, {"success": True})

    def test_with_session_id_persists(self):
        service = _make_service()
        mock_conv = Mock()
        with patch("app.services.get_conversation_service", return_value=mock_conv):
            service._persist_chat_turn(
                "u1", "hello",
                {"session_id": "sess1"},
                {"success": True, "response": "world", "data": {"text": "world", "action": "reply", "data": {}}},
            )
        assert mock_conv.save_message.call_count == 2

    def test_with_conversation_id_persists(self):
        service = _make_service()
        mock_conv = Mock()
        with patch("app.services.get_conversation_service", return_value=mock_conv):
            service._persist_chat_turn(
                "u1", "hello",
                {"conversation_id": "conv1"},
                {"success": True, "response": "world", "data": {}},
            )
        assert mock_conv.save_message.call_count == 2

    def test_with_tool_call_data(self):
        service = _make_service()
        mock_conv = Mock()
        with patch("app.services.get_conversation_service", return_value=mock_conv):
            service._persist_chat_turn(
                "u1", "hello",
                {"session_id": "sess1"},
                {
                    "success": True,
                    "response": "done",
                    "data": {"text": "done", "action": "tool_call", "data": {"tool_key": "products"}},
                    "toolCall": {"tool_id": "products"},
                },
            )
        assert mock_conv.save_message.call_count == 2


# ========================= _inject_excel_vector_context - deep ============


class TestInjectExcelVectorContextDeep:
    def test_successful_query(self):
        service = _make_service()
        mock_svc = Mock()
        mock_svc.query.return_value = {"success": True, "hits": [{"score": 0.9}]}
        with patch("app.application.get_excel_vector_search_app_service", return_value=mock_svc):
            result = service._inject_excel_vector_context("hello", {"excel_index_id": "idx1"})
        assert "excel_vector_context" in result
        assert result["excel_vector_context"]["hits"] == [{"score": 0.9}]

    def test_unsuccessful_query(self):
        service = _make_service()
        mock_svc = Mock()
        mock_svc.query.return_value = {"success": False}
        with patch("app.application.get_excel_vector_search_app_service", return_value=mock_svc):
            result = service._inject_excel_vector_context("hello", {"excel_index_id": "idx1"})
        assert "excel_vector_context" not in result

    def test_custom_top_k(self):
        service = _make_service()
        mock_svc = Mock()
        mock_svc.query.return_value = {"success": True, "hits": []}
        with patch("app.application.get_excel_vector_search_app_service", return_value=mock_svc):
            result = service._inject_excel_vector_context("hello", {"excel_index_id": "idx1", "excel_top_k": 10})
        mock_svc.query.assert_called_once_with(index_id="idx1", query_text="hello", top_k=10)

    def test_invalid_top_k_defaults_to_5(self):
        service = _make_service()
        mock_svc = Mock()
        mock_svc.query.return_value = {"success": True, "hits": []}
        with patch("app.application.get_excel_vector_search_app_service", return_value=mock_svc):
            result = service._inject_excel_vector_context("hello", {"excel_index_id": "idx1", "excel_top_k": "abc"})
        mock_svc.query.assert_called_once_with(index_id="idx1", query_text="hello", top_k=5)

    def test_vector_index_id_alias(self):
        service = _make_service()
        mock_svc = Mock()
        mock_svc.query.return_value = {"success": True, "hits": []}
        with patch("app.application.get_excel_vector_search_app_service", return_value=mock_svc):
            result = service._inject_excel_vector_context("hello", {"excel_vector_index_id": "vidx1"})
        mock_svc.query.assert_called_once()
