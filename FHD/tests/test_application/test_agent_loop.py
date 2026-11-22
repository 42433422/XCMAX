"""Employee tool-catalog compatibility retained by the fixed Codex entry."""

from unittest.mock import patch

from app.application.employee_runtime.agent_loop import default_employee_tools


class TestDefaultEmployeeTools:
    @patch("app.application.tools.workflow.get_workflow_tool_registry", return_value=None)
    def test_none_registry_returns_empty(self, mock_reg):
        result = default_employee_tools()
        assert result == []

    @patch("app.mod_sdk.employee_tool_registry.is_employee_tool", return_value=True)
    @patch("app.application.tools.workflow.get_workflow_tool_registry")
    def test_filters_employee_tools(self, mock_reg, mock_is_emp):
        spec = {"function": {"name": "employee_tool"}}
        mock_reg.return_value = [spec]
        result = default_employee_tools()
        assert len(result) == 0

    @patch("app.mod_sdk.employee_tool_registry.is_employee_tool", return_value=False)
    @patch("app.application.tools.workflow.get_workflow_tool_registry")
    def test_keeps_non_employee_tools(self, mock_reg, mock_is_emp):
        spec = {"function": {"name": "normal_tool"}}
        mock_reg.return_value = [spec]
        result = default_employee_tools()
        assert len(result) == 1

    @patch(
        "app.application.tools.workflow.get_workflow_tool_registry",
        side_effect=ImportError("no module"),
    )
    def test_import_error_returns_empty(self, mock_reg):
        result = default_employee_tools()
        assert result == []
