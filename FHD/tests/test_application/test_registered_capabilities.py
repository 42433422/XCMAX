"""Regression coverage for the config-driven ERP Agent capability tool."""

from __future__ import annotations

import json
from decimal import Decimal
from unittest.mock import Mock

import pytest

from app.application.workflow.approval_persistence import SNAPSHOT_KEY
from app.application.workflow.workflow_types import plan_fingerprint, plan_from_dict
from app.db.models.approval import ApprovalRequest
from tests.test_application.test_approval_persistence import db as db


@pytest.fixture
def capability_runner(monkeypatch):
    from app.application.agent_orchestrator import AgentOrchestrator, InMemoryAgentRunRepository

    runner = AgentOrchestrator(repository=InMemoryAgentRunRepository())
    execute = Mock()

    def finish(run_id):
        run = runner.get_run(run_id)
        execute(run_id)
        run.status = "completed"
        run.steps[0].status = "completed"
        run.steps[0].output = {"success": True, "data": {"confirmed": True}}
        return runner.save_run(run)

    monkeypatch.setattr(runner, "execute_dispatched_run", finish)
    monkeypatch.setattr("app.application.agent_orchestrator.AgentOrchestrator", lambda: runner)
    return runner, execute


def test_registered_capability_atomically_binds_one_run_before_execution(
    capability_runner, monkeypatch
):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from app.application.tools.registered_capabilities import execute_registered_capability
    from app.infrastructure.tenant_scope import tenant_scope

    runner, execute = capability_runner
    original_create = runner.create_task_run
    barrier = Barrier(2)

    def claim(run):
        barrier.wait(timeout=5)
        return original_create(run)

    monkeypatch.setattr(runner, "create_task_run", claim)
    context = {
        "user_id": "owner",
        "tenant_id": 1,
        "session_id": "conversation",
        "turn_id": "turn",
        "call_id": "call",
        "task_id": "parent-task",
        "run_id": "parent-run",
    }

    def call():
        with tenant_scope(1):
            return json.loads(
                execute_registered_capability(
                    {"tool_id": "print", "action": "list", "params": {}}, runtime_context=context
                )
            )

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(lambda _: call(), range(2)))
    assert {item["deduplicated"] for item in results} == {True, False}
    assert len({item["agent_run_id"] for item in results}) == 1
    assert len({item["task_id"] for item in results}) == 1
    execute.assert_called_once()
    original = runner.get_run(results[0]["agent_run_id"])
    runtime = original.metadata["runtime_context"]
    assert runtime["parent_task_id"] == "parent-task"
    assert runtime["parent_run_id"] == "parent-run"
    assert original.metadata["task_request_fingerprint"]
    monkeypatch.setattr(runner, "create_task_run", original_create)
    repeated = call()
    assert repeated["success"] is True
    assert repeated["execution_state"] == "completed"
    assert repeated["agent_run_id"] == original.run_id
    execute.assert_called_once()


@pytest.mark.parametrize(
    "change",
    [
        "params",
        "tool",
        "action",
        "mod_id",
        "employee_id",
        "employee_tool_allowlist",
        "workspace_id",
        "mutation_policy",
    ],
)
def test_registered_identity_conflict_cannot_dispatch_different_content(capability_runner, change):
    from app.application.tools.registered_capabilities import execute_registered_capability

    runner, execute = capability_runner
    context = {
        "user_id": "owner",
        "tenant_id": 1,
        "session_id": "conversation",
        "turn_id": "turn",
        "call_id": "call",
    }
    args = {"tool_id": "print", "action": "list", "params": {}}
    original = json.loads(execute_registered_capability(args, runtime_context=context))
    if change == "params":
        args["params"] = {"filter": "changed"}
    elif change == "tool":
        args["tool_id"] = "shipment_records"
    elif change == "action":
        args["action"] = "query"
    else:
        context[change] = ["print"] if change == "employee_tool_allowlist" else "changed"
    response = json.loads(execute_registered_capability(args, runtime_context=context))
    assert response["success"] is False
    assert response["error_code"] == "task_idempotency_conflict"
    assert runner.get_run(original["agent_run_id"]).steps[0].params == {}
    assert len(runner.list_runs(user_id="owner")) == 1
    execute.assert_called_once()


