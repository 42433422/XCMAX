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
    evidence.append(f"absorption_state_active={state.get('active', '')}")
    evidence.append(f"absorption_state_status={state.get('status', '')}")
    if state.get("external_path"):
        external_path = Path(str(state.get("external_path")))
        evidence.append(f"external_materialized_path={state.get('external_path')}; exists={external_path.is_dir()}")
    if proof.get("verified"):
        evidence.append("closed_loop_five_proofs_verified=True")
    evidence.append(f"absorption_state_closed_loop_completed_by_design={state.get('active') is False and state.get('status') == 'closed_loop_verified' and proof.get('verified') is True}")
    evidence.extend(_latest_run_evidence(project))
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
        "capability_absorption_latest_scope=latest_real_absorption_run",
        "capability_absorption_counting_model=latest_run_counts_separate_from_support_inventory_and_post_merge_hardening",
        f"latest_absorption_behavior_source_file_count={len(audit.get('behavior_source_files') or [])}",
        f"latest_absorption_behavior_test_file_count={len(audit.get('behavior_test_files') or [])}",
        f"behavior_source_file_count={len(audit.get('behavior_source_files') or [])}",
        f"behavior_test_file_count={len(audit.get('behavior_test_files') or [])}",
        f"test_to_source_ratio={audit.get('test_to_source_ratio', '')}",
    ]
    hardening = audit.get("post_absorption_hardening") if isinstance(audit.get("post_absorption_hardening"), dict) else {}
    latest_source_count = len(audit.get("behavior_source_files") or [])
    latest_test_count = len(audit.get("behavior_test_files") or [])
    hardening_source_count = len(hardening.get("behavior_source_files") or [])
    hardening_test_count = len(hardening.get("behavior_test_files") or [])
    evidence.extend(
        [
            "post_absorption_hardening_scope=latest_merge_commit_to_head",
            f"post_absorption_hardening_file_count={hardening.get('file_count', '')}",
            f"post_absorption_hardening_source_count={hardening_source_count}",
            f"post_absorption_hardening_test_count={hardening_test_count}",
            f"total_behavior_source_file_count={latest_source_count + hardening_source_count}",
            f"total_behavior_test_file_count={latest_test_count + hardening_test_count}",
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
            f"employee_worker_pid_isolation_verified={worker_review.get('pid_isolation_verified', False)}",
            f"employee_worker_runtime_boundary_verified={worker_review.get('runtime_boundary_verified', False)}",
            f"employee_worker_unique_process_ids={worker_review.get('unique_process_id_count', '')}",
            f"employee_worker_process_traces={worker_review.get('worker_process_trace_count', '')}",
            f"employee_worker_runtime_boundary_verified_count={worker_review.get('runtime_boundary_verified_count', '')}",
            f"employee_worker_pid_cross_check_count={worker_review.get('pid_cross_check_count', '')}",
            f"employee_worker_crash_isolation_verified={worker_review.get('crash_isolation_verified', False)}",
            f"employee_worker_crash_isolation_verified_count={worker_review.get('crash_isolation_verified_count', '')}",
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
        f"pr_review_absorbed_context_rank_weight_count={pr_review.get('absorbed_context_rank_weight_count')}",
        f"pr_review_absorbed_context_rank_weight_max={pr_review.get('absorbed_context_rank_weight_max')}",
        f"pr_review_calibration_policy_enabled={pr_review.get('calibration_policy_enabled')}",
        f"pr_review_calibration_weighted_context_count={pr_review.get('calibration_weighted_context_count')}",
        f"pr_review_calibration_max_context_weight={pr_review.get('calibration_max_context_weight')}",
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
        f"pr_review_benchmark_cross_project_case_count={pr_review.get('benchmark_cross_project_case_count')}",
        f"pr_review_benchmark_cross_project_family_count={pr_review.get('benchmark_cross_project_family_count')}",
        f"pr_review_benchmark_cross_project_pass_rate={pr_review.get('benchmark_cross_project_pass_rate')}",
        f"review_pipeline_diff_replay_status={pr_review.get('diff_pipeline_status')}",
        f"review_pipeline_diff_replay_depth_score={pr_review.get('diff_pipeline_depth_score')}",
        f"review_pipeline_diff_replay_context_groups={pr_review.get('diff_pipeline_context_group_count')}",
        f"review_pipeline_diff_replay_task_groups={pr_review.get('diff_pipeline_task_group_count')}",
        f"review_pipeline_diff_replay_publishable_comments={pr_review.get('diff_pipeline_publishable_comment_count')}",
        f"review_pipeline_diff_replay_chunk_count={pr_review.get('diff_pipeline_chunk_count')}",
        f"review_pipeline_diff_replay_large_chunking={pr_review.get('diff_pipeline_large_chunking')}",
        f"pr_review_core_large_diff_chunking={pr_review.get('core_large_diff_chunking')}",
        f"pr_review_core_large_diff_chunk_count={pr_review.get('core_large_diff_chunk_count')}",
        f"pr_review_core_large_diff_context_balancing={pr_review.get('core_large_diff_context_balancing')}",
        f"pr_review_employee_feedback_changes_ranking={pr_review.get('employee_feedback_changes_ranking')}",
        f"pr_review_employee_feedback_rank_context={pr_review.get('employee_feedback_rank_context')}",
        f"pr_review_extension_policy_known={pr_review.get('extension_policy_known_count')}",
        f"pr_review_extension_policy_unknown={pr_review.get('extension_policy_unknown_count')}",
        f"pr_review_extension_policy_language_family_count={pr_review.get('extension_policy_language_family_count')}",
        f"pr_review_extension_policy_review_context_count={pr_review.get('extension_policy_review_context_count')}",
        f"pr_review_extension_policy_review_contexts={','.join(pr_review.get('extension_policy_review_contexts') or [])}",
        f"pr_review_extension_policy_language_families={','.join(pr_review.get('extension_policy_language_families') or [])}",
        f"pr_review_extension_policy_source={pr_review.get('extension_policy_source')}",
        f"pr_review_cross_language_transfer_source={pr_review.get('cross_language_transfer_source')}",
        f"pr_review_cross_language_transfer_status={pr_review.get('cross_language_transfer_status')}",
        f"pr_review_cross_language_transfer_findings={pr_review.get('cross_language_transfer_finding_count')}",
        f"pr_review_cross_language_transfer_patterns={pr_review.get('cross_language_transfer_pattern_count')}",
        f"pr_review_cross_language_transfer_families={pr_review.get('cross_language_transfer_family_count')}",
        f"pr_review_cross_language_transfer_core_mapping={pr_review.get('cross_language_transfer_core_mapping')}",
        f"pr_review_cross_language_transfer_comments={pr_review.get('cross_language_transfer_comment_count')}",
        f"pr_review_cross_language_transfer_top_ranked={pr_review.get('cross_language_transfer_top_ranked')}",
        f"pr_review_cross_language_transfer_core_score_active={pr_review.get('cross_language_transfer_core_score_active')}",
        f"pr_review_cross_language_transfer_max_rank_score={pr_review.get('cross_language_transfer_max_rank_score')}",
        f"pr_review_hunk_semantic_status={pr_review.get('hunk_semantic_review_status')}",
        f"pr_review_hunk_semantic_findings={pr_review.get('hunk_semantic_review_finding_count')}",
        f"pr_review_hunk_semantic_types={','.join(pr_review.get('hunk_semantic_review_types') or [])}",
        f"pr_review_hunk_semantic_comments={pr_review.get('hunk_semantic_review_comment_count')}",
        f"pr_review_hunk_semantic_top_ranked={pr_review.get('hunk_semantic_review_top_ranked')}",
        f"pr_review_hunk_semantic_core_score_active={pr_review.get('hunk_semantic_review_core_score_active')}",
        f"pr_review_hunk_semantic_max_rank_score={pr_review.get('hunk_semantic_review_max_rank_score')}",
    ]


def _report_evidence(project: Path) -> list[str]:
    publish_report = read_json(project / "docs" / "retort_pr_publish_dry_run.json")
    publish_summary = publish_report.get("summary") if isinstance(publish_report.get("summary"), dict) else {}
    sandbox_report = read_json(project / "docs" / "retort_pr_publish_sandbox.json")
    sandbox_summary = sandbox_report.get("summary") if isinstance(sandbox_report.get("summary"), dict) else {}
    live_probe = read_json(project / "docs" / "retort_pr_live_publish_probe.json")
    live_summary = live_probe.get("summary") if isinstance(live_probe.get("summary"), dict) else {}
    low_permission_probe = read_json(project / "docs" / "retort_pr_low_permission_probe.json")
    low_permission_summary = low_permission_probe.get("summary") if isinstance(low_permission_probe.get("summary"), dict) else {}
    readonly_probe = read_json(project / "docs" / "retort_pr_readonly_degradation_probe.json")
    readonly_summary = readonly_probe.get("summary") if isinstance(readonly_probe.get("summary"), dict) else {}
    long_run_report = read_json(project / "docs" / "retort_pr_long_run_review.json")
    long_run_summary = long_run_report.get("summary") if isinstance(long_run_report.get("summary"), dict) else {}
    holdout_report = read_json(project / "docs" / "retort_pr_holdout_blind_eval.json")
    holdout_summary = holdout_report.get("summary") if isinstance(holdout_report.get("summary"), dict) else {}
    failure_rollback_report = read_json(project / "docs" / "retort_pr_failure_rollback_replay.json")
    failure_rollback_summary = failure_rollback_report.get("summary") if isinstance(failure_rollback_report.get("summary"), dict) else {}
    replay_report = read_json(project / "docs" / "retort_cross_project_replay.json")
    replay_summary = replay_report.get("summary") if isinstance(replay_report.get("summary"), dict) else {}
    replay_checks = [item for item in replay_report.get("checks") or [] if isinstance(item, dict)]
    multi_absorption_report = read_json(project / "docs" / "retort_multi_project_absorption_replay.json")
    multi_absorption_summary = multi_absorption_report.get("summary") if isinstance(multi_absorption_report.get("summary"), dict) else {}
    continuity_report = read_json(project / "docs" / "retort_absorption_continuity_probe.json")
    continuity_summary = continuity_report.get("summary") if isinstance(continuity_report.get("summary"), dict) else {}
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
    external_matrix = read_json(project / "docs" / "retort_external_advantage_matrix.json")
    external_matrix_summary = external_matrix.get("summary") if isinstance(external_matrix.get("summary"), dict) else {}
    external_ci = read_json(project / "docs" / "retort_external_advantage_ci_regression.json")
    external_ci_summary = external_ci.get("summary") if isinstance(external_ci.get("summary"), dict) else {}
    external_process = read_json(project / "docs" / "retort_external_process_adjudication.json")
    external_process_summary = external_process.get("summary") if isinstance(external_process.get("summary"), dict) else {}
    external_repeat = read_json(project / "docs" / "retort_external_advantage_repeat.json")
    external_repeat_summary = external_repeat.get("summary") if isinstance(external_repeat.get("summary"), dict) else {}
    upstream_pr_ci = read_json(project / "docs" / "retort_upstream_pr_ci_probe.json")
    upstream_pr_ci_summary = upstream_pr_ci.get("summary") if isinstance(upstream_pr_ci.get("summary"), dict) else {}
    competitor_runtime = read_json(project / "docs" / "retort_competitor_runtime_comparison.json")
    competitor_runtime_summary = competitor_runtime.get("summary") if isinstance(competitor_runtime.get("summary"), dict) else {}
    competitor_blind = read_json(project / "docs" / "retort_competitor_blind_adjudication.json")
    competitor_blind_summary = competitor_blind.get("summary") if isinstance(competitor_blind.get("summary"), dict) else {}
    competitor_behavior = read_json(project / "docs" / "retort_competitor_behavior_regression.json")
    competitor_behavior_summary = competitor_behavior.get("summary") if isinstance(competitor_behavior.get("summary"), dict) else {}
    paibi_cli_cross = read_json(project / "docs" / "retort_paibi_cli_cross_adjudication.json")
    paibi_cli_cross_summary = paibi_cli_cross.get("summary") if isinstance(paibi_cli_cross.get("summary"), dict) else {}
    heterogeneous_replay = read_json(project / "docs" / "retort_heterogeneous_absorption_replay.json")
    heterogeneous_summary = heterogeneous_replay.get("summary") if isinstance(heterogeneous_replay.get("summary"), dict) else {}
    cross_domain_replay = read_json(project / "docs" / "retort_cross_domain_absorption_replay.json")
    cross_domain_summary = cross_domain_replay.get("summary") if isinstance(cross_domain_replay.get("summary"), dict) else {}
    cross_domain_e2e = read_json(project / "docs" / "retort_cross_domain_end_to_end.json")
    cross_domain_e2e_summary = cross_domain_e2e.get("summary") if isinstance(cross_domain_e2e.get("summary"), dict) else {}
    cross_domain_ci = read_json(project / "docs" / "retort_cross_domain_ci_regression.json")
    cross_domain_ci_summary = cross_domain_ci.get("summary") if isinstance(cross_domain_ci.get("summary"), dict) else {}
    contract_runtime = read_json(project / "docs" / "retort_contract_runtime_rehearsal.json")
    contract_runtime_summary = contract_runtime.get("summary") if isinstance(contract_runtime.get("summary"), dict) else {}
    contract_stability = read_json(project / "docs" / "retort_contract_stability_stress.json")
    contract_stability_summary = contract_stability.get("summary") if isinstance(contract_stability.get("summary"), dict) else {}
    review_family = read_json(project / "docs" / "retort_review_family_behavior_replay.json")
    review_family_summary = review_family.get("summary") if isinstance(review_family.get("summary"), dict) else {}
    external_merge_landing = read_json(project / "docs" / "retort_external_merge_landing.json")
    external_merge_summary = external_merge_landing.get("summary") if isinstance(external_merge_landing.get("summary"), dict) else {}
    adjudication_report = read_json(project / "docs" / "retort_review_adjudication_calibration.json")
    adjudication_summary = adjudication_report.get("summary") if isinstance(adjudication_report.get("summary"), dict) else {}
    stress_report = read_json(project / "docs" / "retort_employee_scheduler_stress.json")
    stress_summary = stress_report.get("summary") if isinstance(stress_report.get("summary"), dict) else {}
    patch_report = read_json(project / "docs" / "retort_employee_patch_closure.json")
    patch_summary = patch_report.get("summary") if isinstance(patch_report.get("summary"), dict) else {}
    patch_stress = read_json(project / "docs" / "retort_employee_patch_stress.json")
    patch_stress_summary = patch_stress.get("summary") if isinstance(patch_stress.get("summary"), dict) else {}
    quality_report = read_json(project / "docs" / "retort_quality_gate_bundle.json")
    quality_summary = quality_report.get("summary") if isinstance(quality_report.get("summary"), dict) else {}
    recovery_report = read_json(project / "docs" / "retort_production_recovery_drill.json")
    recovery_summary = recovery_report.get("summary") if isinstance(recovery_report.get("summary"), dict) else {}
    mainline_proof = read_json(project / "docs" / "retort_product_mainline_absorption_proof.json")
    mainline_summary = mainline_proof.get("summary") if isinstance(mainline_proof.get("summary"), dict) else {}
    release_decision = read_json(project / "docs" / "retort_absorption_release_decision.json")
    release_summary = release_decision.get("summary") if isinstance(release_decision.get("summary"), dict) else {}
    operator_journey = read_json(project / "docs" / "retort_operator_journey_replay.json")
    operator_summary = operator_journey.get("summary") if isinstance(operator_journey.get("summary"), dict) else {}
    return [
        f"quality_gate_bundle_status={quality_report.get('status', '')}",
        f"quality_gate_bundle_all_passed={quality_summary.get('all_gates_passed', '')}",
        f"quality_gate_bundle_lint={quality_summary.get('lint_passed', '')}",
        f"quality_gate_bundle_pytest={quality_summary.get('pytest_passed', '')}",
        f"quality_gate_bundle_test_density={quality_summary.get('test_density_passed', '')}",
        f"quality_gate_bundle_test_to_source_ratio={quality_summary.get('test_to_source_ratio', '')}",
        f"quality_gate_bundle_test_density_target={quality_summary.get('test_density_target', '')}",
        f"quality_gate_bundle_test_density_target_met={quality_summary.get('test_density_target_met', '')}",
        f"quality_gate_bundle_test_density_missing_lines={quality_summary.get('test_density_missing_lines_to_target', '')}",
        f"quality_gate_bundle_source_lines={quality_summary.get('source_line_count', '')}",
        f"quality_gate_bundle_test_lines={quality_summary.get('test_line_count', '')}",
        f"quality_gate_bundle_contract={quality_summary.get('contract_passed', '')}",
        f"quality_gate_bundle_single_command={quality_summary.get('single_command_surface', '')}",
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
        f"pr_live_publish_probe_permission_denied={live_summary.get('permission_denied', '')}",
        f"pr_live_publish_probe_degraded_without_write={live_summary.get('degraded_without_write', '')}",
        f"pr_live_publish_probe_real_network={(live_probe.get('evidence') or {}).get('real_network', '') if isinstance(live_probe.get('evidence'), dict) else ''}",
        f"pr_live_publish_probe_transport={(live_probe.get('evidence') or {}).get('transport', '') if isinstance(live_probe.get('evidence'), dict) else ''}",
        f"pr_live_publish_probe_required_permission={(live_probe.get('evidence') or {}).get('required_permission', '') if isinstance(live_probe.get('evidence'), dict) else ''}",
        f"pr_live_publish_probe_degradation={(live_probe.get('evidence') or {}).get('degradation', '') if isinstance(live_probe.get('evidence'), dict) else ''}",
        f"pr_low_permission_probe_status={low_permission_probe.get('status', '')}",
        f"pr_low_permission_probe_pr_url={low_permission_probe.get('pr_url', '')}",
        f"pr_low_permission_probe_created_count={low_permission_summary.get('created_comment_count', '')}",
        f"pr_low_permission_probe_rollback_verified={low_permission_summary.get('rollback_verified', '')}",
        f"pr_low_permission_probe_live_write={low_permission_summary.get('live_github_write', '')}",
        f"pr_low_permission_probe_permission_denied={low_permission_summary.get('permission_denied', '')}",
        f"pr_low_permission_probe_degraded_without_write={low_permission_summary.get('degraded_without_write', '')}",
        f"pr_low_permission_probe_real_network={(low_permission_probe.get('evidence') or {}).get('real_network', '') if isinstance(low_permission_probe.get('evidence'), dict) else ''}",
        f"pr_low_permission_probe_transport={(low_permission_probe.get('evidence') or {}).get('transport', '') if isinstance(low_permission_probe.get('evidence'), dict) else ''}",
        f"pr_low_permission_probe_required_permission={(low_permission_probe.get('evidence') or {}).get('required_permission', '') if isinstance(low_permission_probe.get('evidence'), dict) else ''}",
        f"pr_low_permission_probe_degradation={(low_permission_probe.get('evidence') or {}).get('degradation', '') if isinstance(low_permission_probe.get('evidence'), dict) else ''}",
        f"pr_readonly_degradation_probe_status={readonly_probe.get('status', '')}",
        f"pr_readonly_degradation_probe_pr_url={readonly_probe.get('pr_url', '')}",
        f"pr_readonly_degradation_probe_live_write={readonly_summary.get('live_github_write', '')}",
        f"pr_readonly_degradation_probe_degraded_without_write={readonly_summary.get('degraded_without_write', '')}",
        f"pr_readonly_degradation_probe_real_network={(readonly_probe.get('evidence') or {}).get('real_network', '') if isinstance(readonly_probe.get('evidence'), dict) else ''}",
        f"pr_readonly_degradation_probe_transport={(readonly_probe.get('evidence') or {}).get('transport', '') if isinstance(readonly_probe.get('evidence'), dict) else ''}",
        f"pr_readonly_degradation_probe_degradation={(readonly_probe.get('evidence') or {}).get('degradation', '') if isinstance(readonly_probe.get('evidence'), dict) else ''}",
        f"pr_readonly_degradation_probe_artifact_ready={readonly_summary.get('degradation_artifact_ready', '')}",
        f"pr_long_run_review_status={long_run_report.get('status', '')}",
        f"pr_long_run_review_reviewed={long_run_summary.get('reviewed_pr_count', '')}/{long_run_summary.get('target_pr_count', '')}",
        f"pr_long_run_review_distinct_repos={long_run_summary.get('distinct_repo_count', '')}",
        f"pr_long_run_review_distinct_extensions={long_run_summary.get('distinct_extension_count', '')}",
        f"pr_long_run_review_total_comments={long_run_summary.get('total_comment_count', '')}",
        f"pr_long_run_review_total_reviewed_changes={long_run_summary.get('total_reviewed_new_change_count', '')}",
        f"pr_long_run_review_publish_safety_ready={long_run_summary.get('publish_safety_matrix_ready', '')}",
        f"pr_holdout_blind_eval_status={holdout_report.get('status', '')}",
        f"pr_holdout_blind_eval_reviewed={holdout_summary.get('reviewed_pr_count', '')}/{holdout_summary.get('target_pr_count', '')}",
        f"pr_holdout_blind_eval_accepted={holdout_summary.get('accepted_pr_count', '')}/{holdout_summary.get('target_pr_count', '')}",
        f"pr_holdout_blind_eval_distinct_repos={holdout_summary.get('distinct_repo_count', '')}",
        f"pr_holdout_blind_eval_distinct_extensions={holdout_summary.get('distinct_extension_count', '')}",
        f"pr_holdout_blind_eval_total_comments={holdout_summary.get('total_comment_count', '')}",
        f"pr_holdout_blind_eval_total_reviewed_changes={holdout_summary.get('total_reviewed_new_change_count', '')}",
        f"pr_holdout_blind_eval_overlap_prior={holdout_summary.get('overlap_with_prior_long_run_count', '')}",
        f"pr_holdout_blind_eval_blind_prior={holdout_summary.get('blind_against_prior_reports', '')}",
        f"pr_holdout_blind_eval_holdout_labels={holdout_summary.get('holdout_label_count', '')}",
        f"pr_failure_rollback_replay_status={failure_rollback_report.get('status', '')}",
        f"pr_failure_rollback_replay_real_reviewed={failure_rollback_summary.get('real_pr_reviewed_count', '')}/{failure_rollback_summary.get('target_case_count', '')}",
        f"pr_failure_rollback_replay_failed_gates={failure_rollback_summary.get('failed_gate_count', '')}",
        f"pr_failure_rollback_replay_rolled_back={failure_rollback_summary.get('rollback_verified_count', '')}/{failure_rollback_summary.get('target_case_count', '')}",
        f"pr_failure_rollback_replay_distinct_repos={failure_rollback_summary.get('distinct_repo_count', '')}",
        f"pr_failure_rollback_replay_all_rolled_back={failure_rollback_summary.get('all_failures_rolled_back', '')}",
        f"pr_failure_rollback_replay_uses_git_revert={failure_rollback_summary.get('uses_git_revert', '')}",
        f"cross_project_replay_status={replay_report.get('status', '')}",
        f"cross_project_replay_external_project_count={replay_summary.get('external_project_count', '')}",
        f"cross_project_replay_distinct_signal_count={replay_summary.get('distinct_signal_count', '')}",
        f"cross_project_replay_passed_checks={sum(1 for item in replay_checks if item.get('passed'))}/{len(replay_checks)}",
        f"multi_project_absorption_replay_status={multi_absorption_report.get('status', '')}",
        f"multi_project_absorption_replay_ready_count={multi_absorption_summary.get('ready_project_count', '')}",
        f"multi_project_absorption_replay_distinct_sources={multi_absorption_summary.get('distinct_source_count', '')}",
        f"multi_project_absorption_replay_source_family_count={multi_absorption_summary.get('source_family_count', '')}",
        f"multi_project_absorption_replay_source_families={','.join(multi_absorption_summary.get('source_families') or []) if isinstance(multi_absorption_summary.get('source_families'), list) else ''}",
        f"multi_project_absorption_replay_heterogeneous_verified={multi_absorption_summary.get('heterogeneous_absorption_verified', '')}",
        f"multi_project_absorption_replay_historical_source_family_count={multi_absorption_summary.get('historical_source_family_count', '')}",
        f"multi_project_absorption_replay_historical_non_ts_sources={multi_absorption_summary.get('historical_non_ts_source_count', '')}",
        f"multi_project_absorption_replay_historical_architecture_sources={multi_absorption_summary.get('historical_architecture_source_count', '')}",
        f"multi_project_absorption_replay_historical_benchmark_sources={multi_absorption_summary.get('historical_benchmark_source_count', '')}",
        f"multi_project_absorption_replay_historical_security_sources={multi_absorption_summary.get('historical_security_source_count', '')}",
        f"multi_project_absorption_replay_historical_heterogeneous_verified={multi_absorption_summary.get('historical_heterogeneous_absorption_verified', '')}",
        f"multi_project_absorption_replay_all_behavior_diff={multi_absorption_summary.get('all_have_behavior_diff', '')}",
        f"multi_project_absorption_replay_all_employee_results={multi_absorption_summary.get('all_have_employee_results', '')}",
        f"multi_project_absorption_replay_all_code_graph_proof={multi_absorption_summary.get('all_have_per_run_code_graph_proof', '')}",
        f"multi_project_absorption_replay_latest_differs={multi_absorption_summary.get('latest_project_differs_from_previous', '')}",
        f"absorption_continuity_probe_status={continuity_report.get('status', '')}",
        f"absorption_continuity_ready_runs={continuity_summary.get('ready_run_count', '')}/{continuity_summary.get('min_run_count', '')}",
        f"absorption_continuity_distinct_sources={continuity_summary.get('distinct_source_count', '')}",
        f"absorption_continuity_all_behavior_diff={continuity_summary.get('all_have_behavior_diff', '')}",
        f"absorption_continuity_all_behavior_tests={continuity_summary.get('all_have_behavior_tests', '')}",
        f"absorption_continuity_all_employee_results={continuity_summary.get('all_have_employee_results', '')}",
        f"absorption_continuity_all_gates_passed={continuity_summary.get('all_have_gates_passed', '')}",
        f"absorption_continuity_all_code_graph_proof={continuity_summary.get('all_have_per_run_code_graph_proof', '')}",
        f"absorption_continuity_latest_closed_loop={continuity_summary.get('latest_closed_loop_verified', '')}",
        f"absorption_continuity_merge_commit={continuity_summary.get('latest_merge_commit', '')}",
        f"absorption_continuity_counting_model_separated={continuity_summary.get('counting_model_separated', '')}",
        f"complex_pr_replay_status={complex_pr_report.get('status', '')}",
        f"complex_pr_replay_pr_count={complex_pr_summary.get('pr_count', '')}",
        f"complex_pr_replay_reviewed_pr_count={complex_pr_summary.get('reviewed_pr_count', '')}",
        f"complex_pr_replay_complex_pr_count={complex_pr_summary.get('complex_pr_count', '')}",
        f"complex_pr_replay_total_file_count={complex_pr_summary.get('total_file_count', '')}",
        f"complex_pr_replay_total_hunk_count={complex_pr_summary.get('total_hunk_count', '')}",
        f"complex_pr_replay_total_comment_count={complex_pr_summary.get('total_comment_count', '')}",
        f"complex_pr_replay_total_reviewed_change_count={complex_pr_summary.get('total_reviewed_new_change_count', '')}",
        f"complex_pr_replay_truncated_pr_count={complex_pr_summary.get('truncated_pr_count', '')}",
        f"complex_pr_replay_distinct_extension_count={complex_pr_summary.get('distinct_extension_count', '')}",
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
        f"review_quality_benchmark_cross_project_case_count={benchmark_summary.get('cross_project_case_count', '')}",
        f"review_quality_benchmark_cross_project_family_count={benchmark_summary.get('cross_project_family_count', '')}",
        f"review_quality_benchmark_cross_project_pass_rate={benchmark_summary.get('cross_project_pass_rate', '')}",
        f"external_advantage_matrix_status={external_matrix.get('status', '')}",
        f"external_advantage_matrix_ready_cases={external_matrix_summary.get('ready_case_count', '')}/{external_matrix_summary.get('case_count', '')}",
        f"external_advantage_matrix_source_projects={external_matrix_summary.get('source_project_count', '')}",
        f"external_advantage_matrix_absorbed_signals={external_matrix_summary.get('absorbed_signal_count', '')}",
        f"external_advantage_matrix_baseline_score={external_matrix_summary.get('baseline_average_score', '')}",
        f"external_advantage_matrix_retort_score={external_matrix_summary.get('retort_average_score', '')}",
        f"external_advantage_matrix_score_delta={external_matrix_summary.get('score_delta', '')}",
        f"external_advantage_matrix_behavior_delta_count={external_matrix_summary.get('behavior_delta_count', '')}",
        f"external_advantage_matrix_publishable_cases={external_matrix_summary.get('publishable_case_count', '')}",
        f"external_advantage_matrix_extension_policy_cases={external_matrix_summary.get('extension_policy_case_count', '')}",
        f"external_advantage_matrix_per_case_before_after={external_matrix_summary.get('per_case_before_after', '')}",
        f"external_advantage_matrix_all_improved={external_matrix_summary.get('all_advantages_improved', '')}",
        f"external_advantage_matrix_regression_status={external_matrix_summary.get('regression_status', '')}",
        f"external_advantage_matrix_regression_cases={external_matrix_summary.get('passed_regression_case_count', '')}/{external_matrix_summary.get('regression_case_count', '')}",
        f"external_advantage_matrix_direct_regression_cases={external_matrix_summary.get('direct_regression_case_count', '')}/{external_matrix_summary.get('regression_case_count', '')}",
        f"external_advantage_matrix_all_direct_execution={external_matrix_summary.get('all_use_direct_review_execution', '')}",
        f"external_advantage_matrix_all_delta_regressions_verified={external_matrix_summary.get('all_delta_regressions_verified', '')}",
        f"external_advantage_matrix_regression_verifier={(external_matrix.get('evidence') or {}).get('regression_verifier', '') if isinstance(external_matrix.get('evidence'), dict) else ''}",
        f"external_advantage_matrix_regression_runtime={(external_matrix.get('evidence') or {}).get('regression_runtime', '') if isinstance(external_matrix.get('evidence'), dict) else ''}",
        f"external_advantage_matrix_regression_model={(external_matrix.get('evidence') or {}).get('regression_model', '') if isinstance(external_matrix.get('evidence'), dict) else ''}",
        f"external_advantage_matrix_regression_test_module={(external_matrix.get('evidence') or {}).get('regression_test_module', '') if isinstance(external_matrix.get('evidence'), dict) else ''}",
        f"external_advantage_matrix_independent_adjudication={external_matrix_summary.get('independent_adjudication_status', '')}",
        f"external_advantage_matrix_independent_accepted={external_matrix_summary.get('independent_accepted_case_count', '')}/{external_matrix_summary.get('independent_adjudicated_case_count', '')}",
        f"external_advantage_matrix_independent_min_delta={external_matrix_summary.get('independent_minimum_recomputed_delta', '')}",
        f"external_advantage_matrix_independent_all_accepted={external_matrix_summary.get('independent_all_cases_accepted', '')}",
        f"external_advantage_matrix_independent_adjudicator={(external_matrix.get('evidence') or {}).get('independent_adjudicator', '') if isinstance(external_matrix.get('evidence'), dict) else ''}",
        f"external_advantage_matrix_blind_third_party_status={external_matrix_summary.get('blind_third_party_status', '')}",
        f"external_advantage_matrix_blind_third_party_accepted={external_matrix_summary.get('blind_third_party_accepted_case_count', '')}/{external_matrix_summary.get('blind_third_party_adjudicated_case_count', '')}",
        f"external_advantage_matrix_blind_third_party_min_delta={external_matrix_summary.get('blind_third_party_minimum_delta', '')}",
        f"external_advantage_matrix_blind_third_party_delta_floor={external_matrix_summary.get('blind_third_party_delta_floor_passed', '')}",
        f"external_advantage_matrix_blind_third_party_score_fields_consumed={external_matrix_summary.get('blind_third_party_score_fields_consumed', '')}",
        f"external_advantage_matrix_blind_third_party_adjudicator={(external_matrix.get('evidence') or {}).get('blind_third_party_adjudicator', '') if isinstance(external_matrix.get('evidence'), dict) else ''}",
        f"external_advantage_matrix_blind_third_party_boundary={(external_matrix.get('evidence') or {}).get('blind_third_party_boundary', '') if isinstance(external_matrix.get('evidence'), dict) else ''}",
        f"external_advantage_ci_regression_status={external_ci.get('status', '')}",
        f"external_advantage_ci_regression_cases={external_ci_summary.get('passed_case_count', '')}/{external_ci_summary.get('case_count', '')}",
        f"external_advantage_ci_regression_source_projects={external_ci_summary.get('source_project_count', '')}",
        f"external_advantage_ci_regression_matrix_status={external_ci_summary.get('matrix_status', '')}",
        f"external_advantage_ci_regression_min_blind_delta={external_ci_summary.get('blind_third_party_minimum_delta', '')}",
        f"external_advantage_ci_regression_delta_floor={external_ci_summary.get('blind_delta_floor', '')}",
        f"external_advantage_ci_regression_delta_floor_met={external_ci_summary.get('blind_delta_floor_met', '')}",
        f"external_advantage_ci_regression_all_direct_review={external_ci_summary.get('all_direct_review_regressions_verified', '')}",
        f"external_advantage_ci_regression_all_ci_acceptance={external_ci_summary.get('all_cases_have_ci_acceptance', '')}",
        f"external_advantage_ci_regression_ci_gate={(external_ci.get('evidence') or {}).get('ci_gate', '') if isinstance(external_ci.get('evidence'), dict) else ''}",
        f"external_process_adjudication_status={external_process.get('status', '')}",
        f"external_process_adjudication_cases={external_process_summary.get('external_accepted_case_count', '')}/{external_process_summary.get('external_adjudicated_case_count', '')}",
        f"external_process_adjudication_min_delta={external_process_summary.get('external_minimum_delta', '')}",
        f"external_process_adjudication_imports_retort={external_process_summary.get('script_imports_retort_engine', '')}",
        f"external_process_adjudication_score_fields_consumed={external_process_summary.get('score_fields_consumed', '')}",
        f"external_process_adjudication_input_sha={external_process_summary.get('input_sha256', '')}",
        f"external_process_adjudication_output_sha={external_process_summary.get('output_sha256', '')}",
        f"external_process_adjudication_boundary={(external_process.get('evidence') or {}).get('boundary', '') if isinstance(external_process.get('evidence'), dict) else ''}",
        f"external_advantage_repeat_status={external_repeat.get('status', '')}",
        f"external_advantage_repeat_ready={external_repeat_summary.get('ready_repeat_count', '')}/{external_repeat_summary.get('repeat_count', '')}",
        f"external_advantage_repeat_total_case_evaluations={external_repeat_summary.get('total_case_evaluation_count', '')}",
        f"external_advantage_repeat_stable_case_set={external_repeat_summary.get('stable_case_set', '')}",
        f"external_advantage_repeat_stable_score_delta={external_repeat_summary.get('stable_score_delta', '')}",
        f"external_advantage_repeat_minimum_score_delta={external_repeat_summary.get('minimum_score_delta', '')}",
        f"upstream_pr_ci_probe_status={upstream_pr_ci.get('status', '')}",
        f"upstream_pr_ci_probe_repo={upstream_pr_ci_summary.get('repo', '')}",
        f"upstream_pr_ci_probe_pr={upstream_pr_ci_summary.get('pr_number', '')}",
        f"upstream_pr_ci_probe_merged={upstream_pr_ci_summary.get('merged', '')}",
        f"upstream_pr_ci_probe_merge_commit={upstream_pr_ci_summary.get('merge_commit_sha', '')}",
        f"upstream_pr_ci_probe_checks={upstream_pr_ci_summary.get('successful_check_run_count', '')}/{upstream_pr_ci_summary.get('check_run_count', '')}",
        f"upstream_pr_ci_probe_all_successful={upstream_pr_ci_summary.get('all_check_runs_successful', '')}",
        f"upstream_pr_ci_probe_targets={upstream_pr_ci_summary.get('ready_target_count', '')}/{upstream_pr_ci_summary.get('target_count', '')}",
        f"upstream_pr_ci_probe_distinct_repos={upstream_pr_ci_summary.get('distinct_repo_count', '')}",
        f"upstream_pr_ci_probe_total_checks={upstream_pr_ci_summary.get('total_successful_check_run_count', '')}/{upstream_pr_ci_summary.get('total_check_run_count', '')}",
        f"upstream_pr_ci_probe_all_targets_successful={upstream_pr_ci_summary.get('all_target_check_runs_successful', '')}",
        f"upstream_pr_ci_probe_multi_repo_generalization={upstream_pr_ci_summary.get('multi_repo_ci_generalization', '')}",
        f"upstream_pr_ci_probe_real_remote_api={upstream_pr_ci_summary.get('real_remote_api', '')}",
        f"competitor_runtime_comparison_status={competitor_runtime.get('status', '')}",
        f"competitor_runtime_comparison_project={competitor_runtime_summary.get('competitor_project', '')}",
        f"competitor_runtime_comparison_projects={','.join(competitor_runtime_summary.get('competitor_projects') or []) if isinstance(competitor_runtime_summary.get('competitor_projects'), list) else ''}",
        f"competitor_runtime_comparison_project_count={competitor_runtime_summary.get('competitor_project_count', '')}",
        f"competitor_runtime_comparison_ready_projects={competitor_runtime_summary.get('ready_competitor_project_count', '')}",
        f"competitor_runtime_comparison_real_cached_projects={competitor_runtime_summary.get('real_cached_project_count', '')}",
        f"competitor_runtime_comparison_external_processes={competitor_runtime_summary.get('external_process_success_count', '')}/{competitor_runtime_summary.get('external_process_count', '')}",
        f"competitor_runtime_comparison_all_external_successful={competitor_runtime_summary.get('all_external_processes_successful', '')}",
        f"competitor_runtime_comparison_multi_side_by_side={competitor_runtime_summary.get('multi_competitor_side_by_side', '')}",
        f"competitor_runtime_comparison_live_upstream_requested={competitor_runtime_summary.get('live_upstream_requested', '')}",
        f"competitor_runtime_comparison_live_upstream_verified={competitor_runtime_summary.get('live_upstream_verified_count', '')}/{competitor_runtime_summary.get('live_upstream_probe_count', '')}",
        f"competitor_runtime_comparison_all_live_upstream_verified={competitor_runtime_summary.get('all_live_upstream_sources_verified', '')}",
        f"competitor_runtime_comparison_live_upstream_materialized={competitor_runtime_summary.get('live_upstream_materialized_count', '')}/{competitor_runtime_summary.get('live_upstream_probe_count', '')}",
        f"competitor_runtime_comparison_all_live_upstream_materialized={competitor_runtime_summary.get('all_live_upstream_sources_materialized', '')}",
        f"competitor_runtime_comparison_source_exists={competitor_runtime_summary.get('competitor_source_exists', '')}",
        f"competitor_runtime_comparison_source_sha={competitor_runtime_summary.get('competitor_source_sha256', '')}",
        f"competitor_runtime_comparison_hunks={competitor_runtime_summary.get('competitor_hunk_count', '')}",
        f"competitor_runtime_comparison_retort_comments={competitor_runtime_summary.get('retort_comment_count', '')}",
        f"competitor_runtime_comparison_side_by_side={competitor_runtime_summary.get('side_by_side_output_materialized', '')}",
        f"competitor_runtime_comparison_retort_exceeds_all={competitor_runtime_summary.get('retort_exceeds_all_competitors_by_semantic_comments', '')}",
        f"competitor_runtime_comparison_boundary={(competitor_runtime.get('evidence') or {}).get('competitor_boundary', '') if isinstance(competitor_runtime.get('evidence'), dict) else ''}",
        f"competitor_blind_adjudication_status={competitor_blind.get('status', '')}",
        f"competitor_blind_adjudication_accepted={competitor_blind_summary.get('accepted_competitor_count', '')}/{competitor_blind_summary.get('competitor_count', '')}",
        f"competitor_blind_adjudication_min_delta={competitor_blind_summary.get('minimum_blind_delta', '')}",
        f"competitor_blind_adjudication_imports_retort={competitor_blind_summary.get('script_imports_retort_engine', '')}",
        f"competitor_blind_adjudication_input_score_fields={competitor_blind_summary.get('input_contains_score_fields', '')}",
        f"competitor_blind_adjudication_input_sha={competitor_blind_summary.get('input_sha256', '')}",
        f"competitor_blind_adjudication_output_sha={competitor_blind_summary.get('output_sha256', '')}",
        f"competitor_blind_adjudication_human_reviewed={(competitor_blind.get('evidence') or {}).get('human_reviewed', '') if isinstance(competitor_blind.get('evidence'), dict) else ''}",
        f"competitor_behavior_regression_status={competitor_behavior.get('status', '')}",
        f"competitor_behavior_regression_ready_cases={competitor_behavior_summary.get('ready_case_count', '')}/{competitor_behavior_summary.get('case_count', '')}",
        f"competitor_behavior_regression_source_projects={competitor_behavior_summary.get('source_project_count', '')}",
        f"competitor_behavior_regression_direct_review={competitor_behavior_summary.get('all_cases_direct_review_execution', '')}",
        f"competitor_behavior_regression_all_signals={competitor_behavior_summary.get('all_competitor_signals_regressed', '')}",
        f"competitor_behavior_regression_assertions={competitor_behavior_summary.get('behavior_assertion_count', '')}",
        f"competitor_behavior_regression_runtime={(competitor_behavior.get('evidence') or {}).get('runtime', '') if isinstance(competitor_behavior.get('evidence'), dict) else ''}",
        f"paibi_cli_cross_adjudication_status={paibi_cli_cross.get('status', '')}",
        f"paibi_cli_cross_adjudication_tools={paibi_cli_cross_summary.get('accepted_tool_count', '')}/{paibi_cli_cross_summary.get('tool_count', '')}",
        f"paibi_cli_cross_adjudication_tool_identities={','.join(paibi_cli_cross_summary.get('tool_identities') or []) if isinstance(paibi_cli_cross_summary.get('tool_identities'), list) else ''}",
        f"paibi_cli_cross_adjudication_all_accepted={paibi_cli_cross_summary.get('all_tools_accepted', '')}",
        f"paibi_cli_cross_adjudication_consensus={paibi_cli_cross_summary.get('cross_tool_consensus', '')}",
        f"paibi_cli_cross_adjudication_input_score_fields={paibi_cli_cross_summary.get('input_contains_score_fields', '')}",
        f"paibi_cli_cross_adjudication_imports_retort={paibi_cli_cross_summary.get('script_imports_retort_engine', '')}",
        f"paibi_cli_cross_adjudication_human_reviewed={paibi_cli_cross_summary.get('human_reviewed', '')}",
        f"paibi_cli_cross_adjudication_human_calibrated={paibi_cli_cross_summary.get('human_calibrated_cli_consensus', '')}",
        f"paibi_cli_cross_adjudication_calibration_labels={paibi_cli_cross_summary.get('calibration_human_label_count', '')}",
        f"paibi_cli_cross_adjudication_calibration_pass_rate={paibi_cli_cross_summary.get('calibration_pass_rate', '')}",
        f"paibi_cli_cross_adjudication_calibration_false_positive={paibi_cli_cross_summary.get('calibration_false_positive_count', '')}",
        f"paibi_cli_cross_adjudication_calibration_false_negative={paibi_cli_cross_summary.get('calibration_false_negative_count', '')}",
        f"paibi_cli_cross_adjudication_replaces_human_labels={paibi_cli_cross_summary.get('replaces_human_labels', '')}",
        f"paibi_cli_cross_adjudication_boundary={(paibi_cli_cross.get('evidence') or {}).get('boundary', '') if isinstance(paibi_cli_cross.get('evidence'), dict) else ''}",
        f"heterogeneous_absorption_replay_status={heterogeneous_replay.get('status', '')}",
        f"heterogeneous_absorption_replay_ready_cases={heterogeneous_summary.get('ready_case_count', '')}/{heterogeneous_summary.get('case_count', '')}",
        f"heterogeneous_absorption_replay_cached_sources={heterogeneous_summary.get('cached_source_count', '')}",
        f"heterogeneous_absorption_replay_language_families={heterogeneous_summary.get('language_family_count', '')}",
        f"heterogeneous_absorption_replay_language_family_list={','.join(heterogeneous_summary.get('language_families') or []) if isinstance(heterogeneous_summary.get('language_families'), list) else ''}",
        f"heterogeneous_absorption_replay_source_families={heterogeneous_summary.get('source_family_count', '')}",
        f"heterogeneous_absorption_replay_before_failures={heterogeneous_summary.get('pre_absorption_failure_count', '')}",
        f"heterogeneous_absorption_replay_after_passes={heterogeneous_summary.get('post_absorption_pass_count', '')}",
        f"heterogeneous_absorption_replay_before_after={heterogeneous_summary.get('all_before_failed_after_passed', '')}",
        f"heterogeneous_absorption_replay_min_delta={heterogeneous_summary.get('minimum_behavior_delta', '')}",
        f"heterogeneous_absorption_replay_average_delta={heterogeneous_summary.get('average_behavior_delta', '')}",
        f"heterogeneous_absorption_replay_independent_adjudication={heterogeneous_summary.get('independent_adjudication_status', '')}",
        f"heterogeneous_absorption_replay_independent_accepted={heterogeneous_summary.get('independent_accepted_case_count', '')}/{heterogeneous_summary.get('independent_adjudicated_case_count', '')}",
        f"heterogeneous_absorption_replay_all_independent_accepted={heterogeneous_summary.get('independent_all_cases_accepted', '')}",
        f"heterogeneous_absorption_replay_cross_language_verified={heterogeneous_summary.get('cross_language_absorption_verified', '')}",
        f"heterogeneous_absorption_replay_adjudicator={(heterogeneous_replay.get('evidence') or {}).get('adjudicator', '') if isinstance(heterogeneous_replay.get('evidence'), dict) else ''}",
        f"cross_domain_absorption_replay_status={cross_domain_replay.get('status', '')}",
        f"cross_domain_absorption_replay_ready_cases={cross_domain_summary.get('ready_case_count', '')}/{cross_domain_summary.get('case_count', '')}",
        f"cross_domain_absorption_replay_non_pr_domains={cross_domain_summary.get('non_pr_domain_count', '')}",
        f"cross_domain_absorption_replay_domain_list={','.join(cross_domain_summary.get('non_pr_domains') or []) if isinstance(cross_domain_summary.get('non_pr_domains'), list) else ''}",
        f"cross_domain_absorption_replay_direct_modules={cross_domain_summary.get('direct_module_count', '')}",
        f"cross_domain_absorption_replay_direct_module_list={','.join(cross_domain_summary.get('direct_modules') or []) if isinstance(cross_domain_summary.get('direct_modules'), list) else ''}",
        f"cross_domain_absorption_replay_before_after={cross_domain_summary.get('all_before_failed_after_passed', '')}",
        f"cross_domain_absorption_replay_direct_execution={cross_domain_summary.get('all_direct_modules_executed', '')}",
        f"cross_domain_absorption_replay_output_assertions={cross_domain_summary.get('all_output_assertions_passed', '')}",
        f"cross_domain_absorption_replay_independent_accepted={cross_domain_summary.get('independent_accepted_case_count', '')}/{cross_domain_summary.get('case_count', '')}",
        f"cross_domain_absorption_replay_claim_boundary={(cross_domain_replay.get('evidence') or {}).get('claim_boundary', '') if isinstance(cross_domain_replay.get('evidence'), dict) else ''}",
        f"cross_domain_end_to_end_status={cross_domain_e2e.get('status', '')}",
        f"cross_domain_end_to_end_stages={cross_domain_e2e_summary.get('linked_stage_count', '')}",
        f"cross_domain_end_to_end_domains={cross_domain_e2e_summary.get('linked_domain_count', '')}",
        f"cross_domain_end_to_end_direct_modules={cross_domain_e2e_summary.get('linked_direct_module_count', '')}",
        f"cross_domain_end_to_end_integrated_review={cross_domain_e2e_summary.get('integrated_review_status', '')}",
        f"cross_domain_end_to_end_comments={cross_domain_e2e_summary.get('integrated_review_comment_count', '')}",
        f"cross_domain_end_to_end_task_groups={cross_domain_e2e_summary.get('integrated_review_task_group_count', '')}",
        f"cross_domain_end_to_end_all_stages_chained={cross_domain_e2e_summary.get('all_stages_chained', '')}",
        f"cross_domain_end_to_end_all_outputs_consumed={cross_domain_e2e_summary.get('all_stage_outputs_consumed', '')}",
        f"cross_domain_end_to_end_assertions={cross_domain_e2e_summary.get('output_assertions_passed', '')}",
        f"cross_domain_end_to_end_runtime={(cross_domain_e2e.get('evidence') or {}).get('integrated_runtime', '') if isinstance(cross_domain_e2e.get('evidence'), dict) else ''}",
        f"cross_domain_ci_regression_status={cross_domain_ci.get('status', '')}",
        f"cross_domain_ci_regression_rounds={cross_domain_ci_summary.get('ready_round_count', '')}/{cross_domain_ci_summary.get('round_count', '')}",
        f"cross_domain_ci_regression_min_domains={cross_domain_ci_summary.get('minimum_linked_domain_count', '')}",
        f"cross_domain_ci_regression_total_domains={cross_domain_ci_summary.get('total_domain_replay_count', '')}",
        f"cross_domain_ci_regression_stable_domains={cross_domain_ci_summary.get('stable_domain_count', '')}",
        f"cross_domain_ci_regression_all_assertions={cross_domain_ci_summary.get('all_output_assertions_passed', '')}",
        f"cross_domain_ci_regression_ci_command={cross_domain_ci_summary.get('ci_command', '')}",
        f"contract_runtime_rehearsal_status={contract_runtime.get('status', '')}",
        f"contract_runtime_rehearsal_ready_cases={contract_runtime_summary.get('ready_case_count', '')}/{contract_runtime_summary.get('case_count', '')}",
        f"contract_runtime_rehearsal_violations_rejected={contract_runtime_summary.get('violation_rejected_count', '')}",
        f"contract_runtime_rehearsal_rollbacks={contract_runtime_summary.get('rollback_verified_count', '')}",
        f"contract_runtime_rehearsal_all_rejected={contract_runtime_summary.get('all_violations_rejected', '')}",
        f"contract_runtime_rehearsal_all_rollbacks={contract_runtime_summary.get('all_rollbacks_verified', '')}",
        f"contract_runtime_rehearsal_valid_payloads={contract_runtime_summary.get('valid_payload_accepted_count', '')}",
        f"contract_runtime_rehearsal_concurrent_workers={contract_runtime_summary.get('concurrent_worker_count', '')}",
        f"contract_runtime_rehearsal_concurrency_faults={contract_runtime_summary.get('concurrency_fault_injection_count', '')}",
        f"contract_runtime_rehearsal_concurrent_rejected={contract_runtime_summary.get('concurrent_violation_rejected_count', '')}",
        f"contract_runtime_rehearsal_concurrent_rollbacks={contract_runtime_summary.get('concurrent_rollback_verified_count', '')}",
        f"contract_runtime_rehearsal_all_concurrent_rejected={contract_runtime_summary.get('all_concurrent_violations_rejected', '')}",
        f"contract_runtime_rehearsal_all_concurrent_rollbacks={contract_runtime_summary.get('all_concurrent_rollbacks_verified', '')}",
        f"contract_runtime_rehearsal_fault_model={(contract_runtime.get('evidence') or {}).get('fault_injection_model', '') if isinstance(contract_runtime.get('evidence'), dict) else ''}",
        f"contract_runtime_rehearsal_guard={(contract_runtime.get('evidence') or {}).get('runtime_guard', '') if isinstance(contract_runtime.get('evidence'), dict) else ''}",
        f"contract_stability_stress_status={contract_stability.get('status', '')}",
        f"contract_stability_stress_rounds={contract_stability_summary.get('ready_round_count', '')}/{contract_stability_summary.get('round_count', '')}",
        f"contract_stability_stress_workers={contract_stability_summary.get('concurrent_worker_count', '')}",
        f"contract_stability_stress_floor_exceeded={contract_stability_summary.get('concurrency_floor_exceeded', '')}",
        f"contract_stability_stress_faults={contract_stability_summary.get('total_fault_injection_count', '')}",
        f"contract_stability_stress_rejected={contract_stability_summary.get('total_concurrent_violation_rejected_count', '')}",
        f"contract_stability_stress_rollbacks={contract_stability_summary.get('total_concurrent_rollback_verified_count', '')}",
        f"contract_stability_stress_state_leaks={contract_stability_summary.get('state_leak_count', '')}",
        f"contract_stability_stress_acceptance={(contract_stability.get('evidence') or {}).get('acceptance', '') if isinstance(contract_stability.get('evidence'), dict) else ''}",
        f"employee_patch_stress_status={patch_stress.get('status', '')}",
        f"employee_patch_stress_workers={patch_stress_summary.get('ready_worker_count', '')}/{patch_stress_summary.get('worker_count', '')}",
        f"employee_patch_stress_concurrent_workers={patch_stress_summary.get('concurrent_worker_count', '')}",
        f"employee_patch_stress_floor_exceeded={patch_stress_summary.get('concurrency_floor_exceeded', '')}",
        f"employee_patch_stress_failed_gates={patch_stress_summary.get('failed_gate_count', '')}",
        f"employee_patch_stress_rollbacks={patch_stress_summary.get('rollback_verified_count', '')}",
        f"employee_patch_stress_post_rollback_gates={patch_stress_summary.get('post_rollback_gate_passed_count', '')}",
        f"employee_patch_stress_state_leaks={patch_stress_summary.get('state_leak_count', '')}",
        f"employee_patch_stress_all_rollbacks={patch_stress_summary.get('all_rollbacks_verified', '')}",
        f"employee_patch_stress_acceptance={(patch_stress.get('evidence') or {}).get('acceptance', '') if isinstance(patch_stress.get('evidence'), dict) else ''}",
        f"review_family_behavior_replay_status={review_family.get('status', '')}",
        f"review_family_behavior_replay_ready_cases={review_family_summary.get('ready_case_count', '')}/{review_family_summary.get('case_count', '')}",
        f"review_family_behavior_replay_language_families={','.join(review_family_summary.get('language_families') or []) if isinstance(review_family_summary.get('language_families'), list) else ''}",
        f"review_family_behavior_replay_typescript_cases={review_family_summary.get('typescript_case_count', '')}",
        f"review_family_behavior_replay_python_cases={review_family_summary.get('python_case_count', '')}",
        f"review_family_behavior_replay_direct_outputs={review_family_summary.get('all_direct_review_outputs_verified', '')}",
        f"review_family_behavior_replay_publishable_cases={review_family_summary.get('publishable_case_count', '')}",
        f"review_family_behavior_replay_independent_accepted={review_family_summary.get('independent_accepted_case_count', '')}/{review_family_summary.get('case_count', '')}",
        f"review_family_behavior_replay_runtime={(review_family.get('evidence') or {}).get('direct_runtime', '') if isinstance(review_family.get('evidence'), dict) else ''}",
        f"external_merge_landing_status={external_merge_landing.get('status', '')}",
        f"external_merge_landing_ready_cases={external_merge_summary.get('ready_case_count', '')}/{external_merge_summary.get('case_count', '')}",
        f"external_merge_landing_branch_diffs={external_merge_summary.get('branch_diff_count', '')}",
        f"external_merge_landing_merge_commits={external_merge_summary.get('merge_commit_count', '')}",
        f"external_merge_landing_post_merge_tests={external_merge_summary.get('post_merge_test_passed_count', '')}",
        f"external_merge_landing_all_passed={external_merge_summary.get('all_branch_diff_merge_tests_passed', '')}",
        f"external_merge_landing_source_families={','.join(external_merge_summary.get('source_families') or []) if isinstance(external_merge_summary.get('source_families'), list) else ''}",
        f"external_merge_landing_verifier={(external_merge_landing.get('evidence') or {}).get('verifier', '') if isinstance(external_merge_landing.get('evidence'), dict) else ''}",
        f"review_adjudication_calibration_status={adjudication_report.get('status', '')}",
        f"review_adjudication_human_label_count={adjudication_summary.get('human_label_count', '')}",
        f"review_adjudication_pass_rate={adjudication_summary.get('pass_rate', '')}",
        f"review_adjudication_pre_calibration_pass_rate={adjudication_summary.get('pre_calibration_pass_rate', '')}",
        f"review_adjudication_post_calibration_pass_rate={adjudication_summary.get('post_calibration_pass_rate', '')}",
        f"review_adjudication_improvement_delta={adjudication_summary.get('calibration_improvement_delta', '')}",
        f"review_adjudication_false_positive_count={adjudication_summary.get('false_positive_count', '')}",
        f"review_adjudication_false_negative_count={adjudication_summary.get('false_negative_count', '')}",
        f"review_adjudication_pre_false_positive_count={adjudication_summary.get('pre_calibration_false_positive_count', '')}",
        f"review_adjudication_pre_false_negative_count={adjudication_summary.get('pre_calibration_false_negative_count', '')}",
        f"review_adjudication_false_positive_reduction={adjudication_summary.get('false_positive_reduction', '')}",
        f"review_adjudication_false_negative_reduction={adjudication_summary.get('false_negative_reduction', '')}",
        f"review_adjudication_feedback_recalibration_applied={adjudication_summary.get('feedback_recalibration_applied', '')}",
        f"review_adjudication_context_count={adjudication_summary.get('context_count', '')}",
        f"employee_scheduler_stress_status={stress_report.get('status', '')}",
        f"employee_scheduler_stress_round_count={stress_summary.get('round_count', '')}",
        f"employee_scheduler_stress_workers_per_round={stress_summary.get('workers_per_round', '')}",
        f"employee_scheduler_stress_process_invocation_count={stress_summary.get('process_invocation_count', '')}",
        f"employee_scheduler_stress_unique_process_ids={stress_summary.get('unique_process_id_count', '')}",
        f"employee_scheduler_stress_successful_process_ids={stress_summary.get('unique_successful_process_id_count', '')}",
        f"employee_scheduler_stress_pid_isolation_verified={stress_summary.get('pid_isolation_verified', '')}",
        f"employee_scheduler_stress_queued_task_count={stress_summary.get('queued_task_count', '')}",
        f"employee_scheduler_stress_completed_result_count={stress_summary.get('completed_result_count', '')}",
        f"employee_scheduler_stress_history_result_count={stress_summary.get('history_task_result_count', '')}",
        f"employee_scheduler_stress_missing_result_count={stress_summary.get('missing_result_count', '')}",
        f"employee_scheduler_stress_failed_process_count={stress_summary.get('failed_process_count', '')}",
        f"employee_scheduler_stress_consistent={stress_summary.get('queue_result_history_consistent', '')}",
        f"employee_scheduler_stress_independent_process={stress_summary.get('independent_process_verified', '')}",
        f"employee_scheduler_stress_concurrent_workers_verified={stress_summary.get('concurrent_workers_verified', '')}",
        f"employee_patch_closure_status={patch_report.get('status', '')}",
        f"employee_patch_closure_case_count={patch_summary.get('case_count', '')}",
        f"employee_patch_closure_patch_generated_count={patch_summary.get('patch_generated_count', '')}",
        f"employee_patch_closure_patch_applied_count={patch_summary.get('patch_applied_count', '')}",
        f"employee_patch_closure_gate_passed_count={patch_summary.get('gate_passed_count', '')}",
        f"employee_patch_closure_gate_expected_to_pass={patch_summary.get('gate_expected_to_pass_passed_count', '')}/{patch_summary.get('gate_expected_to_pass_count', '')}",
        f"employee_patch_closure_rollback_verified_count={patch_summary.get('rollback_verified_count', '')}",
        f"employee_patch_closure_primary_rollback_verified_count={patch_summary.get('primary_rollback_verified_count', '')}",
        f"employee_patch_closure_rollback_scope={patch_summary.get('rollback_scope', '')}",
        f"employee_patch_closure_failure_rehearsal_count={patch_summary.get('failure_rehearsal_count', '')}",
        f"employee_patch_closure_failure_rehearsal_rollback_count={patch_summary.get('failure_rehearsal_rollback_count', '')}",
        f"employee_patch_closure_full_path_rollback_verified={patch_summary.get('full_path_rollback_verified', '')}",
        f"employee_patch_closure_all_cases_have_failure_rollback_rehearsal={patch_summary.get('all_cases_have_failure_rollback_rehearsal', '')}",
        f"employee_patch_closure_expected_failure_count={patch_summary.get('expected_failure_case_count', '')}",
        f"employee_patch_closure_expected_failure_rollback_count={patch_summary.get('expected_failure_rollback_count', '')}",
        f"employee_patch_closure_unexpected_gate_failure_count={patch_summary.get('unexpected_gate_failure_count', '')}",
        f"employee_patch_closure_success_case_verified={patch_summary.get('success_case_verified', '')}",
        f"employee_patch_closure_existing_file_update_verified={patch_summary.get('existing_file_update_verified', '')}",
        f"employee_patch_closure_failure_case_rolled_back={patch_summary.get('failure_case_rolled_back', '')}",
        f"employee_patch_closure_multi_file_case_verified={patch_summary.get('multi_file_case_verified', '')}",
        f"employee_patch_closure_policy_state_case_verified={patch_summary.get('policy_state_case_verified', '')}",
        f"employee_patch_closure_multi_file_changed_file_count={patch_summary.get('multi_file_changed_file_count', '')}",
        f"employee_patch_closure_secondary_review_status={patch_summary.get('secondary_review_status', '')}",
        f"employee_patch_closure_successful_repairs_re_reviewed={patch_summary.get('successful_repairs_re_reviewed', '')}",
        f"employee_patch_closure_retry_case_verified={patch_summary.get('retry_case_verified', '')}",
        f"employee_patch_closure_retry_first_failure_rolled_back={patch_summary.get('retry_first_failure_rolled_back', '')}",
        f"employee_patch_closure_retry_second_patch_passed={patch_summary.get('retry_second_patch_passed', '')}",
        f"employee_patch_closure_all_expected_outcomes_verified={patch_summary.get('all_expected_outcomes_verified', '')}",
        f"production_recovery_drill_status={recovery_report.get('status', '')}",
        f"production_recovery_drill_recovered={recovery_summary.get('recovered_count', '')}/{recovery_summary.get('scenario_count', '')}",
        f"production_recovery_drill_all_recovered={recovery_summary.get('all_recovered', '')}",
        f"production_recovery_drill_real_network_denial={recovery_summary.get('real_network_denial_verified', '')}",
        f"production_recovery_drill_live_write_rollback={recovery_summary.get('live_write_rollback_verified', '')}",
        f"production_recovery_drill_rollback_scenarios={recovery_summary.get('rollback_scenario_count', '')}",
        f"production_recovery_drill_degradation_scenarios={recovery_summary.get('degradation_scenario_count', '')}",
        f"product_mainline_absorption_status={mainline_proof.get('status', '')}",
        f"product_mainline_absorption_merge_commit={mainline_summary.get('is_merge_commit', '')}",
        f"product_mainline_absorption_sources={mainline_summary.get('behavior_source_changed_count', '')}",
        f"product_mainline_absorption_tests={mainline_summary.get('behavior_test_changed_count', '')}",
        f"product_mainline_absorption_quality={mainline_summary.get('post_merge_quality_gate_passed', '')}",
        f"product_mainline_absorption_commit={mainline_summary.get('commit', '')}",
        f"operator_journey_replay_status={operator_journey.get('status', '')}",
        f"operator_journey_replay_ready_stages={operator_summary.get('ready_stage_count', '')}/{operator_summary.get('stage_count', '')}",
        f"operator_journey_replay_hashed_artifacts={operator_summary.get('hashed_artifact_count', '')}",
        f"operator_journey_replay_real_absorption_run_present={operator_summary.get('real_absorption_run_present', '')}",
        f"operator_journey_replay_gates_passed={operator_summary.get('real_absorption_gates_passed', '')}",
        f"operator_journey_replay_per_run_code_graph={operator_summary.get('per_run_code_graph_proved', '')}",
        f"operator_journey_replay_product_mainline_ready={operator_summary.get('product_mainline_absorption_ready', '')}",
        f"operator_journey_replay_cross_domain_ready={operator_summary.get('cross_domain_live_probe_ready', '')}",
        f"operator_journey_replay_frontend_ready={operator_summary.get('frontend_structure_ready', '')}",
        f"operator_journey_replay_frontend_operation_replay_ready={operator_summary.get('frontend_operation_replay_ready', '')}",
        f"operator_journey_replay_architecture_ready={operator_summary.get('architecture_contract_ready', '')}",
        f"operator_journey_replay_codebase_graph_ready={operator_summary.get('codebase_graph_ready', '')}",
        f"operator_journey_replay_external_advantage_ci_ready={operator_summary.get('external_advantage_ci_ready', '')}",
        f"operator_journey_replay_external_process_adjudication_ready={operator_summary.get('external_process_adjudication_ready', '')}",
        f"operator_journey_replay_upstream_pr_ci_ready={operator_summary.get('upstream_pr_ci_ready', '')}",
        f"operator_journey_replay_competitor_runtime_ready={operator_summary.get('competitor_runtime_ready', '')}",
        f"operator_journey_replay_competitor_blind_ready={operator_summary.get('competitor_blind_adjudication_ready', '')}",
        f"operator_journey_replay_competitor_behavior_ready={operator_summary.get('competitor_behavior_regression_ready', '')}",
        f"operator_journey_replay_paibi_cli_cross_ready={operator_summary.get('paibi_cli_cross_adjudication_ready', '')}",
        f"operator_journey_replay_employee_patch_stress_ready={operator_summary.get('employee_patch_stress_ready', '')}",
        f"operator_journey_replay_contract_stability_ready={operator_summary.get('contract_stability_ready', '')}",
        f"operator_journey_replay_cross_domain_end_to_end_ready={operator_summary.get('cross_domain_end_to_end_ready', '')}",
        f"operator_journey_replay_cross_domain_ci_regression_ready={operator_summary.get('cross_domain_ci_regression_ready', '')}",
        f"operator_journey_replay_manifest={operator_summary.get('manifest_path', '')}",
        f"operator_journey_replay_single_command={operator_summary.get('single_command_surface', '')}",
        f"absorption_release_decision_status={release_decision.get('status', '')}",
        f"absorption_release_decision_ready={release_summary.get('ready_decision_count', '')}/{release_summary.get('decision_count', '')}",
        f"absorption_release_decision_core_paths={release_summary.get('core_decision_path_count', '')}",
        f"absorption_release_decision_all_ready={release_summary.get('all_core_decisions_ready', '')}",
        f"absorption_release_decision_product_mainline_ready={release_summary.get('product_mainline_absorption_ready', '')}",
        f"absorption_release_decision_product_mainline_merge={release_summary.get('product_mainline_absorption_merge', '')}",
        f"absorption_release_decision_long_run_ready={release_summary.get('long_run_ready', '')}",
        f"absorption_release_decision_holdout_ready={release_summary.get('holdout_blind_eval_ready', '')}",
        f"absorption_release_decision_failure_rollback_ready={release_summary.get('failure_rollback_ready', '')}",
        f"absorption_release_decision_recovery_ready={release_summary.get('recovery_ready', '')}",
        f"absorption_release_decision_employee_patch_stress_ready={release_summary.get('employee_patch_stress_ready', '')}",
        f"absorption_release_decision_employee_patch_stress_workers={release_summary.get('employee_patch_stress_workers', '')}",
        f"absorption_release_decision_employee_patch_stress_rollbacks={release_summary.get('employee_patch_stress_rollbacks', '')}",
        f"absorption_release_decision_employee_scheduler_ready={release_summary.get('employee_scheduler_stress_ready', '')}",
        f"absorption_release_decision_employee_scheduler_unique_processes={release_summary.get('employee_scheduler_stress_unique_processes', '')}",
        f"absorption_release_decision_external_ci_ready={release_summary.get('external_advantage_ci_regression_ready', '')}",
        f"absorption_release_decision_external_process_ready={release_summary.get('external_process_adjudication_ready', '')}",
        f"absorption_release_decision_upstream_pr_ci_ready={release_summary.get('upstream_pr_ci_ready', '')}",
        f"absorption_release_decision_competitor_runtime_ready={release_summary.get('competitor_runtime_ready', '')}",
        f"absorption_release_decision_competitor_runtime_projects={release_summary.get('competitor_runtime_ready_projects', '')}/{release_summary.get('competitor_runtime_project_count', '')}",
        f"absorption_release_decision_competitor_runtime_multi_side_by_side={release_summary.get('competitor_runtime_multi_side_by_side', '')}",
        f"absorption_release_decision_competitor_runtime_live_upstream={release_summary.get('competitor_runtime_live_upstream_verified', '')}",
        f"absorption_release_decision_competitor_runtime_live_materialized={release_summary.get('competitor_runtime_live_upstream_materialized', '')}",
        f"absorption_release_decision_competitor_blind_ready={release_summary.get('competitor_blind_adjudication_ready', '')}",
        f"absorption_release_decision_competitor_blind_min_delta={release_summary.get('competitor_blind_adjudication_min_delta', '')}",
        f"absorption_release_decision_competitor_behavior_ready={release_summary.get('competitor_behavior_regression_ready', '')}",
        f"absorption_release_decision_competitor_behavior_assertions={release_summary.get('competitor_behavior_regression_assertions', '')}",
        f"absorption_release_decision_paibi_cli_cross_ready={release_summary.get('paibi_cli_cross_adjudication_ready', '')}",
        f"absorption_release_decision_paibi_cli_cross_tools={release_summary.get('paibi_cli_cross_adjudication_tools', '')}/{release_summary.get('paibi_cli_cross_adjudication_tool_count', '')}",
        f"absorption_release_decision_paibi_cli_cross_consensus={release_summary.get('paibi_cli_cross_adjudication_consensus', '')}",
        f"absorption_release_decision_paibi_cli_cross_human_reviewed={release_summary.get('paibi_cli_cross_adjudication_human_reviewed', '')}",
        f"absorption_release_decision_paibi_cli_cross_human_calibrated={release_summary.get('paibi_cli_cross_adjudication_human_calibrated', '')}",
        f"absorption_release_decision_cross_domain_ready={release_summary.get('cross_domain_absorption_ready', '')}",
        f"absorption_release_decision_cross_domain_domains={release_summary.get('cross_domain_absorption_domains', '')}",
        f"absorption_release_decision_cross_domain_assertions={release_summary.get('cross_domain_absorption_output_assertions', '')}",
        f"absorption_release_decision_cross_domain_e2e_ready={release_summary.get('cross_domain_end_to_end_ready', '')}",
        f"absorption_release_decision_cross_domain_ci_ready={release_summary.get('cross_domain_ci_regression_ready', '')}",
        f"absorption_release_decision_cross_domain_ci_rounds={release_summary.get('cross_domain_ci_regression_rounds', '')}",
        f"absorption_release_decision_contract_runtime_ready={release_summary.get('contract_runtime_rehearsal_ready', '')}",
        f"absorption_release_decision_contract_runtime_rollback={release_summary.get('contract_runtime_rehearsal_rollback', '')}",
        f"absorption_release_decision_contract_stability_ready={release_summary.get('contract_stability_stress_ready', '')}",
        f"absorption_release_decision_review_family_ready={release_summary.get('review_family_behavior_ready', '')}",
        f"absorption_release_decision_review_family_outputs={release_summary.get('review_family_behavior_outputs', '')}",
        f"absorption_release_decision_operator_journey_ready={release_summary.get('operator_journey_ready', '')}",
        f"absorption_release_decision_operator_cross_domain_ready={release_summary.get('operator_journey_cross_domain_ready', '')}",
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
    latest = latest_employee_result_file(project)
    if not latest:
        return []
    payload = read_json(latest)
    runtime = payload.get("runtime_evidence") if isinstance(payload.get("runtime_evidence"), dict) else {}
    review = runtime.get("worker_review") if isinstance(runtime.get("worker_review"), dict) else {}
    multi_worker = runtime.get("multi_worker") if isinstance(runtime.get("multi_worker"), dict) else {}
    process_isolation = multi_worker.get("process_isolation") if isinstance(multi_worker.get("process_isolation"), dict) else {}
    patch = runtime.get("employee_patch_closure") if isinstance(runtime.get("employee_patch_closure"), dict) else {}
    patch_summary = patch.get("summary") if isinstance(patch.get("summary"), dict) else {}
    return [
        f"employee_results_file={latest}",
        f"employee_result_count={len(payload.get('results') or [])}; execution_mode={payload.get('execution_mode', '')}",
        f"employee_runtime_worker_review={review.get('status', '')}; comments={review.get('comment_count', '')}; artifact={review.get('artifact', '')}",
        f"employee_runtime_worker_review_files={review.get('file_count', '')}; task_groups={review.get('task_group_count', '')}; worker_reviews={review.get('worker_review_count', '')}",
        f"employee_runtime_multi_worker_verified={multi_worker.get('verified', '')}; workers={multi_worker.get('worker_count', '')}; independent_workers={multi_worker.get('independent_worker_count', '')}; result_paths={multi_worker.get('result_path_count', '')}",
        f"employee_runtime_pid_isolation_verified={process_isolation.get('pid_isolation_verified', '')}; unique_pids={process_isolation.get('unique_process_id_count', '')}; traces={process_isolation.get('worker_process_trace_count', '')}",
        f"employee_runtime_crash_isolation_verified={process_isolation.get('crash_isolation_verified', '')}; crash_verified={process_isolation.get('crash_isolation_verified_count', '')}",
        f"employee_runtime_patch_closure={patch.get('status', '')}; success_case={patch_summary.get('success_case_verified', '')}; rollback_case={patch_summary.get('failure_case_rolled_back', '')}",
    ]


def latest_employee_result_file(project: Path) -> Path | None:
    latest = latest_absorption_run_payload(project)
    result_path = Path(str(latest.get("employee_results_path") or ""))
    if result_path.is_file():
        return result_path
    results = employee_result_files(project)
    return results[-1] if results else None


def latest_absorption_run_payload(project: Path) -> dict[str, Any]:
    run_dir = project / ".retort" / "real_absorption_runs"
    runs = sorted(run_dir.glob("*.json")) if run_dir.is_dir() else []
    for path in reversed(runs):
        payload = read_json(path)
        if payload:
            return payload
    return {}


def _latest_run_evidence(project: Path) -> list[str]:
    run_dir = project / ".retort" / "real_absorption_runs"
    runs = sorted(run_dir.glob("*.json")) if run_dir.is_dir() else []
    for path in reversed(runs):
        payload = read_json(path)
        if payload:
            changed_files = [str(item) for item in payload.get("changed_files") or []]
            source_files = [item for item in changed_files if "/retort_engine/" in item and "/tests/" not in item]
            test_files = [item for item in changed_files if "/tests/" in item]
            summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
            return [
                f"latest_absorption_run_id={payload.get('run_id', path.stem)}",
                f"latest_absorption_source={payload.get('source', '')}",
                f"latest_absorption_gates_passed={payload.get('gates_passed', '')}",
                f"latest_absorption_changed_file_count={len(changed_files)}",
                f"latest_absorption_behavior_source_count={len(source_files)}",
                f"latest_absorption_behavior_test_count={len(test_files)}",
                f"latest_absorption_worker_count={summary.get('worker_count', '')}",
                f"latest_absorption_independent_worker_count={summary.get('independent_worker_count', '')}",
                f"latest_absorption_employee_result_count={summary.get('employee_result_count', '')}",
                f"latest_absorption_multi_worker_verified={summary.get('multi_worker_verified', '')}",
                f"latest_absorption_worker_review_count={summary.get('worker_review_count', '')}",
                f"latest_absorption_worker_review_files={summary.get('worker_review_file_count', '')}",
                f"latest_absorption_worker_review_comments={summary.get('worker_review_comment_count', '')}",
                f"latest_absorption_worker_review_task_groups={summary.get('worker_review_task_group_count', '')}",
                f"latest_absorption_pid_isolation_verified={summary.get('pid_isolation_verified', '')}",
                f"latest_absorption_unique_process_ids={summary.get('unique_process_id_count', '')}",
                f"latest_absorption_worker_process_traces={summary.get('worker_process_trace_count', '')}",
                f"latest_absorption_crash_isolation_verified={summary.get('crash_isolation_verified', '')}",
                f"latest_absorption_crash_isolation_verified_count={summary.get('crash_isolation_verified_count', '')}",
            ]
    return []


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
