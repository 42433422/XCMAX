"""Export resource limits precede materialization and artifact publication."""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock

import pandas as pd
import pytest

from app.application import excel_export_limits as limits
from app.application.agent_orchestrator import artifact_files
from app.application.tools import workflow
from app.application.tools import workflow_spreadsheet_scope as scope
from app.application.tools.workflow_tools import excel_analysis
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


@pytest.mark.parametrize("case", ["rows", "columns", "dense_cells", "header", "cell"])
def test_export_rejects_oversized_input_before_dataframe(tmp_path, monkeypatch, case):
    rows = {
        "rows": lambda: [{"a": 1}] * 50_001,
        "columns": lambda: [{f"c{i}": i} for i in range(201)],
        "dense_cells": lambda: [{f"c{i % 200}": i} for i in range(501)],
        "header": lambda: [{"x" * 32_768: 1}],
        "cell": lambda: [{"a": "x" * 32_768}],
    }[case]()
    construct = Mock(side_effect=AssertionError("DataFrame must not receive oversized input"))
    monkeypatch.setattr(excel_analysis.pd, "DataFrame", construct)

    result = workflow.handle_excel_analysis(
        {"action": "export", "file_path": "new/report.xlsx", "rows": rows, "columns": ["a"]},
        workspace_root=str(tmp_path),
    )

    assert result["success"] is False
    assert result["error_code"] == "excel_export_limit_exceeded"
    construct.assert_not_called()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("kind", ["csv", "xlsx"])
def test_small_export_preserves_values_and_original_column_semantics(tmp_path, kind):
    rows = [{"姓名": "甲", "数量": 2}, {"姓名": "乙", "数量": 3}]
    target = tmp_path / f"report.{kind}"

    result = workflow.handle_excel_analysis(
        {"action": "export", "file_path": target.name, "rows": rows, "columns": ["姓名"]},
        workspace_root=str(tmp_path),
    )

    assert result["success"] is True
    assert result["data"]["row_count"] == 2
    assert result["data"]["columns"] == ["姓名", "数量"]
    read = pd.read_csv if kind == "csv" else pd.read_excel
    assert read(target).to_dict(orient="records") == rows
    assert list(tmp_path.iterdir()) == [target]


def test_sparse_rows_are_materialized_as_the_union_of_columns(tmp_path):
    result = workflow.handle_excel_analysis(
        {"action": "export", "file_path": "sparse.csv", "rows": [{"a": 1}, {"b": 2}]},
        workspace_root=str(tmp_path),
    )

    assert result["success"] is True
    actual = pd.read_csv(result["data"]["file_path"])
    assert actual.shape == (2, 2)
    assert actual.loc[0, "a"] == 1 and pd.isna(actual.loc[0, "b"])
    assert pd.isna(actual.loc[1, "a"]) and actual.loc[1, "b"] == 2


@pytest.mark.parametrize("value", ["汉😀" * 10, '"\\\n' * 10, ["a", {"nested": "汉字"}]])
def test_serialized_budget_counts_full_utf8_payload_before_dataframe(tmp_path, monkeypatch, value):
    payload = {"action": "export", "file_path": "report.csv", "rows": [{"a": 1}], "extra": value}
    size = len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    monkeypatch.setattr(limits, "MAX_EXPORT_INPUT_BYTES", size - 1)
    construct = Mock(side_effect=AssertionError("oversized JSON reached pandas"))
    with monkeypatch.context() as guarded:
        guarded.setattr(excel_analysis.pd, "DataFrame", construct)
        result = workflow.handle_excel_analysis(payload, workspace_root=str(tmp_path))
    assert result["error_code"] == "excel_export_limit_exceeded"
    construct.assert_not_called()
    assert list(tmp_path.iterdir()) == []

    monkeypatch.setattr(limits, "MAX_EXPORT_INPUT_BYTES", size)
    assert workflow.handle_excel_analysis(payload, workspace_root=str(tmp_path))["success"] is True


