from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from retort_engine.absorption_state import closed_loop_proof, load_absorption_state
from retort_engine.capability_audit import capability_absorption_audit, employee_result_files, pr_review_runtime_evidence
from retort_engine.contracts import contract_names
from retort_engine.core_refactor_execution import verify_core_refactor_execution


def llm_absorption_evidence(project: Path) -> list[str]:
    evidence: list[str] = []
    state = load_absorption_state(project)
    proof = closed_loop_proof(project)
    if state.get("source"):
        evidence.append(f"absorption_source={state.get('source')}")
    if state.get("external_path"):
        external_path = Path(str(state.get("external_path")))
        evidence.append(f"external_materialized_path={state.get('external_path')}; exists={external_path.is_dir()}")
    if proof.get("verified"):
        evidence.append("closed_loop_five_proofs_verified=True")
    evidence.append(f"contract_schema_count={len(contract_names())}")

    audit = capability_absorption_audit(project)
    refactor_execution = verify_core_refactor_execution(project)
    evidence.extend(_capability_audit_evidence(audit, refactor_execution, project))
    evidence.extend(_pr_runtime_evidence(project))
    evidence.extend(_report_evidence(project))
    evidence.extend(proof.get("evidence") or [])
    evidence.extend(_external_review_evidence(project))
    evidence.extend(_employee_result_evidence(project))
    return evidence


def _capability_audit_evidence(audit: dict[str, Any], refactor_execution: dict[str, Any], project: Path) -> list[str]:
    evidence = [
        f"capability_absorption_local_score_removed={audit.get('local_score_removed', True)}",
        f"capability_absorption_status={audit.get('status')}",
        f"capability_absorption_risk_level={audit.get('risk_level')}",
        f"capability_absorption_blockers={','.join(str(item) for item in audit.get('blockers') or [])}",
        f"capability_absorption_reason={audit.get('reason')}",
        f"behavior_source_file_count={len(audit.get('behavior_source_files') or [])}",
        f"behavior_test_file_count={len(audit.get('behavior_test_files') or [])}",
        f"test_to_source_ratio={audit.get('test_to_source_ratio', '')}",
    ]
    hardening = audit.get("post_absorption_hardening") if isinstance(audit.get("post_absorption_hardening"), dict) else {}
    evidence.extend(
        [
            f"post_absorption_hardening_file_count={hardening.get('file_count', '')}",
            f"post_absorption_hardening_source_count={len(hardening.get('behavior_source_files') or [])}",
            f"post_absorption_hardening_test_count={len(hardening.get('behavior_test_files') or [])}",
        ]
    )
    behavior_test = project / "tests" / "test_absorbed_capabilities.py"
    if behavior_test.is_file():
        behavior_test_count = len(re.findall(r"^\s*def\s+test_", read_text(behavior_test), re.M))
        evidence.append(f"behavior_test_function_count={behavior_test_count}")
    evidence.extend(
        [
            f"generated_evidence_file_count={len(audit.get('generated_evidence_files') or [])}",
            f"employee_execution_mode={audit.get('employee_execution_mode', '')}",
        ]
    )
    worker_review = audit.get("employee_worker_review") if isinstance(audit.get("employee_worker_review"), dict) else {}
    evidence.extend(
        [
            f"employee_worker_review_status={worker_review.get('status', '')}",
            f"employee_worker_review_file_count={worker_review.get('file_count', '')}",
            f"employee_worker_review_comment_count={worker_review.get('comment_count', '')}",
            f"employee_worker_review_artifact_exists={worker_review.get('artifact_exists', False)}",
            f"external_project_count={audit.get('external_project_count', '')}",
            f"core_refactor_execution_status={refactor_execution.get('status')}",
            f"core_refactor_implemented_tasks={refactor_execution.get('implemented_task_count')}/{refactor_execution.get('task_count')}",
            f"core_refactor_missing_count={len(refactor_execution.get('missing') or [])}",
        ]
    )
    return evidence


