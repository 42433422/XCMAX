"""Tests for app.fastapi_routes.excel_extract — pure helper functions."""

from __future__ import annotations

import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from app.fastapi_routes.excel_extract import (
    TEMP_EXCEL_DIR,
    _extract_from_excel,
    _generate_excel,
)

# ========================= _extract_from_excel ===========================


class TestExtractFromExcel:
    def test_file_not_found(self):
        result, status = _extract_from_excel("/nonexistent/file.xlsx")
        assert status == 404
        assert result["success"] is False

    def test_extract_basic(self):
        """Test extraction from a real xlsx file."""
        from openpyxl import Workbook

        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            wb = Workbook()
            ws = wb.active
            ws.title = "Sheet1"
            ws.append(["Name", "Age"])
            ws.append(["Alice", 30])
            ws.append(["Bob", 25])
            wb.save(f.name)
            path = f.name

        try:
            result, status = _extract_from_excel(path)
            assert status == 200
            assert result["success"] is True
            assert result["total_rows"] == 2
            assert len(result["headers"]) == 2
        finally:
            os.unlink(path)

    def test_extract_with_sheet_name(self):
        from openpyxl import Workbook

        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            wb = Workbook()
            ws = wb.active
            ws.title = "Data"
            ws.append(["Col1"])
            ws.append(["val1"])
            wb.save(f.name)
            path = f.name

        try:
            result, status = _extract_from_excel(path, sheet_name="Data")
            assert status == 200
            assert result["sheet"] == "Data"
        finally:
            os.unlink(path)


# ========================= _generate_excel ===============================


class TestGenerateExcel:
    def test_basic_generation(self):
        data = [{"Name": "Alice", "Age": 30}, {"Name": "Bob", "Age": 25}]
        result, status = _generate_excel(data)
        assert status == 200
        assert result["success"] is True
        assert result["rows"] == 2
        assert os.path.exists(result["file_path"])
        # Cleanup
        os.unlink(result["file_path"])

    def test_custom_filename(self):
        data = [{"A": 1}]
        result, status = _generate_excel(data, filename="test_custom.xlsx")
        assert status == 200
        assert "test_custom.xlsx" in result["filename"]
        os.unlink(result["file_path"])

    def test_custom_sheet_name(self):
        data = [{"A": 1}]
        result, status = _generate_excel(data, sheet_name="MySheet")
        assert status == 200
        assert result["sheet"] == "MySheet"
        os.unlink(result["file_path"])

    def test_empty_data(self):
        result, status = _generate_excel([])
        assert status == 400
        assert result["success"] is False

    def test_invalid_data(self):
        result, status = _generate_excel("not a list")
        assert status == 400
        assert result["success"] is False
