"""Owned workbook -> approved bundled writer -> independent QC -> next action.

Fixtures are synthetic workbooks, not the unavailable original customer corpus.
"""

from __future__ import annotations

import copy
import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook

from app.application.agent_orchestrator import set_agent_run_repository_for_tests
from app.application.agent_orchestrator.approval_grant import issue_approval_grant
from app.application.agent_orchestrator.approval_transaction import approve_and_enqueue
from app.application.agent_orchestrator.artifact_files import artifact_path, read_verified_run_file
from app.application.agent_orchestrator.orchestrator import AgentOrchestrator
from app.application.agent_orchestrator.run_models import AgentRun
from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
from app.application.agent_orchestrator.task_dispatcher import AgentTaskDispatcher
from app.application.agent_orchestrator.task_execution_sql_repository import (
    SQLAlchemyTaskExecutionRepository,
)
from app.application.agent_orchestrator.tool_executor import AgentToolExecutor
from app.application.employee_runtime.executor import execute_employee_task_local
from app.db.models.elt import EltUpload
from app.db.session import get_db
from app.domain.task_lifecycle.agent_runtime_contract import build_goal_contract
from app.domain.workbook_write_contract import WORKBOOK_WRITER
from app.fastapi_routes.platform_shell_routes import router as platform_shell_router
from app.infrastructure.tenant_scope import tenant_scope
from app.infrastructure.xiaox.binding import XiaoxBindingError, XiaoxBindingStore
from app.infrastructure.xiaox.tools import XiaoxToolBridge
from app.mod_sdk.employee_tool_registry import office_output_paths
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


