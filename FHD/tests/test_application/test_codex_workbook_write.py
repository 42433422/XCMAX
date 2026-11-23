"""Owned workbook -> approved bundled writer -> independent QC -> next action.

Fixtures are synthetic workbooks, not the unavailable original customer corpus.
"""

from __future__ import annotations

import copy
import io
from types import SimpleNamespace

import pytest
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
from app.application.elt.service_uploads import UploadServiceMixin
from app.db.models.elt import EltUpload
from app.db.session import get_db
from app.domain.task_lifecycle.agent_runtime_contract import build_goal_contract
from app.domain.workbook_write_contract import WORKBOOK_WRITER
from app.infrastructure.codex.binding import CodexBindingError, CodexBindingStore
from app.infrastructure.codex.tools import CodexToolBridge
from app.infrastructure.tenant_scope import tenant_scope
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


@pytest.fixture
def workbook_runtime(trusted_actor, monkeypatch, tmp_path):
    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("XCAGI_TOOL_IDEMPOTENCY_PATH", str(tmp_path / "idempotency.sqlite"))
    actor = trusted_actor(permissions=["employee.execute", "tool.excel_analysis.read"])
    repository = SQLAlchemyAgentRunRepository(session_factory=actor.factory)
    set_agent_run_repository_for_tests(repository)
    parent = AgentRun(
        str(actor.user_id), "按原模板写入两格并保存公式，然后读回工作簿", status="running"
    )
    parent.metadata.update(runtime_type="codex", runtime_context=actor.context)
    contract = build_goal_contract(parent)
    parent.metadata.update(runtime_goal_contract=contract, runtime_goal_digest=contract["digest"])
    repository.save(parent)
    store = CodexBindingStore(repository)
    grant = store.create(parent.run_id)
    book = Workbook()
    sheet = book.active
    sheet.title = "Data"
    sheet["A1"], sheet["B1"], sheet["C1"] = "name", "amount", "formula"
    sheet["A2"], sheet["B2"], sheet["D2"] = "old", 1, "protected"
    content = io.BytesIO()
    book.save(content)
    book.close()
    content.seek(0)
    with tenant_scope(actor.tenant_id), get_db() as db:
        upload = UploadServiceMixin().save_upload(
            db,
            owner_user_id=actor.user_id,
            file_name="template.xlsx",
            content_type=None,
            stream=content,
        )

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

    bridge = CodexToolBridge(store, orchestrator(repository))
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
    try:
        yield SimpleNamespace(
            actor=actor,
            repository=repository,
            parent=parent,
            store=store,
            bridge=bridge,
            grant=grant,
            upload=upload,
            params=params,
            invoke=invoke,
            approve=approve,
        )
    finally:
        set_agent_run_repository_for_tests(None)


def test_actual_owned_writer_and_independent_qc_publish_reusable_original_artifact(
    workbook_runtime,
):
    state = workbook_runtime
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
    with io.BytesIO(content) as stream:
        book = load_workbook(stream, data_only=False)
        assert book["Data"]["A2"].value == "observed-name"
        assert book["Data"]["B2"].value == 5
        assert book["Data"]["C2"].value == "=B2*2"
        assert book["Data"]["D2"].value == "protected"
        book.close()
    checks = receipt["verification"]["steps"][0]["checks"]
    quality = next(row["evidence"] for row in checks if row["source"] == "workbook_qc")
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
    assert len(child.tool_calls) == 1 and not child.llm_calls


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
    with pytest.raises((CodexBindingError, PermissionError, ValueError)):
        # Opening a previous file needs its original bytes and verified scope;
        # no supplied URI alone grants filesystem authority.
        from app.infrastructure.codex.receipts import read_action_artifact

        current = state.repository.get(child.run_id)
        read_action_artifact(
            artifact["uri"], {**current.metadata["runtime_context"], "run_id": current.run_id}
        )
