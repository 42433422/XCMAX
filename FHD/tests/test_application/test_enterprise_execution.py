"""Generated proposals use one atomic original task and cannot author their own approval."""

import copy
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.agent_orchestrator import AgentOrchestrator, SQLAlchemyAgentRunRepository
from app.application.enterprise_cognition.execution import EnterpriseExecutionService
from app.application.enterprise_cognition.goals import GoalBindingError, GoalService
from app.application.workflow.workflow_types import PlanGraph, WorkflowNode
from app.db.models.agent import AgentRunRecord, AgentTaskRecord
from app.db.models.enterprise_goal import EnterpriseGoalBinding
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.fixtures.xiaox_http_runtime import dynamic_chat_runtime as dynamic_chat_runtime
from tests.fixtures.xiaox_http_runtime import runtime_entry as runtime_entry
from tests.test_application.test_enterprise_goals import Projections, definition

MESSAGE = "为订单 42 安排剩余数量出库，先审批"
CONTEXT = {"tenant_id": "7", "user_id": "19", "actor_id": "19", "mod_id": ""}


@pytest.fixture
def execution_env(dynamic_chat_runtime, trusted_actor):
    state = dynamic_chat_runtime
    actor = trusted_actor(user_id=19, tenant_id=7, role="admin")
    projections = Projections()
    goals = GoalService(actor.factory, projections=projections)
    goals.create(definition(), tenant_id=7, actor_id="19")
    repo = state.repository
    service = EnterpriseExecutionService(
        goals=goals, orchestrator=AgentOrchestrator(repository=repo)
    )
    service.test_context = actor.context
    state.enterprise_actor = actor
    return service, goals, projections, repo, state, actor.factory


def pending_write(execution_env):
    service, _goals, _projection, repo, state, _factory = execution_env
    parent = submit(service)
    state.actions = [
        {
            "tool_id": "sales",
            "action": "deliver",
            "params": {"order_id": 42, "item_id": 3, "quantity": 10.125, "warehouse_id": 4},
            "call_id": "deliver",
        }
    ]
    state.drain(parent.run_id)
    parent = repo.get(parent.run_id)
    rows = parent.metadata["xiaox_runtime"]["calls"]
    child = repo.get(rows["deliver"]["child_run_id"])
    assert child.status == "waiting_user" and not child.tool_calls
    return child


def submit(service, **kwargs):
    return service.plan(
        "fulfill-order-42",
        kwargs.pop("request_id", "request-a"),
        kwargs.pop("message", MESSAGE),
        tenant_id=7,
        actor_id="19",
        runtime_context=kwargs.pop("runtime_context", service.test_context),
        **kwargs,
    )


def test_goal_admission_is_queued_without_plan_and_child_keeps_original_approval(execution_env):
    service, _goals, _projection, repo, state, factory = execution_env
    parent = submit(service)
    assert parent.status == "queued" and not parent.steps and not parent.tool_calls
    assert state.transports == [] and state.model_requests == []
    assert not parent.metadata.get("plan")
    binding = parent.metadata["runtime_context"]["enterprise_cognition"]
    assert binding["goal"]["entity_id"] == "42"
    assert binding["baseline"]["state"]["remaining_quantity"] == "10.125"
    child = pending_write(execution_env)
    assert child.steps[0].risk == "high"
    child_binding = child.metadata["runtime_context"]["enterprise_cognition"]
    assert child_binding["baseline"] == binding["baseline"]
    assert child_binding["action_bindings"][0]["entity_id"] == "42"
    assert child.metadata["plan"]["metadata"]["approval_required_node_ids"] == [
        child.steps[0].node_id
    ]
    assert repo.get(child.run_id).to_dict() == child.to_dict()
    with factory() as db:
        assert db.query(AgentRunRecord).count() == db.query(AgentTaskRecord).count() == 2


def test_retry_reuses_original_run_without_model_or_tool_replay(execution_env):
    service, _goals, projections, _repo, state, _factory = execution_env
    first = submit(service)
    projections.version = "new-source-after-original-request"
    second = submit(service)
    assert second.run_id == first.run_id
    assert (
        second.metadata["runtime_context"]["enterprise_cognition"]
        == first.metadata["runtime_context"]["enterprise_cognition"]
    )
    assert len(state.transports) == 0
    assert not second.tool_calls
    with pytest.raises(GoalBindingError, match="request_id_already_bound"):
        submit(service, message="改成取消订单")


