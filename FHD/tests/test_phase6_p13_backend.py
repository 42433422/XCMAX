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


def _assert_shared_llm_empty_content_returns_none_0(self, _shared_literal_0):
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"choices": [{"message": {"content": _shared_literal_0}}]}
    with patch("app.application.workflow.planner.get_ai_conversation_service") as mock_get:
        mock_svc = Mock()
        mock_svc.api_key = "key"
        mock_svc.api_url = "http://fake"
        mock_svc.model = "m"
        mock_svc.get_context.return_value = None
        mock_get.return_value = mock_svc
        planner = LLMWorkflowPlanner()
        with patch(
            "app.application.workflow.planner.request_planner_completion",
            return_value=mock_response.json() if mock_response.status_code < 400 else None,
        ):
            result = planner._plan_with_llm("p1", "u1", "hello", get_tool_registry(), {})
            assert result is None


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
from app.application.tools.workflow import (
    _parse_excel_header_row_1based,
    execute_workflow_tool,
    get_workflow_tool_registry,
    handle_excel_analysis,
    invalidate_workflow_tool_registry,
)
from app.application.workflow.planner import LLMWorkflowPlanner, _filter_tool_registry_for_profile
from app.application.workflow.workflow_types import PlanGraph, WorkflowNode, validate_plan_graph
from app.services.tools_execution.registry import get_workflow_tool_registry as get_tool_registry
from tests.fixtures.planner_model import goal_review_response

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
        assert (
            _skip_pro_excel_deterministic_import({"excel_import_skip_deterministic_shortcut": True})
            is True
        )

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


class TestMergeToolRuntimeContext:
    """Cover _merge_tool_runtime_context."""

    def test_basic_merge(self) -> None:
        ctx = {"ui_surface": "normal", "intent_channel": "pro"}
        result = AIChatApplicationService._merge_tool_runtime_context("u1", "hello", ctx)
        assert result["conversation_id"] == "u1"
        assert result["message"] == "hello"
        assert result["ui_surface"] == "normal"
        assert result["intent_channel"] == "pro"

    def test_none_context(self) -> None:
        from app.infrastructure.tenant_scope import tenant_scope

        with tenant_scope(1):
            result = AIChatApplicationService._merge_tool_runtime_context("u1", "hello", None)
        assert result == {
            "conversation_id": "u1",
            "message": "hello",
            "tenant_id": "1",
        }

    def test_non_dict_context(self) -> None:
        from app.infrastructure.tenant_scope import tenant_scope

        with tenant_scope(1):
            result = AIChatApplicationService._merge_tool_runtime_context(
                "u1", "hello", "not a dict"
            )
        assert result == {
            "conversation_id": "u1",
            "message": "hello",
            "tenant_id": "1",
        }

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

    @pytest.mark.parametrize(
        "source,whitespace", [("analysis", False), ("preview", False), ("analysis", True)]
    )
    def test_path_source_and_whitespace(self, source, whitespace) -> None:
        from pathlib import Path
        from tempfile import gettempdir

        path = str(Path(gettempdir()) / "xcagi-test.xlsx")
        value = f"  {path}  " if whitespace else path
        ea = {"file_path": value if source == "analysis" else ""}
        preview = {"file_path": value if source == "preview" else ""}
        assert AIChatApplicationService._resolve_excel_path_for_import(ea, preview) == path


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
        assert (
            AIChatApplicationService._excel_cell_looks_like_product_measure_unit(value) is expected
        )


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
        result = AIChatApplicationService._merge_user_intent_for_price_resolution(
            "导入调价前", None
        )
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
        assert "shipment_orders" in reg
        assert "shipment_records" in reg

    def test_tool_has_required_fields(self) -> None:
        reg = get_tool_registry()
        for tool_id, spec in reg.items():
            assert "description" in spec, f"{tool_id} missing description"
            assert "availability" in spec, f"{tool_id} missing availability"
            assert "actions" in spec, f"{tool_id} missing actions"
            assert isinstance(spec["actions"], dict)


