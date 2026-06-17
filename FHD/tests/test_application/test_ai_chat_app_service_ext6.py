"""Tests for app.application.ai_chat_app_service — extended coverage (ext6).

Focus: _skip_pro_excel_deterministic_import env-var branches,
_merge_tool_runtime_context, _build_fallback_response greeting/default,
_resolve_excel_path_for_import, _customer_hint_from_preview_grid,
_default_purchase_unit_for_import, _guess_default_purchase_unit,
_resolve_force_header_row_1based, _resolve_sheet_name_for_reimport,
_packaging_or_measure_ratio, _header_hint_column_roles,
_price_column_buckets, _merge_user_intent_for_price_resolution,
_resolve_unit_price_column, _infer_excel_column_roles,
_fallback_excel_product_name_column, _fallback_excel_model_number_column.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# _skip_pro_excel_deterministic_import — env-var branches
# ---------------------------------------------------------------------------


class TestSkipProExcelDeterministicImportEnv:
    """Cover env-var branches of _skip_pro_excel_deterministic_import."""

    def test_force_shortcut_returns_false(self, monkeypatch):
        from app.application.ai_chat_app_service import _skip_pro_excel_deterministic_import

        monkeypatch.delenv("XCAGI_DISABLE_PRO_EXCEL_IMPORT_SHORTCUT", raising=False)
        monkeypatch.delenv("XCAGI_EXCEL_IMPORT_AI_DECIDES", raising=False)
        ctx = {"excel_import_use_deterministic_shortcut": True}
        assert _skip_pro_excel_deterministic_import(ctx) is False

    def test_skip_shortcut_flag_returns_true(self, monkeypatch):
        from app.application.ai_chat_app_service import _skip_pro_excel_deterministic_import

        monkeypatch.delenv("XCAGI_DISABLE_PRO_EXCEL_IMPORT_SHORTCUT", raising=False)
        monkeypatch.delenv("XCAGI_EXCEL_IMPORT_AI_DECIDES", raising=False)
        ctx = {"excel_import_skip_deterministic_shortcut": True}
        assert _skip_pro_excel_deterministic_import(ctx) is True

    def test_ai_decides_flag_returns_true(self, monkeypatch):
        from app.application.ai_chat_app_service import _skip_pro_excel_deterministic_import

        monkeypatch.delenv("XCAGI_DISABLE_PRO_EXCEL_IMPORT_SHORTCUT", raising=False)
        monkeypatch.delenv("XCAGI_EXCEL_IMPORT_AI_DECIDES", raising=False)
        ctx = {"excel_import_ai_decides": True}
        assert _skip_pro_excel_deterministic_import(ctx) is True

    def test_env_disable_shortcut_returns_true(self, monkeypatch):
        from app.application.ai_chat_app_service import _skip_pro_excel_deterministic_import

        monkeypatch.setenv("XCAGI_DISABLE_PRO_EXCEL_IMPORT_SHORTCUT", "1")
        monkeypatch.delenv("XCAGI_EXCEL_IMPORT_AI_DECIDES", raising=False)
        assert _skip_pro_excel_deterministic_import({}) is True

    def test_env_ai_decides_returns_true(self, monkeypatch):
        from app.application.ai_chat_app_service import _skip_pro_excel_deterministic_import

        monkeypatch.delenv("XCAGI_DISABLE_PRO_EXCEL_IMPORT_SHORTCUT", raising=False)
        monkeypatch.setenv("XCAGI_EXCEL_IMPORT_AI_DECIDES", "true")
        assert _skip_pro_excel_deterministic_import({}) is True

    def test_env_on_value_returns_true(self, monkeypatch):
        from app.application.ai_chat_app_service import _skip_pro_excel_deterministic_import

        monkeypatch.setenv("XCAGI_DISABLE_PRO_EXCEL_IMPORT_SHORTCUT", "on")
        assert _skip_pro_excel_deterministic_import({}) is True

    def test_env_yes_value_returns_true(self, monkeypatch):
        from app.application.ai_chat_app_service import _skip_pro_excel_deterministic_import

        monkeypatch.setenv("XCAGI_EXCEL_IMPORT_AI_DECIDES", "yes")
        assert _skip_pro_excel_deterministic_import({}) is True

    def test_no_flags_returns_false(self, monkeypatch):
        from app.application.ai_chat_app_service import _skip_pro_excel_deterministic_import

        monkeypatch.delenv("XCAGI_DISABLE_PRO_EXCEL_IMPORT_SHORTCUT", raising=False)
        monkeypatch.delenv("XCAGI_EXCEL_IMPORT_AI_DECIDES", raising=False)
        assert _skip_pro_excel_deterministic_import({}) is False

    def test_force_shortcut_overrides_skip(self, monkeypatch):
        from app.application.ai_chat_app_service import _skip_pro_excel_deterministic_import

        # use_deterministic_shortcut=True overrides skip flags.
        ctx = {
            "excel_import_use_deterministic_shortcut": True,
            "excel_import_skip_deterministic_shortcut": True,
            "excel_import_ai_decides": True,
        }
        assert _skip_pro_excel_deterministic_import(ctx) is False


# ---------------------------------------------------------------------------
# _merge_tool_runtime_context
# ---------------------------------------------------------------------------


class TestMergeToolRuntimeContext:
    """Cover AIChatApplicationService._merge_tool_runtime_context."""

    def test_minimal_context(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        result = AIChatApplicationService._merge_tool_runtime_context(
            "user1", "hello", None
        )
        assert result["user_id"] == "user1"
        assert result["message"] == "hello"

    def test_with_context_keys(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        ctx = {
            "ui_surface": "chat",
            "intent_channel": "default",
            "tool_execution_profile": "fast",
            "ignored_key": "ignored",
        }
        result = AIChatApplicationService._merge_tool_runtime_context(
            "user1", "hello", ctx
        )
        assert result["ui_surface"] == "chat"
        assert result["intent_channel"] == "default"
        assert result["tool_execution_profile"] == "fast"
        assert "ignored_key" not in result

    def test_with_excel_analysis_context(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        ctx = {"excel_analysis": {"file_path": "/tmp/x.xlsx"}}
        result = AIChatApplicationService._merge_tool_runtime_context(
            "user1", "hello", ctx
        )
        assert result["excel_analysis"] == {"file_path": "/tmp/x.xlsx"}

    def test_with_none_context_values(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        ctx = {"ui_surface": None, "intent_channel": "ch"}
        result = AIChatApplicationService._merge_tool_runtime_context(
            "user1", "hello", ctx
        )
        # None values are skipped.
        assert "ui_surface" not in result
        assert result["intent_channel"] == "ch"


# ---------------------------------------------------------------------------
# _build_fallback_response — greeting vs default
# ---------------------------------------------------------------------------


class TestBuildFallbackResponseBranches:
    """Cover _build_fallback_response greeting vs default branches."""

    def test_greeting_response(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        result = AIChatApplicationService._build_fallback_response("你好", "timeout")
        assert result["success"] is False
        assert result["response"]  # non-empty
        assert "您好" in result["response"] or "你好" in result["response"]

    def test_default_response(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        result = AIChatApplicationService._build_fallback_response("查询产品", "error")
        assert result["success"] is False
        assert result["response"]
        assert "原因" in result["response"]

    def test_english_greeting(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        result = AIChatApplicationService._build_fallback_response("hi there", "error")
        assert result["success"] is False
        # English greeting should also trigger greeting response.
        assert "您好" in result["response"] or "AI" in result["response"]

    def test_data_payload_structure(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        result = AIChatApplicationService._build_fallback_response("test", "err")
        assert "data" in result
        data = result["data"]
        assert data["action"] == "error_fallback"
        assert data["data"]["fallback_mode"] is True
        assert data["data"]["error_reason"] == "err"


# ---------------------------------------------------------------------------
# _resolve_excel_path_for_import
# ---------------------------------------------------------------------------


class TestResolveExcelPathForImport:
    """Cover _resolve_excel_path_for_import."""

    def test_from_excel_analysis(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        result = AIChatApplicationService._resolve_excel_path_for_import(
            {"file_path": "/tmp/a.xlsx"}, {}
        )
        assert result == "/tmp/a.xlsx"

    def test_fallback_to_preview_data(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        result = AIChatApplicationService._resolve_excel_path_for_import(
            {}, {"file_path": "/tmp/b.xlsx"}
        )
        assert result == "/tmp/b.xlsx"

    def test_empty_returns_empty(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        result = AIChatApplicationService._resolve_excel_path_for_import({}, {})
        assert result == ""


# ---------------------------------------------------------------------------
# _guess_default_purchase_unit
# ---------------------------------------------------------------------------


class TestGuessDefaultPurchaseUnit:
    """Cover _guess_default_purchase_unit."""

    def test_with_company_suffix(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        result = AIChatApplicationService._guess_default_purchase_unit(
            {"file_name": "ACME有限公司产品报价表.xlsx"}
        )
        assert "有限公司" in result

    def test_with_file_path_only(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        result = AIChatApplicationService._guess_default_purchase_unit(
            {"file_path": "/tmp/ACME厂.xlsx"}
        )
        assert "ACME" in result or "厂" in result

    def test_empty_returns_empty(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        result = AIChatApplicationService._guess_default_purchase_unit({})
        assert result == ""

    def test_strips_quotation_tokens(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        result = AIChatApplicationService._guess_default_purchase_unit(
            {"file_name": "ACME报价单.xlsx"}
        )
        # "报价单" suffix should be stripped.
        assert "报价单" not in result

    def test_short_stem_returns_empty(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        result = AIChatApplicationService._guess_default_purchase_unit(
            {"file_name": "a.xlsx"}
        )
        # Single-char stem should return empty.
        assert result == ""


# ---------------------------------------------------------------------------
# _resolve_force_header_row_1based
# ---------------------------------------------------------------------------


class TestResolveForceHeaderRow1based:
    """Cover _resolve_force_header_row_1based."""

    def test_from_grid_preview_header_row_index(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        result = AIChatApplicationService._resolve_force_header_row_1based(
            {}, {"grid_preview": {"header_row_index": 3}}
        )
        assert result == 3

    def test_from_tables(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        result = AIChatApplicationService._resolve_force_header_row_1based(
            {}, {"tables": [{"header_row": 5}]}
        )
        assert result == 5

    def test_from_sheets_tables(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        result = AIChatApplicationService._resolve_force_header_row_1based(
            {"sheets": [{"tables": [{"header_row": 7}]}]}, {}
        )
        assert result == 7

    def test_from_sheets_grid_preview(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        result = AIChatApplicationService._resolve_force_header_row_1based(
            {"sheets": [{"grid_preview": {"header_row_index": 4}}]}, {}
        )
        assert result == 4

    def test_invalid_value_returns_none(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        result = AIChatApplicationService._resolve_force_header_row_1based(
            {}, {"grid_preview": {"header_row_index": "abc"}}
        )
        assert result is None

    def test_zero_value_returns_none(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        result = AIChatApplicationService._resolve_force_header_row_1based(
            {}, {"grid_preview": {"header_row_index": 0}}
        )
        assert result is None

    def test_empty_returns_none(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        result = AIChatApplicationService._resolve_force_header_row_1based({}, {})
        assert result is None


# ---------------------------------------------------------------------------
# _resolve_sheet_name_for_reimport
# ---------------------------------------------------------------------------


class TestResolveSheetNameForReimport:
    """Cover _resolve_sheet_name_for_reimport."""

    def test_from_request_context_selected_sheet(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        result = AIChatApplicationService._resolve_sheet_name_for_reimport(
            {}, {}, {"excel_analysis_selected_sheet": {"sheet_name": "Sheet1"}}
        )
        assert result == "Sheet1"

    def test_from_request_context_preferred(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        result = AIChatApplicationService._resolve_sheet_name_for_reimport(
            {}, {}, {"preferred_sheet_name": "Sheet2"}
        )
        assert result == "Sheet2"

    def test_from_preview_data_selected(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        result = AIChatApplicationService._resolve_sheet_name_for_reimport(
            {}, {"selected_sheet_name": "Sheet3"}, None
        )
        assert result == "Sheet3"

    def test_from_preview_data_sheet_name(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        result = AIChatApplicationService._resolve_sheet_name_for_reimport(
            {}, {"sheet_name": "Sheet4"}, None
        )
        assert result == "Sheet4"

    def test_from_excel_analysis_sheets(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        result = AIChatApplicationService._resolve_sheet_name_for_reimport(
            {"sheets": [{"sheet_name": "Sheet5"}]}, {}, None
        )
        assert result == "Sheet5"

    def test_empty_returns_none(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        result = AIChatApplicationService._resolve_sheet_name_for_reimport({}, {}, None)
        assert result is None


# ---------------------------------------------------------------------------
# _packaging_or_measure_ratio
# ---------------------------------------------------------------------------


class TestPackagingOrMeasureRatio:
    """Cover _packaging_or_measure_ratio."""

    def test_all_units(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        result = AIChatApplicationService._packaging_or_measure_ratio(
            ["件", "个", "箱"]
        )
        assert result == 1.0

    def test_no_units(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        result = AIChatApplicationService._packaging_or_measure_ratio(
            ["Widget", "Gadget", "Thing"]
        )
        assert result == 0.0

    def test_mixed(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        result = AIChatApplicationService._packaging_or_measure_ratio(
            ["件", "Widget", "箱"]
        )
        assert 0.0 < result < 1.0

    def test_empty(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        result = AIChatApplicationService._packaging_or_measure_ratio([])
        assert result == 0.0

    def test_kg_value(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        result = AIChatApplicationService._packaging_or_measure_ratio(["5kg", "10kg"])
        assert result == 1.0


# ---------------------------------------------------------------------------
# _price_column_buckets
# ---------------------------------------------------------------------------


class TestPriceColumnBuckets:
    """Cover _price_column_buckets."""

    def test_before_after_generic(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        before, after, generic = AIChatApplicationService._price_column_buckets(
            ["调价前单价", "调价后单价", "现价", "单价"]
        )
        assert "调价前单价" in before
        assert "调价后单价" in after
        # "现价" does not match the price-column regex (单价|价格|报价|含税价|含税单价|金额),
        # so it is excluded. "单价" matches and is neither before nor after → generic.
        assert "单价" in generic
        assert "现价" not in generic

    def test_no_price_columns(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        before, after, generic = AIChatApplicationService._price_column_buckets(
            ["产品名称", "数量"]
        )
        assert before == []
        assert after == []
        assert generic == []

    def test_quantity_excluded(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        before, after, generic = AIChatApplicationService._price_column_buckets(
            ["数量", "计量单位"]
        )
        assert before == []
        assert after == []
        assert generic == []


# ---------------------------------------------------------------------------
# _merge_user_intent_for_price_resolution
# ---------------------------------------------------------------------------


class TestMergeUserIntentForPriceResolution:
    """Cover _merge_user_intent_for_price_resolution."""

    def test_no_context(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        result = AIChatApplicationService._merge_user_intent_for_price_resolution(
            "导入调价前", None
        )
        assert "导入调价前" in result

    def test_with_recent_messages(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        ctx = {
            "recent_messages": [
                {"role": "user", "content": "导入"},
                {"role": "assistant", "content": "好的"},
                {"role": "system", "content": "ignored"},
            ]
        }
        result = AIChatApplicationService._merge_user_intent_for_price_resolution(
            "调价前", ctx
        )
        assert "导入" in result
        assert "好的" in result
        assert "调价前" in result
        assert "ignored" not in result

    def test_with_html_content(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        ctx = {
            "recent_messages": [
                {"role": "user", "content": "<b>导入</b><br/>调价前"},
            ]
        }
        result = AIChatApplicationService._merge_user_intent_for_price_resolution(
            "确认", ctx
        )
        assert "导入" in result
        assert "调价前" in result
        assert "<b>" not in result

    def test_with_message_key(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        ctx = {"message": "导入调价前"}
        result = AIChatApplicationService._merge_user_intent_for_price_resolution(
            "确认", ctx
        )
        assert "导入调价前" in result

    def test_dedup(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        ctx = {
            "recent_messages": [
                {"role": "user", "content": "same"},
                {"role": "user", "content": "same"},
            ]
        }
        result = AIChatApplicationService._merge_user_intent_for_price_resolution(
            "same", ctx
        )
        # History dedups against itself (the second "same" is dropped), but the
        # current user_message is always appended at the end without dedup
        # against history (per docstring: avoid overwriting latest intent).
        # So we expect: "same" (from history) + "same" (current) = 2 occurrences.
        assert result.count("same") == 2
        assert result == "same\nsame"


# ---------------------------------------------------------------------------
# _resolve_unit_price_column
# ---------------------------------------------------------------------------


class TestResolveUnitPriceColumn:
    """Cover _resolve_unit_price_column."""

    def test_forced_override(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        col, err = AIChatApplicationService._resolve_unit_price_column(
            ["price", "name"], "", "import", {"unit_price": "price"}
        )
        assert col == "price"
        assert err is None

    def test_forced_override_not_in_keys(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        col, err = AIChatApplicationService._resolve_unit_price_column(
            ["name"], "", "import", {"unit_price": "missing"}
        )
        # Falls through to normal logic.
        assert col == ""

    def test_empty_keys(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        col, err = AIChatApplicationService._resolve_unit_price_column(
            [], "", "import", None
        )
        assert col == ""
        assert err is None

    def test_tension_prefer_before(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        col, err = AIChatApplicationService._resolve_unit_price_column(
            ["调价前单价", "调价后单价"],
            "",
            "导入调价前",
            None,
        )
        assert col == "调价前单价"
        assert err is None

    def test_tension_prefer_after(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        col, err = AIChatApplicationService._resolve_unit_price_column(
            ["调价前单价", "调价后单价"],
            "",
            "导入调价后",
            None,
        )
        assert col == "调价后单价"
        assert err is None

    def test_tension_both_preferred_ambiguous(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        col, err = AIChatApplicationService._resolve_unit_price_column(
            ["调价前单价", "调价后单价"],
            "",
            "导入调价前和调价后",
            None,
        )
        assert col == ""
        assert err == "ambiguous_price_columns"

    def test_tension_default_to_before(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        col, err = AIChatApplicationService._resolve_unit_price_column(
            ["调价前单价", "调价后单价"],
            "",
            "导入数据",
            None,
        )
        assert col == "调价前单价"
        assert err is None

    def test_no_tension_keep_current(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        col, err = AIChatApplicationService._resolve_unit_price_column(
            ["现价"], "现价", "import", None
        )
        assert col == "现价"
        assert err is None

    def test_generic_single(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        col, err = AIChatApplicationService._resolve_unit_price_column(
            ["单价"], "", "import", None
        )
        assert col == "单价"
        assert err is None

    def test_generic_multiple_ambiguous(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        col, err = AIChatApplicationService._resolve_unit_price_column(
            ["单价A", "单价B"], "", "import", None
        )
        assert col == ""
        assert err == "ambiguous_price_columns"


# ---------------------------------------------------------------------------
# _infer_excel_column_roles
# ---------------------------------------------------------------------------


class TestInferExcelColumnRoles:
    """Cover _infer_excel_column_roles."""

    def test_empty_records(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        svc = AIChatApplicationService.__new__(AIChatApplicationService)
        result, conf = svc._infer_excel_column_roles([])
        assert result == {}
        assert conf == 0.0

    def test_with_records(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        svc = AIChatApplicationService.__new__(AIChatApplicationService)
        records = [
            {"name": "Widget", "price": "10.5", "model": "ABC-123", "unit": "ACME"},
            {"name": "Gadget", "price": "20.0", "model": "XYZ-456", "unit": "ACME"},
        ]
        result, conf = svc._infer_excel_column_roles(records)
        assert isinstance(result, dict)
        assert "unit_price" in result
        assert "model_number" in result
        assert "unit_name" in result
        assert "product_name" in result
        assert 0.0 <= conf <= 1.0

    def test_with_only_numeric_columns(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        svc = AIChatApplicationService.__new__(AIChatApplicationService)
        records = [
            {"a": "1", "b": "2"},
            {"a": "3", "b": "4"},
        ]
        result, conf = svc._infer_excel_column_roles(records)
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# _fallback_excel_product_name_column
# ---------------------------------------------------------------------------


class TestFallbackExcelProductNameColumn:
    """Cover _fallback_excel_product_name_column."""

    def test_empty_records(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        svc = AIChatApplicationService.__new__(AIChatApplicationService)
        result = svc._fallback_excel_product_name_column([], set())
        assert result == ""

    def test_with_text_columns(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        svc = AIChatApplicationService.__new__(AIChatApplicationService)
        records = [
            {"name": "Widget A", "price": "10"},
            {"name": "Gadget B", "price": "20"},
            {"name": "Thing C", "price": "30"},
        ]
        result = svc._fallback_excel_product_name_column(records, {"price"})
        assert result == "name"

    def test_with_reserved_columns(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        svc = AIChatApplicationService.__new__(AIChatApplicationService)
        records = [
            {"name": "Widget", "price": "10"},
            {"name": "Gadget", "price": "20"},
        ]
        # If "name" is reserved, should return empty (no other candidates).
        result = svc._fallback_excel_product_name_column(records, {"name", "price"})
        assert result == ""

    def test_skips_packaging_columns(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        svc = AIChatApplicationService.__new__(AIChatApplicationService)
        records = [
            {"pack": "件", "name": "Widget"},
            {"pack": "箱", "name": "Gadget"},
            {"pack": "件", "name": "Thing"},
        ]
        result = svc._fallback_excel_product_name_column(records, set())
        # "name" should win because "pack" looks like packaging.
        assert result == "name"


# ---------------------------------------------------------------------------
# _fallback_excel_model_number_column
# ---------------------------------------------------------------------------


class TestFallbackExcelModelNumberColumn:
    """Cover _fallback_excel_model_number_column."""

    def test_empty_records(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        svc = AIChatApplicationService.__new__(AIChatApplicationService)
        result = svc._fallback_excel_model_number_column([], set())
        assert result == ""

    def test_with_model_like_values(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        svc = AIChatApplicationService.__new__(AIChatApplicationService)
        records = [
            {"model": "ABC-123", "name": "Widget"},
            {"model": "XYZ-456", "name": "Gadget"},
        ]
        result = svc._fallback_excel_model_number_column(records, {"name"})
        assert result == "model"

    def test_with_reserved_columns(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        svc = AIChatApplicationService.__new__(AIChatApplicationService)
        records = [
            {"model": "ABC-123", "name": "Widget"},
            {"model": "XYZ-456", "name": "Gadget"},
        ]
        result = svc._fallback_excel_model_number_column(records, {"model", "name"})
        assert result == ""


# ---------------------------------------------------------------------------
# _header_hint_column_roles
# ---------------------------------------------------------------------------


class TestHeaderHintColumnRoles:
    """Cover _header_hint_column_roles."""

    def test_returns_dict(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        result = AIChatApplicationService._header_hint_column_roles(
            ["产品名称", "型号", "单价", "客户"]
        )
        assert isinstance(result, dict)
        # Should contain the four standard roles.
        for role in ("unit_name", "product_name", "model_number", "unit_price"):
            assert role in result

    def test_empty_keys(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        result = AIChatApplicationService._header_hint_column_roles([])
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# _customer_hint_from_preview_grid
# ---------------------------------------------------------------------------


class TestCustomerHintFromPreviewGrid:
    """Cover _customer_hint_from_preview_grid."""

    def test_none_preview_data(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        result = AIChatApplicationService._customer_hint_from_preview_grid(None)
        assert result == ""

    def test_no_grid_preview(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        result = AIChatApplicationService._customer_hint_from_preview_grid({})
        assert result == ""

    def test_no_rows(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        result = AIChatApplicationService._customer_hint_from_preview_grid(
            {"grid_preview": {}}
        )
        assert result == ""

    def test_with_rows_no_hits(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        result = AIChatApplicationService._customer_hint_from_preview_grid(
            {"grid_preview": {"rows": [[{"text": "产品名称"}]]}}
        )
        assert result == ""


# ---------------------------------------------------------------------------
# _default_purchase_unit_for_import
# ---------------------------------------------------------------------------


class TestDefaultPurchaseUnitForImport:
    """Cover _default_purchase_unit_for_import."""

    def test_from_request_context_hint(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        result = AIChatApplicationService._default_purchase_unit_for_import(
            {}, {}, {"excel_customer_hint": "ACME Corp"}
        )
        assert result == "ACME Corp"

    def test_from_preview_data_hint(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        result = AIChatApplicationService._default_purchase_unit_for_import(
            {}, {"customer_hint": "Beta Inc"}, None
        )
        assert result == "Beta Inc"

    def test_from_preview_data_document_customer(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        result = AIChatApplicationService._default_purchase_unit_for_import(
            {}, {"document_customer": "Gamma Ltd"}, None
        )
        assert result == "Gamma Ltd"

    def test_fallback_to_guess(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        result = AIChatApplicationService._default_purchase_unit_for_import(
            {"file_name": "ACME有限公司报价表.xlsx"}, {}, None
        )
        assert "ACME" in result or result == ""


# ---------------------------------------------------------------------------
# _excel_cell_looks_like_product_measure_unit — additional branches
# ---------------------------------------------------------------------------


class TestExcelCellMeasureUnitExtra:
    """Cover additional _excel_cell_looks_like_product_measure_unit branches."""

    def test_pcs_unit(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        assert AIChatApplicationService._excel_cell_looks_like_product_measure_unit("pcs") is True

    def test_qty_with_unit(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        assert AIChatApplicationService._excel_cell_looks_like_product_measure_unit("5件") is True

    def test_long_text(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        assert (
            AIChatApplicationService._excel_cell_looks_like_product_measure_unit(
                "ACME Corporation Limited"
            )
            is False
        )

    def test_empty_string(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        assert AIChatApplicationService._excel_cell_looks_like_product_measure_unit("") is False
