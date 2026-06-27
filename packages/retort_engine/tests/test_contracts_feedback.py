from __future__ import annotations

import json
from pathlib import Path

from retort_engine.contracts import contract_names, validate_contract
from retort_engine.feedback_audit import audit_feedback_closure
from retort_engine.history import RetortHistoryStore
from retort_engine.models import EmployeeTaskResult


def test_contract_schemas_validate_required_outputs() -> None:
    assert "assessment" in contract_names()
    assert "pr_review_result" in contract_names()
    valid = validate_contract("execution_result", {"status": "applied", "changed_files": [], "gates": [], "gates_passed": True, "review_report_path": "report.json", "employee_results_path": "result.json"})
    review_valid = validate_contract("pr_review_result", {"status": "reviewed", "summary": {}, "files": [], "comments": [], "task_groups": [], "incremental": {}})
    invalid = validate_contract("review_report", {"run_id": "run"})

    assert valid["valid"] is True
    assert review_valid["valid"] is True
    assert invalid["valid"] is False
    assert "license_review" in invalid["missing"]


def test_feedback_audit_closes_queue_result_history_loop(tmp_path: Path) -> None:
    queue = tmp_path / "employee_queue.jsonl"
    results_dir = tmp_path / "employee_results"
    history = tmp_path / "retort_history.sqlite"
    task_id = "retort-absorb-depth"
    queue.write_text(json.dumps({"task": {"task_id": task_id}}, ensure_ascii=False) + "\n", encoding="utf-8")
    results_dir.mkdir()
    (results_dir / "run.json").write_text(json.dumps({"results": [{"task_id": task_id, "status": "completed"}]}, ensure_ascii=False), encoding="utf-8")
    RetortHistoryStore(history).record_task_result(EmployeeTaskResult(task_id, "completed", "ok"))

    audit = audit_feedback_closure(queue_path=queue, history_store=history, employee_results_dir=results_dir)

    assert audit["closed"] is True
    assert audit["result_tasks_have_queue_records"] is True
    assert audit["history_matches_employee_results"] is True
