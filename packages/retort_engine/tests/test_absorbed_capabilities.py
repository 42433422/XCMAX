from __future__ import annotations

from retort_engine.absorbed_capabilities import absorbed_capability_plan, capability_progress_from_execution, explain_missing_absorption_evidence, ranked_capabilities

EXPECTED_ABSORPTION_SOURCE = 'https://github.com/sourcefuse/ai-pr-reviewer'


def test_absorbed_capability_plan_has_ranked_behavior_signals() -> None:
    plan = absorbed_capability_plan()
    assert plan["run_id"]
    assert plan["source"] == EXPECTED_ABSORPTION_SOURCE
    assert isinstance(plan["tasks"], list)
    assert plan["minimum_behavior_tests"] >= 3
    assert ranked_capabilities()


def test_capability_progress_requires_behavior_code_tests_and_gates() -> None:
    progress = capability_progress_from_execution(
        ["retort_engine/absorbed_capabilities.py", "tests/test_absorbed_capabilities.py"],
        [{"ok": True}, {"ok": True}],
    )
    assert progress["ready_for_90"] is True


def test_missing_absorption_evidence_blocks_report_only_runs() -> None:
    missing = explain_missing_absorption_evidence(["docs/retort_absorption_log.md"], [{"ok": True}])
    assert "missing_behavior_source_diff" in missing
    assert "missing_behavior_test_diff" in missing
