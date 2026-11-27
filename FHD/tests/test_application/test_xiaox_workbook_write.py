"""Owned workbook writes through approved tools and independent structural QC."""

from __future__ import annotations

import copy
import hashlib
import io
import json
from pathlib import Path
from urllib.parse import unquote

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from app.application.agent_orchestrator.artifact_files import artifact_path, read_verified_run_file
from app.application.employee_runtime.executor import execute_employee_task_local
from app.db.models.elt import EltUpload
from app.db.session import get_db
from app.domain.task_lifecycle.agent_runtime_contract import (
    _batch_goal_capacity,
    goal_evidence_snapshot,
    runtime_file_evidence,
)
from app.domain.task_lifecycle.execution_mode import CONTEXT_KEY
from app.domain.workbook_write_contract import WORKBOOK_READER
from app.infrastructure.tenant_scope import tenant_scope
from app.infrastructure.xiaox.binding import XiaoxBindingError
from app.mod_sdk.employee_tool_registry import office_output_paths
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.fixtures.xiaox_workbook_runtime import workbook_runtime as workbook_runtime


@pytest.mark.parametrize("workbook_runtime", [1], indirect=True)
def test_l1_retry_reads_owned_workbook_without_write_approval(workbook_runtime):
    state = workbook_runtime
    parent = state.repository.get(state.parent.run_id)
    parent.metadata["runtime_context"]["mutation_policy"] = "model_only"
    state.repository.save(parent)

    structure = state.invoke(
        "structure",
        {"file_path": state.upload["upload_id"]},
        tool="excel_analysis",
        action="structure",
    )
    # The synthetic sheet may need header confirmation, but policy must not
    # misclassify this registered read as a write during a model-only retry.
    assert structure.get("message") == "header_confirmation_required", structure
    reader = state.invoke(
        "reader",
        {
            "employee_id": WORKBOOK_READER,
            "task": "读取上传的工作簿",
            "input": {"upload_id": state.upload["upload_id"]},
        },
    )
    assert reader["status"] == "completed" and reader["verified"] is True, reader
    assert reader.get("pending_approval") is not True


def test_reader_bad_file_reference_is_terminal_failure_without_reconciliation(workbook_runtime):
    state = workbook_runtime
    result = state.invoke(
        "missing-reader",
        {
            "employee_id": WORKBOOK_READER,
            "task": "读取上传的工作簿",
            "input": {"upload_id": "missing-upload-id"},
        },
    )
    assert result["status"] == "failed"
    assert result["reconciliation_required"] is False
    assert result["message"] == "文件不属于当前账号或当前任务，请明确选择 upload_id"


def test_writer_missing_sheet_reports_original_plan_error_before_dispatch(workbook_runtime):
    state = workbook_runtime
    params = copy.deepcopy(state.params)
    params["input"]["plan"]["phases"][0]["writes"][0]["sheet"] = "不存在的汇总页"
    result = state.invoke("missing-sheet", params)
    assert result["status"] == "not_started"
    assert result["error_code"] == "workbook_plan_invalid"
    assert "不存在的汇总页" in result["message"]
    assert state.store.get(state.parent.run_id).metadata["calls"] == {}


def test_invalid_formula_is_rejected_before_workbook_approval(workbook_runtime):
    state = workbook_runtime
    params = copy.deepcopy(state.params)
    params["input"]["plan"]["phases"][1]["writes"][0]["formula"] = "=SUM(A1;B1)"
    result = state.invoke("invalid-formula", params)
    assert result["status"] == "not_started"
    assert result["error_code"] == "workbook_formula_syntax_invalid"
    assert result["field_path"] == "input.plan.phases[1].writes[0].formula"
    assert state.store.get(state.parent.run_id).metadata["calls"] == {}


