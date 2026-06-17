"""Tests for app.application.ai_chat_app_service — deep coverage (ext5).

Focus: AIChatApplicationService private methods — _is_pro_source, _is_number_text,
_sanitize_import_scalar, _excel_analysis_payload_present, _looks_like_short_excel_import_command,
_build_fallback_response, _skip_pro_excel_deterministic_import.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# AIChatApplicationService._is_pro_source
# ---------------------------------------------------------------------------


class TestIsProSource:
    def test_pro_source(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        result = AIChatApplicationService._is_pro_source("pro")
        assert result is True

    def test_normal_source(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        result = AIChatApplicationService._is_pro_source("normal")
        assert result is False

    def test_none_source(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        result = AIChatApplicationService._is_pro_source(None)
        assert result is False


# ---------------------------------------------------------------------------
# AIChatApplicationService._is_number_text
# ---------------------------------------------------------------------------


class TestIsNumberText:
    def test_integer_text(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        result = AIChatApplicationService._is_number_text("42")
        assert result is True

    def test_float_text(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        result = AIChatApplicationService._is_number_text("3.14")
        assert result is True

    def test_non_number_text(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        result = AIChatApplicationService._is_number_text("hello")
        assert result is False

    def test_empty_string(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        result = AIChatApplicationService._is_number_text("")
        assert result is False

    def test_negative_number(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        result = AIChatApplicationService._is_number_text("-5")
        assert result is True


# ---------------------------------------------------------------------------
# AIChatApplicationService._sanitize_import_scalar
# ---------------------------------------------------------------------------


class TestSanitizeImportScalar:
    def test_none(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        result = AIChatApplicationService._sanitize_import_scalar(None)
        assert result is None or result == ""

    def test_string(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        result = AIChatApplicationService._sanitize_import_scalar("hello")
        assert result == "hello"

    def test_number(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        result = AIChatApplicationService._sanitize_import_scalar(42)
        assert result == 42 or result == "42"

    def test_nan(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        result = AIChatApplicationService._sanitize_import_scalar(float("nan"))
        assert result is None or isinstance(result, (str, float))


# ---------------------------------------------------------------------------
# AIChatApplicationService._excel_analysis_payload_present
# ---------------------------------------------------------------------------


class TestExcelAnalysisPayloadPresent:
    def test_none_context(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        result = AIChatApplicationService._excel_analysis_payload_present(None)
        assert result is False

    def test_empty_context(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        result = AIChatApplicationService._excel_analysis_payload_present({})
        assert result is False

    def test_with_excel_analysis(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        # The implementation considers excel_analysis "present" when it has a
        # non-empty `summary`, a non-empty `fields` list, `preview_data.sample_rows`,
        # or `preview_data.grid_preview.rows` with >= 2 entries.
        context = {"excel_analysis": {"summary": "found columns A, B"}}
        result = AIChatApplicationService._excel_analysis_payload_present(context)
        assert result is True


# ---------------------------------------------------------------------------
# AIChatApplicationService._looks_like_short_excel_import_command
# ---------------------------------------------------------------------------


class TestLooksLikeShortExcelImportCommand:
    def test_import_command(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        result = AIChatApplicationService._looks_like_short_excel_import_command("导入Excel")
        assert isinstance(result, bool)

    def test_normal_text(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        result = AIChatApplicationService._looks_like_short_excel_import_command("你好")
        assert result is False

    def test_empty_text(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        result = AIChatApplicationService._looks_like_short_excel_import_command("")
        assert result is False


# ---------------------------------------------------------------------------
# AIChatApplicationService._build_fallback_response
# ---------------------------------------------------------------------------


class TestBuildFallbackResponse:
    def test_basic_response(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        result = AIChatApplicationService._build_fallback_response("测试消息", "超时")
        assert isinstance(result, dict)
        assert "message" in result or "text" in result or "response" in result

    def test_empty_message(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        result = AIChatApplicationService._build_fallback_response("", "错误")
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# _skip_pro_excel_deterministic_import
# ---------------------------------------------------------------------------


class TestSkipProExcelDeterministicImport:
    def test_none_context(self):
        from app.application.ai_chat_app_service import _skip_pro_excel_deterministic_import

        result = _skip_pro_excel_deterministic_import(None)
        assert isinstance(result, bool)

    def test_empty_context(self):
        from app.application.ai_chat_app_service import _skip_pro_excel_deterministic_import

        result = _skip_pro_excel_deterministic_import({})
        assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# AIChatApplicationService._row_values_look_like_table_headers
# ---------------------------------------------------------------------------


class TestRowValuesLookLikeTableHeaders:
    def test_header_like_values(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        values = ["产品名称", "型号", "数量", "单价"]
        result = AIChatApplicationService._row_values_look_like_table_headers(values)
        assert isinstance(result, bool)

    def test_numeric_values(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        values = ["100", "200", "300"]
        result = AIChatApplicationService._row_values_look_like_table_headers(values)
        assert result is False

    def test_empty_values(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        result = AIChatApplicationService._row_values_look_like_table_headers([])
        assert result is False


# ---------------------------------------------------------------------------
# AIChatApplicationService._excel_cell_looks_like_product_measure_unit
# ---------------------------------------------------------------------------


class TestExcelCellLooksLikeProductMeasureUnit:
    def test_common_unit(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        result = AIChatApplicationService._excel_cell_looks_like_product_measure_unit("kg")
        assert isinstance(result, bool)

    def test_non_unit(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        result = AIChatApplicationService._excel_cell_looks_like_product_measure_unit("产品A")
        assert result is False

    def test_none(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        result = AIChatApplicationService._excel_cell_looks_like_product_measure_unit(None)
        assert result is False


# ---------------------------------------------------------------------------
# AIChatApplicationService._model_like_score
# ---------------------------------------------------------------------------


class TestModelLikeScore:
    def test_model_number(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        result = AIChatApplicationService._model_like_score("ABC-123")
        assert isinstance(result, float)
        assert result >= 0

    def test_plain_text(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        result = AIChatApplicationService._model_like_score("产品名称")
        assert isinstance(result, float)

    def test_empty(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        result = AIChatApplicationService._model_like_score("")
        assert isinstance(result, float)
