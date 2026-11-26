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
from urllib.parse import unquote

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook

from app.application.agent_orchestrator import set_agent_run_repository_for_tests
from app.application.agent_orchestrator.approval_grant import issue_approval_grant
from app.application.agent_orchestrator.approval_transaction import approve_and_enqueue
from app.application.agent_orchestrator.artifact_files import artifact_path, read_verified_run_file
from app.application.agent_orchestrator.attachment_inputs import resolve_attachment_inputs
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
from app.domain.task_lifecycle.execution_mode import CONTEXT_KEY
from app.domain.workbook_write_contract import WORKBOOK_READER, WORKBOOK_WRITER
from app.fastapi_routes.platform_shell_routes import router as platform_shell_router
from app.infrastructure.tenant_scope import tenant_scope
from app.infrastructure.xiaox.binding import XiaoxBindingError, XiaoxBindingStore
from app.infrastructure.xiaox.tools import XiaoxToolBridge
from app.mod_sdk.employee_tool_registry import office_output_paths
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


@pytest.fixture
def workbook_runtime(trusted_actor, monkeypatch, tmp_path, request):
    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path / "data"))
    workspace = tmp_path / "workspace"
    monkeypatch.setenv("WORKSPACE_ROOT", str(workspace))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("XCAGI_TOOL_IDEMPOTENCY_PATH", str(tmp_path / "idempotency.sqlite"))
    actor = trusted_actor(permissions=["employee.execute", "tool.excel_analysis.read"])
    level = getattr(request, "param", 3)
    chat_context = {}
    if isinstance(level, tuple):
        level, session = level
        from app.application.task_conversation_store import TaskConversationStore

        with tenant_scope(actor.tenant_id):
            TaskConversationStore().save_message(
                session_id=session, user_id=actor.user_id, role="user", content="Original turn",
            )
        chat_context = {
            "local_user_id": actor.user_id,
            "session_id": session,
            "conversation_id": session,
            "turn_id": "original-turn",
            "_conversation_revision": 0,
        }
    repository = SQLAlchemyAgentRunRepository(session_factory=actor.factory)
    parent = AgentRun(
        str(actor.user_id), "按原模板写入两格并保存公式，然后读回工作簿", status="running"
    )
    parent.metadata.update(
        runtime_type="xiaox",
        runtime_context={
            **actor.context,
            "execution_autonomy_level": level,
            **chat_context,
        },
    )
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
    attachments = resolve_attachment_inputs({**actor.context, "attachment_upload_ids": [upload["upload_id"]]})
    contract = build_goal_contract(parent, attachments=attachments)
    parent.metadata.update(runtime_goal_contract=contract, runtime_goal_digest=contract["digest"])
    repository.save(parent)
    store = XiaoxBindingStore(repository)
    grant = store.create(parent.run_id)

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
            queue=queue,
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
    changes = quality["cell_changes"]
    assert changes["scan_complete"] is True
    assert {example["ref"] for group in changes["groups"] for example in group["examples"]} == {
        "A2", "B2", "C2"
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
    assert unquote(response.headers["content-disposition"]) == f"attachment; filename*=UTF-8''{output_name}"
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


@pytest.mark.parametrize(("field", "value"), [
    ("workspace_root", "/outside/private.xlsx"),
    ("output_relpath", "/outside/private.xlsx"),
    ("template_relpath", "/outside/private.xlsx"),
    ("output_name", "../答题.xlsx"),
    ("output_name", r"其他目录\答题.xlsx"),
])
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
        "A2": "replace", "B2": "replace", "B6": "fill_blank",
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
        {"phase": "cell_writes", "writes": [
            {"sheet": "Data", "ref": "A1", "value": "Report"},
            {"sheet": "Data", "ref": "B3", "value": "1", "value_type": "number"},
        ]},
        {"phase": "formula_writes", "writes": [
            {"sheet": "Data", "ref": "C3", "formula": "=B3*2"},
        ]},
    ]
    result = state.invoke("edit", params)
    if result.get("pending_approval"):
        state.approve(result)
        result = state.store.receipt_snapshot(state.parent.run_id)[-1]["receipt"]
    child = state.repository.get(result.get("run_id", ""))
    assert result["status"] == "completed" and result["verified"] is True, (
        child.status, [call.metadata.get("verification") for call in child.tool_calls]
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
                "Report", "old", 1, "=B3*2", "protected", None,
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


def test_reverify_original_child_releases_scoped_file_without_dispatch(workbook_runtime, monkeypatch):
    from app.application.agent_orchestrator import verification_workbook
    from app.fastapi_routes.domains.agent import agent_routes, artifact_routes

    state = workbook_runtime
    parent = state.repository.get(state.parent.run_id)
    parent.metadata["runtime_context"]["chat_approval_mode"] = "auto"
    state.repository.save(parent)
    params = copy.deepcopy(state.params)
    params["input"]["plan"]["phases"] = [
        {"phase": "insert_rows", "sheet": "Data", "row": 1, "count": 1}
    ]
    real_qc = verification_workbook.verify_workbook

    def reject_first_qc(*args, **kwargs):
        report = real_qc(*args, **kwargs)
        assert report["status"] == "verified"
        report["checks"][-1]["status"] = "failed"
        return {**report, "status": "failed", "code": "result_workbook_qc_unmet"}

    with monkeypatch.context() as old_qc:
        old_qc.setattr(verification_workbook, "verify_workbook", reject_first_qc)
        receipt = state.invoke("write-once", params)
        if receipt.get("pending_approval"):
            state.approve(receipt)
            receipt = state.store.receipt_snapshot(state.parent.run_id)[0]["receipt"]
    child = state.repository.get(receipt["run_id"])
    assert child.status == "blocked" and not child.artifacts
    [call] = child.tool_calls
    [original] = call.output["artifacts"]
    original_bytes = read_verified_run_file(child.run_id, original)
    assert receipt["status"] == "unknown"
    assert state.store.get(parent.run_id).run.metadata["non_retryable"] is True
    assert child.metadata["runtime_context"]["parent_run_id"] == parent.run_id
    assert state.queue.get(child.run_id).state == "unknown"
    assert not state.queue.get(child.run_id).lease_owner

    def forbid_retry(*args, **kwargs):
        pytest.fail("rechecking an original file must not dispatch its graph")

    monkeypatch.setattr(AgentOrchestrator, "retry_run", forbid_retry)
    app = FastAPI()
    assert agent_routes.router is artifact_routes.router
    app.include_router(agent_routes.router)
    path = f"/api/agent/runs/{child.run_id}/verify"
    with TestClient(app) as anonymous:
        assert anonymous.post(path).status_code in (401, 403)
        assert anonymous.get(original["uri"]).status_code in (401, 403)
    with TestClient(app, headers=state.actor.headers) as client:
        assert client.get(original["uri"]).status_code == 404
        checked = client.post(path)
        assert checked.status_code == 200, checked.text
        assert checked.json()["verification"]["accepted"] is True
        downloaded = client.get(original["uri"])
    assert downloaded.status_code == 200 and downloaded.content == original_bytes
    assert hashlib.sha256(downloaded.content).hexdigest() == original["metadata"]["sha256"]
    reopened = state.repository.get(child.run_id)
    assert reopened.status == "blocked" and state.queue.get(child.run_id).state == "blocked"
    assert [artifact.artifact_id for artifact in reopened.artifacts] == [original["artifact_id"]]
    assert len(reopened.tool_calls) == 1 and not reopened.llm_calls
    assert reopened.tool_calls[0].output == call.output
    assert state.repository.get(parent.run_id).metadata["non_retryable"] is True


@pytest.mark.parametrize("workbook_runtime", [(1, "original-conversation")], indirect=True)
def test_interrupted_original_turn_shows_verified_file_without_replaying(workbook_runtime, monkeypatch):
    from app.application.ai_chat.conversation_history import persist_chat_turn
    from app.application.agent_runtime.chat import runtime_chat_payload
    from app.application.task_conversation_store import TaskConversationStore
    from app.domain.shared_services.conversation_service import ConversationService
    from app.domain.task_lifecycle.agent_runtime_contract import canonical_digest
    from app.fastapi_routes.domains.agent.artifact_routes import router as artifacts
    from app.infrastructure.xiaox.queued_runtime import stage_queued_request

    state = workbook_runtime
    parent = state.repository.get(state.parent.run_id)
    context = parent.metadata["runtime_context"]
    context["chat_approval_mode"] = "auto"
    state.repository.save(parent)
    params = copy.deepcopy(state.params)
    params["input"]["plan"]["phases"] = [
        {"phase": "set_column_width", "sheet": "Data", "column": "B", "width": 22},
    ]
    receipt = state.invoke("write-original", params)
    if receipt.get("pending_approval"):
        state.approve(receipt)
        receipt = state.store.receipt_snapshot(state.parent.run_id)[0]["receipt"]
    assert receipt["verified"] and receipt["status"] == "completed", receipt
    [artifact] = receipt["artifacts"]
    child = state.repository.get(receipt["run_id"])
    original = read_verified_run_file(child.run_id, artifact)

    session, turn = context["session_id"], context["turn_id"]
    request_key = canonical_digest({"turn_id": turn, "owner": parent.user_id})
    worker_turn = "queue_" + canonical_digest([parent.run_id, request_key])
    parent = state.repository.get(parent.run_id)
    parent.metadata["runtime_requests"] = {
        request_key: {"turn_id": turn, "state": "admitted"},
        canonical_digest({"turn_id": worker_turn, "owner": parent.user_id}): {
            "turn_id": worker_turn, "state": "admitted",
        },
    }
    queued = stage_queued_request(parent, request_key, {})
    ledger = parent.metadata["xiaox_runtime"]
    parent.metadata["_xiaox_queued_request"]["generation"] = ledger["generation"] - 1
    ledger.update(coordinator_active=False, revoked=True)
    parent.status = "failed"
    parent.metadata.update(non_retryable=True, recovery={"state": "manual_reconciliation_required"})
    state.repository.save(parent)
    state.queue.enqueue(parent, requested_by=parent.user_id)
    assert state.queue.claim("stopped-worker", lease_seconds=60).run_id == parent.run_id
    conversations = TaskConversationStore()
    with tenant_scope(state.actor.tenant_id):
        ack = persist_chat_turn("owner", "Original question", context, runtime_chat_payload(
            queued, conversation_id=session,
        ))
    assert ack["status"] == "saved"

    def fail_replay(*args, **kwargs):
        pytest.fail("history read must not dispatch or persist a replacement")
    monkeypatch.setattr(AgentOrchestrator, "retry_run", fail_replay)
    monkeypatch.setattr(XiaoxBindingStore, "claim_call", fail_replay)
    monkeypatch.setattr(ConversationService, "settle_queued_reply", fail_replay)

    def assistant(*, user_id=state.actor.user_id, tenant=state.actor.tenant_id, session_id=session):
        with tenant_scope(tenant):
            history = conversations.get_history(session_id=session_id, user_id=user_id, turn_id=turn)
        return next((row for row in history["messages"] if row["role"] == "assistant"), None)

    stale = assistant()
    assert json.loads(stale["metadata"])["summary"]["status"] == "queued"
    stopped = state.queue.finish(parent.run_id, "stopped-worker", "unknown", error_code="needs_verification")
    assert stopped.state == "unknown" and not stopped.lease_owner
    parent_before, child_before = state.repository.get(parent.run_id), state.repository.get(child.run_id)
    restored = assistant()
    assert assistant() == restored
    assert restored["id"] == stale["id"] and restored["content"] != stale["content"]
    meta = json.loads(restored["metadata"])
    assert meta["summary"]["status"] == "unknown" and meta["summary"]["success"] is False
    assert meta["ui"]["runtimeContinuation"]["runId"] is None
    assert meta["ui"]["execution"] == {"effect": "unknown", "outcome": "unknown"}
    [file] = meta["ui"]["outputArtifacts"]
    assert (file["run_id"], file["uri"], file["metadata"]["sha256"]) == (
        child.run_id, artifact["uri"], hashlib.sha256(original).hexdigest(),
    )
    assert state.repository.get(parent.run_id).to_dict() == parent_before.to_dict()
    assert state.repository.get(child.run_id).to_dict() == child_before.to_dict()
    assert state.queue.get(parent.run_id).to_dict() == stopped.to_dict()

    assert assistant(user_id=state.actor.user_id + 1) is None
    assert assistant(session_id="another-conversation") is None
    with tenant_scope(state.actor.tenant_id + 1):
        wrong_tenant = assistant(tenant=state.actor.tenant_id + 1)
    assert wrong_tenant is None or "outputArtifacts" not in json.loads(wrong_tenant["metadata"])["ui"]

    forged = copy.deepcopy(parent_before)
    call = next(iter(forged.metadata["xiaox_runtime"]["calls"].values()))
    call["child_task_id"] += "-forged"
    state.repository.save(forged)
    assert assistant() == stale
    state.repository.save(parent_before)
    assert assistant() == restored

    app = FastAPI()
    app.include_router(artifacts)
    with TestClient(app, headers=state.actor.headers) as client:
        assert client.get(file["uri"]).content == original
        artifact_path(child.run_id, artifact["artifact_id"]).write_bytes(b"damaged original result")
        assert client.get(file["uri"]).status_code == 410
        assert assistant() == stale
    with tenant_scope(state.actor.tenant_id):
        persisted = conversations.get_conversation(session_id=session, user_id=state.actor.user_id)
    original_message = next(row for row in persisted["messages"] if row["role"] == "assistant")
    assert original_message == stale


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
