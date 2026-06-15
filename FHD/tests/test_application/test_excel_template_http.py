"""Tests for app.application.excel_template_http_app_service — coverage ramp."""

import json
import os
import tempfile
from datetime import date, datetime, time
from decimal import Decimal
from unittest.mock import MagicMock, Mock, patch

import pytest

from app.application.excel_template_http_app_service import (
    _is_unreadable_workbook_error,
    _json_safe_cell_value,
    _map_template_category,
    _normalize_template_dto,
    _pick_sheet_name,
    _resolve_template_path,
    excel_templates_test,
)


# ========================= _map_template_category =======================


class TestMapTemplateCategory:
    def test_label(self):
        assert _map_template_category("标签打印") == "label_print"

    def test_print(self):
        assert _map_template_category("打印模板") == "label_print"

    def test_excel(self):
        assert _map_template_category("发货单") == "excel"

    def test_empty(self):
        assert _map_template_category("") == "excel"


# ========================= _normalize_template_dto =======================


class TestNormalizeTemplateDto:
    def test_basic(self):
        tpl = {"template_type": "发货单", "file_path": "/tmp/a.xlsx", "exists": True}
        result = _normalize_template_dto(tpl)
        assert result["category"] == "excel"
        assert result["is_active"] is True
        assert result["preview_capable"] is True

    def test_word_file(self):
        tpl = {"template_type": "合同", "file_path": "/tmp/a.docx"}
        result = _normalize_template_dto(tpl)
        assert result["category"] == "word"

    def test_label_type(self):
        tpl = {"template_type": "标签打印"}
        result = _normalize_template_dto(tpl)
        assert result["category"] == "label_print"

    def test_inactive(self):
        tpl = {"template_type": "excel", "is_active": False}
        result = _normalize_template_dto(tpl)
        assert result["is_active"] is False

    def test_path_key(self):
        tpl = {"template_type": "excel", "path": "/tmp/b.xlsx", "exists": True}
        result = _normalize_template_dto(tpl)
        assert result["file_path"] == "/tmp/b.xlsx"


# ========================= _json_safe_cell_value =========================


class TestJsonSafeCellValue:
    def test_none(self):
        assert _json_safe_cell_value(None) is None

    def test_bool(self):
        assert _json_safe_cell_value(True) is True

    def test_datetime(self):
        dt = datetime(2026, 1, 1, 12, 0, 0)
        result = _json_safe_cell_value(dt)
        assert isinstance(result, str)
        assert "2026" in result

    def test_date(self):
        d = date(2026, 6, 14)
        result = _json_safe_cell_value(d)
        assert result == "2026-06-14"

    def test_time(self):
        t = time(10, 30, 0)
        result = _json_safe_cell_value(t)
        assert "10:30" in result

    def test_int(self):
        assert _json_safe_cell_value(42) == 42

    def test_str(self):
        assert _json_safe_cell_value("hello") == "hello"

    def test_float(self):
        assert _json_safe_cell_value(3.14) == 3.14

    def test_infinity(self):
        assert _json_safe_cell_value(float("inf")) is None

    def test_decimal(self):
        result = _json_safe_cell_value(Decimal("10.50"))
        assert result == "10.50"

    def test_other_type(self):
        result = _json_safe_cell_value(object())
        assert isinstance(result, str)


# ========================= _is_unreadable_workbook_error =================


class TestIsUnreadableWorkbookError:
    def test_bad_zip(self):
        assert _is_unreadable_workbook_error("BadZipFile: not a zip") is True

    def test_invalid_xml(self):
        assert _is_unreadable_workbook_error("Invalid XML content") is True

    def test_bad_magic(self):
        assert _is_unreadable_workbook_error("bad magic number") is True

    def test_normal_error(self):
        assert _is_unreadable_workbook_error("permission denied") is False

    def test_empty(self):
        assert _is_unreadable_workbook_error("") is False


# ========================= _pick_sheet_name ==============================


class TestPickSheetName:
    def test_requested_exists(self):
        assert _pick_sheet_name(["Sheet1", "出货", "Sheet3"], "出货") == "出货"

    def test_requested_not_exists_picks_shipment(self):
        assert _pick_sheet_name(["Sheet1", "出货明细", "Sheet3"], "不存在") == "出货明细"

    def test_no_shipment_picks_first(self):
        assert _pick_sheet_name(["Sheet1", "Sheet2"], None) == "Sheet1"

    def test_empty_list(self):
        assert _pick_sheet_name([], None) == ""

    def test_none_sheet_name(self):
        assert _pick_sheet_name(["Sheet1", "出货"], None) == "出货"


# ========================= _resolve_template_path ========================


class TestResolveTemplatePath:
    def test_file_in_base_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = os.path.join(tmpdir, "test.xlsx")
            with open(test_file, "w") as f:
                f.write("test")
            with patch(
                "app.application.excel_template_http_app_service.get_base_dir", return_value=tmpdir
            ):
                result = _resolve_template_path("test.xlsx")
            assert result == test_file

    def test_file_not_found(self):
        with patch(
            "app.application.excel_template_http_app_service.get_base_dir",
            return_value="/nonexistent",
        ):
            result = _resolve_template_path("missing_file_12345.xlsx")
        assert result is None


# ========================= excel_templates_test ==========================


class TestExcelTemplatesTest:
    def test_returns_success(self):
        result = excel_templates_test()
        assert result.status_code == 200
        body = json.loads(result.body)
        assert body["success"] is True
        assert "timestamp" in body