def test_chat_upload_id_flows_through_reader_writer_and_independent_qc(workbook_runtime):
    state = workbook_runtime
    upload_id = state.upload["upload_id"]
    reader = "excel-full-read-employee"
    with tenant_scope(state.actor.tenant_id):
        with get_db() as db:
            owned_copy = Path(db.get(EltUpload, upload_id).storage_path)
        assert owned_copy.read_bytes() == state.workspace_copy.read_bytes() == state.original
        read = execute_employee_task_local(
            reader,
            "读取上传的工作簿",
            {"upload_id": upload_id},
            user_id=state.actor.user_id,
            runtime_context=state.actor.context,
        )
    assert read["success"] is True, read
    [reader_output] = office_output_paths(reader, read)
    [sheet] = json.loads(Path(reader_output).read_text(encoding="utf-8"))["sheets"]
    assert sheet["name"] == "Data"
    cells = {(cell["row"], cell["col"]): cell["value"] for cell in sheet["cells"]}
    assert cells[2, 1] == "old"
    assert cells[2, 2] == 1
    pending = state.invoke("write", state.params)
    assert pending["pending_approval"] is True and not pending["artifacts"]
    [review] = pending["approval_card"]["todo"]
    assert 'Data · A2  "old" → "observed-name"' in review
    assert "Data · B2  1 → 5" in review
    child = state.approve(pending)
    receipt = state.store.receipt_snapshot(state.parent.run_id)[0]["receipt"]
    assert child.status == "completed" and receipt["verified"] is True, [
        (
            record.metadata.get("verification"),
            record.metadata.get("verification_contract", {}).get("workbook_template"),
        )
        for record in child.tool_calls
    ]
    artifact = receipt["artifacts"][0]
    content = read_verified_run_file(child.run_id, artifact)
    # Exercise the authenticated HTTP download, not only the private file reader.
    from app.fastapi_routes.domains.agent.artifact_routes import router as artifact_router

    download_app = FastAPI()
    download_app.include_router(artifact_router)
    with TestClient(download_app, headers=state.actor.headers) as client:
        downloaded = client.get(artifact["uri"])
    assert downloaded.status_code == 200, downloaded.text
    assert downloaded.headers["cache-control"] == "private, no-store"
    assert downloaded.content == content
    assert downloaded.content != state.original
    with TestClient(download_app) as anonymous:
        denied = anonymous.get(artifact["uri"])
    assert denied.status_code in (401, 403)
    with io.BytesIO(content) as stream:
        book = load_workbook(stream, data_only=False)
        assert book["Data"]["A2"].value == "observed-name"
        assert book["Data"]["B2"].value == 5
        assert book["Data"]["C2"].value == "=B2*2"
        assert book["Data"]["D2"].value == "protected"
        book.close()
    checks = receipt["verification"]["steps"][0]["checks"]
    quality = next(row["evidence"] for row in checks if row["source"] == "workbook_qc")
    assert quality["template_sha256"] == hashlib.sha256(state.original).hexdigest()
    assert quality["artifact_sha256"] == hashlib.sha256(downloaded.content).hexdigest()
    assert quality["formula_recalculation_verified"] is False
    assert quality["formula_recalculation"]["code"] == "formula_recalculation_engine_unavailable"
    changes = quality["cell_changes"]
    assert changes["scan_complete"] is True
    assert {example["ref"] for group in changes["groups"] for example in group["examples"]} == {
        "A2",
        "B2",
        "C2",
    }
    assert "observed-name" not in json.dumps(changes)
    assert quality["sections"]["conformance"] == quality["sections"]["protection"] == "pass"
    next_action = state.invoke(
        "read-written", {"file_path": artifact["uri"]}, "excel_analysis", "read"
    )
    assert next_action["verified"] is True, next_action
    assert "observed-name" in str(next_action["tool_calls"][0]["output"])
    replay = state.invoke("write-retry", state.params)
    assert replay["run_id"] == child.run_id
    assert read_verified_run_file(child.run_id, artifact) == content
    assert owned_copy.read_bytes() == state.workspace_copy.read_bytes() == state.original
    assert len(child.tool_calls) == 1 and not child.llm_calls


