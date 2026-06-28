from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from retort_engine.core_refactor_execution import verify_core_refactor_execution
from retort_engine.ui_features import blackhole_ui_detected, blackhole_ui_structure


@dataclass(frozen=True)
class Score:
    dimension: str
    value: float
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"dimension": self.dimension, "value": self.value, "reason": self.reason}


@dataclass(frozen=True)
class Assessment:
    project: str
    scores: tuple[Score, ...]
    evidence: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def score_map(self) -> dict[str, float]:
        return {score.dimension: score.value for score in self.scores}

    def all_scores_over(self, threshold: float) -> bool:
        return bool(self.scores) and all(score.value > threshold for score in self.scores)

    def to_dict(self) -> dict[str, Any]:
        return {"project": self.project, "scores": [score.to_dict() for score in self.scores], "evidence": list(self.evidence), "metadata": self.metadata}


@dataclass(frozen=True)
class AssessmentDependencies:
    read_text: Callable[[Path], str]
    run_command: Callable[[list[str], Path], bool]
    python_command: Callable[[], str]
    tracking_state: Callable[[Path], str]
    closed_loop_proof: Callable[[Path], dict[str, Any]]
    capability_absorption_audit: Callable[[Path], dict[str, Any]]
    public_absorption_state: Callable[[Path], dict[str, Any]]


def assess_project(project: str, *, run_local_gates: bool = False, context_policy: str = "isolated", dependencies: AssessmentDependencies) -> Assessment:
    del context_policy
    root = Path(project).expanduser().resolve()
    files = project_files(root, {".git", ".retort", "__pycache__"})
    text = "\n".join(dependencies.read_text(path) for path in files if path.suffix.lower() in {".py", ".js", ".html", ".css", ".md", ".toml", ".yml", ".yaml"})
    tests = [path for path in files if path.name.startswith("test_") and path.suffix == ".py"]
    test_functions = sum(len(re.findall(r"^\s*def\s+test_", dependencies.read_text(path), re.M)) for path in tests)
    lint_ok = test_ok = False
    if run_local_gates:
        lint_ok = dependencies.run_command([dependencies.python_command(), "-m", "ruff", "check", "."], root)
        test_ok = dependencies.run_command([dependencies.python_command(), "-m", "pytest", "tests", "-q"], root) if (root / "tests").is_dir() else False
    features = _feature_flags(text, root)
    tracked = dependencies.tracking_state(root)
    proof = dependencies.closed_loop_proof(root)
    capability_audit = dependencies.capability_absorption_audit(root)
    refactor_execution = verify_core_refactor_execution(root)
    state = dependencies.public_absorption_state(root)
    evidence = tuple(
        [
            f"source_files={len(files)}",
            f"test_functions={test_functions}",
            f"git_tracking_state={tracked}",
            f"lint={lint_ok}",
            f"test={test_ok}",
            f"closed_loop_verified={proof['verified']}",
            f"closed_loop_missing={','.join(proof['missing'])}",
            f"absorption_active={state.get('active')}",
            f"absorption_status={state.get('status')}",
            f"core_refactor_execution_status={refactor_execution.get('status')}",
            f"core_refactor_implemented_tasks={refactor_execution.get('implemented_task_count')}/{refactor_execution.get('task_count')}",
        ]
        + [f"{key}={value}" for key, value in features.items()]
    )
    metadata = {
        "features": features,
        "git_tracking_state": tracked,
        "absorption_state": state,
        "closed_loop_proof": proof,
        "capability_absorption_audit": capability_audit,
        "core_refactor_execution": refactor_execution,
        "blackhole_ui_structure": blackhole_ui_structure(root),
        "score_authority": "paibi_llm_prompt_only",
        "local_scores_removed": True,
    }
    return Assessment(str(root), (), evidence, metadata)


def project_files(root: Path, skip_parts: set[str]) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel_parts = path.relative_to(root).parts
        if any(part in skip_parts for part in rel_parts):
            continue
        files.append(path)
    return files


