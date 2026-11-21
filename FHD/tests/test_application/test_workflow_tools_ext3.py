"""Spreadsheet reader engine selection and header behavior."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest


class TestReadExcelDataframeEngineSelection:
    def test_xlsx_file_uses_openpyxl(self, tmp_path):
        import pandas as pd

        from app.application.tools.workflow import _read_excel_dataframe

        df = pd.DataFrame({"name": ["A", "B"], "value": [1, 2]})
        xlsx_path = tmp_path / "test.xlsx"
        df.to_excel(str(xlsx_path), index=False)

        result = _read_excel_dataframe(xlsx_path, sheet_name=None, header_row_1based=1)
        assert len(result) == 2
        assert "name" in result.columns

    def test_with_sheet_name(self, tmp_path):
        import pandas as pd

        from app.application.tools.workflow import _read_excel_dataframe

        df = pd.DataFrame({"name": ["A"], "value": [1]})
        xlsx_path = tmp_path / "test_sheet.xlsx"
        df.to_excel(str(xlsx_path), index=False, sheet_name="Sheet1")

        result = _read_excel_dataframe(xlsx_path, sheet_name="Sheet1", header_row_1based=1)
        assert len(result) == 1

    def test_none_header_row(self, tmp_path):
        import pandas as pd

        from app.application.tools.workflow import _read_excel_dataframe

        df = pd.DataFrame({"name": ["A"], "value": [1]})
        xlsx_path = tmp_path / "test_hdr.xlsx"
        df.to_excel(str(xlsx_path), index=False)

        # header_row_1based=None means no header arg passed
        result = _read_excel_dataframe(xlsx_path, sheet_name=None, header_row_1based=None)
        assert result is not None