def test_chat_upload_id_through_xiaox_a2_structural_write_and_download(workbook_runtime):
    state = workbook_runtime
    upload_id = state.upload["upload_id"]
    with tenant_scope(state.actor.tenant_id), get_db() as db:
        upload = db.get(EltUpload, upload_id)
        owned_copy = Path(upload.storage_path)
        source_digest = upload.sha256
    assert source_digest == hashlib.sha256(state.original).hexdigest()
    assert owned_copy.read_bytes() == state.workspace_copy.read_bytes() == state.original

    params = copy.deepcopy(state.params)
    assert params["input"]["template_path"] == upload_id
    output_name = "小C-Excel制表考卷.xlsx"
    params["input"]["output_name"] = output_name
    params["input"]["plan"] = {
        "plan_version": 1,
        "phases": [
            {"phase": "insert_rows", "sheet": "Data", "row": 1, "count": 1},
            {"phase": "merge_cells", "sheet": "Data", "range": "A1:C1"},
            {
                "phase": "cell_writes",
                "writes": [{"sheet": "Data", "ref": "A1", "value": "Uploaded report"}],
            },
            {
                "phase": "cell_styles",
                "sheet": "Data",
                "range": "A1",
                "font_size": 18,
                "bold": True,
                "horizontal": "center",
            },
            {"phase": "set_row_height", "sheet": "Data", "row": 1, "height": 30},
            {"phase": "freeze_panes", "sheet": "Data", "ref": "A3"},
        ],
    }
    pending = state.invoke("structure", params)
    assert pending["pending_approval"] is True and not pending["artifacts"]
    child = state.approve(pending)
    assert child.metadata["runtime_context"]["attachment_upload_ids"] == [upload_id]
    receipt = state.store.receipt_snapshot(state.parent.run_id)[0]["receipt"]
    assert child.status == "completed" and receipt["verified"] is True, (child.error, receipt)
    [artifact] = receipt["artifacts"]
    assert artifact["name"] == output_name
    raw = read_verified_run_file(child.run_id, artifact)
    from app.fastapi_routes.domains.agent.artifact_routes import router as artifact_router

    app = FastAPI()
    app.include_router(artifact_router)
    with TestClient(app, headers=state.actor.headers) as client:
        response = client.get(artifact["uri"])
    assert response.status_code == 200, response.text
    assert response.content == raw != state.original
    assert (
        unquote(response.headers["content-disposition"])
        == f"attachment; filename*=UTF-8''{output_name}"
    )
    checks = receipt["verification"]["steps"][0]["checks"]
    quality = next(row["evidence"] for row in checks if row["source"] == "workbook_qc")
    assert quality["template_sha256"] == source_digest
    assert quality["artifact_sha256"] == hashlib.sha256(response.content).hexdigest()
    assert quality["sections"]["conformance"] == quality["sections"]["formulas"] == "pass"
    assert quality["formula_recalculation_verified"] is False
    assert quality["formula_recalculation"]["code"] == "formula_recalculation_engine_unavailable"
    with io.BytesIO(response.content) as stream:
        book = load_workbook(stream, data_only=False)
        try:
            sheet = book["Data"]
            assert sheet["A1"].value == "Uploaded report"
            assert {str(region) for region in sheet.merged_cells.ranges} == {"A1:C1"}
            assert sheet["A1"].font.sz == 18
            assert sheet["A1"].font.bold is True
            assert sheet["A1"].alignment.horizontal == "center"
            assert sheet.row_dimensions[1].height == 30
            assert sheet.freeze_panes == "A3"
            assert [sheet.cell(2, col).value for col in range(1, 4)] == [
                "name",
                "amount",
                "formula",
            ]
            assert [sheet.cell(3, col).value for col in range(1, 5)] == [
                "old",
                1,
                "=B3+1",
                "protected",
            ]
        finally:
            book.close()
    replay = state.invoke("structure-retry", params)
    assert replay["run_id"] == child.run_id
    assert read_verified_run_file(child.run_id, artifact) == raw
    assert owned_copy.read_bytes() == state.workspace_copy.read_bytes() == state.original


def test_new_sheet_is_written_and_independently_verified(workbook_runtime):
    state = workbook_runtime
    params = copy.deepcopy(state.params)
    params["input"]["plan"] = {
        "plan_version": 1,
        "template": {"sheet_names": ["Data"]},
        "phases": [
            {"phase": "create_sheet", "sheet": "Summary"},
            {
                "phase": "cell_writes",
                "writes": [
                    {"sheet": "Summary", "ref": "A1", "value": "Total"},
                ],
            },
            {
                "phase": "formula_writes",
                "writes": [
                    {"sheet": "Summary", "ref": "B1", "formula": "=SUM(Data!B2:B3)"},
                ],
            },
        ],
    }
    pending = state.invoke("new-sheet", params)
    assert pending["pending_approval"] is True, pending
    child = state.approve(pending)
    receipt = state.store.receipt_snapshot(state.parent.run_id)[0]["receipt"]
    assert child.status == "completed" and receipt["verified"] is True, (child.error, receipt)
    [artifact] = receipt["artifacts"]
    with io.BytesIO(read_verified_run_file(child.run_id, artifact)) as stream:
        book = load_workbook(stream, data_only=False)
        try:
            assert book.sheetnames == ["Data", "Summary"]
            assert book["Summary"]["A1"].value == "Total"
            assert book["Summary"]["B1"].value == "=SUM(Data!B2:B3)"
        finally:
            book.close()
    checks = receipt["verification"]["steps"][0]["checks"]
    quality = next(row["evidence"] for row in checks if row["source"] == "workbook_qc")
    assert quality["sections"]["conformance"] == "pass"
    assert state.workspace_copy.read_bytes() == state.original


