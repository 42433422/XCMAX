from __future__ import annotations

from typing import Any


RETORT_CONTRACT_SCHEMAS: dict[str, tuple[str, ...]] = {
    "assessment": ("project", "scores", "evidence", "metadata"),
    "absorption_result": ("status", "summary", "own_assessment", "external_assessment", "tasks", "execution", "branch_workflow"),
    "execution_result": ("status", "changed_files", "gates", "gates_passed", "review_report_path", "employee_results_path"),
    "review_report": ("run_id", "source", "external_snapshot", "license_review", "review_pipeline", "replay"),
    "pr_review_result": ("status", "summary", "files", "comments", "task_groups", "incremental"),
    "pr_dry_run_result": ("status", "pr_url", "diff_url", "summary", "review"),
    "llm_score": ("dimension", "value", "reason"),
}


def validate_contract(name: str, payload: dict[str, Any]) -> dict[str, Any]:
    required = RETORT_CONTRACT_SCHEMAS[name]
    missing = [key for key in required if key not in payload]
    return {"name": name, "valid": not missing, "missing": missing, "required": list(required)}


def contract_names() -> tuple[str, ...]:
    return tuple(RETORT_CONTRACT_SCHEMAS)
