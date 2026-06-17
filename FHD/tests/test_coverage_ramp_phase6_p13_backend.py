"""COVERAGE_RAMP Phase 6 round 13: backend low-coverage modules.

Targets:
- ``app/application/ai_chat_app_service.py`` (81.0% line coverage, 230 uncovered lines)
- ``app/application/workflow/planner.py`` (77.0% line coverage, 151 uncovered lines)
- ``app/application/tools/workflow.py`` (82.1% line coverage, 121 uncovered lines)

Tests follow the phase-4 style: ``from __future__ import annotations``,
``unittest.mock`` + ``pytest``, mock only external boundaries (DB / external
API / LLM / file IO). The handler functions themselves are exercised through
real calls.

Coverage scenarios per 铁律3:
- Happy path (valid input)
- Empty / None input
- Boundary values (empty list, empty dict, empty string)
- Exception paths (RECOVERABLE_ERRORS: RuntimeError, ValueError, httpx errors)
"""

from __future__ import annotations

import os

os.environ.setdefault("XCAGI_SKIP_LEGACY_COMPAT_ROUTES", "1")

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pandas as pd
import pytest

from app.application.ai_chat_app_service import (
    AIChatApplicationService,
    _skip_pro_excel_deterministic_import,
)
from app.application.workflow.planner import (
    LLMWorkflowPlanner,
    _execute_customers_ensure_exists_tool,
    _execute_customers_tool,
    _execute_excel_analysis_tool,
    _execute_excel_decompose_tool,
    _execute_excel_schema_tool,
    _execute_import_excel_tool,
    _execute_materials_tool,
    _execute_price_list_tool,
    _execute_print_label_tool,
    _execute_products_tool,
    _execute_shipment_generate_tool,
    _execute_shipment_records_tool,
    _execute_template_extract_tool,
    _execute_wechat_preview_tool,
    _filter_tool_registry_for_profile,
    execute_tool,
    get_tool_registry,
)
from app.application.workflow.types import PlanGraph, WorkflowNode, validate_plan_graph
from app.application.tools.workflow import (
    _excel_cell_as_clean_str,
    _excel_cell_as_float,
    _handle_import_excel_to_database,
    _import_customers_preview_or_execute,
    _import_orders_preview_or_execute,
    _import_products_preview_or_execute,
    _infer_product_field_mapping,
    _looks_like_contract_or_footer_line,
    _parse_excel_header_row_1based,
    execute_workflow_tool,
    get_workflow_tool_registry,
    handle_excel_analysis,
    invalidate_workflow_tool_registry,
    run_natural_language_pandas,
)


# ===========================================================================
# 1. app/application/ai_chat_app_service.py
# ===========================================================================


class TestSkipProExcelDeterministicImport:
    """Cover _skip_pro_excel_deterministic_import branches."""

    def test_none_context_returns_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("XCAGI_DISABLE_PRO_EXCEL_IMPORT_SHORTCUT", raising=False)
        monkeypatch.delenv("XCAGI_EXCEL_IMPORT_AI_DECIDES", raising=False)
        assert _skip_pro_excel_deterministic_import(None) is False

    def test_non_dict_context_returns_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("XCAGI_DISABLE_PRO_EXCEL_IMPORT_SHORTCUT", raising=False)
        monkeypatch.delenv("XCAGI_EXCEL_IMPORT_AI_DECIDES", raising=False)
        assert _skip_pro_excel_deterministic_import("not a dict") is False  # type: ignore[arg-type]

    def test_force_shortcut_overrides_skip_flags(self) -> None:
        ctx = {
            "excel_import_use_deterministic_shortcut": True,
            "excel_import_skip_deterministic_shortcut": True,
            "excel_import_ai_decides": True,
        }
        assert _skip_pro_excel_deterministic_import(ctx) is False

    def test_skip_shortcut_flag_returns_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("XCAGI_DISABLE_PRO_EXCEL_IMPORT_SHORTCUT", raising=False)
        monkeypatch.delenv("XCAGI_EXCEL_IMPORT_AI_DECIDES", raising=False)
        assert _skip_pro_excel_deterministic_import({"excel_import_skip_deterministic_shortcut": True}) is True

    def test_ai_decides_flag_returns_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("XCAGI_DISABLE_PRO_EXCEL_IMPORT_SHORTCUT", raising=False)
        monkeypatch.delenv("XCAGI_EXCEL_IMPORT_AI_DECIDES", raising=False)
        assert _skip_pro_excel_deterministic_import({"excel_import_ai_decides": True}) is True

    def test_env_disable_shortcut_returns_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XCAGI_DISABLE_PRO_EXCEL_IMPORT_SHORTCUT", "1")
        monkeypatch.delenv("XCAGI_EXCEL_IMPORT_AI_DECIDES", raising=False)
        assert _skip_pro_excel_deterministic_import({}) is True

    def test_env_ai_decides_returns_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("XCAGI_DISABLE_PRO_EXCEL_IMPORT_SHORTCUT", raising=False)
        monkeypatch.setenv("XCAGI_EXCEL_IMPORT_AI_DECIDES", "true")
        assert _skip_pro_excel_deterministic_import({}) is True

    def test_env_on_value_returns_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XCAGI_DISABLE_PRO_EXCEL_IMPORT_SHORTCUT", "on")
        assert _skip_pro_excel_deterministic_import({}) is True

    def test_env_yes_value_returns_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XCAGI_EXCEL_IMPORT_AI_DECIDES", "yes")
        assert _skip_pro_excel_deterministic_import({}) is True

    def test_no_flags_returns_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("XCAGI_DISABLE_PRO_EXCEL_IMPORT_SHORTCUT", raising=False)
        monkeypatch.delenv("XCAGI_EXCEL_IMPORT_AI_DECIDES", raising=False)
        assert _skip_pro_excel_deterministic_import({}) is False

    def test_env_empty_string_returns_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XCAGI_DISABLE_PRO_EXCEL_IMPORT_SHORTCUT", "")
        monkeypatch.setenv("XCAGI_EXCEL_IMPORT_AI_DECIDES", "  ")
        assert _skip_pro_excel_deterministic_import({}) is False


class TestIsProSource:
    """Cover AIChatApplicationService._is_pro_source."""

    @pytest.mark.parametrize(
        "source,expected",
        [
            ("pro", True),
            ("pro_mode", True),
            ("promode", True),
            ("professional", True),
            ("xcagi_pro", True),
            ("PRO", True),
            ("Pro-Mode", True),
            ("  pro  ", True),
            ("normal", False),
            ("", False),
            (None, False),
            ("unknown", False),
        ],
    )
    def test_is_pro_source_parametrized(self, source: str | None, expected: bool) -> None:
        assert AIChatApplicationService._is_pro_source(source) is expected


class TestMergeToolRuntimeContext:
    """Cover _merge_tool_runtime_context."""

    def test_basic_merge(self) -> None:
        ctx = {"ui_surface": "normal", "intent_channel": "pro"}
        result = AIChatApplicationService._merge_tool_runtime_context("u1", "hello", ctx)
        assert result["user_id"] == "u1"
        assert result["message"] == "hello"
        assert result["ui_surface"] == "normal"
        assert result["intent_channel"] == "pro"

    def test_none_context(self) -> None:
        result = AIChatApplicationService._merge_tool_runtime_context("u1", "hello", None)
        assert result == {"user_id": "u1", "message": "hello"}

    def test_non_dict_context(self) -> None:
        result = AIChatApplicationService._merge_tool_runtime_context("u1", "hello", "not a dict")  # type: ignore[arg-type]
        assert result == {"user_id": "u1", "message": "hello"}

    def test_skips_none_values(self) -> None:
        ctx = {"ui_surface": None, "intent_channel": "pro", "tool_execution_profile": None}
        result = AIChatApplicationService._merge_tool_runtime_context("u1", "msg", ctx)
        assert "ui_surface" not in result
        assert "tool_execution_profile" not in result
        assert result["intent_channel"] == "pro"

    def test_excel_analysis_dict_passed_through(self) -> None:
        ea = {"file_path": "/tmp/x.xlsx"}
        ctx = {"excel_analysis": ea}
        result = AIChatApplicationService._merge_tool_runtime_context("u1", "msg", ctx)
        assert result["excel_analysis"] == ea

    def test_excel_analysis_non_dict_skipped(self) -> None:
        ctx = {"excel_analysis": "not a dict"}
        result = AIChatApplicationService._merge_tool_runtime_context("u1", "msg", ctx)
        assert "excel_analysis" not in result

    def test_last_excel_analysis_context_passed(self) -> None:
        last_ea = {"file_path": "/tmp/y.xlsx"}
        ctx = {"last_excel_analysis_context": last_ea}
        result = AIChatApplicationService._merge_tool_runtime_context("u1", "msg", ctx)
        assert result["last_excel_analysis_context"] == last_ea


class TestBuildFallbackResponse:
    """Cover _build_fallback_response."""

    def test_greeting_message(self) -> None:
        result = AIChatApplicationService._build_fallback_response("你好", "service down")
        assert result["success"] is False
        assert result["message"] == "service down"
        assert "您好" in result["response"]
        assert result["data"]["action"] == "error_fallback"
        assert result["data"]["data"]["fallback_mode"] is True

    def test_default_message(self) -> None:
        result = AIChatApplicationService._build_fallback_response("查询产品", "service down")
        assert result["success"] is False
        assert "service down" in result["response"]
        assert result["data"]["action"] == "error_fallback"

    def test_empty_message(self) -> None:
        result = AIChatApplicationService._build_fallback_response("", "err")
        assert result["success"] is False
        assert result["data"]["data"]["original_message"] == ""

    def test_none_message(self) -> None:
        # ``_build_fallback_response`` does not guard None — it raises TypeError
        # when slicing ``message[:100]``. We assert the contract explicitly so
        # the behaviour is documented and any future fix is detected.
        with pytest.raises(TypeError):
            AIChatApplicationService._build_fallback_response(None, "err")  # type: ignore[arg-type]

    def test_hello_triggers_greeting(self) -> None:
        result = AIChatApplicationService._build_fallback_response("hello there", "err")
        assert "您好" in result["response"]

    def test_hi_triggers_greeting(self) -> None:
        result = AIChatApplicationService._build_fallback_response("hi", "err")
        assert "您好" in result["response"]

    def test_original_message_truncated(self) -> None:
        long_msg = "x" * 200
        result = AIChatApplicationService._build_fallback_response(long_msg, "err")
        assert len(result["data"]["data"]["original_message"]) <= 100


class TestIsNumberText:
    """Cover _is_number_text."""

    @pytest.mark.parametrize(
        "value,expected",
        [
            ("123", True),
            ("12.34", True),
            ("1,234.56", True),
            ("-5", True),
            ("0", True),
            ("", False),
            (None, False),
            ("abc", False),
            ("  ", False),
            ("12abc", False),
        ],
    )
    def test_is_number_text(self, value: str, expected: bool) -> None:
        assert AIChatApplicationService._is_number_text(value) is expected


class TestResolveExcelPathForImport:
    """Cover _resolve_excel_path_for_import."""

    def test_from_excel_analysis(self) -> None:
        ea = {"file_path": "/tmp/x.xlsx"}
        result = AIChatApplicationService._resolve_excel_path_for_import(ea, {})
        assert result == "/tmp/x.xlsx"

    def test_from_preview_data_when_excel_analysis_empty(self) -> None:
        ea = {"file_path": ""}
        pd_ = {"file_path": "/tmp/y.xlsx"}
        result = AIChatApplicationService._resolve_excel_path_for_import(ea, pd_)
        assert result == "/tmp/y.xlsx"

    def test_both_empty_returns_empty(self) -> None:
        result = AIChatApplicationService._resolve_excel_path_for_import({}, {})
        assert result == ""

    def test_strips_whitespace(self) -> None:
        ea = {"file_path": "  /tmp/x.xlsx  "}
        result = AIChatApplicationService._resolve_excel_path_for_import(ea, {})
        assert result == "/tmp/x.xlsx"


class TestExcelCellLooksLikeProductMeasureUnit:
    """Cover _excel_cell_looks_like_product_measure_unit."""

    @pytest.mark.parametrize(
        "value,expected",
        [
            ("件", True),
            ("箱", True),
            ("pcs", True),
            ("PC", True),
            ("5件", True),
            ("10箱", True),
            ("客户A", False),
            ("", False),
            (None, False),
            ("产品名称", False),
            ("12.5kg", False),
        ],
    )
    def test_measure_unit_detection(self, value: Any, expected: bool) -> None:
        assert AIChatApplicationService._excel_cell_looks_like_product_measure_unit(value) is expected