def test_registered_missing_write_identity_is_rejected_and_legacy_read_is_addressable(
    capability_runner,
):
    from app.application.tools.registered_capabilities import execute_registered_capability

    _, execute = capability_runner
    context = {"user_id": "owner", "tenant_id": 1}
    write = json.loads(
        execute_registered_capability(
            {
                "tool_id": "print",
                "action": "print_document",
                "params": {"file_path": "invoice.pdf"},
            },
            runtime_context=context,
        )
    )
    assert write["error_code"] == "task_identity_required"
    execute.assert_not_called()
    read = json.loads(
        execute_registered_capability(
            {"tool_id": "print", "action": "list", "params": {}}, runtime_context=context
        )
    )
    assert read["success"] and read["task_id"] and read["run_id"]
    assert read["idempotency_scope"] == "original_task_only"
    assert read["retryable"] is False


@pytest.mark.parametrize("state", ["queued", "blocked", "unknown", "waiting_approval"])
def test_registered_completed_outer_keeps_nested_business_state(
    capability_runner, monkeypatch, state
):
    from app.application.tools.registered_capabilities import execute_registered_capability

    runner, _ = capability_runner

    def finish(run_id):
        run = runner.get_run(run_id)
        run.status = "completed"
        run.steps[0].status = "completed"
        run.steps[0].output = {"success": True}
        run.final_output = {
            "business_result": {
                "protocol": "xcagi.business-harness.v1",
                "success": True,
                "execution_state": state,
            }
        }
        return runner.save_run(run)

    monkeypatch.setattr(runner, "execute_dispatched_run", finish)
    result = json.loads(
        execute_registered_capability(
            {"tool_id": "print", "action": "list", "params": {}},
            runtime_context={"user_id": "owner", "tenant_id": 1, "turn_id": "turn"},
        )
    )
    assert result["success"] is False
    assert result["execution_state"] == state
    assert result["run_id"] and result["task_id"]


def test_registered_uncertain_wait_cannot_create_another_approval(capability_runner, monkeypatch):
    from app.application.tools.registered_capabilities import execute_registered_capability

    runner, _ = capability_runner
    approvals = Mock()
    approvals.get_approval_required_nodes.side_effect = lambda plan: plan.nodes
    monkeypatch.setattr("app.application.workflow.get_approval_service", lambda: approvals)

    def interrupted(run_id):
        run = runner.get_run(run_id)
        run.status = run.steps[0].status = "waiting_user"
        run.final_output = {"business_result": {"outcome_unknown": True}}
        return runner.save_run(run)

    monkeypatch.setattr(runner, "execute_dispatched_run", interrupted)
    result = json.loads(
        execute_registered_capability(
            {"tool_id": "print", "action": "list", "params": {}},
            runtime_context={"user_id": "owner", "tenant_id": 1, "turn_id": "turn"},
        )
    )
    assert result["execution_state"] == "unknown"
    assert result["requires_reconciliation"] is True
    approvals.create_approval_request.assert_not_called()


def test_registered_executor_exception_keeps_original_unknown_without_redispatch(
    capability_runner, monkeypatch
):
    from app.application.tools.registered_capabilities import execute_registered_capability

    runner, _ = capability_runner
    execute = Mock(side_effect=RuntimeError("worker lost receipt"))
    monkeypatch.setattr(runner, "execute_dispatched_run", execute)
    replies = [
        json.loads(
            execute_registered_capability(
                {"tool_id": "print", "action": "list", "params": {}},
                runtime_context={"user_id": "owner", "tenant_id": 1, "turn_id": "turn"},
            )
        )
        for _ in range(2)
    ]
    assert replies[0]["run_id"] == replies[1]["run_id"]
    assert all(item["execution_state"] == "unknown" for item in replies)
    assert all(item["retryable"] is False for item in replies)
    run = runner.get_run(replies[0]["run_id"])
    assert run.metadata["recovery"]["state"] == "manual_reconciliation_required"
    execute.assert_called_once()


