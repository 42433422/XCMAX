from __future__ import annotations

from pathlib import Path

from retort_engine.contracts import validate_contract
from retort_engine.employee_scheduler_stress import run_employee_scheduler_stress


def test_employee_scheduler_stress_verifies_queue_result_history(tmp_path: Path) -> None:
    result = run_employee_scheduler_stress(tmp_path, round_count=10, tasks_per_round=3)

    assert result["status"] == "ready"
    assert result["summary"]["round_count"] == 10
    assert result["summary"]["queued_task_count"] == 30
    assert result["summary"]["completed_result_count"] == 30
    assert result["summary"]["history_task_result_count"] == 30
    assert result["summary"]["failed_process_count"] == 0
    assert result["summary"]["queue_result_history_consistent"] is True
    assert result["summary"]["independent_process_verified"] is True
    assert validate_contract("employee_scheduler_stress_result", result)["valid"] is True