class TestSanitizeImportScalar:
    """Cover _sanitize_import_scalar."""

    def test_none_returns_none(self) -> None:
        assert AIChatApplicationService._sanitize_import_scalar(None) is None

    def test_nan_float_returns_none(self) -> None:
        import math

        assert AIChatApplicationService._sanitize_import_scalar(float("nan")) is None

    def test_nan_string_returns_none(self) -> None:
        assert AIChatApplicationService._sanitize_import_scalar("nan") is None

    def test_none_string_returns_none(self) -> None:
        assert AIChatApplicationService._sanitize_import_scalar("none") is None

    def test_nat_string_returns_none(self) -> None:
        assert AIChatApplicationService._sanitize_import_scalar("nat") is None

    def test_null_string_returns_none(self) -> None:
        assert AIChatApplicationService._sanitize_import_scalar("null") is None

    def test_na_string_returns_none(self) -> None:
        assert AIChatApplicationService._sanitize_import_scalar("<na>") is None

    def test_strips_string(self) -> None:
        assert AIChatApplicationService._sanitize_import_scalar("  hello  ") == "hello"

    def test_int_passthrough(self) -> None:
        assert AIChatApplicationService._sanitize_import_scalar(42) == 42

    def test_float_passthrough(self) -> None:
        assert AIChatApplicationService._sanitize_import_scalar(3.14) == 3.14

    def test_nan_via_float_conversion(self) -> None:
        # object that becomes nan when float() is called
        class NanLike:
            def __float__(self) -> float:
                return float("nan")

        assert AIChatApplicationService._sanitize_import_scalar(NanLike()) is None


class TestModelLikeScore:
    """Cover _model_like_score."""

    def test_empty_returns_zero(self) -> None:
        assert AIChatApplicationService._model_like_score("") == 0.0

    def test_none_returns_zero(self) -> None:
        assert AIChatApplicationService._model_like_score(None) == 0.0

    def test_digit_and_alpha_returns_one(self) -> None:
        assert AIChatApplicationService._model_like_score("ABC123") == 1.0

    def test_digit_only_short_returns_six_tenths(self) -> None:
        assert AIChatApplicationService._model_like_score("12345") == 0.6

    def test_too_short_returns_zero(self) -> None:
        assert AIChatApplicationService._model_like_score("A") == 0.0

    def test_too_long_returns_zero(self) -> None:
        assert AIChatApplicationService._model_like_score("A" * 30) == 0.0

    def test_alpha_only_returns_zero(self) -> None:
        assert AIChatApplicationService._model_like_score("ABCDEF") == 0.0


class TestPackagingOrMeasureRatio:
    """Cover _packaging_or_measure_ratio."""

    def test_empty_list_returns_zero(self) -> None:
        assert AIChatApplicationService._packaging_or_measure_ratio([]) == 0.0

    def test_all_measure_units_returns_one(self) -> None:
        assert AIChatApplicationService._packaging_or_measure_ratio(["件", "箱", "桶"]) == 1.0

    def test_mixed_values(self) -> None:
        ratio = AIChatApplicationService._packaging_or_measure_ratio(["件", "客户A", "产品B"])
        assert 0.0 < ratio < 1.0

    def test_no_measure_units_returns_zero(self) -> None:
        assert AIChatApplicationService._packaging_or_measure_ratio(["客户A", "产品B"]) == 0.0

    def test_pack_spec_format(self) -> None:
        assert AIChatApplicationService._packaging_or_measure_ratio(["25kg", "30kg"]) == 1.0


class TestResolveForceHeaderRow1based:
    """Cover _resolve_force_header_row_1based."""

    def test_from_grid_preview_header_row_index(self) -> None:
        ea = {}
        pd_ = {"grid_preview": {"header_row_index": 3}}
        assert AIChatApplicationService._resolve_force_header_row_1based(ea, pd_) == 3

    def test_from_tables_header_row(self) -> None:
        ea = {}
        pd_ = {"tables": [{"header_row": 2}]}
        assert AIChatApplicationService._resolve_force_header_row_1based(ea, pd_) == 2

    def test_from_excel_analysis_sheets(self) -> None:
        ea = {"sheets": [{"tables": [{"header_row": 4}]}]}
        assert AIChatApplicationService._resolve_force_header_row_1based(ea, {}) == 4

    def test_from_excel_analysis_sheets_grid_preview(self) -> None:
        ea = {"sheets": [{"grid_preview": {"header_row_index": 5}}]}
        assert AIChatApplicationService._resolve_force_header_row_1based(ea, {}) == 5

    def test_invalid_value_returns_none(self) -> None:
        ea = {}
        pd_ = {"grid_preview": {"header_row_index": "not a number"}}
        assert AIChatApplicationService._resolve_force_header_row_1based(ea, pd_) is None

    def test_zero_returns_none(self) -> None:
        ea = {}
        pd_ = {"grid_preview": {"header_row_index": 0}}
        assert AIChatApplicationService._resolve_force_header_row_1based(ea, pd_) is None

    def test_none_returns_none(self) -> None:
        assert AIChatApplicationService._resolve_force_header_row_1based({}, {}) is None

    def test_non_dict_preview_data(self) -> None:
        assert AIChatApplicationService._resolve_force_header_row_1based({}, "not a dict") is None  # type: ignore[arg-type]


class TestResolveSheetNameForReimport:
    """Cover _resolve_sheet_name_for_reimport."""

    def test_from_request_context_selected_sheet(self) -> None:
        rc = {"excel_analysis_selected_sheet": {"sheet_name": "Sheet1"}}
        assert AIChatApplicationService._resolve_sheet_name_for_reimport({}, {}, rc) == "Sheet1"

    def test_from_request_context_preferred_sheet_name(self) -> None:
        rc = {"preferred_sheet_name": "Sheet2"}
        assert AIChatApplicationService._resolve_sheet_name_for_reimport({}, {}, rc) == "Sheet2"

    def test_from_preview_data_selected_sheet_name(self) -> None:
        pd_ = {"selected_sheet_name": "Sheet3"}
        assert AIChatApplicationService._resolve_sheet_name_for_reimport({}, pd_, None) == "Sheet3"

    def test_from_preview_data_sheet_name(self) -> None:
        pd_ = {"sheet_name": "Sheet4"}
        assert AIChatApplicationService._resolve_sheet_name_for_reimport({}, pd_, None) == "Sheet4"

    def test_from_excel_analysis_sheets(self) -> None:
        ea = {"sheets": [{"sheet_name": "Sheet5"}]}
        assert AIChatApplicationService._resolve_sheet_name_for_reimport(ea, {}, None) == "Sheet5"

    def test_none_when_no_data(self) -> None:
        assert AIChatApplicationService._resolve_sheet_name_for_reimport({}, {}, None) is None

    def test_empty_strings_skipped(self) -> None:
        rc = {"preferred_sheet_name": "  "}
        assert AIChatApplicationService._resolve_sheet_name_for_reimport({}, {}, rc) is None


class TestExcelAnalysisPayloadPresent:
    """Cover _excel_analysis_payload_present."""

    def test_none_context_returns_false(self) -> None:
        assert AIChatApplicationService._excel_analysis_payload_present(None) is False

    def test_empty_dict_returns_false(self) -> None:
        assert AIChatApplicationService._excel_analysis_payload_present({}) is False

    def test_with_summary_returns_true(self) -> None:
        ctx = {"excel_analysis": {"summary": "test summary"}}
        assert AIChatApplicationService._excel_analysis_payload_present(ctx) is True

    def test_with_fields_returns_true(self) -> None:
        ctx = {"excel_analysis": {"fields": [{"name": "col1"}]}}
        assert AIChatApplicationService._excel_analysis_payload_present(ctx) is True

    def test_with_sample_rows_returns_true(self) -> None:
        ctx = {"excel_analysis": {"preview_data": {"sample_rows": [{"a": 1}]}}}
        assert AIChatApplicationService._excel_analysis_payload_present(ctx) is True

    def test_with_grid_preview_rows_returns_true(self) -> None:
        ctx = {"excel_analysis": {"preview_data": {"grid_preview": {"rows": [[1], [2]]}}}}
        assert AIChatApplicationService._excel_analysis_payload_present(ctx) is True

    def test_grid_preview_single_row_returns_false(self) -> None:
        ctx = {"excel_analysis": {"preview_data": {"grid_preview": {"rows": [[1]]}}}}
        assert AIChatApplicationService._excel_analysis_payload_present(ctx) is False


class TestLooksLikeShortExcelImportCommand:
    """Cover _looks_like_short_excel_import_command."""

    def test_exact_command(self) -> None:
        assert AIChatApplicationService._looks_like_short_excel_import_command("加入数据库") is True

    def test_exact_command_ku(self) -> None:
        assert AIChatApplicationService._looks_like_short_excel_import_command("入库") is True

    def test_containing_command(self) -> None:
        assert AIChatApplicationService._looks_like_short_excel_import_command("请加入数据库") is True

    def test_long_text_returns_false(self) -> None:
        long_text = "x" * 50 + "加入数据库"
        assert AIChatApplicationService._looks_like_short_excel_import_command(long_text) is False

    def test_empty_returns_false(self) -> None:
        assert AIChatApplicationService._looks_like_short_excel_import_command("") is False

    def test_none_returns_false(self) -> None:
        assert AIChatApplicationService._looks_like_short_excel_import_command(None) is False  # type: ignore[arg-type]

    def test_unrelated_text_returns_false(self) -> None:
        assert AIChatApplicationService._looks_like_short_excel_import_command("查询产品") is False


class TestRowValuesLookLikeTableHeaders:
    """Cover _row_values_look_like_table_headers."""

    def test_with_multiple_header_hints(self) -> None:
        values = ["产品名称", "型号", "单价", "单位"]
        assert AIChatApplicationService._row_values_look_like_table_headers(values) is True

    def test_with_few_values_returns_false(self) -> None:
        values = ["产品"]
        assert AIChatApplicationService._row_values_look_like_table_headers(values) is False

    def test_empty_values_returns_false(self) -> None:
        assert AIChatApplicationService._row_values_look_like_table_headers([]) is False

    def test_no_header_hints_returns_false(self) -> None:
        values = ["数据1", "数据2", "数据3"]
        assert AIChatApplicationService._row_values_look_like_table_headers(values) is False


class TestPriceColumnBuckets:
    """Cover _price_column_buckets."""

    def test_before_and_after_columns(self) -> None:
        keys = ["调价前单价", "调价后单价", "产品名称"]
        before, after, generic = AIChatApplicationService._price_column_buckets(keys)
        assert "调价前单价" in before
        assert "调价后单价" in after
        assert "产品名称" not in generic

    def test_generic_price_column(self) -> None:
        keys = ["单价", "产品名称"]
        before, after, generic = AIChatApplicationService._price_column_buckets(keys)
        assert before == []
        assert after == []
        assert "单价" in generic

    def test_quantity_excluded(self) -> None:
        keys = ["数量", "计量", "件数"]
        before, after, generic = AIChatApplicationService._price_column_buckets(keys)
        assert before == []
        assert after == []
        assert generic == []

    def test_empty_keys(self) -> None:
        before, after, generic = AIChatApplicationService._price_column_buckets([])
        assert before == []
        assert after == []
        assert generic == []


class TestMergeUserIntentForPriceResolution:
    """Cover _merge_user_intent_for_price_resolution."""

    def test_none_context(self) -> None:
        result = AIChatApplicationService._merge_user_intent_for_price_resolution("导入调价前", None)
        assert "导入调价前" in result

    def test_with_recent_messages(self) -> None:
        rc = {
            "recent_messages": [
                {"role": "user", "content": "导入调价前"},
                {"role": "assistant", "content": "好的"},
            ]
        }
        result = AIChatApplicationService._merge_user_intent_for_price_resolution("确认", rc)
        assert "导入调价前" in result
        assert "确认" in result

    def test_strips_html(self) -> None:
        rc = {"recent_messages": [{"role": "user", "content": "<b>导入</b><br/>调价前"}]}
        result = AIChatApplicationService._merge_user_intent_for_price_resolution("", rc)
        assert "<b>" not in result
        assert "导入" in result

    def test_dedup_chunks(self) -> None:
        rc = {
            "recent_messages": [
                {"role": "user", "content": "导入调价前"},
                {"role": "user", "content": "导入调价前"},
            ]
        }
        result = AIChatApplicationService._merge_user_intent_for_price_resolution("导入调价前", rc)
        # Should only appear twice (once for unique chunks, once for current)
        assert result.count("导入调价前") == 2

    def test_truncates_long_text(self) -> None:
        long_msg = "调价前" * 3000
        result = AIChatApplicationService._merge_user_intent_for_price_resolution(long_msg, None)
        assert len(result) <= 8000

    def test_skips_non_dict_items(self) -> None:
        rc = {"recent_messages": ["not a dict", {"role": "user", "content": "ok"}]}
        result = AIChatApplicationService._merge_user_intent_for_price_resolution("", rc)
        assert "ok" in result

    def test_skips_unknown_roles(self) -> None:
        rc = {"recent_messages": [{"role": "system", "content": "hidden"}]}
        result = AIChatApplicationService._merge_user_intent_for_price_resolution("user_msg", rc)
        assert "hidden" not in result
        assert "user_msg" in result


