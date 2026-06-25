"""Second-wave coverage for material_repository_impl.

Targets the previously-uncovered branches: the ``delete`` failure path and the
whole ``export_to_excel`` method (search/category filters, default workbook,
template-driven workbook, template lookup error swallowing, and the top-level
RECOVERABLE_ERRORS failure return). All external deps (DB, filesystem dir,
template service, template fill helper) are mocked; openpyxl Workbook writes to
tmp_path so the test stays offline and deterministic.
"""

from __future__ import annotations

import os
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from app.infrastructure.persistence.material_repository_impl import (
    SQLAlchemyMaterialRepository,
)

MODULE = "app.infrastructure.persistence.material_repository_impl"


@pytest.fixture
def repo():
    return SQLAlchemyMaterialRepository()


def _make_material(**overrides):
    m = MagicMock()
    defaults = {
        "id": 7,
        "material_code": "MAT-007",
        "name": "导出原材料",
        "category": "化工",
        "specification": "25kg/桶",
        "unit": "kg",
        "quantity": 12.0,
        "unit_price": 3.5,
        "supplier": "供应商X",
        "warehouse_location": "B-02",
        "min_stock": 10.0,
        "max_stock": 500.0,
        "description": "desc",
        "is_active": 1,
        "created_at": datetime(2026, 1, 1),
        "updated_at": datetime(2026, 6, 1),
    }
    defaults.update(overrides)
    for k, v in defaults.items():
        setattr(m, k, v)
    return m


def _mock_db_ctx(mock_db):
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=mock_db)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx


def _query_returning(materials):
    """Build a mock db whose query(...).filter(...).order_by(...).all() yields materials."""
    mock_db = MagicMock()
    mock_query = MagicMock()
    mock_db.query.return_value = mock_query
    mock_query.filter.return_value = mock_query
    mock_query.order_by.return_value.all.return_value = materials
    return mock_db, mock_query


# --------------------------------------------------------------------------- #
# delete() failure path  (lines 190-191)
# --------------------------------------------------------------------------- #
class TestDeleteErrorBranch:
    def test_db_error_returns_false(self, repo):
        with patch(
            f"{MODULE}.get_db",
            side_effect=RuntimeError("boom"),
        ):
            assert repo.delete(1) is False


# --------------------------------------------------------------------------- #
# export_to_excel — default workbook path (no template)
# Covers query build, search+category filters, records comprehension,
# timestamp/dir/path setup, default Workbook branch, wb.save, success return.
# --------------------------------------------------------------------------- #
class TestExportDefaultWorkbook:
    def test_success_no_template_writes_file(self, repo, tmp_path):
        mat = _make_material()
        mock_db, mock_query = _query_returning([mat])
        export_root = str(tmp_path)

        with (
            patch(f"{MODULE}.get_db", return_value=_mock_db_ctx(mock_db)),
            patch("app.utils.path_utils.get_data_dir", return_value=export_root),
        ):
            result = repo.export_to_excel(search="导出", category="化工")

        assert result["success"] is True
        assert result["count"] == 1
        assert result["filename"].startswith("materials_")
        assert result["filename"].endswith(".xlsx")
        # File actually got written under <data_dir>/exports
        assert os.path.isfile(result["file_path"])
        assert os.path.dirname(result["file_path"]) == os.path.join(export_root, "exports")
        # search + category each apply a filter -> filter called at least 3 times
        # (base is_active, search OR-group, category)
        assert mock_query.filter.call_count >= 3

    def test_success_no_filters_empty_records(self, repo, tmp_path):
        mock_db, mock_query = _query_returning([])
        with (
            patch(f"{MODULE}.get_db", return_value=_mock_db_ctx(mock_db)),
            patch("app.utils.path_utils.get_data_dir", return_value=str(tmp_path)),
        ):
            result = repo.export_to_excel()

        assert result["success"] is True
        assert result["count"] == 0
        assert os.path.isfile(result["file_path"])
        # No search and no category -> only the base is_active filter
        assert mock_query.filter.call_count == 1

    def test_none_field_fallbacks_in_records(self, repo, tmp_path):
        # quantity/unit_price None -> 0 fallback; string fields None -> "" fallback
        mat = _make_material(
            material_code=None,
            name=None,
            quantity=None,
            unit_price=None,
            supplier=None,
        )
        mock_db, _ = _query_returning([mat])
        with (
            patch(f"{MODULE}.get_db", return_value=_mock_db_ctx(mock_db)),
            patch("app.utils.path_utils.get_data_dir", return_value=str(tmp_path)),
        ):
            result = repo.export_to_excel()

        assert result["success"] is True
        assert result["count"] == 1
        assert os.path.isfile(result["file_path"])


