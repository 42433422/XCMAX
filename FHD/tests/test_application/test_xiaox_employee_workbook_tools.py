"""Canonical employee workbook actions use real operations and owned input snapshots."""

from contextlib import contextmanager
from unittest.mock import Mock

import pandas as pd
import pytest

from app.application.employee_runtime.agent_runner import _xiaox_employee_tool_scope
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
        {"file_path": "left.xlsx", "header_row": 1, "metrics": [{"column": "amount", "op": "sum"}]},
        context,
        "shared",
        "汇总金额",
    )
    assert aggregate["success"] is True
    assert aggregate["records"] == [{"amount_sum": 30}]
    structure = _registered_router_excel_analysis(
        "structure", {"file_path": "left.xlsx", "header_row": 1}, context, "shared", "结构"
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


def test_diff_and_structure_keep_employee_forbidden_paths(tmp_path):
    declared = [
        tool
        for tool in excel_tool_specs()
        if tool["function"]["name"] in {"excel_analysis", "excel_join_compare"}
    ]
    gate = build_employee_gate(
        "clerk", {}, {"workspace_policy": {"forbidden_globs": ["secret/**"]}}, str(tmp_path)
    )
    _, check = _xiaox_employee_tool_scope(declared, gate)
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


def test_native_read_pages_use_registered_snapshot_and_bind_source(owned_workbooks):
    opened, context = owned_workbooks
    args = {"file_path": "left.xlsx", "view": "sheets", "max_rows": 1}
    sheets = _registered_router_excel_analysis("read", args, context, "shared", "")
    assert sheets["success"] is True
    assert sheets["sheets"][0]["sheet"] == "Sheet1"
    args.update(view="cells", sheet_name="Sheet1", max_rows=2)
    first = _registered_router_excel_analysis("read", args, context, "shared", "")
    assert [cell["address"] for cell in first["cells"]] == ["A1", "B1"]
    assert first["has_more"] is True
    args.update(offset=first["next_offset"], expected_sha256=first["source_sha256"])
    second = _registered_router_excel_analysis("read", args, context, "shared", "")
    assert [cell["address"] for cell in second["cells"]] == ["A2", "B2"]
    assert first["document_id"] == second["document_id"]
    assert second["file_path"] == "left.xlsx"
    args.update(offset=0, cell_range="B2:B3")
    selected = _registered_router_excel_analysis("read", args, context, "shared", "")
    assert [cell["value"] for cell in selected["cells"]] == [10, 20]
    args["expected_sha256"] = "0" * 64
    stale = _registered_router_excel_analysis("read", args, context, "shared", "")
    assert stale["success"] is False
    assert "SHA-256 mismatch" in stale["message"]
    args.pop("expected_sha256")
    args["offset"] = 2
    unbound = _registered_router_excel_analysis("read", args, context, "shared", "")
    assert unbound["success"] is False
    assert "requires_source_sha256" in unbound["message"]
    assert opened == ["left.xlsx"] * 6


def test_native_paging_fields_are_discoverable_on_original_read_contract():
    from app.application.agent_orchestrator.tool_spec_data.input_schemas import (
        workbook_input_schemas,
    )

    properties = workbook_input_schemas()[("excel_analysis", "read")]["properties"]
    assert properties["view"]["enum"] == ["table", "sheets", "cells"]
    assert {"expected_sha256", "cell_range", "offset", "max_rows"} <= properties.keys()


def test_reader_contract_declares_source_and_accepts_explicit_headerless_read():
    from jsonschema import Draft202012Validator

    from app.application.agent_orchestrator.tool_spec import (
        get_tool_action_spec,
        validate_tool_call,
    )

    for action in ("read", "structure", "query"):
        params = {"file_path": "owned.xlsx", "header_row": 0}
        if action == "query":
            params["query_expression"] = "A > 0"
        assert validate_tool_call("excel_analysis", action, params).ok
        assert not validate_tool_call("excel_analysis", action, {**params, "header_row": -1}).ok
    reader_contract = Draft202012Validator(get_tool_action_spec("employee", "execute").input_schema)
    for key in ("employee_id", "pack_id", "tool_name", "id"):
        params = {key: "excel-full-read-employee", "task": "read workbook", "input": {}}
        assert not reader_contract.is_valid(params)
        params["input"] = {"upload_id": "owned-upload"}
        assert reader_contract.is_valid(params)


def test_registered_reader_rejects_missing_source_and_invalid_header(owned_workbooks):
    _, context = owned_workbooks
    missing = _registered_router_excel_analysis("read", {}, context, "shared", "")
    assert missing["success"] is False and "file_path" in missing["message"]
    for header in (-1, 1.5, True, "guess"):
        result = _registered_router_excel_analysis(
            "read", {"file_path": "left.xlsx", "header_row": header}, context, "shared", ""
        )
        assert result["success"] is False and result["error"] == "invalid_header_row"


@pytest.mark.parametrize("action", ["read", "structure", "statistics", "query", "aggregate"])
def test_registered_ooxml_actions_reject_unsafe_archive_before_native_load(
    owned_workbooks, tmp_path, monkeypatch, action
):
    from zipfile import ZipFile

    _, context = owned_workbooks
    with ZipFile(tmp_path / "left.xlsx", "w") as archive:
        archive.writestr("../escape.xml", "<blocked/>")
    pandas_read = Mock(side_effect=AssertionError("unsafe workbook reached pandas"))
    header_read = Mock(side_effect=AssertionError("unsafe workbook reached header detection"))
    native_read = Mock(side_effect=AssertionError("unsafe workbook reached openpyxl"))
    monkeypatch.setattr(
        "app.application.tools.workflow_tools.excel_analysis.pd.read_excel", pandas_read
    )
    monkeypatch.setattr(
        "app.application.tools.workflow_tools.excel_analysis.auto_header_row", header_read
    )
    monkeypatch.setattr("openpyxl.load_workbook", native_read)
    args = {"file_path": "left.xlsx"}
    if action == "query":
        args["query_expression"] = "id > 0"
    if action == "aggregate":
        args.update(header_row=0, metrics=[{"column": "A", "op": "sum", "cell_range": "A2:A3"}])
    result = _registered_router_excel_analysis(action, args, context, "shared", "")
    assert result["success"] is False and result["error"] == "read_excel_failed"
    pandas_read.assert_not_called()
    header_read.assert_not_called()
    native_read.assert_not_called()


@pytest.mark.parametrize("suffix", [".csv", ".xls"])
def test_non_ooxml_analysis_keeps_existing_reader_without_zip_audit(tmp_path, monkeypatch, suffix):
    from app.application.tools.workflow import handle_excel_analysis

    path = tmp_path / f"data{suffix}"
    guard = Mock(side_effect=AssertionError("non-OOXML input sent to ZIP audit"))
    monkeypatch.setattr(
        "app.infrastructure.document_parsing.archive_safety.inspect_office_archive", guard
    )
    if suffix == ".csv":
        path.write_text("id\n1\n", encoding="utf-8")
    else:
        # Test routing to the existing XLS backend, not XLS format qualification.
        path.write_bytes(bytes.fromhex("D0CF11E0A1B11AE1"))
        reader = Mock(return_value=pd.DataFrame({"id": [1]}))
        monkeypatch.setattr(
            "app.application.tools.workflow_tools.excel_analysis.pd.read_excel", reader
        )
    result = handle_excel_analysis({"file_path": str(path), "action": "read", "header_row": 1})
    assert result["success"] is True and result["records"] == [{"id": 1}]
    guard.assert_not_called()
    if suffix == ".xls":
        reader.assert_called_once_with(path, header=0)
