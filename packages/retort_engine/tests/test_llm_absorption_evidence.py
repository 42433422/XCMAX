from __future__ import annotations

import json
from pathlib import Path

from retort_engine.absorption_state import save_absorption_state
from retort_engine.llm_absorption_evidence import llm_absorption_evidence, read_json


def test_llm_absorption_evidence_collects_state_reports_and_audit_without_local_scores(tmp_path: Path) -> None:
    external = tmp_path / "external"
    external.mkdir()
    save_absorption_state(
        tmp_path,
        {
            "source": "https://github.com/owner/repo",
            "external_path": str(external),
            "closed_loop_proof": {
                "branch_diff_verified": True,
                "employee_execution_verified": True,
                "post_absorption_tests_passed": True,
                "merge_verified": True,
                "external_advantage_reassessed": True,
                "evidence": ["merge_cross_check=True"],
            },
        },
    )
    source = tmp_path / "retort_engine" / "feature.py"
    test = tmp_path / "tests" / "test_absorbed_capabilities.py"
    source.parent.mkdir()
    test.parent.mkdir()
    source.write_text("def feature():\n    return True\n", encoding="utf-8")
    (source.parent / "pr_review.py").write_text("def parse_unified_diff():\n    task_groups = []\n    return task_groups\n", encoding="utf-8")
    (source.parent / "cross_language_transfer.py").write_text("def build_cross_language_transfer():\n    return {'status': 'mapped'}\n", encoding="utf-8")
    test.write_text("def test_feature():\n    assert True\n", encoding="utf-8")
    run_dir = tmp_path / ".retort" / "real_absorption_runs"
    run_dir.mkdir(parents=True)
    aggregate_result_path = tmp_path / ".retort" / "employee_results" / "result.json"
    (run_dir / "run.json").write_text(
        json.dumps({"source": "https://github.com/owner/repo", "changed_files": [str(source), str(test)], "employee_results_path": str(aggregate_result_path)}),
        encoding="utf-8",
    )
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "retort_pr_live_publish_probe.json").write_text(
        json.dumps(
            {
                "status": "permission_denied_degraded",
                "pr_url": "https://github.com/owner/repo/pull/7",
                "summary": {
                    "target_repo": "owner/repo",
                    "created_comment_count": 0,
                    "rollback_verified": True,
                    "permission_admin": False,
                    "permission_maintain": False,
                    "permission_push": False,
                    "live_github_write": False,
                    "permission_denied": True,
                    "degraded_without_write": True,
                },
                "evidence": {
                    "real_network": False,
                    "transport": "injected_transport",
                    "required_permission": "issues:write or pull_requests:write",
                    "degradation": "no_comment_created_no_rollback_needed",
                },
                "created_receipts": [],
                "rollback_receipts": [],
            }
        ),
        encoding="utf-8",
    )
    (docs / "retort_pr_low_permission_probe.json").write_text(
        json.dumps(
            {
                "status": "permission_denied_degraded",
                "pr_url": "https://github.com/python/cpython/pull/1",
                "summary": {
                    "created_comment_count": 0,
                    "rollback_verified": True,
                    "live_github_write": False,
                    "permission_denied": True,
                    "degraded_without_write": True,
                },
                "evidence": {
                    "real_network": False,
                    "transport": "injected_transport",
                    "required_permission": "issues:write or pull_requests:write",
                    "degradation": "no_comment_created_no_rollback_needed",
                },
                "created_receipts": [],
                "rollback_receipts": [],
            }
        ),
        encoding="utf-8",
    )
    (docs / "retort_external_review_report.json").write_text(
        json.dumps(
            {
                "external_snapshot": {"git_revision": "abc123"},
                "absorbed_signals": ["pipeline", "benchmark"],
                "semantic_review": {"gaps": [{"name": "one"}]},
                "license_review": {"status": "passed", "detected_license": "MIT", "source_code_copy_allowed": True, "pattern_absorption_allowed": True, "isolation_policy": "license_gate_standard"},
                "review_pipeline": {
                    "component_gaps": [{"component": "core"}],
                    "prioritized_absorptions": [{"task": "split"}],
                    "benchmark": {"minimum_expected_behavior_tests": 2},
                },
            }
        ),
        encoding="utf-8",
    )
    (docs / "retort_employee_patch_closure.json").write_text(
        json.dumps(
            {
                "status": "ready",
                "summary": {
                    "case_count": 4,
                    "patch_generated_count": 4,
                    "patch_applied_count": 4,
                    "gate_passed_count": 3,
                    "primary_rollback_verified_count": 2,
                    "rollback_verified_count": 4,
                    "rollback_scope": "per_primary_case_failure_injection",
                    "failure_rehearsal_count": 4,
                    "failure_rehearsal_rollback_count": 4,
                    "full_path_rollback_verified": True,
                    "all_cases_have_failure_rollback_rehearsal": True,
                    "success_case_verified": True,
                    "failure_case_rolled_back": True,
                    "multi_file_case_verified": True,
                    "multi_file_changed_file_count": 2,
                    "secondary_review_status": "reviewed",
                    "successful_repairs_re_reviewed": True,
                    "retry_case_verified": True,
                    "retry_first_failure_rolled_back": True,
                    "retry_second_patch_passed": True,
                },
                "cases": [],
                "evidence": {},
            }
        ),
        encoding="utf-8",
    )
    (docs / "retort_quality_gate_bundle.json").write_text(
        json.dumps(
            {
                "status": "ready",
                "summary": {
                    "all_gates_passed": True,
                    "lint_passed": True,
                    "pytest_passed": True,
                    "contract_passed": True,
                    "single_command_surface": True,
                    "test_density_passed": True,
                    "test_density_target_met": False,
                    "test_to_source_ratio": 0.408,
                    "test_density_target": 0.6,
                    "test_density_missing_lines_to_target": 3276,
                    "source_line_count": 17083,
                    "test_line_count": 6974,
                },
                "gates": [],
                "evidence": {},
            }
        ),
        encoding="utf-8",
    )
    (docs / "retort_external_advantage_matrix.json").write_text(
        json.dumps(
            {
                "status": "ready",
                "summary": {
                    "case_count": 6,
                    "ready_case_count": 6,
                    "source_project_count": 6,
                    "absorbed_signal_count": 6,
                    "baseline_average_score": 40,
                    "retort_average_score": 95,
                    "score_delta": 55,
                    "behavior_delta_count": 6,
                    "publishable_case_count": 6,
                    "extension_policy_case_count": 6,
                    "per_case_before_after": True,
                    "all_advantages_improved": True,
                    "regression_case_count": 6,
                    "passed_regression_case_count": 6,
                    "direct_regression_case_count": 6,
                    "all_use_direct_review_execution": True,
                    "all_delta_regressions_verified": True,
                    "blind_third_party_status": "ready",
                    "blind_third_party_adjudicated_case_count": 6,
                    "blind_third_party_accepted_case_count": 6,
                    "blind_third_party_minimum_delta": 65,
                    "blind_third_party_delta_floor_passed": True,
                    "blind_third_party_score_fields_consumed": False,
                },
                "matrix": [],
                "evidence": {
                    "regression_verifier": "retort_engine.external_advantage_regression.verify_external_advantage_rows",
                    "regression_runtime": "retort_engine.pr_review.review_diff",
                    "regression_model": "executable_input_output_diff_replay",
                    "blind_third_party_adjudicator": "retort_engine.external_advantage_adjudicator.blind_third_party_adjudicate_external_advantages",
                    "blind_third_party_boundary": "redacted_structural_facts_only_no_baseline_or_retort_score_fields",
                },
            }
        ),
        encoding="utf-8",
    )
    (docs / "retort_external_advantage_ci_regression.json").write_text(
        json.dumps(
            {
                "status": "ready",
                "summary": {
                    "case_count": 6,
                    "passed_case_count": 6,
                    "source_project_count": 6,
                    "matrix_status": "ready",
                    "blind_third_party_minimum_delta": 80,
                    "blind_delta_floor": 80,
                    "blind_delta_floor_met": True,
                    "all_direct_review_regressions_verified": True,
                    "all_cases_have_ci_acceptance": True,
                },
                "cases": [],
                "evidence": {"ci_gate": "all_cases_direct_replay_and_blind_delta_at_or_above_80"},
            }
        ),
        encoding="utf-8",
    )
    (docs / "retort_heterogeneous_absorption_replay.json").write_text(
        json.dumps(
            {
                "status": "ready",
                "summary": {
                    "case_count": 6,
                    "ready_case_count": 6,
                    "cached_source_count": 6,
                    "language_family_count": 5,
                    "language_families": ["go", "jvm", "python", "rust", "typescript"],
                    "source_family_count": 5,
                    "pre_absorption_failure_count": 6,
                    "post_absorption_pass_count": 6,
                    "all_before_failed_after_passed": True,
                    "minimum_behavior_delta": 70,
                    "average_behavior_delta": 73.33,
                    "independent_adjudication_status": "ready",
                    "independent_adjudicated_case_count": 6,
                    "independent_accepted_case_count": 6,
                    "independent_all_cases_accepted": True,
                    "cross_language_absorption_verified": True,
                },
                "cases": [],
                "evidence": {"adjudicator": "retort_engine.heterogeneous_absorption_replay._adjudicate_rows"},
            }
        ),
        encoding="utf-8",
    )
    (docs / "retort_cross_domain_absorption_replay.json").write_text(
        json.dumps(
            {
                "status": "ready",
                "summary": {
                    "case_count": 10,
                    "ready_case_count": 10,
                    "non_pr_domain_count": 10,
                    "non_pr_domains": [
                        "architecture_governance",
                        "benchmark_harness",
                        "codebase_graph",
                        "context_packaging",
                        "core_architecture_refactor",
                        "employee_dispatch",
                        "employee_task_graph",
                        "intent_alignment",
                        "license_policy",
                        "static_analysis_security",
                    ],
                    "direct_module_count": 10,
                    "direct_modules": [
                        "retort_engine.architecture_contracts.evaluate_architecture_contracts",
                        "retort_engine.architecture_refactor.build_core_refactor_plan",
                        "retort_engine.codebase_graph.build_codebase_graph",
                        "retort_engine.context_packager.build_context_pack",
                        "retort_engine.intent_alignment.assess_change_intent_alignment",
                        "retort_engine.license_gate.license_gate",
                        "retort_engine.static_analysis_gate.scan_static_analysis_findings",
                        "retort_engine.swe_bench_oracle.build_issue_patch_benchmark",
                        "retort_engine.task_dispatch_plan.build_task_dispatch_plan",
                        "retort_engine.task_prioritization.build_task_prioritization_report",
                    ],
                    "all_before_failed_after_passed": True,
                    "all_direct_modules_executed": True,
                    "all_output_assertions_passed": True,
                    "independent_accepted_case_count": 10,
                },
                "cases": [],
                "evidence": {"claim_boundary": "direct_core_modules_not_pr_review_manifest"},
            }
        ),
        encoding="utf-8",
    )
    (docs / "retort_cross_domain_end_to_end.json").write_text(
        json.dumps(
            {
                "status": "ready",
                "summary": {
                    "linked_stage_count": 10,
                    "linked_domain_count": 10,
                    "linked_direct_module_count": 10,
                    "integrated_review_status": "reviewed",
                    "integrated_review_comment_count": 4,
                    "integrated_review_task_group_count": 2,
                    "all_stages_chained": True,
                    "all_stage_outputs_consumed": True,
                    "output_assertions_passed": True,
                },
                "stages": [],
                "review": {},
                "assertions": {},
                "artifacts": {},
                "evidence": {"integrated_runtime": "retort_engine.pr_review.review_diff"},
            }
        ),
        encoding="utf-8",
    )
    (docs / "retort_contract_runtime_rehearsal.json").write_text(
        json.dumps(
            {
                "status": "ready",
                "summary": {
                    "case_count": 3,
                    "ready_case_count": 3,
                    "violation_rejected_count": 3,
                    "rollback_verified_count": 3,
                    "valid_payload_accepted_count": 3,
                    "concurrent_worker_count": 6,
                    "concurrency_fault_injection_count": 18,
                    "concurrent_violation_rejected_count": 18,
                    "concurrent_rollback_verified_count": 18,
                    "all_violations_rejected": True,
                    "all_rollbacks_verified": True,
                    "all_concurrent_violations_rejected": True,
                    "all_concurrent_rollbacks_verified": True,
                },
                "cases": [],
                "evidence": {
                    "runtime_guard": "retort_engine.contracts.validate_contract",
                    "fault_injection_model": "threaded_invalid_payload_workers_with_per_worker_state_rollback",
                },
            }
        ),
        encoding="utf-8",
    )
    (docs / "retort_contract_stability_stress.json").write_text(
        json.dumps(
            {
                "status": "ready",
                "summary": {
                    "round_count": 2,
                    "ready_round_count": 2,
                    "concurrent_worker_count": 120,
                    "concurrency_floor_exceeded": True,
                    "total_fault_injection_count": 720,
                    "total_concurrent_violation_rejected_count": 720,
                    "total_concurrent_rollback_verified_count": 720,
                    "state_leak_count": 0,
                },
                "runs": [],
                "evidence": {"acceptance": ">100 concurrent workers across repeated rounds with zero state leaks"},
            }
        ),
        encoding="utf-8",
    )
    (docs / "retort_review_family_behavior_replay.json").write_text(
        json.dumps(
            {
                "status": "ready",
                "summary": {
                    "case_count": 3,
                    "ready_case_count": 3,
                    "language_families": ["python", "typescript"],
                    "typescript_case_count": 2,
                    "python_case_count": 1,
                    "all_direct_review_outputs_verified": True,
                    "publishable_case_count": 3,
                    "independent_accepted_case_count": 3,
                },
                "cases": [],
                "evidence": {"direct_runtime": "retort_engine.pr_review.review_diff"},
            }
        ),
        encoding="utf-8",
    )
    (docs / "retort_external_merge_landing.json").write_text(
        json.dumps(
            {
                "status": "ready",
                "summary": {
                    "case_count": 10,
                    "ready_case_count": 10,
                    "branch_diff_count": 10,
                    "merge_commit_count": 10,
                    "post_merge_test_passed_count": 10,
                    "all_branch_diff_merge_tests_passed": True,
                    "source_families": ["agentic_benchmark", "architecture_governance", "architecture_graph", "benchmark_harness", "context_packager", "go_ci_review_publisher", "python_pr_agent", "security_static_analysis", "typescript_pr_bot"],
                },
                "cases": [],
                "evidence": {"verifier": "git_branch_diff_plus_no_ff_merge_plus_post_merge_pytest"},
            }
        ),
        encoding="utf-8",
    )
    (docs / "retort_pr_readonly_degradation_probe.json").write_text(
        json.dumps(
            {
                "status": "read_only_degraded",
                "pr_url": "https://github.com/owner/repo/pull/7",
                "summary": {
                    "live_github_write": False,
                    "degraded_without_write": True,
                    "degradation_artifact_ready": True,
                },
                "evidence": {
                    "real_network": True,
                    "transport": "github_rest_readonly",
                    "degradation": "dry_run_review_payload_only_no_comment_created",
                },
                "created_receipts": [],
                "rollback_receipts": [],
            }
        ),
        encoding="utf-8",
    )
    (docs / "retort_review_adjudication_calibration.json").write_text(
        json.dumps(
            {
                "status": "ready",
                "summary": {
                    "human_label_count": 50,
                    "pass_rate": 0.98,
                    "pre_calibration_pass_rate": 0.62,
                    "post_calibration_pass_rate": 0.98,
                    "calibration_improvement_delta": 0.36,
                    "false_positive_count": 1,
                    "false_negative_count": 0,
                    "pre_calibration_false_positive_count": 5,
                    "pre_calibration_false_negative_count": 14,
                    "false_positive_reduction": 4,
                    "false_negative_reduction": 14,
                    "feedback_recalibration_applied": True,
                    "context_count": 5,
                },
                "cases": [],
                "evidence": {},
            }
        ),
        encoding="utf-8",
    )
    (docs / "retort_operator_journey_replay.json").write_text(
        json.dumps(
            {
                "status": "ready",
                "summary": {
                    "ready_stage_count": 9,
                    "stage_count": 9,
                    "hashed_artifact_count": 15,
                    "real_absorption_run_present": True,
                    "real_absorption_gates_passed": True,
                    "per_run_code_graph_proved": True,
                    "cross_domain_live_probe_ready": True,
                    "frontend_structure_ready": True,
                    "frontend_operation_replay_ready": True,
                    "architecture_contract_ready": True,
                    "codebase_graph_ready": True,
                    "external_advantage_ci_ready": True,
                    "contract_stability_ready": True,
                    "cross_domain_end_to_end_ready": True,
                    "manifest_path": ".retort/operator_journey_replays/run.manifest.json",
                    "single_command_surface": True,
                },
                "stages": [],
                "artifacts": [],
                "live_probes": {},
                "replay": {},
                "evidence": {},
            }
        ),
        encoding="utf-8",
    )
    (docs / "retort_pr_holdout_blind_eval.json").write_text(
        json.dumps(
            {
                "status": "ready",
                "summary": {
                    "target_pr_count": 20,
                    "reviewed_pr_count": 20,
                    "accepted_pr_count": 20,
                    "distinct_repo_count": 20,
                    "distinct_extension_count": 9,
                    "total_comment_count": 55,
                    "total_reviewed_new_change_count": 120,
                    "overlap_with_prior_long_run_count": 0,
                    "blind_against_prior_reports": True,
                    "holdout_label_count": 20,
                },
                "cases": [],
                "evidence": {},
            }
        ),
        encoding="utf-8",
    )
    (docs / "retort_pr_failure_rollback_replay.json").write_text(
        json.dumps(
            {
                "status": "ready",
                "summary": {
                    "target_case_count": 3,
                    "real_pr_reviewed_count": 3,
                    "failed_gate_count": 3,
                    "rollback_verified_count": 3,
                    "distinct_repo_count": 3,
                    "all_failures_rolled_back": True,
                    "uses_git_revert": True,
                },
                "cases": [],
                "evidence": {},
            }
        ),
        encoding="utf-8",
    )
    result_dir = tmp_path / ".retort" / "employee_results"
    result_dir.mkdir(parents=True)
    aggregate_result_path.write_text(
        json.dumps(
            {
                "execution_mode": "employee_runtime_worker_multi_process",
                "results": [{"task_id": "one"}],
                "runtime_evidence": {
                    "worker_review": {
                        "status": "reviewed",
                        "comment_count": 60,
                        "file_count": 45,
                        "task_group_count": 15,
                        "worker_review_count": 5,
                        "artifact": "review.json",
                    },
                    "multi_worker": {
                        "verified": True,
                        "worker_count": 5,
                        "independent_worker_count": 5,
                        "result_path_count": 5,
                        "process_isolation": {
                            "pid_isolation_verified": True,
                            "runtime_boundary_verified": True,
                            "unique_process_id_count": 5,
                            "worker_process_trace_count": 5,
                            "runtime_boundary_verified_count": 5,
                            "pid_cross_check_count": 5,
                            "crash_isolation_verified": True,
                            "crash_isolation_verified_count": 5,
                        },
                    },
                    "employee_patch_closure": {
                        "status": "ready",
                        "summary": {"success_case_verified": True, "failure_case_rolled_back": True},
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    (result_dir / "zz_scheduler_stress_worker.json").write_text(
        json.dumps(
            {
                "execution_mode": "employee_runtime_worker",
                "results": [{"task_id": "stress"}],
                "runtime_evidence": {
                    "worker_review": {"status": "reviewed", "comment_count": 2, "file_count": 1, "task_group_count": 1, "artifact": "stress_review.json"},
                },
            }
        ),
        encoding="utf-8",
    )

    evidence = llm_absorption_evidence(tmp_path)

    assert "absorption_source=https://github.com/owner/repo" in evidence
    assert f"external_materialized_path={external}; exists=True" in evidence
    assert "closed_loop_five_proofs_verified=True" in evidence
    assert "latest_absorption_source=https://github.com/owner/repo" in evidence
    assert "capability_absorption_local_score_removed=True" in evidence
    assert "capability_absorption_latest_scope=latest_real_absorption_run" in evidence
    assert not any(item.startswith("capability_absorption_score=") for item in evidence)
    assert not any(item.startswith("capability_absorption_cap=") for item in evidence)
    assert "behavior_test_function_count=1" in evidence
    assert "post_absorption_hardening_scope=latest_merge_commit_to_head" in evidence
    assert any(item.startswith("total_behavior_source_file_count=") for item in evidence)
    assert "external_snapshot_revision=abc123" in evidence
    assert "semantic_gap_count=1" in evidence
    assert "license_review_status=passed; detected=MIT; source_copy_allowed=True; pattern_absorption_allowed=True; isolation=license_gate_standard" in evidence
    assert "component_gap_count=1" in evidence
    assert "employee_result_count=1; execution_mode=employee_runtime_worker_multi_process" in evidence
    assert "employee_runtime_worker_review=reviewed; comments=60; artifact=review.json" in evidence
    assert "employee_runtime_worker_review_files=45; task_groups=15; worker_reviews=5" in evidence
    assert "employee_runtime_multi_worker_verified=True; workers=5; independent_workers=5; result_paths=5" in evidence
    assert "employee_worker_pid_isolation_verified=True" in evidence
    assert "employee_worker_runtime_boundary_verified=True" in evidence
    assert "employee_worker_unique_process_ids=5" in evidence
    assert "employee_worker_process_traces=5" in evidence
    assert "employee_worker_runtime_boundary_verified_count=5" in evidence
    assert "employee_worker_pid_cross_check_count=5" in evidence
    assert "employee_worker_crash_isolation_verified=True" in evidence
    assert "employee_worker_crash_isolation_verified_count=5" in evidence
    assert "employee_runtime_crash_isolation_verified=True; crash_verified=5" in evidence
    assert "employee_runtime_patch_closure=ready; success_case=True; rollback_case=True" in evidence
    assert "employee_patch_closure_status=ready" in evidence
    assert "employee_patch_closure_rollback_verified_count=4" in evidence
    assert "employee_patch_closure_primary_rollback_verified_count=2" in evidence
    assert "employee_patch_closure_rollback_scope=per_primary_case_failure_injection" in evidence
    assert "employee_patch_closure_failure_rehearsal_count=4" in evidence
    assert "employee_patch_closure_failure_rehearsal_rollback_count=4" in evidence
    assert "employee_patch_closure_full_path_rollback_verified=True" in evidence
    assert "employee_patch_closure_all_cases_have_failure_rollback_rehearsal=True" in evidence
    assert "employee_patch_closure_success_case_verified=True" in evidence
    assert "employee_patch_closure_failure_case_rolled_back=True" in evidence
    assert "employee_patch_closure_multi_file_case_verified=True" in evidence
    assert "employee_patch_closure_successful_repairs_re_reviewed=True" in evidence
    assert "employee_patch_closure_retry_case_verified=True" in evidence
    assert "quality_gate_bundle_status=ready" in evidence
    assert "quality_gate_bundle_all_passed=True" in evidence
    assert "quality_gate_bundle_test_density=True" in evidence
    assert "quality_gate_bundle_test_to_source_ratio=0.408" in evidence
    assert "quality_gate_bundle_test_density_target=0.6" in evidence
    assert "quality_gate_bundle_test_density_target_met=False" in evidence
    assert "quality_gate_bundle_test_density_missing_lines=3276" in evidence
    assert "quality_gate_bundle_source_lines=17083" in evidence
    assert "quality_gate_bundle_test_lines=6974" in evidence
    assert "quality_gate_bundle_contract=True" in evidence
    assert "review_adjudication_calibration_status=ready" in evidence
    assert "external_advantage_matrix_status=ready" in evidence
    assert "external_advantage_matrix_ready_cases=6/6" in evidence
    assert "external_advantage_matrix_source_projects=6" in evidence
    assert "external_advantage_matrix_absorbed_signals=6" in evidence
    assert "external_advantage_matrix_baseline_score=40" in evidence
    assert "external_advantage_matrix_retort_score=95" in evidence
    assert "external_advantage_matrix_score_delta=55" in evidence
    assert "external_advantage_matrix_behavior_delta_count=6" in evidence
    assert "external_advantage_matrix_publishable_cases=6" in evidence
    assert "external_advantage_matrix_extension_policy_cases=6" in evidence
    assert "external_advantage_matrix_per_case_before_after=True" in evidence
    assert "external_advantage_matrix_all_improved=True" in evidence
    assert "external_advantage_matrix_direct_regression_cases=6/6" in evidence
    assert "external_advantage_matrix_all_direct_execution=True" in evidence
    assert "external_advantage_matrix_regression_runtime=retort_engine.pr_review.review_diff" in evidence
    assert "external_advantage_matrix_regression_model=executable_input_output_diff_replay" in evidence
    assert "external_advantage_matrix_blind_third_party_status=ready" in evidence
    assert "external_advantage_matrix_blind_third_party_accepted=6/6" in evidence
    assert "external_advantage_matrix_blind_third_party_min_delta=65" in evidence
    assert "external_advantage_matrix_blind_third_party_delta_floor=True" in evidence
    assert "external_advantage_matrix_blind_third_party_score_fields_consumed=False" in evidence
    assert "external_advantage_matrix_blind_third_party_boundary=redacted_structural_facts_only_no_baseline_or_retort_score_fields" in evidence
    assert "external_advantage_ci_regression_status=ready" in evidence
    assert "external_advantage_ci_regression_cases=6/6" in evidence
    assert "external_advantage_ci_regression_min_blind_delta=80" in evidence
    assert "external_advantage_ci_regression_delta_floor_met=True" in evidence
    assert "external_advantage_ci_regression_all_direct_review=True" in evidence
    assert "external_advantage_ci_regression_all_ci_acceptance=True" in evidence
    assert "heterogeneous_absorption_replay_status=ready" in evidence
    assert "heterogeneous_absorption_replay_ready_cases=6/6" in evidence
    assert "heterogeneous_absorption_replay_cached_sources=6" in evidence
    assert "heterogeneous_absorption_replay_language_families=5" in evidence
    assert "heterogeneous_absorption_replay_language_family_list=go,jvm,python,rust,typescript" in evidence
    assert "heterogeneous_absorption_replay_before_after=True" in evidence
    assert "heterogeneous_absorption_replay_min_delta=70" in evidence
    assert "heterogeneous_absorption_replay_independent_adjudication=ready" in evidence
    assert "heterogeneous_absorption_replay_independent_accepted=6/6" in evidence
    assert "heterogeneous_absorption_replay_cross_language_verified=True" in evidence
    assert "cross_domain_absorption_replay_status=ready" in evidence
    assert "cross_domain_absorption_replay_ready_cases=10/10" in evidence
    assert "cross_domain_absorption_replay_non_pr_domains=10" in evidence
    assert "cross_domain_absorption_replay_before_after=True" in evidence
    assert "cross_domain_absorption_replay_direct_execution=True" in evidence
    assert "cross_domain_absorption_replay_output_assertions=True" in evidence
    assert "cross_domain_absorption_replay_claim_boundary=direct_core_modules_not_pr_review_manifest" in evidence
    assert "cross_domain_end_to_end_status=ready" in evidence
    assert "cross_domain_end_to_end_domains=10" in evidence
    assert "cross_domain_end_to_end_integrated_review=reviewed" in evidence
    assert "cross_domain_end_to_end_all_stages_chained=True" in evidence
    assert "cross_domain_end_to_end_all_outputs_consumed=True" in evidence
    assert "cross_domain_end_to_end_runtime=retort_engine.pr_review.review_diff" in evidence
    assert "contract_runtime_rehearsal_status=ready" in evidence
    assert "contract_runtime_rehearsal_ready_cases=3/3" in evidence
    assert "contract_runtime_rehearsal_violations_rejected=3" in evidence
    assert "contract_runtime_rehearsal_all_rollbacks=True" in evidence
    assert "contract_runtime_rehearsal_concurrent_workers=6" in evidence
    assert "contract_runtime_rehearsal_concurrency_faults=18" in evidence
    assert "contract_runtime_rehearsal_all_concurrent_rejected=True" in evidence
    assert "contract_runtime_rehearsal_all_concurrent_rollbacks=True" in evidence
    assert "contract_runtime_rehearsal_fault_model=threaded_invalid_payload_workers_with_per_worker_state_rollback" in evidence
    assert "contract_runtime_rehearsal_guard=retort_engine.contracts.validate_contract" in evidence
    assert "contract_stability_stress_status=ready" in evidence
    assert "contract_stability_stress_rounds=2/2" in evidence
    assert "contract_stability_stress_workers=120" in evidence
    assert "contract_stability_stress_faults=720" in evidence
    assert "contract_stability_stress_state_leaks=0" in evidence
    assert "review_family_behavior_replay_status=ready" in evidence
    assert "review_family_behavior_replay_ready_cases=3/3" in evidence
    assert "review_family_behavior_replay_language_families=python,typescript" in evidence
    assert "review_family_behavior_replay_typescript_cases=2" in evidence
    assert "review_family_behavior_replay_direct_outputs=True" in evidence
    assert "review_family_behavior_replay_runtime=retort_engine.pr_review.review_diff" in evidence
    assert "external_merge_landing_status=ready" in evidence
    assert "external_merge_landing_ready_cases=10/10" in evidence
    assert "external_merge_landing_branch_diffs=10" in evidence
    assert "external_merge_landing_merge_commits=10" in evidence
    assert "external_merge_landing_post_merge_tests=10" in evidence
    assert "external_merge_landing_all_passed=True" in evidence
    assert "external_merge_landing_verifier=git_branch_diff_plus_no_ff_merge_plus_post_merge_pytest" in evidence
    assert "pr_review_cross_language_transfer_source=True" in evidence
    assert "pr_review_cross_language_transfer_status=mapped" in evidence
    assert "pr_review_cross_language_transfer_core_mapping=True" in evidence
    assert "pr_review_hunk_semantic_status=active" in evidence
    assert "pr_review_hunk_semantic_findings=1" in evidence
    assert "pr_review_hunk_semantic_types=validation_regression" in evidence
    assert "pr_review_hunk_semantic_top_ranked=True" in evidence
    assert "pr_review_hunk_semantic_core_score_active=True" in evidence
    assert "review_adjudication_human_label_count=50" in evidence
    assert "review_adjudication_pass_rate=0.98" in evidence
    assert "review_adjudication_pre_calibration_pass_rate=0.62" in evidence
    assert "review_adjudication_post_calibration_pass_rate=0.98" in evidence
    assert "review_adjudication_improvement_delta=0.36" in evidence
    assert "review_adjudication_pre_false_positive_count=5" in evidence
    assert "review_adjudication_pre_false_negative_count=14" in evidence
    assert "review_adjudication_false_positive_reduction=4" in evidence
    assert "review_adjudication_false_negative_reduction=14" in evidence
    assert "review_adjudication_feedback_recalibration_applied=True" in evidence
    assert "pr_holdout_blind_eval_status=ready" in evidence
    assert "pr_holdout_blind_eval_reviewed=20/20" in evidence
    assert "pr_holdout_blind_eval_accepted=20/20" in evidence
    assert "pr_holdout_blind_eval_blind_prior=True" in evidence
    assert "pr_failure_rollback_replay_status=ready" in evidence
    assert "pr_failure_rollback_replay_real_reviewed=3/3" in evidence
    assert "pr_failure_rollback_replay_rolled_back=3/3" in evidence
    assert "pr_failure_rollback_replay_uses_git_revert=True" in evidence
    assert "merge_cross_check=True" in evidence
    assert "pr_live_publish_probe_status=permission_denied_degraded" in evidence
    assert "pr_live_publish_probe_permission_denied=True" in evidence
    assert "pr_live_publish_probe_degraded_without_write=True" in evidence
    assert "pr_live_publish_probe_real_network=False" in evidence
    assert "pr_live_publish_probe_transport=injected_transport" in evidence
    assert "pr_live_publish_probe_required_permission=issues:write or pull_requests:write" in evidence
    assert "pr_live_publish_probe_degradation=no_comment_created_no_rollback_needed" in evidence
    assert "pr_low_permission_probe_status=permission_denied_degraded" in evidence
    assert "pr_low_permission_probe_live_write=False" in evidence
    assert "pr_low_permission_probe_permission_denied=True" in evidence
    assert "pr_low_permission_probe_degraded_without_write=True" in evidence
    assert "pr_low_permission_probe_real_network=False" in evidence
    assert "pr_low_permission_probe_transport=injected_transport" in evidence
    assert "pr_readonly_degradation_probe_status=read_only_degraded" in evidence
    assert "pr_readonly_degradation_probe_real_network=True" in evidence
    assert "pr_readonly_degradation_probe_artifact_ready=True" in evidence
    assert "operator_journey_replay_status=ready" in evidence
    assert "operator_journey_replay_ready_stages=9/9" in evidence
    assert "operator_journey_replay_cross_domain_ready=True" in evidence
    assert "operator_journey_replay_frontend_operation_replay_ready=True" in evidence
    assert "operator_journey_replay_single_command=True" in evidence


def test_llm_absorption_evidence_read_json_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")

    assert read_json(path) == {}


def test_llm_absorption_evidence_includes_extension_policy_runtime_signals(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "retort_engine.llm_absorption_evidence.pr_review_runtime_evidence",
        lambda project: {
            "runtime": True,
            "cli": True,
            "api": True,
            "contract": True,
            "test_function_count": 12,
            "sample_comment_count": 3,
            "publishable_comment_count": 3,
            "comment_ranking_model": "severity_context_publishability_v1",
            "extension_policy_known_count": 9,
            "extension_policy_unknown_count": 0,
            "extension_policy_language_family_count": 8,
            "extension_policy_review_context_count": 5,
            "extension_policy_review_contexts": ["ci_config", "config", "docs", "frontend", "runtime"],
            "extension_policy_language_families": ["cpp", "dotnet", "go", "rust", "typescript"],
            "extension_policy_source": "retort_holdout_extension_policy_v1",
        },
    )

    evidence = llm_absorption_evidence(tmp_path)

    assert "pr_review_extension_policy_known=9" in evidence
    assert "pr_review_extension_policy_unknown=0" in evidence
    assert "pr_review_extension_policy_language_family_count=8" in evidence
    assert "pr_review_extension_policy_review_context_count=5" in evidence
    assert "pr_review_extension_policy_review_contexts=ci_config,config,docs,frontend,runtime" in evidence
    assert "pr_review_extension_policy_language_families=cpp,dotnet,go,rust,typescript" in evidence
    assert "pr_review_extension_policy_source=retort_holdout_extension_policy_v1" in evidence
