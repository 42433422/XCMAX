"""Tests for app.application.excel_template_http_app_service — coverage ramp."""

from __future__ import annotations

import json
import os
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from app.application.excel_template_http_app_service import (
    _json_safe_cell_value,
    _map_template_category,
    _normalize_template_dto,
    _resolve_template_path,
    get_base_dir,
)

# ========================= _map_template_category ========================


class TestMapTemplateCategory:
    def test_label_category(self):
        assert _map_template_category("标签模板") == "label_print"

    def test_label_english(self):
        assert _map_template_category("label template") == "label_print"

    def test_print_keyword(self):
        assert _map_template_category("打印模板") == "label_print"

    def test_excel_default(self):
        assert _map_template_category("数据报表") == "excel"

    def test_empty(self):
        assert _map_template_category("") == "excel"

    def test_none(self):
        assert _map_template_category(None) == "excel"


# ========================= _normalize_template_dto =======================


class TestNormalizeTemplateDto:
    def test_basic_normalization(self):
        template = {"template_type": "标签", "file_path": "/tmp/test.xlsx", "exists": True}
        result = _normalize_template_dto(template)
        assert result["category"] == "label_print"
        assert result["is_active"] is True
        assert result["preview_capable"] is True

    def test_word_template(self):
        template = {"template_type": "report", "file_path": "/tmp/test.docx"}
        result = _normalize_template_dto(template)
        assert result["category"] == "word"

    def test_no_file_path(self):
        template = {"template_type": "excel"}
        result = _normalize_template_dto(template)
        assert result["preview_capable"] is False

    def test_inactive(self):
        template = {"is_active": False, "template_type": ""}
        result = _normalize_template_dto(template)
        assert result["is_active"] is False

    def test_existing_category_preserved(self):
        template = {"category": "custom", "template_type": "标签"}
        result = _normalize_template_dto(template)
        assert result["category"] == "custom"

    def test_path_fallback(self):
        template = {"path": "/tmp/alt.xlsx", "template_type": ""}
        result = _normalize_template_dto(template)
        assert result["file_path"] == "/tmp/alt.xlsx"

    def test_empty_dict(self):
        result = _normalize_template_dto({})
        assert result["category"] == "excel"
        assert result["is_active"] is True


# ========================= _json_safe_cell_value =========================


class TestJsonSafeCellValue:
    def test_none(self):
        assert _json_safe_cell_value(None) is None

    def test_bool(self):
        assert _json_safe_cell_value(True) is True
        assert _json_safe_cell_value(False) is False

    def test_datetime(self):
        dt = datetime(2026, 6, 14, 10, 30, 0)
        result = _json_safe_cell_value(dt)
        assert isinstance(result, str)
        assert "2026-06-14" in result

    def test_date(self):
        d = date(2026, 6, 14)
        result = _json_safe_cell_value(d)
        assert result == "2026-06-14"

    def test_time(self):
        t = time(10, 30, 0)
        result = _json_safe_cell_value(t)
        assert isinstance(result, str)

    def test_int(self):
        assert _json_safe_cell_value(42) == 42

    def test_str(self):
        assert _json_safe_cell_value("hello") == "hello"

    def test_float(self):
        assert _json_safe_cell_value(3.14) == 3.14

    def test_float_inf(self):
        assert _json_safe_cell_value(float("inf")) is None

    def test_float_nan(self):
        assert _json_safe_cell_value(float("nan")) is None

    def test_decimal(self):
        result = _json_safe_cell_value(Decimal("3.14"))
        assert result == "3.14"

    def test_other_type(self):
        result = _json_safe_cell_value([1, 2, 3])
        assert isinstance(result, str)


# ========================= get_base_dir ==================================


class TestGetBaseDir:
    def test_returns_string(self):
        result = get_base_dir()
        assert isinstance(result, str)
        assert len(result) > 0


# ========================= _resolve_template_path ========================


class TestResolveTemplatePath:
    def test_nonexistent_file(self):
        result = _resolve_template_path("nonexistent_file_12345.xlsx")
        assert result is None