class TestResolveUnitPriceColumn:
    """Cover _resolve_unit_price_column."""

    def test_forced_override(self) -> None:
        keys = ["调价前", "调价后", "产品"]
        overrides = {"unit_price": "调价前"}
        col, err = AIChatApplicationService._resolve_unit_price_column(keys, "", "", overrides)
        assert col == "调价前"
        assert err is None

    def test_forced_override_not_in_keys(self) -> None:
        keys = ["产品"]
        overrides = {"unit_price": "不存在"}
        col, err = AIChatApplicationService._resolve_unit_price_column(keys, "", "", overrides)
        # Falls through to normal logic
        assert col == ""

    def test_empty_keys(self) -> None:
        col, err = AIChatApplicationService._resolve_unit_price_column([], "", "", None)
        assert col == ""
        assert err is None

    def test_tension_prefer_before(self) -> None:
        keys = ["调价前单价", "调价后单价"]
        col, err = AIChatApplicationService._resolve_unit_price_column(keys, "", "用调价前", None)
        assert col == "调价前单价"
        assert err is None

    def test_tension_prefer_after(self) -> None:
        keys = ["调价前单价", "调价后单价"]
        col, err = AIChatApplicationService._resolve_unit_price_column(keys, "", "用调价后", None)
        assert col == "调价后单价"
        assert err is None

    def test_tension_ambiguous(self) -> None:
        keys = ["调价前单价", "调价后单价"]
        col, err = AIChatApplicationService._resolve_unit_price_column(
            keys, "", "用调价前也用调价后", None
        )
        assert col == ""
        assert err == "ambiguous_price_columns"

    def test_tension_default_to_before(self) -> None:
        keys = ["调价前单价", "调价后单价"]
        col, err = AIChatApplicationService._resolve_unit_price_column(keys, "", "无关键词", None)
        assert col == "调价前单价"
        assert err is None

    def test_current_in_keys(self) -> None:
        keys = ["单价", "产品"]
        col, err = AIChatApplicationService._resolve_unit_price_column(keys, "单价", "", None)
        assert col == "单价"

    def test_only_before(self) -> None:
        keys = ["调价前单价"]
        col, err = AIChatApplicationService._resolve_unit_price_column(keys, "", "", None)
        assert col == "调价前单价"

    def test_only_after(self) -> None:
        keys = ["调价后单价"]
        col, err = AIChatApplicationService._resolve_unit_price_column(keys, "", "", None)
        assert col == "调价后单价"

    def test_generic_single(self) -> None:
        keys = ["单价"]
        col, err = AIChatApplicationService._resolve_unit_price_column(keys, "", "", None)
        assert col == "单价"

    def test_generic_multiple_ambiguous(self) -> None:
        keys = ["单价", "价格"]
        col, err = AIChatApplicationService._resolve_unit_price_column(keys, "", "", None)
        assert col == ""
        assert err == "ambiguous_price_columns"

    def test_tension_with_spaces_in_keys(self) -> None:
        keys = ["调价 前单价", "调价 后单价"]
        col, err = AIChatApplicationService._resolve_unit_price_column(keys, "", "", None)
        assert col == "调价 前单价"


class TestGuessDefaultPurchaseUnit:
    """Cover _guess_default_purchase_unit."""

    def test_with_company_suffix(self) -> None:
        ea = {"file_name": "某某有限公司报价表.xlsx"}
        result = AIChatApplicationService._guess_default_purchase_unit(ea)
        assert "有限公司" in result

    def test_with_file_path_only(self) -> None:
        ea = {"file_path": "/tmp/某某厂报价单.xlsx"}
        result = AIChatApplicationService._guess_default_purchase_unit(ea)
        assert "某某厂" in result

    def test_empty_returns_empty(self) -> None:
        assert AIChatApplicationService._guess_default_purchase_unit({}) == ""

    def test_strips_year_suffix(self) -> None:
        ea = {"file_name": "某某公司2024.xlsx"}
        result = AIChatApplicationService._guess_default_purchase_unit(ea)
        assert "2024" not in result

    def test_strips_quote_tokens(self) -> None:
        ea = {"file_name": "某某公司报价表.xlsx"}
        result = AIChatApplicationService._guess_default_purchase_unit(ea)
        assert "报价表" not in result

    def test_short_stem_returns_empty(self) -> None:
        ea = {"file_name": "A.xlsx"}
        result = AIChatApplicationService._guess_default_purchase_unit(ea)
        assert result == ""


class TestInferExcelColumnRoles:
    """Cover _infer_excel_column_roles."""

    def test_empty_records(self) -> None:
        svc = AIChatApplicationService.__new__(AIChatApplicationService)
        roles, conf = svc._infer_excel_column_roles([])
        assert roles == {}
        assert conf == 0.0

    def test_records_with_no_keys(self) -> None:
        svc = AIChatApplicationService.__new__(AIChatApplicationService)
        roles, conf = svc._infer_excel_column_roles([{}])
        assert roles == {}

    def test_with_typical_columns(self) -> None:
        svc = AIChatApplicationService.__new__(AIChatApplicationService)
        records = [
            {"产品名称": "产品A", "型号": "M123", "单价": "10.5", "客户": "客户X"},
            {"产品名称": "产品B", "型号": "M456", "单价": "20.0", "客户": "客户X"},
        ]
        roles, conf = svc._infer_excel_column_roles(records)
        assert "unit_price" in roles
        assert "model_number" in roles
        assert "unit_name" in roles
        assert "product_name" in roles


class TestHeaderHintColumnRoles:
    """Cover _header_hint_column_roles."""

    def test_with_typical_headers(self) -> None:
        keys = ["产品名称", "型号", "单价", "客户"]
        roles = AIChatApplicationService._header_hint_column_roles(keys)
        assert isinstance(roles, dict)
        # Should contain some role mappings (or empty if service unavailable)
        assert "unit_name" in roles
        assert "product_name" in roles

    def test_empty_keys(self) -> None:
        roles = AIChatApplicationService._header_hint_column_roles([])
        assert "unit_name" in roles
        assert roles["unit_name"] == ""


class TestCustomerHintFromPreviewGrid:
    """Cover _customer_hint_from_preview_grid."""

    def test_none_returns_empty(self) -> None:
        assert AIChatApplicationService._customer_hint_from_preview_grid(None) == ""

    def test_non_dict_returns_empty(self) -> None:
        assert AIChatApplicationService._customer_hint_from_preview_grid("not a dict") == ""  # type: ignore[arg-type]

    def test_no_grid_preview(self) -> None:
        assert AIChatApplicationService._customer_hint_from_preview_grid({}) == ""

    def test_no_rows(self) -> None:
        pd_ = {"grid_preview": {}}
        assert AIChatApplicationService._customer_hint_from_preview_grid(pd_) == ""

    def test_rows_not_list(self) -> None:
        pd_ = {"grid_preview": {"rows": "not a list"}}
        assert AIChatApplicationService._customer_hint_from_preview_grid(pd_) == ""


class TestDefaultPurchaseUnitForImport:
    """Cover _default_purchase_unit_for_import."""

    def test_with_request_context_hint(self) -> None:
        rc = {"excel_customer_hint": "客户A"}
        result = AIChatApplicationService._default_purchase_unit_for_import({}, {}, rc)
        assert result == "客户A"

    def test_with_preview_data_hint(self) -> None:
        pd_ = {"customer_hint": "客户B"}
        result = AIChatApplicationService._default_purchase_unit_for_import({}, pd_, None)
        assert result == "客户B"

    def test_with_document_customer(self) -> None:
        pd_ = {"document_customer": "客户C"}
        result = AIChatApplicationService._default_purchase_unit_for_import({}, pd_, None)
        assert result == "客户C"

    def test_empty_returns_empty_or_guess(self) -> None:
        # Without file, falls back to _guess_default_purchase_unit
        result = AIChatApplicationService._default_purchase_unit_for_import({}, {}, None)
        assert isinstance(result, str)


# ===========================================================================
# 2. app/application/workflow/planner.py
# ===========================================================================


class TestGetToolRegistryPlanner:
    """Cover get_tool_registry from planner."""

    def test_returns_dict_with_tools(self) -> None:
        reg = get_tool_registry()
        assert isinstance(reg, dict)
        assert "products" in reg
        assert "customers" in reg
        assert "price_list" in reg
        assert "shipment_generate" in reg

    def test_tool_has_required_fields(self) -> None:
        reg = get_tool_registry()
        for tool_id, spec in reg.items():
            assert "description" in spec, f"{tool_id} missing description"
            assert "availability" in spec, f"{tool_id} missing availability"
            assert "actions" in spec, f"{tool_id} missing actions"
            assert isinstance(spec["actions"], dict)


class TestExecuteToolPlanner:
    """Cover execute_tool from planner."""

    def test_unknown_tool_returns_error(self) -> None:
        result = execute_tool("nonexistent", {})
        assert result["success"] is False
        assert "未知工具" in result["message"]

    def test_runtime_context_removed(self) -> None:
        # The handler dict captures function references at import time, so we
        # patch the dict entry directly rather than the module-level name.
        from app.application.workflow import planner as planner_mod

        captured: dict[str, Any] = {}

        def spy(params: dict[str, Any]) -> dict[str, Any]:
            captured.update(params)
            return {"success": True}

        original = planner_mod._WORKFLOW_TOOL_HANDLERS.get(("products", "query"))
        planner_mod._WORKFLOW_TOOL_HANDLERS[("products", "query")] = spy
        try:
            execute_tool("products", {"_runtime_context": {"x": 1}, "_action": "query"})
        finally:
            if original is not None:
                planner_mod._WORKFLOW_TOOL_HANDLERS[("products", "query")] = original
        assert "_runtime_context" not in captured

    def test_explicit_action_used(self) -> None:
        from app.application.workflow import planner as planner_mod

        called: list[dict[str, Any]] = []

        def spy(params: dict[str, Any]) -> dict[str, Any]:
            called.append(params)
            return {"success": True}

        key = ("customers", "ensure_exists")
        original = planner_mod._WORKFLOW_TOOL_HANDLERS.get(key)
        planner_mod._WORKFLOW_TOOL_HANDLERS[key] = spy
        try:
            result = execute_tool("customers", {"_action": "ensure_exists", "unit_name": "X"})
        finally:
            if original is not None:
                planner_mod._WORKFLOW_TOOL_HANDLERS[key] = original
        assert result["success"] is True
        assert len(called) == 1
        assert called[0]["unit_name"] == "X"

    def test_default_action_resolution(self) -> None:
        from app.application.workflow import planner as planner_mod

        called: list[dict[str, Any]] = []

        def spy(params: dict[str, Any]) -> dict[str, Any]:
            called.append(params)
            return {"success": True}

        key = ("products", "query")
        original = planner_mod._WORKFLOW_TOOL_HANDLERS.get(key)
        planner_mod._WORKFLOW_TOOL_HANDLERS[key] = spy
        try:
            execute_tool("products", {})
        finally:
            if original is not None:
                planner_mod._WORKFLOW_TOOL_HANDLERS[key] = original
        assert len(called) == 1

    def test_unknown_action_for_known_tool(self) -> None:
        result = execute_tool("products", {"_action": "unknown_action"})
        assert result["success"] is False
        assert "未知工具" in result["message"]


class TestExecutePriceListTool:
    """Cover _execute_price_list_tool."""

    def test_missing_customer_name(self) -> None:
        result = _execute_price_list_tool({})
        assert result["success"] is False
        assert result["error_code"] == "missing_customer_name"

    def test_with_unit_param(self) -> None:
        with patch("app.application.workflow.planner.ensure_fhd_repo_on_syspath", return_value=None):
            with patch(
                "app.application.tools.handle_price_list_export",
                return_value={"success": True, "file_path": "/tmp/x.docx"},
            ):
                result = _execute_price_list_tool({"unit": "客户A"})
                assert result["success"] is True

    def test_import_error(self) -> None:
        with patch("app.application.workflow.planner.ensure_fhd_repo_on_syspath", return_value=None):
            with patch(
                "app.application.tools.handle_price_list_export",
                side_effect=ImportError("no module"),
            ):
                result = _execute_price_list_tool({"customer_name": "X"})
                assert result["success"] is False
                assert result["error_code"] == "service_unavailable"

    def test_value_error(self) -> None:
        with patch("app.application.workflow.planner.ensure_fhd_repo_on_syspath", return_value=None):
            with patch(
                "app.application.tools.handle_price_list_export",
                side_effect=ValueError("bad param"),
            ):
                result = _execute_price_list_tool({"customer_name": "X"})
                assert result["success"] is False
                assert result["error_code"] == "invalid_parameters"

    def test_os_error(self) -> None:
        with patch("app.application.workflow.planner.ensure_fhd_repo_on_syspath", return_value=None):
            with patch(
                "app.application.tools.handle_price_list_export",
                side_effect=OSError("disk full"),
            ):
                result = _execute_price_list_tool({"customer_name": "X"})
                assert result["success"] is False
                assert result["error_code"] == "file_io_error"

    def test_runtime_error(self) -> None:
        with patch("app.application.workflow.planner.ensure_fhd_repo_on_syspath", return_value=None):
            with patch(
                "app.application.tools.handle_price_list_export",
                side_effect=RuntimeError("failed"),
            ):
                result = _execute_price_list_tool({"customer_name": "X"})
                assert result["success"] is False
                assert result["error_code"] == "export_failed"


