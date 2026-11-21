"""Goal writes and child admission are verified against original SQL records."""

import copy

import pytest
from sqlalchemy import event

from app.application.agent_orchestrator import AgentOrchestrator
from app.application.agent_orchestrator.result_verification import (
    freeze_verification_contract,
    verified_step_output,
)
from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
from app.application.agent_orchestrator.tool_executor import AgentToolExecutor
from app.application.agent_orchestrator.tool_spec import get_tool_action_spec
from app.application.enterprise_cognition.execution import EnterpriseExecutionService
from app.application.enterprise_cognition.goals import GoalService
from app.application.enterprise_cognition.service import EnterpriseCognitionService
from app.application.tools.enterprise_cognition import execute_enterprise_cognition
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.test_application.test_enterprise_acceptance import OrderPlanner, _seed_order
from tests.test_application.test_sales_verification_readback import verify
from tests.test_application.test_verification_readback import invocation


@pytest.fixture
def cognition(trusted_actor, monkeypatch, tmp_path):
    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    actor = trusted_actor(role="admin")
    monkeypatch.setattr("app.db.SessionLocal", actor.factory)
    order_id, item_id, warehouse_id, _ = _seed_order(actor)
    repository = SQLAlchemyAgentRunRepository(session_factory=actor.factory)
    monkeypatch.setattr(
        "app.application.agent_orchestrator.run_repository.get_agent_run_repository",
        lambda: repository,
    )
    goals = GoalService(actor.factory)
    execution = EnterpriseExecutionService(
        goals=goals,
        orchestrator=AgentOrchestrator(repository=repository),
        planner=OrderPlanner(order_id, item_id, warehouse_id),
    )
    service = EnterpriseCognitionService(goals=goals, execution=execution)
    monkeypatch.setattr(
        "app.application.tools.enterprise_cognition.get_cognition_service", lambda: service
    )
    definition = {
        "goal_id": "deliver-order",
        "objective": "将原订单待交付数量减为0",
        "entity_type": "order",
        "entity_id": str(order_id),
        "metric": "remaining_quantity",
        "unit": "件",
        "direction": "decrease",
        "target": "0",
    }
    return actor, repository, definition


def case_for(cognition, action, params):
    actor, repository, _ = cognition
    case = invocation(actor, tool="enterprise_cognition", action=action, params=params)
    task_id = "original-parent-task"
    case.run.metadata["runtime_context"]["task_id"] = task_id
    case.run.metadata["task_context"] = {
        "task_id": task_id,
        "tenant_id": str(actor.tenant_id),
        "attempt": 1,
    }
    case.context["task_id"] = task_id
    freeze_verification_contract(
        case.run,
        case.step,
        case.call,
        get_tool_action_spec("enterprise_cognition", action),
        case.context,
    )
    repository.save(case.run)
    return case


def test_goal_binding_is_read_from_the_original_owner_without_creating_another_goal(cognition):
    actor, _, definition = cognition
    case = case_for(cognition, "bind_goal", definition)
    output = execute_enterprise_cognition("bind_goal", definition, case.context)
    assert output["success"], output
    writes = []

    def observe(_connection, _cursor, statement, _params, _context, _many):
        if statement.split()[0].upper() in {"INSERT", "UPDATE", "DELETE"}:
            writes.append(statement)

    engine = actor.factory.kw["bind"]
    event.listen(engine, "before_cursor_execute", observe)
    try:
        assert verify(case, output)["accepted"]
        assert verify(case, output)["accepted"]
        assert writes == []
    finally:
        event.remove(engine, "before_cursor_execute", observe)
    forged = copy.deepcopy(output)
    forged["data"]["target"] = "999"
    assert verify(case, forged)["accepted"] is False


def test_goal_claim_without_original_persisted_binding_is_not_verified(cognition):
    _, _, definition = cognition
    case = case_for(cognition, "bind_goal", definition)
    assert (
        verify(case, {"success": True, "data": definition, "verified": True})["accepted"] is False
    )


