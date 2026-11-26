"""Do not infer absence of business effects from failed verification."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.application.agent_orchestrator import result_verification
from app.domain.task_lifecycle.results import execution_result_proven_not_executed
from app.infrastructure.xiaox import receipts


@pytest.mark.parametrize(
    "output",
    [
        {"success": False, "error": "missing evidence"},
        {"success": False, "execution": {"outcome": "unknown", "committed": False}},
        {"success": False, "execution": {"outcome": "not_executed", "committed": True}},
        {
            "success": False,
            "execution": {"outcome": "not_executed", "committed": False},
            "data": {"result": {"success": True}},
        },
        {
            "success": False,
            "execution": {"outcome": "not_executed", "committed": False},
            "data": {"result": {"execution": {"outcome": "unknown"}}},
        },
    ],
)
def test_failure_without_consistent_no_effect_evidence_is_not_proven(output):
    assert execution_result_proven_not_executed(output) is False
    step = SimpleNamespace(status="failed")
    record = SimpleNamespace(status="failed", output=output)
    child = SimpleNamespace(status="failed", artifacts=[], tool_calls=[record])
    assert receipts._failed_execution_receipt(child, step, record) is None


def test_no_effect_receipt_requires_original_frozen_binding(monkeypatch):
    output = {
        "success": False,
        "execution": {"outcome": "not_executed", "committed": False, "effect": "none"},
    }
    step = SimpleNamespace(status="failed")
    record = SimpleNamespace(status="failed", output=output, metadata={})
    child = SimpleNamespace(status="failed", artifacts=[], tool_calls=[record], metadata={})
    assert execution_result_proven_not_executed(output) is True
    assert receipts._failed_execution_receipt(child, step, record) is None
    monkeypatch.setattr(result_verification, "_binding_valid", lambda *args: True)
    assert receipts._failed_execution_receipt(child, step, record) == output["execution"]
    child.artifacts.append(object())
    assert receipts._failed_execution_receipt(child, step, record) is None
    child.artifacts.clear()
    child.tool_calls.append(record)
    assert receipts._failed_execution_receipt(child, step, record) is None


@pytest.mark.parametrize("status", ["failed", "blocked"])
@pytest.mark.parametrize(
    "output",
    [
        {"success": False, "error": "readback failed"},
        {"success": False, "execution": {"outcome": "unknown"}},
    ],
)
def test_uncertain_write_receipt_cannot_be_retried(monkeypatch, status, output):
    record = SimpleNamespace(
        status="failed",
        output=output,
        metadata={},
        cost_units=0,
        to_dict=lambda: {"output": output},
    )
    step = SimpleNamespace(status="failed", output=output)
    child = SimpleNamespace(
        status=status,
        user_id="owner",
        run_id="original",
        updated_at="now",
        metadata={
            "runtime_context": {"tenant_id": "tenant", "parent_run_id": "parent"},
            "task_context": {"task_id": "task"},
        },
        steps=[step],
        tool_calls=[record],
        llm_calls=[],
        artifacts=[],
    )
    monkeypatch.setattr(
        result_verification,
        "summarize_verification",
        lambda run: {"accepted": False, "status": "inconclusive"},
    )
    repository = Mock()
    repository.get.return_value = child
    binding = _receipt_binding()
    binding.run_id = "parent"
    result = receipts.read_call_receipt(
        SimpleNamespace(repository=repository),
        binding,
        {"child_task_id": "task", "child_run_id": "original"},
    )
    assert result["status"] == "unknown"
    assert result["retryable"] is False
    assert result["reconciliation_required"] is True
    repository.get_task.assert_not_called()


def _receipt_binding():
    return SimpleNamespace(
        run=SimpleNamespace(user_id="owner", metadata={"runtime_context": {"tenant_id": "tenant"}}),
        metadata={
            "generation": 1,
            "coordinator_active": True,
            "revoked": False,
            "expires_at": 10**12,
        },
    )


def test_missing_bound_child_cannot_adopt_current_attempt_or_report_claimed():
    repository = Mock()
    repository.get.return_value = None
    result = receipts.read_call_receipt(
        SimpleNamespace(repository=repository),
        _receipt_binding(),
        {
            "child_task_id": "task",
            "child_run_id": "original",
            "state": "claimed",
            "generation": 1,
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
        attempt=attempt,
        run_count=run_count,
        active_run_id="replacement",
    )
    result = receipts.read_call_receipt(
        SimpleNamespace(repository=repository),
        _receipt_binding(),
        {"child_task_id": "task", "state": "claimed", "generation": 1},
    )
    assert result["status"] == "unknown"
    assert result["retryable"] is False
    repository.get.assert_not_called()
    repository.get_task.assert_called_once_with(
        user_id="owner", task_id="task", tenant_id="tenant"
    )


def test_lost_binding_ack_can_read_only_the_single_original_admission():
    repository = Mock()
    repository.get_task.return_value = SimpleNamespace(
        attempt=1,
        run_count=1,
        active_run_id="original",
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