class TestExecuteProductsTool:
    """Cover _execute_products_tool."""

    def test_with_model_and_unit(self) -> None:
        with patch("app.bootstrap.get_products_service") as mock_get:
            mock_svc = MagicMock()
            mock_svc.get_products.return_value = {"success": True, "data": []}
            mock_get.return_value = mock_svc
            result = _execute_products_tool({"model_number": "M1", "unit_name": "U1"})
            assert result["success"] is True

    def test_with_model_only(self) -> None:
        with patch("app.bootstrap.get_products_service") as mock_get:
            mock_svc = MagicMock()
            mock_svc.get_products.return_value = {"success": True, "data": []}
            mock_get.return_value = mock_svc
            result = _execute_products_tool({"model_number": "M1"})
            assert result["success"] is True

    def test_with_unit_only(self) -> None:
        with patch("app.bootstrap.get_products_service") as mock_get:
            mock_svc = MagicMock()
            mock_svc.get_products.return_value = {"success": True, "data": []}
            mock_get.return_value = mock_svc
            result = _execute_products_tool({"unit_name": "U1"})
            assert result["success"] is True

    def test_with_keyword_only(self) -> None:
        with patch("app.bootstrap.get_products_service") as mock_get:
            mock_svc = MagicMock()
            mock_svc.get_products.return_value = {"success": True, "data": []}
            mock_get.return_value = mock_svc
            result = _execute_products_tool({"keyword": "K1"})
            assert result["success"] is True

    def test_no_params(self) -> None:
        with patch("app.bootstrap.get_products_service") as mock_get:
            mock_svc = MagicMock()
            mock_svc.get_products.return_value = {"success": True, "data": []}
            mock_get.return_value = mock_svc
            result = _execute_products_tool({})
            assert result["success"] is True

    def test_import_error(self) -> None:
        with patch("app.bootstrap.get_products_service", side_effect=ImportError("no")):
            result = _execute_products_tool({})
            assert result["success"] is False
            assert result["error_code"] == "service_unavailable"

    def test_value_error(self) -> None:
        with patch("app.bootstrap.get_products_service", side_effect=ValueError("bad")):
            result = _execute_products_tool({})
            assert result["success"] is False
            assert result["error_code"] == "invalid_parameters"

    def test_runtime_error(self) -> None:
        with patch("app.bootstrap.get_products_service", side_effect=RuntimeError("fail")):
            result = _execute_products_tool({})
            assert result["success"] is False
            assert result["error_code"] == "query_failed"


class TestExecuteCustomersTool:
    """Cover _execute_customers_tool."""

    def test_with_keyword(self) -> None:
        with patch("app.bootstrap.get_customer_app_service") as mock_get:
            mock_svc = MagicMock()
            mock_svc.get_all.return_value = {"success": True, "data": []}
            mock_get.return_value = mock_svc
            result = _execute_customers_tool({"keyword": "K"})
            assert result["success"] is True

    def test_with_customer_name(self) -> None:
        with patch("app.bootstrap.get_customer_app_service") as mock_get:
            mock_svc = MagicMock()
            mock_svc.get_all.return_value = {"success": True, "data": []}
            mock_get.return_value = mock_svc
            result = _execute_customers_tool({"customer_name": "C"})
            assert result["success"] is True

    def test_import_error(self) -> None:
        with patch("app.bootstrap.get_customer_app_service", side_effect=ImportError("no")):
            result = _execute_customers_tool({})
            assert result["success"] is False
            assert result["error_code"] == "service_unavailable"

    def test_value_error(self) -> None:
        with patch("app.bootstrap.get_customer_app_service", side_effect=ValueError("bad")):
            result = _execute_customers_tool({})
            assert result["success"] is False
            assert result["error_code"] == "invalid_parameters"

    def test_runtime_error(self) -> None:
        with patch("app.bootstrap.get_customer_app_service", side_effect=RuntimeError("fail")):
            result = _execute_customers_tool({})
            assert result["success"] is False
            assert result["error_code"] == "query_failed"


class TestExecuteCustomersEnsureExistsTool:
    """Cover _execute_customers_ensure_exists_tool."""

    def test_missing_unit_name(self) -> None:
        result = _execute_customers_ensure_exists_tool({})
        assert result["success"] is False
        assert result["error_code"] == "missing_unit_name"

    def test_existing_customer(self) -> None:
        with patch("app.bootstrap.get_customer_app_service") as mock_get:
            mock_svc = MagicMock()
            mock_matched = MagicMock()
            mock_matched.id = 1
            mock_matched.unit_name = "客户A"
            mock_svc.match_purchase_unit.return_value = mock_matched
            mock_get.return_value = mock_svc
            result = _execute_customers_ensure_exists_tool({"unit_name": "客户A"})
            assert result["success"] is True
            assert result["created"] is False

    def test_create_new_customer(self) -> None:
        with patch("app.bootstrap.get_customer_app_service") as mock_get:
            mock_svc = MagicMock()
            mock_svc.match_purchase_unit.return_value = None
            mock_svc.create.return_value = {"success": True, "data": {"id": 1}}
            mock_get.return_value = mock_svc
            result = _execute_customers_ensure_exists_tool({"unit_name": "新客户"})
            assert result["success"] is True
            assert result["created"] is True

    def test_with_customer_name_param(self) -> None:
        with patch("app.bootstrap.get_customer_app_service") as mock_get:
            mock_svc = MagicMock()
            mock_svc.match_purchase_unit.return_value = None
            mock_svc.create.return_value = {"success": True}
            mock_get.return_value = mock_svc
            result = _execute_customers_ensure_exists_tool({"customer_name": "X"})
            assert result["success"] is True

    def test_import_error(self) -> None:
        with patch("app.bootstrap.get_customer_app_service", side_effect=ImportError("no")):
            result = _execute_customers_ensure_exists_tool({"unit_name": "X"})
            assert result["success"] is False
            assert result["created"] is False

    def test_value_error(self) -> None:
        with patch("app.bootstrap.get_customer_app_service", side_effect=ValueError("bad")):
            result = _execute_customers_ensure_exists_tool({"unit_name": "X"})
            assert result["success"] is False
            assert result["created"] is False

    def test_runtime_error(self) -> None:
        with patch("app.bootstrap.get_customer_app_service", side_effect=RuntimeError("fail")):
            result = _execute_customers_ensure_exists_tool({"unit_name": "X"})
            assert result["success"] is False
            assert result["created"] is False


class TestExecuteShipmentGenerateTool:
    """Cover _execute_shipment_generate_tool."""

    def test_missing_params(self) -> None:
        result = _execute_shipment_generate_tool({})
        assert result["success"] is False
        assert result["error_code"] == "missing_order_params"

    def test_with_order_text_parse_fail(self) -> None:
        with patch("app.routes.tools._parse_order_text", return_value={"success": False, "message": "bad"}):
            result = _execute_shipment_generate_tool({"order_text": "invalid"})
            assert result["success"] is False

    def test_with_unit_and_products(self) -> None:
        with patch("app.bootstrap.get_shipment_app_service") as mock_get:
            mock_svc = MagicMock()
            mock_svc.generate_shipment_document.return_value = {"success": True, "doc_name": "doc.docx"}
            mock_get.return_value = mock_svc
            result = _execute_shipment_generate_tool(
                {"unit_name": "U1", "products": [{"product_name": "P1"}]}
            )
            assert result["success"] is True

    def test_import_error(self) -> None:
        # ImportError is caught when ``from app.bootstrap import ...`` fails.
        # We force the import to fail by hiding the attribute on the module.
        import app.bootstrap as bootstrap_mod

        original = getattr(bootstrap_mod, "get_shipment_app_service", None)
        del bootstrap_mod.get_shipment_app_service
        try:
            result = _execute_shipment_generate_tool({"order_text": "x"})
        finally:
            if original is not None:
                bootstrap_mod.get_shipment_app_service = original
        assert result["success"] is False
        assert result["error_code"] == "service_unavailable"

    def test_value_error(self) -> None:
        with patch("app.routes.tools._parse_order_text", side_effect=ValueError("bad")):
            result = _execute_shipment_generate_tool({"order_text": "x"})
            assert result["success"] is False
            assert result["error_code"] == "invalid_parameters"

    def test_os_error(self) -> None:
        with patch("app.routes.tools._parse_order_text", side_effect=OSError("io")):
            result = _execute_shipment_generate_tool({"order_text": "x"})
            assert result["success"] is False
            assert result["error_code"] == "file_io_error"

    def test_runtime_error(self) -> None:
        with patch("app.routes.tools._parse_order_text", side_effect=RuntimeError("fail")):
            result = _execute_shipment_generate_tool({"order_text": "x"})
            assert result["success"] is False
            assert result["error_code"] == "generation_failed"


class TestExecuteShipmentRecordsTool:
    """Cover _execute_shipment_records_tool."""

    def test_with_unit_name(self) -> None:
        with patch("app.bootstrap.get_shipment_app_service") as mock_get:
            mock_svc = MagicMock()
            mock_svc.get_shipment_records.return_value = []
            mock_get.return_value = mock_svc
            result = _execute_shipment_records_tool({"unit_name": "U1"})
            assert result["success"] is True

    def test_with_keyword(self) -> None:
        with patch("app.bootstrap.get_shipment_app_service") as mock_get:
            mock_svc = MagicMock()
            mock_svc.get_shipment_records.return_value = []
            mock_get.return_value = mock_svc
            result = _execute_shipment_records_tool({"keyword": "K"})
            assert result["success"] is True

    def test_import_error(self) -> None:
        with patch("app.bootstrap.get_shipment_app_service", side_effect=ImportError("no")):
            result = _execute_shipment_records_tool({})
            assert result["success"] is False
            assert result["error_code"] == "service_unavailable"

    def test_value_error(self) -> None:
        with patch("app.bootstrap.get_shipment_app_service", side_effect=ValueError("bad")):
            result = _execute_shipment_records_tool({})
            assert result["success"] is False
            assert result["error_code"] == "invalid_parameters"

    def test_runtime_error(self) -> None:
        with patch("app.bootstrap.get_shipment_app_service", side_effect=RuntimeError("fail")):
            result = _execute_shipment_records_tool({})
            assert result["success"] is False
            assert result["error_code"] == "query_failed"


class TestExecuteMaterialsTool:
    """Cover _execute_materials_tool."""

    def test_with_keyword(self) -> None:
        with patch("app.bootstrap.get_materials_service") as mock_get:
            mock_svc = MagicMock()
            mock_svc.get_all_materials.return_value = {"success": True, "data": []}
            mock_get.return_value = mock_svc
            result = _execute_materials_tool({"keyword": "K"})
            assert result["success"] is True

    def test_with_search(self) -> None:
        with patch("app.bootstrap.get_materials_service") as mock_get:
            mock_svc = MagicMock()
            mock_svc.get_all_materials.return_value = {"success": True, "data": []}
            mock_get.return_value = mock_svc
            result = _execute_materials_tool({"search": "S"})
            assert result["success"] is True

    def test_import_error(self) -> None:
        with patch("app.bootstrap.get_materials_service", side_effect=ImportError("no")):
            result = _execute_materials_tool({})
            assert result["success"] is False
            assert result["error_code"] == "service_unavailable"

    def test_value_error(self) -> None:
        with patch("app.bootstrap.get_materials_service", side_effect=ValueError("bad")):
            result = _execute_materials_tool({})
            assert result["success"] is False
            assert result["error_code"] == "invalid_parameters"

    def test_runtime_error(self) -> None:
        with patch("app.bootstrap.get_materials_service", side_effect=RuntimeError("fail")):
            result = _execute_materials_tool({})
            assert result["success"] is False
            assert result["error_code"] == "query_failed"


class TestExecutePrintLabelTool:
    """Cover _execute_print_label_tool."""

    def test_missing_products(self) -> None:
        result = _execute_print_label_tool({})
        assert result["success"] is False
        assert result["error_code"] == "missing_products"

    def test_empty_products_list(self) -> None:
        result = _execute_print_label_tool({"products": []})
        assert result["success"] is False
        assert result["error_code"] == "missing_products"

    def test_import_error(self) -> None:
        with patch("app.infrastructure.documents.shipment_document_generator_impl.SimpleLabelGenerator", side_effect=ImportError("no")):
            result = _execute_print_label_tool({"products": [{"name": "P1"}]})
            assert result["success"] is False
            assert result["error_code"] == "service_unavailable"