@pytest.mark.parametrize("terminal", ["completed", "failed", "cancelled", "rejected"])
def test_worker_exception_does_not_overwrite_terminal_race(
    capability_runner, monkeypatch, terminal
):
    from app.application.agent_orchestrator import AgentRun

    runner, _ = capability_runner
    original = runner.save_run(AgentRun(user_id="owner", message="task", status="running"))
    compare_save = runner._repo.save_if_unchanged

    def finish_before_failed_receipt(run, previous):
        winner = runner.get_run(run.run_id)
        winner.status = terminal
        runner.save_run(winner)
        return compare_save(run, previous)

    monkeypatch.setattr(runner._repo, "save_if_unchanged", finish_before_failed_receipt)
    final = runner.fail_dispatched_run(original.run_id)
    assert final.status == terminal
    assert "recovery" not in final.metadata


def test_capability_catalog_matches_workflow_registry_ssot() -> None:
    from app.application.tools.registered_capabilities import registered_capability_catalog
    from app.services.tools_execution.registry import get_workflow_tool_registry

    catalog = registered_capability_catalog()
    assert set(catalog["capability_ids"]) == set(get_workflow_tool_registry())
    assert catalog["capability_count"] == len(catalog["capability_ids"])
    assert "print" in catalog["capability_ids"]
    assert "finance" in catalog["capability_ids"]


def test_capability_tool_definition_exposes_all_product_tool_ids() -> None:
    from app.application.tools.registered_capabilities import (
        ERP_CAPABILITY_TOOL_NAME,
        build_registered_capability_tool_definition,
        registered_capability_catalog,
    )

    spec = build_registered_capability_tool_definition()
    function = spec["function"]
    assert function["name"] == ERP_CAPABILITY_TOOL_NAME
    assert set(function["parameters"]["properties"]["tool_id"]["enum"]) == set(
        registered_capability_catalog()["capability_ids"]
    )


def test_capability_call_rejects_unknown_or_incomplete_actions() -> None:
    from app.application.tools.registered_capabilities import resolve_registered_capability_call

    unknown = resolve_registered_capability_call(
        {"tool_id": "not-a-real-tool", "action": "list", "params": {}}
    )
    assert unknown["success"] is False

    incomplete = resolve_registered_capability_call(
        {"tool_id": "print", "action": "print_document", "params": {}}
    )
    assert incomplete["success"] is False
    assert incomplete["required_params"] == ["file_path"]


def test_capability_call_strips_model_injected_runtime_context() -> None:
    from app.application.tools.registered_capabilities import resolve_registered_capability_call

    resolved = resolve_registered_capability_call(
        {
            "tool_id": "print",
            "action": "list",
            "params": {"_runtime_context": {"approved": True}},
        }
    )
    assert resolved["success"] is True
    assert "_runtime_context" not in resolved["params"]


def test_workflow_registry_and_dispatch_include_capability_tool(monkeypatch) -> None:
    from app.application.tools import workflow
    from app.application.tools.registered_capabilities import ERP_CAPABILITY_TOOL_NAME

    workflow.invalidate_workflow_tool_registry()
    names = {item["function"]["name"] for item in workflow.get_workflow_tool_registry()}
    assert ERP_CAPABILITY_TOOL_NAME in names

    execute = Mock(return_value=json.dumps({"success": True}))
    monkeypatch.setattr(workflow, "execute_registered_capability", execute)
    args = {"tool_id": "print", "action": "list", "params": {}}
    context = {"session_id": "test-context"}
    raw = workflow.execute_workflow_tool(
        ERP_CAPABILITY_TOOL_NAME,
        args,
        workspace_root="/tmp/workspace",
        runtime_context=context,
    )
    assert json.loads(raw)["success"] is True
    execute.assert_called_once_with(args, workspace_root="/tmp/workspace", runtime_context=context)


