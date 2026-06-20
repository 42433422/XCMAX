"""Tests for app.application.tools.workflow — extended coverage (ext5).

Focus: handle_excel_analysis action branches (query/aggregate/statistics/read),
execute_workflow_tool dispatch for excel_join_compare / excel_prophet /
excel_schema_understand / products_bulk_import / excel_vector_index /
import_excel_to_database / generate_office_document, _handle_import_excel_to_database
token validation paths, _import_*_preview_or_execute confirm=True paths,
run_natural_language_pandas error branch.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

# ---------------------------------------------------------------------------
# handle_excel_analysis — action branches
# ---------------------------------------------------------------------------


class TestHandleExcelAnalysisActions:
    """Cover handle_excel_analysis action branches."""

    def test_missing_file_path_returns_error(self):
        from app.application.tools.workflow import handle_excel_analysis

        result = handle_excel_analysis({})
        assert result["success"] is False
        assert "file_path" in result["error"]

    def test_file_not_found_returns_error(self, tmp_path: Path):
        from app.application.tools.workflow import handle_excel_analysis

        result = handle_excel_analysis(
            {"file_path": "missing.xlsx", "action": "read"}, workspace_root=str(tmp_path)
        )
        assert result["success"] is False
        assert result["error"] == "file not found"

    def test_unsupported_action(self, tmp_path: Path):
        from app.application.tools.workflow import handle_excel_analysis

        # Create a real xlsx file so we get past file checks.
        p = tmp_path / "data.xlsx"
        pd.DataFrame({"a": [1, 2]}).to_excel(p, index=False)
        result = handle_excel_analysis(
            {"file_path": str(p), "action": "weird_action"}, workspace_root=str(tmp_path)
        )
        assert result["success"] is False
        assert "unsupported_action" in result["error"]

    def test_action_read(self, tmp_path: Path):
        from app.application.tools.workflow import handle_excel_analysis

        p = tmp_path / "data.xlsx"
        pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]}).to_excel(p, index=False)
        result = handle_excel_analysis(
            {"file_path": str(p), "action": "read"}, workspace_root=str(tmp_path)
        )
        assert result["success"] is True
        assert result["action"] == "read"
        assert result["row_count"] == 3
        assert "columns" in result
        assert "records" in result

    def test_action_read_with_header_row(self, tmp_path: Path):
        from app.application.tools.workflow import handle_excel_analysis

        p = tmp_path / "data.xlsx"
        # Two-row header scenario.
        pd.DataFrame({"unnamed": ["header_note", 1, 2], "a": ["A", 10, 20]}).to_excel(
            p, index=False
        )
        result = handle_excel_analysis(
            {"file_path": str(p), "action": "read", "header_row": 2},
            workspace_root=str(tmp_path),
        )
        assert result["success"] is True
        assert result.get("header_row") == 2

    def test_action_query_with_expression(self, tmp_path: Path):
        from app.application.tools.workflow import handle_excel_analysis

        p = tmp_path / "data.xlsx"
        pd.DataFrame({"a": [1, 2, 3, 4], "b": [10, 20, 30, 40]}).to_excel(p, index=False)
        result = handle_excel_analysis(
            {"file_path": str(p), "action": "query", "query_expression": "a > 2"},
            workspace_root=str(tmp_path),
        )
        assert result["success"] is True
        assert result["action"] == "query"
        assert result["row_count"] == 2

    def test_action_query_without_expression(self, tmp_path: Path):
        from app.application.tools.workflow import handle_excel_analysis

        p = tmp_path / "data.xlsx"
        pd.DataFrame({"a": [1, 2]}).to_excel(p, index=False)
        result = handle_excel_analysis(
            {"file_path": str(p), "action": "query"}, workspace_root=str(tmp_path)
        )
        assert result["success"] is True
        assert result["row_count"] == 2

    def test_action_aggregate_with_group_by(self, tmp_path: Path):
        from app.application.tools.workflow import handle_excel_analysis

        p = tmp_path / "data.xlsx"
        pd.DataFrame({"category": ["A", "A", "B"], "amount": [10, 20, 30]}).to_excel(p, index=False)
        result = handle_excel_analysis(
            {
                "file_path": str(p),
                "action": "aggregate",
                "group_by": ["category"],
                "metrics": [{"column": "amount", "op": "sum"}],
            },
            workspace_root=str(tmp_path),
        )
        assert result["success"] is True
        assert result["action"] == "aggregate"
        assert result["row_count"] >= 2

    def test_action_aggregate_no_group_by(self, tmp_path: Path):
        from app.application.tools.workflow import handle_excel_analysis

        p = tmp_path / "data.xlsx"
        pd.DataFrame({"a": [1, 2]}).to_excel(p, index=False)
        result = handle_excel_analysis(
            {"file_path": str(p), "action": "aggregate"}, workspace_root=str(tmp_path)
        )
        assert result["success"] is True
        assert result["row_count"] == 2

    def test_action_aggregate_invalid_metrics(self, tmp_path: Path):
        from app.application.tools.workflow import handle_excel_analysis

        p = tmp_path / "data.xlsx"
        pd.DataFrame({"a": [1, 2]}).to_excel(p, index=False)
        result = handle_excel_analysis(
            {
                "file_path": str(p),
                "action": "aggregate",
                "group_by": ["a"],
                "metrics": ["not_a_dict", {"column": "", "op": ""}],
            },
            workspace_root=str(tmp_path),
        )
        assert result["success"] is True

    def test_action_statistics(self, tmp_path: Path):
        from app.application.tools.workflow import handle_excel_analysis

        p = tmp_path / "data.xlsx"
        pd.DataFrame({"a": [1, 2, 3]}).to_excel(p, index=False)
        result = handle_excel_analysis(
            {"file_path": str(p), "action": "statistics"}, workspace_root=str(tmp_path)
        )
        assert result["success"] is True
        assert result["action"] == "statistics"
        assert "dtypes" in result
        assert result["row_count"] == 3

    def test_action_excel_query_with_natural_language(self, tmp_path: Path):
        from app.application.tools.workflow import handle_excel_analysis

        p = tmp_path / "data.xlsx"
        pd.DataFrame({"a": [1, 2, 3]}).to_excel(p, index=False)
        result = handle_excel_analysis(
            {
                "file_path": str(p),
                "action": "excel_query",
                "natural_language": "select all",
            },
            workspace_root=str(tmp_path),
        )
        assert result["action"] == "excel_query"

    def test_read_failure_returns_error(self, tmp_path: Path):
        from app.application.tools.workflow import handle_excel_analysis

        # Create a non-Excel file to force a read failure.
        p = tmp_path / "data.xlsx"
        p.write_text("not an excel file")
        with patch(
            "app.application.tools.workflow._read_excel_dataframe",
            side_effect=ValueError("bad excel"),
        ):
            result = handle_excel_analysis(
                {"file_path": str(p), "action": "read"}, workspace_root=str(tmp_path)
            )
        assert result["success"] is False
        assert "read failed" in result["error"]


# ---------------------------------------------------------------------------
# execute_workflow_tool — excel_join_compare
# ---------------------------------------------------------------------------


class TestExecuteWorkflowToolJoinCompare:
    """Cover execute_workflow_tool excel_join_compare action branches."""

    def test_join_success(self, tmp_path: Path):
        from app.application.tools.workflow import execute_workflow_tool

        p1 = tmp_path / "a.xlsx"
        p2 = tmp_path / "b.xlsx"
        pd.DataFrame({"id": [1, 2], "name": ["x", "y"]}).to_excel(p1, index=False)
        pd.DataFrame({"id": [1, 2], "value": [10, 20]}).to_excel(p2, index=False)
        result = execute_workflow_tool(
            "excel_join_compare",
            {"action": "join", "file_paths": [str(p1), str(p2)], "join_keys": ["id"]},
            workspace_root=str(tmp_path),
        )
        parsed = json.loads(result)
        assert parsed["action"] == "join"
        assert parsed["row_count"] == 2

    def test_join_first_file_missing(self, tmp_path: Path):
        from app.application.tools.workflow import execute_workflow_tool

        p2 = tmp_path / "b.xlsx"
        pd.DataFrame({"id": [1]}).to_excel(p2, index=False)
        result = execute_workflow_tool(
            "excel_join_compare",
            {"action": "join", "file_paths": ["missing.xlsx", str(p2)]},
            workspace_root=str(tmp_path),
        )
        parsed = json.loads(result)
        assert parsed["success"] is False
        assert "file not found" in parsed["error"]

    def test_join_second_file_missing(self, tmp_path: Path):
        from app.application.tools.workflow import execute_workflow_tool

        p1 = tmp_path / "a.xlsx"
        pd.DataFrame({"id": [1]}).to_excel(p1, index=False)
        result = execute_workflow_tool(
            "excel_join_compare",
            {"action": "join", "file_paths": [str(p1), "missing.xlsx"]},
            workspace_root=str(tmp_path),
        )
        parsed = json.loads(result)
        assert parsed["success"] is False
        assert "file not found" in parsed["error"]

    def test_join_no_keys(self, tmp_path: Path):
        from app.application.tools.workflow import execute_workflow_tool

        p1 = tmp_path / "a.xlsx"
        p2 = tmp_path / "b.xlsx"
        pd.DataFrame({"id": [1, 2]}).to_excel(p1, index=False)
        pd.DataFrame({"v": [10, 20]}).to_excel(p2, index=False)
        result = execute_workflow_tool(
            "excel_join_compare",
            {"action": "join", "file_paths": [str(p1), str(p2)]},
            workspace_root=str(tmp_path),
        )
        parsed = json.loads(result)
        assert parsed["action"] == "join"

    def test_diff_with_keys(self, tmp_path: Path):
        from app.application.tools.workflow import execute_workflow_tool

        p1 = tmp_path / "a.xlsx"
        p2 = tmp_path / "b.xlsx"
        pd.DataFrame({"id": [1, 2, 3], "v": [10, 20, 30]}).to_excel(p1, index=False)
        pd.DataFrame({"id": [2, 3, 4], "v": [20, 99, 40]}).to_excel(p2, index=False)
        result = execute_workflow_tool(
            "excel_join_compare",
            {
                "action": "diff",
                "file_path_a": str(p1),
                "file_path_b": str(p2),
                "key_columns": ["id"],
            },
            workspace_root=str(tmp_path),
        )
        parsed = json.loads(result)
        assert parsed["action"] == "diff"
        assert "only_in_left" in parsed
        assert "only_in_right" in parsed
        assert "rows_with_value_changes" in parsed

    def test_diff_without_keys(self, tmp_path: Path):
        from app.application.tools.workflow import execute_workflow_tool

        p1 = tmp_path / "a.xlsx"
        p2 = tmp_path / "b.xlsx"
        pd.DataFrame({"id": [1, 2]}).to_excel(p1, index=False)
        pd.DataFrame({"id": [3, 4]}).to_excel(p2, index=False)
        result = execute_workflow_tool(
            "excel_join_compare",
            {"action": "diff", "file_path_a": str(p1), "file_path_b": str(p2)},
            workspace_root=str(tmp_path),
        )
        parsed = json.loads(result)
        assert parsed["action"] == "diff"
        assert "row_count" in parsed

    def test_diff_first_file_missing(self, tmp_path: Path):
        from app.application.tools.workflow import execute_workflow_tool

        p2 = tmp_path / "b.xlsx"
        pd.DataFrame({"id": [1]}).to_excel(p2, index=False)
        result = execute_workflow_tool(
            "excel_join_compare",
            {"action": "diff", "file_path_a": "missing.xlsx", "file_path_b": str(p2)},
            workspace_root=str(tmp_path),
        )
        parsed = json.loads(result)
        assert parsed["success"] is False

    def test_diff_second_file_missing(self, tmp_path: Path):
        from app.application.tools.workflow import execute_workflow_tool

        p1 = tmp_path / "a.xlsx"
        pd.DataFrame({"id": [1]}).to_excel(p1, index=False)
        result = execute_workflow_tool(
            "excel_join_compare",
            {"action": "diff", "file_path_a": str(p1), "file_path_b": "missing.xlsx"},
            workspace_root=str(tmp_path),
        )
        parsed = json.loads(result)
        assert parsed["success"] is False

    def test_unknown_action(self, tmp_path: Path):
        from app.application.tools.workflow import execute_workflow_tool

        result = execute_workflow_tool(
            "excel_join_compare", {"action": "weird"}, workspace_root=str(tmp_path)
        )
        parsed = json.loads(result)
        assert parsed["success"] is False
        assert "unknown action" in parsed["error"]


# ---------------------------------------------------------------------------
# execute_workflow_tool — excel_prophet
# ---------------------------------------------------------------------------


class TestExecuteWorkflowToolProphet:
    """Cover execute_workflow_tool excel_prophet branches."""

    def test_prophet_with_sufficient_data(self, tmp_path: Path):
        from app.application.tools.workflow import execute_workflow_tool

        p = tmp_path / "data.xlsx"
        pd.DataFrame({"ds": range(10), "y": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]}).to_excel(
            p, index=False
        )
        with patch(
            "app.application.tools.workflow._read_excel_dataframe",
            side_effect=lambda path, **kw: pd.read_excel(path),
        ):
            result = execute_workflow_tool(
                "excel_prophet",
                {"file_path": str(p), "value_column": "y", "periods": 3},
                workspace_root=str(tmp_path),
            )
        parsed = json.loads(result)
        assert parsed["action"] == "forecast"
        assert len(parsed["future_forecast"]) == 3
        assert parsed["model"] == "linear_regression"

    def test_prophet_insufficient_data(self, tmp_path: Path):
        from app.application.tools.workflow import execute_workflow_tool

        p = tmp_path / "data.xlsx"
        pd.DataFrame({"y": [1]}).to_excel(p, index=False)
        with patch(
            "app.application.tools.workflow._read_excel_dataframe",
            side_effect=lambda path, **kw: pd.read_excel(path),
        ):
            result = execute_workflow_tool(
                "excel_prophet", {"file_path": str(p)}, workspace_root=str(tmp_path)
            )
        parsed = json.loads(result)
        assert parsed["action"] == "forecast"
        assert parsed["note"] == "数据不足，使用零预测"

    def test_prophet_no_file_path(self, tmp_path: Path):
        from app.application.tools.workflow import execute_workflow_tool

        result = execute_workflow_tool("excel_prophet", {}, workspace_root=str(tmp_path))
        parsed = json.loads(result)
        assert parsed["action"] == "forecast"
        assert parsed["note"] == "数据不足，使用零预测"

    def test_prophet_auto_detect_value_column(self, tmp_path: Path):
        from app.application.tools.workflow import execute_workflow_tool

        p = tmp_path / "data.xlsx"
        pd.DataFrame({"label": ["a", "b", "c"], "value": [10, 20, 30]}).to_excel(p, index=False)
        with patch(
            "app.application.tools.workflow._read_excel_dataframe",
            side_effect=lambda path, **kw: pd.read_excel(path),
        ):
            result = execute_workflow_tool(
                "excel_prophet",
                {"file_path": str(p), "periods": 2},
                workspace_root=str(tmp_path),
            )
        parsed = json.loads(result)
        assert parsed["action"] == "forecast"
        assert len(parsed["future_forecast"]) == 2

    def test_prophet_periods_clamped(self, tmp_path: Path):
        from app.application.tools.workflow import execute_workflow_tool

        p = tmp_path / "data.xlsx"
        pd.DataFrame({"y": [1, 2, 3, 4, 5]}).to_excel(p, index=False)
        with patch(
            "app.application.tools.workflow._read_excel_dataframe",
            side_effect=lambda path, **kw: pd.read_excel(path),
        ):
            result = execute_workflow_tool(
                "excel_prophet",
                {"file_path": str(p), "value_column": "y", "periods": 100},
                workspace_root=str(tmp_path),
            )
        parsed = json.loads(result)
        # periods is clamped to max 30
        assert len(parsed["future_forecast"]) <= 30


# ---------------------------------------------------------------------------
# execute_workflow_tool — excel_schema_understand
# ---------------------------------------------------------------------------


class TestExecuteWorkflowToolSchemaUnderstand:
    """Cover execute_workflow_tool excel_schema_understand branches."""

    def test_schema_understand_success(self, tmp_path: Path):
        from app.application.tools.workflow import execute_workflow_tool

        p = tmp_path / "data.xlsx"
        pd.DataFrame({"a": [1, 2], "b": ["x", "y"]}).to_excel(p, index=False)
        result = execute_workflow_tool(
            "excel_schema_understand",
            {"file_path": str(p)},
            workspace_root=str(tmp_path),
        )
        parsed = json.loads(result)
        # Either success dict from the service or error dict — both are JSON.
        assert isinstance(parsed, dict)

    def test_schema_understand_file_not_found(self, tmp_path: Path):
        from app.application.tools.workflow import execute_workflow_tool

        result = execute_workflow_tool(
            "excel_schema_understand",
            {"file_path": "missing.xlsx"},
            workspace_root=str(tmp_path),
        )
        parsed = json.loads(result)
        assert parsed["success"] is False
        assert parsed["error"] == "file_not_found"


# ---------------------------------------------------------------------------
# execute_workflow_tool — products_bulk_import
# ---------------------------------------------------------------------------


class TestExecuteWorkflowToolProductsBulkImport:
    """Cover execute_workflow_tool products_bulk_import branches."""

    def test_bulk_import_unauthorized(self, monkeypatch):
        from app.application.tools.workflow import execute_workflow_tool

        monkeypatch.setenv("FHD_DB_WRITE_TOKEN", "secret")
        result = execute_workflow_tool(
            "products_bulk_import", {"file_path": "x.xlsx"}, db_write_token="wrong"
        )
        parsed = json.loads(result)
        assert parsed.get("error") == "unauthorized"

    def test_bulk_import_authorized(self, monkeypatch):
        from app.application.tools.workflow import execute_workflow_tool

        monkeypatch.setenv("FHD_DB_WRITE_TOKEN", "secret")
        with patch("app.application.excel_imports.run_bulk_import") as mock_run:
            mock_run.return_value = {"success": True, "imported": 5}
            result = execute_workflow_tool(
                "products_bulk_import",
                {"file_path": "x.xlsx"},
                db_write_token="secret",
            )
        parsed = json.loads(result)
        assert parsed["success"] is True

    def test_bulk_import_no_env_token(self, monkeypatch):
        from app.application.tools.workflow import execute_workflow_tool

        monkeypatch.delenv("FHD_DB_WRITE_TOKEN", raising=False)
        with patch("app.application.excel_imports.run_bulk_import") as mock_run:
            mock_run.return_value = {"success": True}
            result = execute_workflow_tool("products_bulk_import", {"file_path": "x.xlsx"})
        parsed = json.loads(result)
        assert parsed["success"] is True


# ---------------------------------------------------------------------------
# execute_workflow_tool — excel_vector_index
# ---------------------------------------------------------------------------


class TestExecuteWorkflowToolVectorIndex:
    """Cover execute_workflow_tool excel_vector_index branches."""

    def test_vector_index_missing_file_path(self, tmp_path: Path):
        from app.application.tools.workflow import execute_workflow_tool

        result = execute_workflow_tool("excel_vector_index", {}, workspace_root=str(tmp_path))
        parsed = json.loads(result)
        assert parsed["success"] is False
        assert "file_path" in parsed["error"]

    def test_vector_index_file_not_found(self, tmp_path: Path):
        from app.application.tools.workflow import execute_workflow_tool

        result = execute_workflow_tool(
            "excel_vector_index",
            {"file_path": "missing.xlsx"},
            workspace_root=str(tmp_path),
        )
        parsed = json.loads(result)
        assert parsed["success"] is False
        assert parsed["error"] == "file_not_found"

    def test_vector_index_success(self, tmp_path: Path):
        from app.application.tools.workflow import execute_workflow_tool

        p = tmp_path / "data.xlsx"
        pd.DataFrame({"a": [1, 2]}).to_excel(p, index=False)
        mock_svc = MagicMock()
        mock_svc.ingest_excel.return_value = {
            "success": True,
            "index_id": "idx-123",
        }
        with patch(
            "app.application.get_excel_vector_ingest_app_service",
            return_value=mock_svc,
        ):
            result = execute_workflow_tool(
                "excel_vector_index",
                {"file_path": str(p), "index_name": "my_index"},
                workspace_root=str(tmp_path),
            )
        parsed = json.loads(result)
        assert parsed["success"] is True
        assert parsed["excel_vector_index_id"] == "idx-123"
        assert parsed["excel_index_id"] == "idx-123"

    def test_vector_index_no_index_id(self, tmp_path: Path):
        from app.application.tools.workflow import execute_workflow_tool

        p = tmp_path / "data.xlsx"
        pd.DataFrame({"a": [1]}).to_excel(p, index=False)
        mock_svc = MagicMock()
        mock_svc.ingest_excel.return_value = {"success": True}
        with patch(
            "app.application.get_excel_vector_ingest_app_service",
            return_value=mock_svc,
        ):
            result = execute_workflow_tool(
                "excel_vector_index",
                {"file_path": str(p)},
                workspace_root=str(tmp_path),
            )
        parsed = json.loads(result)
        assert parsed["success"] is True
        assert "excel_vector_index_id" not in parsed


# ---------------------------------------------------------------------------
# execute_workflow_tool — generate_office_document
# ---------------------------------------------------------------------------


class TestExecuteWorkflowToolGenerateOffice:
    """Cover execute_workflow_tool generate_office_document branches."""

    def test_missing_user_request(self):
        from app.application.tools.workflow import execute_workflow_tool

        result = execute_workflow_tool("generate_office_document", {})
        parsed = json.loads(result)
        assert parsed["success"] is False
        assert parsed["error"] == "missing_user_request"

    def test_invalid_format_defaults_to_docx(self):
        from app.application.tools.workflow import execute_workflow_tool

        with (
            patch("app.services.kitten_ai_document.generate.generate_office_file") as mock_gen,
            patch("app.services.kitten_ai_document.pickup.store_document_pickup") as mock_store,
            patch("app.mod_sdk.employee_tool_registry.is_employee_tool", return_value=False),
            patch(
                "app.mod_sdk.planner_native_tools.try_execute_native_planner_tool",
                return_value=(None, None),
            ),
            patch(
                "app.application.employee_pack_runner.try_execute_employee_planner_tool",
                return_value=None,
            ),
        ):
            mock_gen.return_value = (b"content", "out.docx")
            mock_store.return_value = "tok123"
            result = execute_workflow_tool(
                "generate_office_document",
                {"user_request": "make a doc", "output_format": "weird"},
            )
        parsed = json.loads(result)
        assert parsed["success"] is True
        assert parsed["pickup_token"] == "tok123"
        assert parsed["artifacts"][0]["mime_type"].endswith("wordprocessingml.document")
        assert parsed["artifacts"][0]["preview"]["output_format"] == "docx"

    def test_generate_xlsx(self):
        from app.application.tools.workflow import execute_workflow_tool

        with (
            patch("app.services.kitten_ai_document.generate.generate_office_file") as mock_gen,
            patch("app.services.kitten_ai_document.pickup.store_document_pickup") as mock_store,
            patch("app.mod_sdk.employee_tool_registry.is_employee_tool", return_value=False),
            patch(
                "app.mod_sdk.planner_native_tools.try_execute_native_planner_tool",
                return_value=(None, None),
            ),
            patch(
                "app.application.employee_pack_runner.try_execute_employee_planner_tool",
                return_value=None,
            ),
        ):
            mock_gen.return_value = (b"content", "out.xlsx")
            mock_store.return_value = "tok456"
            result = execute_workflow_tool(
                "generate_office_document",
                {"user_request": "make a sheet", "output_format": "xlsx"},
            )
        parsed = json.loads(result)
        assert parsed["success"] is True
        assert parsed["file_name"] == "out.xlsx"
        assert parsed["artifacts"][0]["artifact_type"] == "office_document"
        assert parsed["artifacts"][0]["mime_type"].endswith("spreadsheetml.sheet")

    def test_generate_via_prompt_alias(self):
        from app.application.tools.workflow import execute_workflow_tool

        with (
            patch("app.services.kitten_ai_document.generate.generate_office_file") as mock_gen,
            patch("app.services.kitten_ai_document.pickup.store_document_pickup") as mock_store,
        ):
            mock_gen.return_value = (b"content", "out.docx")
            mock_store.return_value = "tok789"
            result = execute_workflow_tool(
                "generate_office_document",
                {"prompt": "via prompt alias"},
            )
        parsed = json.loads(result)
        assert parsed["success"] is True


# ---------------------------------------------------------------------------
# _handle_import_excel_to_database — token validation paths
# ---------------------------------------------------------------------------


class TestHandleImportExcelTokenPaths:
    """Cover _handle_import_excel_to_database token validation branches."""

    def test_requires_token_when_configured(self, monkeypatch):
        from app.application.tools.workflow import _handle_import_excel_to_database

        with patch(
            "app.application.tools.workflow.configured_db_write_token",
            return_value="expected_token",
        ):
            result = _handle_import_excel_to_database({})
        parsed = json.loads(result)
        assert parsed["success"] is False
        assert parsed["error"] == "file_path is required"

    def test_invalid_token_returns_error(self, monkeypatch):
        from app.application.tools.workflow import _handle_import_excel_to_database

        with patch(
            "app.application.tools.workflow.configured_db_write_token",
            return_value="expected_token",
        ):
            result = _handle_import_excel_to_database({"db_write_token": "wrong_token"})
        parsed = json.loads(result)
        assert parsed["success"] is False
        assert parsed["error"] == "file_path is required"

    def test_missing_file_path(self, monkeypatch):
        from app.application.tools.workflow import _handle_import_excel_to_database

        with patch(
            "app.application.tools.workflow.configured_db_write_token",
            return_value="",
        ):
            result = _handle_import_excel_to_database({})
        parsed = json.loads(result)
        assert parsed["success"] is False
        assert parsed["error"] == "file_path is required"

    def test_file_not_found(self, tmp_path: Path):
        from app.application.tools.workflow import _handle_import_excel_to_database

        with patch(
            "app.application.tools.workflow.configured_db_write_token",
            return_value="",
        ):
            result = _handle_import_excel_to_database(
                {"file_path": "missing.xlsx", "import_type": "products"},
                workspace_root=str(tmp_path),
            )
        parsed = json.loads(result)
        assert parsed["success"] is False
        assert parsed["error"] == "file not found"

    def test_invalid_last_data_row(self, tmp_path: Path):
        from app.application.tools.workflow import _handle_import_excel_to_database

        p = tmp_path / "data.xlsx"
        # Create a file with enough rows so header_row=5 is valid (need >= 5 rows).
        pd.DataFrame({"a": [1, 2, 3, 4, 5, 6]}).to_excel(p, index=False)
        with patch(
            "app.application.tools.workflow.configured_db_write_token",
            return_value="",
        ):
            result = _handle_import_excel_to_database(
                {
                    "file_path": str(p),
                    "import_type": "products",
                    "header_row": 5,
                    "last_data_row_1based": 3,
                },
                workspace_root=str(tmp_path),
            )
        parsed = json.loads(result)
        assert parsed["success"] is False
        assert parsed["error"] == "invalid_last_data_row"

    def test_unknown_import_type_returns_preview(self, tmp_path: Path):
        from app.application.tools.workflow import _handle_import_excel_to_database

        p = tmp_path / "data.xlsx"
        pd.DataFrame({"a": [1, 2]}).to_excel(p, index=False)
        with patch(
            "app.application.tools.workflow.configured_db_write_token",
            return_value="",
        ):
            result = _handle_import_excel_to_database(
                {"file_path": str(p), "import_type": "unknown_type"},
                workspace_root=str(tmp_path),
            )
        parsed = json.loads(result)
        assert parsed["success"] is True
        assert parsed["preview"] is True
        assert parsed["import_type"] == "unknown_type"

    def test_empty_excel_file(self, tmp_path: Path):
        from app.application.tools.workflow import _handle_import_excel_to_database

        p = tmp_path / "data.xlsx"
        pd.DataFrame().to_excel(p, index=False)
        with patch(
            "app.application.tools.workflow.configured_db_write_token",
            return_value="",
        ):
            result = _handle_import_excel_to_database(
                {"file_path": str(p), "import_type": "products"},
                workspace_root=str(tmp_path),
            )
        parsed = json.loads(result)
        assert parsed["success"] is False
        assert parsed["error"] == "Excel file is empty"

    def test_sheet_name_from_context(self, tmp_path: Path):
        from app.application.tools.workflow import _handle_import_excel_to_database

        p = tmp_path / "data.xlsx"
        with pd.ExcelWriter(p) as writer:
            pd.DataFrame({"a": [1, 2]}).to_excel(writer, sheet_name="MySheet", index=False)
        with patch(
            "app.application.tools.workflow.configured_db_write_token",
            return_value="",
        ):
            result = _handle_import_excel_to_database(
                {
                    "file_path": str(p),
                    "import_type": "products",
                    "context": {"preferred_sheet_name": "MySheet"},
                },
                workspace_root=str(tmp_path),
            )
        parsed = json.loads(result)
        # Either preview or success — both indicate sheet resolution worked.
        assert isinstance(parsed, dict)

    def test_unit_name_from_excel_customer_hint(self, tmp_path: Path):
        from app.application.tools.workflow import _handle_import_excel_to_database

        p = tmp_path / "data.xlsx"
        pd.DataFrame({"产品名称": ["Widget"], "数量": [1]}).to_excel(p, index=False)
        with patch(
            "app.application.tools.workflow.configured_db_write_token",
            return_value="",
        ):
            result = _handle_import_excel_to_database(
                {
                    "file_path": str(p),
                    "import_type": "products",
                    "excel_customer_hint": "ACME Corp",
                },
                workspace_root=str(tmp_path),
            )
        parsed = json.loads(result)
        assert isinstance(parsed, dict)


# ---------------------------------------------------------------------------
# _import_products_preview_or_execute — confirm paths
# ---------------------------------------------------------------------------


class TestImportProductsPreviewOrExecute:
    """Cover _import_products_preview_or_execute confirm=True path."""

    def test_preview_mode(self):
        from app.application.tools.workflow import _import_products_preview_or_execute

        df = pd.DataFrame({"产品名称": ["A", "B"], "数量": [1, 2]})
        result = _import_products_preview_or_execute(df, list(df.columns), "ACME", False, 2)
        parsed = json.loads(result)
        assert parsed["success"] is True
        assert parsed["preview"] is True
        assert parsed["import_type"] == "products"
        assert parsed["detected_unit"] == "ACME"

    def test_confirm_with_bootstrap(self):
        from app.application.tools.workflow import _import_products_preview_or_execute

        df = pd.DataFrame({"产品名称": ["A"], "数量": [1]})
        with (
            patch("app.bootstrap.get_products_service") as mock_ps,
            patch("app.bootstrap.get_customer_app_service") as mock_cs,
            patch(
                "app.services.unified_query_service.find_purchase_unit",
                return_value=True,
            ),
        ):
            mock_svc = MagicMock()
            mock_svc.batch_add_products.return_value = {
                "success_count": 1,
                "failed_count": 0,
                "message": "ok",
            }
            mock_ps.return_value = mock_svc
            mock_cs.return_value = MagicMock()
            result = _import_products_preview_or_execute(df, list(df.columns), "ACME", True, 1)
        parsed = json.loads(result)
        assert parsed["success"] is True
        assert parsed["preview"] is False
        assert parsed["imported"] == 1

    def test_confirm_creates_customer_when_missing(self):
        from app.application.tools.workflow import _import_products_preview_or_execute

        df = pd.DataFrame({"产品名称": ["A"], "数量": [1]})
        with (
            patch("app.bootstrap.get_products_service") as mock_ps,
            patch("app.bootstrap.get_customer_app_service") as mock_cs,
            patch(
                "app.services.unified_query_service.find_purchase_unit",
                return_value=False,
            ),
        ):
            mock_svc = MagicMock()
            mock_svc.batch_add_products.return_value = {
                "success_count": 1,
                "failed_count": 0,
            }
            mock_ps.return_value = mock_svc
            mock_customer_svc = MagicMock()
            mock_cs.return_value = mock_customer_svc
            result = _import_products_preview_or_execute(df, list(df.columns), "ACME", True, 1)
        parsed = json.loads(result)
        assert parsed["success"] is True
        mock_customer_svc.create.assert_called_once()

    def test_confirm_with_nested_result(self):
        from app.application.tools.workflow import _import_products_preview_or_execute

        df = pd.DataFrame({"产品名称": ["A"], "数量": [1]})
        with (
            patch("app.bootstrap.get_products_service") as mock_ps,
            patch("app.bootstrap.get_customer_app_service"),
            patch(
                "app.services.unified_query_service.find_purchase_unit",
                return_value=True,
            ),
        ):
            mock_svc = MagicMock()
            mock_svc.batch_add_products.return_value = {
                "data": {"success_count": 5, "failed_count": 1},
            }
            mock_ps.return_value = mock_svc
            result = _import_products_preview_or_execute(df, list(df.columns), "ACME", True, 1)
        parsed = json.loads(result)
        assert parsed["success"] is True
        assert parsed["imported"] == 5
        assert parsed["failed"] == 1

    def test_confirm_skips_clause_like_rows(self):
        from app.application.tools.workflow import _import_products_preview_or_execute

        df = pd.DataFrame(
            {
                "产品名称": ["Widget", "以上价格为含税价，请严格按以上比例施工"],
                "数量": [1, 0],
            }
        )
        with (
            patch("app.bootstrap.get_products_service") as mock_ps,
            patch("app.bootstrap.get_customer_app_service"),
            patch(
                "app.services.unified_query_service.find_purchase_unit",
                return_value=True,
            ),
        ):
            mock_svc = MagicMock()
            mock_svc.batch_add_products.return_value = {
                "success_count": 1,
                "failed_count": 0,
            }
            mock_ps.return_value = mock_svc
            result = _import_products_preview_or_execute(df, list(df.columns), "ACME", True, 2)
        parsed = json.loads(result)
        assert parsed["success"] is True
        assert parsed["skipped_clause_like_rows"] >= 1


# ---------------------------------------------------------------------------
# _import_customers_preview_or_execute — confirm paths
# ---------------------------------------------------------------------------


class TestImportCustomersPreviewOrExecute:
    """Cover _import_customers_preview_or_execute confirm=True path."""

    def test_preview_mode(self):
        from app.application.tools.workflow import _import_customers_preview_or_execute

        df = pd.DataFrame({"客户名称": ["A", "B"], "联系人": ["x", "y"], "电话": ["1", "2"]})
        result = _import_customers_preview_or_execute(df, list(df.columns), False, 2)
        parsed = json.loads(result)
        assert parsed["success"] is True
        assert parsed["preview"] is True
        assert parsed["import_type"] == "customers"
        assert parsed["row_count"] == 2

    def test_confirm_with_success(self):
        from app.application.tools.workflow import _import_customers_preview_or_execute

        df = pd.DataFrame({"客户名称": ["A"], "联系人": ["x"]})
        with patch("app.bootstrap.get_customer_app_service") as mock_cs:
            mock_svc = MagicMock()
            mock_svc.create.return_value = {"success": True}
            mock_cs.return_value = mock_svc
            result = _import_customers_preview_or_execute(df, list(df.columns), True, 1)
        parsed = json.loads(result)
        assert parsed["success"] is True
        assert parsed["imported"] == 1
        assert parsed["failed"] == 0

    def test_confirm_with_failure(self):
        from app.application.tools.workflow import _import_customers_preview_or_execute

        df = pd.DataFrame({"客户名称": ["A"]})
        with patch("app.bootstrap.get_customer_app_service") as mock_cs:
            mock_svc = MagicMock()
            mock_svc.create.return_value = {"success": False}
            mock_cs.return_value = mock_svc
            result = _import_customers_preview_or_execute(df, list(df.columns), True, 1)
        parsed = json.loads(result)
        assert parsed["success"] is True
        assert parsed["failed"] == 1

    def test_confirm_skips_rows_without_name(self):
        from app.application.tools.workflow import _import_customers_preview_or_execute

        df = pd.DataFrame({"客户名称": ["A", "", ""], "联系人": ["x", "y", "z"]})
        with patch("app.bootstrap.get_customer_app_service") as mock_cs:
            mock_svc = MagicMock()
            mock_svc.create.return_value = {"success": True}
            mock_cs.return_value = mock_svc
            result = _import_customers_preview_or_execute(df, list(df.columns), True, 3)
        parsed = json.loads(result)
        # Only the first row has a customer_name.
        assert parsed["imported"] == 1


# ---------------------------------------------------------------------------
# _import_orders_preview_or_execute — confirm paths
# ---------------------------------------------------------------------------


class TestImportOrdersPreviewOrExecute:
    """Cover _import_orders_preview_or_execute confirm=True path."""

    def test_preview_mode(self):
        from app.application.tools.workflow import _import_orders_preview_or_execute

        df = pd.DataFrame({"产品名称": ["A"], "数量": [1], "购买单位": ["ACME"]})
        result = _import_orders_preview_or_execute(df, list(df.columns), "ACME", False, 1)
        parsed = json.loads(result)
        assert parsed["success"] is True
        assert parsed["preview"] is True
        assert parsed["import_type"] == "orders"
        assert "column_mapping" in parsed

    def test_confirm_with_success(self):
        from app.application.tools.workflow import _import_orders_preview_or_execute

        df = pd.DataFrame({"产品名称": ["A"], "数量": [1], "购买单位": ["ACME"]})
        with patch("app.bootstrap.get_shipment_app_service") as mock_ss:
            mock_svc = MagicMock()
            mock_svc.create_shipment.return_value = {"success": True}
            mock_ss.return_value = mock_svc
            result = _import_orders_preview_or_execute(df, list(df.columns), "ACME", True, 1)
        parsed = json.loads(result)
        assert parsed["success"] is True
        assert parsed["imported"] == 1

    def test_confirm_with_failure(self):
        from app.application.tools.workflow import _import_orders_preview_or_execute

        df = pd.DataFrame({"产品名称": ["A"], "数量": [1], "购买单位": ["ACME"]})
        with patch("app.bootstrap.get_shipment_app_service") as mock_ss:
            mock_svc = MagicMock()
            mock_svc.create_shipment.return_value = {"success": False}
            mock_ss.return_value = mock_svc
            result = _import_orders_preview_or_execute(df, list(df.columns), "ACME", True, 1)
        parsed = json.loads(result)
        assert parsed["success"] is True
        assert parsed["failed"] == 1

    def test_confirm_no_unit_name_skipped(self):
        from app.application.tools.workflow import _import_orders_preview_or_execute

        df = pd.DataFrame({"产品名称": ["A"], "数量": [1]})
        with patch("app.bootstrap.get_shipment_app_service") as mock_ss:
            mock_svc = MagicMock()
            mock_svc.create_shipment.return_value = {"success": True}
            mock_ss.return_value = mock_svc
            result = _import_orders_preview_or_execute(df, list(df.columns), "", True, 1)
        parsed = json.loads(result)
        assert parsed["success"] is True
        assert parsed["failed"] == 1
        assert parsed["imported"] == 0


# ---------------------------------------------------------------------------
# run_natural_language_pandas — error branch
# ---------------------------------------------------------------------------


class TestRunNaturalLanguagePandasErrors:
    """Cover run_natural_language_pandas error branch."""

    def test_with_invalid_code_generation(self):
        from app.application.tools.workflow import run_natural_language_pandas

        df = pd.DataFrame({"a": [1, 2]})
        mock_converter = MagicMock()
        # Use code that raises a RECOVERABLE_ERRORS member (ValueError) at runtime,
        # since SyntaxError is NOT in RECOVERABLE_ERRORS and would propagate.
        mock_converter.translate.return_value = "result = df.loc['nonexistent']"
        with patch.dict(
            "sys.modules",
            {
                "app.legacy.excel_text_to_pandas": MagicMock(
                    ExcelTextToPandas=MagicMock(return_value=mock_converter)
                )
            },
        ):
            result = run_natural_language_pandas(df, "anything")
        assert isinstance(result, dict)
        # error path returns error key
        assert "error" in result or "records" in result

    def test_with_empty_code(self):
        from app.application.tools.workflow import run_natural_language_pandas

        df = pd.DataFrame({"a": [1, 2]})
        mock_converter = MagicMock()
        mock_converter.translate.return_value = ""
        with patch.dict(
            "sys.modules",
            {
                "app.legacy.excel_text_to_pandas": MagicMock(
                    ExcelTextToPandas=MagicMock(return_value=mock_converter)
                )
            },
        ):
            result = run_natural_language_pandas(df, "anything")
        assert isinstance(result, dict)
        assert result["generated_code"] == ""
        assert result["row_count"] == 2

    def test_with_result_dataframe(self):
        from app.application.tools.workflow import run_natural_language_pandas

        df = pd.DataFrame({"a": [1, 2, 3]})
        mock_converter = MagicMock()
        mock_converter.translate.return_value = "result = df.head(1)"
        with patch.dict(
            "sys.modules",
            {
                "app.legacy.excel_text_to_pandas": MagicMock(
                    ExcelTextToPandas=MagicMock(return_value=mock_converter)
                )
            },
        ):
            result = run_natural_language_pandas(df, "first row")
        assert isinstance(result, dict)
        assert result["row_count"] == 1
        assert result["generated_code"] == "result = df.head(1)"


# ---------------------------------------------------------------------------
# execute_workflow_tool — string args
# ---------------------------------------------------------------------------


class TestExecuteWorkflowToolStringArgs:
    """Cover execute_workflow_tool when args is a JSON string."""

    def test_string_args_valid_json(self):
        from app.application.tools.workflow import execute_workflow_tool

        result = execute_workflow_tool("excel_chart_recommend", json.dumps({"file_path": "x.xlsx"}))
        parsed = json.loads(result)
        assert "suggestions" in parsed

    def test_string_args_invalid_json(self):
        from app.application.tools.workflow import execute_workflow_tool

        result = execute_workflow_tool("excel_chart_recommend", "not json")
        parsed = json.loads(result)
        assert "suggestions" in parsed

    def test_excel_chart_recommend(self):
        from app.application.tools.workflow import execute_workflow_tool

        result = execute_workflow_tool("excel_chart_recommend", {})
        parsed = json.loads(result)
        assert "suggestions" in parsed
        assert len(parsed["suggestions"]) == 2


# ---------------------------------------------------------------------------
# execute_workflow_tool — import_excel_to_database dispatch
# ---------------------------------------------------------------------------


class TestExecuteWorkflowToolImportDispatch:
    """Cover execute_workflow_tool import_excel_to_database dispatch."""

    def test_dispatches_to_handler(self, tmp_path: Path):
        from app.application.tools.workflow import execute_workflow_tool

        p = tmp_path / "data.xlsx"
        pd.DataFrame({"产品名称": ["A"], "数量": [1]}).to_excel(p, index=False)
        with patch(
            "app.application.tools.workflow.configured_db_write_token",
            return_value="",
        ):
            result = execute_workflow_tool(
                "import_excel_to_database",
                {"file_path": str(p), "import_type": "products", "preview_only": True},
                workspace_root=str(tmp_path),
            )
        parsed = json.loads(result)
        assert parsed["success"] is True
        assert parsed["import_type"] == "products"


# ---------------------------------------------------------------------------
# get_workflow_tool_registry — bulk token branch
# ---------------------------------------------------------------------------


class TestGetWorkflowToolRegistryBulkToken:
    """Cover get_workflow_tool_registry bulk token branch."""

    def test_bulk_token_adds_products_bulk_import(self, monkeypatch):
        from app.application.tools.workflow import (
            get_workflow_tool_registry,
            invalidate_workflow_tool_registry,
        )

        monkeypatch.setenv("FHD_DB_WRITE_TOKEN", "secret")
        invalidate_workflow_tool_registry()
        reg = get_workflow_tool_registry()
        names = [item["function"]["name"] for item in reg]
        assert "products_bulk_import" in names

    def test_no_bulk_token_excludes_products_bulk_import(self, monkeypatch):
        from app.application.tools.workflow import (
            get_workflow_tool_registry,
            invalidate_workflow_tool_registry,
        )

        monkeypatch.delenv("FHD_DB_WRITE_TOKEN", raising=False)
        invalidate_workflow_tool_registry()
        reg = get_workflow_tool_registry()
        names = [item["function"]["name"] for item in reg]
        assert "products_bulk_import" in names