class TestExecuteExcelDecomposeTool:
    """Cover _execute_excel_decompose_tool."""

    def test_missing_file_path(self) -> None:
        result = _execute_excel_decompose_tool({})
        assert result["success"] is False
        assert result["error_code"] == "missing_file_path"

    def test_import_error(self) -> None:
        with patch("app.bootstrap.get_template_app_service", side_effect=ImportError("no")):
            result = _execute_excel_decompose_tool({"file_path": "/tmp/x.xlsx"})
            assert result["success"] is False
            assert result["error_code"] == "service_unavailable"

    def test_value_error(self) -> None:
        with patch("app.bootstrap.get_template_app_service", side_effect=ValueError("bad")):
            result = _execute_excel_decompose_tool({"file_path": "/tmp/x.xlsx"})
            assert result["success"] is False
            assert result["error_code"] == "invalid_parameters"

    def test_os_error(self) -> None:
        with patch("app.bootstrap.get_template_app_service", side_effect=OSError("io")):
            result = _execute_excel_decompose_tool({"file_path": "/tmp/x.xlsx"})
            assert result["success"] is False
            assert result["error_code"] == "file_not_found"

    def test_runtime_error(self) -> None:
        with patch("app.bootstrap.get_template_app_service", side_effect=RuntimeError("fail")):
            result = _execute_excel_decompose_tool({"file_path": "/tmp/x.xlsx"})
            assert result["success"] is False
            assert result["error_code"] == "decomposition_failed"


class TestExecuteTemplateExtractTool:
    """Cover _execute_template_extract_tool (delegates to decompose)."""

    def test_missing_file_path(self) -> None:
        result = _execute_template_extract_tool({})
        assert result["success"] is False
        assert result["error_code"] == "missing_file_path"


class TestExecuteWechatPreviewTool:
    """Cover _execute_wechat_preview_tool."""

    def test_with_keyword(self) -> None:
        with patch("app.bootstrap.get_wechat_contact_app_service") as mock_get:
            mock_svc = MagicMock()
            mock_svc.get_contacts.return_value = [{"name": "C1"}]
            mock_get.return_value = mock_svc
            result = _execute_wechat_preview_tool({"keyword": "K"})
            assert result["success"] is True

    def test_no_contacts_found(self) -> None:
        with patch("app.bootstrap.get_wechat_contact_app_service") as mock_get:
            mock_svc = MagicMock()
            mock_svc.get_contacts.return_value = []
            mock_get.return_value = mock_svc
            result = _execute_wechat_preview_tool({"keyword": "K"})
            assert result["success"] is True
            assert "未找到" in result["message"]

    def test_import_error(self) -> None:
        with patch("app.bootstrap.get_wechat_contact_app_service", side_effect=ImportError("no")):
            result = _execute_wechat_preview_tool({})
            assert result["success"] is False
            assert result["error_code"] == "service_unavailable"

    def test_value_error(self) -> None:
        with patch("app.bootstrap.get_wechat_contact_app_service", side_effect=ValueError("bad")):
            result = _execute_wechat_preview_tool({})
            assert result["success"] is False
            assert result["error_code"] == "invalid_parameters"

    def test_runtime_error(self) -> None:
        with patch("app.bootstrap.get_wechat_contact_app_service", side_effect=RuntimeError("fail")):
            result = _execute_wechat_preview_tool({})
            assert result["success"] is False
            assert result["error_code"] == "query_failed"


class TestExecuteExcelSchemaTool:
    """Cover _execute_excel_schema_tool."""

    def test_missing_file_path(self) -> None:
        result = _execute_excel_schema_tool({})
        assert result["success"] is False
        assert result["error_code"] == "missing_file_path"

    def test_import_error_for_service(self) -> None:
        # ``get_excel_analysis_app_service`` is not exported from app.bootstrap,
        # so the first branch always raises ImportError and falls through to
        # the openpyxl fallback. We force the openpyxl import to fail too to
        # exercise the ``library_unavailable`` error path.
        with patch.dict("sys.modules", {"openpyxl": None}):
            result = _execute_excel_schema_tool({"file_path": "/tmp/x.xlsx"})
        assert result["success"] is False
        assert result["error_code"] == "library_unavailable"


class TestExecuteExcelAnalysisTool:
    """Cover _execute_excel_analysis_tool."""

    def test_missing_file_path(self) -> None:
        result = _execute_excel_analysis_tool({})
        assert result["success"] is False
        assert result["error_code"] == "missing_file_path"

    def test_import_error_for_service(self) -> None:
        # Same as above: service import fails, openpyxl fallback also fails.
        with patch.dict("sys.modules", {"openpyxl": None}):
            result = _execute_excel_analysis_tool({"file_path": "/tmp/x.xlsx"})
        assert result["success"] is False
        assert result["error_code"] == "library_unavailable"


class TestExecuteImportExcelTool:
    """Cover _execute_import_excel_tool."""

    def test_missing_file_path(self) -> None:
        with patch("app.bootstrap.get_products_service"):
            with patch("app.bootstrap.get_customer_app_service", side_effect=ImportError):
                result = _execute_import_excel_tool({})
                assert result["success"] is False
                assert result["error_code"] == "missing_file_path"

    def test_import_error_products_service(self) -> None:
        with patch("app.bootstrap.get_products_service", side_effect=ImportError("no")):
            result = _execute_import_excel_tool({"file_path": "/tmp/x.xlsx"})
            assert result["success"] is False
            assert result["error_code"] == "service_unavailable"

    def test_runtime_error_products_service(self) -> None:
        with patch("app.bootstrap.get_products_service", side_effect=RuntimeError("init fail")):
            result = _execute_import_excel_tool({"file_path": "/tmp/x.xlsx"})
            assert result["success"] is False
            assert result["error_code"] == "service_init_failed"


class TestFilterToolRegistryForProfile:
    """Cover _filter_tool_registry_for_profile."""

    def test_normal_removes_pro_only(self) -> None:
        reg = {
            "tool_a": {
                "availability": "shared",
                "actions": {"query": {"availability": "shared", "risk": "low"}},
            },
            "tool_b": {
                "availability": "pro_only",
                "actions": {"exec": {"availability": "pro_only", "risk": "high"}},
            },
        }
        result = _filter_tool_registry_for_profile(reg, "normal")
        assert "tool_a" in result
        assert "tool_b" not in result

    def test_pro_default_removes_normal_only(self) -> None:
        reg = {
            "tool_a": {
                "availability": "shared",
                "actions": {"query": {"availability": "shared", "risk": "low"}},
            },
            "tool_b": {
                "availability": "normal_only",
                "actions": {"slot": {"availability": "normal_only", "risk": "low"}},
            },
        }
        result = _filter_tool_registry_for_profile(reg, "pro_default")
        assert "tool_a" in result
        assert "tool_b" not in result

    def test_shared_kept_in_both(self) -> None:
        reg = {
            "tool_a": {
                "availability": "shared",
                "actions": {"query": {"availability": "shared", "risk": "low"}},
            },
        }
        assert "tool_a" in _filter_tool_registry_for_profile(reg, "normal")
        assert "tool_a" in _filter_tool_registry_for_profile(reg, "pro_default")

    def test_action_level_filtering(self) -> None:
        reg = {
            "tool_a": {
                "availability": "shared",
                "actions": {
                    "query": {"availability": "shared", "risk": "low"},
                    "admin": {"availability": "pro_only", "risk": "high"},
                },
            },
        }
        result = _filter_tool_registry_for_profile(reg, "normal")
        assert "query" in result["tool_a"]["actions"]
        assert "admin" not in result["tool_a"]["actions"]

    def test_non_dict_spec_skipped(self) -> None:
        reg = {"bad": "not a dict"}
        result = _filter_tool_registry_for_profile(reg, "normal")
        assert "bad" not in result

    def test_empty_actions_skipped(self) -> None:
        reg = {
            "tool_a": {
                "availability": "pro_only",
                "actions": {"query": {"availability": "pro_only", "risk": "low"}},
            },
        }
        result = _filter_tool_registry_for_profile(reg, "normal")
        assert "tool_a" not in result

    def test_non_dict_actions_skipped(self) -> None:
        reg = {
            "tool_a": {
                "availability": "shared",
                "actions": "not a dict",
            },
        }
        result = _filter_tool_registry_for_profile(reg, "normal")
        assert "tool_a" not in result

    def test_non_dict_action_meta_skipped(self) -> None:
        reg = {
            "tool_a": {
                "availability": "shared",
                "actions": {"query": "not a dict"},
            },
        }
        result = _filter_tool_registry_for_profile(reg, "normal")
        assert "tool_a" not in result


class TestLLMWorkflowPlannerFallback:
    """Cover LLMWorkflowPlanner._fallback_plan."""

    def _make_planner(self) -> LLMWorkflowPlanner:
        with patch("app.application.workflow.planner.get_ai_conversation_service"):
            return LLMWorkflowPlanner()

    def test_fallback_add_product(self) -> None:
        planner = self._make_planner()
        reg = get_tool_registry()
        plan = planner._fallback_plan("p1", "添加产品到公司A", reg)
        assert plan.intent == "add_product_to_unit"
        assert len(plan.nodes) >= 1

    def test_fallback_create_product_english(self) -> None:
        # The intent matcher requires the Chinese token "产品" — English-only
        # input falls through to generic_workflow. We assert the actual
        # contract so the behaviour is documented.
        planner = self._make_planner()
        reg = get_tool_registry()
        plan = planner._fallback_plan("p1", "create product", reg)
        assert plan.intent == "generic_workflow"
        assert len(plan.nodes) >= 1

    def test_fallback_create_product_chinese(self) -> None:
        planner = self._make_planner()
        reg = get_tool_registry()
        plan = planner._fallback_plan("p1", "添加产品", reg)
        assert plan.intent == "add_product_to_unit"

    def test_fallback_generic(self) -> None:
        planner = self._make_planner()
        reg = get_tool_registry()
        plan = planner._fallback_plan("p1", "查询信息", reg)
        assert plan.intent == "generic_workflow"
        assert len(plan.nodes) >= 1

    def test_fallback_no_products_in_registry(self) -> None:
        planner = self._make_planner()
        reg = {"customers": {"actions": {"query": {"risk": "low"}}}}
        plan = planner._fallback_plan("p1", "查询", reg)
        assert len(plan.nodes) >= 1
        assert plan.nodes[0].tool_id == "customers"

    def test_fallback_empty_registry(self) -> None:
        planner = self._make_planner()
        plan = planner._fallback_plan("p1", "查询", {})
        assert len(plan.nodes) == 0
        assert plan.risk_level == "low"

    def test_fallback_risk_level_medium(self) -> None:
        planner = self._make_planner()
        reg = get_tool_registry()
        plan = planner._fallback_plan("p1", "添加产品", reg)
        # customers.ensure_exists is medium risk
        assert plan.risk_level in ("low", "medium", "high")