def _feature_flags(text: str, root: Path) -> dict[str, bool]:
    return {
        "blackhole_ui": blackhole_ui_detected(root),
        "folder_project_picker": "ownProjectFolder" in text and "externalProjectFolder" in text,
        "github_or_folder_source": "github_url" in text and "external_path" in text,
        "branch_workflow": "begin_absorption_branch" in text and "merge_absorption_branch" in text,
        "employee_queue": "employee_queue" in text and "RetortHistory" in text,
        "license_gate": "license" in text.lower() and "incompatible" in text.lower(),
        "license_boundary_tests": "DEFAULT_BLOCKED_LICENSES" in text and "AGPL" in text and "enforce=True" in text,
        "service_api": "RetortService" in text and "RetortUIServer" in text,
        "self_evolution": "RetortSelfEvolutionRunner" in text and "scores_repeated_without_convergence" in text,
        "real_absorption_cli": "apply_real_absorption" in text and "apply-absorption" in text and "execution_requests" in text,
        "execution_proof_recorder": "_record_execution_proof" in text and "closed_loop_proof" in text and "gates_passed" in text,
        "component_review_pipeline": "build_absorption_review_report" in text and "compare_component_gaps" in text and "group_review_files" in text,
        "api_contract_schemas": "RETORT_CONTRACT_SCHEMAS" in text and "validate_contract" in text,
        "feedback_audit": "audit_feedback_closure" in text and "history_result_count" in text,
        "diff_hunk_review": "diff hunk" in text.lower() and "patch set" in text.lower(),
        "pr_review_runtime": "review_diff" in text and "parse_unified_diff" in text and "review-diff" in text,
        "pr_review_api": "/api/review-diff" in text and "pr_review_result" in text,
        "incremental_pr_review": "previous_diff_text" in text and "skipped_existing_change_count" in text,
        "pr_dry_run": "review-pr" in text and "review_pr_url" in text and "/api/review-pr" in text,
        "pr_publish_dry_run": "publish-pr-dry-run" in text and "build_publish_dry_run" in text and "/api/publish-pr-dry-run" in text,
        "pr_publish_sandbox": "publish-pr-sandbox" in text and "run_publish_sandbox" in text and "/api/publish-pr-sandbox" in text,
        "pr_live_publish_probe": "publish-pr-live-probe" in text and "run_live_pr_comment_probe" in text and "/api/publish-pr-live-probe" in text,
        "pr_low_permission_probe": "publish-pr-low-permission-probe" in text and "run_low_permission_pr_degradation_probe" in text,
        "pr_long_run_review": "pr-long-run-review" in text and "build_pr_long_run_review" in text,
        "pr_holdout_blind_eval": "pr-holdout-blind-eval" in text and "build_pr_holdout_blind_eval" in text and "/api/pr-holdout-blind-eval" in text,
        "pr_failure_rollback_replay": "pr-failure-rollback-replay" in text and "build_pr_failure_rollback_replay" in text and "/api/pr-failure-rollback-replay" in text,
        "cross_project_replay": "cross-project-replay" in text and "build_cross_project_replay" in text and "/api/cross-project-replay" in text,
        "multi_project_absorption_replay": "multi-project-absorption-replay" in text and "build_multi_project_absorption_replay" in text,
        "absorption_continuity_probe": "absorption-continuity-probe" in text and "build_absorption_continuity_probe" in text,
        "post_absorption_hardening_run": "record-hardening-run" in text and "record_post_absorption_hardening_run" in text,
        "complex_pr_replay": "complex-pr-replay" in text and "build_complex_pr_replay_report" in text,
        "task_prioritization": "task-prioritization-report" in text and "build_task_prioritization_report" in text,
        "task_dispatch_plan": "task-dispatch-plan" in text and "build_task_dispatch_plan" in text,
        "review_quality_benchmark": "quality-benchmark-report" in text and "build_review_quality_benchmark" in text,
        "external_advantage_matrix": "external-advantage-matrix" in text and "build_external_advantage_matrix" in text and "/api/external-advantage-matrix" in text,
        "external_advantage_ci_regression": "external-advantage-ci-regression" in text and "build_external_advantage_ci_regression" in text,
        "external_process_adjudication": "external-process-adjudication" in text and "build_external_process_adjudication" in text,
        "external_advantage_repeat": "external-advantage-repeat" in text and "build_external_advantage_repeat" in text and "/api/external-advantage-repeat" in text,
        "upstream_pr_ci_probe": "upstream-pr-ci-probe" in text and "build_upstream_pr_ci_probe" in text,
        "competitor_runtime_comparison": "competitor-runtime-comparison" in text and "build_competitor_runtime_comparison" in text,
        "cross_domain_end_to_end": "cross-domain-end-to-end" in text and "build_cross_domain_end_to_end" in text,
        "cross_domain_ci_regression": "cross-domain-ci-regression" in text and "build_cross_domain_ci_regression" in text,
        "contract_stability_stress": "contract-stability-stress" in text and "build_contract_stability_stress" in text,
        "review_adjudication_calibration": "review-adjudication-calibration" in text and "build_review_adjudication_calibration" in text,
        "review_calibration_policy": "calibration_context_rank_weight" in text and "calibration_policy_enabled" in text,
        "codebase_graph": "codebase-graph-report" in text and "build_codebase_graph" in text and "codebase_graph_result" in text,
        "architecture_contracts": "architecture-contract-report" in text and "evaluate_architecture_contracts" in text and "architecture_contract_result" in text,
        "employee_scheduler_stress": "employee-scheduler-stress" in text and "run_employee_scheduler_stress" in text,
        "employee_patch_closure": "employee-patch-closure" in text and "run_employee_patch_closure_suite" in text,
        "employee_patch_stress": "employee-patch-stress" in text and "build_employee_patch_stress" in text and "employee_patch_stress_result" in text,
        "production_recovery_drill": "production-recovery-drill" in text and "build_production_recovery_drill" in text,
        "absorption_release_decision": "absorption-release-decision" in text and "build_absorption_release_decision" in text,
        "real_github_case": "https://github.com/openai/codex" in text,
    }
