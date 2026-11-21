"""Workflow composition and the retained spreadsheet analysis contract."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest


def _assert_shared_json_string_args_parsed_0(self, _shared_literal_0):
    with (
        patch(
            "app.mod_sdk.employee_tool_registry.is_employee_tool", return_value=False, create=True
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
        result = self._call("excel_chart_recommend", _shared_literal_0)
    data = json.loads(result)
    assert data["error_code"] == "unknown_tool"
    assert data["execution_status"] == "not_started"


class TestParseExcelHeaderRow1based:
    def _call(self, args):
        from app.application.tools.workflow import _parse_excel_header_row_1based

        return _parse_excel_header_row_1based(args)

    def test_returns_none_when_missing(self):
        assert self._call({}) is None

    def test_returns_none_when_empty_string(self):
        assert self._call({"header_row": ""}) is None

    def test_returns_none_for_zero(self):
        assert self._call({"header_row": 0}) is None

    def test_returns_int_for_positive(self):
        assert self._call({"header_row": 3}) == 3

    def test_falls_back_to_header_row_index(self):
        assert self._call({"header_row_index": 2}) == 2

    def test_returns_none_for_non_int_string(self):
        assert self._call({"header_row": "abc"}) is None


class TestExecuteWorkflowTool:
    def _call(self, name, args, workspace_root=None, db_write_token=None):
        from app.application.tools.workflow import execute_workflow_tool

        return execute_workflow_tool(name, args, workspace_root, db_write_token=db_write_token)

    def test_json_string_args_parsed(self):
        return _assert_shared_json_string_args_parsed_0(self, '{"file_path": "x.xlsx"}')

    def test_malformed_json_string_defaults_to_empty(self):
        return _assert_shared_json_string_args_parsed_0(self, "{not valid")

    def test_employee_tool_dispatched(self):
        with (
            patch(
                "app.mod_sdk.employee_tool_registry.is_employee_tool",
                return_value=True,
                create=True,
            ),
            patch(
                "app.mod_sdk.employee_tool_registry.execute_employee_tool",
                return_value='{"ok": true}',
                create=True,
            ),
        ):
            result = self._call("my_emp_tool", {})
        assert result == '{"ok": true}'

    def test_native_planner_tool_returned(self):
        with (
            patch(
                "app.mod_sdk.employee_tool_registry.is_employee_tool",
                return_value=False,
                create=True,
            ),
            patch(
                "app.mod_sdk.planner_native_tools.try_execute_native_planner_tool",
                return_value=('{"native": 1}', None),
                create=True,
            ),
        ):
            result = self._call("some_native", {})
        assert "native" in result

    def test_excel_analysis_dispatched(self, tmp_path):
        """excel_analysis name hits handle_excel_analysis."""
        (tmp_path / "data.xlsx").touch()
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
                "app.application.tools.workflow.handle_excel_analysis",
                return_value={"success": False, "error": "mocked"},
            ),
        ):
            result = self._call("excel_analysis", {"file_path": "data.xlsx"})
        data = json.loads(result)
        assert data["success"] is False

    def test_excel_chart_recommend(self):
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
            result = self._call("excel_chart_recommend", {})
        data = json.loads(result)
        assert data["error_code"] == "unknown_tool"
        assert data["execution_status"] == "not_started"

    def test_employee_registry_error_stops_dispatch(self):
        with (
            patch(
                "app.mod_sdk.employee_tool_registry.is_employee_tool",
                side_effect=ImportError("no"),
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
            result = self._call("excel_chart_recommend", {})
        data = json.loads(result)
        assert data["execution_state"] == "unknown"
        assert data["retryable"] is False

    def test_template_preview_dispatched(self):
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
                "app.application.tools.registered_capabilities.execute_registered_capability",
                return_value='{"result":"ok"}',
            ) as dispatch,
        ):
            result = self._call("template_preview", {"action": "view"})
            dispatch.assert_called_once_with(
                {"tool_id": "template_preview", "action": "view", "params": {"action": "view"}},
                workspace_root=None,
                runtime_context=None,
            )
        data = json.loads(result)
        assert "result" in data
