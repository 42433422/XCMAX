"""计划级确认：暂停后用同一计划续跑（等价 interrupt + resume），不再要求重新规划。"""

from __future__ import annotations

import pytest

from app.application.agent_orchestrator.clarification import (
    ClarificationAnswerError,
    apply_plan_confirmation,
    is_plan_confirmation,
)
from app.application.agent_orchestrator.run_models import AgentRun, AgentStep


def _run() -> AgentRun:
    run = AgentRun(user_id="2", message="清理一下全部数据库", run_id="run_plan_confirm")
    run.status = "waiting_user"
    run.steps = [
        AgentStep(
            node_id="preview_scope",
            tool_id="business_db",
            action="read",
            params={"entity": "customers"},
            status="completed",
            output={"success": True, "data": []},
        ),
        AgentStep(
            node_id="confirm_clear",
            tool_id="clarify",
            action="ask",
            params={"question": "回复「确认」执行"},
            status="waiting_user",
            output={"requires_confirmation": True, "answer_key": "confirmed"},
            depends_on=["preview_scope"],
        ),
        AgentStep(
            node_id="clear_customers",
            tool_id="customers",
            action="clear",
            params={},
            risk="high",
            status="pending",
            depends_on=["confirm_clear"],
        ),
    ]
    return run


def test_unbound_clarify_is_a_plan_confirmation():
    run = _run()
    confirm = next(step for step in run.steps if step.node_id == "confirm_clear")
    assert is_plan_confirmation(confirm) is True


@pytest.mark.parametrize(
    "params",
    [
        {"question": "补客户", "target_node_id": "clear_customers"},
        {"question": "补客户", "clarification": {"reason": "missing_required"}},
    ],
)
def test_bound_or_detailed_clarify_is_not_a_plan_confirmation(params):
    step = AgentStep(node_id="c", tool_id="clarify", action="ask", params=params)
    assert is_plan_confirmation(step) is False


def test_confirm_completes_the_gate_and_resumes_the_same_run():
    run = _run()
    confirm = next(step for step in run.steps if step.node_id == "confirm_clear")
    apply_plan_confirmation(run, step_id=confirm.step_id, confirmed=True)
    assert confirm.status == "completed"
    assert confirm.output["answer_confirmed"] is True
    assert run.status == "running"
    assert run.error == ""
    # 预览步骤保持已完成，目标清空节点仍未执行。
    assert run.steps[0].status == "completed"
    assert run.steps[2].status == "pending"


def test_cancel_stops_the_plan_without_touching_business_steps():
    run = _run()
    confirm = next(step for step in run.steps if step.node_id == "confirm_clear")
    apply_plan_confirmation(run, step_id=confirm.step_id, confirmed=False)
    assert confirm.status == "failed"
    assert run.status == "cancelled"
    assert run.steps[2].status == "pending"


def test_plan_confirmation_requires_a_waiting_gate():
    run = _run()
    run.status = "running"
    confirm = next(step for step in run.steps if step.node_id == "confirm_clear")
    with pytest.raises(ClarificationAnswerError):
        apply_plan_confirmation(run, step_id=confirm.step_id, confirmed=True)


def test_orchestrator_resumes_in_place_instead_of_replanning(monkeypatch):
    from app.application.agent_orchestrator import AgentOrchestrator

    class _Repo:
        def __init__(self, run):
            self.run = run

        def get(self, run_id):
            return self.run if run_id == self.run.run_id else None

        def save_if_unchanged(self, run, previous):
            return True

        def save(self, run):
            return run

    run = _run()
    orchestrator = AgentOrchestrator.__new__(AgentOrchestrator)
    orchestrator._repo = _Repo(run)
    executed = []

    monkeypatch.setattr(
        orchestrator,
        "_execute_with_durable_lease",
        lambda current, runtime_context=None: (
            executed.append(current.run_id),
            setattr(current, "status", "completed"),
        ),
    )
    confirm = next(step for step in run.steps if step.node_id == "confirm_clear")
    result = orchestrator.continue_plan_confirmation(
        run.run_id,
        answered_by="2",
        clarification_step_id=confirm.step_id,
        confirmed=True,
    )
    assert result is run
    assert executed == [run.run_id]
    assert run.status == "completed"


def test_confirmation_decision_parsing():
    from app.application.ai_chat.workflow_session import _plan_confirmation_decision

    assert _plan_confirmation_decision("确认清空全部") is True
    assert _plan_confirmation_decision("确认") is True
    assert _plan_confirmation_decision("可以，执行") is True
    assert _plan_confirmation_decision("取消") is False
    assert _plan_confirmation_decision("不要清空了") is False
    assert _plan_confirmation_decision("改成只清空客户") is None
