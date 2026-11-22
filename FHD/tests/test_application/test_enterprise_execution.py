"""Generated proposals use one atomic original task and cannot author their own approval."""

import copy
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

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
from tests.test_application.test_enterprise_goals import Projections, definition

MESSAGE = "为订单 42 安排剩余数量出库，先审批"
CONTEXT = {"tenant_id": "7", "user_id": "19", "actor_id": "19", "mod_id": ""}


class Planner:
    def __init__(self, *, barrier=None, order_id=42):
        self.barrier = barrier
        self.order_id = order_id
        self.calls = []
        self.remove_coverage = False
        self.foreign_source = False
        self.extra_node = False
        self.change_source = None

    def plan(self, user_id, message, registry, context):
        self.calls.append((user_id, message, copy.deepcopy(context)))
        if self.barrier:
            self.barrier.wait(timeout=15)
        if self.change_source:
            self.change_source.version = "concurrent-source-change"
        plan = PlanGraph(
            plan_id=f"plan-{uuid.uuid4().hex}",
            intent="fulfill_order",
            nodes=[
                WorkflowNode(
                    "deliver",
                    "sales",
                    "deliver",
                    {
                        "order_id": self.order_id,
                        "item_id": 3,
                        "quantity": 10.125,
                        "warehouse_id": 4,
                    },
                )
            ],
        )
        if self.extra_node:
            plan.nodes.append(WorkflowNode("unrelated", "customers", "query", {}))
        if not self.remove_coverage:
            plan.metadata["goal_coverage"] = {
                "goals": [
                    {
                        "goal_id": "delivery",
                        "source": "another request" if self.foreign_source else message,
                        "outcome": "execute",
                        "node_ids": ["deliver"],
                    }
                ],
                "violations": [],
            }
        return plan

    def complete_messages(self, **kwargs):
        return None


@pytest.fixture
def execution_env(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'goals-tasks.sqlite'}")
    EnterpriseGoalBinding.__table__.create(engine)
    factory = sessionmaker(bind=engine)
    projections = Projections()
    goals = GoalService(factory, projections=projections)
    goals.create(definition(), tenant_id=7, actor_id="19")
    repo = SQLAlchemyAgentRunRepository(session_factory=factory)
    repo._ensure_schema()
    planner = Planner()
    # Authenticated route/tool tests exercise the real sealed-session boundary.
    # These tests isolate proposal admission, concurrent SQL and source binding.
    monkeypatch.setattr(
        "app.application.enterprise_cognition.execution.validate_actor_context", lambda _ctx: None
    )
    monkeypatch.setattr(
        "app.application.enterprise_cognition.execution.actor_tool_denial", lambda *_args: None
    )
    service = EnterpriseExecutionService(
        goals=goals, orchestrator=AgentOrchestrator(repository=repo), planner=planner
    )
    yield service, goals, projections, repo, planner, factory
    engine.dispose()


def submit(service, **kwargs):
    return service.plan(
        "fulfill-order-42",
        kwargs.pop("request_id", "request-a"),
        kwargs.pop("message", MESSAGE),
        tenant_id=7,
        actor_id="19",
        runtime_context=kwargs.pop("runtime_context", CONTEXT),
        **kwargs,
    )


def test_plan_is_durable_waiting_approval_with_goal_baseline_and_original_graph(execution_env):
    service, _goals, _projection, repo, planner, factory = execution_env
    run = submit(service)
    assert run.status == run.steps[0].status == "waiting_user"
    assert not run.tool_calls
    assert run.steps[0].risk == "high"
    binding = run.metadata["runtime_context"]["enterprise_cognition"]
    assert binding["goal"]["entity_id"] == "42"
    assert binding["baseline"]["state"]["remaining_quantity"] == "10.125"
    assert binding["action_bindings"][0]["entity_id"] == "42"
    assert run.metadata["plan"]["metadata"]["approval_required_node_ids"] == ["deliver"]
    assert "把订单 42 的剩余待发数量降为 0 件" in planner.calls[0][1]
    assert repo.get(run.run_id).to_dict() == run.to_dict()
    with factory() as db:
        task = db.query(AgentTaskRecord).one()
        assert task.active_run_id == run.run_id
        assert db.query(AgentRunRecord).count() == 1


