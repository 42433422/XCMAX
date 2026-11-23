"""HTTP projections preserve a rejected receipt without advertising success or retry."""

from __future__ import annotations

import copy
from types import SimpleNamespace

import pytest

from app.domain.task_lifecycle.results import agent_node_output


def _run(output, *, verification_status="inconclusive", accepted=False):
    return SimpleNamespace(
        run_id="original-run",
        status="blocked",
        error="删除成功",
        final_output={"node_outputs": {"delete": copy.deepcopy(output)}},
        steps=[SimpleNamespace(node_id="delete", output=copy.deepcopy(output))],
        tool_calls=[
            SimpleNamespace(
                node_id="delete",
                output=copy.deepcopy(output),
                metadata={
                    "verification_contract": {"call_id": "original-call"},
                    "verification": {
                        "status": verification_status,
                        "accepted": accepted,
                        "code": "original_receipt_unavailable",
                    },
                },
            )
        ],
    )


@pytest.mark.parametrize("status", ["failed", "inconclusive"])
def test_rejected_success_stays_unknown_and_preserves_the_original_receipt(status):
    run = _run(
        {"success": True, "message": "删除成功", "deleted": 2},
        verification_status=status,
    )
    original = copy.deepcopy(run)
    output = agent_node_output(run, "delete")
    assert output["success"] is False
    assert output["retryable"] is False
    assert output["reconciliation_required"] is True
    assert output["outcome"] == "unknown"
    assert output["error_code"] == f"result_verification_{status}"
    assert output["verification_code"] == "original_receipt_unavailable"
    assert output["deleted"] == 2
    assert "删除成功" not in output["message"]
    assert "核验" in output["message"]
    assert output["run_id"] == output["agent_run_id"] == "original-run"
    assert run == original


def test_pre_dispatch_permission_denial_keeps_its_no_execution_semantics():
    denial = {
        "success": False,
        "error_code": "permission_denied",
        "message": "未授权，未执行",
        "execution_status": "not_started",
        "http_status": 403,
    }
    run = _run(denial, verification_status="failed")
    output = agent_node_output(run, "delete")
    assert {key: output[key] for key in denial} == denial
    assert "reconciliation_required" not in output
    assert "outcome" not in output


def test_other_nodes_and_an_old_rejection_cannot_override_the_latest_node_receipt():
    run = _run({"success": True, "data": {"id": 7}})
    run.tool_calls.append(
        SimpleNamespace(
            node_id="delete",
            metadata={
                "verification_contract": {"call_id": "readback-call"},
                "verification": {"status": "verified", "accepted": True},
            },
        )
    )
    unrelated = copy.deepcopy(run.tool_calls[0])
    unrelated.node_id = "other"
    run.tool_calls.append(unrelated)
    assert agent_node_output(run, "delete")["success"] is True


def test_pending_approval_is_not_projected_as_an_unknown_write():
    run = _run({"success": True, "pending_approval": True}, verification_status="pending")
    run.status = "waiting_user"
    output = agent_node_output(run, "delete")
    assert output["pending_approval"] is True
    assert "reconciliation_required" not in output
    assert output["agent_status"] == "waiting_user"
