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
    test.write_text("def test_feature():\n    assert True\n", encoding="utf-8")
    run_dir = tmp_path / ".retort" / "real_absorption_runs"
    run_dir.mkdir(parents=True)
    (run_dir / "run.json").write_text(
        json.dumps({"source": "https://github.com/owner/repo", "changed_files": [str(source), str(test)]}),
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
                    "rollback_verified_count": 2,
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
                },
                "matrix": [],
                "evidence": {},
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
                    "false_positive_count": 1,
                    "false_negative_count": 0,
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
                    "ready_stage_count": 8,
                    "stage_count": 8,
                    "hashed_artifact_count": 15,
                    "real_absorption_run_present": True,
                    "real_absorption_gates_passed": True,
                    "per_run_code_graph_proved": True,
                    "cross_domain_live_probe_ready": True,
                    "frontend_structure_ready": True,
                    "architecture_contract_ready": True,
                    "codebase_graph_ready": True,
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
    (result_dir / "result.json").write_text(
        json.dumps(
            {
                "execution_mode": "employee_runtime_worker",
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
                    "multi_worker": {"verified": True, "worker_count": 5, "independent_worker_count": 5, "result_path_count": 5},
                    "employee_patch_closure": {
                        "status": "ready",
                        "summary": {"success_case_verified": True, "failure_case_rolled_back": True},
                    },
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
    assert "employee_result_count=1; execution_mode=employee_runtime_worker" in evidence
    assert "employee_runtime_worker_review=reviewed; comments=60; artifact=review.json" in evidence
    assert "employee_runtime_worker_review_files=45; task_groups=15; worker_reviews=5" in evidence
    assert "employee_runtime_multi_worker_verified=True; workers=5; independent_workers=5; result_paths=5" in evidence
    assert "employee_runtime_patch_closure=ready; success_case=True; rollback_case=True" in evidence
    assert "employee_patch_closure_status=ready" in evidence
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
    assert "review_adjudication_human_label_count=50" in evidence
    assert "review_adjudication_pass_rate=0.98" in evidence
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
    assert "operator_journey_replay_ready_stages=8/8" in evidence
    assert "operator_journey_replay_cross_domain_ready=True" in evidence
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
