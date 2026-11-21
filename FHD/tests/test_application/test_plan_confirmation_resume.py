"""计划级确认：暂停后用同一计划续跑（等价 interrupt + resume），不再要求重新规划。"""

from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

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

    assert _plan_confirmation_decision("确认清空全部") is None
    assert _plan_confirmation_decision("确认") is True
    assert _plan_confirmation_decision("可以，执行") is True
    assert _plan_confirmation_decision("取消") is False
    assert _plan_confirmation_decision("不要清空了") is False
    assert _plan_confirmation_decision("改成只清空客户") is None
    assert _plan_confirmation_decision("确认，但换成第二个") is None
    assert _plan_confirmation_decision("可以换成上个月吗") is None


@pytest.fixture
def waiting_session(monkeypatch):
    from app.application.ai_chat.workflow_session import WorkflowSession
    from app.application.workflow.workflow_types import PlanGraph, WorkflowNode, plan_to_dict

    run = _run()
    run.plan_id = "original-plan"
    plan = PlanGraph(
        plan_id=run.plan_id,
        intent="clear_customers",
        nodes=[
            WorkflowNode(
                node_id=step.node_id,
                tool_id=step.tool_id,
                action=step.action,
                params=deepcopy(step.params),
                depends_on=list(step.depends_on),
                risk=step.risk,
            )
            for step in run.steps
        ],
    )
    runtime = {"tenant_id": "tenant-1", "session_id": "session-1"}
    run.metadata.update(plan=plan_to_dict(plan), runtime_context=deepcopy(runtime))
    pending = {
        "kind": "clarification",
        "plan": plan,
        "agent_run_id": run.run_id,
        "clarification_step_id": run.steps[1].step_id,
        "runtime_context": runtime,
    }
    orchestrator = Mock(get_run=Mock(return_value=run))
    monkeypatch.setattr(
        "app.application.agent_orchestrator.AgentOrchestrator", lambda: orchestrator
    )
    callbacks = Mock(_task_owner_id=Mock(return_value="2"))
    session = WorkflowSession({"2": pending}, callbacks)
    return SimpleNamespace(
        run=run,
        plan=plan,
        pending=pending,
        runtime=runtime,
        session=session,
        orchestrator=orchestrator,
        callbacks=callbacks,
    )


@pytest.mark.parametrize(
    ("change", "reason", "path"),
    [
        ("missing", "run_missing", "task_record"),
        ("actor", "scope_mismatch", "authorization_scope"),
        ("tenant", "scope_mismatch", "authorization_scope"),
        ("session", "scope_mismatch", "authorization_scope"),
        ("params", "plan_changed", "nodes[0].params.entity"),
        ("metadata", "plan_changed", "metadata"),
        ("depends", "plan_changed", "nodes[2].depends_on"),
        ("handled", "already_handled", "task.status"),
        ("step", "step_changed", "clarification.step"),
    ],
)
def test_stale_confirmation_reports_changed_fields_without_replaying(
    waiting_session, change, reason, path
):
    state = waiting_session
    if change == "missing":
        state.orchestrator.get_run.return_value = None
    elif change == "actor":
        state.run.user_id = "foreign-private-owner"
        state.run.status = "completed"
    elif change in {"tenant", "session"}:
        state.run.metadata["runtime_context"][f"{change}_id"] = "foreign-private-scope"
    elif change == "params":
        state.run.metadata["plan"]["nodes"][0]["params"]["entity"] = "private-new-value"
    elif change == "metadata":
        state.run.metadata["plan"]["metadata"]["attachment_manifest"] = "private-new-value"
    elif change == "depends":
        state.run.metadata["plan"]["nodes"][2]["depends_on"] = ["private-new-value"]
    elif change == "handled":
        state.run.status = state.run.steps[1].status = "completed"
    else:
        state.run.steps[1].step_id = "new-private-step"
    result = state.session.continue_after_clarification("2", state.pending, "确认")
    assert (
        result["success"] is False and result["data"]["error_code"] == "workflow_confirmation_stale"
    )
    assert result["data"]["reason"] == reason
    assert path in result["data"]["changed_items"]
    assert result["run_id"] == state.run.run_id
    assert "原任务" in result["response"] and "无需重复提交" in result["response"]
    assert "private-" not in str(result) and "foreign-" not in str(result)
    state.orchestrator.continue_plan_confirmation.assert_not_called()
    state.orchestrator.continue_after_clarification.assert_not_called()
    state.callbacks._persist_plan_state.assert_not_called()


def test_unknown_or_credential_parameter_names_are_not_exposed(waiting_session):
    state = waiting_session
    current_params = state.run.metadata["plan"]["nodes"][0]["params"]
    current_params.update({"secret-from-user-as-key": "private-value", "api_key": "private-secret"})
    result = state.session.continue_after_clarification("2", state.pending, "确认")
    assert result["data"]["changed_items"] == ["nodes[0].params"]
    assert "secret" not in str(result) and "private" not in str(result)


@pytest.mark.parametrize("diagnostics_only", [False, True])
def test_cas_rejection_reads_original_run_and_reports_revision_change(
    waiting_session, diagnostics_only
):
    state = waiting_session
    newer = deepcopy(state.run)
    if diagnostics_only:
        newer.metadata["plan"]["metadata"]["planning_diagnostics"] = {"elapsed_ms": 123}
    else:
        newer.metadata["revision"] = 2
    state.orchestrator.get_run.side_effect = [state.run, newer]
    state.orchestrator.continue_plan_confirmation.return_value = None
    result = state.session.continue_after_clarification("2", state.pending, "确认")
    assert result["data"]["reason"] == "concurrent_update"
    assert result["data"]["changed_items"] == ["task.revision"]
    assert result["run_id"] == state.run.run_id and not result["success"]
    state.orchestrator.continue_plan_confirmation.assert_called_once()
    assert state.orchestrator.get_run.call_count == 2
    state.callbacks._persist_plan_state.assert_not_called()


def test_confirmation_card_mismatch_does_not_redirect_to_another_task(waiting_session):
    state = waiting_session
    handled, result = state.session.resume_pending_dynamic_workflow(
        "2", "确认", "确认", {**state.runtime, "expected_workflow_plan_id": "old-card-plan"}
    )
    assert handled and not result["success"]
    details = result["data"]["data"]
    assert details["reason"] == "confirmation_card_mismatch"
    assert details["plan_id"] == "old-card-plan" and details["changed_items"] == ["plan_id"]
    assert "run_id" not in details
    state.orchestrator.continue_plan_confirmation.assert_not_called()


def test_dispatch_stale_answer_retains_original_task_and_safe_reason(waiting_session):
    from app.application.ai_chat.planned_workflow_dispatch import PlannedWorkflowDispatch

    state = waiting_session
    original = deepcopy(state.run)
    state.run.status = state.run.steps[1].status = "completed"
    state.orchestrator.continue_planning_clarification.return_value = None
    dispatch = PlannedWorkflowDispatch({}, state.callbacks, Mock(), Mock(), Mock())
    result = dispatch._run_admitted_plan(
        user_id="2",
        message="确认",
        plan=state.plan,
        runtime_context=state.runtime,
        continuation={"run": original, "step_id": original.steps[1].step_id, "answer": "确认"},
    )
    assert result["success"] is False and result["data"]["reason"] == "already_handled"
    assert result["data"]["action"] == "workflow_risk_rejected"
    assert result["data"]["error_code"] == "workflow_confirmation_stale"
    assert result["run_id"] == original.run_id
    state.orchestrator.continue_planning_clarification.assert_called_once()
    state.orchestrator.start_run_from_plan.assert_not_called()