class TestFilterToolRegistryForProfile:
    """Cover _filter_tool_registry_for_profile."""

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
        with patch("app.application.workflow.planner.get_ai_conversation_service") as mock_get:
            mock_svc = Mock()
            mock_svc.api_key = "key"
            mock_svc.api_url = "http://fake"
            mock_svc.model = "m"
            mock_svc.get_context.return_value = None
            mock_get.return_value = mock_svc
            planner = LLMWorkflowPlanner()
            with patch(
                "app.application.workflow.planner.request_planner_completion",
                return_value=mock_response.json() if mock_response.status_code < 400 else None,
            ):
                result = planner._plan_with_llm("p1", "u1", "hello", get_tool_registry(), {})
                assert result is None

    def test_llm_empty_content_returns_none(self) -> None:
        return _assert_shared_llm_empty_content_returns_none_0(self, "")

    def test_llm_invalid_json_returns_none(self) -> None:
        return _assert_shared_llm_empty_content_returns_none_0(self, "not json{")

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
        with patch("app.application.workflow.planner.get_ai_conversation_service") as mock_get:
            mock_svc = Mock()
            mock_svc.api_key = "key"
            mock_svc.api_url = "http://fake"
            mock_svc.model = "m"
            mock_svc.get_context.return_value = None
            mock_get.return_value = mock_svc
            planner = LLMWorkflowPlanner()
            with patch(
                "app.application.workflow.planner.request_planner_completion",
                return_value=mock_response.json() if mock_response.status_code < 400 else None,
            ):
                result = planner._plan_with_llm("p1", "u1", "hello", get_tool_registry(), {})
                assert result is not None
                assert result.intent == "product_query"
                assert len(result.nodes) == 1


class TestLLMWorkflowPlannerPlan:
    """Cover LLMWorkflowPlanner.plan top-level."""

    def test_plan_with_model_returns_valid(self) -> None:
        with patch("app.application.workflow.planner.get_ai_conversation_service"):
            completion = Mock(
                side_effect=lambda **kwargs: goal_review_response(
                    json.loads(kwargs["messages"][-1]["content"]),
                    source="msg",
                    node_ids=["n1"],
                    outcome="execute",
                )
            )
            planner = LLMWorkflowPlanner(completion=completion)
            valid_plan = PlanGraph(
                plan_id="p1",
                intent="test",
                nodes=[
                    WorkflowNode(
                        node_id="n1", tool_id="products", action="query", params={"keyword": "k"}
                    )
                ],
            )
            with (
                patch.object(planner, "_plan_with_llm", return_value=valid_plan),
                patch(
                    "app.application.workflow.tool_profile.resolve_tool_execution_profile",
                    return_value="full",
                ),
                patch("app.application.get_user_memory_rag_app_service", side_effect=ImportError),
            ):
                plan = planner.plan("u1", "msg", get_tool_registry())
                assert plan.plan_id == "p1"
                completion.assert_called_once()

    def test_invalid_model_plan_is_rejected_without_fallback(self) -> None:
        with patch("app.application.workflow.planner.get_ai_conversation_service"):
            planner = LLMWorkflowPlanner()
            invalid_plan = PlanGraph(plan_id="p1", intent="", nodes=[])
            with (
                patch.object(planner, "_plan_with_llm", return_value=invalid_plan),
                patch(
                    "app.application.workflow.tool_profile.resolve_tool_execution_profile",
                    return_value="full",
                ),
                patch("app.application.get_user_memory_rag_app_service", side_effect=ImportError),
            ):
                plan = planner.plan("u1", "msg", get_tool_registry())
                assert plan.intent == "plan_rejected"
                assert plan.metadata["planning_rejected"] is True

    def test_missing_model_plan_is_rejected(self) -> None:
        with patch("app.application.workflow.planner.get_ai_conversation_service"):
            planner = LLMWorkflowPlanner()
            with (
                patch.object(planner, "_plan_with_llm", return_value=None),
                patch(
                    "app.application.workflow.tool_profile.resolve_tool_execution_profile",
                    return_value="full",
                ),
                patch("app.application.get_user_memory_rag_app_service", side_effect=ImportError),
            ):
                plan = planner.plan("u1", "msg", get_tool_registry())
                assert plan.metadata["planning_rejected"] is True

    def test_plan_with_user_memory_rag_runtime_error(self) -> None:
        with patch("app.application.workflow.planner.get_ai_conversation_service"):
            planner = LLMWorkflowPlanner()
            with (
                patch.object(planner, "_plan_with_llm", return_value=None),
                patch(
                    "app.application.workflow.tool_profile.resolve_tool_execution_profile",
                    return_value="full",
                ),
                patch("app.application.get_user_memory_rag_app_service") as mock_rag_get,
            ):
                mock_rag = MagicMock()
                mock_rag.query.side_effect = RuntimeError("fail")
                mock_rag_get.return_value = mock_rag
                plan = planner.plan("u1", "msg", get_tool_registry())
                assert plan.metadata["planning_rejected"] is True

    def test_plan_with_user_memory_rag_value_error(self) -> None:
        with patch("app.application.workflow.planner.get_ai_conversation_service"):
            planner = LLMWorkflowPlanner()
            with (
                patch.object(planner, "_plan_with_llm", return_value=None),
                patch(
                    "app.application.workflow.tool_profile.resolve_tool_execution_profile",
                    return_value="full",
                ),
                patch("app.application.get_user_memory_rag_app_service") as mock_rag_get,
            ):
                mock_rag = MagicMock()
                mock_rag.query.side_effect = ValueError("bad")
                mock_rag_get.return_value = mock_rag
                plan = planner.plan("u1", "msg", get_tool_registry())
                assert plan.metadata["planning_rejected"] is True

    def test_plan_with_user_memory_rag_success(self) -> None:
        with patch("app.application.workflow.planner.get_ai_conversation_service"):
            planner = LLMWorkflowPlanner()
            with (
                patch.object(planner, "_plan_with_llm", return_value=None),
                patch(
                    "app.application.workflow.tool_profile.resolve_tool_execution_profile",
                    return_value="full",
                ),
                patch("app.application.get_user_memory_rag_app_service") as mock_rag_get,
            ):
                mock_rag = MagicMock()
                mock_rag.query.return_value = {"hits": [{"text": "memory"}]}
                mock_rag.format_for_prompt.return_value = "summary"
                mock_rag_get.return_value = mock_rag
                plan = planner.plan("u1", "msg", get_tool_registry())
                assert plan.metadata["planning_rejected"] is True


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
        pd.DataFrame({"unnamed": ["header_note", 1, 2], "a": ["A", 10, 20]}).to_excel(
            p, index=False
        )
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
        assert result["success"] is False
        assert result["error_code"] == "missing_query_expression"
        assert "records" not in result

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
            {"file_path": str(p), "action": "aggregate", "metrics": [{"column": "a", "op": "sum"}]},
            workspace_root=str(tmp_path),
        )
        assert result["success"] is True
        assert result["records"] == [{"a_sum": 3}]

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
        assert result["success"] is False
        assert result["error"] == "invalid_aggregation_metrics"

    def test_action_statistics(self, tmp_path: Path) -> None:
        p = tmp_path / "data.xlsx"
        pd.DataFrame({"a": [1, 2, 3]}).to_excel(p, index=False)
        result = handle_excel_analysis(
            {"file_path": str(p), "action": "statistics"}, workspace_root=str(tmp_path)
        )
        assert result["success"] is True
        assert result["action"] == "statistics"
        assert "dtypes" in result

    def test_query_expression_filters_rows(self, tmp_path: Path) -> None:
        p = tmp_path / "data.xlsx"
        pd.DataFrame({"a": [1, 2, 3]}).to_excel(p, index=False)
        result = handle_excel_analysis(
            {"file_path": str(p), "action": "query", "query_expression": "a > 2"},
            workspace_root=str(tmp_path),
        )
        assert result["success"] is True
        assert result["action"] == "query"
        assert result["records"] == [{"a": 3}]

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
        assert result["error"] == "read_excel_failed"


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
        assert parsed["error_code"] == "unknown_tool"
        assert parsed["execution_status"] == "not_started"

    def test_retired_excel_alias_is_not_started(self, tmp_path: Path) -> None:
        p = tmp_path / "data.xlsx"
        pd.DataFrame({"a": [1, 2]}).to_excel(p, index=False)
        result = execute_workflow_tool(
            "excel_analysis",
            {"file_path": str(p), "action": "read"},
            workspace_root=str(tmp_path),
        )
        parsed = json.loads(result)
        assert parsed["success"] is False
        assert parsed["error_code"] == "unknown_tool"
        assert parsed["execution_status"] == "not_started"