def _pr_runtime_evidence(project: Path) -> list[str]:
    pr_review = pr_review_runtime_evidence(project)
    return [
        f"pr_review_runtime={pr_review.get('runtime')}",
        f"pr_review_cli={pr_review.get('cli')}",
        f"pr_review_api={pr_review.get('api')}",
        f"pr_review_contract={pr_review.get('contract')}",
        f"pr_review_test_function_count={pr_review.get('test_function_count')}",
        f"pr_review_sample_comment_count={pr_review.get('sample_comment_count')}",
        f"pr_review_publishable_comment_count={pr_review.get('publishable_comment_count')}",
        f"pr_review_comment_ranking_model={pr_review.get('comment_ranking_model')}",
        f"pr_review_incremental={pr_review.get('incremental')}",
        f"pr_review_incremental_skipped_count={pr_review.get('incremental_skipped_count')}",
        f"pr_review_incremental_new_count={pr_review.get('incremental_new_count')}",
        f"pr_dry_run_runtime={pr_review.get('dry_run_runtime')}",
        f"pr_dry_run_cli={pr_review.get('dry_run_cli')}",
        f"pr_dry_run_api={pr_review.get('dry_run_api')}",
        f"pr_dry_run_contract={pr_review.get('dry_run_contract')}",
        f"pr_dry_run_report_status={pr_review.get('dry_run_report_status')}",
        f"pr_dry_run_report_pr_url={pr_review.get('dry_run_report_pr_url')}",
        f"pr_dry_run_report_comment_count={pr_review.get('dry_run_report_comment_count')}",
        f"pr_dry_run_report_file_count={pr_review.get('dry_run_report_file_count')}",
        f"pr_review_benchmark_status={pr_review.get('benchmark_status')}",
        f"pr_review_benchmark_sample_count={pr_review.get('benchmark_sample_count')}",
        f"pr_review_benchmark_baseline_score={pr_review.get('benchmark_baseline_aggregate_score')}",
        f"pr_review_benchmark_aggregate_score={pr_review.get('benchmark_aggregate_score')}",
        f"pr_review_benchmark_post_absorption_delta={pr_review.get('benchmark_post_absorption_delta')}",
        f"pr_review_benchmark_publishable_comment_count={pr_review.get('benchmark_publishable_comment_count')}",
        f"review_pipeline_diff_replay_status={pr_review.get('diff_pipeline_status')}",
        f"review_pipeline_diff_replay_depth_score={pr_review.get('diff_pipeline_depth_score')}",
        f"review_pipeline_diff_replay_context_groups={pr_review.get('diff_pipeline_context_group_count')}",
        f"review_pipeline_diff_replay_task_groups={pr_review.get('diff_pipeline_task_group_count')}",
        f"review_pipeline_diff_replay_publishable_comments={pr_review.get('diff_pipeline_publishable_comment_count')}",
        f"review_pipeline_diff_replay_chunk_count={pr_review.get('diff_pipeline_chunk_count')}",
        f"review_pipeline_diff_replay_large_chunking={pr_review.get('diff_pipeline_large_chunking')}",
    ]


