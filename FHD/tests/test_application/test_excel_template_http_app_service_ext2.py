"""Tests for app.application.excel_template_http_app_service — coverage ext2.

Covers ``_decompose_from_grid``, ``_decompose_template_xls_pandas``,
``_decompose_template_openpyxl``, ``_decompose_template`` (file missing /
.xls / .xlsx paths), ``get_template_file``, ``save_template``,
``upload_excel`` (async), and DB-backed ``get_template`` / ``update_template``
/ ``delete_template``.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.application import excel_template_http_app_service as svc

# ── _json_safe_cell_value ────────────────────────────────────────────────────


class TestJsonSafeCellValue:
    def test_none(self):
        assert svc._json_safe_cell_value(None) is None

    def test_bool(self):
        assert svc._json_safe_cell_value(True) is True
        assert svc._json_safe_cell_value(False) is False

    def test_datetime(self):
        dt = datetime(2026, 1, 1, 12, 0, 0)
        assert svc._json_safe_cell_value(dt) == dt.isoformat()

    def test_date(self):
        d = date(2026, 1, 1)
        assert svc._json_safe_cell_value(d) == d.isoformat()

    def test_time(self):
        t = time(12, 30, 0)
        assert svc._json_safe_cell_value(t) == t.isoformat()

    def test_int(self):
        assert svc._json_safe_cell_value(42) == 42

    def test_str(self):
        assert svc._json_safe_cell_value("hello") == "hello"

    def test_float_finite(self):
        assert svc._json_safe_cell_value(3.14) == 3.14

    def test_float_infinity(self):
        assert svc._json_safe_cell_value(float("inf")) is None

    def test_float_nan(self):
        assert svc._json_safe_cell_value(float("nan")) is None

    def test_decimal(self):
        d = Decimal("3.14")
        assert svc._json_safe_cell_value(d) == "3.14"

    def test_other_types_coerced_to_str(self):
        assert svc._json_safe_cell_value([1, 2]) == "[1, 2]"


# ── _is_unreadable_workbook_error ────────────────────────────────────────────


class TestIsUnreadableWorkbookError:
    @pytest.mark.parametrize(
        "msg",
        [
            "Unable to read workbook",
            "Could not read worksheets",
            "Invalid XML",
            "BadZipFile",
            "bad zip file",
            "bad magic number",
            "central directory",
            "file is not a zip file",
            "not a zip file",
            "does not support the old .xls",
        ],
    )
    def test_matches_markers(self, msg):
        assert svc._is_unreadable_workbook_error(msg) is True

    def test_no_match(self):
        assert svc._is_unreadable_workbook_error("some other error") is False

    def test_empty(self):
        assert svc._is_unreadable_workbook_error("") is False

    def test_none(self):
        assert svc._is_unreadable_workbook_error(None) is False


# ── _pick_sheet_name ─────────────────────────────────────────────────────────


class TestPickSheetName:
    def test_explicit_name_present(self):
        assert svc._pick_sheet_name(["a", "b"], "b") == "b"

    def test_explicit_name_not_present_picks_chuhuo(self):
        assert svc._pick_sheet_name(["出货", "a"], "missing") == "出货"

    def test_no_explicit_picks_chuhuo(self):
        assert svc._pick_sheet_name(["出货", "a"], None) == "出货"

    def test_no_chuhuo_picks_first(self):
        assert svc._pick_sheet_name(["a", "b"], None) == "a"

    def test_empty_list(self):
        assert svc._pick_sheet_name([], None) == ""

    def test_none_list(self):
        assert svc._pick_sheet_name(None, None) == ""


# ── _resolve_template_path ───────────────────────────────────────────────────


class TestResolveTemplatePath:
    def test_finds_in_base_dir(self, tmp_path, monkeypatch):
        f = tmp_path / "x.xlsx"
        f.write_text("hi")
        monkeypatch.setattr(svc, "_REPO_ROOT", tmp_path)
        monkeypatch.setattr(svc, "TEMPLATE_DIR", str(tmp_path / "templates"))
        out = svc._resolve_template_path("x.xlsx")
        assert out is not None
        assert os.path.exists(out)

    def test_finds_in_template_dir(self, tmp_path, monkeypatch):
        template_dir = tmp_path / "templates"
        template_dir.mkdir()
        f = template_dir / "x.xlsx"
        f.write_text("hi")
        monkeypatch.setattr(svc, "_REPO_ROOT", tmp_path)
        monkeypatch.setattr(svc, "TEMPLATE_DIR", str(template_dir))
        out = svc._resolve_template_path("x.xlsx")
        assert out is not None

    def test_missing_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr(svc, "_REPO_ROOT", tmp_path)
        monkeypatch.setattr(svc, "TEMPLATE_DIR", str(tmp_path / "templates"))
        assert svc._resolve_template_path("missing.xlsx") is None


# ── _decompose_from_grid ─────────────────────────────────────────────────────


class TestDecomposeFromGrid:
    def test_basic_grid(self):
        # 5x5 grid with header in row 1
        def get_cell(r, c):
            if r == 1:
                return f"col{c}"
            if r <= 3:
                return f"r{r}c{c}"
            return None

        out, status = svc._decompose_from_grid(
            "/tmp/test.xlsx",
            "Sheet1",
            5,
            5,
            get_cell,
            0,
            "A1:E5",
            None,
            5,
        )
        assert status == 200
        assert out["success"] is True
        assert out["template"]["sheet"] == "Sheet1"
        assert out["decomposition"]["header_row"] == 1
        assert len(out["decomposition"]["editable_entries"]) == 5
        assert len(out["decomposition"]["sample_rows"]) == 2

    def test_no_header_row_falls_back_to_1(self):
        def get_cell(r, c):
            return None  # all empty

        out, status = svc._decompose_from_grid(
            "/tmp/test.xlsx",
            "Sheet1",
            5,
            5,
            get_cell,
            0,
            "A1:E5",
            None,
            5,
        )
        assert status == 200
        assert out["decomposition"]["header_row"] == 1
        assert out["decomposition"]["editable_entries"] == []

    def test_amount_related_entries_detected(self):
        def get_cell(r, c):
            if r == 1 and c == 1:
                return "金额"
            if r == 1 and c == 2:
                return "数量"
            if r == 1 and c == 3:
                return "名称"
            if r == 1 and c == 4:
                return "单价"
            return None

        out, _ = svc._decompose_from_grid(
            "/tmp/test.xlsx",
            "Sheet1",
            5,
            5,
            get_cell,
            0,
            "A1:E5",
            None,
            5,
        )
        amount_related = out["decomposition"]["amount_related_entries"]
        # 金额, 数量, 单价 should be detected
        assert len(amount_related) == 3

    def test_max_rows_capped_at_30(self):
        def get_cell(r, c):
            return None

        out, _ = svc._decompose_from_grid(
            "/tmp/test.xlsx",
            "Sheet1",
            100,  # > 30
            5,
            get_cell,
            0,
            "A1:E100",
            None,
            5,
        )
        # Should not crash; header_row defaults to 1
        assert out["decomposition"]["header_row"] == 1

    def test_max_cols_capped_at_25(self):
        def get_cell(r, c):
            return None

        out, _ = svc._decompose_from_grid(
            "/tmp/test.xlsx",
            "Sheet1",
            5,
            100,  # > 25
            get_cell,
            0,
            "A1:CV5",
            None,
            5,
        )
        assert out["success"] is True


# ── _decompose_template ──────────────────────────────────────────────────────


class TestDecomposeTemplate:
    def test_missing_file(self):
        out, status = svc._decompose_template("/nonexistent/file.xlsx")
        assert status == 404
        assert out["success"] is False
        assert "不存在" in out["message"]

    def test_xlsx_unreadable(self, tmp_path):
        f = tmp_path / "bad.xlsx"
        f.write_text("not an xlsx")
        with patch.object(
            svc, "_decompose_template_openpyxl", side_effect=OSError("BadZipFile: bad zip")
        ):
            out, status = svc._decompose_template(str(f))
        assert status == 200
        assert out["success"] is False
        assert out.get("error_code") == "UNREADABLE_WORKBOOK"

    def test_xlsx_other_error(self, tmp_path):
        f = tmp_path / "bad.xlsx"
        f.write_text("not an xlsx")
        with patch.object(
            svc, "_decompose_template_openpyxl", side_effect=ValueError("some other error")
        ):
            out, status = svc._decompose_template(str(f))
        assert status == 500
        assert out["success"] is False

    def test_xls_path_calls_pandas(self, tmp_path):
        f = tmp_path / "test.xls"
        f.write_text("fake xls")
        with patch.object(
            svc,
            "_decompose_template_xls_pandas",
            return_value=({"success": True}, 200),
        ) as mock_pandas:
            out, status = svc._decompose_template(str(f))
        assert status == 200
        mock_pandas.assert_called_once()


# ── _decompose_template_xls_pandas ───────────────────────────────────────────


class TestDecomposeTemplateXlsPandas:
    def test_pandas_import_error(self, tmp_path):
        f = tmp_path / "test.xls"
        f.write_text("fake")
        with patch.dict("sys.modules", {"pandas": None}):
            out, status = svc._decompose_template_xls_pandas(str(f))
        assert status == 500
        assert "pandas" in out["message"]

    def test_pandas_open_failure_unreadable(self, tmp_path):
        f = tmp_path / "test.xls"
        f.write_text("fake")
        fake_pd = MagicMock()
        fake_pd.ExcelFile.side_effect = OSError("BadZipFile: bad zip")
        with patch.dict("sys.modules", {"pandas": fake_pd}):
            out, status = svc._decompose_template_xls_pandas(str(f))
        assert status == 200
        assert out.get("error_code") == "UNREADABLE_WORKBOOK"

    def test_pandas_open_failure_xlrd_missing(self, tmp_path):
        f = tmp_path / "test.xls"
        f.write_text("fake")
        fake_pd = MagicMock()
        fake_pd.ExcelFile.side_effect = ImportError("No module named xlrd")
        with patch.dict("sys.modules", {"pandas": fake_pd}):
            out, status = svc._decompose_template_xls_pandas(str(f))
        assert status == 500
        assert "xlrd" in out["message"]

    def test_pandas_open_failure_other(self, tmp_path):
        f = tmp_path / "test.xls"
        f.write_text("fake")
        fake_pd = MagicMock()
        fake_pd.ExcelFile.side_effect = OSError("some other error")
        with patch.dict("sys.modules", {"pandas": fake_pd}):
            out, status = svc._decompose_template_xls_pandas(str(f))
        assert status == 500
        assert "xlrd" in out["message"]

    def test_no_sheets(self, tmp_path):
        f = tmp_path / "test.xls"
        f.write_text("fake")
        fake_pd = MagicMock()
        fake_xl = MagicMock()
        fake_xl.sheet_names = []
        fake_pd.ExcelFile.return_value = fake_xl
        with patch.dict("sys.modules", {"pandas": fake_pd}):
            out, status = svc._decompose_template_xls_pandas(str(f))
        assert status == 200
        assert "没有工作表" in out["message"]


# ── get_template_file ────────────────────────────────────────────────────────


class TestGetTemplateFile:
    def test_template_not_found(self):
        with patch.object(svc, "_get_template_list", return_value=[]):
            resp = svc.get_template_file("missing-id")
        assert resp.status_code == 404

    def test_template_file_missing(self):
        templates = [{"id": "t1", "exists": False, "path": None}]
        with patch.object(svc, "_get_template_list", return_value=templates):
            resp = svc.get_template_file("t1")
        assert resp.status_code == 404

    def test_returns_file_response(self, tmp_path):
        f = tmp_path / "tpl.xlsx"
        f.write_text("content")
        templates = [{"id": "t1", "exists": True, "path": str(f), "filename": "tpl.xlsx"}]
        with patch.object(svc, "_get_template_list", return_value=templates):
            resp = svc.get_template_file("t1")
        assert resp.status_code == 200

    def test_handles_error(self):
        with patch.object(svc, "_get_template_list", side_effect=RuntimeError("db down")):
            resp = svc.get_template_file("t1")
        assert resp.status_code == 500


# ── save_template ────────────────────────────────────────────────────────────


class TestSaveTemplate:
    def test_success(self):
        fake_svc = MagicMock()
        fake_svc.save_template_file.return_value = {"success": True}
        with patch("app.application.get_template_app_service", return_value=fake_svc):
            resp = svc.save_template({"source_name": "a.xlsx", "target_name": "b.xlsx"})
        assert resp.status_code == 200

    def test_failure_returns_404(self):
        fake_svc = MagicMock()
        fake_svc.save_template_file.return_value = {"success": False, "message": "missing"}
        with patch("app.application.get_template_app_service", return_value=fake_svc):
            resp = svc.save_template({})
        assert resp.status_code == 404

    def test_handles_error(self):
        with patch(
            "app.application.get_template_app_service",
            side_effect=RuntimeError("db down"),
        ):
            resp = svc.save_template({})
        assert resp.status_code == 500

    def test_default_overwrite_false(self):
        fake_svc = MagicMock()
        fake_svc.save_template_file.return_value = {"success": True}
        with patch("app.application.get_template_app_service", return_value=fake_svc):
            svc.save_template({})
        call_args = fake_svc.save_template_file.call_args
        assert call_args.args[2] is False  # overwrite


# ── upload_excel (async) ─────────────────────────────────────────────────────


class TestUploadExcel:
    @pytest.mark.asyncio
    async def test_no_file(self):
        resp = await svc.upload_excel(None)
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_no_filename(self):
        mock_file = MagicMock()
        mock_file.filename = ""
        resp = await svc.upload_excel(mock_file)
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_invalid_extension(self):
        mock_file = MagicMock()
        mock_file.filename = "test.txt"
        mock_file.read = AsyncMock(return_value=b"content")
        resp = await svc.upload_excel(mock_file)
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_success_xlsx(self, tmp_path, monkeypatch):
        monkeypatch.setattr(svc, "TEMP_EXCEL_DIR", str(tmp_path))
        mock_file = MagicMock()
        mock_file.filename = "test.xlsx"
        mock_file.read = AsyncMock(return_value=b"content")
        resp = await svc.upload_excel(mock_file)
        assert resp.status_code == 200
        body = json.loads(resp.body)
        assert body["success"] is True
        assert "file_path" in body

    @pytest.mark.asyncio
    async def test_success_xls(self, tmp_path, monkeypatch):
        monkeypatch.setattr(svc, "TEMP_EXCEL_DIR", str(tmp_path))
        mock_file = MagicMock()
        mock_file.filename = "test.xls"
        mock_file.read = AsyncMock(return_value=b"content")
        resp = await svc.upload_excel(mock_file)
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_handles_error(self):
        mock_file = MagicMock()
        mock_file.filename = "test.xlsx"
        mock_file.read = AsyncMock(side_effect=RuntimeError("io fail"))
        resp = await svc.upload_excel(mock_file)
        assert resp.status_code == 500


# ── get_template (DB) ────────────────────────────────────────────────────────


class TestGetTemplateDb:
    def test_not_found(self):
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_db.execute.return_value = mock_result

        from contextlib import contextmanager

        @contextmanager
        def fake_get_db():
            yield mock_db

        with patch("app.db.session.get_db", fake_get_db):
            resp = svc.get_template(999)
        assert resp.status_code == 404

    def test_found(self):
        mock_db = MagicMock()
        mock_row = MagicMock()
        mock_row.id = 1
        mock_row.template_key = "k"
        mock_row.template_name = "name"
        mock_row.template_type = "type"
        mock_row.original_file_path = "/path"
        mock_row.analyzed_data = None
        mock_row.editable_config = None
        mock_row.zone_config = None
        mock_row.merged_cells_config = None
        mock_row.style_config = None
        mock_row.business_rules = None
        mock_row.created_at = "2026-01-01"
        mock_row.updated_at = "2026-01-01"
        mock_result = MagicMock()
        mock_result.fetchone.return_value = mock_row
        mock_db.execute.return_value = mock_result

        from contextlib import contextmanager

        @contextmanager
        def fake_get_db():
            yield mock_db

        with patch("app.db.session.get_db", fake_get_db):
            resp = svc.get_template(1)
        assert resp.status_code == 200
        body = json.loads(resp.body)
        assert body["success"] is True
        assert body["template"]["id"] == 1

    def test_handles_error(self):
        from contextlib import contextmanager

        @contextmanager
        def fake_get_db():
            raise RuntimeError("db down")

        with patch("app.db.session.get_db", fake_get_db):
            resp = svc.get_template(1)
        assert resp.status_code == 500


# ── update_template (DB) ─────────────────────────────────────────────────────


class TestUpdateTemplateDb:
    def test_not_found(self):
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_db.execute.return_value = mock_result

        from contextlib import contextmanager

        @contextmanager
        def fake_get_db():
            yield mock_db

        with patch("app.db.session.get_db", fake_get_db):
            resp = svc.update_template(999, {"template_name": "new"})
        assert resp.status_code == 404

    def test_success(self):
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = MagicMock(id=1)
        mock_db.execute.return_value = mock_result

        from contextlib import contextmanager

        @contextmanager
        def fake_get_db():
            yield mock_db

        with patch("app.db.session.get_db", fake_get_db):
            resp = svc.update_template(
                1,
                {
                    "template_name": "new",
                    "template_type": "type",
                    "editable_config": {"k": "v"},
                    "zone_config": {"z": "v"},
                    "business_rules": {"r": "v"},
                },
            )
        assert resp.status_code == 200
        body = json.loads(resp.body)
        assert body["success"] is True

    def test_handles_error(self):
        from contextlib import contextmanager

        @contextmanager
        def fake_get_db():
            raise RuntimeError("db down")

        with patch("app.db.session.get_db", fake_get_db):
            resp = svc.update_template(1, {})
        assert resp.status_code == 500


# ── delete_template (DB) ─────────────────────────────────────────────────────


class TestDeleteTemplateDb:
    def test_not_found(self):
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_db.execute.return_value = mock_result

        from contextlib import contextmanager

        @contextmanager
        def fake_get_db():
            yield mock_db

        with patch("app.db.session.get_db", fake_get_db):
            resp = svc.delete_template(999)
        assert resp.status_code == 404

    def test_success(self):
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = MagicMock(id=1)
        mock_db.execute.return_value = mock_result

        from contextlib import contextmanager

        @contextmanager
        def fake_get_db():
            yield mock_db

        with patch("app.db.session.get_db", fake_get_db):
            resp = svc.delete_template(1)
        assert resp.status_code == 200
        body = json.loads(resp.body)
        assert body["success"] is True

    def test_handles_error(self):
        from contextlib import contextmanager

        @contextmanager
        def fake_get_db():
            raise RuntimeError("db down")

        with patch("app.db.session.get_db", fake_get_db):
            resp = svc.delete_template(1)
        assert resp.status_code == 500


# ── list_templates_by_type / get_default_template ────────────────────────────


class TestListTemplatesByType:
    def test_success(self):
        fake_svc = MagicMock()
        fake_svc.list_by_type.return_value = [
            {"template_type": "标签", "file_path": "/a.xlsx", "exists": True}
        ]
        with patch("app.application.get_template_app_service", return_value=fake_svc):
            resp = svc.list_templates_by_type(type="标签", active_only="true")
        assert resp.status_code == 200
        body = json.loads(resp.body)
        assert body["success"] is True
        assert body["count"] == 1

    def test_active_only_false(self):
        fake_svc = MagicMock()
        fake_svc.list_by_type.return_value = []
        with patch("app.application.get_template_app_service", return_value=fake_svc):
            svc.list_templates_by_type(type="x", active_only="false")
        call_kwargs = fake_svc.list_by_type.call_args.kwargs
        assert call_kwargs["active_only"] is False

    def test_handles_error(self):
        with patch(
            "app.application.get_template_app_service",
            side_effect=RuntimeError("db down"),
        ):
            # Pass active_only as a string (Query object would fail .lower())
            resp = svc.list_templates_by_type(type="标签", active_only="true")
        assert resp.status_code == 500


class TestGetDefaultTemplate:
    def test_not_found(self):
        fake_svc = MagicMock()
        fake_svc.get_default_for_type.return_value = None
        with patch("app.application.get_template_app_service", return_value=fake_svc):
            resp = svc.get_default_template(type="x")
        assert resp.status_code == 404

    def test_found(self):
        fake_svc = MagicMock()
        fake_svc.get_default_for_type.return_value = {
            "template_type": "x",
            "file_path": "/a.xlsx",
            "exists": True,
        }
        with patch("app.application.get_template_app_service", return_value=fake_svc):
            resp = svc.get_default_template(type="x")
        assert resp.status_code == 200

    def test_handles_error(self):
        with patch(
            "app.application.get_template_app_service",
            side_effect=RuntimeError("db down"),
        ):
            resp = svc.get_default_template()
        assert resp.status_code == 500


# ── list_templates_get / get_templates_list ──────────────────────────────────


class TestListTemplatesGet:
    def test_success(self):
        with patch.object(
            svc,
            "_get_template_list",
            return_value=[{"template_type": "x", "file_path": "/a.xlsx", "exists": True}],
        ):
            resp = svc.list_templates_get()
        assert resp.status_code == 200

    def test_handles_error(self):
        with patch.object(svc, "_get_template_list", side_effect=RuntimeError("db down")):
            resp = svc.list_templates_get()
        assert resp.status_code == 500


class TestGetTemplatesList:
    def test_success(self):
        with patch.object(svc, "_get_template_list", return_value=[]):
            resp = svc.get_templates_list()
        assert resp.status_code == 200

    def test_handles_error(self):
        with patch.object(svc, "_get_template_list", side_effect=RuntimeError("db down")):
            resp = svc.get_templates_list()
        assert resp.status_code == 500


# ── decompose_template (HTTP) ────────────────────────────────────────────────


class TestDecomposeTemplateHttp:
    def test_no_filename_or_path(self):
        resp = svc.decompose_template({})
        assert resp.status_code == 400

    def test_file_not_found(self):
        resp = svc.decompose_template({"filename": "missing.xlsx"})
        assert resp.status_code == 404

    def test_success_with_filename(self, tmp_path, monkeypatch):
        f = tmp_path / "test.xlsx"
        f.write_text("content")
        monkeypatch.setattr(svc, "_REPO_ROOT", tmp_path)
        monkeypatch.setattr(svc, "TEMPLATE_DIR", str(tmp_path / "templates"))
        with patch.object(
            svc,
            "_decompose_template",
            return_value=({"success": True}, 200),
        ):
            resp = svc.decompose_template({"filename": "test.xlsx"})
        assert resp.status_code == 200

    def test_success_with_file_path(self, tmp_path):
        f = tmp_path / "test.xlsx"
        f.write_text("content")
        with patch.object(
            svc,
            "_decompose_template",
            return_value=({"success": True}, 200),
        ):
            resp = svc.decompose_template({"file_path": str(f)})
        assert resp.status_code == 200

    def test_handles_error(self, tmp_path):
        # Create a real file so os.path.exists passes, then _decompose_template raises
        f = tmp_path / "x.xlsx"
        f.write_text("content")
        with patch.object(svc, "_decompose_template", side_effect=RuntimeError("boom")):
            resp = svc.decompose_template({"file_path": str(f)})
        assert resp.status_code == 500


# ── excel_templates_test ─────────────────────────────────────────────────────


class TestExcelTemplatesTest:
    def test_returns_ok(self):
        resp = svc.excel_templates_test()
        assert resp.status_code == 200
        body = json.loads(resp.body)
        assert body["success"] is True
        assert "timestamp" in body


# ── get_base_dir ─────────────────────────────────────────────────────────────


class TestGetBaseDir:
    def test_returns_str(self):
        out = svc.get_base_dir()
        assert isinstance(out, str)
        assert len(out) > 0
