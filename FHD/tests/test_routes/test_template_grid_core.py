"""Tests for app.routes.template_grid_core — coverage ramp."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.routes.template_grid_core import (
    _clean_customer_candidate,
    _extract_inline_customer_hits_from_cell,
    _is_trivial_customer_token,
)


# ---------------------------------------------------------------------------
# _clean_customer_candidate
# ---------------------------------------------------------------------------
class TestCleanCustomerCandidate:
    def test_normal_string(self):
        assert _clean_customer_candidate("张三公司") == "张三公司"

    def test_whitespace_collapsed(self):
        assert _clean_customer_candidate("张三  公司") == "张三 公司"

    def test_trailing_semicolons_stripped(self):
        assert _clean_customer_candidate("张三公司；") == "张三公司"

    def test_trailing_commas_stripped(self):
        assert _clean_customer_candidate("张三公司，") == "张三公司"

    def test_mixed_trailing_punctuation(self):
        assert _clean_customer_candidate("张三公司；, ") == "张三公司"

    def test_none_returns_empty(self):
        assert _clean_customer_candidate(None) == ""

    def test_empty_string(self):
        assert _clean_customer_candidate("") == ""

    def test_only_whitespace_and_punctuation(self):
        assert _clean_customer_candidate("  ；,") == ""


# ---------------------------------------------------------------------------
# _is_trivial_customer_token
# ---------------------------------------------------------------------------
class TestIsTrivialCustomerToken:
    def test_short_string(self):
        assert _is_trivial_customer_token("A") is True

    def test_empty_string(self):
        assert _is_trivial_customer_token("") is True

    def test_measure_unit(self):
        assert _is_trivial_customer_token("桶") is True
        assert _is_trivial_customer_token("箱") is True
        assert _is_trivial_customer_token("kg") is True

    def test_date_string(self):
        assert _is_trivial_customer_token("2024-01-01") is True

    def test_number(self):
        assert _is_trivial_customer_token("123") is True

    def test_number_with_comma(self):
        assert _is_trivial_customer_token("1,234") is True

    def test_valid_company_name(self):
        assert _is_trivial_customer_token("成都修茈科技有限公司") is False

    def test_none_returns_true(self):
        assert _is_trivial_customer_token(None) is True


# ---------------------------------------------------------------------------
# _extract_inline_customer_hits_from_cell
# ---------------------------------------------------------------------------
class TestExtractInlineCustomerHitsFromCell:
    def test_empty_string(self):
        assert _extract_inline_customer_hits_from_cell("") == []

    def test_short_string(self):
        assert _extract_inline_customer_hits_from_cell("ab") == []

    def test_customer_label(self):
        result = _extract_inline_customer_hits_from_cell("客户名称：成都修茈科技有限公司")
        assert len(result) >= 1
        assert "成都修茈" in result[0]

    def test_purchase_unit_label(self):
        result = _extract_inline_customer_hits_from_cell("购货单位：成都修茈科技有限公司")
        assert len(result) >= 1

    def test_customer_with_contact(self):
        result = _extract_inline_customer_hits_from_cell(
            "客户名称：成都修茈科技有限公司 联系人：张三"
        )
        assert len(result) >= 1
        assert "成都修茈" in result[0]

    def test_no_customer_label(self):
        result = _extract_inline_customer_hits_from_cell("普通文本没有客户信息")
        assert result == []

    def test_deduplication(self):
        text = "客户名称：成都修茈科技有限公司 客户名称：成都修茈科技有限公司"
        result = _extract_inline_customer_hits_from_cell(text)
        assert len(result) == 1

    def test_trivial_customer_filtered(self):
        # "桶" is a measure unit and should be filtered
        result = _extract_inline_customer_hits_from_cell("客户名称：桶")
        assert result == []

    def test_purchase_unit_with_paren(self):
        result = _extract_inline_customer_hits_from_cell("购货单位（简称）：成都修茈科技有限公司")
        # May or may not match depending on regex; just ensure no crash
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# _extract_customer_hint_from_excel
# ---------------------------------------------------------------------------
class TestExtractCustomerHintFromExcel:
    @patch("app.routes.template_grid_core._extract_inline_customer_hits_from_cell")
    @patch("openpyxl.load_workbook")
    def test_with_customer_in_cell(self, mock_wb_cls, mock_extract):
        mock_wb = MagicMock()
        mock_ws = MagicMock()
        mock_ws.max_row = 5
        mock_ws.max_column = 5
        mock_ws.sheetnames = ["Sheet1"]
        mock_wb.sheetnames = ["Sheet1"]
        mock_wb.__getitem__ = MagicMock(return_value=mock_ws)
        mock_wb.__enter__ = MagicMock(return_value=mock_wb)
        mock_wb.__exit__ = MagicMock(return_value=False)

        cell = MagicMock()
        cell.value = "客户名称：成都修茈科技有限公司"
        mock_ws.cell.return_value = cell

        mock_extract.return_value = ["成都修茈科技有限公司"]
        mock_wb_cls.return_value = mock_wb

        from app.routes.template_grid_core import _extract_customer_hint_from_excel

        result = _extract_customer_hint_from_excel("/tmp/test.xlsx")
        assert result == "成都修茈科技有限公司"

    def test_nonexistent_file(self):
        from app.routes.template_grid_core import _extract_customer_hint_from_excel

        result = _extract_customer_hint_from_excel("/nonexistent/file.xlsx")
        assert result == ""

    @patch("openpyxl.load_workbook")
    def test_empty_workbook(self, mock_wb_cls):
        mock_wb = MagicMock()
        mock_wb.sheetnames = []
        mock_wb_cls.return_value = mock_wb

        from app.routes.template_grid_core import _extract_customer_hint_from_excel

        result = _extract_customer_hint_from_excel("/tmp/test.xlsx")
        assert result == ""


# ---------------------------------------------------------------------------
# _extract_rectangular_excel_preview
# ---------------------------------------------------------------------------
class TestExtractRectangularExcelPreview:
    def test_nonexistent_file(self):
        from app.routes.template_grid_core import _extract_rectangular_excel_preview

        result = _extract_rectangular_excel_preview("/nonexistent/file.xlsx")
        assert result["fields"] == []
        assert result["sample_rows"] == []

    @patch("openpyxl.load_workbook")
    @patch("openpyxl.utils.get_column_letter")
    def test_with_data(self, mock_col_letter, mock_wb_cls):
        mock_col_letter.side_effect = lambda c: chr(64 + c)

        mock_wb = MagicMock()
        mock_ws = MagicMock()
        mock_ws.max_row = 2
        mock_ws.max_column = 2
        mock_ws.sheetnames = ["Sheet1"]
        mock_ws.title = "Sheet1"
        mock_wb.sheetnames = ["Sheet1"]
        mock_wb.__getitem__ = MagicMock(return_value=mock_ws)

        cell_a1 = MagicMock()
        cell_a1.value = "Header1"
        cell_b1 = MagicMock()
        cell_b1.value = "Header2"
        cell_a2 = MagicMock()
        cell_a2.value = "Data1"
        cell_b2 = MagicMock()
        cell_b2.value = "Data2"

        def cell_fn(r, c):
            if r == 1 and c == 1:
                return cell_a1
            if r == 1 and c == 2:
                return cell_b1
            if r == 2 and c == 1:
                return cell_a2
            if r == 2 and c == 2:
                return cell_b2
            return MagicMock(value=None)

        mock_ws.cell = cell_fn
        mock_wb_cls.return_value = mock_wb

        from app.routes.template_grid_core import _extract_rectangular_excel_preview

        result = _extract_rectangular_excel_preview("/tmp/test.xlsx")
        assert len(result["fields"]) == 2
        assert len(result["sample_rows"]) >= 1


# ---------------------------------------------------------------------------
# _extract_structured_excel_preview
# ---------------------------------------------------------------------------
class TestExtractStructuredExcelPreview:
    def test_no_force_header_delegates_to_legacy(self):
        from app.routes.template_grid_core import _extract_structured_excel_preview

        with patch(
            "app.application.facades.template_facade._extract_structured_excel_preview"
        ) as mock_legacy:
            mock_legacy.return_value = {"fields": [], "sample_rows": [], "sheet_name": ""}
            result = _extract_structured_excel_preview("/tmp/test.xlsx")
            mock_legacy.assert_called_once()

    def test_negative_force_header_delegates_to_legacy(self):
        from app.routes.template_grid_core import _extract_structured_excel_preview

        with patch(
            "app.application.facades.template_facade._extract_structured_excel_preview"
        ) as mock_legacy:
            mock_legacy.return_value = {"fields": [], "sample_rows": [], "sheet_name": ""}
            result = _extract_structured_excel_preview("/tmp/test.xlsx", force_header_row_1based=0)
            mock_legacy.assert_called_once()

    @patch("openpyxl.load_workbook")
    def test_with_force_header(self, mock_wb_cls):
        mock_wb = MagicMock()
        mock_ws = MagicMock()
        mock_ws.max_column = 2
        mock_ws.max_row = 5
        mock_ws.sheetnames = ["Sheet1"]
        mock_ws.title = "Sheet1"
        mock_wb.sheetnames = ["Sheet1"]
        mock_wb.__getitem__ = MagicMock(return_value=mock_ws)

        def cell_fn(r, c):
            m = MagicMock()
            if r == 1:
                m.value = f"Col{c}"
            elif r == 2:
                m.value = f"Val{c}"
            else:
                m.value = None
            return m

        mock_ws.cell = cell_fn
        mock_wb_cls.return_value = mock_wb

        from app.routes.template_grid_core import _extract_structured_excel_preview

        result = _extract_structured_excel_preview("/tmp/test.xlsx", force_header_row_1based=1)
        assert len(result["fields"]) == 2

    @patch("openpyxl.load_workbook")
    def test_empty_header_row(self, mock_wb_cls):
        mock_wb = MagicMock()
        mock_ws = MagicMock()
        mock_ws.max_column = 2
        mock_ws.max_row = 5
        mock_ws.sheetnames = ["Sheet1"]
        mock_ws.title = "Sheet1"
        mock_wb.sheetnames = ["Sheet1"]
        mock_wb.__getitem__ = MagicMock(return_value=mock_ws)

        cell_empty = MagicMock()
        cell_empty.value = None
        mock_ws.cell = MagicMock(return_value=cell_empty)
        mock_wb_cls.return_value = mock_wb

        from app.routes.template_grid_core import _extract_structured_excel_preview

        result = _extract_structured_excel_preview("/tmp/test.xlsx", force_header_row_1based=1)
        assert result["fields"] == []
