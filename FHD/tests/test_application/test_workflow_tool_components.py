"""Workflow dispatch precedence and the boundary between preview and writes."""

from __future__ import annotations

import json
from copy import deepcopy
from unittest.mock import Mock

import pandas as pd
import pytest

from app.application.tools import workflow


@pytest.fixture
def dispatch_ports(monkeypatch):
    from app.application import employee_pack_runner
    from app.mod_sdk import employee_tool_registry, planner_native_tools
    from app.services import tools_workflow_registered

    ports = {
        "employee_match": Mock(return_value=False),
        "employee": Mock(return_value="employee"),
        "native": Mock(return_value=(None, None)),
        "legacy": Mock(return_value=None),
        "registered": Mock(return_value={"source": "registered"}),
        "analysis": Mock(return_value={"source": "analysis"}),
        "business": Mock(return_value=None),
        "crud": Mock(return_value=None),
    }
    monkeypatch.setattr(employee_tool_registry, "is_employee_tool", ports["employee_match"])
    monkeypatch.setattr(employee_tool_registry, "execute_employee_tool", ports["employee"])
    monkeypatch.setattr(planner_native_tools, "try_execute_native_planner_tool", ports["native"])
    monkeypatch.setattr(employee_pack_runner, "try_execute_employee_planner_tool", ports["legacy"])
    monkeypatch.setattr(
        tools_workflow_registered, "execute_registered_workflow_tool", ports["registered"]
    )
    monkeypatch.setattr(workflow, "handle_excel_analysis", ports["analysis"])
    monkeypatch.setattr(workflow, "try_execute_business_db_tool", ports["business"])
    monkeypatch.setattr(workflow, "_resolve_new_tool_dispatch", ports["crud"])
    return ports


def test_registered_capability_preserves_runtime_authorization_identity(
    monkeypatch, dispatch_ports
):
    authorization = object()
    runtime = {"tenant_id": "tenant-a", "_mod_authorization": authorization}
    args = {"capability": "orders.read"}
    registered = Mock(return_value="capability-result")
    monkeypatch.setattr(workflow, "execute_registered_capability", registered)

    result = workflow.execute_workflow_tool(
        workflow.ERP_CAPABILITY_TOOL_NAME, args, "/workspace/a", runtime_context=runtime
    )

    assert result == "capability-result"
    assert registered.call_args.args[0] is args
    assert registered.call_args.kwargs["runtime_context"] is runtime
    assert registered.call_args.kwargs["runtime_context"]["_mod_authorization"] is authorization
    assert registered.call_args.kwargs["workspace_root"] == "/workspace/a"
    for port in dispatch_ports.values():
        port.assert_not_called()


@pytest.mark.parametrize("owner", ["employee", "native", "legacy"])
def test_empty_extension_result_is_handled_without_fallback(owner, dispatch_ports):
    if owner == "employee":
        dispatch_ports["employee_match"].return_value = True
        dispatch_ports["employee"].return_value = ""
    elif owner == "native":
        dispatch_ports["native"].return_value = ("", "native-mod")
    else:
        dispatch_ports["legacy"].return_value = ""

    result = workflow.execute_workflow_tool("excel_analysis", {}, "/workspace/a")

    assert result == ""
    dispatch_ports["analysis"].assert_not_called()
    dispatch_ports["business"].assert_not_called()
    dispatch_ports["crud"].assert_not_called()
    if owner == "employee":
        dispatch_ports["native"].assert_not_called()
    if owner in {"employee", "native"}:
        dispatch_ports["legacy"].assert_not_called()


def test_native_mod_failure_does_not_execute_legacy_or_builtin(dispatch_ports):
    failure = {"success": False, "error": "mod_execution_failed", "mod_id": "tenant-mod"}
    dispatch_ports["native"].return_value = (json.dumps(failure), "tenant-mod")

    result = workflow.execute_workflow_tool("excel_analysis", {}, db_write_token="write-token")

    assert json.loads(result) == failure
    assert dispatch_ports["native"].call_args.kwargs["db_write_token"] == "write-token"
    dispatch_ports["legacy"].assert_not_called()
    dispatch_ports["analysis"].assert_not_called()


def test_recoverable_extension_failures_preserve_ordered_builtin_fallback(dispatch_ports):
    calls = []

    def fail(stage):
        def invoke(*args, **kwargs):
            calls.append(stage)
            raise RuntimeError(stage)

        return invoke

    for name in ("employee_match", "native", "legacy"):
        dispatch_ports[name].side_effect = fail(name)
    dispatch_ports["analysis"].side_effect = lambda *a, **kw: (
        calls.append("analysis") or {"ok": True}
    )

    assert json.loads(workflow.execute_workflow_tool("excel_analysis", {})) == {"ok": True}
    assert calls == ["employee_match", "native", "legacy", "analysis"]
    dispatch_ports["business"].assert_not_called()


def test_template_registration_precedes_legacy_employee(dispatch_ports):
    args = {"action": "create", "file_path": "quote.xlsx"}

    assert json.loads(workflow.execute_workflow_tool("template_preview", args)) == {
        "source": "registered"
    }
    dispatch_ports["registered"].assert_called_once_with("template_preview", "create", args)
    dispatch_ports["legacy"].assert_not_called()


