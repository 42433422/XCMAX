"""Workflow composition and the retained spreadsheet analysis contract."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from app.application.tools.workflow import (
    _read_excel_dataframe,
    execute_workflow_tool,
    handle_excel_analysis,
    invalidate_workflow_tool_registry,
)
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


def _write_excel_fixture(path, frame, *, sheet_name="Sheet1", header_row=1):
    frame.to_excel(
        path, engine="openpyxl", sheet_name=sheet_name, index=False, startrow=header_row - 1
    )


class TestHandleExcelAnalysis:
    """handle_excel_analysis 分支覆盖。"""

    def test_missing_file_path_returns_error(self) -> None:
        result = handle_excel_analysis({})
        assert result["success"] is False
        assert "file_path" in result["error"]

    def test_resolve_path_error_returns_error(self) -> None:
        with patch(
            "app.application.tools.workflow.resolve_safe_excel_path",
            side_effect=OSError("denied"),
        ):
            result = handle_excel_analysis({"file_path": "x.xlsx"})
        assert result["success"] is False
        assert result["error"] == "invalid_excel_path"
        assert "denied" not in result["error"]

    def test_file_not_found_returns_error(self, tmp_path: Path) -> None:
        result = handle_excel_analysis({"file_path": "missing.xlsx"}, workspace_root=str(tmp_path))
        assert result["success"] is False
        assert result["error"] == "file not found"

    def test_read_failed_returns_error(self, tmp_path: Path) -> None:
        f = tmp_path / "data.xlsx"
        _write_excel_fixture(f, pd.DataFrame({"a": [1]}))
        with patch(
            "app.application.tools.workflow._read_excel_dataframe",
            side_effect=OSError("read fail"),
        ) as read:
            result = handle_excel_analysis(
                {"file_path": "data.xlsx", "action": "read"}, workspace_root=str(tmp_path)
            )
        assert result["success"] is False
        assert result["error"] == "read_excel_failed"
        read.assert_called_once()

    def test_action_query_uses_expression(self, tmp_path: Path) -> None:
        f = tmp_path / "data.xlsx"
        df = pd.DataFrame({"a": [1, 2]})
        _write_excel_fixture(f, df)
        with patch("app.application.tools.workflow._read_excel_dataframe", return_value=df):
            result = handle_excel_analysis(
                {"file_path": "data.xlsx", "action": "query", "query_expression": "a > 1"},
                workspace_root=str(tmp_path),
            )
        assert result["success"] is True
        assert result["action"] == "query"
        assert result["records"] == [{"a": 2}]

    def test_action_read_with_customer_hint(self, tmp_path: Path) -> None:
        f = tmp_path / "data.xlsx"
        df = pd.DataFrame({"a": [1, 2]})
        _write_excel_fixture(f, df)
        with (
            patch("app.application.tools.workflow._read_excel_dataframe", return_value=df),
            patch(
                "app.application.template_grid_core._extract_customer_hint_from_excel",
                return_value="客户A",
                create=True,
            ),
        ):
            result = handle_excel_analysis(
                {"file_path": "data.xlsx", "action": "read"}, workspace_root=str(tmp_path)
            )
        assert result["success"] is True
        assert result["customer_hint"] == "客户A"
        assert result["action"] == "read"

    def test_action_read_customer_hint_error_swallowed(self, tmp_path: Path) -> None:
        f = tmp_path / "data.xlsx"
        df = pd.DataFrame({"a": [1, 2]})
        _write_excel_fixture(f, df)
        with (
            patch("app.application.tools.workflow._read_excel_dataframe", return_value=df),
            patch(
                "app.application.template_grid_core._extract_customer_hint_from_excel",
                side_effect=OSError("fail"),
                create=True,
            ),
        ):
            result = handle_excel_analysis(
                {"file_path": "data.xlsx", "action": "read"}, workspace_root=str(tmp_path)
            )
        assert result["success"] is True
        assert "customer_hint" not in result

    def test_action_read_with_header_row(self, tmp_path: Path) -> None:
        f = tmp_path / "data.xlsx"
        df = pd.DataFrame({"a": [1, 2]})
        _write_excel_fixture(f, df, header_row=2)
        with (
            patch("app.application.tools.workflow._read_excel_dataframe", return_value=df),
            patch(
                "app.application.template_grid_core._extract_customer_hint_from_excel",
                return_value="",
                create=True,
            ),
        ):
            result = handle_excel_analysis(
                {"file_path": "data.xlsx", "action": "read", "header_row": 2},
                workspace_root=str(tmp_path),
            )
        assert result["success"] is True
        assert result["header_row"] == 2

    def test_action_query_with_expr(self, tmp_path: Path) -> None:
        f = tmp_path / "data.xlsx"
        df = pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]})
        _write_excel_fixture(f, df)
        with patch("app.application.tools.workflow._read_excel_dataframe", return_value=df):
            result = handle_excel_analysis(
                {"file_path": "data.xlsx", "action": "query", "query_expression": "a > 1"},
                workspace_root=str(tmp_path),
            )
        assert result["success"] is True
        assert result["action"] == "query"
        assert result["row_count"] == 2

    def test_action_query_without_expr(self, tmp_path: Path) -> None:
        f = tmp_path / "data.xlsx"
        df = pd.DataFrame({"a": [1, 2, 3]})
        _write_excel_fixture(f, df)
        with patch("app.application.tools.workflow._read_excel_dataframe", return_value=df) as read:
            result = handle_excel_analysis(
                {"file_path": "data.xlsx", "action": "query"},
                workspace_root=str(tmp_path),
            )
        assert result["success"] is False
        assert result["error_code"] == "missing_query_expression"
        assert "records" not in result
        read.assert_not_called()

    def test_action_aggregate_with_metrics(self, tmp_path: Path) -> None:
        f = tmp_path / "data.xlsx"
        df = pd.DataFrame({"cat": ["a", "a", "b"], "val": [1, 2, 3]})
        _write_excel_fixture(f, df)
        with patch("app.application.tools.workflow._read_excel_dataframe", return_value=df):
            result = handle_excel_analysis(
                {
                    "file_path": "data.xlsx",
                    "action": "aggregate",
                    "group_by": ["cat"],
                    "metrics": [{"column": "val", "op": "sum"}],
                },
                workspace_root=str(tmp_path),
            )
        assert result["success"] is True
        assert result["action"] == "aggregate"

    def test_action_aggregate_with_invalid_metrics(self, tmp_path: Path) -> None:
        f = tmp_path / "data.xlsx"
        df = pd.DataFrame({"cat": ["a"], "val": [1]})
        _write_excel_fixture(f, df)
        with patch("app.application.tools.workflow._read_excel_dataframe", return_value=df) as read:
            result = handle_excel_analysis(
                {
                    "file_path": "data.xlsx",
                    "action": "aggregate",
                    "group_by": ["cat"],
                    "metrics": ["not a dict", {"column": "", "op": ""}],
                },
                workspace_root=str(tmp_path),
            )
        assert result["success"] is False
        read.assert_called_once()

    def test_action_aggregate_no_group_by(self, tmp_path: Path) -> None:
        f = tmp_path / "data.xlsx"
        df = pd.DataFrame({"a": [1]})
        _write_excel_fixture(f, df)
        with patch("app.application.tools.workflow._read_excel_dataframe", return_value=df) as read:
            result = handle_excel_analysis(
                {"file_path": "data.xlsx", "action": "aggregate"},
                workspace_root=str(tmp_path),
            )
        assert result["success"] is False
        read.assert_called_once()

    def test_action_statistics(self, tmp_path: Path) -> None:
        f = tmp_path / "data.xlsx"
        df = pd.DataFrame({"a": [1, 2, 3]})
        _write_excel_fixture(f, df)
        with patch("app.application.tools.workflow._read_excel_dataframe", return_value=df):
            result = handle_excel_analysis(
                {"file_path": "data.xlsx", "action": "statistics"},
                workspace_root=str(tmp_path),
            )
        assert result["success"] is True
        assert result["action"] == "statistics"
        assert "dtypes" in result

    def test_unsupported_action(self, tmp_path: Path) -> None:
        f = tmp_path / "data.xlsx"
        df = pd.DataFrame({"a": [1]})
        _write_excel_fixture(f, df)
        with patch("app.application.tools.workflow._read_excel_dataframe", return_value=df):
            result = handle_excel_analysis(
                {"file_path": "data.xlsx", "action": "unknown"},
                workspace_root=str(tmp_path),
            )
        assert result["success"] is False
        assert "unsupported_action" in result["error"]


class TestExecuteWorkflowToolMisc:
    """execute_workflow_tool 其它分支覆盖。"""

    def test_unknown_tool(self) -> None:
        with (
            patch(
                "app.mod_sdk.employee_tool_registry.is_employee_tool",
                return_value=False,
                create=True,
            ),
            patch(
                "app.mod_sdk.planner_native_tools.try_execute_native_planner_tool",
                return_value=(None, None),
                create=True,
            ),
            patch(
                "app.domain.app_pure.employee_pack_runner.try_execute_employee_planner_tool",
                return_value=None,
                create=True,
            ),
        ):
            result = execute_workflow_tool("totally_unknown", {})
        data = json.loads(result)
        assert data["success"] is False
        assert data["error"] == "unknown_tool"
        assert data["tool"] == "totally_unknown"

    def test_template_preview_empty_action_defaults_to_view(
        self, trusted_actor, local_tools, tmp_path, monkeypatch
    ) -> None:
        from app.application.agent_orchestrator import InMemoryAgentRunRepository
        from app.application.agent_orchestrator.tool_spec import get_tool_action_spec
        from app.application.facades.tools_facade import execute_registered_workflow_tool

        actor = trusted_actor(
            role="template-preview-reader",
            permissions=[get_tool_action_spec("template_preview", "view").permission],
        )
        monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
        monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
        repo = InMemoryAgentRunRepository()
        with (
            patch(
                "app.mod_sdk.employee_tool_registry.is_employee_tool",
                return_value=False,
                create=True,
            ),
            patch(
                "app.mod_sdk.planner_native_tools.try_execute_native_planner_tool",
                return_value=(None, None),
                create=True,
            ),
            patch(
                "app.domain.app_pure.employee_pack_runner.try_execute_employee_planner_tool",
                return_value=None,
                create=True,
            ),
            patch(
                "app.application.facades.tools_facade.execute_registered_workflow_tool",
                wraps=execute_registered_workflow_tool,
            ) as dispatch,
            patch(
                "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
                return_value=repo,
            ),
        ):
            result = execute_workflow_tool(
                "template_preview", {"action": ""}, runtime_context=actor.context
            )
        data = json.loads(result)
        assert data["capability"]["action"] == "view"
        assert data["result"]["success"] is True
        assert data["result"]["redirect"] == "/console?view=template-preview"
        run = repo.get(data["run_id"])
        assert run is not None and len(run.tool_calls) == 1
        receipt = run.tool_calls[0].output
        assert {key: data["result"][key] for key in receipt} == receipt
        assert data["result"]["agent_run_id"] == data["result"]["run_id"] == run.run_id
        assert data["result"]["agent_status"] == run.status == "completed"
        assert data["result"]["task_id"] == run.metadata["task_context"]["task_id"]
        assert data["result"]["root_run_id"] == run.run_id
        assert data["result"]["verification"]["accepted"] is True
        dispatch.assert_called_once()
        assert dispatch.call_args.args[:2] == ("template_preview", "view")
        context = dispatch.call_args.args[2]["_runtime_context"]
        assert context["user_id"] == str(actor.user_id)
        assert context["tenant_id"] == str(actor.tenant_id)

    def test_employee_planner_tool_returned(self) -> None:
        with (
            patch(
                "app.mod_sdk.employee_tool_registry.is_employee_tool",
                return_value=False,
                create=True,
            ),
            patch(
                "app.mod_sdk.planner_native_tools.try_execute_native_planner_tool",
                return_value=(None, None),
                create=True,
            ),
            patch(
                "app.domain.app_pure.employee_pack_runner.try_execute_employee_planner_tool",
                return_value='{"emp": true}',
                create=True,
            ),
        ):
            result = execute_workflow_tool("some_tool", {})
        assert "emp" in result

    def test_planner_native_tool_error_stays_unknown_without_fallback(self) -> None:
        fallback = MagicMock(return_value='{"suggestions": []}')
        with (
            patch(
                "app.mod_sdk.employee_tool_registry.is_employee_tool",
                return_value=False,
                create=True,
            ),
            patch(
                "app.mod_sdk.planner_native_tools.try_execute_native_planner_tool",
                side_effect=ImportError("no planner"),
                create=True,
            ) as native,
            patch(
                "app.domain.app_pure.employee_pack_runner.try_execute_employee_planner_tool",
                return_value=None,
                create=True,
            ) as employee,
        ):
            result = execute_workflow_tool("excel_chart_recommend", {})
        data = json.loads(result)
        assert data["success"] is False and data["retryable"] is False
        assert data["outcome"] == "unknown"
        assert data["error_code"] == "tool_execution_interrupted"
        assert data["reconciliation_required"] is True and "suggestions" not in data
        native.assert_called_once()
        employee.assert_not_called()
        fallback.assert_not_called()

    def test_employee_planner_tool_error_stays_unknown_without_fallback(self) -> None:
        fallback = MagicMock(return_value='{"suggestions": []}')
        with (
            patch(
                "app.mod_sdk.employee_tool_registry.is_employee_tool",
                return_value=False,
                create=True,
            ),
            patch(
                "app.mod_sdk.planner_native_tools.try_execute_native_planner_tool",
                return_value=(None, None),
                create=True,
            ) as native,
            patch(
                "app.domain.app_pure.employee_pack_runner.try_execute_employee_planner_tool",
                side_effect=OSError("fail"),
                create=True,
            ) as employee,
        ):
            result = execute_workflow_tool("excel_chart_recommend", {})
        data = json.loads(result)
        assert data["success"] is False and data["retryable"] is False
        assert data["outcome"] == "unknown"
        assert data["error_code"] == "tool_execution_interrupted"
        assert data["reconciliation_required"] is True and "suggestions" not in data
        native.assert_called_once()
        employee.assert_called_once()
        fallback.assert_not_called()


class TestReadExcelDataframe:
    """_read_excel_dataframe 分支覆盖。"""

    def test_xlsx_uses_openpyxl_engine(self, tmp_path: Path) -> None:
        p = tmp_path / "data.xlsx"
        df = pd.DataFrame({"a": [1]})
        _write_excel_fixture(p, df)
        with patch("pandas.read_excel", wraps=pd.read_excel) as mock_read:
            result = _read_excel_dataframe(p, sheet_name=None, header_row_1based=None)
            assert mock_read.call_args.kwargs.get("engine") == "openpyxl"
        pd.testing.assert_frame_equal(result, df)

    def test_xlsm_uses_openpyxl_engine(self, tmp_path: Path) -> None:
        p = tmp_path / "data.xlsm"
        df = pd.DataFrame({"a": [1]})
        _write_excel_fixture(p, df)
        with patch("pandas.read_excel", wraps=pd.read_excel) as mock_read:
            result = _read_excel_dataframe(p, sheet_name=None, header_row_1based=None)
            assert mock_read.call_args.kwargs.get("engine") == "openpyxl"
        pd.testing.assert_frame_equal(result, df)

    def test_sheet_name_passed(self, tmp_path: Path) -> None:
        p = tmp_path / "data.xlsx"
        df = pd.DataFrame({"a": [1]})
        _write_excel_fixture(p, df, sheet_name="Sheet2")
        with patch("pandas.read_excel", wraps=pd.read_excel) as mock_read:
            result = _read_excel_dataframe(p, sheet_name="Sheet2", header_row_1based=None)
            assert mock_read.call_args.kwargs.get("sheet_name") == "Sheet2"
        pd.testing.assert_frame_equal(result, df)

    def test_header_row_passed(self, tmp_path: Path) -> None:
        p = tmp_path / "data.xlsx"
        df = pd.DataFrame({"a": [1]})
        _write_excel_fixture(p, df, header_row=3)
        with patch("pandas.read_excel", wraps=pd.read_excel) as mock_read:
            result = _read_excel_dataframe(p, sheet_name=None, header_row_1based=3)
            assert mock_read.call_args.kwargs.get("header") == 2
        pd.testing.assert_frame_equal(result, df)

    def test_no_extra_kwargs_for_xls(self, tmp_path: Path) -> None:
        p = tmp_path / "data.xls"
        p.write_text("not excel")
        df = pd.DataFrame({"a": [1]})
        with patch("pandas.read_excel", return_value=df) as mock_read:
            _read_excel_dataframe(p, sheet_name=None, header_row_1based=None)
            assert "engine" not in mock_read.call_args.kwargs
