"""Dynamic discovery and concrete actions retain the original SQL receipts and approvals."""

from __future__ import annotations

import copy
from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.application.agent_orchestrator.orchestrator import AgentOrchestrator
from app.application.agent_orchestrator.run_models import AgentRun
from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
from app.application.agent_orchestrator.tool_executor import AgentToolExecutor
from app.application.agent_orchestrator.tool_spec import get_tool_action_spec
from app.domain.task_lifecycle.agent_runtime_contract import build_goal_contract
from app.infrastructure.xiaox.binding import XiaoxBindingError, XiaoxBindingStore
from app.infrastructure.xiaox.tools import XiaoxToolBridge
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


@pytest.fixture
def dynamic_runtime(trusted_actor, monkeypatch, tmp_path):
    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    actor = trusted_actor(
        permissions=[
            "product.view",
            "customer.view",
            "customer.edit",
            "tool.excel_analyzer.analyze",
        ]
    )
    repository = SQLAlchemyAgentRunRepository(session_factory=actor.factory)
    parent = AgentRun(
        user_id=str(actor.user_id), message="查看产品后按结果处理客户", status="running"
    )
    parent.metadata.update(runtime_type="xiaox", runtime_context=actor.context)
    contract = build_goal_contract(parent)
    parent.metadata.update(runtime_goal_contract=contract, runtime_goal_digest=contract["digest"])
    repository.save(parent)
    store = XiaoxBindingStore(repository)
    grant = store.create(parent.run_id)
    executor = AgentToolExecutor()
    orchestrator = AgentOrchestrator(
        repository=repository, tool_executor=SimpleNamespace(execute=executor.execute)
    )
    bridge = XiaoxToolBridge(store, orchestrator)

    def describe(tool="products", action="query"):
        return bridge.invoke(
            grant.mcp_token, "capability_describe", {"tool_id": tool, "action": action}
        )["capability"]

    def execute(call, params, tool="products", action="query", **extra):
        capability = describe(tool, action)
        return bridge.invoke(
            grant.mcp_token,
            "execute_action",
            {
                "tool_id": tool,
                "action": action,
                "call_id": call,
                "params": params,
                "schema_digest": capability["schema_digest"],
                **extra,
            },
        )

    return SimpleNamespace(
        actor=actor,
        repository=repository,
        store=store,
        parent=parent,
        grant=grant,
        bridge=bridge,
        describe=describe,
        execute=execute,
        executor=executor,
    )


def test_discovery_is_authorized_paginated_and_returns_the_exact_contract(dynamic_runtime):
    state = dynamic_runtime
    first = state.bridge.invoke(state.grant.mcp_token, "capability_search", {"limit": 1})
    second = state.bridge.invoke(
        state.grant.mcp_token, "capability_search", {"limit": 1, "offset": first["next_offset"]}
    )
    assert first["capabilities"] != second["capabilities"]
    assert first["total"] == second["total"] >= 2
    assert all(
        row["tool_id"] != "materials" for row in first["capabilities"] + second["capabilities"]
    )
    capability = state.describe()
    spec = get_tool_action_spec("products", "query")
    assert capability["input_schema"] == spec.input_schema
    assert capability["output_schema"] == spec.output_schema
    assert capability["schema_digest"] == spec.schema_digest
    assert state.store.get(state.parent.run_id).metadata["calls"] == {}


def test_mcp_thread_reads_current_sql_parent_budget_before_running_action(
    dynamic_runtime, monkeypatch
):
    import time

    from app.application.tool_execution_deadline import remaining_invocation_seconds

    state = dynamic_runtime
    now = time.time()
    state.store.update(
        state.parent.run_id,
        lambda run, metadata: metadata.update(active_started_at=now, deadline_at=now + 2.0),
    )
    observed = []

    def dispatch(tool, action, params):
        observed.append(remaining_invocation_seconds(60))
        return {"success": True, "data": []}

    monkeypatch.setattr(
        "app.application.facades.tools_facade.execute_registered_workflow_tool", dispatch
    )
    result = state.execute("read-with-budget", {})
    assert result["verified"] is True
    assert len(observed) == 1 and 0 < observed[0] <= 2
    assert remaining_invocation_seconds(60) == 60


