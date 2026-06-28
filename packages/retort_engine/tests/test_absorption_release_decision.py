from __future__ import annotations

import json
from pathlib import Path

from retort_engine.absorption_release_decision import build_absorption_release_decision
from retort_engine.contracts import validate_contract
from retort_engine.service import RetortService


def test_absorption_release_decision_combines_core_product_gates(tmp_path: Path) -> None:
    _write_decision_inputs(tmp_path)

    result = build_absorption_release_decision(tmp_path)

    assert result["status"] == "ready"
    assert result["summary"]["ready_decision_count"] == 26
    assert result["summary"]["core_decision_path_count"] == 12
    assert result["summary"]["all_core_decisions_ready"] is True
    assert result["summary"]["product_mainline_absorption_ready"] is True
    assert result["summary"]["holdout_blind_eval_ready"] is True
    assert result["summary"]["external_advantage_matrix_ready"] is True
    assert result["summary"]["external_advantage_ci_regression_ready"] is True
    assert result["summary"]["external_process_adjudication_ready"] is True
    assert result["summary"]["external_advantage_repeat_ready"] is True
    assert result["summary"]["upstream_pr_ci_ready"] is True
    assert result["summary"]["competitor_runtime_ready"] is True
    assert result["summary"]["competitor_blind_adjudication_ready"] is True
    assert result["summary"]["competitor_behavior_regression_ready"] is True
    assert result["summary"]["heterogeneous_absorption_ready"] is True
    assert result["summary"]["cross_domain_absorption_ready"] is True
    assert result["summary"]["cross_domain_end_to_end_ready"] is True
    assert result["summary"]["cross_domain_ci_regression_ready"] is True
    assert result["summary"]["contract_runtime_rehearsal_ready"] is True
    assert result["summary"]["contract_stability_stress_ready"] is True
    assert result["summary"]["employee_patch_stress_ready"] is True
    assert result["summary"]["employee_scheduler_stress_ready"] is True
    assert result["summary"]["review_family_behavior_ready"] is True
    assert result["summary"]["external_merge_landing_ready"] is True
    assert result["summary"]["failure_rollback_ready"] is True
    assert result["summary"]["operator_journey_ready"] is True
    assert validate_contract("absorption_release_decision_result", result)["valid"] is True


def test_service_exposes_absorption_release_decision(tmp_path: Path) -> None:
    _write_decision_inputs(tmp_path)

    result = RetortService().absorption_release_decision({"project": str(tmp_path)})

    assert result["status"] == "ready"


def test_absorption_release_decision_blocks_without_holdout_quality(tmp_path: Path) -> None:
    _write_decision_inputs(tmp_path)
    (tmp_path / "docs" / "retort_pr_holdout_blind_eval.json").unlink()

    result = build_absorption_release_decision(tmp_path)

    assert result["status"] == "blocked"
    assert result["summary"]["holdout_blind_eval_ready"] is False
    assert result["summary"]["blocking_decision_count"] == 1
    assert any(decision["name"] == "accept_blind_holdout_quality" and decision["action"] == "block" for decision in result["decisions"])


def test_absorption_release_decision_blocks_without_operator_journey(tmp_path: Path) -> None:
    _write_decision_inputs(tmp_path)
    (tmp_path / "docs" / "retort_operator_journey_replay.json").unlink()

    result = build_absorption_release_decision(tmp_path)

    assert result["status"] == "blocked"
    assert result["summary"]["operator_journey_ready"] is False
    assert result["summary"]["blocking_decision_count"] == 1
    assert any(decision["name"] == "replay_operator_absorption_journey" and decision["action"] == "block" for decision in result["decisions"])


def test_absorption_release_decision_blocks_without_external_advantage_matrix(tmp_path: Path) -> None:
    _write_decision_inputs(tmp_path)
    (tmp_path / "docs" / "retort_external_advantage_matrix.json").unlink()

    result = build_absorption_release_decision(tmp_path)

    assert result["status"] == "blocked"
    assert result["summary"]["external_advantage_matrix_ready"] is False
    assert result["summary"]["blocking_decision_count"] == 1
    assert any(decision["name"] == "prove_external_advantage_matrix" and decision["action"] == "block" for decision in result["decisions"])


def test_absorption_release_decision_blocks_without_heterogeneous_replay(tmp_path: Path) -> None:
    _write_decision_inputs(tmp_path)
    (tmp_path / "docs" / "retort_heterogeneous_absorption_replay.json").unlink()

    result = build_absorption_release_decision(tmp_path)

    assert result["status"] == "blocked"
    assert result["summary"]["heterogeneous_absorption_ready"] is False
    assert result["summary"]["blocking_decision_count"] == 1
    assert any(decision["name"] == "prove_heterogeneous_absorption" and decision["action"] == "block" for decision in result["decisions"])


