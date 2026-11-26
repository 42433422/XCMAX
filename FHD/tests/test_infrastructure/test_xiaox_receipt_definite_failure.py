"""A definitively failed write must be retryable, not reported as unknown."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.infrastructure.xiaox import receipts

FAILED_STEP = SimpleNamespace(
    status="failed",
    output={
        "data": {
            "result": {
                "outputs": [
                    {"output": {"ok": False, "error": "非法 Excel 表格名称：'销售明细表'"}}
                ]
            }
        }
    },
)


def child(*, status="blocked", artifacts=(), tool_calls=(), steps=(FAILED_STEP,)):
    return SimpleNamespace(
        status=status, artifacts=list(artifacts), tool_calls=list(tool_calls),
        steps=list(steps), metadata={},
    )


def test_blocked_child_without_effect_is_definite_failure():
    assert receipts._definitely_not_applied(child(), {"status": "failed", "accepted": False}) is True
    assert receipts._failed_step_detail(child()) == "非法 Excel 表格名称：'销售明细表'"


def test_completed_or_artifact_child_is_not_definite_failure():
    verification = {"status": "failed", "accepted": False}
    assert receipts._definitely_not_applied(child(status="completed"), verification) is False
    assert receipts._definitely_not_applied(
        child(artifacts=[SimpleNamespace(id="artifact")]), verification
    ) is False


def test_successful_tool_call_is_not_definite_failure():
    calls = [SimpleNamespace(output={"success": True})]
    assert receipts._definitely_not_applied(
        child(tool_calls=calls), {"status": "failed", "accepted": False}
    ) is False

def _receipt_binding():
    return SimpleNamespace(
        run=SimpleNamespace(user_id="owner", metadata={"runtime_context": {"tenant_id": "tenant"}}),
        metadata={"generation": 1, "coordinator_active": True, "revoked": False, "expires_at": 10**12},
    )


def test_missing_bound_child_cannot_adopt_current_attempt_or_report_claimed():
    repository = Mock()
    repository.get.return_value = None
    result = receipts.read_call_receipt(
        SimpleNamespace(repository=repository),
        _receipt_binding(),
        {
            "child_task_id": "task", "child_run_id": "original",
            "state": "claimed", "generation": 1,
        },
    )
    assert result["run_id"] == "original"
    assert result["status"] == "unknown"
    assert result["reconciliation_required"] is True
    assert result["retryable"] is False
    repository.get.assert_called_once_with("original")
    repository.get_task.assert_not_called()


@pytest.mark.parametrize(("attempt", "run_count"), [(2, 2), (1, 2), (2, 1)])
def test_unbound_receipt_cannot_adopt_multiple_admissions(attempt, run_count):
    repository = Mock()
    repository.get_task.return_value = SimpleNamespace(
        attempt=attempt, run_count=run_count, active_run_id="replacement",
    )
    result = receipts.read_call_receipt(
        SimpleNamespace(repository=repository),
        _receipt_binding(),
        {"child_task_id": "task", "state": "claimed", "generation": 1},
    )
    assert result["status"] == "unknown"
    assert result["retryable"] is False
    repository.get.assert_not_called()
    repository.get_task.assert_called_once_with(user_id="owner", task_id="task", tenant_id="tenant")


def test_lost_binding_ack_can_read_only_the_single_original_admission():
    repository = Mock()
    repository.get_task.return_value = SimpleNamespace(
        attempt=1, run_count=1, active_run_id="original",
    )
    repository.get.return_value = SimpleNamespace(user_id="other", metadata={})
    with pytest.raises(receipts.XiaoxBindingError) as exc:
        receipts.read_call_receipt(
            SimpleNamespace(repository=repository),
            _receipt_binding(),
            {"child_task_id": "task", "state": "claimed", "generation": 1},
        )
    assert exc.value.code == "owner_changed"
    repository.get.assert_called_once_with("original")
