"""Real file boundaries and artifact evidence for approved legacy Python employees."""

from __future__ import annotations

import hashlib
from copy import deepcopy
from pathlib import Path
from types import ModuleType

import pytest

from modstore_server import strategic_portfolio as portfolio
from modstore_server import strategic_portfolio_usage as usage
from modstore_server.employee_path_guard import check_path_guard
from modstore_server.employee_verification import run_verification
from modstore_server.strategic_execution_contract import (
    bind_file_receipts,
    execution_payload,
    verify_execution_binding,
)
from modstore_server.strategic_execution_receipts import evaluate_execution_receipt
from tests import test_strategic_execution_contract as contracts
from tests import test_strategic_portfolio as fixtures
from tests.test_strategic_portfolio import claim_proposal, opportunity, proposal

database = fixtures.database
archived_python = contracts.archived_python


@pytest.mark.parametrize(
    "case", ["absolute", "parent", "symlink", "sibling", "missing", "directory"]
)
def test_file_input_is_rejected_before_approval(database, tmp_path, case):
    workspace = tmp_path / "workspaces/7/project"
    workspace.mkdir(parents=True)
    outside = tmp_path / "workspaces/8/private.json"
    outside.parent.mkdir(parents=True)
    outside.write_text("private")
    sibling = workspace.parent / "other.json"
    sibling.write_text("other authorized project")
    link = workspace / "linked.json"
    link.symlink_to(outside)
    paths = {
        "absolute": str(outside),
        "parent": "../../8/private.json",
        "symlink": str(link),
        "sibling": "../other.json",
        "missing": "missing.json",
        "directory": ".",
    }
    with pytest.raises(portfolio.PortfolioError, match="selected workspace"):
        proposal(
            database,
            rows=[
                opportunity(input_data={"project_root": str(workspace), "file_path": paths[case]})
            ],
        )


def test_input_symlink_changed_after_approval_is_rechecked_before_execution(database, tmp_path):
    workspace = tmp_path / "workspaces/7"
    workspace.mkdir(parents=True)
    source = workspace / "source.json"
    source.write_text("approved source")
    link = workspace / "input.json"
    link.symlink_to(source)
    decision, task = claim_proposal(
        database, rows=[opportunity(input_data={"file_path": str(link)})]
    )
    outside = tmp_path / "private.json"
    outside.write_text("unapproved source")
    link.unlink()
    link.symlink_to(outside)
    with (
        usage.portfolio_usage_scope(decision, "a", task["lease_token"]),
        pytest.raises(portfolio.PortfolioError, match="selected workspace"),
    ):
        verify_execution_binding(task["employee_id"], user_id=7, payload=execution_payload(task))


@pytest.mark.parametrize(
    "path", ["../escape.csv", "/tmp/escape.csv", "other/result.csv", "docs/.env"]
)
def test_output_location_rejected_during_freeze(archived_python, path):
    from modstore_server.strategic_execution_contract import freeze_execution

    _facade, _pack, _decision, task, _archive = archived_python
    with pytest.raises(portfolio.PortfolioError, match="workspace|scope"):
        freeze_execution(
            7, opportunity(employee_id=task["employee_id"], input_data={"output_relpath": path})
        )


@pytest.mark.parametrize("alias", ["path", "excel_path"])
def test_file_input_alias_cannot_bypass_selected_workspace(archived_python, tmp_path, alias):
    from modstore_server.strategic_execution_contract import freeze_execution

    _facade, _pack, _decision, task, _archive = archived_python
    outside = tmp_path / "private.json"
    outside.write_text("private")
    inputs = {alias: f" {outside} ", "output_relpath": "docs/result.csv"}
    with pytest.raises(portfolio.PortfolioError, match="selected workspace"):
        freeze_execution(7, opportunity(employee_id=task["employee_id"], input_data=inputs))
    source = Path(task["input_data"]["project_root"]) / "source.json"
    source.write_text("approved")
    # The same precedence as FileEmployeeSupport: unused lower-priority aliases
    # do not change the file actually selected by a valid file_path.
    inputs["file_path"] = str(source)
    assert freeze_execution(7, opportunity(employee_id=task["employee_id"], input_data=inputs))


