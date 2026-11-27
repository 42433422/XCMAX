"""Owned workbook, approved bundled writer and original SQL/QC fixture.

Synthetic workbooks are not customer answer artifacts."""

from __future__ import annotations

import io
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.application.agent_orchestrator import set_agent_run_repository_for_tests
from app.application.agent_orchestrator.approval_grant import issue_approval_grant
from app.application.agent_orchestrator.approval_transaction import approve_and_enqueue
from app.application.agent_orchestrator.attachment_inputs import resolve_attachment_inputs
from app.application.agent_orchestrator.orchestrator import AgentOrchestrator
from app.application.agent_orchestrator.run_models import AgentRun
from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
from app.application.agent_orchestrator.task_dispatcher import AgentTaskDispatcher
from app.application.agent_orchestrator.task_execution_sql_repository import (
    SQLAlchemyTaskExecutionRepository,
)
from app.application.agent_orchestrator.tool_executor import AgentToolExecutor
from app.domain.task_lifecycle.agent_runtime_contract import build_goal_contract
from app.domain.workbook_write_contract import WORKBOOK_WRITER
from app.fastapi_routes.platform_shell_routes import router as platform_shell_router
from app.infrastructure.tenant_scope import tenant_scope
from app.infrastructure.xiaox.binding import XiaoxBindingStore
from app.infrastructure.xiaox.tools import XiaoxToolBridge
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
    # These original scenarios verify approved writes and formula preservation.
    # A host without Calc must retain that receipt while stating that numerical
    # recalculation is unverified. Real-engine coverage lives in its own suite.
    monkeypatch.setattr(
        "app.application.agent_orchestrator.workbook_recalculation._engine_path", lambda: None
    )
    actor = trusted_actor(permissions=["employee.execute", "tool.excel_analysis.read"])
    level = getattr(request, "param", 3)
    chat_context = {}
    if isinstance(level, tuple):
        level, session = level
        from app.application.task_conversation_store import TaskConversationStore

        with tenant_scope(actor.tenant_id):
            TaskConversationStore().save_message(
                session_id=session,
                user_id=actor.user_id,
                role="user",
                content="Original turn",
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
    attachments = resolve_attachment_inputs(
        {**actor.context, "attachment_upload_ids": [upload["upload_id"]]}
    )
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