def test_model_tool_attaches_one_child_to_original_parent_and_projects_its_state(
    execution_env, trusted_actor, monkeypatch
):
    from app.application.enterprise_cognition.service import EnterpriseCognitionService
    from app.application.tools.enterprise_cognition import execute_enterprise_cognition
    from app.fastapi_routes.domains.agent.route_support import public_run_dict

    service, _goals, _projection, repo, state, factory = execution_env
    actor = trusted_actor(user_id=19, tenant_id=7, role="admin")
    params = {"goal_id": "fulfill-order-42", "request_id": "child-request", "message": MESSAGE}
    parent_context = {**actor.context, "task_id": "parent-task", "workspace_id": "parent-task"}
    parent = service.orchestrator.start_task_from_plan(
        user_id="19",
        message="调用模型工具为订单目标准备子任务",
        plan=PlanGraph(
            plan_id="original-parent-plan",
            intent="prepare_goal_proposal",
            nodes=[WorkflowNode("propose", "enterprise_cognition", "plan", params)],
        ),
        runtime_context=parent_context,
    )
    cognition = EnterpriseCognitionService(execution=service)
    monkeypatch.setattr(
        "app.application.tools.enterprise_cognition.get_cognition_service", lambda: cognition
    )
    tool_context = {**parent_context, "agent_run_id": parent.run_id}
    response = execute_enterprise_cognition("plan", params, tool_context)
    assert response["success"] and not response["pending_approval"], response
    child_id = response["data"]["run_id"]
    child = repo.get(child_id)
    assert child is not None and child.status == "queued"
    runtime = child.metadata["runtime_context"]
    assert runtime["parent_run_id"] == parent.run_id
    assert runtime["parent_task_id"] == "parent-task"
    assert runtime["task_id"] != "parent-task"
    stored_parent = repo.get(parent.run_id)
    assert set(stored_parent.metadata["child_results"]) == {child_id}
    receipt = public_run_dict(stored_parent, read_run=repo.get)["metadata"]["child_results"][
        child_id
    ]
    assert receipt["source"] == "child_run"
    assert receipt["execution_state"] == "queued"
    assert receipt["success"] is False
    assert receipt["run_id"] == child_id and receipt["parent_task_id"] == "parent-task"
    attach_events = [
        event for event in stored_parent.events if event.event_type == "task.child_run_attached"
    ]
    assert len(attach_events) == 1 and attach_events[0].data["child_run_id"] == child_id

    retried = execute_enterprise_cognition("plan", params, tool_context)
    assert retried["data"]["run_id"] == child_id and len(state.transports) == 0
    reloaded = repo.get(parent.run_id)
    assert [
        event.to_dict()
        for event in reloaded.events
        if event.event_type == "task.child_run_attached"
    ] == [event.to_dict() for event in attach_events]
    with factory() as db:
        assert db.query(AgentRunRecord).count() == db.query(AgentTaskRecord).count() == 2


def test_current_actor_cannot_supply_another_tenant_or_mod_scope(execution_env):
    service, *_ = execution_env
    for context in (
        {**CONTEXT, "tenant_id": "8"},
        {**CONTEXT, "user_id": "20"},
        {**CONTEXT, "mod_id": "foreign"},
    ):
        with pytest.raises(GoalBindingError, match="identity_invalid"):
            submit(service, runtime_context=context)


def test_boolean_approval_and_context_baseline_do_not_authorize_execution(execution_env):
    service, *_ = execution_env
    run = submit(
        service,
        runtime_context={
            **service.test_context,
            "approved": True,
            "approved_step_id": "deliver",
            "task_id": "parent-task",
            "enterprise_cognition": {"baseline": {"state": {"remaining_quantity": 0}}},
        },
    )
    runtime = run.metadata["runtime_context"]
    assert run.status == "queued" and not run.tool_calls
    assert "approved" not in runtime and "approved_step_id" not in runtime
    assert runtime["task_id"] != "parent-task"
    assert runtime["enterprise_cognition"]["baseline"]["state"]["remaining_quantity"] == "10.125"