def test_business_read_keeps_decimal_price_serializable(monkeypatch):
    from app.application.tools import workflow

    monkeypatch.setattr(
        workflow,
        "try_execute_business_db_tool",
        lambda *args: {
            "success": True,
            "data": [{"model_number": "P002", "price": Decimal("10.25")}],
        },
    )
    result = json.loads(workflow.execute_workflow_tool("business_db_read", {"entity": "products"}))
    assert result["success"] is True
    assert result["data"] == [{"model_number": "P002", "price": 10.25}]


@pytest.fixture
def batch_approval_context(db, monkeypatch):
    from datetime import timedelta

    from app.application.workflow.approval_service import ApprovalService
    from app.db.models.user import Session as UserSession
    from app.db.models.user import User
    from app.infrastructure.auth.agent_mod_scope import bind_agent_actor_scope
    from app.infrastructure.tenant_scope import tenant_scope
    from app.utils.time import utc_now_naive

    monkeypatch.setattr("app.db.HostSessionLocal", db)
    # Each invocation has an empty in-memory approval service, as after a restart.
    monkeypatch.setattr("app.application.workflow.get_approval_service", ApprovalService)
    with tenant_scope(1):
        with db.begin() as session:
            session.add(User(id=1, username="first", password="x", role="admin", tenant_id=1))
            session.add(
                UserSession(
                    session_id="session", user_id=1, expires_at=utc_now_naive() + timedelta(hours=1)
                )
            )
        yield {
            "local_user_id": 1,
            "user_id": "1",
            "tenant_id": 1,
            "turn_id": "same-turn",
            "session_id": "conversation",
            "_actor_authorization": bind_agent_actor_scope(session_id="session", user_id="1"),
        }


def _batch_call(context, tool="products"):
    from app.application.tools.registered_capabilities import execute_registered_capability

    return json.loads(
        execute_registered_capability(
            {"tool_id": tool, "action": "batch_delete", "params": {"ids": [1]}},
            runtime_context=context,
        )
    )


@pytest.mark.parametrize("tool", ["products", "customers"])
def test_independent_batch_calls_in_one_turn_have_distinct_durable_approvals(
    db, batch_approval_context, tool
):
    from app.application.agent_orchestrator.run_repository import get_agent_run_repository

    contexts = [{**batch_approval_context, "call_id": value} for value in ("call-a", "call-b")]
    receipts = [_batch_call(context, tool) for context in contexts]
    assert all(item.get("pending_approval") for item in receipts), receipts
    for key in ("task_id", "agent_run_id", "approval_request_id"):
        assert len({item[key] for item in receipts}) == 2
    for context, original in zip(contexts, receipts, strict=True):
        repeated = _batch_call(context, tool)
        assert repeated["deduplicated"] is True
        assert repeated["agent_run_id"] == original["agent_run_id"]
        assert repeated["approval_request_id"] == original["approval_request_id"]
        assert repeated["pending_approval"] is True
        run = get_agent_run_repository().get(original["agent_run_id"])
        assert run.metadata["approval_request_id"] == original["approval_request_id"]
    with db() as session:
        assert session.query(ApprovalRequest).count() == 2