def test_nested_cell_text_limit_precedes_dataframe(tmp_path, monkeypatch):
    construct = Mock(side_effect=AssertionError("oversized nested cell reached pandas"))
    monkeypatch.setattr(excel_analysis.pd, "DataFrame", construct)
    result = workflow.handle_excel_analysis(
        {"action": "export", "file_path": "nested.csv", "rows": [{"a": ["x" * 32_767]}]},
        workspace_root=str(tmp_path),
    )
    assert result["error_code"] == "excel_export_limit_exceeded"
    construct.assert_not_called()
    assert not list(tmp_path.iterdir())


def test_exact_cell_text_limit_is_written_without_truncation(tmp_path):
    value = "x" * 32_767
    result = workflow.handle_excel_analysis(
        {"action": "export", "file_path": "cell.xlsx", "rows": [{"a": value}]},
        workspace_root=str(tmp_path),
    )
    assert result["success"] is True
    assert pd.read_excel(result["data"]["file_path"]).iloc[0, 0] == value


@pytest.mark.parametrize("rows", [[{"a": 1}] * 50_001, ["not an object"]], ids=["rows", "type"])
def test_export_contract_rejects_excess_rows_or_invalid_items_without_truncation(rows):
    from app.application.agent_orchestrator.tool_spec import validate_tool_call

    original_count = len(rows)
    result = validate_tool_call("excel_analysis", "export", {"file_path": "a.csv", "rows": rows})
    assert result.ok is False
    assert len(rows) == original_count


def test_extensionless_export_is_rejected_before_staging_or_approval(export_context, monkeypatch):
    from app.application.agent_orchestrator.tool_spec import validate_tool_call

    payload = {"file_path": "run-generated-name", "rows": [{"result": 1}]}
    assert validate_tool_call("excel_analysis", "export", payload).ok is False
    context, data = export_context
    exporter = Mock(side_effect=AssertionError("invalid path reached exporter"))
    monkeypatch.setattr(workflow, "handle_excel_analysis", exporter)
    result = scope.export_workflow_spreadsheet(payload, context, exporter)
    assert result["error_code"] == "invalid_excel_path"
    exporter.assert_not_called()
    assert not list(data.iterdir())


@pytest.mark.parametrize("kind", ["csv", "xlsx"])
@pytest.mark.parametrize("existing", [False, True])
def test_oversized_artifact_is_removed_without_replacing_destination(
    tmp_path, monkeypatch, kind, existing
):
    monkeypatch.setattr(limits, "MAX_EXPORT_FILE_BYTES", 1)
    target = tmp_path / f"report.{kind}"
    if existing:
        target.write_bytes(b"previous export")

    result = workflow.handle_excel_analysis(
        {"action": "export", "file_path": target.name, "rows": [{"a": "small"}]},
        workspace_root=str(tmp_path),
    )

    assert result["error_code"] == "excel_export_limit_exceeded"
    assert list(tmp_path.iterdir()) == ([target] if existing else [])
    if existing:
        assert target.read_bytes() == b"previous export"


def test_partial_writer_failure_cleans_staging_and_preserves_previous_file(tmp_path, monkeypatch):
    target = tmp_path / "report.csv"
    target.write_bytes(b"previous export")

    def fail_write(frame, path, **kwargs):
        Path(path).write_bytes(b"partial output")
        raise OSError("write failed")

    monkeypatch.setattr(pd.DataFrame, "to_csv", fail_write)
    result = workflow.handle_excel_analysis(
        {"action": "export", "file_path": target.name, "rows": [{"a": 1}]},
        workspace_root=str(tmp_path),
    )

    assert result["error_code"] == "file_write_failed"
    assert target.read_bytes() == b"previous export"
    assert list(tmp_path.iterdir()) == [target]


