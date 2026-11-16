"""工具返回 requires_user_decision 时，编排应停下询问用户而不是记为异常。"""

from __future__ import annotations

from unittest.mock import MagicMock

from app.application.agent_orchestrator.orchestrator import AgentOrchestrator
from app.application.agent_orchestrator.run_models import AgentRun, AgentStep
from app.application.workflow.workflow_types import PlanGraph, WorkflowNode, plan_to_dict


def _run() -> AgentRun:
    preview = AgentStep(
        node_id="elt_preview",
        tool_id="elt_import",
        action="preview",
        params={"file_path": "@uploads/宗南.xlsx"},
        risk="medium",
        idempotent=False,
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
    run = AgentRun(user_id="u1", message="导入宗南.xlsx", status="running")
    run.metadata.update(cost_units_total=0, ai_cost_units_total=0)
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


def test_preview_blocker_pauses_run_instead_of_failing():
    repo = MagicMock()
    repo.save.side_effect = lambda run: run
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
    run = _run()

    orchestrator._execute_ready_steps(
        run, runtime_context={"user_id": "1"}, approved_step_id=run.steps[0].step_id
    )

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


def test_approved_pause_reruns_step_with_resume_params():
    repo = MagicMock()
    repo.save.side_effect = lambda run: run
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
    run = _run()

    orchestrator._execute_ready_steps(
        run, runtime_context={"user_id": "1"}, approved_step_id=run.steps[0].step_id
    )
    assert run.status == "waiting_user"

    run.status = "running"
    orchestrator._execute_ready_steps(
        run, runtime_context={"user_id": "1"}, approved_step_id=run.steps[0].step_id
    )

    second_params = executor.execute_with_deadline.call_args_list[1].args[0].params
    assert second_params["valid_rows_only"] is True