@pytest.mark.parametrize("change", ["plan", "binding", "consistent_binding", "remove_binding"])
def test_approval_grant_binds_the_whole_plan_and_cannot_downgrade_evidence(execution_env, change):
    from app.application.agent_orchestrator.approval_grant import (
        ApprovalGrantError,
        issue_approval_grant,
        validate_approval_grant,
    )
    from app.application.agent_orchestrator.business_action_ledger import canonical_hash

    service, *_ = execution_env
    run = pending_write(execution_env)
    grant = issue_approval_grant(run, principal_id="19")
    claims = validate_approval_grant(grant["grant"], run=run, principal_id="19")
    assert claims["plan_sha256"] == canonical_hash(run.metadata["plan"])
    assert claims["enterprise_binding_sha256"] == canonical_hash(
        run.metadata["runtime_context"]["enterprise_cognition"]
    )
    changed = copy.deepcopy(run)
    if change == "plan":
        changed.metadata["plan"]["intent"] = "unrelated_new_objective"
        changed.metadata["plan_sha256"] = canonical_hash(changed.metadata["plan"])
    elif change == "binding":
        changed.metadata["runtime_context"]["enterprise_cognition"]["baseline"]["state"][
            "remaining_quantity"
        ] = "0"
    elif change == "consistent_binding":
        changed.metadata["runtime_context"]["enterprise_cognition"]["goal"]["target"] = "99"
        changed.metadata["plan"]["metadata"]["enterprise_cognition"] = copy.deepcopy(
            changed.metadata["runtime_context"]["enterprise_cognition"]
        )
        changed.metadata["plan_sha256"] = canonical_hash(changed.metadata["plan"])
    else:
        changed.metadata["runtime_context"].pop("enterprise_cognition")
        changed.metadata["plan"]["metadata"].pop("enterprise_cognition")
    # No current-step parameter changes are needed: the grant covers the full
    # goal, baseline and all subsequent nodes in the approved proposal.
    assert changed.steps[0].params == run.steps[0].params
    with pytest.raises(ApprovalGrantError, match="不匹配"):
        validate_approval_grant(grant["grant"], run=changed, principal_id="19")


@pytest.mark.parametrize("fault", ["foreign_source", "unrelated_write", "remove_binding"])
def test_dynamic_action_cannot_expand_original_goal_scope(execution_env, fault):
    from app.application.enterprise_cognition.execution import validate_goal_action

    service, _goals, _projection, _repo, _state, factory = execution_env
    run = submit(service)
    context = copy.deepcopy(run.metadata["runtime_context"])
    tool, action, params = "sales", "deliver", {"order_id": 42}
    if fault == "foreign_source":
        context["enterprise_cognition"]["goal"]["source"] = {"kind": "model_claim"}
    elif fault == "unrelated_write":
        tool, action, params = "customers", "ensure_exists", {"unit_name": "unrelated"}
    else:
        context.pop("enterprise_cognition")
    with pytest.raises(GoalBindingError):
        validate_goal_action(context, tool, action, params, read_only=False)
    with factory() as db:
        assert db.query(AgentTaskRecord).count() == db.query(AgentRunRecord).count() == 1


def test_other_order_cannot_use_current_orders_goal_as_its_effect_binding(execution_env):
    from app.application.enterprise_cognition.execution import validate_goal_action

    service, *_ = execution_env
    run = submit(service)
    with pytest.raises(GoalBindingError, match="target_unsupported_or_mismatched"):
        validate_goal_action(
            run.metadata["runtime_context"], "sales", "deliver", {"order_id": 999}, read_only=False
        )


def test_source_change_during_admission_rejects_stale_baseline(execution_env, monkeypatch):
    service, _goals, projections, _repo, _state, factory = execution_env
    original = projections.get
    calls = []

    def changing(*args, **kwargs):
        calls.append(1)
        if len(calls) == 3:
            projections.version = "source-changed-during-admission"
        return original(*args, **kwargs)

    monkeypatch.setattr(projections, "get", changing)
    with pytest.raises(GoalBindingError, match="changed_during_admission"):
        submit(service)
    with factory() as db:
        assert db.query(AgentTaskRecord).count() == 0


