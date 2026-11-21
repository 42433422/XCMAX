"""工具返回 requires_user_decision 时，编排应停下询问用户而不是记为异常。"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.application.agent_orchestrator import InMemoryAgentRunRepository
from app.application.agent_orchestrator.approval_grant import (
    ApprovalGrantError,
    consume_approval_grant,
    issue_approval_grant,
    validate_approval_grant,
)
from app.application.agent_orchestrator.orchestrator import AgentOrchestrator
from app.application.agent_orchestrator.run_models import AgentRun, AgentStep
from app.application.workflow.workflow_types import PlanGraph, WorkflowNode, plan_to_dict
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


def _run(actor) -> AgentRun:
    preview = AgentStep(
        node_id="elt_preview",
        tool_id="elt_import",
        action="preview",
        params={"file_path": "@uploads/宗南.xlsx"},
        risk="medium",
        idempotent=False,
        status="waiting_user",
    )
    execute = AgentStep(
        node_id="elt_execute",
        tool_id="elt_import",
        action="execute",
        params={"run_id": "{{elt_preview.data.run_id}}"},
        risk="high",
        idempotent=False,
        depends_on=["elt_preview"],
    )
    run = AgentRun(user_id=str(actor.user_id), message="导入宗南.xlsx", status="waiting_user")
    run.metadata.update(cost_units_total=0, ai_cost_units_total=0)
    run.metadata["runtime_context"] = dict(actor.context)
    run.steps = [preview, execute]
    plan = PlanGraph(
        plan_id="elt-decision-pause",
        intent="elt_import",
        nodes=[
            WorkflowNode(
                node_id=step.node_id,
                tool_id=step.tool_id,
                action=step.action,
                params=dict(step.params),
                risk=step.risk,
                idempotent=step.idempotent,
                depends_on=list(step.depends_on),
            )
            for step in run.steps
        ],
    )
    run.plan_id = plan.plan_id
    run.intent = plan.intent
    run.metadata["plan"] = plan_to_dict(plan)
    return run


def _executor(output: dict) -> MagicMock:
    executor = MagicMock()
    executor.execute_with_deadline.return_value = dict(output)
    return executor


def _approve_and_execute(orchestrator, run, actor):
    grant = issue_approval_grant(run, principal_id=str(actor.user_id))
    assert grant is not None
    claims = consume_approval_grant(grant["grant"], run=run, principal_id=str(actor.user_id))
    staged = orchestrator.stage_approved_run(
        run.run_id,
        approved_by=str(actor.user_id),
        approved_step_id=claims["step_id"],
        runtime_context=actor.context,
        authenticated_actor_binding=actor.principal.actor_authorization,
        approval_claims=claims,
    )
    assert staged is not None and staged.status == "queued"
    return orchestrator.execute_dispatched_run(run.run_id)


def test_preview_blocker_pauses_run_instead_of_failing(trusted_actor):
    actor = trusted_actor(role="admin")
    repo = InMemoryAgentRunRepository()
    executor = _executor(
        {
            "success": True,
            "preview": True,
            "message": "预演完成：1 行源数据未通过校验（第18行（宗南）：公斤数或桶数至少填写一项）。",
            "requires_user_decision": True,
            "question": "预演完成：1 行源数据未通过校验（第18行（宗南）：公斤数或桶数至少填写一项）。",
            "data": {"run_id": "run-1", "executable": False, "error_rows": 1},
        }
    )
    orchestrator = AgentOrchestrator(repository=repo, tool_executor=executor)
    run = _run(actor)
    repo.save(run)
    run = _approve_and_execute(orchestrator, run, actor)

    preview, execute = run.steps
    assert preview.status == "waiting_user"
    assert run.status == "waiting_user"
    assert execute.status == "pending", "阻断后不应继续调度执行节点"
    assert executor.execute_with_deadline.call_count == 1
    assert not any(event.event_type == "tool.failed" for event in run.events)
    waiting = [event for event in run.events if event.event_type == "step.waiting_user"]
    assert waiting and waiting[-1].data["reason"] == "requires_user_decision"
    assert "第18行" in waiting[-1].message
    assert run.final_output["clarification"]["requires_confirmation"] is True


@pytest.mark.parametrize("tamper_params", [False, True])
def test_approved_pause_reruns_step_with_resume_params(trusted_actor, tamper_params):
    actor = trusted_actor(role="admin")
    repo = InMemoryAgentRunRepository()
    pause_output = {
        "success": True,
        "preview": True,
        "message": "预演有 1 行错误",
        "requires_user_decision": True,
        "question": "预演有 1 行错误",
        "resume_params": {"valid_rows_only": True},
        "data": {"run_id": "run-1", "executable": False, "error_rows": 1},
    }
    resume_output = {
        "success": True,
        "preview": True,
        "message": "预演完成",
        "requires_user_decision": False,
        "data": {"run_id": "run-1", "executable": True, "error_rows": 1},
    }
    executor = MagicMock()
    executor.execute_with_deadline.side_effect = [dict(pause_output), dict(resume_output)]
    orchestrator = AgentOrchestrator(repository=repo, tool_executor=executor)
    run = _run(actor)
    repo.save(run)
    run = _approve_and_execute(orchestrator, run, actor)
    assert run.status == "waiting_user"
    assert executor.execute_with_deadline.call_count == 1
    assert run.steps[0].params["valid_rows_only"] is True
    assert run.metadata["plan"]["nodes"][0]["params"]["valid_rows_only"] is True
    assert "valid_rows_only" not in run.tool_calls[0].params

    if tamper_params:
        grant = issue_approval_grant(run, principal_id=str(actor.user_id))
        run.steps[0].params["valid_rows_only"] = False
        with pytest.raises(ApprovalGrantError):
            validate_approval_grant(grant["grant"], run=run, principal_id=str(actor.user_id))
        assert executor.execute_with_deadline.call_count == 1
        return

    run = _approve_and_execute(orchestrator, run, actor)
    assert executor.execute_with_deadline.call_count == 2
    second_params = executor.execute_with_deadline.call_args_list[1].args[0].params
    assert second_params["valid_rows_only"] is True
    assert run.steps[0].status == "completed"
    assert run.steps[1].status == run.status == "waiting_user"
    assert all(call.action == "preview" for call in run.tool_calls)


def test_step_id_alone_cannot_authorize_a_paused_step(trusted_actor):
    actor = trusted_actor(role="admin")
    repo = InMemoryAgentRunRepository()
    executor = _executor({"success": True})
    orchestrator = AgentOrchestrator(repository=repo, tool_executor=executor)
    run = _run(actor)
    repo.save(run)
    orchestrator._execute_ready_steps(
        run, runtime_context=actor.context, approved_step_id=run.steps[0].step_id
    )
    assert run.status == run.steps[0].status == "waiting_user"
    assert run.steps[0].output["error_code"] == "approval_scope_changed"
    executor.execute_with_deadline.assert_not_called()
