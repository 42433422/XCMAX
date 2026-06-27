from __future__ import annotations

from pathlib import Path

from retort_engine.review_pipeline import build_absorption_review_report, group_review_files


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_review_pipeline_groups_external_advantages(tmp_path: Path) -> None:
    own = tmp_path / "own"
    external = tmp_path / "external"
    write(own / "retort_engine" / "core.py", "def absorb(): pass\n")
    write(external / "internal" / "review.ts", "review pipeline reflection localization changed files patch set\n")
    write(external / "internal" / "providers.ts", "provider model openai anthropic ollama plugin extension\n")
    write(external / "bench" / "eval.md", "benchmark precision recall evaluation\n")

    groups = group_review_files(external)
    report = build_absorption_review_report(own, external, [{"task_id": "t1", "title": "review pipeline", "dimension": "comparative_analysis_depth"}])

    assert "review_pipeline" in groups
    assert "provider_surface" in groups
    assert "diff_hunk_review" in groups
    assert report["component_gaps"]
    assert "map_diff_hunk_context" in report["pipeline_stages"]
    assert report["prioritized_absorptions"][0]["source_files"]
    assert report["benchmark"]["minimum_expected_behavior_tests"] >= 3
    workflow = report["depth_absorption_workflow"]
    assert workflow["focus_mode"] == "similar_function_depth_only"
    assert workflow["quality_gate"]["passed"] is True
    assert workflow["employee_tasks"]
    assert all(item["component"] not in {"provider_surface", "plugin_surface"} for item in workflow["focused_components"])
    assert {item["component"] for item in workflow["rejected_breadth_components"]} & {"provider_surface", "plugin_surface"}
    assert all(task["acceptance"] and task["evidence_required"] for task in workflow["employee_tasks"])
    assert workflow["quality_gate"]["marketplace_candidate_count"] == len(workflow["marketplace_candidates"])
    assert {item["component"] for item in workflow["marketplace_candidates"]} & {"provider_surface", "plugin_surface"}
    assert all(item["route"] == "ai_employee_marketplace" for item in workflow["marketplace_candidates"])