def test_two_independent_services_admit_one_complete_original_task(execution_env):
    original, goals, projections, _repo, state, factory = execution_env
    barrier = threading.Barrier(2)

    def admit(**kwargs):
        from app.application.agent_runtime.gateway import run_runtime_task

        barrier.wait(timeout=15)
        return run_runtime_task(**kwargs)

    def attempt(_index):
        service = EnterpriseExecutionService(
            goals=GoalService(factory, projections=projections),
            orchestrator=AgentOrchestrator(
                repository=SQLAlchemyAgentRunRepository(session_factory=factory, auto_create=False)
            ),
            runtime_gateway=admit,
        )
        service.test_context = original.test_context
        return submit(service)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, (0, 1)))
    assert results[0].run_id == results[1].run_id
    assert results[0].to_dict() == results[1].to_dict()
    with factory() as db:
        assert db.query(AgentRunRecord).count() == db.query(AgentTaskRecord).count() == 1
    assert results[0].status == "queued" and not results[0].tool_calls


def test_approval_and_resume_cannot_replace_frozen_business_evidence(execution_env):
    from app.application.agent_orchestrator.runtime_context import (
        RuntimeContextOwnershipError,
        merge_runtime_context,
    )
    from app.application.agent_orchestrator.tool_permission import overlay_resume_context

    service, *_ = execution_env
    run = submit(service)
    stored = run.metadata["runtime_context"]
    forged = copy.deepcopy(stored["enterprise_cognition"])
    forged["baseline"]["state"]["remaining_quantity"] = "999999"
    updates = {"enterprise_cognition": forged}
    with pytest.raises(RuntimeContextOwnershipError, match="经营目标证据"):
        merge_runtime_context(run, updates)
    with pytest.raises(RuntimeContextOwnershipError, match="经营目标证据"):
        overlay_resume_context(stored, updates)
    assert (
        merge_runtime_context(
            run, {"enterprise_cognition": copy.deepcopy(stored["enterprise_cognition"])}
        )["enterprise_cognition"]
        == stored["enterprise_cognition"]
    )


def test_tool_feedback_cannot_author_a_business_evidence_binding():
    from app.application.agent_orchestrator.tool_permission import merge_turn_context

    assert "enterprise_cognition" not in merge_turn_context(
        {}, {"enterprise_cognition": {"baseline": "forged"}}
    )


def test_goal_decision_receives_scoped_conditional_world_scenario(execution_env):
    service, _goals, _projections, _repo, state, _factory = execution_env
    parent = submit(service, request_id="world-decision-consumer")
    binding = parent.metadata["runtime_context"]["enterprise_cognition"]
    scenario = binding["world_scenario"]
    assert scenario["knowledge_kind"] == "prediction"
    assert scenario["method"] == "conditional_arithmetic"
    assert scenario["baseline_source_version"] == binding["baseline"]["source_version"]
    assert Decimal(scenario["value"]) == 0
    assert scenario["probability"] is None
    assert scenario["causal_effect_verified"] is False
    assert scenario["business_data_written"] is False
    assert parent.status == "queued" and not parent.tool_calls
    assert state.transports == [] and state.model_requests == []


def test_unreachable_goal_stays_unknown_in_world_scenario(execution_env):
    service, goals, _projections, _repo, _state, _factory = execution_env
    goals.create(
        definition(goal_id="order-42-over-target", target="20"),
        tenant_id=7,
        actor_id="19",
    )
    parent = service.plan(
        "order-42-over-target",
        "world-unknown-target",
        MESSAGE,
        tenant_id=7,
        actor_id="19",
        runtime_context=service.test_context,
    )
    scenario = parent.metadata["runtime_context"]["enterprise_cognition"]["world_scenario"]
    assert scenario["knowledge_kind"] == "unknown"
    assert scenario["reason_code"] == "scenario_quantity_out_of_range"
    assert not parent.tool_calls


def test_evidence_bound_world_scenario_reaches_codex_model_input(execution_env):
    from app.application.agent_runtime.codex_runtime import _input_text

    service, _goals, _projections, _repo, _state, _factory = execution_env
    run = submit(service, request_id="world-model-input-evidence")
    binding = run.metadata["runtime_context"]["enterprise_cognition"]
    scenario = binding["world_scenario"]
    payload = run.metadata["_codex_input_data"]
    assert payload["world_scenario"] == scenario
    assert payload["baseline"]["source_version"] == scenario["baseline_source_version"]
    model_input = _input_text(run.message, [], payload)
    assert '"world_scenario"' in model_input
    assert scenario["baseline_source_version"] in model_input
    assert '"method": "conditional_arithmetic"' in model_input
    assert '"business_data_written": false' in model_input
    assert not run.tool_calls
