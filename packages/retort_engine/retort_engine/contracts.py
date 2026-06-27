from __future__ import annotations

from typing import Any


RETORT_CONTRACT_SCHEMAS: dict[str, tuple[str, ...]] = {
    "assessment": ("project", "scores", "evidence", "metadata"),
    "absorption_result": ("status", "summary", "own_assessment", "external_assessment", "tasks", "execution", "branch_workflow"),
    "execution_result": ("status", "changed_files", "gates", "gates_passed", "review_report_path", "employee_results_path"),
    "review_report": ("run_id", "source", "external_snapshot", "license_review", "review_pipeline", "replay"),
    "pr_review_result": ("status", "summary", "files", "comments", "task_groups", "incremental"),
    "pr_dry_run_result": ("status", "pr_url", "diff_url", "summary", "review"),
    "pr_publish_dry_run_result": ("status", "pr_url", "summary", "comments", "rollback"),
    "pr_publish_sandbox_result": ("status", "pr_url", "summary", "created_receipts", "rollback_receipts"),
    "pr_live_publish_probe_result": ("status", "pr_url", "summary", "created_receipts", "rollback_receipts", "evidence"),
    "cross_project_replay_result": ("status", "project", "summary", "projects", "checks"),
    "complex_pr_replay_result": ("status", "project", "summary", "pull_requests", "evidence"),
    "task_prioritization_result": ("status", "project", "summary", "priorities", "evidence"),
    "task_dispatch_plan_result": ("status", "project", "summary", "tasks", "evidence"),
    "review_quality_benchmark_result": ("status", "project", "summary", "samples", "evidence"),
    "issue_patch_benchmark_result": ("status", "summary", "cases", "evidence"),
    "employee_scheduler_stress_result": ("status", "project", "summary", "rounds", "evidence"),
    "llm_score": ("dimension", "value", "reason"),
}


def validate_contract(name: str, payload: dict[str, Any]) -> dict[str, Any]:
    required = RETORT_CONTRACT_SCHEMAS[name]
    missing = [key for key in required if key not in payload]
    return {"name": name, "valid": not missing, "missing": missing, "required": list(required)}


def contract_names() -> tuple[str, ...]:
    return tuple(RETORT_CONTRACT_SCHEMAS)
