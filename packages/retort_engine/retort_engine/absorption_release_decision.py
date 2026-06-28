from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def build_absorption_release_decision(project: str | Path, *, output: str | Path = "") -> dict[str, Any]:
    root = Path(project).expanduser().resolve()
    quality = _read_json(root / "docs" / "retort_quality_gate_bundle.json")
    continuity = _read_json(root / "docs" / "retort_absorption_continuity_probe.json")
    long_run = _read_json(root / "docs" / "retort_pr_long_run_review.json")
    holdout = _read_json(root / "docs" / "retort_pr_holdout_blind_eval.json")
    failure_rollback = _read_json(root / "docs" / "retort_pr_failure_rollback_replay.json")
    recovery = _read_json(root / "docs" / "retort_production_recovery_drill.json")
    mainline_proof = _read_json(root / "docs" / "retort_product_mainline_absorption_proof.json")
    patch = _read_json(root / "docs" / "retort_employee_patch_closure.json")
    patch_stress = _read_json(root / "docs" / "retort_employee_patch_stress.json")
    scheduler_stress = _read_json(root / "docs" / "retort_employee_scheduler_stress.json")
    benchmark = _read_json(root / "docs" / "retort_review_quality_benchmark.json")
    external_matrix = _read_json(root / "docs" / "retort_external_advantage_matrix.json")
    external_ci_regression = _read_json(root / "docs" / "retort_external_advantage_ci_regression.json")
    external_process_adjudication = _read_json(root / "docs" / "retort_external_process_adjudication.json")
    external_repeat = _read_json(root / "docs" / "retort_external_advantage_repeat.json")
    upstream_pr_ci = _read_json(root / "docs" / "retort_upstream_pr_ci_probe.json")
    competitor_runtime = _read_json(root / "docs" / "retort_competitor_runtime_comparison.json")
    competitor_blind = _read_json(root / "docs" / "retort_competitor_blind_adjudication.json")
    competitor_behavior = _read_json(root / "docs" / "retort_competitor_behavior_regression.json")
    paibi_cli_cross = _read_json(root / "docs" / "retort_paibi_cli_cross_adjudication.json")
    heterogeneous_replay = _read_json(root / "docs" / "retort_heterogeneous_absorption_replay.json")
    cross_domain_replay = _read_json(root / "docs" / "retort_cross_domain_absorption_replay.json")
    cross_domain_end_to_end = _read_json(root / "docs" / "retort_cross_domain_end_to_end.json")
    cross_domain_ci = _read_json(root / "docs" / "retort_cross_domain_ci_regression.json")
    contract_runtime = _read_json(root / "docs" / "retort_contract_runtime_rehearsal.json")
    contract_stability = _read_json(root / "docs" / "retort_contract_stability_stress.json")
    review_family = _read_json(root / "docs" / "retort_review_family_behavior_replay.json")
    external_merge_landing = _read_json(root / "docs" / "retort_external_merge_landing.json")
    operator_journey = _read_json(root / "docs" / "retort_operator_journey_replay.json")
    decisions = [
        _decision(
            "run_absorption",
            "absorption_depth",
            quality.get("summary", {}).get("all_gates_passed") is True and continuity.get("status") == "ready",
            ["quality_gate_bundle", "absorption_continuity_probe"],
        ),
        _decision(
            "prove_product_mainline_absorption_merge",
            "branch_absorption_workflow",
            mainline_proof.get("status") == "ready"
            and mainline_proof.get("summary", {}).get("is_merge_commit") is True
            and int(mainline_proof.get("summary", {}).get("behavior_source_changed_count") or 0) > 0
            and int(mainline_proof.get("summary", {}).get("behavior_test_changed_count") or 0) > 0
            and mainline_proof.get("summary", {}).get("post_merge_quality_gate_passed") is True,
            ["product_mainline_absorption_proof"],
        ),
        _decision(
            "dispatch_employee_patch",
            "employee_execution",
            patch.get("status") == "ready" and patch.get("summary", {}).get("all_expected_outcomes_verified") is True,
            ["employee_patch_closure"],
        ),
        _decision(
            "stress_employee_patch_rollback",
            "employee_execution",
            patch_stress.get("status") == "ready"
            and patch_stress.get("summary", {}).get("concurrency_floor_exceeded") is True
            and int(patch_stress.get("summary", {}).get("rollback_verified_count") or 0) >= 100
            and patch_stress.get("summary", {}).get("all_post_rollback_gates_passed") is True,
            ["employee_patch_stress"],
        ),
        _decision(
            "stress_employee_independent_processes",
            "employee_execution",
            scheduler_stress.get("status") == "ready"
            and int(scheduler_stress.get("summary", {}).get("unique_successful_process_id_count") or 0) >= 20
            and scheduler_stress.get("summary", {}).get("pid_isolation_verified") is True
            and scheduler_stress.get("summary", {}).get("queue_result_history_consistent") is True,
            ["employee_scheduler_stress"],
        ),
        _decision(
            "publish_or_degrade_review",
            "product_operability",
            long_run.get("status") == "ready" and recovery.get("status") == "ready",
            ["pr_long_run_review", "production_recovery_drill"],
        ),
        _decision(
            "claim_absorbed_quality_gain",
            "feedback_loop_closure",
            benchmark.get("status") == "ready" and int(benchmark.get("summary", {}).get("post_absorption_score_delta") or 0) > 0,
            ["review_quality_benchmark"],
        ),
        _decision(
            "prove_external_advantage_matrix",
            "comparative_analysis_depth",
            external_matrix.get("status") == "ready"
            and int(external_matrix.get("summary", {}).get("score_delta") or 0) > 0
            and external_matrix.get("summary", {}).get("blind_third_party_all_cases_accepted") is True
            and int(external_matrix.get("summary", {}).get("blind_third_party_minimum_delta") or 0) >= 65,
            ["external_advantage_matrix"],
        ),
        _decision(
            "prove_external_advantage_ci_regression",
            "comparative_analysis_depth",
            external_ci_regression.get("status") == "ready"
            and external_ci_regression.get("summary", {}).get("all_cases_have_ci_acceptance") is True
            and external_ci_regression.get("summary", {}).get("all_direct_review_regressions_verified") is True
            and int(external_ci_regression.get("summary", {}).get("blind_third_party_minimum_delta") or 0) >= 80,
            ["external_advantage_ci_regression"],
        ),
        _decision(
            "prove_external_process_adjudication",
            "comparative_analysis_depth",
            external_process_adjudication.get("status") == "ready"
            and external_process_adjudication.get("summary", {}).get("external_all_cases_accepted") is True
            and external_process_adjudication.get("summary", {}).get("script_imports_retort_engine") is False
            and int(external_process_adjudication.get("summary", {}).get("external_minimum_delta") or 0) >= 80,
            ["external_process_adjudication"],
        ),
        _decision(
            "prove_repeatable_external_advantage",
            "comparative_analysis_depth",
            external_repeat.get("status") == "ready"
            and external_repeat.get("summary", {}).get("stable_case_set") is True
            and external_repeat.get("summary", {}).get("stable_score_delta") is True,
            ["external_advantage_repeat"],
        ),
        _decision(
            "prove_upstream_pr_ci",
            "branch_absorption_workflow",
            upstream_pr_ci.get("status") == "ready"
            and upstream_pr_ci.get("summary", {}).get("multi_repo_ci_generalization") is True
            and int(upstream_pr_ci.get("summary", {}).get("distinct_repo_count") or 0) >= 3
            and int(upstream_pr_ci.get("summary", {}).get("ready_target_count") or 0) >= 3
            and upstream_pr_ci.get("summary", {}).get("all_target_check_runs_successful") is True,
            ["upstream_pr_ci_probe"],
        ),
        _decision(
            "prove_competitor_runtime_comparison",
            "comparative_analysis_depth",
            competitor_runtime.get("status") == "ready"
            and competitor_runtime.get("summary", {}).get("side_by_side_output_materialized") is True
            and competitor_runtime.get("summary", {}).get("multi_competitor_side_by_side") is True
            and int(competitor_runtime.get("summary", {}).get("ready_competitor_project_count") or 0) >= 3
            and competitor_runtime.get("summary", {}).get("all_external_processes_successful") is True
            and competitor_runtime.get("summary", {}).get("all_live_upstream_sources_verified") is True
            and competitor_runtime.get("summary", {}).get("all_live_upstream_sources_materialized") is True
            and competitor_runtime.get("summary", {}).get("retort_exceeds_patch_parser_by_semantic_comments") is True,
            ["competitor_runtime_comparison"],
        ),
        _decision(
            "prove_competitor_blind_adjudication",
            "comparative_analysis_depth",
            competitor_blind.get("status") == "ready"
            and competitor_blind.get("summary", {}).get("all_competitors_blind_accepted") is True
            and competitor_blind.get("summary", {}).get("script_imports_retort_engine") is False
            and competitor_blind.get("summary", {}).get("input_contains_score_fields") is False
            and int(competitor_blind.get("summary", {}).get("minimum_blind_delta") or 0) >= 45,
            ["competitor_blind_adjudication"],
        ),
        _decision(
            "prove_competitor_behavior_regression",
            "capability_absorption",
            competitor_behavior.get("status") == "ready"
            and competitor_behavior.get("summary", {}).get("all_competitor_signals_regressed") is True
            and competitor_behavior.get("summary", {}).get("all_cases_direct_review_execution") is True
            and int(competitor_behavior.get("summary", {}).get("ready_case_count") or 0) >= 3
            and int(competitor_behavior.get("summary", {}).get("behavior_assertion_count") or 0) >= 18,
            ["competitor_behavior_regression"],
        ),
        _decision(
            "prove_paibi_four_cli_cross_adjudication",
            "comparative_analysis_depth",
            paibi_cli_cross.get("status") == "ready"
            and int(paibi_cli_cross.get("summary", {}).get("tool_count") or 0) >= 4
            and int(paibi_cli_cross.get("summary", {}).get("accepted_tool_count") or 0) >= 4
            and paibi_cli_cross.get("summary", {}).get("all_tools_accepted") is True
            and paibi_cli_cross.get("summary", {}).get("cross_tool_consensus") is True
            and paibi_cli_cross.get("summary", {}).get("input_contains_score_fields") is False
            and paibi_cli_cross.get("summary", {}).get("script_imports_retort_engine") is False
            and paibi_cli_cross.get("summary", {}).get("human_reviewed") is False,
            ["paibi_cli_cross_adjudication"],
        ),
        _decision(
            "prove_heterogeneous_absorption",
            "cross_language_absorption",
            heterogeneous_replay.get("status") == "ready"
            and heterogeneous_replay.get("summary", {}).get("all_before_failed_after_passed") is True
            and heterogeneous_replay.get("summary", {}).get("cross_language_absorption_verified") is True,
            ["heterogeneous_absorption_replay"],
        ),
        _decision(
            "prove_non_pr_cross_domain_absorption",
            "cross_domain_absorption",
            cross_domain_replay.get("status") == "ready"
            and cross_domain_replay.get("summary", {}).get("all_before_failed_after_passed") is True
            and cross_domain_replay.get("summary", {}).get("all_output_assertions_passed") is True
            and int(cross_domain_replay.get("summary", {}).get("non_pr_domain_count") or 0) >= 10,
            ["cross_domain_absorption_replay"],
        ),
        _decision(
            "prove_cross_domain_end_to_end_absorption",
            "cross_domain_absorption",
            cross_domain_end_to_end.get("status") == "ready"
            and cross_domain_end_to_end.get("summary", {}).get("all_stages_chained") is True
            and cross_domain_end_to_end.get("summary", {}).get("all_stage_outputs_consumed") is True
            and int(cross_domain_end_to_end.get("summary", {}).get("linked_domain_count") or 0) >= 10,
            ["cross_domain_end_to_end"],
        ),
        _decision(
            "prove_cross_domain_continuous_regression",
            "cross_domain_absorption",
            cross_domain_ci.get("status") == "ready"
            and int(cross_domain_ci.get("summary", {}).get("ready_round_count") or 0) >= 3
            and cross_domain_ci.get("summary", {}).get("all_output_assertions_passed") is True
            and cross_domain_ci.get("summary", {}).get("stable_domain_count") is True,
            ["cross_domain_ci_regression"],
        ),
        _decision(
            "reject_contract_runtime_violations",
            "api_contract_quality",
            contract_runtime.get("status") == "ready"
            and contract_runtime.get("summary", {}).get("all_violations_rejected") is True
            and contract_runtime.get("summary", {}).get("all_rollbacks_verified") is True
            and contract_runtime.get("summary", {}).get("all_concurrent_violations_rejected") is True
            and contract_runtime.get("summary", {}).get("all_concurrent_rollbacks_verified") is True,
            ["contract_runtime_rehearsal"],
        ),
        _decision(
            "prove_contract_stability_under_load",
            "api_contract_quality",
            contract_stability.get("status") == "ready"
            and contract_stability.get("summary", {}).get("concurrency_floor_exceeded") is True
            and int(contract_stability.get("summary", {}).get("state_leak_count") or 0) == 0
            and int(contract_stability.get("summary", {}).get("total_fault_injection_count") or 0) >= 600,
            ["contract_stability_stress"],
        ),
        _decision(
            "prove_review_family_core_behavior",
            "branch_absorption_workflow",
            review_family.get("status") == "ready"
            and review_family.get("summary", {}).get("all_direct_review_outputs_verified") is True
            and review_family.get("summary", {}).get("independent_all_cases_accepted") is True
            and int(review_family.get("summary", {}).get("typescript_case_count") or 0) >= 2,
            ["review_family_behavior_replay"],
        ),
        _decision(
            "prove_external_merge_landing",
            "branch_absorption_workflow",
            external_merge_landing.get("status") == "ready"
            and external_merge_landing.get("summary", {}).get("all_branch_diff_merge_tests_passed") is True
            and int(external_merge_landing.get("summary", {}).get("merge_commit_count") or 0) >= 10,
            ["external_merge_landing"],
        ),
        _decision(
            "accept_blind_holdout_quality",
            "blind_external_validation",
            holdout.get("status") == "ready" and int(holdout.get("summary", {}).get("accepted_pr_count") or 0) >= int(holdout.get("summary", {}).get("target_pr_count") or 20),
            ["pr_holdout_blind_eval"],
        ),
        _decision(
            "allow_failure_rollback_replay",
            "failure_recovery_validation",
            failure_rollback.get("status") == "ready" and bool(failure_rollback.get("summary", {}).get("all_failures_rolled_back")),
            ["pr_failure_rollback_replay"],
        ),
        _decision(
            "replay_operator_absorption_journey",
            "product_operability",
            operator_journey.get("status") == "ready" and bool(operator_journey.get("summary", {}).get("cross_domain_live_probe_ready")),
            ["operator_journey_replay"],
        ),
    ]
    ready = [item for item in decisions if item["ready"]]
    blockers = [item for item in decisions if not item["ready"]]
    summary = {
        "decision_count": len(decisions),
        "ready_decision_count": len(ready),
        "blocking_decision_count": len(blockers),
        "core_decision_path_count": len({item["dimension"] for item in decisions}),
        "all_core_decisions_ready": len(blockers) == 0,
        "quality_gate_all_passed": quality.get("summary", {}).get("all_gates_passed") is True,
        "product_mainline_absorption_ready": mainline_proof.get("status") == "ready",
        "product_mainline_absorption_merge": mainline_proof.get("summary", {}).get("is_merge_commit", ""),
        "product_mainline_absorption_behavior_sources": mainline_proof.get("summary", {}).get("behavior_source_changed_count", ""),
        "product_mainline_absorption_behavior_tests": mainline_proof.get("summary", {}).get("behavior_test_changed_count", ""),
        "long_run_ready": long_run.get("status") == "ready",
        "recovery_ready": recovery.get("status") == "ready",
        "employee_patch_ready": patch.get("status") == "ready",
        "employee_patch_stress_ready": patch_stress.get("status") == "ready",
        "employee_patch_stress_workers": patch_stress.get("summary", {}).get("worker_count", ""),
        "employee_patch_stress_rollbacks": patch_stress.get("summary", {}).get("rollback_verified_count", ""),
        "employee_patch_stress_post_rollback_gates": patch_stress.get("summary", {}).get("post_rollback_gate_passed_count", ""),
        "employee_scheduler_stress_ready": scheduler_stress.get("status") == "ready",
        "employee_scheduler_stress_unique_processes": scheduler_stress.get("summary", {}).get("unique_successful_process_id_count", ""),
        "employee_scheduler_stress_queued_tasks": scheduler_stress.get("summary", {}).get("queued_task_count", ""),
        "holdout_blind_eval_ready": holdout.get("status") == "ready",
        "external_advantage_matrix_ready": external_matrix.get("status") == "ready",
        "external_advantage_matrix_delta": external_matrix.get("summary", {}).get("score_delta", ""),
        "external_advantage_blind_third_party_ready": external_matrix.get("summary", {}).get("blind_third_party_all_cases_accepted", ""),
        "external_advantage_blind_third_party_min_delta": external_matrix.get("summary", {}).get("blind_third_party_minimum_delta", ""),
        "external_advantage_ci_regression_ready": external_ci_regression.get("status") == "ready",
        "external_advantage_ci_regression_cases": external_ci_regression.get("summary", {}).get("passed_case_count", ""),
        "external_advantage_ci_regression_min_delta": external_ci_regression.get("summary", {}).get("blind_third_party_minimum_delta", ""),
        "external_process_adjudication_ready": external_process_adjudication.get("status") == "ready",
        "external_process_adjudication_min_delta": external_process_adjudication.get("summary", {}).get("external_minimum_delta", ""),
        "external_process_adjudication_imports_retort": external_process_adjudication.get("summary", {}).get("script_imports_retort_engine", ""),
        "external_advantage_repeat_ready": external_repeat.get("status") == "ready",
        "external_advantage_repeat_total_cases": external_repeat.get("summary", {}).get("total_case_evaluation_count", ""),
        "upstream_pr_ci_ready": upstream_pr_ci.get("status") == "ready",
        "upstream_pr_ci_distinct_repos": upstream_pr_ci.get("summary", {}).get("distinct_repo_count", ""),
        "upstream_pr_ci_ready_targets": upstream_pr_ci.get("summary", {}).get("ready_target_count", ""),
        "upstream_pr_ci_target_count": upstream_pr_ci.get("summary", {}).get("target_count", ""),
        "upstream_pr_ci_check_runs": upstream_pr_ci.get("summary", {}).get("check_run_count", ""),
        "upstream_pr_ci_total_check_runs": upstream_pr_ci.get("summary", {}).get("total_check_run_count", ""),
        "upstream_pr_ci_all_successful": upstream_pr_ci.get("summary", {}).get("all_check_runs_successful", ""),
        "upstream_pr_ci_all_targets_successful": upstream_pr_ci.get("summary", {}).get("all_target_check_runs_successful", ""),
        "competitor_runtime_ready": competitor_runtime.get("status") == "ready",
        "competitor_runtime_project_count": competitor_runtime.get("summary", {}).get("competitor_project_count", ""),
        "competitor_runtime_ready_projects": competitor_runtime.get("summary", {}).get("ready_competitor_project_count", ""),
        "competitor_runtime_multi_side_by_side": competitor_runtime.get("summary", {}).get("multi_competitor_side_by_side", ""),
        "competitor_runtime_live_upstream_verified": competitor_runtime.get("summary", {}).get("all_live_upstream_sources_verified", ""),
        "competitor_runtime_live_upstream_projects": competitor_runtime.get("summary", {}).get("live_upstream_verified_count", ""),
        "competitor_runtime_live_upstream_materialized": competitor_runtime.get("summary", {}).get("all_live_upstream_sources_materialized", ""),
        "competitor_runtime_hunks": competitor_runtime.get("summary", {}).get("competitor_hunk_count", ""),
        "competitor_runtime_retort_comments": competitor_runtime.get("summary", {}).get("retort_comment_count", ""),
        "competitor_blind_adjudication_ready": competitor_blind.get("status") == "ready",
        "competitor_blind_adjudication_accepted": competitor_blind.get("summary", {}).get("accepted_competitor_count", ""),
        "competitor_blind_adjudication_competitors": competitor_blind.get("summary", {}).get("competitor_count", ""),
        "competitor_blind_adjudication_min_delta": competitor_blind.get("summary", {}).get("minimum_blind_delta", ""),
        "competitor_blind_adjudication_imports_retort": competitor_blind.get("summary", {}).get("script_imports_retort_engine", ""),
        "competitor_behavior_regression_ready": competitor_behavior.get("status") == "ready",
        "competitor_behavior_regression_cases": competitor_behavior.get("summary", {}).get("ready_case_count", ""),
        "competitor_behavior_regression_assertions": competitor_behavior.get("summary", {}).get("behavior_assertion_count", ""),
        "competitor_behavior_regression_direct": competitor_behavior.get("summary", {}).get("all_cases_direct_review_execution", ""),
        "paibi_cli_cross_adjudication_ready": paibi_cli_cross.get("status") == "ready",
        "paibi_cli_cross_adjudication_tools": paibi_cli_cross.get("summary", {}).get("accepted_tool_count", ""),
        "paibi_cli_cross_adjudication_tool_count": paibi_cli_cross.get("summary", {}).get("tool_count", ""),
        "paibi_cli_cross_adjudication_consensus": paibi_cli_cross.get("summary", {}).get("cross_tool_consensus", ""),
        "paibi_cli_cross_adjudication_human_reviewed": paibi_cli_cross.get("summary", {}).get("human_reviewed", ""),
        "heterogeneous_absorption_ready": heterogeneous_replay.get("status") == "ready",
        "heterogeneous_absorption_languages": heterogeneous_replay.get("summary", {}).get("language_family_count", ""),
        "heterogeneous_absorption_before_after": heterogeneous_replay.get("summary", {}).get("all_before_failed_after_passed", ""),
        "cross_domain_absorption_ready": cross_domain_replay.get("status") == "ready",
        "cross_domain_absorption_domains": cross_domain_replay.get("summary", {}).get("non_pr_domain_count", ""),
        "cross_domain_absorption_direct_modules": cross_domain_replay.get("summary", {}).get("direct_module_count", ""),
        "cross_domain_absorption_output_assertions": cross_domain_replay.get("summary", {}).get("all_output_assertions_passed", ""),
        "cross_domain_end_to_end_ready": cross_domain_end_to_end.get("status") == "ready",
        "cross_domain_end_to_end_domains": cross_domain_end_to_end.get("summary", {}).get("linked_domain_count", ""),
        "cross_domain_end_to_end_review_status": cross_domain_end_to_end.get("summary", {}).get("integrated_review_status", ""),
        "cross_domain_ci_regression_ready": cross_domain_ci.get("status") == "ready",
        "cross_domain_ci_regression_rounds": cross_domain_ci.get("summary", {}).get("ready_round_count", ""),
        "cross_domain_ci_regression_total_domains": cross_domain_ci.get("summary", {}).get("total_domain_replay_count", ""),
        "contract_runtime_rehearsal_ready": contract_runtime.get("status") == "ready",
        "contract_runtime_rehearsal_rejected": contract_runtime.get("summary", {}).get("violation_rejected_count", ""),
        "contract_runtime_rehearsal_rollback": contract_runtime.get("summary", {}).get("all_rollbacks_verified", ""),
        "contract_runtime_rehearsal_concurrent_rejected": contract_runtime.get("summary", {}).get("concurrent_violation_rejected_count", ""),
        "contract_runtime_rehearsal_concurrent_rollback": contract_runtime.get("summary", {}).get("all_concurrent_rollbacks_verified", ""),
        "contract_stability_stress_ready": contract_stability.get("status") == "ready",
        "contract_stability_stress_workers": contract_stability.get("summary", {}).get("concurrent_worker_count", ""),
        "contract_stability_stress_faults": contract_stability.get("summary", {}).get("total_fault_injection_count", ""),
        "contract_stability_stress_state_leaks": contract_stability.get("summary", {}).get("state_leak_count", ""),
        "review_family_behavior_ready": review_family.get("status") == "ready",
        "review_family_behavior_typescript_cases": review_family.get("summary", {}).get("typescript_case_count", ""),
        "review_family_behavior_python_cases": review_family.get("summary", {}).get("python_case_count", ""),
        "review_family_behavior_outputs": review_family.get("summary", {}).get("all_direct_review_outputs_verified", ""),
        "external_merge_landing_ready": external_merge_landing.get("status") == "ready",
        "external_merge_landing_merge_commits": external_merge_landing.get("summary", {}).get("merge_commit_count", ""),
        "external_merge_landing_post_merge_tests": external_merge_landing.get("summary", {}).get("post_merge_test_passed_count", ""),
        "failure_rollback_ready": failure_rollback.get("status") == "ready",
        "operator_journey_ready": operator_journey.get("status") == "ready",
        "operator_journey_cross_domain_ready": bool(operator_journey.get("summary", {}).get("cross_domain_live_probe_ready")),
    }
    result = {
        "status": "ready" if summary["all_core_decisions_ready"] else "blocked",
        "project": str(root),
        "summary": summary,
        "decisions": decisions,
        "evidence": {
            "style": "core_product_decision_gate",
            "source_reports": [
                "retort_quality_gate_bundle.json",
                "retort_absorption_continuity_probe.json",
                "retort_pr_long_run_review.json",
                "retort_pr_holdout_blind_eval.json",
                "retort_pr_failure_rollback_replay.json",
                "retort_production_recovery_drill.json",
                "retort_product_mainline_absorption_proof.json",
                "retort_employee_patch_closure.json",
                "retort_employee_patch_stress.json",
                "retort_employee_scheduler_stress.json",
                "retort_review_quality_benchmark.json",
                "retort_external_advantage_matrix.json",
                "retort_external_advantage_ci_regression.json",
                "retort_external_process_adjudication.json",
                "retort_external_advantage_repeat.json",
                "retort_upstream_pr_ci_probe.json",
                "retort_competitor_runtime_comparison.json",
                "retort_competitor_blind_adjudication.json",
                "retort_competitor_behavior_regression.json",
                "retort_paibi_cli_cross_adjudication.json",
                "retort_heterogeneous_absorption_replay.json",
                "retort_cross_domain_absorption_replay.json",
                "retort_cross_domain_end_to_end.json",
                "retort_cross_domain_ci_regression.json",
                "retort_contract_runtime_rehearsal.json",
                "retort_contract_stability_stress.json",
                "retort_review_family_behavior_replay.json",
                "retort_external_merge_landing.json",
                "retort_operator_journey_replay.json",
            ],
        },
    }
    if output:
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return result


def _decision(name: str, dimension: str, ready: bool, evidence: list[str]) -> dict[str, Any]:
    return {
        "name": name,
        "dimension": dimension,
        "ready": ready,
        "evidence": evidence,
        "action": "allow" if ready else "block",
    }


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}