def test_verified_workbook_readback_reaches_goal_evidence(workbook_runtime):
    state = workbook_runtime
    written = state.approve(state.invoke("write-for-readback", state.params))
    assert written.status == "completed"
    write_row = state.store.receipt_snapshot(state.parent.run_id)[0]
    assert _batch_goal_capacity(write_row) >= 2
    artifact = write_row["receipt"]["artifacts"][0]
    read = state.invoke(
        "read-answer-copy",
        {
            "employee_id": WORKBOOK_READER,
            "task": "回读已验证的答题副本",
            "input": {"file_path": artifact["uri"]},
        },
    )
    assert read["status"] == "completed" and read["verified"] is True, read
    rows = state.store.receipt_snapshot(state.parent.run_id)
    contract = state.repository.get(state.parent.run_id).metadata["runtime_goal_contract"]
    snapshot = goal_evidence_snapshot(contract, rows, "副本已回读")
    sources = runtime_file_evidence(contract, snapshot)
    assert sources is not None
    source = sources[read["run_id"]]
    assert source["origin"] == "verified_workbook_readback"
    assert source["coverage"]["truncated"] is False
    assert '"ref":"C2","value":null,"formula":"=B2*2"' in source["text"]


def test_unverified_workbook_readback_cannot_be_cited(workbook_runtime):
    state = workbook_runtime
    written = state.approve(state.invoke("write-for-untrusted-readback", state.params))
    assert written.status == "completed"
    artifact = state.store.receipt_snapshot(state.parent.run_id)[0]["receipt"]["artifacts"][0]
    read = state.invoke(
        "read-untrusted",
        {
            "employee_id": WORKBOOK_READER,
            "task": "回读已验证的答题副本",
            "input": {"file_path": artifact["uri"]},
        },
    )
    assert read["status"] == "completed"
    rows = state.store.receipt_snapshot(state.parent.run_id)
    read_row = next(row for row in rows if row["child_run_id"] == read["run_id"])
    read_row["receipt"]["tool_calls"][0]["output"]["data"]["readback"]["sha256"] = "0" * 64
    contract = state.repository.get(state.parent.run_id).metadata["runtime_goal_contract"]
    snapshot = goal_evidence_snapshot(contract, rows, "副本已回读")
    assert read["run_id"] not in (runtime_file_evidence(contract, snapshot) or {})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("workspace_root", "/outside/private.xlsx"),
        ("output_relpath", "/outside/private.xlsx"),
        ("template_relpath", "/outside/private.xlsx"),
        ("output_name", "../答题.xlsx"),
        ("output_name", r"其他目录\答题.xlsx"),
    ],
)
def test_model_cannot_override_writer_paths_or_output_authority(workbook_runtime, field, value):
    state = workbook_runtime
    params = copy.deepcopy(state.params)
    params["input"][field] = value
    result = state.invoke("invalid", params)
    assert result["status"] == "not_started"
    assert state.store.get(state.parent.run_id).metadata["calls"] == {}


def test_writer_rejects_output_name_with_different_workbook_format(workbook_runtime):
    state = workbook_runtime
    params = copy.deepcopy(state.params)
    params["input"]["output_name"] = "答题.xlsm"
    child = state.approve(state.invoke("format-mismatch", params))
    assert child.status != "completed" and not child.artifacts
    assert not any(record.output.get("success") is True for record in child.tool_calls)


def test_writer_rejects_conflicting_writes_before_approval(workbook_runtime):
    state = workbook_runtime
    params = copy.deepcopy(state.params)
    params["input"]["plan"]["phases"][1]["writes"].append(
        {"sheet": "Data", "ref": "A2", "formula": "=B2*2"}
    )
    denied = state.invoke("conflicting-cell", params)
    assert denied["status"] == "not_started"
    assert denied["error_code"] == "workbook_plan_invalid"
    assert "Data!A2" in denied["message"]
    assert state.store.get(state.parent.run_id).metadata["calls"] == {}


