from __future__ import annotations

from pathlib import Path

from retort_engine.contracts import validate_contract
from retort_engine.employee_scheduler_stress import run_employee_scheduler_stress
from retort_engine.service import RetortService


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


def test_employee_scheduler_stress_verifies_concurrent_workers(tmp_path: Path) -> None:
    result = run_employee_scheduler_stress(tmp_path, round_count=10, tasks_per_round=4, workers_per_round=2)

    assert result["status"] == "ready"
    assert result["summary"]["workers_per_round"] == 2
    assert result["summary"]["queued_task_count"] == 40
    assert result["summary"]["completed_result_count"] == 40
    assert result["summary"]["history_task_result_count"] == 40
    assert result["summary"]["process_invocation_count"] == 20
    assert result["summary"]["failed_process_count"] == 0
    assert result["summary"]["queue_result_history_consistent"] is True
    assert result["summary"]["independent_process_verified"] is True
    assert result["summary"]["concurrent_workers_verified"] is True
    assert all(len(round_["workers"]) == 2 for round_ in result["rounds"])


def test_employee_scheduler_stress_service_passes_concurrent_worker_count(tmp_path: Path) -> None:
    result = RetortService().employee_scheduler_stress(
        {"project": str(tmp_path), "rounds": 10, "tasks_per_round": 3, "workers_per_round": 3}
    )

    assert result["status"] == "ready"
    assert result["summary"]["workers_per_round"] == 3
    assert result["summary"]["concurrent_workers_verified"] is True
