from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from retort_engine.contracts import contract_names, validate_contract
from retort_engine.feedback_audit import audit_feedback_closure
from retort_engine.history import RetortHistoryStore
from retort_engine.models import EmployeeTaskResult


def test_contract_schemas_validate_required_outputs() -> None:
    assert "assessment" in contract_names()
    assert "pr_review_result" in contract_names()
    assert "pr_dry_run_result" in contract_names()
    assert "pr_publish_dry_run_result" in contract_names()
    assert "pr_publish_sandbox_result" in contract_names()
    assert "pr_live_publish_probe_result" in contract_names()
    assert "cross_project_replay_result" in contract_names()
    assert "task_prioritization_result" in contract_names()
    assert "review_quality_benchmark_result" in contract_names()
    assert "employee_scheduler_stress_result" in contract_names()
    valid = validate_contract("execution_result", {"status": "applied", "changed_files": [], "gates": [], "gates_passed": True, "review_report_path": "report.json", "employee_results_path": "result.json"})
    review_valid = validate_contract("pr_review_result", {"status": "reviewed", "summary": {}, "files": [], "comments": [], "task_groups": [], "incremental": {}})
    dry_run_valid = validate_contract("pr_dry_run_result", {"status": "reviewed", "pr_url": "u", "diff_url": "d", "summary": {}, "review": {}})
    publish_valid = validate_contract("pr_publish_dry_run_result", {"status": "dry_run_ready", "pr_url": "u", "summary": {}, "comments": [], "rollback": {}})
    sandbox_valid = validate_contract("pr_publish_sandbox_result", {"status": "sandbox_rolled_back", "pr_url": "u", "summary": {}, "created_receipts": [], "rollback_receipts": []})
    live_probe_valid = validate_contract("pr_live_publish_probe_result", {"status": "live_rolled_back", "pr_url": "u", "summary": {}, "created_receipts": [], "rollback_receipts": [], "evidence": {}})
    replay_valid = validate_contract("cross_project_replay_result", {"status": "ready", "project": "p", "summary": {}, "projects": [], "checks": []})
    task_valid = validate_contract("task_prioritization_result", {"status": "ready", "project": "p", "summary": {}, "priorities": [], "evidence": {}})
    benchmark_valid = validate_contract("review_quality_benchmark_result", {"status": "ready", "project": "p", "summary": {}, "samples": [], "evidence": {}})
    stress_valid = validate_contract("employee_scheduler_stress_result", {"status": "ready", "project": "p", "summary": {}, "rounds": [], "evidence": {}})
    invalid = validate_contract("review_report", {"run_id": "run"})

    assert valid["valid"] is True
    assert review_valid["valid"] is True
    assert dry_run_valid["valid"] is True
    assert publish_valid["valid"] is True
    assert sandbox_valid["valid"] is True
    assert live_probe_valid["valid"] is True
    assert replay_valid["valid"] is True
    assert task_valid["valid"] is True
    assert benchmark_valid["valid"] is True
    assert stress_valid["valid"] is True
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


def test_history_store_migrates_legacy_payload_tables(tmp_path: Path) -> None:
    history = tmp_path / "legacy.sqlite"
    with sqlite3.connect(history) as conn:
        conn.executescript(
            """
            CREATE TABLE absorption_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, payload TEXT NOT NULL);
            CREATE TABLE employee_tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, payload TEXT NOT NULL);
            CREATE TABLE task_results (id INTEGER PRIMARY KEY AUTOINCREMENT, payload TEXT NOT NULL);
            """
        )

    store = RetortHistoryStore(history)
    store.record_task_result(EmployeeTaskResult("legacy-task", "completed", "migrated"))

    with sqlite3.connect(history) as conn:
        employee_cols = {row[1] for row in conn.execute("PRAGMA table_info(employee_tasks)").fetchall()}
        result_cols = {row[1] for row in conn.execute("PRAGMA table_info(task_results)").fetchall()}

    assert {"created_at", "queue_id", "task_id", "owner_hint", "status", "payload_json"} <= employee_cols
    assert {"created_at", "task_id", "status", "payload_json"} <= result_cols
