"""Comprehensive tests for app.application.excel_template_http_app_service.

Covers: template listing, normalization, decomposition, upload, CRUD, and all helper functions.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import date, datetime, time
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from app.application.excel_template_http_app_service import (
    TEMP_EXCEL_DIR,
    TEMPLATE_DIR,
    _is_unreadable_workbook_error,
    _json_safe_cell_value,
    _map_template_category,
    _normalize_template_dto,
    _pick_sheet_name,
    _resolve_template_path,
    decompose_template,
    delete_template,
    excel_templates_test,
    get_base_dir,
    get_default_template,
    get_template,
    get_template_file,
    get_templates_list,
    list_templates_by_type,
    list_templates_get,
    save_template,
    update_template,
    upload_excel,
)

# ---------------------------------------------------------------------------
# _map_template_category
# ---------------------------------------------------------------------------


class TestMapTemplateCategory:
    def test_label_print(self):
        assert _map_template_category("标签模板") == "label_print"

    def test_print(self):
        assert _map_template_category("打印模板") == "label_print"

    def test_label(self):
        assert _map_template_category("Label Template") == "label_print"

    def test_excel_default(self):
        assert _map_template_category("发货单") == "excel"

    def test_empty(self):
        assert _map_template_category("") == "excel"

    def test_none(self):
        assert _map_template_category(None) == "excel"


# ---------------------------------------------------------------------------
# _normalize_template_dto
# ---------------------------------------------------------------------------


class TestNormalizeTemplateDto:
    def test_basic(self):
        tpl = {"template_type": "标签", "file_path": "/a.xlsx", "exists": True, "is_active": True}
        result = _normalize_template_dto(tpl)
        assert result["category"] == "label_print"
        assert result["preview_capable"] is True
        assert result["is_active"] is True

    def test_word_category(self):
        tpl = {"template_type": "excel", "file_path": "/a.docx", "exists": True}
        result = _normalize_template_dto(tpl)
        assert result["category"] == "word"

    def test_doc_category(self):
        tpl = {"template_type": "excel", "file_path": "/a.doc", "exists": True}
        result = _normalize_template_dto(tpl)
        assert result["category"] == "word"

    def test_no_file_path(self):
        tpl = {"template_type": "excel"}
        result = _normalize_template_dto(tpl)
        assert result["preview_capable"] is False

    def test_inactive(self):
        tpl = {"is_active": False}
        result = _normalize_template_dto(tpl)
        assert result["is_active"] is False

    def test_preserves_existing_category(self):
        tpl = {"category": "custom", "template_type": "excel"}
        result = _normalize_template_dto(tpl)
        assert result["category"] == "custom"

    def test_none_template(self):
        result = _normalize_template_dto(None)
        assert result["is_active"] is True


# ---------------------------------------------------------------------------
# _resolve_template_path
# ---------------------------------------------------------------------------


class TestResolveTemplatePath:
    def test_file_in_base_dir(self):
        with tempfile.NamedTemporaryFile(suffix=".xlsx", dir=get_base_dir(), delete=False) as f:
            path = f.name
        try:
            result = _resolve_template_path(os.path.basename(path))
            assert result is not None
        finally:
            os.unlink(path)

    def test_file_not_found(self):
        result = _resolve_template_path("nonexistent_file_abc123.xlsx")
        assert result is None


# ---------------------------------------------------------------------------
# _json_safe_cell_value
# ---------------------------------------------------------------------------


class TestJsonSafeCellValue:
    def test_none(self):
        assert _json_safe_cell_value(None) is None

    def test_bool(self):
        assert _json_safe_cell_value(True) is True
        assert _json_safe_cell_value(False) is False

    def test_datetime(self):
        dt = datetime(2024, 1, 1, 12, 0)
        assert _json_safe_cell_value(dt) == dt.isoformat()

    def test_date(self):
        d = date(2024, 1, 1)
        assert _json_safe_cell_value(d) == d.isoformat()

    def test_time(self):
        t = time(12, 30)
        assert _json_safe_cell_value(t) == t.isoformat()

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
        assert _json_safe_cell_value(Decimal("3.14")) == "3.14"

    def test_other_type(self):
        assert _json_safe_cell_value({1, 2}) == "{1, 2}"


# ---------------------------------------------------------------------------
# _is_unreadable_workbook_error
# ---------------------------------------------------------------------------


class TestIsUnreadableWorkbookError:
    def test_badzipfile(self):
        assert _is_unreadable_workbook_error("BadZipFile: not a zip") is True

    def test_invalid_xml(self):
        assert _is_unreadable_workbook_error("Invalid XML content") is True

    def test_not_a_zip(self):
        assert _is_unreadable_workbook_error("not a zip file") is True

    def test_normal_error(self):
        assert _is_unreadable_workbook_error("permission denied") is False

    def test_empty(self):
        assert _is_unreadable_workbook_error("") is False

    def test_none(self):
        assert _is_unreadable_workbook_error(None) is False


# ---------------------------------------------------------------------------
# _pick_sheet_name
# ---------------------------------------------------------------------------


class TestPickSheetName:
    def test_requested_name_found(self):
        assert _pick_sheet_name(["Sheet1", "出货"], "Sheet1") == "Sheet1"

    def test_chuhuo_fallback(self):
        assert _pick_sheet_name(["Sheet1", "出货"], None) == "出货"

    def test_first_sheet(self):
        assert _pick_sheet_name(["Sheet1", "Sheet2"], None) == "Sheet1"

    def test_empty_list(self):
        assert _pick_sheet_name([], None) == ""

    def test_requested_not_found(self):
        assert _pick_sheet_name(["Sheet1"], "Missing") == "Sheet1"


# ---------------------------------------------------------------------------
# get_base_dir
# ---------------------------------------------------------------------------


class TestGetBaseDir:
    def test_returns_string(self):
        assert isinstance(get_base_dir(), str)
        assert len(get_base_dir()) > 0


# ---------------------------------------------------------------------------
# excel_templates_test
# ---------------------------------------------------------------------------


class TestExcelTemplatesTest:
    def test_returns_success(self):
        resp = excel_templates_test()
        assert resp.status_code == 200
        data = resp.body
        parsed = json.loads(data)
        assert parsed["success"] is True


# ---------------------------------------------------------------------------
# list_templates_get
# ---------------------------------------------------------------------------


class TestListTemplatesGet:
    def test_happy_path(self):
        with patch(
            "app.application.excel_template_http_app_service._get_template_list",
            return_value=[{"id": "1", "name": "T1"}],
        ):
            resp = list_templates_get()
            assert resp.status_code == 200

    def test_error(self):
        with patch(
            "app.application.excel_template_http_app_service._get_template_list",
            side_effect=RuntimeError("fail"),
        ):
            resp = list_templates_get()
            assert resp.status_code == 500


# ---------------------------------------------------------------------------
# list_templates_by_type
# ---------------------------------------------------------------------------


class TestListTemplatesByType:
    def test_happy_path(self):
        mock_svc = MagicMock()
        mock_svc.list_by_type.return_value = [{"id": "1"}]
        # Reset singleton and patch at the re-export level
        import app.application.template_app_service as _ts

        _ts._template_app_service = None
        with patch("app.application.get_template_app_service", return_value=mock_svc):
            resp = list_templates_by_type(type="发货单", active_only="true")
            assert resp.status_code == 200

    def test_error(self):
        import app.application.template_app_service as _ts

        _ts._template_app_service = None
        with patch("app.application.get_template_app_service", side_effect=RuntimeError("fail")):
            resp = list_templates_by_type(type="发货单", active_only="true")
            assert resp.status_code == 500


# ---------------------------------------------------------------------------
# get_default_template
# ---------------------------------------------------------------------------


class TestGetDefaultTemplate:
    def test_not_found(self):
        mock_svc = MagicMock()
        mock_svc.get_default_for_type.return_value = None
        with patch("app.application.get_template_app_service", return_value=mock_svc):
            resp = get_default_template()
            assert resp.status_code == 404

    def test_found(self):
        mock_svc = MagicMock()
        mock_svc.get_default_for_type.return_value = {
            "id": "1",
            "template_type": "excel",
            "exists": True,
        }
        with patch("app.application.get_template_app_service", return_value=mock_svc):
            resp = get_default_template()
            assert resp.status_code == 200


# ---------------------------------------------------------------------------
# get_template_file
# ---------------------------------------------------------------------------


class TestGetTemplateFile:
    def test_not_found_id(self):
        with patch(
            "app.application.excel_template_http_app_service._get_template_list",
            return_value=[],
        ):
            resp = get_template_file("nonexistent")
            assert resp.status_code == 404

    def test_no_path(self):
        with patch(
            "app.application.excel_template_http_app_service._get_template_list",
            return_value=[{"id": "1", "exists": False, "path": None}],
        ):
            resp = get_template_file("1")
            assert resp.status_code == 404


# ---------------------------------------------------------------------------
# save_template
# ---------------------------------------------------------------------------


class TestSaveTemplate:
    def test_success(self):
        mock_svc = MagicMock()
        mock_svc.save_template_file.return_value = {"success": True}
        with patch("app.application.get_template_app_service", return_value=mock_svc):
            resp = save_template({"source_name": "a.xlsx", "target_name": "b.xlsx"})
            assert resp.status_code == 200

    def test_not_found(self):
        mock_svc = MagicMock()
        mock_svc.save_template_file.return_value = {"success": False}
        with patch("app.application.get_template_app_service", return_value=mock_svc):
            resp = save_template({})
            assert resp.status_code == 404


# ---------------------------------------------------------------------------
# decompose_template
# ---------------------------------------------------------------------------


class TestDecomposeTemplate:
    def test_no_filename_or_path(self):
        resp = decompose_template({})
        assert resp.status_code == 400

    def test_file_not_found(self):
        resp = decompose_template({"filename": "nonexistent_xyz.xlsx"})
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# upload_excel
# ---------------------------------------------------------------------------


class TestUploadExcel:
    @pytest.mark.asyncio
    async def test_no_file(self):
        resp = await upload_excel(None)
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_no_filename(self):
        mock_file = MagicMock()
        mock_file.filename = None
        resp = await upload_excel(mock_file)
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_wrong_extension(self):
        mock_file = MagicMock()
        mock_file.filename = "test.pdf"
        resp = await upload_excel(mock_file)
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# get_template (by id from DB)
# ---------------------------------------------------------------------------


class TestGetTemplate:
    def test_not_found(self):
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_db.execute.return_value = mock_result
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        with patch("app.db.session.get_db", return_value=mock_db):
            resp = get_template(999)
            assert resp.status_code == 404

    def test_found(self):
        mock_db = MagicMock()
        mock_row = MagicMock()
        mock_row.id = 1
        mock_row.template_key = "key1"
        mock_row.template_name = "Name"
        mock_row.template_type = "excel"
        mock_row.original_file_path = "/a.xlsx"
        mock_row.analyzed_data = None
        mock_row.editable_config = None
        mock_row.zone_config = None
        mock_row.merged_cells_config = None
        mock_row.style_config = None
        mock_row.business_rules = None
        mock_row.created_at = None
        mock_row.updated_at = None
        mock_result = MagicMock()
        mock_result.fetchone.return_value = mock_row
        mock_db.execute.return_value = mock_result
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        with patch("app.db.session.get_db", return_value=mock_db):
            resp = get_template(1)
            assert resp.status_code == 200


# ---------------------------------------------------------------------------
# update_template
# ---------------------------------------------------------------------------


class TestUpdateTemplate:
    def test_not_found(self):
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_db.execute.return_value = mock_result
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        with patch("app.db.session.get_db", return_value=mock_db):
            resp = update_template(999, {"template_name": "X"})
            assert resp.status_code == 404

    def test_success(self):
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = MagicMock()
        mock_db.execute.return_value = mock_result
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        with patch("app.db.session.get_db", return_value=mock_db):
            resp = update_template(1, {"template_name": "New Name"})
            assert resp.status_code == 200


# ---------------------------------------------------------------------------
# delete_template
# ---------------------------------------------------------------------------


class TestDeleteTemplate:
    def test_not_found(self):
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_db.execute.return_value = mock_result
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        with patch("app.db.session.get_db", return_value=mock_db):
            resp = delete_template(999)
            assert resp.status_code == 404

    def test_success(self):
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = MagicMock()
        mock_db.execute.return_value = mock_result
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        with patch("app.db.session.get_db", return_value=mock_db):
            resp = delete_template(1)
            assert resp.status_code == 200