@pytest.fixture
def export_context(tmp_path, monkeypatch, trusted_actor):
    actor = trusted_actor()
    data = tmp_path / "app-data"
    data.mkdir()
    monkeypatch.setattr(scope, "get_app_data_dir", lambda: str(data))
    monkeypatch.setattr(artifact_files, "get_app_data_dir", lambda: str(data))
    monkeypatch.setattr("app.utils.path_io.path_utils.get_app_data_dir", lambda: str(data))
    return {**actor.context, "run_id": "bounded-export"}, data


def test_authenticated_export_rejects_before_handler_or_store(export_context, monkeypatch):
    from app.domain.shared_services.tools_workflow_excel_ocr import (
        _registered_router_excel_analysis,
    )

    context, data = export_context
    monkeypatch.setattr(limits, "MAX_EXPORT_CELLS", 3)
    export = Mock(side_effect=AssertionError("oversized input reached export"))
    store = Mock(side_effect=AssertionError("oversized input reached persistence"))
    monkeypatch.setattr(workflow, "handle_excel_analysis", export)
    monkeypatch.setattr(scope, "store_spreadsheet", store)

    result = _registered_router_excel_analysis(
        "export", {"file_path": "report.csv", "rows": [{"a": 1}, {"b": 2}]}, context, "core", "导出"
    )

    assert result["error_code"] == "excel_export_limit_exceeded"
    export.assert_not_called()
    store.assert_not_called()
    assert not list(data.iterdir())


@pytest.mark.parametrize("kind", ["csv", "xlsx"])
def test_authenticated_small_export_publishes_real_file_and_removes_staging(export_context, kind):
    context, data = export_context
    rows = [{"name": "甲", "count": 2}]
    result = scope.export_workflow_spreadsheet(
        {"action": "export", "file_path": f"report.{kind}", "rows": rows},
        context,
        workflow.handle_excel_analysis,
    )

    assert result["success"] is True
    receipt = result["artifacts"][0]
    assert result["data"]["file_path"] == receipt["uri"]
    path = artifact_files.artifact_path(context["run_id"], receipt["artifact_id"])
    read = pd.read_csv if kind == "csv" else pd.read_excel
    assert read(path).to_dict(orient="records") == rows
    assert not list((data / "temp_excel").iterdir())


def test_artifact_read_is_bounded_and_oversized_file_is_not_persisted(export_context, monkeypatch):
    context, data = export_context
    monkeypatch.setattr(limits, "MAX_EXPORT_FILE_BYTES", 64)
    store = Mock(side_effect=AssertionError("oversized file reached persistence"))
    monkeypatch.setattr(scope, "store_spreadsheet", store)
    reads = []
    original_open = scope.open_elt_input_file

    @contextmanager
    def observe_read(*args, **kwargs):
        with original_open(*args, **kwargs) as source:
            observed = Mock(wraps=source)
            yield observed
            reads.extend(observed.read.call_args_list)

    monkeypatch.setattr(scope, "open_elt_input_file", observe_read)

    def large_export(payload, *, workspace_root):
        path = Path(workspace_root) / "report.csv"
        path.write_bytes(b"a" * 65)
        return {"success": True, "data": {"file_path": str(path)}}

    result = scope.export_workflow_spreadsheet(
        {"file_path": "report.csv", "rows": [{"a": 1}]}, context, large_export
    )

    assert result["error_code"] == "excel_export_limit_exceeded"
    assert [call.args for call in reads] == [(65,)]
    store.assert_not_called()
    assert not list((data / "temp_excel").iterdir())
    assert not (data / "agent-artifacts").exists()


def test_publication_failure_also_removes_private_staging(export_context, monkeypatch):
    context, data = export_context
    monkeypatch.setattr(scope, "store_spreadsheet", Mock(side_effect=OSError("storage failed")))
    with pytest.raises(OSError, match="storage failed"):
        scope.export_workflow_spreadsheet(
            {"action": "export", "file_path": "report.csv", "rows": [{"a": 1}]},
            context,
            workflow.handle_excel_analysis,
        )
    assert not list((data / "temp_excel").iterdir())
    assert not (data / "agent-artifacts").exists()
