"""Canonical employee workbook actions use real operations and owned input snapshots."""

from contextlib import contextmanager
from unittest.mock import Mock

import pandas as pd
import pytest

from app.application.employee_runtime.agent_runner import _codex_employee_tool_scope
from app.application.employee_runtime.workspace_guard import build_employee_gate
from app.application.tools.workflow_tools.catalog_excel import excel_tool_specs
from app.domain.shared_services.tools_workflow_excel_ocr import (
    _registered_router_excel_analysis,
    _registered_router_excel_join_compare,
)


@pytest.fixture
def owned_workbooks(tmp_path, monkeypatch):
    paths = {name: tmp_path / name for name in ("left.xlsx", "right.xlsx")}
    pd.DataFrame({"id": [1, 2], "amount": [10, 20]}).to_excel(paths["left.xlsx"], index=False)
    pd.DataFrame({"id": [1, 2], "amount": [10, 25]}).to_excel(paths["right.xlsx"], index=False)
    opened = []

    @contextmanager
    def snapshot(name, context):
        assert context["_actor_authorization"] == "trusted boundary"
        if name not in paths:
            raise PermissionError("文件不属于当前账号")
        opened.append(name)
        yield paths[name]

    monkeypatch.setattr(
        "app.application.tools.workflow_spreadsheet_scope.workflow_file_snapshot", snapshot
    )
    return opened, {"_actor_authorization": "trusted boundary"}


def test_aggregate_and_structure_return_observed_workbook_data(owned_workbooks):
    opened, context = owned_workbooks
    aggregate = _registered_router_excel_analysis(
        "aggregate",
        {"file_path": "left.xlsx", "metrics": [{"column": "amount", "op": "sum"}]},
        context,
        "shared",
        "汇总金额",
    )
    assert aggregate["success"] is True
    assert aggregate["records"] == [{"amount_sum": 30}]
    structure = _registered_router_excel_analysis(
        "structure", {"file_path": "left.xlsx"}, context, "shared", "结构"
    )
    assert structure["success"] is True
    assert structure["data"]["row_count"] == 2
    assert structure["data"]["columns"] == ["id", "amount"]
    assert "llm_understanding" not in structure
    assert structure["file_path"] == "left.xlsx"
    assert opened == ["left.xlsx", "left.xlsx"]


def test_join_and_diff_open_both_inputs_and_use_the_registered_operation(owned_workbooks):
    opened, context = owned_workbooks
    joined = _registered_router_excel_join_compare(
        "join",
        {"file_paths": ["left.xlsx", "right.xlsx"], "join_keys": ["id"]},
        context,
        "shared",
        "合并",
    )
    assert joined["success"] is True and joined["row_count"] == 2
    diff = _registered_router_excel_join_compare(
        "diff",
        {"file_path_a": "left.xlsx", "file_path_b": "right.xlsx", "key_columns": ["id"]},
        context,
        "shared",
        "比较",
    )
    assert diff["success"] is True and diff["rows_with_value_changes"] == {"count": 1}
    assert opened == ["left.xlsx", "right.xlsx", "left.xlsx", "right.xlsx"]


def test_foreign_workbook_is_rejected_before_legacy_file_reader(owned_workbooks, monkeypatch):
    _, context = owned_workbooks
    read = Mock()
    monkeypatch.setattr("app.application.tools.workflow.execute_workflow_tool", read)
    denied = _registered_router_excel_join_compare(
        "diff",
        {"file_path_a": "left.xlsx", "file_path_b": "foreign.xlsx", "key_columns": ["id"]},
        context,
        "shared",
        "比较",
    )
    assert denied["error_code"] == "spreadsheet_access_denied"
    read.assert_not_called()


def test_diff_and_schema_alias_keep_employee_forbidden_paths(tmp_path):
    declared = [
        tool
        for tool in excel_tool_specs()
        if tool["function"]["name"] in {"excel_schema_understand", "excel_join_compare"}
    ]
    gate = build_employee_gate(
        "clerk", {}, {"workspace_policy": {"forbidden_globs": ["secret/**"]}}, str(tmp_path)
    )
    _, check = _codex_employee_tool_scope(declared, gate)
    assert check("excel_analysis", "structure", {"file_path": "secret/input.xlsx"})["ok"] is False
    assert (
        check(
            "excel_join_compare",
            "diff",
            {"file_path_a": "public/a.xlsx", "file_path_b": "secret/b.xlsx", "key_columns": ["id"]},
        )["ok"]
        is False
    )
    assert (
        check(
            "excel_join_compare",
            "diff",
            {"file_path_a": "public/a.xlsx", "file_path_b": "public/b.xlsx", "key_columns": ["id"]},
        )["ok"]
        is True
    )