def test_absorption_release_decision_blocks_without_cross_domain_replay(tmp_path: Path) -> None:
    _write_decision_inputs(tmp_path)
    (tmp_path / "docs" / "retort_cross_domain_absorption_replay.json").unlink()

    result = build_absorption_release_decision(tmp_path)

    assert result["status"] == "blocked"
    assert result["summary"]["cross_domain_absorption_ready"] is False
    assert result["summary"]["blocking_decision_count"] == 1
    assert any(decision["name"] == "prove_non_pr_cross_domain_absorption" and decision["action"] == "block" for decision in result["decisions"])


def test_absorption_release_decision_blocks_without_external_merge_landing(tmp_path: Path) -> None:
    _write_decision_inputs(tmp_path)
    (tmp_path / "docs" / "retort_external_merge_landing.json").unlink()

    result = build_absorption_release_decision(tmp_path)

    assert result["status"] == "blocked"
    assert result["summary"]["external_merge_landing_ready"] is False
    assert result["summary"]["blocking_decision_count"] == 1
    assert any(decision["name"] == "prove_external_merge_landing" and decision["action"] == "block" for decision in result["decisions"])


def test_absorption_release_decision_blocks_without_contract_runtime_rehearsal(tmp_path: Path) -> None:
    _write_decision_inputs(tmp_path)
    (tmp_path / "docs" / "retort_contract_runtime_rehearsal.json").unlink()

    result = build_absorption_release_decision(tmp_path)

    assert result["status"] == "blocked"
    assert result["summary"]["contract_runtime_rehearsal_ready"] is False
    assert result["summary"]["blocking_decision_count"] == 1
    assert any(decision["name"] == "reject_contract_runtime_violations" and decision["action"] == "block" for decision in result["decisions"])


def test_absorption_release_decision_blocks_without_review_family_behavior(tmp_path: Path) -> None:
    _write_decision_inputs(tmp_path)
    (tmp_path / "docs" / "retort_review_family_behavior_replay.json").unlink()

    result = build_absorption_release_decision(tmp_path)

    assert result["status"] == "blocked"
    assert result["summary"]["review_family_behavior_ready"] is False
    assert result["summary"]["blocking_decision_count"] == 1
    assert any(decision["name"] == "prove_review_family_core_behavior" and decision["action"] == "block" for decision in result["decisions"])