def _report_evidence(project: Path) -> list[str]:
    publish_report = read_json(project / "docs" / "retort_pr_publish_dry_run.json")
    publish_summary = publish_report.get("summary") if isinstance(publish_report.get("summary"), dict) else {}
    sandbox_report = read_json(project / "docs" / "retort_pr_publish_sandbox.json")
    sandbox_summary = sandbox_report.get("summary") if isinstance(sandbox_report.get("summary"), dict) else {}
    live_probe = read_json(project / "docs" / "retort_pr_live_publish_probe.json")
    live_summary = live_probe.get("summary") if isinstance(live_probe.get("summary"), dict) else {}
    replay_report = read_json(project / "docs" / "retort_cross_project_replay.json")
    replay_summary = replay_report.get("summary") if isinstance(replay_report.get("summary"), dict) else {}
    replay_checks = [item for item in replay_report.get("checks") or [] if isinstance(item, dict)]
    complex_pr_report = read_json(project / "docs" / "retort_complex_pr_replay.json")
    complex_pr_summary = complex_pr_report.get("summary") if isinstance(complex_pr_report.get("summary"), dict) else {}
    pipeline_replay_report = read_json(project / "docs" / "retort_review_pipeline_diff_replay.json")
    pipeline_replay_summary = pipeline_replay_report.get("summary") if isinstance(pipeline_replay_report.get("summary"), dict) else {}
    task_report = read_json(project / "docs" / "retort_task_prioritization_report.json")
    task_summary = task_report.get("summary") if isinstance(task_report.get("summary"), dict) else {}
    dispatch_report = read_json(project / "docs" / "retort_employee_task_dispatch_plan.json")
    dispatch_summary = dispatch_report.get("summary") if isinstance(dispatch_report.get("summary"), dict) else {}
    benchmark_report = read_json(project / "docs" / "retort_review_quality_benchmark.json")
    benchmark_summary = benchmark_report.get("summary") if isinstance(benchmark_report.get("summary"), dict) else {}
    stress_report = read_json(project / "docs" / "retort_employee_scheduler_stress.json")
    stress_summary = stress_report.get("summary") if isinstance(stress_report.get("summary"), dict) else {}
    return [
        f"pr_publish_dry_run_status={publish_report.get('status', '')}",
        f"pr_publish_dry_run_comment_count={publish_summary.get('would_post_comment_count', '')}",
        f"pr_publish_dry_run_permission={publish_summary.get('permission_required', '')}",
        f"pr_publish_dry_run_rollback={(publish_report.get('rollback') or {}).get('strategy', '') if isinstance(publish_report.get('rollback'), dict) else ''}",
        f"pr_publish_sandbox_status={sandbox_report.get('status', '')}",
        f"pr_publish_sandbox_created_count={sandbox_summary.get('created_comment_count', '')}",
        f"pr_publish_sandbox_rollback_verified={sandbox_summary.get('rollback_verified', '')}",
        f"pr_live_publish_probe_status={live_probe.get('status', '')}",
        f"pr_live_publish_probe_pr_url={live_probe.get('pr_url', '')}",
        f"pr_live_publish_probe_target_repo={live_summary.get('target_repo', '')}",
        f"pr_live_publish_probe_created_count={live_summary.get('created_comment_count', '')}",
        f"pr_live_publish_probe_rollback_verified={live_summary.get('rollback_verified', '')}",
        f"pr_live_publish_probe_permission_admin={live_summary.get('permission_admin', '')}",
        f"pr_live_publish_probe_permission_maintain={live_summary.get('permission_maintain', '')}",
        f"pr_live_publish_probe_permission_push={live_summary.get('permission_push', '')}",
        f"pr_live_publish_probe_live_write={live_summary.get('live_github_write', '')}",
        f"cross_project_replay_status={replay_report.get('status', '')}",
        f"cross_project_replay_external_project_count={replay_summary.get('external_project_count', '')}",
        f"cross_project_replay_distinct_signal_count={replay_summary.get('distinct_signal_count', '')}",
        f"cross_project_replay_passed_checks={sum(1 for item in replay_checks if item.get('passed'))}/{len(replay_checks)}",
        f"complex_pr_replay_status={complex_pr_report.get('status', '')}",
        f"complex_pr_replay_pr_count={complex_pr_summary.get('pr_count', '')}",
        f"complex_pr_replay_reviewed_pr_count={complex_pr_summary.get('reviewed_pr_count', '')}",
        f"complex_pr_replay_complex_pr_count={complex_pr_summary.get('complex_pr_count', '')}",
        f"complex_pr_replay_total_file_count={complex_pr_summary.get('total_file_count', '')}",
        f"complex_pr_replay_total_hunk_count={complex_pr_summary.get('total_hunk_count', '')}",
        f"complex_pr_replay_total_comment_count={complex_pr_summary.get('total_comment_count', '')}",
        f"complex_pr_replay_total_reviewed_change_count={complex_pr_summary.get('total_reviewed_new_change_count', '')}",
        f"complex_pr_replay_truncated_pr_count={complex_pr_summary.get('truncated_pr_count', '')}",
        f"review_pipeline_diff_replay_report_status={pipeline_replay_report.get('status', '')}",
        f"review_pipeline_diff_replay_report_depth_score={pipeline_replay_summary.get('diff_grouping_depth_score', '')}",
        f"review_pipeline_diff_replay_report_context_groups={pipeline_replay_summary.get('context_group_count', '')}",
        f"review_pipeline_diff_replay_report_task_groups={pipeline_replay_summary.get('task_group_count', '')}",
        f"review_pipeline_diff_replay_report_chunk_count={pipeline_replay_summary.get('chunk_count', '')}",
        f"review_pipeline_diff_replay_report_large_chunking={pipeline_replay_summary.get('large_diff_chunking', '')}",
        f"task_prioritization_status={task_report.get('status', '')}",
        f"task_prioritization_queued_count={task_summary.get('queued_task_count', '')}",
        f"task_prioritization_completed_count={task_summary.get('completed_result_count', '')}",
        f"task_prioritization_dimension_count={task_summary.get('prioritized_dimension_count', '')}",
        f"task_prioritization_ready_employee_task_count={task_summary.get('ready_employee_task_count', '')}",
        f"task_prioritization_feedback_driven_count={task_summary.get('feedback_driven_priority_count', '')}",
        f"task_prioritization_employee_feedback_applied={task_summary.get('employee_feedback_applied', '')}",
        f"task_prioritization_all_tasks_have_acceptance={task_summary.get('all_tasks_have_acceptance', '')}",
        f"task_dispatch_plan_status={dispatch_report.get('status', '')}",
        f"task_dispatch_plan_source_llm_task_count={dispatch_summary.get('source_llm_task_count', '')}",
        f"task_dispatch_plan_ready_task_count={dispatch_summary.get('ready_task_count', '')}",
        f"task_dispatch_plan_dispatch_task_count={dispatch_summary.get('dispatch_task_count', '')}",
        f"task_dispatch_plan_queued_dispatch_count={dispatch_summary.get('queued_dispatch_count', '')}",
        f"task_dispatch_plan_all_tasks_have_owner={dispatch_summary.get('all_tasks_have_owner', '')}",
        f"task_dispatch_plan_all_tasks_have_acceptance={dispatch_summary.get('all_tasks_have_acceptance', '')}",
        f"task_dispatch_plan_all_tasks_have_evidence_required={dispatch_summary.get('all_tasks_have_evidence_required', '')}",
        f"review_quality_benchmark_status={benchmark_report.get('status', '')}",
        f"review_quality_benchmark_sample_count={benchmark_summary.get('sample_count', '')}",
        f"review_quality_benchmark_positive_sample_count={benchmark_summary.get('positive_sample_count', '')}",
        f"review_quality_benchmark_negative_sample_count={benchmark_summary.get('negative_sample_count', '')}",
        f"review_quality_benchmark_expected_conclusions={benchmark_summary.get('curated_expected_conclusion_count', '')}",
        f"review_quality_benchmark_pass_rate={benchmark_summary.get('pass_rate', '')}",
        f"review_quality_benchmark_missed_count={benchmark_summary.get('missed_finding_count', '')}",
        f"review_quality_benchmark_false_positive_count={benchmark_summary.get('false_positive_count', '')}",
        f"review_quality_benchmark_negative_false_positive_count={benchmark_summary.get('negative_blocker_false_positive_count', '')}",
        f"review_quality_benchmark_incremental_verified={benchmark_summary.get('incremental_skip_verified_count', '')}",
        f"review_quality_benchmark_baseline_score={benchmark_summary.get('baseline_aggregate_score', '')}",
        f"review_quality_benchmark_post_absorption_delta={benchmark_summary.get('post_absorption_score_delta', '')}",
        f"review_quality_benchmark_publishable_comment_count={benchmark_summary.get('publishable_comment_count', '')}",
        f"employee_scheduler_stress_status={stress_report.get('status', '')}",
        f"employee_scheduler_stress_round_count={stress_summary.get('round_count', '')}",
        f"employee_scheduler_stress_process_invocation_count={stress_summary.get('process_invocation_count', '')}",
        f"employee_scheduler_stress_queued_task_count={stress_summary.get('queued_task_count', '')}",
        f"employee_scheduler_stress_completed_result_count={stress_summary.get('completed_result_count', '')}",
        f"employee_scheduler_stress_history_result_count={stress_summary.get('history_task_result_count', '')}",
        f"employee_scheduler_stress_missing_result_count={stress_summary.get('missing_result_count', '')}",
        f"employee_scheduler_stress_failed_process_count={stress_summary.get('failed_process_count', '')}",
        f"employee_scheduler_stress_consistent={stress_summary.get('queue_result_history_consistent', '')}",
        f"employee_scheduler_stress_independent_process={stress_summary.get('independent_process_verified', '')}",
    ]