@pytest.mark.parametrize(
    "message",
    [
        "你好",
        "查询产品",
        "",
        None,
        "hello there",
        "hi",
        "x" * 200,
        "导入",
        "导入Excel",
        "导入到数据库",
        "写入数据库",
        "帮我导入数据",
        "说明表格",
        "普通消息",
    ],
)
def test_unified_public_chat_never_turns_model_failure_or_import_words_into_success(message):
    from app.application.workflow.planner import LLMWorkflowPlanner
    from tests.test_application.ai_chat_test_helpers import _make_svc

    completion = MagicMock(return_value=None)
    svc = _make_svc()
    svc.workflow_planner = LLMWorkflowPlanner(
        ai_service=MagicMock(get_context=MagicMock(return_value=None)), completion=completion
    )
    with (
        patch.object(svc, "_persist_chat_turn"),
        patch.object(svc, "_persist_recallable_chat_turn"),
        patch("app.application.ai_chat.dialogue_memory.prepare_chat_turn", return_value=None),
        patch("app.application.ai_chat.dialogue_memory.settle_chat_turn"),
    ):
        result = svc.process_chat("u1", message, source="pro")
    assert result["success"] is False
    assert not result.get("toolCall")
    assert not svc._pending_workflows
    if message:
        completion.assert_called_once()
        assert result["data"]["execution_started"] is False
    else:
        completion.assert_not_called()


@pytest.mark.parametrize("source", ["pro", "normal", "admin", "user:7"])
def test_source_never_supplies_authenticated_identity(source):
    result = AIChatApplicationService._merge_tool_runtime_context(
        "conversation-only", "查询", {"source": source}
    )
    assert "user_id" not in result
    assert "_actor_authorization" not in result
    assert result["conversation_id"] == "conversation-only"
