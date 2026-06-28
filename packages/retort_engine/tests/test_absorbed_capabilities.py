from __future__ import annotations

from retort_engine.absorbed_capabilities import absorbed_capability_plan, absorption_quality_gate, advantage_diff_map, capability_progress_from_execution, deferred_breadth_queue, depth_absorption_plan, depth_first_task_queue, explain_missing_absorption_evidence, marketplace_candidate_queue, multi_project_reproduction_index, ranked_capabilities, review_strategy_for_file

EXPECTED_ABSORPTION_SOURCE = 'https://github.com/UllrAI/Vibe-PR-Reviewer'


def test_absorbed_capability_plan_has_ranked_behavior_signals() -> None:
    plan = absorbed_capability_plan()
    assert plan["run_id"]
    assert plan["source"] == EXPECTED_ABSORPTION_SOURCE
    assert isinstance(plan["tasks"], list)
    assert plan["minimum_behavior_tests"] >= 3
    assert ranked_capabilities()
    assert plan["depth_absorption_plan"]["focus_mode"] == "similar_function_depth_only"


def test_depth_absorption_plan_keeps_depth_before_breadth() -> None:
    workflow = depth_absorption_plan()
    focused_components = {item["component"] for item in workflow["focused_components"]}
    assert workflow["quality_gate"]["passed"] is True
    assert focused_components
    assert not (focused_components & {"provider_surface", "plugin_surface"})
    assert workflow["breadth_rejected"]
    assert all(task["acceptance"] and task["evidence_required"] for task in depth_first_task_queue())


def test_breadth_candidates_stay_closed_until_similarity_saturation() -> None:
    assert marketplace_candidate_queue() == []
    deferred = deferred_breadth_queue()
    assert deferred
    assert all(item["status"] == "closed_until_similarity_saturation" for item in deferred)
    assert all(item["next_open_condition"] for item in deferred)


def test_capability_progress_requires_behavior_code_tests_and_gates() -> None:
    progress = capability_progress_from_execution(
        ["retort_engine/review_context_bias.py", "tests/test_review_context_bias.py"],
        [{"ok": True}, {"ok": True}],
    )
    assert progress["ready_for_90"] is True
    assert progress["behavior_source_files"] == ["retort_engine/review_context_bias.py"]
    assert progress["behavior_test_files"] == ["tests/test_review_context_bias.py"]


def test_capability_progress_rejects_registry_only_absorption() -> None:
    progress = capability_progress_from_execution(
        ["retort_engine/absorbed_capabilities.py", "tests/test_absorbed_capabilities.py"],
        [{"ok": True}, {"ok": True}],
    )

    assert progress["ready_for_90"] is False
    assert progress["behavior_source_files"] == []
    assert progress["behavior_test_files"] == []
    assert progress["generated_evidence_files"] == ["retort_engine/absorbed_capabilities.py", "tests/test_absorbed_capabilities.py"]


def test_missing_absorption_evidence_blocks_report_only_runs() -> None:
    missing = explain_missing_absorption_evidence(["docs/retort_absorption_log.md"], [{"ok": True}])
    assert "missing_behavior_source_diff" in missing
    assert "missing_behavior_test_diff" in missing


def test_advantage_diff_map_points_to_behavior_files() -> None:
    rows = advantage_diff_map(["retort_engine/pr_review.py", "tests/test_pr_review.py"])
    assert rows
    assert any(row["has_behavior_diff"] for row in rows)


def test_advantage_diff_map_ignores_registry_files() -> None:
    rows = advantage_diff_map(["retort_engine/absorbed_capabilities.py", "tests/test_absorbed_capabilities.py"])
    assert rows
    assert not any(row["has_behavior_diff"] for row in rows)


def test_absorption_quality_gate_blocks_too_few_behavior_tests() -> None:
    gate = absorption_quality_gate(
        ["retort_engine/review_context_bias.py", "tests/test_review_context_bias.py"],
        [{"ok": True, "command": ["pytest", "tests/test_review_context_bias.py"], "stdout_tail": "3 passed"}],
        minimum_behavior_tests=5,
    )
    assert gate["passed"] is False
    assert "insufficient_behavior_test_count" in gate["missing"]


def test_absorption_quality_gate_passes_with_behavior_depth() -> None:
    gate = absorption_quality_gate(
        ["retort_engine/pr_review.py", "tests/test_pr_review.py", "retort_engine/review_context_bias.py", "tests/test_review_context_bias.py"],
        [
            {"ok": True, "command": ["pytest", "tests/test_pr_review.py"], "stdout_tail": "8 passed"},
            {"ok": True, "command": ["pytest", "tests/test_review_context_bias.py"], "stdout_tail": "1 passed"},
        ],
        minimum_behavior_tests=1,
    )
    assert gate["passed"] is True


def test_review_strategy_for_source_file_uses_absorbed_capabilities() -> None:
    strategy = review_strategy_for_file("src/review.ts")
    assert strategy["strategy"] in {"diff_hunk_review", "semantic_review"}
    assert strategy["capabilities"]


def test_multi_project_reproduction_index_requires_three_sources() -> None:
    index = multi_project_reproduction_index(["a", "b", "a", "c"])
    assert index["unique_source_count"] == 3
    assert index["ready_for_product_score"] is True
