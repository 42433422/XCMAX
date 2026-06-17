"""Tests for app.infrastructure.skills.excel_analyzer.excel_template_analyzer — ext2.

Focus: analyze_template with various Excel structures, sheet selection,
verbose mode, merged cells, zones identification, editable ranges,
classify_cell, ExcelAnalyzerSkill.execute, get_skill_info, get_excel_analyzer_skill,
analyze_to_json, error paths (ImportError, FileNotFoundError, RECOVERABLE_ERRORS).
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.infrastructure.skills.excel_analyzer.excel_template_analyzer import (
    ExcelAnalyzerSkill,
    _classify_cell,
    _identify_editable_ranges,
    _identify_zones,
    analyze_template,
    analyze_to_json,
    get_excel_analyzer_skill,
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
):
    """Create a mock openpyxl worksheet."""
    ws = MagicMock()
    ws.max_row = max_row
    ws.max_column = max_col
    ws.title = title
    ws.dimensions = f"A1:{chr(64 + max_col)}{max_row}"

    # Cell value lookup
    cells = cells or {}

    def cell(row, col):
        c = MagicMock()
        c.row = row
        c.column = col
        c.coordinate = f"{chr(64 + col)}{row}"
        c.value = cells.get((row, col))
        c.data_type = "n" if cells.get((row, col)) is None else "s"
        return c

    ws.cell = cell

    # iter_rows
    def iter_rows(min_row=1, max_row=None, **kwargs):
        max_row = max_row or ws.max_row
        for r in range(min_row, max_row + 1):
            row_cells = []
            for c in range(1, ws.max_column + 1):
                row_cells.append(cell(r, c))
            yield row_cells

    ws.iter_rows = iter_rows

    # merged_cells.ranges
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
# analyze_template — happy path
# ---------------------------------------------------------------------------


class TestAnalyzeTemplateHappyPath:
    def test_basic_analysis(self, tmp_path):
        """Basic template analysis with mocked openpyxl."""
        excel_path = tmp_path / "test.xlsx"
        excel_path.write_bytes(b"fake excel")

        ws = _make_ws(max_row=10, max_col=5, title="Sheet1")
        wb = MagicMock()
        wb.sheetnames = ["Sheet1"]
        wb.active = ws
        wb.__getitem__ = MagicMock(return_value=ws)

        with (
            patch(
                "openpyxl.load_workbook",
                return_value=wb,
            ) as mock_load,
            patch(
                "openpyxl.utils.get_column_letter",
                return_value="E",
            ),
        ):
            result = analyze_template(str(excel_path))

            assert result["success"] is True
            assert result["file"] == "test.xlsx"
            assert result["sheet"] == "Sheet1"
            assert "structure" in result
            assert result["structure"]["max_row"] == 10
            assert result["structure"]["max_col"] == 5
            assert result["structure"]["max_col_letter"] == "E"
            assert "zones" in result
            assert "merged_cells" in result
            assert "editable_ranges" in result
            assert "cells" in result
            mock_load.assert_called_once()

    def test_with_specific_sheet_name(self, tmp_path):
        excel_path = tmp_path / "test.xlsx"
        excel_path.write_bytes(b"fake")

        ws1 = _make_ws(title="Sheet1")
        ws2 = _make_ws(title="Sheet2")
        wb = MagicMock()
        wb.sheetnames = ["Sheet1", "Sheet2"]
        wb.__getitem__ = MagicMock(return_value=ws2)

        with (
            patch(
                "openpyxl.load_workbook",
                return_value=wb,
            ),
            patch(
                "openpyxl.utils.get_column_letter",
                return_value="E",
            ),
        ):
            result = analyze_template(str(excel_path), sheet_name="Sheet2")
            assert result["success"] is True
            assert result["sheet"] == "Sheet2"

    def test_with_nonexistent_sheet_name(self, tmp_path):
        excel_path = tmp_path / "test.xlsx"
        excel_path.write_bytes(b"fake")

        wb = MagicMock()
        wb.sheetnames = ["Sheet1", "Sheet2"]

        with patch(
            "openpyxl.load_workbook",
            return_value=wb,
        ):
            result = analyze_template(str(excel_path), sheet_name="Nonexistent")
            assert result["success"] is False
            assert "不存在" in result["message"]

    def test_verbose_mode(self, tmp_path):
        excel_path = tmp_path / "test.xlsx"
        excel_path.write_bytes(b"fake")

        cells = {(1, 1): "标题", (2, 1): "数据1", (3, 1): "数据2"}
        ws = _make_ws(max_row=10, max_col=3, cells=cells, title="Sheet1")
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
                return_value="C",
            ),
        ):
            result = analyze_template(str(excel_path), verbose=True)
            assert result["success"] is True
            assert "cells" in result
            # In verbose mode, cells dict should be populated
            assert isinstance(result["cells"], dict)


# ---------------------------------------------------------------------------
# analyze_template — merged cells with purposes
# ---------------------------------------------------------------------------


class TestAnalyzeTemplateMergedCells:
    def test_merged_cell_with_title_purpose(self, tmp_path):
        excel_path = tmp_path / "test.xlsx"
        excel_path.write_bytes(b"fake")

        cells = {(1, 1): "标题区域"}
        ws = _make_ws(
            max_row=10,
            max_col=5,
            cells=cells,
            merged_ranges=[(1, 1, 1, 5)],
            title="Sheet1",
        )
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
                return_value="E",
            ),
        ):
            result = analyze_template(str(excel_path))
            assert result["success"] is True
            assert len(result["merged_cells"]) == 1
            mc = result["merged_cells"][0]
            assert mc["purpose"] == "标题/表头"
            assert mc["value"] == "标题区域"

    def test_merged_cell_with_summary_purpose(self, tmp_path):
        excel_path = tmp_path / "test.xlsx"
        excel_path.write_bytes(b"fake")

        cells = {(8, 1): "合计金额"}
        ws = _make_ws(
            max_row=10,
            max_col=5,
            cells=cells,
            merged_ranges=[(8, 8, 1, 5)],
            title="Sheet1",
        )
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
                return_value="E",
            ),
        ):
            result = analyze_template(str(excel_path))
            assert result["merged_cells"][0]["purpose"] == "汇总区域"

    def test_merged_cell_with_signature_purpose(self, tmp_path):
        excel_path = tmp_path / "test.xlsx"
        excel_path.write_bytes(b"fake")

        cells = {(9, 1): "签名处"}
        ws = _make_ws(
            max_row=10,
            max_col=5,
            cells=cells,
            merged_ranges=[(9, 9, 1, 5)],
            title="Sheet1",
        )
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
                return_value="E",
            ),
        ):
            result = analyze_template(str(excel_path))
            assert result["merged_cells"][0]["purpose"] == "签名区域"

    def test_merged_cell_with_data_purpose(self, tmp_path):
        excel_path = tmp_path / "test.xlsx"
        excel_path.write_bytes(b"fake")

        cells = {(5, 1): "普通数据"}
        ws = _make_ws(
            max_row=10,
            max_col=5,
            cells=cells,
            merged_ranges=[(5, 5, 1, 5)],
            title="Sheet1",
        )
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
                return_value="E",
            ),
        ):
            result = analyze_template(str(excel_path))
            assert result["merged_cells"][0]["purpose"] == "数据区域"

    def test_merged_cell_without_value(self, tmp_path):
        excel_path = tmp_path / "test.xlsx"
        excel_path.write_bytes(b"fake")

        ws = _make_ws(
            max_row=10,
            max_col=5,
            cells={},
            merged_ranges=[(5, 5, 1, 5)],
            title="Sheet1",
        )
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
                return_value="E",
            ),
        ):
            result = analyze_template(str(excel_path))
            assert len(result["merged_cells"]) == 1
            assert "purpose" not in result["merged_cells"][0]


# ---------------------------------------------------------------------------
# analyze_template — error paths
# ---------------------------------------------------------------------------


class TestAnalyzeTemplateErrors:
    def test_file_not_found(self, tmp_path):
        result = analyze_template(str(tmp_path / "nonexistent.xlsx"))
        assert result["success"] is False
        assert "文件不存在" in result["message"]

    def test_import_error(self, tmp_path):
        excel_path = tmp_path / "test.xlsx"
        excel_path.write_bytes(b"fake")

        # Simulate ImportError by patching the import inside the function
        original_import = (
            __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__
        )

        def fake_import(name, *args, **kwargs):
            if name == "openpyxl":
                raise ImportError("openpyxl not installed")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fake_import):
            result = analyze_template(str(excel_path))
            assert result["success"] is False
            assert "openpyxl" in result["message"]

    def test_recoverable_error(self, tmp_path):
        excel_path = tmp_path / "test.xlsx"
        excel_path.write_bytes(b"fake")

        with patch(
            "openpyxl.load_workbook",
            side_effect=RuntimeError("corrupt file"),
        ):
            result = analyze_template(str(excel_path))
            assert result["success"] is False
            assert "分析失败" in result["message"]


# ---------------------------------------------------------------------------
# _identify_zones
# ---------------------------------------------------------------------------


class TestIdentifyZones:
    def test_zones_with_header(self):
        cells = {(1, 1): "标题", (2, 1): "数据"}
        ws = _make_ws(max_row=10, max_col=3, cells=cells)
        zones = _identify_zones(ws, [])
        assert len(zones) >= 1
        header_zone = next((z for z in zones if z["name"] == "header"), None)
        assert header_zone is not None

    def test_zones_without_header(self):
        ws = _make_ws(max_row=10, max_col=3, cells={})
        zones = _identify_zones(ws, [])
        # No header rows since no cell values
        header_zone = next((z for z in zones if z["name"] == "header"), None)
        assert header_zone is None

    def test_zones_with_data(self):
        cells = {(1, 1): "标题"}
        ws = _make_ws(max_row=20, max_col=3, cells=cells)
        zones = _identify_zones(ws, [])
        data_zone = next((z for z in zones if z["name"] == "data"), None)
        assert data_zone is not None

    def test_zones_with_summary(self):
        ws = _make_ws(max_row=10, max_col=3, cells={})
        zones = _identify_zones(ws, [])
        summary_zone = next((z for z in zones if z["name"] == "summary"), None)
        assert summary_zone is not None

    def test_zones_small_worksheet(self):
        """Worksheet with very few rows."""
        ws = _make_ws(max_row=3, max_col=3, cells={})
        zones = _identify_zones(ws, [])
        # Should still return some zones (or empty)
        assert isinstance(zones, list)


# ---------------------------------------------------------------------------
# _identify_editable_ranges
# ---------------------------------------------------------------------------


class TestIdentifyEditableRanges:
    def test_with_data_zone(self):
        ws = _make_ws(max_row=20, max_col=5)
        zones = [{"name": "data", "rows": [5, 15], "type": "editable"}]
        ranges = _identify_editable_ranges(ws, zones)
        assert len(ranges) == 1
        assert ranges[0]["min_row"] == 5
        assert ranges[0]["max_row"] == 15

    def test_without_data_zone(self):
        ws = _make_ws(max_row=20, max_col=5)
        zones = [{"name": "header", "rows": [1, 2], "type": "template"}]
        ranges = _identify_editable_ranges(ws, zones)
        assert ranges == []

    def test_empty_zones(self):
        ws = _make_ws(max_row=20, max_col=5)
        ranges = _identify_editable_ranges(ws, [])
        assert ranges == []


# ---------------------------------------------------------------------------
# _classify_cell
# ---------------------------------------------------------------------------


class TestClassifyCell:
    def test_formula_cell(self):
        ws = _make_ws()
        cell = MagicMock()
        cell.data_type = "f"
        cell.row = 5
        result = _classify_cell(ws, cell, [])
        assert result == "formula"

    def test_editable_cell_in_range(self):
        ws = _make_ws()
        cell = MagicMock()
        cell.data_type = "s"
        cell.row = 10
        zones = [{"name": "data", "rows": [5, 15], "type": "editable"}]
        result = _classify_cell(ws, cell, zones)
        assert result == "editable"

    def test_editable_cell_outside_range(self):
        ws = _make_ws()
        cell = MagicMock()
        cell.data_type = "s"
        cell.row = 3
        zones = [{"name": "data", "rows": [5, 15], "type": "editable"}]
        result = _classify_cell(ws, cell, zones)
        assert result == "template"

    def test_template_cell_no_editable_zones(self):
        ws = _make_ws()
        cell = MagicMock()
        cell.data_type = "s"
        cell.row = 5
        zones = [{"name": "header", "rows": [1, 2], "type": "template"}]
        result = _classify_cell(ws, cell, zones)
        assert result == "template"


# ---------------------------------------------------------------------------
# analyze_to_json
# ---------------------------------------------------------------------------


class TestAnalyzeToJson:
    def test_success(self, tmp_path):
        excel_path = tmp_path / "test.xlsx"
        excel_path.write_bytes(b"fake")
        output_path = tmp_path / "output.json"

        ws = _make_ws(max_row=10, max_col=5, title="Sheet1")
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
                return_value="E",
            ),
        ):
            result = analyze_to_json(str(excel_path), str(output_path))
            assert result["success"] is True
            assert result["output_file"] == str(output_path)
            assert output_path.exists()
            saved = json.loads(output_path.read_text(encoding="utf-8"))
            assert saved["success"] is True

    def test_save_failure(self, tmp_path):
        excel_path = tmp_path / "test.xlsx"
        excel_path.write_bytes(b"fake")
        output_path = tmp_path / "output.json"

        ws = _make_ws(max_row=10, max_col=5, title="Sheet1")
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
                return_value="E",
            ),
            patch("builtins.open", side_effect=RuntimeError("disk full")),
        ):
            result = analyze_to_json(str(excel_path), str(output_path))
            assert result["success"] is False
            assert "保存JSON失败" in result["message"]


# ---------------------------------------------------------------------------
# ExcelAnalyzerSkill
# ---------------------------------------------------------------------------


class TestExcelAnalyzerSkill:
    def test_init(self):
        skill = ExcelAnalyzerSkill()
        assert skill.name == "excel_analyzer"
        assert "Excel" in skill.description

    def test_execute_without_output_json(self, tmp_path):
        excel_path = tmp_path / "test.xlsx"
        excel_path.write_bytes(b"fake")

        skill = ExcelAnalyzerSkill()
        with patch(
            "app.infrastructure.skills.excel_analyzer.excel_template_analyzer.analyze_template",
            return_value={"success": True, "file": "test.xlsx"},
        ) as mock_analyze:
            result = skill.execute(str(excel_path))
            assert result["success"] is True
            mock_analyze.assert_called_once_with(str(excel_path), None)

    def test_execute_with_output_json(self, tmp_path):
        excel_path = tmp_path / "test.xlsx"
        excel_path.write_bytes(b"fake")
        output_path = tmp_path / "out.json"

        skill = ExcelAnalyzerSkill()
        with patch(
            "app.infrastructure.skills.excel_analyzer.excel_template_analyzer.analyze_to_json",
            return_value={"success": True, "output_file": str(output_path)},
        ) as mock_analyze:
            result = skill.execute(str(excel_path), output_json=str(output_path))
            assert result["success"] is True
            mock_analyze.assert_called_once_with(str(excel_path), str(output_path), None)

    def test_execute_with_sheet_name(self, tmp_path):
        excel_path = tmp_path / "test.xlsx"
        excel_path.write_bytes(b"fake")

        skill = ExcelAnalyzerSkill()
        with patch(
            "app.infrastructure.skills.excel_analyzer.excel_template_analyzer.analyze_template",
            return_value={"success": True},
        ) as mock_analyze:
            result = skill.execute(str(excel_path), sheet_name="Sheet2")
            assert result["success"] is True
            mock_analyze.assert_called_once_with(str(excel_path), "Sheet2")

    def test_get_skill_info(self):
        skill = ExcelAnalyzerSkill()
        info = skill.get_skill_info()
        assert info["name"] == "excel_analyzer"
        assert "description" in info
        assert "parameters" in info
        assert "file_path" in info["parameters"]
        assert "sheet_name" in info["parameters"]
        assert "output_json" in info["parameters"]
        assert info["parameters"]["file_path"]["required"] is True
        assert info["parameters"]["sheet_name"]["required"] is False


# ---------------------------------------------------------------------------
# get_excel_analyzer_skill — singleton
# ---------------------------------------------------------------------------


class TestGetExcelAnalyzerSkill:
    def test_returns_instance(self):
        # Reset singleton
        import app.infrastructure.skills.excel_analyzer.excel_template_analyzer as mod

        mod._skill_instance = None
        skill = get_excel_analyzer_skill()
        assert isinstance(skill, ExcelAnalyzerSkill)

    def test_returns_same_instance(self):
        import app.infrastructure.skills.excel_analyzer.excel_template_analyzer as mod

        mod._skill_instance = None
        skill1 = get_excel_analyzer_skill()
        skill2 = get_excel_analyzer_skill()
        assert skill1 is skill2