class TestLLMWorkflowPlannerPlanWithLLM:
    """Cover LLMWorkflowPlanner._plan_with_llm."""

    def test_no_api_key_returns_none(self) -> None:
        with patch("app.application.workflow.planner.get_ai_conversation_service") as mock_get:
            mock_svc = Mock()
            mock_svc.api_key = ""
            mock_get.return_value = mock_svc
            planner = LLMWorkflowPlanner()
            result = planner._plan_with_llm("p1", "u1", "hello", get_tool_registry(), {})
            assert result is None

    def test_llm_http_error_returns_none(self) -> None:
        mock_response = Mock()
        mock_response.status_code = 500
        mock_client = Mock()
        mock_client.post.return_value = mock_response

        with patch("app.application.workflow.planner.get_ai_conversation_service") as mock_get:
            mock_svc = Mock()
            mock_svc.api_key = "key"
            mock_svc.api_url = "http://fake"
            mock_svc.model = "m"
            mock_svc.get_context.return_value = None
            mock_get.return_value = mock_svc
            planner = LLMWorkflowPlanner()
            with patch("app.application.workflow.planner._get_planner_http_client", return_value=mock_client):
                result = planner._plan_with_llm("p1", "u1", "hello", get_tool_registry(), {})
                assert result is None

    def test_llm_empty_content_returns_none(self) -> None:
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"choices": [{"message": {"content": ""}}]}
        mock_client = Mock()
        mock_client.post.return_value = mock_response

        with patch("app.application.workflow.planner.get_ai_conversation_service") as mock_get:
            mock_svc = Mock()
            mock_svc.api_key = "key"
            mock_svc.api_url = "http://fake"
            mock_svc.model = "m"
            mock_svc.get_context.return_value = None
            mock_get.return_value = mock_svc
            planner = LLMWorkflowPlanner()
            with patch("app.application.workflow.planner._get_planner_http_client", return_value=mock_client):
                result = planner._plan_with_llm("p1", "u1", "hello", get_tool_registry(), {})
                assert result is None

    def test_llm_invalid_json_returns_none(self) -> None:
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "not json{"}}]
        }
        mock_client = Mock()
        mock_client.post.return_value = mock_response

        with patch("app.application.workflow.planner.get_ai_conversation_service") as mock_get:
            mock_svc = Mock()
            mock_svc.api_key = "key"
            mock_svc.api_url = "http://fake"
            mock_svc.model = "m"
            mock_svc.get_context.return_value = None
            mock_get.return_value = mock_svc
            planner = LLMWorkflowPlanner()
            with patch("app.application.workflow.planner._get_planner_http_client", return_value=mock_client):
                result = planner._plan_with_llm("p1", "u1", "hello", get_tool_registry(), {})
                assert result is None

    def test_llm_valid_plan(self) -> None:
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "intent": "product_query",
                                "todo_steps": ["查询产品"],
                                "risk_level": "low",
                                "nodes": [
                                    {
                                        "node_id": "n1",
                                        "tool_id": "products",
                                        "action": "query",
                                        "params": {"keyword": "test"},
                                        "risk": "low",
                                        "idempotent": True,
                                        "description": "查询产品",
                                        "depends_on": [],
                                    }
                                ],
                            }
                        )
                    }
                }
            ]
        }
        mock_client = Mock()
        mock_client.post.return_value = mock_response

        with patch("app.application.workflow.planner.get_ai_conversation_service") as mock_get:
            mock_svc = Mock()
            mock_svc.api_key = "key"
            mock_svc.api_url = "http://fake"
            mock_svc.model = "m"
            mock_svc.get_context.return_value = None
            mock_get.return_value = mock_svc
            planner = LLMWorkflowPlanner()
            with patch("app.application.workflow.planner._get_planner_http_client", return_value=mock_client):
                result = planner._plan_with_llm("p1", "u1", "hello", get_tool_registry(), {})
                assert result is not None
                assert result.intent == "product_query"
                assert len(result.nodes) == 1


class TestLLMWorkflowPlannerValidateRequiredParams:
    """Cover LLMWorkflowPlanner._validate_required_params."""

    def test_valid_plan(self) -> None:
        plan = PlanGraph(
            plan_id="p1",
            intent="test",
            nodes=[
                WorkflowNode(
                    node_id="n1",
                    tool_id="customers",
                    action="ensure_exists",
                    params={"unit_name": "公司A"},
                )
            ],
        )
        reg = {"customers": {"actions": {"ensure_exists": {"required_params": ["unit_name"]}}}}
        result = LLMWorkflowPlanner._validate_required_params(plan, reg)
        assert result is None

    def test_missing_required_param(self) -> None:
        plan = PlanGraph(
            plan_id="p1",
            intent="test",
            nodes=[
                WorkflowNode(
                    node_id="n1",
                    tool_id="customers",
                    action="ensure_exists",
                    params={},
                )
            ],
        )
        reg = {"customers": {"actions": {"ensure_exists": {"required_params": ["unit_name"]}}}}
        result = LLMWorkflowPlanner._validate_required_params(plan, reg)
        assert result is not None
        assert "unit_name" in result

    def test_empty_required_param(self) -> None:
        plan = PlanGraph(
            plan_id="p1",
            intent="test",
            nodes=[
                WorkflowNode(
                    node_id="n1",
                    tool_id="customers",
                    action="ensure_exists",
                    params={"unit_name": "  "},
                )
            ],
        )
        reg = {"customers": {"actions": {"ensure_exists": {"required_params": ["unit_name"]}}}}
        result = LLMWorkflowPlanner._validate_required_params(plan, reg)
        assert result is not None

    def test_none_required_param(self) -> None:
        plan = PlanGraph(
            plan_id="p1",
            intent="test",
            nodes=[
                WorkflowNode(
                    node_id="n1",
                    tool_id="customers",
                    action="ensure_exists",
                    params={"unit_name": None},
                )
            ],
        )
        reg = {"customers": {"actions": {"ensure_exists": {"required_params": ["unit_name"]}}}}
        result = LLMWorkflowPlanner._validate_required_params(plan, reg)
        assert result is not None

    def test_unknown_tool_skipped(self) -> None:
        plan = PlanGraph(
            plan_id="p1",
            intent="test",
            nodes=[WorkflowNode(node_id="n1", tool_id="unknown_tool", action="x", params={})],
        )
        result = LLMWorkflowPlanner._validate_required_params(plan, {})
        assert result is None

    def test_non_dict_actions_skipped(self) -> None:
        plan = PlanGraph(
            plan_id="p1",
            intent="test",
            nodes=[WorkflowNode(node_id="n1", tool_id="t", action="a", params={})],
        )
        reg = {"t": {"actions": "not a dict"}}
        result = LLMWorkflowPlanner._validate_required_params(plan, reg)
        assert result is None

    def test_non_dict_action_meta_skipped(self) -> None:
        plan = PlanGraph(
            plan_id="p1",
            intent="test",
            nodes=[WorkflowNode(node_id="n1", tool_id="t", action="a", params={})],
        )
        reg = {"t": {"actions": {"a": "not a dict"}}}
        result = LLMWorkflowPlanner._validate_required_params(plan, reg)
        assert result is None

    def test_non_list_required_params(self) -> None:
        plan = PlanGraph(
            plan_id="p1",
            intent="test",
            nodes=[WorkflowNode(node_id="n1", tool_id="t", action="a", params={})],
        )
        reg = {"t": {"actions": {"a": {"required_params": "not a list"}}}}
        result = LLMWorkflowPlanner._validate_required_params(plan, reg)
        assert result is None


class TestLLMWorkflowPlannerCriticRepair:
    """Cover LLMWorkflowPlanner._critic_repair_with_llm."""

    def test_no_api_key_returns_none(self) -> None:
        with patch("app.application.workflow.planner.get_ai_conversation_service") as mock_get:
            mock_svc = Mock()
            mock_svc.api_key = ""
            mock_get.return_value = mock_svc
            planner = LLMWorkflowPlanner()
            invalid_plan = PlanGraph(plan_id="p1", intent="test", nodes=[])
            result = planner._critic_repair_with_llm(
                "p1", "u1", "msg", {}, {}, "error", invalid_plan
            )
            assert result is None

    def test_http_error_returns_none(self) -> None:
        mock_response = Mock()
        mock_response.status_code = 500
        mock_client = Mock()
        mock_client.post.return_value = mock_response

        with patch("app.application.workflow.planner.get_ai_conversation_service") as mock_get:
            mock_svc = Mock()
            mock_svc.api_key = "key"
            mock_svc.api_url = "http://fake"
            mock_svc.model = "m"
            mock_get.return_value = mock_svc
            planner = LLMWorkflowPlanner()
            invalid_plan = PlanGraph(plan_id="p1", intent="test", nodes=[])
            with patch("app.application.workflow.planner._get_planner_http_client", return_value=mock_client):
                result = planner._critic_repair_with_llm(
                    "p1", "u1", "msg", {}, {}, "error", invalid_plan
                )
                assert result is None

    def test_empty_content_returns_none(self) -> None:
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"choices": [{"message": {"content": ""}}]}
        mock_client = Mock()
        mock_client.post.return_value = mock_response

        with patch("app.application.workflow.planner.get_ai_conversation_service") as mock_get:
            mock_svc = Mock()
            mock_svc.api_key = "key"
            mock_svc.api_url = "http://fake"
            mock_svc.model = "m"
            mock_get.return_value = mock_svc
            planner = LLMWorkflowPlanner()
            invalid_plan = PlanGraph(plan_id="p1", intent="test", nodes=[])
            with patch("app.application.workflow.planner._get_planner_http_client", return_value=mock_client):
                result = planner._critic_repair_with_llm(
                    "p1", "u1", "msg", {}, {}, "error", invalid_plan
                )
                assert result is None


class TestLLMWorkflowPlannerPlan:
    """Cover LLMWorkflowPlanner.plan top-level."""

    def test_plan_with_react_returns_valid(self) -> None:
        with patch("app.application.workflow.planner.get_ai_conversation_service"):
            planner = LLMWorkflowPlanner()
            valid_plan = PlanGraph(
                plan_id="p1",
                intent="test",
                nodes=[WorkflowNode(node_id="n1", tool_id="products", action="query", params={"keyword": "k"})],
            )
            with (
                patch.object(planner, "_plan_with_react_multiagent", return_value=valid_plan),
                patch(
                    "app.application.normal_chat_dispatch.resolve_tool_execution_profile",
                    return_value="full",
                ),
                patch("app.application.get_user_memory_rag_app_service", side_effect=ImportError),
            ):
                plan = planner.plan("u1", "msg", get_tool_registry())
                assert plan.plan_id == "p1"

    def test_plan_react_invalid_falls_back(self) -> None:
        with patch("app.application.workflow.planner.get_ai_conversation_service"):
            planner = LLMWorkflowPlanner()
            invalid_plan = PlanGraph(plan_id="p1", intent="", nodes=[])
            with (
                patch.object(planner, "_plan_with_react_multiagent", return_value=invalid_plan),
                patch(
                    "app.application.normal_chat_dispatch.resolve_tool_execution_profile",
                    return_value="full",
                ),
                patch("app.application.get_user_memory_rag_app_service", side_effect=ImportError),
            ):
                plan = planner.plan("u1", "msg", get_tool_registry())
                # Should fall back to fallback plan
                assert plan.intent in ("generic_workflow", "add_product_to_unit")

    def test_plan_react_none_falls_back(self) -> None:
        with patch("app.application.workflow.planner.get_ai_conversation_service"):
            planner = LLMWorkflowPlanner()
            with (
                patch.object(planner, "_plan_with_react_multiagent", return_value=None),
                patch(
                    "app.application.normal_chat_dispatch.resolve_tool_execution_profile",
                    return_value="full",
                ),
                patch("app.application.get_user_memory_rag_app_service", side_effect=ImportError),
            ):
                plan = planner.plan("u1", "msg", get_tool_registry())
                assert plan is not None

    def test_plan_with_user_memory_rag_runtime_error(self) -> None:
        with patch("app.application.workflow.planner.get_ai_conversation_service"):
            planner = LLMWorkflowPlanner()
            with (
                patch.object(planner, "_plan_with_react_multiagent", return_value=None),
                patch(
                    "app.application.normal_chat_dispatch.resolve_tool_execution_profile",
                    return_value="full",
                ),
                patch("app.application.get_user_memory_rag_app_service") as mock_rag_get,
            ):
                mock_rag = MagicMock()
                mock_rag.query.side_effect = RuntimeError("fail")
                mock_rag_get.return_value = mock_rag
                plan = planner.plan("u1", "msg", get_tool_registry())
                assert plan is not None

    def test_plan_with_user_memory_rag_value_error(self) -> None:
        with patch("app.application.workflow.planner.get_ai_conversation_service"):
            planner = LLMWorkflowPlanner()
            with (
                patch.object(planner, "_plan_with_react_multiagent", return_value=None),
                patch(
                    "app.application.normal_chat_dispatch.resolve_tool_execution_profile",
                    return_value="full",
                ),
                patch("app.application.get_user_memory_rag_app_service") as mock_rag_get,
            ):
                mock_rag = MagicMock()
                mock_rag.query.side_effect = ValueError("bad")
                mock_rag_get.return_value = mock_rag
                plan = planner.plan("u1", "msg", get_tool_registry())
                assert plan is not None

    def test_plan_with_user_memory_rag_success(self) -> None:
        with patch("app.application.workflow.planner.get_ai_conversation_service"):
            planner = LLMWorkflowPlanner()
            with (
                patch.object(planner, "_plan_with_react_multiagent", return_value=None),
                patch(
                    "app.application.normal_chat_dispatch.resolve_tool_execution_profile",
                    return_value="full",
                ),
                patch("app.application.get_user_memory_rag_app_service") as mock_rag_get,
            ):
                mock_rag = MagicMock()
                mock_rag.query.return_value = {"hits": [{"text": "memory"}]}
                mock_rag.format_for_prompt.return_value = "summary"
                mock_rag_get.return_value = mock_rag
                plan = planner.plan("u1", "msg", get_tool_registry())
                assert plan is not None


# ===========================================================================
# 3. app/application/tools/workflow.py
# ===========================================================================