def test_plan_verifies_only_original_child_admission_and_preserves_business_approval(cognition):
    actor, repository, definition = cognition
    output = execute_enterprise_cognition("bind_goal", definition, actor.context)
    assert output["success"]
    params = {
        "goal_id": definition["goal_id"],
        "request_id": "original-plan",
        "message": "审批原订单交付方案",
    }
    case = case_for(cognition, "plan", params)
    output = AgentToolExecutor().execute(case.step, runtime_context=case.context)
    assert output["success"], output
    assert output["pending_approval"]
    result = verify(case, output)
    assert result["accepted"], result
    evidence = result["checks"][0]["evidence"]
    assert evidence["admission_verified"] and not evidence["business_execution_verified"]
    child = repository.get(output["data"]["run_id"])
    assert child.status == "waiting_user" and not child.tool_calls
    assert output["pending_approval"] and output["execution_state"] == "waiting_approval"
    forged = copy.deepcopy(output)
    forged["data"]["task_id"] = "another-task"
    assert verify(case, forged)["accepted"] is False
    forged = copy.deepcopy(output)
    forged["pending_approval"] = False
    forged["execution_state"] = "completed"
    assert verify(case, forged)["accepted"] is False
    for signals in (
        {"execution_state": "unknown"},
        {"pending_approval": True},
        {"error": "denied"},
    ):
        forged = copy.deepcopy(output)
        forged["data"].update(signals)
        assert verify(case, forged)["accepted"] is False
    assert (
        len(repository.list_task_runs(user_id=str(actor.user_id), task_id=evidence["task_id"])) == 1
    )
    # The admission remains inspectable after the real child advances. Rechecking
    # its admission neither completes the pending business nor changes the child.
    from app.application.agent_orchestrator.approval_grant import issue_approval_grant
    from app.application.agent_orchestrator.approval_transaction import approve_and_enqueue
    from app.application.agent_orchestrator.task_execution_sql_repository import (
        SQLAlchemyTaskExecutionRepository,
    )
    from app.application.agent_orchestrator.verification_recovery import (
        reverify_run,
        verification_can_finalize,
    )
    from app.application.workflow.workflow_types import PlanGraph, WorkflowNode, plan_to_dict

    grant = issue_approval_grant(child, principal_id=str(actor.user_id))
    queue = SQLAlchemyTaskExecutionRepository(session_factory=actor.factory)
    queued = approve_and_enqueue(
        repository,
        queue,
        run_id=child.run_id,
        token=grant["grant"],
        principal_id=str(actor.user_id),
        runtime_context={},
        authenticated_binding=actor.principal.mod_authorization,
    )
    assert queued.status == "queued" and not queued.tool_calls
    # A fresh read of the same admitted task can now say queued. Generic
    # execution normalization must not turn that known admission into unknown.
    from types import SimpleNamespace

    from app.application.agent_orchestrator.tool_executor import execute_with_tool_deadline

    queued_receipt = execute_enterprise_cognition("plan", params, case.context)
    assert queued_receipt["execution_state"] == "queued" and not queued_receipt["pending_approval"]
    normalized = execute_with_tool_deadline(
        SimpleNamespace(execute=lambda *_args, **_kwargs: queued_receipt),
        case.step,
        runtime_context=case.context,
        timeout_seconds=30,
    )
    assert normalized == queued_receipt and normalized["success"]
    from app.application.agent_orchestrator.business_harness import ensure_terminal_business_result

    assert verify(case, queued_receipt)["accepted"]
    assert verified_step_output(case.run, case.step) == queued_receipt
    assert case.call.output == queued_receipt
    case.run.status = "completed"
    business = ensure_terminal_business_result(case.run)
    assert business["status"] == "pending" and business["success"] is False
    assert business["evidence"]["business_effect_verified"] is False
    assert business["evidence"]["admitted_tasks"][0]["source"] == "enterprise_authority"
    assert verify(case, output)["accepted"]
    plan = PlanGraph(
        plan_id="parent-admission",
        intent="admit_original_child",
        nodes=[WorkflowNode("effect", "enterprise_cognition", "plan", params)],
    )
    case.run.plan_id, case.run.metadata["plan"] = plan.plan_id, plan_to_dict(plan)
    case.run.status = "blocked"
    repository.save(case.run)
    recovered = reverify_run(repository, case.run.run_id)
    assert recovered.metadata["verification"]["accepted"]
    assert verification_can_finalize(recovered) is False
    assert repository.get(child.run_id).status == "queued"
    assert (
        len(repository.list_task_runs(user_id=str(actor.user_id), task_id=evidence["task_id"])) == 1
    )


