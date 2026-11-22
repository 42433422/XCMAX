"""审批执行结果的边界判定：仍在执行 / 结果未知都不算确定失败。"""

from types import SimpleNamespace

import pytest

from app.application.approval_workspace.workflow_bridge import _unknown_tool_outcome


def _run(*outputs):
    return SimpleNamespace(steps=[SimpleNamespace(output=output) for output in outputs])


def test_unknown_outcome_detected_from_reconciliation_flag():
    assert _unknown_tool_outcome(_run({"outcome": "unknown", "reconciliation_required": True}))


def test_plain_failure_is_not_treated_as_unknown():
    assert not _unknown_tool_outcome(_run({"success": False, "error_code": "x"}))
    assert not _unknown_tool_outcome(_run(None))
    assert not _unknown_tool_outcome(SimpleNamespace(steps=[]))


@pytest.mark.parametrize(
    "event_type", ["approval.resume_plan_rejected", "approval.resume_proof_missing"]
)
def test_rejected_resume_is_not_an_accepted_execution(event_type):
    from app.application.agent_orchestrator.run_models import AgentRun, AgentStep
    from app.application.approval_workspace.outcomes import execution_outcome, run_execution_receipt

    run = AgentRun(
        user_id="7",
        message="Resume the original approved plan",
        status="blocked",
        steps=[
            AgentStep(
                node_id="sale", tool_id="sales", action="execute_closed_loop", status="waiting_user"
            )
        ],
    )
    run.add_event(event_type, data={"execution_started": False, "step_id": run.steps[0].step_id})
    receipt = run_execution_receipt(run)
    assert receipt["execution_state"] == "blocked"
    assert receipt["execution_accepted"] is False
    assert receipt["workflow_executed"] is False
    assert execution_outcome(receipt)["status"] == "cancelled"

    # Once a real dispatch reports uncertain execution, preserve that uncertainty
    # even if the old rejected attempt remains in the event history.
    run.steps[0].output = {"outcome": "unknown", "reconciliation_required": True}
    receipt = run_execution_receipt(run)
    assert receipt["code"] == "outcome_unknown"
    assert receipt["workflow_executed"] is False
    assert execution_outcome(receipt)["status"] == "approved"