def test_renderer_navigation_is_searchable_only_on_its_own_run_and_never_executable(
    dynamic_runtime,
):
    from app.application.agent_runtime.gateway import _trusted_context

    state = dynamic_runtime
    entry = {
        "id": "sample-entry",
        "kind": "user_action",
        "label": "项目归档",
        "breadcrumb": ["资料"],
    }
    rows = [entry, entry, {**entry, "id": "invalid", "url": "https://example.invalid"}]
    context, _ = _trusted_context(
        {**state.actor.context, "turn_id": "nav-test", "desktop_navigation": rows}
    )
    assert context["desktop_navigation"] == [entry]
    other = AgentRun(user_id=state.parent.user_id, message="另一个任务", status="running")
    other.metadata.update(runtime_type="xiaox", runtime_context=state.actor.context)
    state.repository.save(other)
    other_token = state.store.create(other.run_id).mcp_token
    state.store.update(
        state.parent.run_id, lambda run, _: run.metadata.update(runtime_context=context)
    )
    search = {"query": "资料 归档"}
    found = state.bridge.invoke(state.grant.mcp_token, "capability_search", search)
    assert found["desktop_navigation"] == [entry] and found["capabilities"] == []
    assert not state.bridge.invoke(other_token, "capability_search", search)["desktop_navigation"]
    with pytest.raises(XiaoxBindingError, match="未获授权"):
        state.describe("sample-entry", "execute")
    assert state.store.get(state.parent.run_id).metadata["calls"] == {}


@pytest.mark.parametrize("digest", [None, "", "0" * 64])
def test_missing_or_stale_schema_never_publishes_an_action(dynamic_runtime, digest):
    state = dynamic_runtime
    with pytest.raises(XiaoxBindingError) as error:
        state.bridge.invoke(
            state.grant.mcp_token,
            "execute_action",
            {
                "tool_id": "products",
                "action": "query",
                "call_id": "stale",
                "params": {},
                "schema_digest": digest,
            },
        )
    assert error.value.code == "schema_changed"
    assert state.store.get(state.parent.run_id).metadata["calls"] == {}


def test_known_invalid_parameters_can_be_corrected_after_schema_feedback(
    dynamic_runtime, monkeypatch
):
    state = dynamic_runtime
    calls = []
    monkeypatch.setattr(
        "app.application.facades.tools_facade.execute_registered_workflow_tool",
        lambda tool, action, params: (
            calls.append(copy.deepcopy(params)) or {"success": True, "file_path": "owned.xlsx"}
        ),
    )
    invalid = state.execute("read", {"file_path": 123}, "excel_analyzer", "analyze")
    assert (
        invalid["status"] == "not_started" and invalid["error_code"] == "schema_validation_failed"
    )
    assert invalid["schema_violation"] == {
        "path": "$.file_path",
        "validator": "type",
        "expected": "string",
        "received": "integer",
    }
    assert state.store.get(state.parent.run_id).metadata["calls"] == {}
    fixed = state.execute("read", {"file_path": "owned.xlsx"}, "excel_analyzer", "analyze")
    child = state.repository.get(fixed["run_id"])
    assert fixed["verified"] is True and len(calls) == 1, (
        fixed,
        child.error,
        [(step.status, step.error, step.output) for step in child.steps],
    )


def test_unexpected_keys_return_published_names_only():
    from jsonschema import Draft202012Validator

    from app.infrastructure.xiaox.tools import schema_violation

    schema = {"type": "object", "properties": {"title": {}}, "additionalProperties": False}
    error = next(Draft202012Validator(schema).iter_errors({"private-field": "private-value"}))
    assert schema_violation(error) == {
        "path": "$",
        "validator": "additionalProperties",
        "allowed": ["title"],
    }


@pytest.mark.parametrize(("keyword", "published", "value"), [
    ("pattern", "^[A-Z]+$", "private-input"), ("maximum", 30, 500),
])
def test_invalid_parameter_reports_only_its_published_constraint(keyword, published, value):
    from jsonschema import Draft202012Validator

    from app.infrastructure.xiaox.tools import schema_violation

    error = next(Draft202012Validator({keyword: published}).iter_errors(value))
    assert schema_violation(error) == {"path": "$", "validator": keyword, "expected": published}


def test_workbook_schema_violation_reports_discriminated_cell_location():
    from jsonschema import Draft202012Validator

    from app.domain.workbook_write_contract import WORKBOOK_WRITE_INPUT
    from app.infrastructure.xiaox.tools import schema_violation

    invalid = {
        "template_path": "scoped-upload",
        "plan": {
            "plan_version": 1,
            "phases": [
                {
                    "phase": "cell_writes",
                    "writes": [{"sheet": "private-sheet", "value": "private-cell"}],
                }
            ],
        },
    }
    error = next(Draft202012Validator(WORKBOOK_WRITE_INPUT).iter_errors(invalid))
    assert schema_violation(error) == {"path": "$.plan.phases[0].writes[0]", "validator": "anyOf"}
    missing = next(Draft202012Validator(WORKBOOK_WRITE_INPUT).iter_errors({}))
    assert schema_violation(missing) == {
        "path": "$",
        "validator": "required",
        "missing": ["template_path", "plan"],
    }