@pytest.mark.parametrize("raw_args", ["invalid-json", "[]", "null", "42"])
def test_non_object_arguments_are_normalized_before_business_dispatch(raw_args, dispatch_ports):
    dispatch_ports["business"].return_value = {"success": True, "source": "business"}

    assert json.loads(workflow.execute_workflow_tool("business_db_read", raw_args)) == {
        "success": True,
        "source": "business",
    }
    dispatch_ports["business"].assert_called_once_with("business_db_read", {})
    dispatch_ports["crud"].assert_not_called()


@pytest.mark.parametrize("import_type", ["products", "customers", "orders"])
def test_preview_reads_selected_rows_without_instantiating_any_writer(
    import_type, tmp_path, monkeypatch
):
    from app import bootstrap
    from app.services import unified_query_service

    df = pd.DataFrame(
        {"产品名称": ["涂料 A", "涂料 B"], "客户名称": ["客户甲", "客户乙"], "数量": [2, 3]}
    )
    path = tmp_path / "source.xlsx"
    df.to_excel(path, sheet_name="报价", startrow=2, index=False)
    writers = []
    for name in ("get_customer_app_service", "get_products_service", "get_shipment_app_service"):
        factory = Mock(side_effect=AssertionError("preview must not construct a writer"))
        monkeypatch.setattr(bootstrap, name, factory)
        writers.append(factory)
    lookup = Mock(side_effect=AssertionError("preview must not access customer persistence"))
    monkeypatch.setattr(unified_query_service, "find_purchase_unit", lookup)
    args = {
        "file_path": "source.xlsx",
        "import_type": import_type,
        "preview_only": True,
        "confirm": True,
        "header_row": 3,
        "last_data_row_1based": 4,
        "context": {
            "excel_analysis_selected_sheet": {"sheet_name": "报价"},
            "preferred_sheet_name": "must-not-read",
            "excel_customer_hint": "客户甲",
        },
    }
    original = deepcopy(args)

    result = json.loads(workflow._handle_import_excel_to_database(args, str(tmp_path)))

    assert result["success"] is True
    assert result["preview"] is True
    assert result["import_type"] == import_type
    assert result["row_count"] == 1
    assert len(result["sample_data"]) == 1
    assert args == original
    for writer in writers:
        writer.assert_not_called()
    lookup.assert_not_called()
    if import_type == "products":
        assert result["detected_unit"] == "客户甲"
        assert result["read_options"] == {
            "sheet_name": "报价",
            "header_row": 3,
            "last_data_row_applied": 4,
        }


def test_registry_cache_rebuilds_current_employee_tools_without_accumulation(monkeypatch):
    from app.mod_sdk import employee_tool_registry

    monkeypatch.setattr(workflow, "_workflow_tool_registry_cache", None)
    monkeypatch.setattr(workflow, "_workflow_tool_registry_bulk_token_present", None)
    monkeypatch.setattr(workflow, "_workflow_registry_cache_ver", None)
    monkeypatch.setattr(workflow, "_WORKFLOW_REG_VER", 3)
    monkeypatch.setattr(workflow, "_base_registry", lambda: [{"function": {"name": "base"}}])
    monkeypatch.setattr(workflow, "extend_workflow_tool_registry", lambda specs: specs)
    employees = Mock(
        side_effect=[[{"function": {"name": "employee-a"}}], [{"function": {"name": "employee-b"}}]]
    )
    invalidate = Mock()
    monkeypatch.setattr(employee_tool_registry, "build_employee_pack_tool_definitions", employees)
    monkeypatch.setattr(employee_tool_registry, "invalidate_employee_tool_cache", invalidate)

    first = workflow.get_workflow_tool_registry()
    assert workflow.get_workflow_tool_registry() is first
    workflow.invalidate_workflow_tool_registry()
    second = workflow.get_workflow_tool_registry()

    assert second is not first
    assert [tool["function"]["name"] for tool in first] == [
        "base",
        "employee-a",
        "products_bulk_import",
    ]
    assert [tool["function"]["name"] for tool in second] == [
        "base",
        "employee-b",
        "products_bulk_import",
    ]
    assert employees.call_count == 2
    invalidate.assert_called_once_with()


@pytest.mark.parametrize("tool_name", ["excel_schema_understand", "excel_analysis"])
def test_json_output_preserves_each_tools_error_boundary(
    tool_name, dispatch_ports, monkeypatch, tmp_path
):
    path = tmp_path / "source.xlsx"
    path.touch()
    circular = {}
    circular["self"] = circular
    schema = Mock()
    schema.understand_dataframe.return_value = circular
    monkeypatch.setattr(workflow, "ExcelSchemaUnderstandingService", Mock(return_value=schema))
    monkeypatch.setattr(workflow, "_read_excel_dataframe", Mock(return_value=pd.DataFrame()))
    dispatch_ports["analysis"].return_value = circular

    if tool_name == "excel_analysis":
        with pytest.raises(ValueError, match="Circular reference"):
            workflow.execute_workflow_tool(tool_name, {"file_path": str(path)})
    else:
        result = json.loads(workflow.execute_workflow_tool(tool_name, {"file_path": str(path)}))
        assert result == {
            "success": False,
            "error": "read_excel_failed",
            "message": "读取 Excel 文件失败，请检查文件后重试",
        }