def test_plan_cannot_verify_a_foreign_or_missing_task_with_a_pending_flag(cognition):
    actor, _, definition = cognition
    assert execute_enterprise_cognition("bind_goal", definition, actor.context)["success"]
    params = {"goal_id": definition["goal_id"], "request_id": "unknown-plan", "message": "审批交付"}
    case = case_for(cognition, "plan", params)
    output = {
        "success": True,
        "pending_approval": True,
        "execution_state": "waiting_approval",
        "data": {"run_id": "another-run", "task_id": "another-task", "status": "waiting_user"},
    }
    assert verify(case, output)["accepted"] is False


def test_original_executor_deadline_step_and_verifier_preserve_only_child_admission(cognition):
    from types import SimpleNamespace

    from app.application.workflow.workflow_types import PlanGraph, WorkflowNode

    actor, repository, definition = cognition
    assert execute_enterprise_cognition("bind_goal", definition, actor.context)["success"]
    plan = PlanGraph(
        plan_id="admission-through-original-step",
        intent="propose_operating_plan",
        nodes=[
            WorkflowNode(
                "propose",
                "enterprise_cognition",
                "plan",
                {
                    "goal_id": definition["goal_id"],
                    "request_id": "actual-parent-step",
                    "message": "审批交付方案",
                },
                risk="low",
                idempotent=True,
            )
        ],
    )
    parent = AgentOrchestrator(
        repository=repository,
        tool_executor=SimpleNamespace(execute=AgentToolExecutor().execute),
    ).start_run_from_plan(
        user_id=str(actor.user_id),
        message="生成待审批交付方案",
        plan=plan,
        runtime_context=actor.context,
    )
    assert len(parent.tool_calls) == 1, parent.to_dict()
    call = parent.tool_calls[0]
    assert call.status == "completed" and call.output["success"] is True, parent.to_dict()
    assert call.output["pending_approval"] and call.output["execution_state"] == "waiting_approval"
    assert call.metadata["verification"]["accepted"]
    assert call.metadata["verification"]["checks"][0]["evidence"]["admission_verified"]
    child = repository.get(call.output["data"]["run_id"])
    assert child.status == "waiting_user" and not child.tool_calls
    assert parent.final_output["business_result"]["pending_approval"]
    assert parent.final_output["business_result"]["status"] != "completed"


@pytest.mark.parametrize(
    "changed",
    [
        "missing_child",
        "foreign_scope",
        "other_action",
        "unknown",
        "nested_unknown",
        "rejected",
        "source_unavailable",
        "unknown_io",
    ],
)
def test_admission_normalization_never_accepts_unproven_or_uncertain_execution(
    cognition, monkeypatch, changed
):
    import time
    from types import SimpleNamespace

    from app.application.agent_orchestrator.tool_executor import execute_with_tool_deadline
    from app.application.agent_orchestrator.verification_cognition import (
        normalize_tool_execution_result,
    )
    from app.application.tool_execution_deadline import invocation_deadline

    actor, repository, definition = cognition
    assert execute_enterprise_cognition("bind_goal", definition, actor.context)["success"]
    params = {
        "goal_id": definition["goal_id"],
        "request_id": "normalize-negative",
        "message": "审批交付",
    }
    case = case_for(cognition, "plan", params)
    output = execute_enterprise_cognition("plan", params, case.context)
    assert output["success"]
    assert normalize_tool_execution_result(case.step, output, case.context) == output
    context = dict(case.context)
    if changed == "missing_child":
        output["data"]["run_id"] = "invented-child"
    elif changed == "foreign_scope":
        context["tenant_id"] = str(actor.tenant_id + 1)
    elif changed == "other_action":
        case.step.tool_id, case.step.action = "employee", "execute"
    elif changed == "unknown":
        output.update(outcome="unknown", reconciliation_required=True)
    elif changed == "nested_unknown":
        output["data"]["execution_state"] = "unknown"
    elif changed == "rejected":
        output["data"]["status"] = output["execution_state"] = "rejected"
        output["pending_approval"] = False
    elif changed == "source_unavailable":

        def unavailable(_run_id):
            raise TimeoutError("authority unavailable")

        monkeypatch.setattr(repository, "get", unavailable)
    if changed == "unknown_io":
        with invocation_deadline(time.monotonic() + 60) as invocation:
            invocation.uncertain.append({"kind": "http_timeout"})
            normalized = execute_with_tool_deadline(
                SimpleNamespace(execute=lambda *_args, **_kwargs: output),
                case.step,
                runtime_context=context,
                timeout_seconds=30,
            )
        assert normalized["outcome"] == "unknown" and normalized["reconciliation_required"]
    else:
        normalized = normalize_tool_execution_result(case.step, output, context)
    assert normalized["success"] is False