def _write_decision_inputs(root: Path) -> None:
    docs = root / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    fixtures = {
        "retort_quality_gate_bundle.json": {"status": "ready", "summary": {"all_gates_passed": True}},
        "retort_absorption_continuity_probe.json": {"status": "ready", "summary": {}},
        "retort_pr_long_run_review.json": {"status": "ready", "summary": {}},
        "retort_pr_holdout_blind_eval.json": {"status": "ready", "summary": {"accepted_pr_count": 20, "target_pr_count": 20}},
        "retort_pr_failure_rollback_replay.json": {"status": "ready", "summary": {"all_failures_rolled_back": True}},
        "retort_production_recovery_drill.json": {"status": "ready", "summary": {}},
        "retort_product_mainline_absorption_proof.json": {
            "status": "ready",
            "summary": {
                "is_merge_commit": True,
                "behavior_source_changed_count": 2,
                "behavior_test_changed_count": 2,
                "post_merge_quality_gate_passed": True,
            },
        },
        "retort_employee_patch_closure.json": {"status": "ready", "summary": {"all_expected_outcomes_verified": True}},
        "retort_employee_patch_stress.json": {
            "status": "ready",
            "summary": {
                "concurrency_floor_exceeded": True,
                "worker_count": 120,
                "rollback_verified_count": 120,
                "all_post_rollback_gates_passed": True,
            },
        },
        "retort_employee_scheduler_stress.json": {
            "status": "ready",
            "summary": {
                "unique_successful_process_id_count": 30,
                "queued_task_count": 30,
                "pid_isolation_verified": True,
                "queue_result_history_consistent": True,
            },
        },
        "retort_review_quality_benchmark.json": {"status": "ready", "summary": {"post_absorption_score_delta": 10}},
        "retort_external_advantage_matrix.json": {
            "status": "ready",
            "summary": {"score_delta": 50, "blind_third_party_all_cases_accepted": True, "blind_third_party_minimum_delta": 65},
        },
        "retort_external_advantage_ci_regression.json": {
            "status": "ready",
            "summary": {
                "passed_case_count": 6,
                "case_count": 6,
                "all_cases_have_ci_acceptance": True,
                "all_direct_review_regressions_verified": True,
                "blind_third_party_minimum_delta": 80,
            },
        },
        "retort_external_process_adjudication.json": {
            "status": "ready",
            "summary": {
                "external_all_cases_accepted": True,
                "script_imports_retort_engine": False,
                "external_minimum_delta": 80,
            },
        },
        "retort_external_advantage_repeat.json": {"status": "ready", "summary": {"stable_case_set": True, "stable_score_delta": True, "total_case_evaluation_count": 12}},
        "retort_upstream_pr_ci_probe.json": {
            "status": "ready",
            "summary": {
                "merged": True,
                "all_check_runs_successful": True,
                "check_run_count": 34,
                "multi_repo_ci_generalization": True,
                "distinct_repo_count": 3,
                "ready_target_count": 3,
                "target_count": 3,
                "all_target_check_runs_successful": True,
                "total_check_run_count": 71,
            },
        },
        "retort_competitor_runtime_comparison.json": {
            "status": "ready",
            "summary": {
                "side_by_side_output_materialized": True,
                "multi_competitor_side_by_side": True,
                "ready_competitor_project_count": 3,
                "competitor_project_count": 3,
                "all_external_processes_successful": True,
                "all_live_upstream_sources_verified": True,
                "all_live_upstream_sources_materialized": True,
                "live_upstream_verified_count": 3,
                "retort_exceeds_patch_parser_by_semantic_comments": True,
            },
        },
        "retort_competitor_blind_adjudication.json": {
            "status": "ready",
            "summary": {
                "all_competitors_blind_accepted": True,
                "accepted_competitor_count": 3,
                "competitor_count": 3,
                "minimum_blind_delta": 56,
                "script_imports_retort_engine": False,
                "input_contains_score_fields": False,
            },
        },
        "retort_competitor_behavior_regression.json": {
            "status": "ready",
            "summary": {
                "all_competitor_signals_regressed": True,
                "all_cases_direct_review_execution": True,
                "ready_case_count": 3,
                "behavior_assertion_count": 18,
            },
        },
        "retort_heterogeneous_absorption_replay.json": {
            "status": "ready",
            "summary": {"all_before_failed_after_passed": True, "cross_language_absorption_verified": True, "language_family_count": 5},
        },
        "retort_cross_domain_absorption_replay.json": {
            "status": "ready",
            "summary": {
                "all_before_failed_after_passed": True,
                "all_output_assertions_passed": True,
                "non_pr_domain_count": 10,
                "direct_module_count": 10,
            },
        },
        "retort_cross_domain_end_to_end.json": {
            "status": "ready",
            "summary": {
                "linked_domain_count": 10,
                "all_stages_chained": True,
                "all_stage_outputs_consumed": True,
                "integrated_review_status": "reviewed",
            },
        },
        "retort_cross_domain_ci_regression.json": {
            "status": "ready",
            "summary": {
                "ready_round_count": 3,
                "round_count": 3,
                "all_output_assertions_passed": True,
                "stable_domain_count": True,
                "total_domain_replay_count": 30,
            },
        },
        "retort_contract_runtime_rehearsal.json": {
            "status": "ready",
            "summary": {
                "all_violations_rejected": True,
                "all_rollbacks_verified": True,
                "all_concurrent_violations_rejected": True,
                "all_concurrent_rollbacks_verified": True,
                "violation_rejected_count": 3,
                "concurrent_violation_rejected_count": 360,
            },
        },
        "retort_contract_stability_stress.json": {
            "status": "ready",
            "summary": {
                "concurrent_worker_count": 120,
                "concurrency_floor_exceeded": True,
                "total_fault_injection_count": 720,
                "state_leak_count": 0,
            },
        },
        "retort_review_family_behavior_replay.json": {
            "status": "ready",
            "summary": {"all_direct_review_outputs_verified": True, "independent_all_cases_accepted": True, "typescript_case_count": 2, "python_case_count": 1},
        },
        "retort_external_merge_landing.json": {
            "status": "ready",
            "summary": {"all_branch_diff_merge_tests_passed": True, "merge_commit_count": 10, "post_merge_test_passed_count": 10},
        },
        "retort_operator_journey_replay.json": {"status": "ready", "summary": {"cross_domain_live_probe_ready": True}},
    }
    for name, payload in fixtures.items():
        (docs / name).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
