from __future__ import annotations

from pathlib import Path

from retort_engine.devour_session import assessment_file_count, assessment_score, build_devour_session


def test_devour_session_keeps_flow_panels_and_improvement_proof() -> None:
    own_before = {"project": "own", "scores": [], "evidence": ["source_files=3"], "metadata": {"score_source": "paibi_llm_pending"}}
    external = {"project": "external", "scores": [], "evidence": ["source_files=5"], "metadata": {"score_source": "external_evidence_only"}}
    own_after = {
        "project": "own",
        "scores": [{"dimension": "calibrated_overall", "value": 82}],
        "evidence": ["source_files=4"],
        "metadata": {"score_source": "paibi_llm", "capability_absorption_audit": {"behavior_source_files": ["retort_engine/a.py"], "behavior_test_files": ["tests/test_a.py"], "blockers": []}},
    }

    session = build_devour_session(
        source="https://github.com/example/repo",
        external_path=Path("/tmp/external"),
        pre_assessment=own_before,
        external_assessment=external,
        own_assessment=own_after,
        tasks=[{"title": "Absorb benchmark", "dimension": "feedback_loop_closure", "priority": "P1", "why": "benchmark"}],
        execution={"status": "applied", "summary": "ok", "changed_files": ["retort_engine/a.py"], "gates": [{"ok": True}], "gates_passed": True},
        branch_state={"status": "merged"},
        absorption_state={"closed_loop_proof": {"flags": {"branch_diff_verified": True, "employee_execution_verified": True}, "missing": []}},
        llm_review={"dispatch": {"status": "accepted", "task_id": "task-1"}},
        external_project_profile=lambda _path: {"benchmarking": True, "review_pipeline": False, "file_grouping": False, "plugin_surface": False},
    )

    assert session["status"] == "final_deep_review_scored"
    assert session["stage_order"] == ["pre_dual_review", "overlap_comparison", "absorption_execution", "improvement_proof", "final_self_review"]
    assert session["pre_dual_review"]["panels"][1]["score_status"] == "external_evidence_collected_needs_llm"
    assert session["overlap_comparison"]["external_depth_signals"] == ["质量基准"]
    assert session["improvement_proof"]["gate_passed_count"] == 1
    assert session["final_self_review"]["score"] == 82.0


def test_assessment_score_prefers_calibrated_overall_and_file_count_evidence() -> None:
    assessment = {"scores": [{"dimension": "product_level", "value": 80}, {"dimension": "calibrated_overall", "value": 77.4}], "evidence": ["source_files=12"]}

    assert assessment_score(assessment) == 77.4
    assert assessment_file_count(assessment) == 12