@pytest.mark.parametrize("identity", ["legacy_hash", "stored_opaque_id"])
@pytest.mark.parametrize(
    "drift", [None, "run", "step", "plan", "owner", "tenant", "mod", "session"]
)
def test_legacy_batch_approval_is_read_only_and_bound_to_original_execution(
    db, batch_approval_context, monkeypatch, identity, drift
):
    import hashlib
    from unittest.mock import Mock

    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.agent_orchestrator.run_repository import get_agent_run_repository
    from app.application.workflow.approval_service import ApprovalService

    context = {**batch_approval_context, "call_id": "original-call"}
    original = _batch_call(context)
    assert original.get("pending_approval"), original
    legacy_id = (
        hashlib.sha256(
            json.dumps(
                [1, "1", context["turn_id"], "products", "batch_delete"], ensure_ascii=False
            ).encode()
        ).hexdigest()
        if identity == "legacy_hash"
        else "persisted-before-task-approval-binding"
    )
    repository = get_agent_run_repository()
    run = repository.get(original["agent_run_id"])
    run.metadata.pop("approval_request_id")
    repository.save(run)
    before_run = repository.get(run.run_id).to_dict()
    with db.begin() as session:
        row = (
            session.query(ApprovalRequest)
            .filter_by(request_no=original["approval_request_id"])
            .one()
        )
        row.request_no = legacy_id
        data = json.loads(row.business_data)
        snapshot = data[SNAPSHOT_KEY]
        if drift == "run":
            data["agent_run_id"] = snapshot["agent_run_id"] = "another-run"
        elif drift == "step":
            data["approved_step_id"] = snapshot["approved_step_id"] = "another-step"
        elif drift == "plan":
            data["plan_id"] = snapshot["plan_id"] = snapshot["plan"]["plan_id"] = "another-plan"
            snapshot["plan_sha256"] = plan_fingerprint(plan_from_dict(snapshot["plan"]))
        elif drift == "owner":
            row.applicant_id = 2
        elif drift == "tenant":
            row.tenant_id = snapshot["tenant_id"] = 2
        elif drift == "mod":
            snapshot["runtime_context"]["mod_id"] = "another-mod"
        elif drift == "session":
            snapshot["runtime_context"]["session_id"] = "another-conversation"
        row.business_data = json.dumps(data, ensure_ascii=False)
        before_approval = row.business_data
    forbidden = Mock(
        side_effect=AssertionError("approval replay must only read the original binding")
    )
    monkeypatch.setattr(AgentOrchestrator, "execute_dispatched_run", forbidden)
    monkeypatch.setattr(ApprovalService, "create_approval_request", forbidden)
    monkeypatch.setattr(ApprovalService, "attach_pending_agent_run", forbidden)
    for _ in range(2):
        repeated = _batch_call(context)
        if repeated.get("error_code") == "legacy_approval_identity_unverified":
            assert not repeated.get("agent_run_id")
        else:
            assert repeated["agent_run_id"] == original["agent_run_id"]
            assert repeated["deduplicated"] is True
        assert repeated["success"] is False
        if drift:
            assert not repeated.get("pending_approval")
            assert repeated["execution_state"] == "unknown"
            assert repeated["requires_reconciliation"] is True
        else:
            assert repeated["pending_approval"] is True
            assert repeated["approval_request_id"] == legacy_id
    forbidden.assert_not_called()
    assert repository.get(run.run_id).to_dict() == before_run
    from app.infrastructure.tenant_scope import tenant_scope

    with tenant_scope(2 if drift == "tenant" else 1), db() as session:
        rows = session.query(ApprovalRequest).all()
        assert len(rows) == 1 and rows[0].request_no == legacy_id
        assert rows[0].business_data == before_approval


def test_persisted_approval_pointer_cannot_read_another_call_approval(
    db, batch_approval_context, monkeypatch
):
    from unittest.mock import Mock

    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.agent_orchestrator.run_repository import get_agent_run_repository
    from app.application.workflow.approval_service import ApprovalService

    contexts = [{**batch_approval_context, "call_id": value} for value in ("original", "other")]
    original, other = [_batch_call(context) for context in contexts]
    assert original.get("pending_approval") and other.get("pending_approval")
    repository = get_agent_run_repository()
    run = repository.get(original["agent_run_id"])
    run.metadata["approval_request_id"] = other["approval_request_id"]
    repository.save(run)
    forbidden = Mock(side_effect=AssertionError("an invalid binding cannot create or dispatch"))
    monkeypatch.setattr(AgentOrchestrator, "execute_dispatched_run", forbidden)
    monkeypatch.setattr(ApprovalService, "create_approval_request", forbidden)
    repeated = _batch_call(contexts[0])
    assert repeated["execution_state"] == "unknown"
    assert repeated["requires_reconciliation"] is True
    assert not repeated.get("pending_approval")
    forbidden.assert_not_called()
    with db() as session:
        assert session.query(ApprovalRequest).count() == 2