@pytest.fixture
def workbook_runtime(trusted_actor, monkeypatch, tmp_path):
    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path / "data"))
    workspace = tmp_path / "workspace"
    monkeypatch.setenv("WORKSPACE_ROOT", str(workspace))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("XCAGI_TOOL_IDEMPOTENCY_PATH", str(tmp_path / "idempotency.sqlite"))
    actor = trusted_actor(permissions=["employee.execute", "tool.excel_analysis.read"])
    repository = SQLAlchemyAgentRunRepository(session_factory=actor.factory)
    parent = AgentRun(
        str(actor.user_id), "按原模板写入两格并保存公式，然后读回工作簿", status="running"
    )
    parent.metadata.update(runtime_type="xiaox", runtime_context=actor.context)
    contract = build_goal_contract(parent)
    parent.metadata.update(runtime_goal_contract=contract, runtime_goal_digest=contract["digest"])
    repository.save(parent)
    store = XiaoxBindingStore(repository)
    grant = store.create(parent.run_id)
    book = Workbook()
    sheet = book.active
    sheet.title = "Data"
    sheet["A1"], sheet["B1"], sheet["C1"] = "name", "amount", "formula"
    sheet["A2"], sheet["B2"], sheet["D2"] = "old", 1, "protected"
    sheet["C2"] = "=B2+1"
    with io.BytesIO() as stream:
        book.save(stream)
        original = stream.getvalue()
    book.close()
    app = FastAPI()
    app.include_router(platform_shell_router)
    with TestClient(app, headers=actor.headers) as client:
        response = client.post(
            "/api/platform-shell/chat-office-file-upload",
            files={
                "file": (
                    "template.xlsx",
                    original,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
        )
    assert response.status_code == 200, response.text
    upload = response.json()["data"]
    assert upload.get("upload_id"), response.text

    def forbid_model(*args, **kwargs):
        pytest.fail("the bundled writer/QC must not add a model planner")

    monkeypatch.setattr("app.application.employee_runtime.executor._cognition_fhd", forbid_model)
    monkeypatch.setattr(
        "app.application.employee_runtime.agent_runner._chat_completion", forbid_model
    )

    def orchestrator(repo):
        return AgentOrchestrator(
            repository=repo, tool_executor=SimpleNamespace(execute=AgentToolExecutor().execute)
        )

    bridge = XiaoxToolBridge(store, orchestrator(repository))
    queue = SQLAlchemyTaskExecutionRepository(session_factory=actor.factory)

    def invoke(call_id, params, tool="employee", action="execute"):
        spec = bridge.invoke(
            grant.mcp_token, "capability_describe", {"tool_id": tool, "action": action}
        )["capability"]
        return bridge.invoke(
            grant.mcp_token,
            "execute_action",
            {
                "tool_id": tool,
                "action": action,
                "params": params,
                "call_id": call_id,
                "schema_digest": spec["schema_digest"],
            },
        )

    def approve(receipt):
        child = repository.get(receipt["run_id"])
        approval = issue_approval_grant(child, principal_id=str(actor.user_id))
        approve_and_enqueue(
            repository,
            queue,
            run_id=child.run_id,
            token=approval["grant"],
            principal_id=str(actor.user_id),
            runtime_context=actor.context,
            authenticated_actor_binding=actor.context["_actor_authorization"],
        )
        claimed = queue.claim("workbook-worker", lease_seconds=30)
        assert claimed is not None
        AgentTaskDispatcher(
            execution_repository=queue, run_repository=repository, orchestrator_factory=orchestrator
        )._execute_claim(claimed, "workbook-worker")
        return repository.get(child.run_id)

    params = {
        "employee_id": WORKBOOK_WRITER,
        "task": "执行明确模板回填并保存公式",
        "input": {
            "template_path": upload["upload_id"],
            "plan": {
                "plan_version": 1,
                "protected_ranges": ["Data!D:D"],
                "phases": [
                    {
                        "phase": "cell_writes",
                        "writes": [
                            {"sheet": "Data", "ref": "A2", "value": "observed-name"},
                            {"sheet": "Data", "ref": "B2", "value": 5},
                        ],
                    },
                    {
                        "phase": "formula_writes",
                        "writes": [
                            {"sheet": "Data", "ref": "C2", "formula": "=B2*2"},
                        ],
                    },
                ],
            },
        },
    }
    set_agent_run_repository_for_tests(repository)
    try:
        yield SimpleNamespace(
            actor=actor,
            repository=repository,
            parent=parent,
            store=store,
            bridge=bridge,
            grant=grant,
            upload=upload,
            workspace_copy=workspace / upload["file_path"],
            original=original,
            params=params,
            invoke=invoke,
            approve=approve,
        )
    finally:
        set_agent_run_repository_for_tests(None)


def test_chat_upload_id_flows_through_reader_writer_and_independent_qc(workbook_runtime):
    state = workbook_runtime
    upload_id = state.upload["upload_id"]
    reader = "excel-full-read-employee"
    reader_input = {"upload_id": upload_id}
    reader_context = {
        **state.actor.context,
        "run_id": state.parent.run_id,
        "step_id": "read-upload",
        "node_id": "read-upload",
        "call_id": "read-upload",
        "input_sha256": hashlib.sha256(
            json.dumps(reader_input, sort_keys=True).encode()
        ).hexdigest(),
    }
    with tenant_scope(state.actor.tenant_id):
        with get_db() as db:
            owned_copy = Path(db.get(EltUpload, upload_id).storage_path)
        assert owned_copy.read_bytes() == state.workspace_copy.read_bytes() == state.original
        read = execute_employee_task_local(
            reader,
            "读取上传的工作簿",
            reader_input,
            user_id=state.actor.user_id,
            runtime_context=reader_context,
        )
        assert read["success"] is True, read
        [reader_output] = office_output_paths(reader, read)
        [reader_artifact] = read["artifacts"]
        assert reader_output == reader_artifact["uri"]
        assert reader_artifact["metadata"]["call_id"] == reader_context["call_id"]
        assert reader_artifact["metadata"]["owner_user_id"] == str(state.actor.user_id)
        reader_content = read_verified_run_file(state.parent.run_id, reader_artifact)
    [sheet] = json.loads(reader_content)["sheets"]
    assert sheet["name"] == "Data"
    cells = {(cell["row"], cell["col"]): cell["value"] for cell in sheet["cells"]}
    assert cells[2, 1] == "old"
    assert cells[2, 2] == 1
    pending = state.invoke("write", state.params)
    assert pending["pending_approval"] is True and not pending["artifacts"]
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
    receipt = state.store.receipt_snapshot(state.parent.run_id)[0]["receipt"]
    assert child.status == "completed" and receipt["verified"] is True, (child.error, receipt)
    [artifact] = receipt["artifacts"]
    raw = read_verified_run_file(child.run_id, artifact)
    from app.fastapi_routes.domains.agent.artifact_routes import router as artifact_router

    app = FastAPI()
    app.include_router(artifact_router)
    with TestClient(app, headers=state.actor.headers) as client:
        response = client.get(artifact["uri"])
    assert response.status_code == 200, response.text
    assert response.content == raw != state.original
    checks = receipt["verification"]["steps"][0]["checks"]
    quality = next(row["evidence"] for row in checks if row["source"] == "workbook_qc")
    assert quality["template_sha256"] == source_digest
    assert quality["artifact_sha256"] == hashlib.sha256(response.content).hexdigest()
    assert quality["sections"]["conformance"] == quality["sections"]["formulas"] == "pass"
    assert quality["formula_recalculation_verified"] is False
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


def test_independent_qc_rejects_unapproved_changes_with_valid_artifact_hash(
    workbook_runtime, monkeypatch
):
    from app.application.tools import workflow_spreadsheet_scope as scope

    state = workbook_runtime
    params = copy.deepcopy(state.params)
    params["input"]["plan"].pop("protected_ranges")
    publish = scope.publish_written_workbook
    changed = []

    def corrupt_before_publication(result, context, workspace):
        [path] = office_output_paths(WORKBOOK_WRITER, result)
        book = load_workbook(path)
        book["Data"]["D2"] = "not approved"
        font = copy.copy(book["Data"]["D2"].font)
        font.bold = True
        book["Data"]["D2"].font = font
        book.save(path)
        book.close()
        changed.append(Path(path).read_bytes())
        return publish(result, context, workspace)

    monkeypatch.setattr(scope, "publish_written_workbook", corrupt_before_publication)
    pending = state.invoke("unapproved-mutation", params)
    assert pending["pending_approval"] is True
    child = state.approve(pending)
    assert len(changed) == 1
    [call] = child.tool_calls
    assert call.output["success"] is True
    [artifact] = call.output["artifacts"]
    raw = read_verified_run_file(child.run_id, artifact)
    assert raw == changed[0]
    assert artifact["metadata"]["sha256"] == hashlib.sha256(raw).hexdigest()
    verification = call.metadata["verification"]
    assert verification["status"] == "failed", verification
    checks = verification["checks"]
    assert any(
        check["source"] == "run_artifact" and check["status"] == "passed" for check in checks
    ), checks
    quality = next(check for check in checks if check["source"] == "workbook_qc")
    assert quality["status"] == "failed"
    assert quality["evidence"]["sections"]["conformance"] == "fail"
    receipt = state.store.receipt_snapshot(state.parent.run_id)[0]["receipt"]
    assert child.status != "completed" and receipt.get("verified") is not True
    assert state.workspace_copy.read_bytes() == state.original


@pytest.mark.parametrize("override", ["workspace_root", "output_relpath", "template_relpath"])
def test_model_cannot_override_writer_paths_or_output_authority(workbook_runtime, override):
    state = workbook_runtime
    params = copy.deepcopy(state.params)
    params["input"][override] = "/outside/private.xlsx"
    result = state.invoke("invalid", params)
    assert result["status"] == "not_started"
    assert state.store.get(state.parent.run_id).metadata["calls"] == {}


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
