from __future__ import annotations

from pathlib import Path

from retort_engine.paibi_prompting import RETORT_SCORE_DIMENSIONS, build_retort_paibi_panel_prompt, build_retort_paibi_prompt, prioritized_evidence, scoring_audit


def test_prompting_keeps_local_audit_as_risk_signal_not_score(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# Retort\n", encoding="utf-8")
    prompt = build_retort_paibi_prompt(
        project=tmp_path,
        mode="assess",
        evidence=["core_refactor_execution_status=implemented"],
        metadata={"capability_absorption_audit": {"score": 96, "overall_cap": 97, "blockers": ["low_test_to_source_ratio"]}},
    )

    assert "core_refactor_execution_status=implemented" in prompt
    assert "不得把本地能力吸收审计当作参考分" in prompt
    audit = scoring_audit({"capability_absorption_audit": {"score": 96, "overall_cap": 97, "blockers": []}})
    assert "score" not in audit["capability_absorption_audit"]
    assert "overall_cap" not in audit["capability_absorption_audit"]


def test_panel_prompt_wraps_base_prompt_with_panel_contract(tmp_path: Path) -> None:
    prompt = build_retort_paibi_panel_prompt(
        project=tmp_path,
        mode="parallel_assess",
        panel_id="capability_absorption",
        panel_title="能力吸收评审",
        focus="只看核心行为和测试",
    )

    assert 'panel_id": "capability_absorption"' in prompt
    assert "unblock_tasks" in prompt
    assert "只看核心行为和测试" in prompt


def test_score_dimensions_include_calibrated_overall_and_capability_absorption() -> None:
    assert "capability_absorption_score" in RETORT_SCORE_DIMENSIONS
    assert "calibrated_overall" in RETORT_SCORE_DIMENSIONS


def test_operator_journey_evidence_is_prioritized_for_deep_review() -> None:
    evidence = [
        "unimportant=1",
        *[f"pr_holdout_blind_eval_total_comments={index}" for index in range(100)],
        "operator_journey_replay_status=ready",
        "operator_journey_replay_ready_stages=8/8",
        "operator_journey_replay_frontend_operation_replay_ready=True",
        "absorption_release_decision_operator_journey_ready=True",
        "external_advantage_matrix_score_delta=55",
        "external_advantage_matrix_blind_third_party_min_delta=65",
        "external_advantage_matrix_per_case_before_after=True",
        "cross_domain_absorption_replay_output_assertions=True",
        "contract_runtime_rehearsal_all_rollbacks=True",
        "employee_patch_stress_concurrent_workers=120",
        "employee_patch_stress_all_rollbacks=True",
        "employee_scheduler_stress_unique_process_ids=30",
        "absorption_state_closed_loop_completed_by_design=True",
        "absorption_continuity_ready_runs=5/5",
        "product_mainline_absorption_merge_commit=True",
        "upstream_pr_ci_probe_multi_repo_generalization=True",
        "competitor_blind_adjudication_status=ready",
        "competitor_blind_adjudication_imports_retort=False",
        "competitor_behavior_regression_status=ready",
        "competitor_behavior_regression_all_signals=True",
        "cross_domain_ci_regression_rounds=3/3",
        "review_family_behavior_replay_direct_outputs=True",
        "release_decision_self_reference=False",
    ]

    selected = prioritized_evidence(evidence)

    assert "operator_journey_replay_status=ready" in selected
    assert "operator_journey_replay_ready_stages=8/8" in selected
    assert "operator_journey_replay_frontend_operation_replay_ready=True" in selected
    assert "absorption_release_decision_operator_journey_ready=True" in selected
    assert "external_advantage_matrix_score_delta=55" in selected
    assert "external_advantage_matrix_blind_third_party_min_delta=65" in selected
    assert "external_advantage_matrix_per_case_before_after=True" in selected
    assert "cross_domain_absorption_replay_output_assertions=True" in selected
    assert "contract_runtime_rehearsal_all_rollbacks=True" in selected
    assert "employee_patch_stress_concurrent_workers=120" in selected
    assert "employee_patch_stress_all_rollbacks=True" in selected
    assert "employee_scheduler_stress_unique_process_ids=30" in selected
    assert "absorption_state_closed_loop_completed_by_design=True" in selected
    assert "absorption_continuity_ready_runs=5/5" in selected
    assert "product_mainline_absorption_merge_commit=True" in selected
    assert "upstream_pr_ci_probe_multi_repo_generalization=True" in selected
    assert "competitor_blind_adjudication_status=ready" in selected
    assert "competitor_blind_adjudication_imports_retort=False" in selected
    assert "competitor_behavior_regression_status=ready" in selected
    assert "competitor_behavior_regression_all_signals=True" in selected
    assert "cross_domain_ci_regression_rounds=3/3" in selected
    assert "review_family_behavior_replay_direct_outputs=True" in selected
    assert "release_decision_self_reference=False" in selected


def test_prompt_stays_compact_with_large_evidence_input(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# Retort\n", encoding="utf-8")
    evidence = [
        *[f"pr_holdout_blind_eval_total_comments={index}" for index in range(180)],
        "operator_journey_replay_status=ready",
        "operator_journey_replay_ready_stages=8/8",
        "absorption_release_decision_operator_journey_ready=True",
        "external_advantage_matrix_score_delta=55",
        "cross_domain_absorption_replay_direct_execution=True",
        "contract_runtime_rehearsal_all_rejected=True",
        "employee_patch_stress_state_leaks=0",
        "review_family_behavior_replay_runtime=retort_engine.pr_review.review_diff",
    ]

    prompt = build_retort_paibi_prompt(project=tmp_path, mode="assess", evidence=evidence)

    assert len(prompt) < 32000
    assert "operator_journey_replay_status=ready" in prompt
    assert "operator_journey_replay_ready_stages=8/8" in prompt
    assert "external_advantage_matrix_score_delta=55" in prompt
    assert "cross_domain_absorption_replay_direct_execution=True" in prompt
    assert "contract_runtime_rehearsal_all_rejected=True" in prompt
    assert "employee_patch_stress_state_leaks=0" in prompt
    assert "review_family_behavior_replay_runtime=retort_engine.pr_review.review_diff" in prompt
    assert "pr_holdout_blind_eval_total_comments=179" not in prompt