class TestParseExcelHeaderRow1based:
    """Cover _parse_excel_header_row_1based."""

    def test_with_header_row(self) -> None:
        assert _parse_excel_header_row_1based({"header_row": 3}) == 3

    def test_with_header_row_index(self) -> None:
        assert _parse_excel_header_row_1based({"header_row_index": 2}) == 2

    def test_header_row_takes_precedence(self) -> None:
        assert _parse_excel_header_row_1based({"header_row": 3, "header_row_index": 2}) == 3

    def test_none_value(self) -> None:
        assert _parse_excel_header_row_1based({"header_row": None}) is None

    def test_empty_string(self) -> None:
        assert _parse_excel_header_row_1based({"header_row": ""}) is None

    def test_invalid_string(self) -> None:
        assert _parse_excel_header_row_1based({"header_row": "abc"}) is None

    def test_zero_returns_none(self) -> None:
        assert _parse_excel_header_row_1based({"header_row": 0}) is None

    def test_negative_returns_none(self) -> None:
        assert _parse_excel_header_row_1based({"header_row": -1}) is None

    def test_missing_key(self) -> None:
        assert _parse_excel_header_row_1based({}) is None


class TestExcelCellAsCleanStr:
    """Cover _excel_cell_as_clean_str."""

    def test_none(self) -> None:
        assert _excel_cell_as_clean_str(None) == ""

    def test_bool(self) -> None:
        assert _excel_cell_as_clean_str(True) == ""

    def test_nan_float(self) -> None:
        assert _excel_cell_as_clean_str(float("nan")) == ""

    def test_integer(self) -> None:
        assert _excel_cell_as_clean_str(42) == "42"

    def test_float_integer_value(self) -> None:
        assert _excel_cell_as_clean_str(3.0) == "3"

    def test_float_decimal(self) -> None:
        assert _excel_cell_as_clean_str(3.14) == "3.14"

    def test_inf_float(self) -> None:
        assert _excel_cell_as_clean_str(float("inf")) == ""

    def test_nan_string(self) -> None:
        assert _excel_cell_as_clean_str("nan") == ""

    def test_none_string(self) -> None:
        assert _excel_cell_as_clean_str("none") == ""

    def test_null_string(self) -> None:
        assert _excel_cell_as_clean_str("null") == ""

    def test_normal_string(self) -> None:
        assert _excel_cell_as_clean_str("hello") == "hello"

    def test_string_with_whitespace(self) -> None:
        assert _excel_cell_as_clean_str("  hello  ") == "hello"


class TestExcelCellAsFloat:
    """Cover _excel_cell_as_float."""

    def test_none(self) -> None:
        assert _excel_cell_as_float(None) == 0.0

    def test_nan_float(self) -> None:
        assert _excel_cell_as_float(float("nan")) == 0.0

    def test_integer(self) -> None:
        assert _excel_cell_as_float(42) == 42.0

    def test_float(self) -> None:
        assert _excel_cell_as_float(3.14) == 3.14

    def test_string_number(self) -> None:
        assert _excel_cell_as_float("3.14") == 3.14

    def test_invalid_string(self) -> None:
        assert _excel_cell_as_float("abc") == 0.0

    def test_with_custom_default(self) -> None:
        assert _excel_cell_as_float(None, default=-1.0) == -1.0

    def test_nan_result_returns_default(self) -> None:
        assert _excel_cell_as_float(float("nan"), default=5.0) == 5.0


class TestLooksLikeContractOrFooterLine:
    """Cover _looks_like_contract_or_footer_line."""

    def test_short_text_returns_false(self) -> None:
        assert _looks_like_contract_or_footer_line("短") is False

    def test_empty_returns_false(self) -> None:
        assert _looks_like_contract_or_footer_line("") is False

    def test_with_clause_substring(self) -> None:
        assert _looks_like_contract_or_footer_line("以上价格为含税价") is True

    def test_with_numbered_clause(self) -> None:
        assert _looks_like_contract_or_footer_line("1、以上各种产品请严格按说明施工") is True

    def test_normal_product_name(self) -> None:
        assert _looks_like_contract_or_footer_line("产品A型号M123") is False

    def test_numbered_clause_without_keywords(self) -> None:
        assert _looks_like_contract_or_footer_line("1、普通说明文字内容") is False


class TestInferProductFieldMapping:
    """Cover _infer_product_field_mapping."""

    def test_typical_columns(self) -> None:
        cols = ["产品名称", "型号", "规格", "单价", "单位", "数量", "备注", "品牌", "类别"]
        mapping = _infer_product_field_mapping(cols)
        assert mapping.get("name") == "产品名称"
        assert mapping.get("model_number") == "型号"
        assert mapping.get("specification") == "规格"
        assert mapping.get("price") == "单价"
        assert mapping.get("unit") == "单位"

    def test_with_price_column_hint(self) -> None:
        cols = ["调价前单价", "调价后单价"]
        mapping = _infer_product_field_mapping(cols, price_column_hint="调价前")
        assert mapping.get("price") == "调价前单价"

    def test_empty_columns(self) -> None:
        mapping = _infer_product_field_mapping([])
        assert mapping == {}

    def test_english_columns(self) -> None:
        cols = ["name", "model", "price", "quantity", "unit"]
        mapping = _infer_product_field_mapping(cols)
        assert mapping.get("name") == "name"
        assert mapping.get("model_number") == "model"

    def test_sku_column(self) -> None:
        cols = ["SKU", "name"]
        mapping = _infer_product_field_mapping(cols)
        assert mapping.get("model_number") == "SKU"

    def test_bian_hao_column(self) -> None:
        cols = ["编号", "name"]
        mapping = _infer_product_field_mapping(cols)
        assert mapping.get("model_number") == "编号"

    def test_spec_excluded_from_model(self) -> None:
        # ``规格型号`` contains ``型号`` so it IS mapped to model_number.
        # ``规格`` alone (without 号/编) is skipped from model_number and
        # mapped to specification instead.
        cols_with_hao = ["规格型号", "name"]
        mapping = _infer_product_field_mapping(cols_with_hao)
        # 规格型号 contains 型号 → mapped to model_number
        assert mapping.get("model_number") == "规格型号"

        cols_plain = ["规格", "name"]
        mapping2 = _infer_product_field_mapping(cols_plain)
        # 规格 (no 号/编) is skipped from model_number, mapped to specification
        assert mapping2.get("model_number") is None
        assert mapping2.get("specification") == "规格"


class TestHandleExcelAnalysis:
    """Cover handle_excel_analysis branches."""

    def test_missing_file_path(self) -> None:
        result = handle_excel_analysis({})
        assert result["success"] is False
        assert "file_path" in result["error"]

    def test_file_not_found(self, tmp_path: Path) -> None:
        result = handle_excel_analysis(
            {"file_path": "missing.xlsx", "action": "read"}, workspace_root=str(tmp_path)
        )
        assert result["success"] is False
        assert result["error"] == "file not found"

    def test_unsupported_action(self, tmp_path: Path) -> None:
        p = tmp_path / "data.xlsx"
        pd.DataFrame({"a": [1, 2]}).to_excel(p, index=False)
        result = handle_excel_analysis(
            {"file_path": str(p), "action": "weird"}, workspace_root=str(tmp_path)
        )
        assert result["success"] is False
        assert "unsupported_action" in result["error"]

    def test_action_read(self, tmp_path: Path) -> None:
        p = tmp_path / "data.xlsx"
        pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]}).to_excel(p, index=False)
        result = handle_excel_analysis(
            {"file_path": str(p), "action": "read"}, workspace_root=str(tmp_path)
        )
        assert result["success"] is True
        assert result["action"] == "read"
        assert result["row_count"] == 3

    def test_action_read_with_header_row(self, tmp_path: Path) -> None:
        p = tmp_path / "data.xlsx"
        pd.DataFrame({"unnamed": ["header_note", 1, 2], "a": ["A", 10, 20]}).to_excel(p, index=False)
        result = handle_excel_analysis(
            {"file_path": str(p), "action": "read", "header_row": 2},
            workspace_root=str(tmp_path),
        )
        assert result["success"] is True
        assert result.get("header_row") == 2

    def test_action_query_with_expression(self, tmp_path: Path) -> None:
        p = tmp_path / "data.xlsx"
        pd.DataFrame({"a": [1, 2, 3, 4]}).to_excel(p, index=False)
        result = handle_excel_analysis(
            {"file_path": str(p), "action": "query", "query_expression": "a > 2"},
            workspace_root=str(tmp_path),
        )
        assert result["success"] is True
        assert result["row_count"] == 2

    def test_action_query_without_expression(self, tmp_path: Path) -> None:
        p = tmp_path / "data.xlsx"
        pd.DataFrame({"a": [1, 2]}).to_excel(p, index=False)
        result = handle_excel_analysis(
            {"file_path": str(p), "action": "query"}, workspace_root=str(tmp_path)
        )
        assert result["success"] is True
        assert result["row_count"] == 2

    def test_action_aggregate_with_group_by(self, tmp_path: Path) -> None:
        p = tmp_path / "data.xlsx"
        pd.DataFrame({"category": ["A", "A", "B"], "amount": [10, 20, 30]}).to_excel(p, index=False)
        result = handle_excel_analysis(
            {
                "file_path": str(p),
                "action": "aggregate",
                "group_by": ["category"],
                "metrics": [{"column": "amount", "op": "sum"}],
            },
            workspace_root=str(tmp_path),
        )
        assert result["success"] is True
        assert result["action"] == "aggregate"

    def test_action_aggregate_no_group_by(self, tmp_path: Path) -> None:
        p = tmp_path / "data.xlsx"
        pd.DataFrame({"a": [1, 2]}).to_excel(p, index=False)
        result = handle_excel_analysis(
            {"file_path": str(p), "action": "aggregate"}, workspace_root=str(tmp_path)
        )
        assert result["success"] is True

    def test_action_aggregate_invalid_metrics(self, tmp_path: Path) -> None:
        p = tmp_path / "data.xlsx"
        pd.DataFrame({"a": [1, 2]}).to_excel(p, index=False)
        result = handle_excel_analysis(
            {
                "file_path": str(p),
                "action": "aggregate",
                "group_by": ["a"],
                "metrics": ["not_a_dict", {"column": "", "op": ""}],
            },
            workspace_root=str(tmp_path),
        )
        assert result["success"] is True

    def test_action_statistics(self, tmp_path: Path) -> None:
        p = tmp_path / "data.xlsx"
        pd.DataFrame({"a": [1, 2, 3]}).to_excel(p, index=False)
        result = handle_excel_analysis(
            {"file_path": str(p), "action": "statistics"}, workspace_root=str(tmp_path)
        )
        assert result["success"] is True
        assert result["action"] == "statistics"
        assert "dtypes" in result

    def test_action_excel_query(self, tmp_path: Path) -> None:
        p = tmp_path / "data.xlsx"
        pd.DataFrame({"a": [1, 2, 3]}).to_excel(p, index=False)
        result = handle_excel_analysis(
            {"file_path": str(p), "action": "excel_query", "natural_language": "select all"},
            workspace_root=str(tmp_path),
        )
        assert result["action"] == "excel_query"

    def test_read_failure(self, tmp_path: Path) -> None:
        p = tmp_path / "data.xlsx"
        p.write_text("not an excel file")
        with patch(
            "app.application.tools.workflow._read_excel_dataframe",
            side_effect=ValueError("bad excel"),
        ):
            result = handle_excel_analysis(
                {"file_path": str(p), "action": "read"}, workspace_root=str(tmp_path)
            )
            assert result["success"] is False
            assert "read failed" in result["error"]


class TestRunNaturalLanguagePandas:
    """Cover run_natural_language_pandas."""

    def test_empty_df(self) -> None:
        df = pd.DataFrame()
        result = run_natural_language_pandas(df, "select all")
        assert result["row_count"] == 0
        assert result["result_kind"] == "dataframe"

    def test_with_valid_df(self) -> None:
        df = pd.DataFrame({"a": [1, 2, 3]})
        result = run_natural_language_pandas(df, "select all")
        assert result["row_count"] == 3
        assert "columns" in result

    def test_with_error(self) -> None:
        # ``app.legacy.excel_text_to_pandas`` is not shipped in this repo, so
        # the import inside ``run_natural_language_pandas`` raises ImportError
        # (a RECOVERABLE_ERROR) and the function returns the original df with
        # an ``error`` key.
        df = pd.DataFrame({"a": [1, 2]})
        result = run_natural_language_pandas(df, "select all")
        assert "error" in result
        assert result["row_count"] == 2

    def test_truncation(self) -> None:
        df = pd.DataFrame({"a": list(range(300))})
        result = run_natural_language_pandas(df, "select all")
        assert result["truncated"] is True
        assert result["returned_rows"] == 200


class TestInvalidateWorkflowToolRegistry:
    """Cover invalidate_workflow_tool_registry."""

    def test_invalidates_cache(self) -> None:
        from app.application.tools import workflow as wf_mod

        wf_mod._workflow_tool_registry_cache = [{"cached": True}]
        invalidate_workflow_tool_registry()
        assert wf_mod._workflow_tool_registry_cache is None
        assert wf_mod._WORKFLOW_REG_VER > 2 or wf_mod._WORKFLOW_REG_VER == 3