@pytest.mark.parametrize("workbook_runtime", range(1, 7), indirect=True)
def test_auto_workbook_review_refuses_unbound_values_and_accepts_a_corrected_plan(workbook_runtime):
    state = workbook_runtime
    parent = state.repository.get(state.parent.run_id)
    parent.metadata["runtime_context"]["chat_approval_mode"] = "auto"
    state.repository.save(parent)
    params = copy.deepcopy(state.params)
    plan = params["input"]["plan"]
    plan["phases"][0]["writes"].append({"sheet": "Data", "ref": "B6", "value": 99})
    denied = state.invoke("edit", params)
    assert denied["status"] == "not_started" and denied["required_approval"] == "manual"
    assert denied["error_code"] == "workbook_manual_approval_required"
    assert {change["ref"]: change["kind"] for change in denied["changes"]} == {
        "A2": "replace",
        "B2": "replace",
        "B6": "fill_blank",
    }
    assert "observed-name" not in json.dumps(denied)
    assert state.store.get(parent.run_id).metadata["calls"] == {}

    read = state.invoke(
        "read-owned",
        {
            "employee_id": WORKBOOK_READER,
            "task": "读取原工作簿",
            "input": {"upload_id": state.upload["upload_id"]},
        },
    )
    if read.get("pending_approval"):
        state.approve(read)
        read = state.store.receipt_snapshot(state.parent.run_id)[0]["receipt"]
    assert read["status"] == "completed" and read["verified"] is True, read
    workbook = json.loads(read_verified_run_file(read["run_id"], read["artifacts"][0]))
    [sheet] = workbook["sheets"]
    assert sheet["name"] == "Data"
    cells = {(cell["row"], cell["col"]): cell["value"] for cell in sheet["cells"]}
    assert cells[2, 1] == "old" and cells[2, 2] == 1

    plan["phases"] = [
        {"phase": "insert_rows", "sheet": "Data", "row": 1, "count": 1},
        {"phase": "merge_cells", "sheet": "Data", "range": "A1:C1"},
        {
            "phase": "cell_writes",
            "writes": [
                {"sheet": "Data", "ref": "A1", "value": "Report"},
                {"sheet": "Data", "ref": "B3", "value": "1", "value_type": "number"},
            ],
        },
        {
            "phase": "formula_writes",
            "writes": [
                {"sheet": "Data", "ref": "C3", "formula": "=B3*2"},
            ],
        },
    ]
    result = state.invoke("edit", params)
    if result.get("pending_approval"):
        state.approve(result)
        result = state.store.receipt_snapshot(state.parent.run_id)[-1]["receipt"]
    child = state.repository.get(result.get("run_id", ""))
    assert result["status"] == "completed" and result["verified"] is True, (
        child.status,
        [call.metadata.get("verification") for call in child.tool_calls],
    )
    calls = state.store.get(parent.run_id).metadata["calls"]
    assert calls["edit"]["isolated_artifact"] and not calls["edit"]["read_only"]
    assert calls["read-owned"]["read_only"]
    replay = state.invoke("repeat", params)
    assert replay["run_id"] == result["run_id"] and replay["artifacts"] == result["artifacts"]
    [artifact] = result["artifacts"]
    with io.BytesIO(read_verified_run_file(result["run_id"], artifact)) as stream:
        book = load_workbook(stream)
        try:
            sheet = book["Data"]
            assert [sheet[ref].value for ref in ("A1", "A3", "B3", "C3", "D3", "B6")] == [
                "Report",
                "old",
                1,
                "=B3*2",
                "protected",
                None,
            ]
        finally:
            book.close()
    assert state.workspace_copy.read_bytes() == state.original


@pytest.mark.parametrize("workbook_runtime", [1], indirect=True)
def test_plan_mode_does_not_create_workbook_write_or_approval(workbook_runtime):
    state = workbook_runtime
    parent = state.repository.get(state.parent.run_id)
    parent.metadata["runtime_context"][CONTEXT_KEY] = "plan"
    state.repository.save(parent)
    denied = state.invoke("edit", state.params)
    assert denied["error_code"] == "execution_mode_plan_blocked"
    assert state.store.get(parent.run_id).metadata["calls"] == {}


def test_replaced_upload_is_rejected_before_signed_writer_runs(workbook_runtime):
    state = workbook_runtime
    pending = state.invoke("write", state.params)
    with tenant_scope(state.actor.tenant_id), get_db() as db:
        db.get(EltUpload, state.upload["upload_id"]).owner_user_id = state.actor.user_id + 100
    child = state.approve(pending)
    assert child.status != "completed" and not child.artifacts
    assert not any(record.output.get("success") is True for record in child.tool_calls)


