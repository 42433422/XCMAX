"""Tests for app.infrastructure.skills.excel_toolkit.excel_toolkit — ext2.

Focus: view_excel_content, get_merged_cells, get_cell_styles, analyze_structure,
ExcelToolkitSkill.execute with all actions, get_skill_info, get_excel_toolkit_skill,
error paths (ImportError, FileNotFoundError, RECOVERABLE_ERRORS).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.infrastructure.skills.excel_toolkit.excel_toolkit import (
    ExcelToolkitSkill,
    analyze_structure,
    get_cell_styles,
    get_excel_toolkit_skill,
    get_merged_cells,
    view_excel_content,
)

# ---------------------------------------------------------------------------
# Helper to create a mock worksheet
# ---------------------------------------------------------------------------


def _make_ws(
    max_row=10,
    max_col=5,
    cells=None,
    merged_ranges=None,
    title="Sheet1",
    dimensions="A1:E10",
):
    """Create a mock openpyxl worksheet."""
    ws = MagicMock()
    ws.max_row = max_row
    ws.max_column = max_col
    ws.title = title
    ws.dimensions = dimensions

    cells = cells or {}

    def cell(row, col):
        c = MagicMock()
        c.row = row
        c.column = col
        c.coordinate = f"{chr(64 + col)}{row}"
        val = cells.get((row, col))
        c.value = val
        c.data_type = "n" if val is None else "s"
        # Font
        c.font = MagicMock()
        c.font.name = "Arial"
        c.font.size = 11
        c.font.bold = False
        c.font.color = None
        # Alignment
        c.alignment = MagicMock()
        c.alignment.horizontal = "left"
        c.alignment.vertical = "center"
        # Fill
        c.fill = MagicMock()
        c.fill.patternType = None
        c.fill.fgColor = None
        return c

    ws.cell = cell

    def iter_rows(min_row=1, max_row=None, **kwargs):
        max_row = max_row or ws.max_row
        for r in range(min_row, max_row + 1):
            yield [cell(r, c) for c in range(1, ws.max_column + 1)]

    ws.iter_rows = iter_rows

    merged_ranges = merged_ranges or []
    range_objs = []
    for mr in merged_ranges:
        r = MagicMock()
        r.min_row = mr[0]
        r.max_row = mr[1]
        r.min_col = mr[2]
        r.max_col = mr[3]
        r.coord = f"{chr(64 + mr[2])}{mr[0]}:{chr(64 + mr[3])}{mr[1]}"
        r.__str__ = lambda self: self.coord
        range_objs.append(r)
    ws.merged_cells = MagicMock()
    ws.merged_cells.ranges = range_objs

    return ws


# ---------------------------------------------------------------------------
# view_excel_content
# ---------------------------------------------------------------------------


class TestViewExcelContent:
    def test_basic_view(self, tmp_path):
        excel_path = tmp_path / "test.xlsx"
        excel_path.write_bytes(b"fake")

        cells = {(1, 1): "Name", (1, 2): "Age", (2, 1): "Alice", (2, 2): 30}
        ws = _make_ws(max_row=10, max_col=5, cells=cells, title="Sheet1")
        wb = MagicMock()
        wb.sheetnames = ["Sheet1"]
        wb.active = ws
        wb.__getitem__ = MagicMock(return_value=ws)

        with patch(
            "openpyxl.load_workbook",
            return_value=wb,
        ):
            result = view_excel_content(str(excel_path))
            assert result["success"] is True
            assert result["file"] == "test.xlsx"
            assert result["sheet"] == "Sheet1"
            assert "structure" in result
            assert "content" in result
            assert result["row_count"] >= 1

    def test_with_specific_sheet(self, tmp_path):
        excel_path = tmp_path / "test.xlsx"
        excel_path.write_bytes(b"fake")

        ws = _make_ws(title="Data")
        wb = MagicMock()
        wb.sheetnames = ["Sheet1", "Data"]
        wb.__getitem__ = MagicMock(return_value=ws)

        with patch(
            "openpyxl.load_workbook",
            return_value=wb,
        ):
            result = view_excel_content(str(excel_path), sheet_name="Data")
            assert result["success"] is True
            assert result["sheet"] == "Data"

    def test_with_nonexistent_sheet(self, tmp_path):
        excel_path = tmp_path / "test.xlsx"
        excel_path.write_bytes(b"fake")

        wb = MagicMock()
        wb.sheetnames = ["Sheet1"]

        with patch(
            "openpyxl.load_workbook",
            return_value=wb,
        ):
            result = view_excel_content(str(excel_path), sheet_name="Nonexistent")
            assert result["success"] is False
            assert "不存在" in result["message"]

    def test_file_not_found(self, tmp_path):
        result = view_excel_content(str(tmp_path / "nonexistent.xlsx"))
        assert result["success"] is False
        assert "文件不存在" in result["message"]

    def test_import_error(self, tmp_path):
        excel_path = tmp_path / "test.xlsx"
        excel_path.write_bytes(b"fake")

        original_import = (
            __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__
        )

        def fake_import(name, *args, **kwargs):
            if name == "openpyxl":
                raise ImportError("openpyxl not installed")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fake_import):
            result = view_excel_content(str(excel_path))
            assert result["success"] is False
            assert "openpyxl" in result["message"]

    def test_recoverable_error(self, tmp_path):
        excel_path = tmp_path / "test.xlsx"
        excel_path.write_bytes(b"fake")

        with patch(
            "openpyxl.load_workbook",
            side_effect=RuntimeError("corrupt"),
        ):
            result = view_excel_content(str(excel_path))
            assert result["success"] is False
            assert "读取失败" in result["message"]

    def test_max_rows_limit(self, tmp_path):
        excel_path = tmp_path / "test.xlsx"
        excel_path.write_bytes(b"fake")

        ws = _make_ws(max_row=100, max_col=3, cells={(1, 1): "x"})
        wb = MagicMock()
        wb.sheetnames = ["Sheet1"]
        wb.active = ws
        wb.__getitem__ = MagicMock(return_value=ws)

        with patch(
            "openpyxl.load_workbook",
            return_value=wb,
        ):
            result = view_excel_content(str(excel_path), max_rows=5)
            assert result["success"] is True


# ---------------------------------------------------------------------------
# get_merged_cells
# ---------------------------------------------------------------------------


class TestGetMergedCells:
    def test_with_merged_cells(self, tmp_path):
        excel_path = tmp_path / "test.xlsx"
        excel_path.write_bytes(b"fake")

        cells = {(1, 1): "Title"}
        ws = _make_ws(max_row=10, max_col=5, cells=cells, merged_ranges=[(1, 1, 1, 5)])
        wb = MagicMock()
        wb.sheetnames = ["Sheet1"]
        wb.active = ws
        wb.__getitem__ = MagicMock(return_value=ws)

        with patch(
            "openpyxl.load_workbook",
            return_value=wb,
        ):
            result = get_merged_cells(str(excel_path))
            assert result["success"] is True
            assert result["count"] == 1
            assert len(result["merged_cells"]) == 1
            mc = result["merged_cells"][0]
            assert mc["value"] == "Title"
            assert "range" in mc
            assert "master" in mc

    def test_without_merged_cells(self, tmp_path):
        excel_path = tmp_path / "test.xlsx"
        excel_path.write_bytes(b"fake")

        ws = _make_ws(max_row=10, max_col=5, merged_ranges=[])
        wb = MagicMock()
        wb.sheetnames = ["Sheet1"]
        wb.active = ws
        wb.__getitem__ = MagicMock(return_value=ws)

        with patch(
            "openpyxl.load_workbook",
            return_value=wb,
        ):
            result = get_merged_cells(str(excel_path))
            assert result["success"] is True
            assert result["count"] == 0

    def test_with_specific_sheet(self, tmp_path):
        excel_path = tmp_path / "test.xlsx"
        excel_path.write_bytes(b"fake")

        ws = _make_ws(title="Data")
        wb = MagicMock()
        wb.sheetnames = ["Sheet1", "Data"]
        wb.__getitem__ = MagicMock(return_value=ws)

        with patch(
            "openpyxl.load_workbook",
            return_value=wb,
        ):
            result = get_merged_cells(str(excel_path), sheet_name="Data")
            assert result["success"] is True
            assert result["sheet"] == "Data"

    def test_with_nonexistent_sheet_falls_back_to_active(self, tmp_path):
        excel_path = tmp_path / "test.xlsx"
        excel_path.write_bytes(b"fake")

        ws = _make_ws(title="Sheet1")
        wb = MagicMock()
        wb.sheetnames = ["Sheet1"]
        wb.active = ws

        with patch(
            "openpyxl.load_workbook",
            return_value=wb,
        ):
            result = get_merged_cells(str(excel_path), sheet_name="Nonexistent")
            assert result["success"] is True
            # Falls back to active sheet
            assert result["sheet"] == "Sheet1"

    def test_import_error(self, tmp_path):
        excel_path = tmp_path / "test.xlsx"
        excel_path.write_bytes(b"fake")

        original_import = (
            __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__
        )

        def fake_import(name, *args, **kwargs):
            if name == "openpyxl":
                raise ImportError("not installed")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fake_import):
            result = get_merged_cells(str(excel_path))
            assert result["success"] is False
            assert "openpyxl" in result["message"]

    def test_recoverable_error(self, tmp_path):
        excel_path = tmp_path / "test.xlsx"
        excel_path.write_bytes(b"fake")

        with patch(
            "openpyxl.load_workbook",
            side_effect=RuntimeError("fail"),
        ):
            result = get_merged_cells(str(excel_path))
            assert result["success"] is False


# ---------------------------------------------------------------------------
# get_cell_styles
# ---------------------------------------------------------------------------


class TestGetCellStyles:
    def test_basic_styles(self, tmp_path):
        excel_path = tmp_path / "test.xlsx"
        excel_path.write_bytes(b"fake")

        cells = {(1, 1): "Header"}
        ws = _make_ws(max_row=5, max_col=3, cells=cells)
        wb = MagicMock()
        wb.sheetnames = ["Sheet1"]
        wb.active = ws
        wb.__getitem__ = MagicMock(return_value=ws)

        with patch(
            "openpyxl.load_workbook",
            return_value=wb,
        ):
            result = get_cell_styles(str(excel_path))
            assert result["success"] is True
            assert "styles" in result
            assert len(result["styles"]) >= 1
            style = result["styles"][0]
            assert "font" in style
            assert "alignment" in style
            assert "fill" in style

    def test_with_specific_sheet(self, tmp_path):
        excel_path = tmp_path / "test.xlsx"
        excel_path.write_bytes(b"fake")

        ws = _make_ws(title="Data")
        wb = MagicMock()
        wb.sheetnames = ["Sheet1", "Data"]
        wb.__getitem__ = MagicMock(return_value=ws)

        with patch(
            "openpyxl.load_workbook",
            return_value=wb,
        ):
            result = get_cell_styles(str(excel_path), sheet_name="Data")
            assert result["success"] is True
            assert result["sheet"] == "Data"

    def test_with_nonexistent_sheet_falls_back(self, tmp_path):
        excel_path = tmp_path / "test.xlsx"
        excel_path.write_bytes(b"fake")

        ws = _make_ws(title="Sheet1")
        wb = MagicMock()
        wb.sheetnames = ["Sheet1"]
        wb.active = ws

        with patch(
            "openpyxl.load_workbook",
            return_value=wb,
        ):
            result = get_cell_styles(str(excel_path), sheet_name="Nonexistent")
            assert result["success"] is True

    def test_recoverable_error(self, tmp_path):
        excel_path = tmp_path / "test.xlsx"
        excel_path.write_bytes(b"fake")

        with patch(
            "openpyxl.load_workbook",
            side_effect=RuntimeError("fail"),
        ):
            result = get_cell_styles(str(excel_path))
            assert result["success"] is False

    def test_max_rows_limit(self, tmp_path):
        excel_path = tmp_path / "test.xlsx"
        excel_path.write_bytes(b"fake")

        ws = _make_ws(max_row=20, max_col=3, cells={(1, 1): "x"})
        wb = MagicMock()
        wb.sheetnames = ["Sheet1"]
        wb.active = ws
        wb.__getitem__ = MagicMock(return_value=ws)

        with patch(
            "openpyxl.load_workbook",
            return_value=wb,
        ):
            result = get_cell_styles(str(excel_path), max_rows=5)
            assert result["success"] is True


# ---------------------------------------------------------------------------
# analyze_structure
# ---------------------------------------------------------------------------


class TestAnalyzeStructure:
    def test_basic_structure(self, tmp_path):
        excel_path = tmp_path / "test.xlsx"
        excel_path.write_bytes(b"fake")

        cells = {(1, 1): "Name", (1, 2): "Age"}
        ws = _make_ws(max_row=10, max_col=3, cells=cells, title="Sheet1")
        wb = MagicMock()
        wb.sheetnames = ["Sheet1", "Sheet2"]
        wb.active = ws
        wb.__getitem__ = MagicMock(return_value=ws)

        with (
            patch(
                "openpyxl.load_workbook",
                return_value=wb,
            ),
            patch(
                "openpyxl.utils.get_column_letter",
                side_effect=lambda n: chr(64 + n),
            ),
        ):
            result = analyze_structure(str(excel_path))
            assert result["success"] is True
            assert "sheet_names" in result
            assert "current_sheet" in result
            assert "structure" in result
            assert "columns" in result
            assert len(result["columns"]) == 3

    def test_with_specific_sheet(self, tmp_path):
        excel_path = tmp_path / "test.xlsx"
        excel_path.write_bytes(b"fake")

        ws = _make_ws(title="Data")
        wb = MagicMock()
        wb.sheetnames = ["Sheet1", "Data"]
        wb.__getitem__ = MagicMock(return_value=ws)

        with (
            patch(
                "openpyxl.load_workbook",
                return_value=wb,
            ),
            patch(
                "openpyxl.utils.get_column_letter",
                side_effect=lambda n: chr(64 + n),
            ),
        ):
            result = analyze_structure(str(excel_path), sheet_name="Data")
            assert result["success"] is True
            assert result["current_sheet"] == "Data"

    def test_with_nonexistent_sheet_falls_back(self, tmp_path):
        excel_path = tmp_path / "test.xlsx"
        excel_path.write_bytes(b"fake")

        ws = _make_ws(title="Sheet1")
        wb = MagicMock()
        wb.sheetnames = ["Sheet1"]
        wb.active = ws
        wb.__getitem__ = MagicMock(return_value=ws)

        with (
            patch(
                "openpyxl.load_workbook",
                return_value=wb,
            ),
            patch(
                "openpyxl.utils.get_column_letter",
                side_effect=lambda n: chr(64 + n),
            ),
        ):
            result = analyze_structure(str(excel_path), sheet_name="Nonexistent")
            assert result["success"] is True

    def test_recoverable_error(self, tmp_path):
        excel_path = tmp_path / "test.xlsx"
        excel_path.write_bytes(b"fake")

        with patch(
            "openpyxl.load_workbook",
            side_effect=RuntimeError("fail"),
        ):
            result = analyze_structure(str(excel_path))
            assert result["success"] is False


# ---------------------------------------------------------------------------
# ExcelToolkitSkill
# ---------------------------------------------------------------------------


class TestExcelToolkitSkill:
    def test_init(self):
        skill = ExcelToolkitSkill()
        assert skill.name == "excel_toolkit"
        assert "Excel" in skill.description

    def test_execute_view_action(self, tmp_path):
        excel_path = tmp_path / "test.xlsx"
        excel_path.write_bytes(b"fake")

        skill = ExcelToolkitSkill()
        with patch(
            "app.infrastructure.skills.excel_toolkit.excel_toolkit.view_excel_content",
            return_value={"success": True},
        ) as mock_view:
            result = skill.execute(str(excel_path), action="view")
            assert result["success"] is True
            mock_view.assert_called_once()

    def test_execute_merged_action(self, tmp_path):
        excel_path = tmp_path / "test.xlsx"
        excel_path.write_bytes(b"fake")

        skill = ExcelToolkitSkill()
        with patch(
            "app.infrastructure.skills.excel_toolkit.excel_toolkit.get_merged_cells",
            return_value={"success": True},
        ) as mock_merged:
            result = skill.execute(str(excel_path), action="merged")
            assert result["success"] is True
            mock_merged.assert_called_once()

    def test_execute_styles_action(self, tmp_path):
        excel_path = tmp_path / "test.xlsx"
        excel_path.write_bytes(b"fake")

        skill = ExcelToolkitSkill()
        with patch(
            "app.infrastructure.skills.excel_toolkit.excel_toolkit.get_cell_styles",
            return_value={"success": True},
        ) as mock_styles:
            result = skill.execute(str(excel_path), action="styles")
            assert result["success"] is True
            mock_styles.assert_called_once()

    def test_execute_structure_action(self, tmp_path):
        excel_path = tmp_path / "test.xlsx"
        excel_path.write_bytes(b"fake")

        skill = ExcelToolkitSkill()
        with patch(
            "app.infrastructure.skills.excel_toolkit.excel_toolkit.analyze_structure",
            return_value={"success": True},
        ) as mock_struct:
            result = skill.execute(str(excel_path), action="structure")
            assert result["success"] is True
            mock_struct.assert_called_once()

    def test_execute_unknown_action(self, tmp_path):
        excel_path = tmp_path / "test.xlsx"
        excel_path.write_bytes(b"fake")

        skill = ExcelToolkitSkill()
        result = skill.execute(str(excel_path), action="unknown")
        assert result["success"] is False
        assert "未知操作" in result["message"]

    def test_execute_with_kwargs(self, tmp_path):
        excel_path = tmp_path / "test.xlsx"
        excel_path.write_bytes(b"fake")

        skill = ExcelToolkitSkill()
        with patch(
            "app.infrastructure.skills.excel_toolkit.excel_toolkit.view_excel_content",
            return_value={"success": True},
        ) as mock_view:
            result = skill.execute(str(excel_path), action="view", max_rows=50)
            assert result["success"] is True
            # view_excel_content is called positionally: (file_path, sheet_name, max_rows)
            args, kwargs = mock_view.call_args
            assert args[0] == str(excel_path)
            assert args[2] == 50

    def test_get_skill_info(self):
        skill = ExcelToolkitSkill()
        info = skill.get_skill_info()
        assert info["name"] == "excel_toolkit"
        assert "description" in info
        assert "actions" in info
        assert "view" in info["actions"]
        assert "merged" in info["actions"]
        assert "styles" in info["actions"]
        assert "structure" in info["actions"]
        assert "parameters" in info
        assert info["parameters"]["file_path"]["required"] is True
        assert info["parameters"]["action"]["required"] is True


# ---------------------------------------------------------------------------
# get_excel_toolkit_skill — singleton
# ---------------------------------------------------------------------------


class TestGetExcelToolkitSkill:
    def test_returns_instance(self):
        import app.infrastructure.skills.excel_toolkit.excel_toolkit as mod

        mod._skill_instance = None
        skill = get_excel_toolkit_skill()
        assert isinstance(skill, ExcelToolkitSkill)

    def test_returns_same_instance(self):
        import app.infrastructure.skills.excel_toolkit.excel_toolkit as mod

        mod._skill_instance = None
        skill1 = get_excel_toolkit_skill()
        skill2 = get_excel_toolkit_skill()
        assert skill1 is skill2