def test_next_action_uses_observed_result_without_a_precompiled_graph(dynamic_runtime, monkeypatch):
    state = dynamic_runtime
    calls = []

    def dispatch(tool, action, params):
        calls.append((tool, action, copy.deepcopy(params)))
        context = params["_runtime_context"]
        assert context["parent_run_id"] == state.parent.run_id
        assert context["_actor_authorization"] == state.actor.context["_actor_authorization"]
        assert str(context["tenant_id"]) == str(state.actor.tenant_id)
        return {"success": True, "data": [{"model_number": "observed-name"}]}

    monkeypatch.setattr(
        "app.application.facades.tools_facade.execute_registered_workflow_tool", dispatch
    )
    observed = state.execute("observe", {"keyword": "first"})
    name = observed["tool_calls"][0]["output"]["data"][0]["model_number"]
    next_result = state.execute("follow-up", {"keyword": name})
    assert observed["verified"] is next_result["verified"] is True
    assert [row[2]["keyword"] for row in calls] == ["first", "observed-name"]
    assert "runtime_frozen_plan" not in state.repository.get(state.parent.run_id).metadata


def test_parameter_dependent_read_keeps_original_read_semantics(dynamic_runtime, monkeypatch):
    state = dynamic_runtime
    spec = get_tool_action_spec("excel_analyzer", "analyze")
    assert spec.read_only is False and spec.is_read_only_call({"file_path": "owned.xlsx"})
    # The registered file adapter is independently covered with owned uploads;
    # this test verifies the conditional effect contract reaches the durable bridge.
    monkeypatch.setattr(
        "app.application.facades.tools_facade.execute_registered_workflow_tool",
        lambda *_: {"success": True, "file_path": "owned.xlsx"},
    )
    result = state.execute("inspect", {"file_path": "owned.xlsx"}, "excel_analyzer", "analyze")
    call = state.store.get(state.parent.run_id).metadata["calls"]["inspect"]
    assert call["read_only"] is True
    assert result["pending_approval"] is False


def test_schema_changed_during_approval_blocks_the_original_effect(dynamic_runtime, monkeypatch):
    state = dynamic_runtime
    result = state.execute("write", {"unit_name": "approved-name"}, "customers", "create")
    assert result["pending_approval"] is True
    child = state.repository.get(result["run_id"])
    original = get_tool_action_spec("customers", "create")
    changed = replace(original, version=original.version + ".changed")
    monkeypatch.setattr(
        "app.application.agent_orchestrator.tool_executor.get_tool_action_spec", lambda *_: changed
    )
    from app.application.agent_orchestrator.tool_spec import ToolValidationResult

    monkeypatch.setattr(
        "app.application.agent_orchestrator.tool_executor.validate_tool_call",
        lambda *_: ToolValidationResult(True, "customers", "create", changed),
    )
    dispatched = []
    monkeypatch.setattr(
        "app.application.facades.tools_facade.execute_registered_workflow_tool",
        lambda *args: dispatched.append(args) or {"success": True},
    )
    outcome = state.executor.execute(
        child.steps[0], runtime_context=child.metadata["runtime_context"]
    )
    assert outcome["error_code"] == "schema_changed"
    assert outcome["execution_status"] == "not_started"
    assert dispatched == []


def test_unknown_receipt_fences_followup_without_replaying_original_action(
    dynamic_runtime, monkeypatch
):
    state = dynamic_runtime
    calls = []
    monkeypatch.setattr(
        "app.application.facades.tools_facade.execute_registered_workflow_tool",
        lambda *args: (
            calls.append(args) or {"success": False, "outcome": "unknown", "retryable": False}
        ),
    )
    first = state.execute("uncertain", {"keyword": "first"})
    assert first["outcome"] == "unknown"
    for call_id, keyword in (("uncertain", "first"), ("another", "second")):
        with pytest.raises(XiaoxBindingError) as error:
            state.execute(call_id, {"keyword": keyword})
        assert error.value.code in {"call_in_progress", "reconciliation_required"}
    original = state.store.receipt_snapshot(state.parent.run_id)
    assert len(original) == 1 and original[0]["receipt"]["run_id"] == first["run_id"]
    assert len(calls) == 1