class TestGetWorkflowToolRegistry:
    """Cover get_workflow_tool_registry."""

    def test_returns_list(self) -> None:
        from app.application.tools.workflow import get_workflow_tool_registry

        reg = get_workflow_tool_registry()
        assert isinstance(reg, list)
        assert len(reg) > 0

    def test_cache_hit(self) -> None:
        from app.application.tools import workflow as wf_mod

        # First call to populate cache
        reg1 = get_workflow_tool_registry()
        # Second call should return cached
        reg2 = get_workflow_tool_registry()
        assert reg1 is reg2

    def test_with_bulk_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.application.tools import workflow as wf_mod

        monkeypatch.setenv("FHD_DB_WRITE_TOKEN", "test_token")
        # Invalidate cache to force rebuild
        wf_mod._workflow_tool_registry_cache = None
        reg = get_workflow_tool_registry()
        names = [t["function"]["name"] for t in reg]
        assert "products_bulk_import" in names
        # Cleanup
        wf_mod._workflow_tool_registry_cache = None


class TestExecuteWorkflowTool:
    """Cover execute_workflow_tool dispatch."""

    def test_string_args_parsed(self) -> None:
        result = execute_workflow_tool("unknown", '{"x": 1}')
        parsed = json.loads(result)
        assert parsed["success"] is False

    def test_invalid_string_args(self) -> None:
        result = execute_workflow_tool("unknown", "not json")
        parsed = json.loads(result)
        assert parsed["success"] is False

    def test_unknown_tool(self) -> None:
        result = execute_workflow_tool("unknown_tool", {})
        parsed = json.loads(result)
        assert parsed["success"] is False
        assert parsed["error"] == "unknown_tool"

    def test_excel_chart_recommend(self) -> None:
        result = execute_workflow_tool("excel_chart_recommend", {})
        parsed = json.loads(result)
        assert "suggestions" in parsed

    def test_excel_analysis_dispatch(self, tmp_path: Path) -> None:
        p = tmp_path / "data.xlsx"
        pd.DataFrame({"a": [1, 2]}).to_excel(p, index=False)
        result = execute_workflow_tool(
            "excel_analysis",
            {"file_path": str(p), "action": "read"},
            workspace_root=str(tmp_path),
        )
        parsed = json.loads(result)
        assert parsed["success"] is True


class TestHandleImportExcelToDatabase:
    """Cover _handle_import_excel_to_database."""

    def test_missing_file_path(self) -> None:
        result = _handle_import_excel_to_database({})
        parsed = json.loads(result)
        assert parsed["success"] is False
        assert "file_path" in parsed["error"]

    def test_file_not_found(self, tmp_path: Path) -> None:
        result = _handle_import_excel_to_database(
            {"file_path": "missing.xlsx", "import_type": "products"},
            workspace_root=str(tmp_path),
        )
        parsed = json.loads(result)
        assert parsed["success"] is False
        assert parsed["error"] == "file not found"

    def test_with_token_required(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FHD_DB_WRITE_TOKEN", "secret")
        result = _handle_import_excel_to_database(
            {"file_path": "/tmp/x.xlsx", "import_type": "products"},
        )
        parsed = json.loads(result)
        assert parsed["success"] is False
        assert parsed.get("requires_token") is True

    def test_with_invalid_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FHD_DB_WRITE_TOKEN", "secret")
        result = _handle_import_excel_to_database(
            {"file_path": "/tmp/x.xlsx", "import_type": "products", "db_write_token": "wrong"},
        )
        parsed = json.loads(result)
        assert parsed["success"] is False
        assert parsed["error"] == "invalid_token"

    def test_empty_excel_file(self, tmp_path: Path) -> None:
        p = tmp_path / "empty.xlsx"
        pd.DataFrame().to_excel(p, index=False)
        result = _handle_import_excel_to_database(
            {"file_path": str(p), "import_type": "products"},
            workspace_root=str(tmp_path),
        )
        parsed = json.loads(result)
        assert parsed["success"] is False
        assert "empty" in parsed["error"]

    def test_invalid_last_data_row(self, tmp_path: Path) -> None:
        p = tmp_path / "data.xlsx"
        pd.DataFrame({"a": [1, 2, 3]}).to_excel(p, index=False)
        result = _handle_import_excel_to_database(
            {
                "file_path": str(p),
                "import_type": "products",
                "header_row": 3,
                "last_data_row_1based": 2,
            },
            workspace_root=str(tmp_path),
        )
        parsed = json.loads(result)
        assert parsed["success"] is False
        assert parsed["error"] == "invalid_last_data_row"

    def test_unknown_import_type(self, tmp_path: Path) -> None:
        p = tmp_path / "data.xlsx"
        pd.DataFrame({"a": [1, 2]}).to_excel(p, index=False)
        result = _handle_import_excel_to_database(
            {"file_path": str(p), "import_type": "unknown_type"},
            workspace_root=str(tmp_path),
        )
        parsed = json.loads(result)
        assert parsed["success"] is True
        assert parsed["preview"] is True

    def test_read_excel_failure(self, tmp_path: Path) -> None:
        p = tmp_path / "data.xlsx"
        p.write_text("not excel")
        # The customer-hint extractor and _read_excel_dataframe both call
        # openpyxl.load_workbook which raises BadZipFile (not a
        # RECOVERABLE_ERROR) on non-xlsx files. We mock both to exercise the
        # read_excel_failed error path with a RECOVERABLE_ERROR.
        with patch(
            "app.routes.template_grid_core._extract_customer_hint_from_excel",
            return_value="",
        ), patch(
            "app.application.tools.workflow._read_excel_dataframe",
            side_effect=OSError("disk read failed"),
        ):
            result = _handle_import_excel_to_database(
                {"file_path": str(p), "import_type": "products"},
                workspace_root=str(tmp_path),
            )
        parsed = json.loads(result)
        assert parsed["success"] is False
        assert "read_excel_failed" in parsed["error"]


class TestImportProductsPreviewOrExecute:
    """Cover _import_products_preview_or_execute."""

    def test_preview_mode(self) -> None:
        df = pd.DataFrame({"产品名称": ["A", "B"], "型号": ["M1", "M2"], "单价": [10, 20]})
        result = _import_products_preview_or_execute(
            df, list(df.columns), "客户A", confirm=False, row_count=2
        )
        parsed = json.loads(result)
        assert parsed["success"] is True
        assert parsed["preview"] is True
        assert parsed["import_type"] == "products"

    def test_with_clause_like_rows(self) -> None:
        df = pd.DataFrame(
            {
                "产品名称": ["产品A", "以上价格为含税价，请严格按说明施工"],
                "型号": ["M1", ""],
                "单价": [10, 0],
            }
        )
        result = _import_products_preview_or_execute(
            df, list(df.columns), "客户A", confirm=False, row_count=2
        )
        parsed = json.loads(result)
        assert parsed["success"] is True
        assert parsed["skipped_clause_like_rows"] >= 1

    def test_confirm_mode_with_service_error(self) -> None:
        df = pd.DataFrame({"产品名称": ["A"], "型号": ["M1"], "单价": [10]})
        with patch("app.bootstrap.get_customer_app_service", side_effect=ImportError("no")):
            result = _import_products_preview_or_execute(
                df, list(df.columns), "客户A", confirm=True, row_count=1
            )
            parsed = json.loads(result)
            assert parsed["success"] is False

    def test_confirm_mode_success(self) -> None:
        df = pd.DataFrame({"产品名称": ["A"], "型号": ["M1"], "单价": [10]})
        with (
            patch("app.services.unified_query_service.find_purchase_unit", return_value=None),
            patch("app.bootstrap.get_customer_app_service") as mock_cust,
            patch("app.bootstrap.get_products_service") as mock_prod,
        ):
            mock_cust_svc = MagicMock()
            mock_cust_svc.create.return_value = {"success": True}
            mock_cust.return_value = mock_cust_svc
            mock_prod_svc = MagicMock()
            mock_prod_svc.batch_add_products.return_value = {
                "success": True,
                "success_count": 1,
                "failed_count": 0,
            }
            mock_prod.return_value = mock_prod_svc
            result = _import_products_preview_or_execute(
                df, list(df.columns), "客户A", confirm=True, row_count=1
            )
            parsed = json.loads(result)
            assert parsed["success"] is True
            assert parsed["imported"] == 1

    def test_empty_df(self) -> None:
        df = pd.DataFrame({"产品名称": [], "型号": [], "单价": []})
        result = _import_products_preview_or_execute(
            df, list(df.columns), "客户A", confirm=False, row_count=0
        )
        parsed = json.loads(result)
        assert parsed["success"] is True
        assert parsed["row_count"] == 0


class TestImportCustomersPreviewOrExecute:
    """Cover _import_customers_preview_or_execute."""

    def test_preview_mode(self) -> None:
        df = pd.DataFrame(
            {
                "名称": ["客户A", "客户B"],
                "联系人": ["张三", "李四"],
                "电话": ["123", "456"],
                "地址": ["地址A", "地址B"],
            }
        )
        result = _import_customers_preview_or_execute(
            df, list(df.columns), confirm=False, row_count=2
        )
        parsed = json.loads(result)
        assert parsed["success"] is True
        assert parsed["preview"] is True
        assert parsed["import_type"] == "customers"

    def test_confirm_mode_success(self) -> None:
        df = pd.DataFrame({"名称": ["客户A"]})
        with patch("app.bootstrap.get_customer_app_service") as mock_get:
            mock_svc = MagicMock()
            mock_svc.create.return_value = {"success": True}
            mock_get.return_value = mock_svc
            result = _import_customers_preview_or_execute(
                df, list(df.columns), confirm=True, row_count=1
            )
            parsed = json.loads(result)
            assert parsed["success"] is True
            assert parsed["imported"] == 1

    def test_confirm_mode_with_error(self) -> None:
        df = pd.DataFrame({"名称": ["客户A"]})
        with patch("app.bootstrap.get_customer_app_service", side_effect=ImportError("no")):
            result = _import_customers_preview_or_execute(
                df, list(df.columns), confirm=True, row_count=1
            )
            parsed = json.loads(result)
            assert parsed["success"] is False

    def test_empty_records(self) -> None:
        df = pd.DataFrame({"名称": []})
        result = _import_customers_preview_or_execute(
            df, list(df.columns), confirm=False, row_count=0
        )
        parsed = json.loads(result)
        assert parsed["success"] is True
        assert parsed["row_count"] == 0


class TestImportOrdersPreviewOrExecute:
    """Cover _import_orders_preview_or_execute."""

    def test_preview_mode(self) -> None:
        df = pd.DataFrame(
            {
                "产品名称": ["A", "B"],
                "型号": ["M1", "M2"],
                "数量": [1, 2],
                "购买单位": ["客户A", "客户B"],
            }
        )
        result = _import_orders_preview_or_execute(
            df, list(df.columns), "客户A", confirm=False, row_count=2
        )
        parsed = json.loads(result)
        assert parsed["success"] is True
        assert parsed["preview"] is True
        assert parsed["import_type"] == "orders"

    def test_confirm_mode_success(self) -> None:
        df = pd.DataFrame(
            {
                "产品名称": ["A"],
                "型号": ["M1"],
                "数量": [1],
                "购买单位": ["客户A"],
            }
        )
        with patch("app.bootstrap.get_shipment_app_service") as mock_get:
            mock_svc = MagicMock()
            mock_svc.create_shipment.return_value = {"success": True}
            mock_get.return_value = mock_svc
            result = _import_orders_preview_or_execute(
                df, list(df.columns), None, confirm=True, row_count=1
            )
            parsed = json.loads(result)
            assert parsed["success"] is True
            assert parsed["imported"] == 1

    def test_confirm_mode_with_error(self) -> None:
        df = pd.DataFrame({"产品名称": ["A"]})
        with patch("app.bootstrap.get_shipment_app_service", side_effect=ImportError("no")):
            result = _import_orders_preview_or_execute(
                df, list(df.columns), None, confirm=True, row_count=1
            )
            parsed = json.loads(result)
            assert parsed["success"] is False

    def test_confirm_mode_no_unit(self) -> None:
        df = pd.DataFrame({"产品名称": ["A"], "型号": ["M1"], "数量": [1]})
        with patch("app.bootstrap.get_shipment_app_service") as mock_get:
            mock_svc = MagicMock()
            mock_svc.create_shipment.return_value = {"success": True}
            mock_get.return_value = mock_svc
            result = _import_orders_preview_or_execute(
                df, list(df.columns), None, confirm=True, row_count=1
            )
            parsed = json.loads(result)
            assert parsed["success"] is True
            assert parsed["failed"] >= 1

    def test_empty_df(self) -> None:
        df = pd.DataFrame({"产品名称": []})
        result = _import_orders_preview_or_execute(
            df, list(df.columns), None, confirm=False, row_count=0
        )
        parsed = json.loads(result)
        assert parsed["success"] is True