# --------------------------------------------------------------------------- #
# export_to_excel — template path
# Covers template lookup success -> fill_workbook_from_template branch (296-312).
# --------------------------------------------------------------------------- #
class TestExportWithTemplate:
    def test_template_match_uses_fill_helper(self, repo, tmp_path):
        mat = _make_material()
        mock_db, _ = _query_returning([mat])

        # A real, existing template file on disk so os.path.exists passes.
        tpl = tmp_path / "tpl.xlsx"
        tpl.write_text("placeholder")

        tpl_svc = MagicMock()
        tpl_svc.get_templates.return_value = {"templates": [{"id": "42", "path": str(tpl)}]}

        # fill helper returns a real workbook so wb.save() works.
        from openpyxl import Workbook

        produced = Workbook()

        with (
            patch(f"{MODULE}.get_db", return_value=_mock_db_ctx(mock_db)),
            patch("app.utils.path_utils.get_data_dir", return_value=str(tmp_path)),
            patch("app.application.get_template_app_service", return_value=tpl_svc),
            patch(
                "app.utils.template_export_utils.fill_workbook_from_template",
                return_value=produced,
            ) as mock_fill,
        ):
            result = repo.export_to_excel(template_id="42")

        assert result["success"] is True
        assert result["count"] == 1
        assert os.path.isfile(result["file_path"])
        mock_fill.assert_called_once()
        # The matched template path was forwarded to the fill helper.
        assert mock_fill.call_args.kwargs["template_path"] == str(tpl)
        assert mock_fill.call_args.kwargs["sheet_name"] == "原材料列表"

    def test_template_id_no_match_falls_back_to_default(self, repo, tmp_path):
        mat = _make_material()
        mock_db, _ = _query_returning([mat])

        tpl_svc = MagicMock()
        # Templates exist but none matches id "999" -> target is None -> default branch.
        tpl_svc.get_templates.return_value = {
            "templates": [{"id": "1", "path": str(tmp_path / "other.xlsx")}]
        }

        with (
            patch(f"{MODULE}.get_db", return_value=_mock_db_ctx(mock_db)),
            patch("app.utils.path_utils.get_data_dir", return_value=str(tmp_path)),
            patch("app.application.get_template_app_service", return_value=tpl_svc),
        ):
            result = repo.export_to_excel(template_id="999")

        assert result["success"] is True
        assert os.path.isfile(result["file_path"])

    def test_template_path_missing_on_disk_falls_back(self, repo, tmp_path):
        # Matching template, but its path does not exist -> template_path stays None.
        mat = _make_material()
        mock_db, _ = _query_returning([mat])

        tpl_svc = MagicMock()
        tpl_svc.get_templates.return_value = {
            "templates": [{"id": "5", "path": str(tmp_path / "missing.xlsx")}]
        }

        with (
            patch(f"{MODULE}.get_db", return_value=_mock_db_ctx(mock_db)),
            patch("app.utils.path_utils.get_data_dir", return_value=str(tmp_path)),
            patch("app.application.get_template_app_service", return_value=tpl_svc),
        ):
            result = repo.export_to_excel(template_id="5")

        assert result["success"] is True
        assert os.path.isfile(result["file_path"])

    def test_template_lookup_raises_is_swallowed(self, repo, tmp_path):
        # get_template_app_service raises a RECOVERABLE_ERRORS -> template_path None,
        # export still succeeds via default workbook (covers except branch 293-294).
        mat = _make_material()
        mock_db, _ = _query_returning([mat])

        with (
            patch(f"{MODULE}.get_db", return_value=_mock_db_ctx(mock_db)),
            patch("app.utils.path_utils.get_data_dir", return_value=str(tmp_path)),
            patch(
                "app.application.get_template_app_service",
                side_effect=RuntimeError("template service down"),
            ),
        ):
            result = repo.export_to_excel(template_id="anything")

        assert result["success"] is True
        assert os.path.isfile(result["file_path"])


# --------------------------------------------------------------------------- #
# export_to_excel — top-level failure return (lines 341-342)
# --------------------------------------------------------------------------- #
class TestExportFailure:
    def test_db_error_returns_failure_payload(self, repo, tmp_path):
        with (
            patch(f"{MODULE}.get_db", side_effect=RuntimeError("db gone")),
            patch("app.utils.path_utils.get_data_dir", return_value=str(tmp_path)),
        ):
            result = repo.export_to_excel()

        assert result["success"] is False
        assert "db gone" in result["message"]
        assert result["file_path"] is None
        assert result["filename"] is None
        assert result["count"] == 0

    def test_save_error_returns_failure_payload(self, repo, tmp_path):
        # Workbook.save raises OSError -> caught by RECOVERABLE_ERRORS branch.
        mat = _make_material()
        mock_db, _ = _query_returning([mat])

        with (
            patch(f"{MODULE}.get_db", return_value=_mock_db_ctx(mock_db)),
            patch("app.utils.path_utils.get_data_dir", return_value=str(tmp_path)),
            patch(
                "openpyxl.workbook.workbook.Workbook.save",
                side_effect=OSError("disk full"),
            ),
        ):
            result = repo.export_to_excel()

        assert result["success"] is False
        assert "disk full" in result["message"]
        assert result["count"] == 0