def test_batch_write_binds_call_identity_and_objects_to_original_sql_approval(
    dynamic_runtime, monkeypatch
):
    from app.application.agent_orchestrator.approval_grant import (
        ApprovalGrantError,
        issue_approval_grant,
        validate_approval_grant,
    )
    from app.application.agent_orchestrator.approval_transaction import approve_and_enqueue
    from app.application.agent_orchestrator.task_execution_sql_repository import (
        SQLAlchemyTaskExecutionRepository,
    )
    from app.db.models.agent_approval import AgentApprovalConsumption

    state = dynamic_runtime
    dispatched = []
    monkeypatch.setattr(
        "app.application.facades.tools_facade.execute_registered_workflow_tool",
        lambda *args: dispatched.append(args) or {"success": True},
    )
    params = {"ids": [11, 22]}
    # Exercise the tenant-owned batch contract; global legacy product writes
    # remain unavailable to this same authenticated enterprise actor.
    with pytest.raises(XiaoxBindingError) as legacy:
        state.describe("products", "batch_delete")
    assert legacy.value.code == "permission_denied"
    first = state.execute("batch-original", params, "customers", "batch_delete")
    repeated = state.execute("batch-repeat", params, "customers", "batch_delete")
    assert first["pending_approval"] is repeated["pending_approval"] is True
    assert first["run_id"] == repeated["run_id"] and first["task_id"] == repeated["task_id"]
    child = state.repository.get(first["run_id"])
    assert child is not None and child.status == "waiting_user"
    assert child.steps[0].params == params and child.tool_calls == []
    assert first["approval_card"]["approval_nodes"][0]["params"] == params
    original = issue_approval_grant(child, principal_id=str(state.actor.user_id))
    assert original is not None
    validate_approval_grant(original["grant"], run=child, principal_id=str(state.actor.user_id))
    mutated = copy.deepcopy(child)
    mutated.steps[0].params = {"ids": [11, 22, 33]}
    with pytest.raises(ApprovalGrantError):
        validate_approval_grant(
            original["grant"], run=mutated, principal_id=str(state.actor.user_id)
        )
    with pytest.raises(XiaoxBindingError) as error:
        state.execute("batch-original", {"ids": [33]}, "customers", "batch_delete")
    assert error.value.code == "call_conflict"
    with pytest.raises(XiaoxBindingError) as pending:
        state.execute("different-batch", {"ids": [33]}, "customers", "batch_delete")
    assert pending.value.code == "waiting_user"
    # Model-supplied approval and identity never reach the frozen batch.
    with pytest.raises(XiaoxBindingError) as forged:
        state.execute("forged", {**params, "human_approved": True}, "customers", "batch_delete")
    assert forged.value.code == "identity_override"
    reopened = XiaoxBindingStore(SQLAlchemyAgentRunRepository(session_factory=state.actor.factory))
    calls = reopened.get(state.parent.run_id).metadata["calls"]
    assert calls["batch-original"]["child_task_id"] == calls["batch-repeat"]["child_task_id"]
    assert all(row["params"] == params for row in calls.values())
    assert (
        child.metadata["runtime_context"]["_actor_authorization"]
        == state.actor.context["_actor_authorization"]
    )
    assert str(child.metadata["runtime_context"]["tenant_id"]) == str(state.actor.tenant_id)
    assert len(state.repository.list_recent()) == 2 and dispatched == []
    queue = SQLAlchemyTaskExecutionRepository(session_factory=state.actor.factory)
    options = {
        "run_id": child.run_id,
        "token": original["grant"],
        "principal_id": str(state.actor.user_id),
        "runtime_context": state.actor.context,
        "authenticated_actor_binding": state.actor.context["_actor_authorization"],
    }
    approved = approve_and_enqueue(state.repository, queue, **options)
    assert approved.status == "queued" and approved.steps[0].params == params
    with pytest.raises(ApprovalGrantError):
        approve_and_enqueue(state.repository, queue, **options)
    with state.actor.factory() as db:
        consumed = db.query(AgentApprovalConsumption).all()
        assert len(consumed) == 1
        assert (consumed[0].run_id, consumed[0].step_id) == (child.run_id, child.steps[0].step_id)
        assert consumed[0].jti == approved.metadata["approval_receipt"]["grant_id"]
    assert dispatched == []


def test_retired_plan_tool_cannot_dispatch_or_create_another_execution_loop(dynamic_runtime):
    state = dynamic_runtime
    with pytest.raises(XiaoxBindingError) as error:
        state.bridge.invoke(
            state.grant.mcp_token, "execute_plan", {"call_id": "old", "plan_digest": "0" * 64}
        )
    assert error.value.code == "unknown_tool"
    assert state.store.get(state.parent.run_id).metadata["calls"] == {}