@pytest.mark.parametrize(
    "case", ["bundled", "workspace_first", "escape", "symlink", "default_output"]
)
def test_actual_file_support_resolver_keeps_frozen_templates_and_rejects_escape(
    archived_python, tmp_path, case
):
    from app.mod_sdk.file_employee_support import FileEmployeeSupport

    from modstore_server.strategic_execution_contract import _verify_file_support

    _facade, pack, _decision, task, _archive = archived_python
    payload = execution_payload(task)
    workspace = Path(payload["project_root"])
    snapshot = tmp_path / "immutable_snapshot"
    module_path = snapshot / "backend/employees/approved.py"
    module_path.parent.mkdir(parents=True)
    module_path.write_text("# approved snapshot")
    bundled = snapshot / "backend/templates/original.xlsx"
    bundled.parent.mkdir(parents=True)
    bundled.write_bytes(b"packaged template")
    spec = {
        "default_output_relpath": "docs/result.csv",
        "default_template_relpath": "templates/original.xlsx",
    }
    module = ModuleType("approved")
    module.__file__ = str(module_path)
    support = module._file_support = FileEmployeeSupport(str(module_path), spec)
    if case == "workspace_first":
        selected = workspace / "templates/original.xlsx"
        selected.parent.mkdir(parents=True)
        selected.write_bytes(b"tenant template")
        assert support._resolve_template(payload, {}) == selected
    elif case in {"escape", "symlink"}:
        private = tmp_path / "private.xlsx"
        private.write_bytes(b"outside authorized paths")
        if case == "escape":
            payload["template_relpath"] = str(private)
        else:
            link = workspace / "templates/original.xlsx"
            link.parent.mkdir(parents=True)
            link.symlink_to(private)
    elif case == "default_output":
        spec["default_output_relpath"] = "../../outside.csv"
    if case in {"escape", "symlink", "default_output"}:
        with pytest.raises(portfolio.PortfolioError, match="selected workspace"):
            _verify_file_support(module, payload, pack["manifest"]["employee_config_v2"], 7)
    else:
        _verify_file_support(module, payload, pack["manifest"]["employee_config_v2"], 7)
        assert support._resolve_template(payload, {}) == (
            selected if case == "workspace_first" else bundled
        )


@pytest.mark.parametrize(
    "case",
    [
        "valid",
        "aliases",
        "missing",
        "outside",
        "symlink",
        "scope",
        "forbidden",
        "no_summary",
        "pending",
        "false_success",
        "changed",
    ],
)
def test_legacy_receipt_needs_real_stable_in_scope_bytes(database, tmp_path, monkeypatch, case):
    from modstore_server import catalog_archive_integrity

    decision, task = claim_proposal(database)
    payload = execution_payload(task)
    workspace = Path(payload["project_root"])
    artifact = workspace / "docs/result.csv"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"order,quantity\nA-7,3\n")
    if case in {"outside", "symlink"}:
        outside = tmp_path / "workspaces/8/private.csv"
        outside.parent.mkdir(parents=True)
        outside.write_text("other tenant")
        if case == "symlink":
            artifact.unlink()
            artifact.symlink_to(outside)
        else:
            artifact = outside
    elif case in {"scope", "forbidden"}:
        artifact = workspace / ("other.csv" if case == "scope" else "docs/.env")
        artifact.write_text("out of scope")
    elif case == "missing":
        artifact.unlink()
    output = {
        "ok": True,
        "summary": "Generated the requested order CSV from authorized data.",
        "items": [{"output_path": str(artifact)}],
        "error": "",
    }
    if case == "aliases":
        output["items"].append({"output_path": "docs/result.csv"})
    if case == "no_summary":
        output["summary"] = ""
    elif case == "pending":
        output["status"] = "pending"
    elif case == "false_success":
        output["ok"] = "true"
    elif case == "changed":
        digest = catalog_archive_integrity.sha256_file

        def change_after_read(path):
            value = digest(path)
            path.write_text("changed after digest")
            return value

        monkeypatch.setattr(catalog_archive_integrity, "sha256_file", change_after_read)
    result = {"outputs": [{"handler": "direct_python", "ok": True, "output": output}]}
    config = {"workspace_policy": {"scope_globs": ["docs/**"], "forbidden_globs": ["**/.env"]}}
    ordinary = deepcopy(result)
    bind_file_receipts(ordinary, payload, config, 7)
    assert ordinary == result  # Ordinary customer executions retain their original protocol.
    with usage.portfolio_usage_scope(decision, "a", task["lease_token"]):
        bind_file_receipts(result, payload, config, 7)
    result["path_guard"] = check_path_guard(
        config=config, result=result, employee_id=task["employee_id"], project_root=workspace
    )
    result["verification"] = run_verification(
        employee_id=task["employee_id"],
        task="Export authorized CSV",
        reasoning={},
        result=result,
        config=config,
        project_root=workspace,
    )
    receipt = evaluate_execution_receipt(result)
    if case in {"valid", "aliases"}:
        assert receipt.status == "completed"
        assert output["items"][0]["output_path"] == str(artifact)
        assert result["path_guard"]["all_changed_files"] == ["docs/result.csv"]
        assert result["verification"]["files_declared"] == ["docs/result.csv"]
        assert output["artifacts"] == [
            {
                "artifact_id": "docs/result.csv",
                "path": "docs/result.csv",
                "artifact_sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
                "size_bytes": artifact.stat().st_size,
            }
        ]
    else:
        assert receipt.status == "failed"
        assert result["outputs"][0]["ok"] is False
        assert "artifacts" not in output and output.get("status") != "completed"