def test_retry_reuses_original_run_without_model_or_tool_replay(execution_env):
    service, _goals, projections, _repo, planner, _factory = execution_env
    first = submit(service)
    projections.version = "new-source-after-original-request"
    second = submit(service)
    assert second.run_id == first.run_id
    assert (
        second.metadata["runtime_context"]["enterprise_cognition"]
        == first.metadata["runtime_context"]["enterprise_cognition"]
    )
    assert len(planner.calls) == 1
    assert not second.tool_calls
    with pytest.raises(GoalBindingError, match="request_id_already_bound"):
        submit(service, message="改成取消订单")


def test_model_tool_attaches_one_child_to_original_parent_and_projects_its_state(
    execution_env, trusted_actor, monkeypatch
):
    from app.application.enterprise_cognition.service import EnterpriseCognitionService
    from app.application.tools.enterprise_cognition import execute_enterprise_cognition
    from app.fastapi_routes.domains.agent.route_support import public_run_dict

    service, _goals, _projection, repo, planner, factory = execution_env
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
    assert response["success"] and response["pending_approval"], response
    child_id = response["data"]["run_id"]
    child = repo.get(child_id)
    assert child is not None and child.status == "waiting_user"
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
    assert receipt["execution_state"] == "waiting_approval"
    assert receipt["success"] is False
    assert receipt["run_id"] == child_id and receipt["parent_task_id"] == "parent-task"
    attach_events = [
        event for event in stored_parent.events if event.event_type == "task.child_run_attached"
    ]
    assert len(attach_events) == 1 and attach_events[0].data["child_run_id"] == child_id

    retried = execute_enterprise_cognition("plan", params, tool_context)
    assert retried["data"]["run_id"] == child_id and len(planner.calls) == 1
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
            **CONTEXT,
            "approved": True,
            "approved_step_id": "deliver",
            "task_id": "parent-task",
            "enterprise_cognition": {"baseline": {"state": {"remaining_quantity": 0}}},
        },
    )
    runtime = run.metadata["runtime_context"]
    assert run.status == "waiting_user" and not run.tool_calls
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
    run = submit(service)
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


@pytest.mark.parametrize("fault", ["foreign_source", "extra_node", "remove_coverage"])
def test_unreviewed_or_partial_goal_plan_never_creates_a_task(execution_env, fault):
    service, _goals, _projection, _repo, planner, factory = execution_env
    setattr(planner, fault, True)
    with pytest.raises(GoalBindingError, match="coverage"):
        submit(service)
    with factory() as db:
        assert db.query(AgentTaskRecord).count() == db.query(AgentRunRecord).count() == 0


def test_other_order_cannot_use_current_orders_goal_as_its_effect_binding(execution_env):
    service, _goals, _projection, _repo, planner, _factory = execution_env
    planner.order_id = 999
    with pytest.raises(GoalBindingError, match="target_unsupported_or_mismatched"):
        submit(service)


def test_source_change_during_planning_rejects_the_stale_proposal(execution_env):
    service, _goals, projections, _repo, planner, factory = execution_env
    planner.change_source = projections
    with pytest.raises(GoalBindingError, match="changed_during_planning"):
        submit(service)
    with factory() as db:
        assert db.query(AgentTaskRecord).count() == 0


def test_two_independent_services_admit_one_complete_original_task(execution_env):
    _service, goals, projections, _repo, _planner, factory = execution_env
    barrier = threading.Barrier(2)

    def attempt(_index):
        service = EnterpriseExecutionService(
            goals=GoalService(factory, projections=projections),
            orchestrator=AgentOrchestrator(
                repository=SQLAlchemyAgentRunRepository(session_factory=factory, auto_create=False)
            ),
            planner=Planner(barrier=barrier),
        )
        return submit(service)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, (0, 1)))
    assert results[0].run_id == results[1].run_id
    assert results[0].to_dict() == results[1].to_dict()
    with factory() as db:
        assert db.query(AgentRunRecord).count() == db.query(AgentTaskRecord).count() == 1
    assert results[0].status == "waiting_user" and not results[0].tool_calls


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
