from __future__ import annotations

from typing import Any


RETORT_CONTRACT_COMPATIBILITY_VERSION = "retort-contracts-v1"

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
    "pr_readonly_degradation_probe_result": ("status", "pr_url", "summary", "created_receipts", "rollback_receipts", "evidence"),
    "pr_long_run_review_result": ("status", "project", "summary", "pull_requests", "publish_safety_matrix", "evidence"),
    "pr_holdout_blind_eval_result": ("status", "project", "summary", "cases", "evidence"),
    "pr_failure_rollback_replay_result": ("status", "project", "summary", "cases", "evidence"),
    "cross_project_replay_result": ("status", "project", "summary", "projects", "checks"),
    "multi_project_absorption_replay_result": ("status", "project", "summary", "projects", "evidence"),
    "absorption_continuity_probe_result": ("status", "project", "summary", "runs", "latest_closed_loop", "evidence"),
    "hardening_run_result": ("run_id", "status", "summary", "changed_files", "gates", "gates_passed", "code_graph_proof", "employee_results_path"),
    "complex_pr_replay_result": ("status", "project", "summary", "pull_requests", "evidence"),
    "task_prioritization_result": ("status", "project", "summary", "priorities", "evidence"),
    "task_dispatch_plan_result": ("status", "project", "summary", "tasks", "evidence"),
    "review_quality_benchmark_result": ("status", "project", "summary", "samples", "evidence"),
    "external_advantage_matrix_result": ("status", "project", "summary", "matrix", "evidence"),
    "external_advantage_repeat_result": ("status", "project", "summary", "runs", "evidence"),
    "heterogeneous_absorption_replay_result": ("status", "project", "summary", "cases", "evidence"),
    "review_adjudication_calibration_result": ("status", "project", "summary", "cases", "evidence"),
    "review_pipeline_diff_replay_result": ("status", "pipeline_stages", "summary", "context_groups", "comments", "task_groups", "evidence"),
    "issue_patch_benchmark_result": ("status", "summary", "cases", "evidence"),
    "codebase_graph_result": ("status", "project", "summary", "nodes", "edges", "hotspots", "evidence"),
    "architecture_contract_result": ("status", "project", "summary", "contracts", "violations", "evidence"),
    "employee_scheduler_stress_result": ("status", "project", "summary", "rounds", "evidence"),
    "employee_patch_closure_result": ("status", "project", "summary", "cases", "evidence"),
    "production_recovery_drill_result": ("status", "project", "summary", "scenarios", "evidence"),
    "absorption_release_decision_result": ("status", "project", "summary", "decisions", "evidence"),
    "operator_journey_replay_result": ("status", "project", "summary", "stages", "artifacts", "live_probes", "replay", "evidence"),
    "quality_gate_bundle_result": ("status", "project", "summary", "gates", "evidence"),
    "llm_score": ("dimension", "value", "reason"),
}


def validate_contract(name: str, payload: dict[str, Any]) -> dict[str, Any]:
    required = RETORT_CONTRACT_SCHEMAS[name]
    missing = [key for key in required if key not in payload]
    return {"name": name, "valid": not missing, "missing": missing, "required": list(required), "version": RETORT_CONTRACT_COMPATIBILITY_VERSION}


def contract_compatibility_report(name: str, previous_required_fields: tuple[str, ...] | list[str]) -> dict[str, Any]:
    current_required = RETORT_CONTRACT_SCHEMAS[name]
    previous = tuple(previous_required_fields)
    removed_historical_fields = [field for field in previous if field not in current_required]
    newly_required_fields = [field for field in current_required if field not in previous]
    append_only = not removed_historical_fields
    producer_compatible = not newly_required_fields
    return {
        "name": name,
        "version": RETORT_CONTRACT_COMPATIBILITY_VERSION,
        "current_required": list(current_required),
        "previous_required": list(previous),
        "removed_historical_fields": removed_historical_fields,
        "newly_required_fields": newly_required_fields,
        "append_only": append_only,
        "producer_compatible": producer_compatible,
        "compatible": append_only and producer_compatible,
        "breaking_change": bool(removed_historical_fields or newly_required_fields),
    }


def contract_names() -> tuple[str, ...]:
    return tuple(RETORT_CONTRACT_SCHEMAS)