def test_changed_artifact_cannot_become_the_next_action_input(workbook_runtime):
    state = workbook_runtime
    child = state.approve(state.invoke("write", state.params))
    receipt = state.store.receipt_snapshot(state.parent.run_id)[0]["receipt"]
    assert receipt["verified"] is True, (child.error, receipt)
    artifact = receipt["artifacts"][0]
    path = artifact_path(child.run_id, artifact["artifact_id"])
    path.write_bytes(b"changed after original receipt")
    with pytest.raises((XiaoxBindingError, PermissionError, ValueError)):
        # Opening a previous file needs its original bytes and verified scope;
        # no supplied URI alone grants filesystem authority.
        from app.infrastructure.xiaox.receipts import read_action_artifact

        current = state.repository.get(child.run_id)
        read_action_artifact(
            artifact["uri"], {**current.metadata["runtime_context"], "run_id": current.run_id}
        )


def test_writer_context_reports_the_input_contract_instead_of_a_write_denial(monkeypatch):
    from app.application.agent_orchestrator import tool_permission
    from app.application.employee_runtime import executor, loader, tool_scope
    from app.domain.workbook_write_contract import WORKBOOK_WRITE_INPUT, WORKBOOK_WRITER

    monkeypatch.setattr(loader, "candidate_pack_ids", lambda employee_id: [WORKBOOK_WRITER])
    monkeypatch.setattr(tool_scope, "host_employee_denial", lambda *args, **kwargs: None)
    monkeypatch.setattr(tool_permission, "actor_tool_denial", lambda *args, **kwargs: None)

    result = executor.execute_employee_task_local(
        "excel-template-write-employee",
        "查看 Excel 模板写入员工的输入结构",
        {},
        runtime_context={"_actor_authorization": {"user_id": 1}},
        context_only=True,
    )

    assert result["success"] is True
    assert result["input_schema"] == WORKBOOK_WRITE_INPUT
    assert result["input_schema"]["required"] == ["template_path", "plan"]


def test_multiterm_capability_search_finds_authorized_workbook_writer(workbook_runtime):
    state = workbook_runtime
    result = state.bridge.invoke(
        state.grant.mcp_token,
        "capability_search",
        {"query": "Excel 工作簿 生成 公式 导出 回读 下载"},
    )
    assert result["success"] is True
    assert ("employee", "execute") in {
        (row["tool_id"], row["action"]) for row in result["capabilities"]
    }


def test_native_employee_mcp_tool_keeps_review_and_approval(workbook_runtime):
    from jsonschema import Draft202012Validator

    from app.infrastructure.xiaox.tools import mcp_tool_definitions

    state = workbook_runtime
    tools = mcp_tool_definitions([("employee", "execute")])
    direct = next(tool for tool in tools if tool.name == "execute_employee")
    assert "execute_employee" not in {
        tool.name for tool in mcp_tool_definitions([("customers", "query")])
    }
    digest = state.bridge.invoke(
        state.grant.mcp_token,
        "capability_describe",
        {"tool_id": "employee", "action": "execute"},
    )["capability"]["schema_digest"]
    args = {**state.params, "call_id": "direct-writer", "schema_digest": digest}
    assert not list(Draft202012Validator(direct.input_schema).iter_errors(args))
    result = state.bridge.invoke(state.grant.mcp_token, "execute_employee", args)
    assert result["status"] == "waiting_user"
    assert result["pending_approval"] is True
    assert not state.workspace_copy.with_name("answer.xlsx").exists()


def test_write_contract_declares_which_structural_capabilities_exist():
    """卷二 A2 需要插入行、合并、字号、行高与冻结；契约必须如实声明。

    题面要求的动作若不在契约里，写入员工只会静默忽略，产物缺项会被
    误判成"模型写错"。能力进契约，写入员与独立质检才都必须覆盖。
    """
    from app.domain.workbook_write_contract import WORKBOOK_WRITE_INPUT

    phases = WORKBOOK_WRITE_INPUT["properties"]["plan"]["properties"]["phases"]["items"]
    supported = set()
    for option in phases["oneOf"]:
        supported.add(option["properties"]["phase"]["const"])

    assert {
        "cell_writes",
        "formula_writes",
        "cell_styles",
        "create_sheet",
        "insert_rows",
        "merge_cells",
        "set_row_height",
        "freeze_panes",
    } <= supported

    style_fields = set()
    for option in phases["oneOf"]:
        if option["properties"]["phase"]["const"] == "cell_styles":
            style_fields = set(option["properties"])
    assert "font_size" in style_fields
