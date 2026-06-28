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
        "absorption_release_decision_operator_journey_ready=True",
        "release_decision_self_reference=False",
    ]

    selected = prioritized_evidence(evidence)

    assert "operator_journey_replay_status=ready" in selected
    assert "operator_journey_replay_ready_stages=8/8" in selected
    assert "absorption_release_decision_operator_journey_ready=True" in selected
    assert "release_decision_self_reference=False" in selected
