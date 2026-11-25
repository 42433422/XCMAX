"""Workflow composition and the retained spreadsheet analysis contract."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest


class TestReadExcelDataframe:
    def test_basic_read(self, tmp_path):
        import pandas as pd

        from app.application.tools.workflow import _read_excel_dataframe

        df = pd.DataFrame({"name": ["A", "B"], "value": [1, 2]})
        xlsx_path = str(tmp_path / "test.xlsx")
        df.to_excel(xlsx_path, index=False)
        result = _read_excel_dataframe(Path(xlsx_path), sheet_name=None, header_row_1based=None)
        assert len(result) == 2

    def test_with_sheet_name(self, tmp_path):
        import pandas as pd

        from app.application.tools.workflow import _read_excel_dataframe

        df = pd.DataFrame({"name": ["A"], "value": [1]})
        xlsx_path = str(tmp_path / "test_sheet.xlsx")
        df.to_excel(xlsx_path, sheet_name="Sheet1", index=False)
        result = _read_excel_dataframe(Path(xlsx_path), sheet_name="Sheet1", header_row_1based=None)
        assert len(result) == 1

    def test_with_header_row(self, tmp_path):
        import pandas as pd

        from app.application.tools.workflow import _read_excel_dataframe

        df = pd.DataFrame({"name": ["A"], "value": [1]})
        xlsx_path = str(tmp_path / "test_hdr.xlsx")
        df.to_excel(xlsx_path, index=False)
        result = _read_excel_dataframe(Path(xlsx_path), sheet_name=None, header_row_1based=1)
        assert isinstance(result, pd.DataFrame)


class TestHandleExcelAnalysisExtended:
    def test_read_action(self, tmp_path):
        import pandas as pd

        from app.application.tools.workflow import handle_excel_analysis

        df = pd.DataFrame({"name": ["A", "B"], "value": [1, 2]})
        xlsx_path = str(tmp_path / "read_test.xlsx")
        df.to_excel(xlsx_path, index=False)
        with patch(
            "app.application.tools.workflow.resolve_safe_excel_path",
            return_value=Path(xlsx_path),
        ):
            result = handle_excel_analysis(
                {"file_path": xlsx_path, "action": "read"},
                workspace_root=str(tmp_path),
            )
        assert result["success"] is True

    def test_query_action(self, tmp_path):
        import pandas as pd

        from app.application.tools.workflow import handle_excel_analysis

        df = pd.DataFrame({"name": ["A", "B"], "value": [1, 2]})
        xlsx_path = str(tmp_path / "query_test.xlsx")
        df.to_excel(xlsx_path, index=False)
        with patch(
            "app.application.tools.workflow.resolve_safe_excel_path",
            return_value=Path(xlsx_path),
        ):
            result = handle_excel_analysis(
                {"file_path": xlsx_path, "action": "query", "query_expression": "value >= 1"},
                workspace_root=str(tmp_path),
            )
        assert result["success"] is True

    def test_statistics_action(self, tmp_path):
        import pandas as pd

        from app.application.tools.workflow import handle_excel_analysis

        df = pd.DataFrame({"name": ["A", "B"], "value": [1, 2]})
        xlsx_path = str(tmp_path / "stats_test.xlsx")
        df.to_excel(xlsx_path, index=False)
        with patch(
            "app.application.tools.workflow.resolve_safe_excel_path",
            return_value=Path(xlsx_path),
        ):
            result = handle_excel_analysis(
                {"file_path": xlsx_path, "action": "statistics"},
                workspace_root=str(tmp_path),
            )
        assert result["success"] is True

    def test_aggregate_action(self, tmp_path):
        import pandas as pd

        from app.application.tools.workflow import handle_excel_analysis

        df = pd.DataFrame({"name": ["A", "A", "B"], "value": [1, 2, 3]})
        xlsx_path = str(tmp_path / "agg_test.xlsx")
        df.to_excel(xlsx_path, index=False)
        with patch(
            "app.application.tools.workflow.resolve_safe_excel_path",
            return_value=Path(xlsx_path),
        ):
            result = handle_excel_analysis(
                {
                    "file_path": xlsx_path,
                    "action": "aggregate",
                    "metrics": [{"column": "value", "op": "sum"}],
                },
                workspace_root=str(tmp_path),
            )
        assert result["success"] is True
        assert result["records"] == [{"value_sum": 6}]

    def test_query_expression_filters_rows(self, tmp_path):
        import pandas as pd

        from app.application.tools.workflow import handle_excel_analysis

        df = pd.DataFrame({"name": ["A", "B"], "value": [1, 2]})
        xlsx_path = str(tmp_path / "eq_test.xlsx")
        df.to_excel(xlsx_path, index=False)
        with patch(
            "app.application.tools.workflow.resolve_safe_excel_path",
            return_value=Path(xlsx_path),
        ):
            result = handle_excel_analysis(
                {"file_path": xlsx_path, "action": "query", "query_expression": "value > 1"},
                workspace_root=str(tmp_path),
            )
        assert result["success"] is True
        assert result["action"] == "query"
        assert result["records"] == [{"name": "B", "value": 2}]