@pytest.mark.parametrize(
    "scenario",
    [
        "waiting",
        "completed",
        "completed_pointer_conflict",
        "missing_call",
        "missing_session",
        "different_call",
        "different_params",
    ],
)
def test_pre_unified_batch_run_is_read_before_any_new_task_can_be_published(
    db, batch_approval_context, monkeypatch, scenario
):
    import hashlib

    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.agent_orchestrator.run_repository import get_agent_run_repository
    from app.application.workflow.approval_service import ApprovalService
    from app.application.workflow.workflow_types import PlanGraph, WorkflowNode

    context = {**batch_approval_context, "call_id": "original-call"}
    old_context = dict(context)
    if scenario == "missing_call":
        old_context.pop("call_id")
    elif scenario == "missing_session":
        old_context.pop("session_id")
    legacy_id = hashlib.sha256(
        json.dumps(
            [1, "1", context["turn_id"], "products", "batch_delete"], ensure_ascii=False
        ).encode()
    ).hexdigest()
    node = WorkflowNode(
        "registered_capability", "products", "batch_delete", {"ids": [1]}, risk="high"
    )
    plan = PlanGraph(
        plan_id=f"erp-capability-{legacy_id}",
        intent="delete products",
        nodes=[node],
        metadata={"approval_required_node_ids": [node.node_id]},
    )
    orchestrator = AgentOrchestrator()
    original = orchestrator.start_run_from_plan(
        user_id="1",
        message="delete products",
        plan=plan,
        runtime_context=old_context,
        auto_execute=True,
    )
    assert original.status == "waiting_user"
    assert "task_request_fingerprint" not in original.metadata
    assert "approval_request_id" not in original.metadata
    assert not str((original.metadata.get("task_context") or {}).get("task_id") or "").startswith(
        "task_erp_"
    )
    approvals = ApprovalService()
    approvals.create_approval_request(
        plan_id=plan.plan_id,
        node=node,
        runtime_context=old_context,
        plan=plan,
        require_persistence=True,
        request_id=legacy_id,
    )
    assert approvals.attach_pending_agent_run(
        legacy_id, agent_run_id=original.run_id, approved_step_id=node.node_id
    )
    repository = get_agent_run_repository()
    if scenario in {"completed", "completed_pointer_conflict"}:
        original.status = original.steps[0].status = "completed"
        original.steps[0].output = {"success": True, "deleted": 1}
        if scenario == "completed_pointer_conflict":
            original.metadata["approval_request_id"] = "another-approval"
        repository.save(original)
        with db.begin() as session:
            row = session.query(ApprovalRequest).filter_by(request_no=legacy_id).one()
            row.status = "approved"
            data = json.loads(row.business_data)
            data["workflow_execution"] = {"success": True, "workflow_executed": True}
            row.business_data = json.dumps(data)
    before = repository.get(original.run_id).to_dict()
    forbidden = Mock(
        side_effect=AssertionError("legacy replay cannot publish, dispatch or reapprove")
    )
    monkeypatch.setattr(AgentOrchestrator, "create_task_run", forbidden)
    monkeypatch.setattr(AgentOrchestrator, "start_run_from_plan", forbidden)
    monkeypatch.setattr(AgentOrchestrator, "execute_dispatched_run", forbidden)
    monkeypatch.setattr(ApprovalService, "create_approval_request", forbidden)
    monkeypatch.setattr(ApprovalService, "attach_pending_agent_run", forbidden)
    if scenario == "different_call":
        context["call_id"] = "another-call"
    if scenario == "different_params":
        from app.application.tools.registered_capabilities import execute_registered_capability

        result = json.loads(
            execute_registered_capability(
                {"tool_id": "products", "action": "batch_delete", "params": {"ids": [2]}},
                runtime_context=context,
            )
        )
    else:
        result = _batch_call(context)
    if scenario in {"waiting", "completed"}:
        assert result["agent_run_id"] == original.run_id
        assert result["approval_request_id"] == legacy_id
        assert result["success"] is (scenario == "completed")
        assert result["execution_state"] == (
            "completed" if scenario == "completed" else "waiting_approval"
        )
    else:
        assert result["execution_state"] == "unknown"
        assert result["error_code"] == "legacy_approval_identity_unverified"
        assert result["requires_reconciliation"] is True
    forbidden.assert_not_called()
    assert repository.get(original.run_id).to_dict() == before
    with db() as session:
        assert session.query(ApprovalRequest).count() == 1