def _external_review_evidence(project: Path) -> list[str]:
    report = project / "docs" / "retort_external_review_report.json"
    if not report.is_file():
        return []
    payload = read_json(report)
    license_review = payload.get("license_review") if isinstance(payload.get("license_review"), dict) else {}
    pipeline = payload.get("review_pipeline") if isinstance(payload.get("review_pipeline"), dict) else {}
    return [
        f"external_review_report={report}",
        f"external_snapshot_revision={(payload.get('external_snapshot') or {}).get('git_revision', '') if isinstance(payload.get('external_snapshot'), dict) else ''}",
        f"absorbed_signals={','.join(str(item) for item in payload.get('absorbed_signals') or [])}",
        f"semantic_gap_count={len((payload.get('semantic_review') or {}).get('gaps') or []) if isinstance(payload.get('semantic_review'), dict) else 0}",
        f"license_review_status={license_review.get('status', '')}; detected={license_review.get('detected_license', '')}; source_copy_allowed={license_review.get('source_code_copy_allowed', '')}; pattern_absorption_allowed={license_review.get('pattern_absorption_allowed', '')}; isolation={license_review.get('isolation_policy', '')}",
        f"component_gap_count={len(pipeline.get('component_gaps') or [])}",
        f"prioritized_absorption_count={len(pipeline.get('prioritized_absorptions') or [])}",
        f"minimum_expected_behavior_tests={(pipeline.get('benchmark') or {}).get('minimum_expected_behavior_tests', '') if isinstance(pipeline.get('benchmark'), dict) else ''}",
    ]


def _employee_result_evidence(project: Path) -> list[str]:
    results = employee_result_files(project)
    if not results:
        return []
    latest = results[-1]
    payload = read_json(latest)
    runtime = payload.get("runtime_evidence") if isinstance(payload.get("runtime_evidence"), dict) else {}
    review = runtime.get("worker_review") if isinstance(runtime.get("worker_review"), dict) else {}
    return [
        f"employee_results_file={latest}",
        f"employee_result_count={len(payload.get('results') or [])}; execution_mode={payload.get('execution_mode', '')}",
        f"employee_runtime_worker_review={review.get('status', '')}; comments={review.get('comment_count', '')}; artifact={review.get('artifact', '')}",
    ]


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}
