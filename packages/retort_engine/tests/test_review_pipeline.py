from __future__ import annotations

from pathlib import Path

from retort_engine.review_pipeline import build_absorption_review_report, build_depth_absorption_workflow, compare_component_gaps, group_review_files


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
    assert workflow["marketplace_candidates_enabled"] is False
    assert workflow["marketplace_candidates"] == []
    assert {item["component"] for item in workflow["deferred_breadth_components"]} & {"provider_surface", "plugin_surface"}
    assert all(item["status"] == "closed_until_similarity_saturation" for item in workflow["deferred_breadth_components"])


def test_group_review_files_skips_runtime_and_dependency_directories(tmp_path: Path) -> None:
    write(tmp_path / "src" / "review.py", "code review reflection localization\n")
    write(tmp_path / ".retort" / "state.json", "benchmark precision recall\n")
    write(tmp_path / "node_modules" / "pkg" / "index.js", "provider openai plugin\n")
    write(tmp_path / "dist" / "bundle.js", "file group changed files\n")
    write(tmp_path / "README.txt", "review pipeline\n")

    groups = group_review_files(tmp_path)

    assert set(groups) == {"review_pipeline"}
    assert groups["review_pipeline"]["files"] == ["src/review.py"]
    assert groups["review_pipeline"]["marker_hits"] == 4


def test_compare_component_gaps_sorts_by_marker_then_file_gap() -> None:
    own = {
        "review_pipeline": {"files": ["own/review.py"], "marker_hits": 3},
        "benchmark_eval": {"files": ["own/bench.py"], "marker_hits": 5},
    }
    external = {
        "review_pipeline": {"files": ["external/review.py", "external/pipeline.py"], "marker_hits": 20},
        "benchmark_eval": {"files": ["external/bench.py"], "marker_hits": 8},
        "workflow_ci": {"files": ["external/ci.yml", "external/gate.py"], "marker_hits": 8},
        "safety_policy": {"files": [], "marker_hits": 0},
    }

    gaps = compare_component_gaps(own, external)

    assert [gap["component"] for gap in gaps] == ["review_pipeline", "workflow_ci", "benchmark_eval"]
    assert gaps[0]["marker_gap"] == 17
    assert gaps[0]["file_gap"] == 1
    assert gaps[1]["own_files"] == 0
    assert gaps[1]["external_files"] == 2
    assert gaps[1]["representative_external_files"] == ["external/ci.yml", "external/gate.py"]


def test_depth_workflow_focuses_overlap_and_rejects_breadth() -> None:
    own_groups = {
        "review_pipeline": {"files": ["own/review.py"], "marker_hits": 5},
        "file_grouping": {"files": ["own/context.py"], "marker_hits": 2},
        "workflow_ci": {"files": ["own/ci.yml"], "marker_hits": 5},
    }
    external_groups = {
        "review_pipeline": {"files": ["external/review.py"], "marker_hits": 50},
        "diff_hunk_review": {"files": ["external/diff.py"], "marker_hits": 30},
        "file_grouping": {"files": ["external/group.py"], "marker_hits": 28},
        "benchmark_eval": {"files": ["external/bench.py"], "marker_hits": 25},
        "workflow_ci": {"files": ["external/ci.yml"], "marker_hits": 20},
        "provider_surface": {"files": ["external/provider.py"], "marker_hits": 100},
        "plugin_surface": {"files": ["external/plugin.py"], "marker_hits": 100},
    }
    tasks = [
        {
            "task_id": "review",
            "title": "Deepen review pipeline and diff hunk review",
            "dimension": "comparative_analysis_depth",
            "why": "Need file grouping depth, not provider breadth",
        }
    ]

    workflow = build_depth_absorption_workflow(own_groups, external_groups, tasks)

    focused = {item["component"]: item for item in workflow["focused_components"]}
    rejected = {item["component"]: item for item in workflow["rejected_breadth_components"]}
    assert workflow["focus_mode"] == "similar_function_depth_only"
    assert set(focused) >= {"review_pipeline", "diff_hunk_review", "file_grouping", "benchmark_eval", "workflow_ci"}
    assert focused["review_pipeline"]["priority"] == "P0"
    assert focused["diff_hunk_review"]["priority"] == "P0"
    assert focused["file_grouping"]["priority"] == "P0"
    assert focused["review_pipeline"]["depth_gap"] == 45
    assert focused["review_pipeline"]["similarity_score"] >= focused["workflow_ci"]["similarity_score"]
    assert rejected["provider_surface"]["reason"] == "breadth_only_for_current_phase"
    assert rejected["plugin_surface"]["reason"] == "breadth_only_for_current_phase"
    assert workflow["marketplace_candidates_enabled"] is False
    assert workflow["marketplace_candidates"] == []
    assert {item["component"] for item in workflow["deferred_breadth_components"]} == {"provider_surface", "plugin_surface"}
    assert workflow["quality_gate"]["focused_component_count"] >= 5
    assert workflow["quality_gate"]["kept_breadth_component_count"] == 0
    assert workflow["quality_gate"]["all_employee_tasks_have_acceptance"] is True
    assert workflow["quality_gate"]["passed"] is True


def test_depth_workflow_fails_gate_when_too_few_focused_components() -> None:
    workflow = build_depth_absorption_workflow(
        {"review_pipeline": {"files": ["own/review.py"], "marker_hits": 5}},
        {
            "review_pipeline": {"files": ["external/review.py"], "marker_hits": 10},
            "provider_surface": {"files": ["external/provider.py"], "marker_hits": 100},
        },
        [{"task_id": "review", "title": "review", "dimension": "comparative_analysis_depth"}],
    )

    assert workflow["quality_gate"]["focused_component_count"] == 1
    assert workflow["quality_gate"]["minimum_focused_component_count"] == 3
    assert workflow["quality_gate"]["passed"] is False
    assert workflow["quality_gate"]["deferred_breadth_component_count"] == 1
    assert workflow["employee_tasks"][0]["task_id"] == "retort-depth-review-pipeline"


def test_depth_workflow_rejects_non_same_direction_components_even_when_requested() -> None:
    workflow = build_depth_absorption_workflow(
        {},
        {
            "provider_surface": {"files": ["external/provider.py"], "marker_hits": 100},
            "plugin_surface": {"files": ["external/plugin.py"], "marker_hits": 100},
            "safety_policy": {"files": ["external/license.py"], "marker_hits": 20},
        },
        [
            {
                "task_id": "broad",
                "title": "plugin_surface provider_surface",
                "dimension": "product_operability",
                "why": "User asked to keep Retort depth first",
            }
        ],
    )

    rejected = {item["component"]: item for item in workflow["rejected_breadth_components"]}
    assert rejected["provider_surface"]["reason"] == "not_same_direction_depth"
    assert rejected["plugin_surface"]["reason"] == "not_same_direction_depth"
    assert rejected["safety_policy"]["reason"] == "no_internal_overlap_yet"
    assert workflow["focused_components"] == []
    assert workflow["employee_tasks"] == []
    assert workflow["quality_gate"]["passed"] is False


def test_depth_workflow_keeps_frontier_depth_components_when_overlapping() -> None:
    own_groups = {
        "codebase_graph": {"files": ["own/graph.py"], "marker_hits": 5},
        "static_analysis": {"files": ["own/rules.py"], "marker_hits": 4},
        "context_packaging": {"files": ["own/context.py"], "marker_hits": 3},
        "semantic_index": {"files": ["own/symbols.py"], "marker_hits": 3},
    }
    external_groups = {
        "static_analysis": {"files": ["external/scan.py"], "marker_hits": 40},
        "context_packaging": {"files": ["external/pack.py"], "marker_hits": 30},
        "semantic_index": {"files": ["external/index.py"], "marker_hits": 28},
    }

    workflow = build_depth_absorption_workflow(own_groups, external_groups, [{"task_id": "architecture", "title": "frontier depth", "dimension": "architecture_depth"}])

    focused = {item["component"]: item for item in workflow["focused_components"]}
    assert {"static_analysis", "context_packaging", "semantic_index"} <= set(focused)
    assert focused["static_analysis"]["priority"] == "P0"
    assert workflow["quality_gate"]["passed"] is True


def test_build_absorption_review_report_preserves_pipeline_contract(tmp_path: Path) -> None:
    own = tmp_path / "own"
    external = tmp_path / "external"
    write(own / "retort_engine" / "pr_review.py", "code review diff hunk workflow gate\n")
    write(own / "tests" / "test_pr_review.py", "def test_review(): pass\n")
    write(external / "review" / "pipeline.py", "code review reflection localization diff hunk changed lines\n")
    write(external / "review" / "grouping.py", "file group group files related files changed files pathspec\n")
    write(external / "eval" / "benchmark.py", "benchmark precision recall evaluation eval\n")
    write(external / "ops" / "ci.yml", "workflow pipeline ci gate test\n")
    write(external / "security" / "license.py", "license security policy permission sandbox\n")
    write(external / "plugins" / "action.yml", "plugin extension github action codex\n")
    tasks = [
        {"task_id": "depth", "title": "deep review pipeline", "dimension": "comparative_analysis_depth", "why": "same direction"},
        {"task_id": "ops", "title": "prove gates", "dimension": "operational_readiness", "why": "workflow ci"},
    ]

    report = build_absorption_review_report(own, external, tasks)

    assert report["pipeline_stages"] == [
        "materialize_external_snapshot",
        "group_related_files",
        "map_diff_hunk_context",
        "extract_review_signals",
        "compare_component_gaps",
        "rank_absorption_tasks",
        "verify_feedback_loop",
    ]
    assert {gap["component"] for gap in report["component_gaps"]} >= {
        "review_pipeline",
        "file_grouping",
        "diff_hunk_review",
        "benchmark_eval",
        "workflow_ci",
        "safety_policy",
        "plugin_surface",
    }
    assert report["prioritized_absorptions"]
    assert all(item["acceptance"].endswith("not only a recorded signal.") for item in report["prioritized_absorptions"])
    assert report["benchmark"]["component_gap_count"] == len(report["component_gaps"])
    assert report["benchmark"]["task_dimension_count"] == 2
    assert report["benchmark"]["minimum_expected_behavior_tests"] >= 3
    workflow = report["depth_absorption_workflow"]
    assert workflow["quality_gate"]["passed"] is True
    assert {item["component"] for item in workflow["focused_components"]} >= {"review_pipeline", "diff_hunk_review", "file_grouping"}
    assert {item["component"] for item in workflow["deferred_breadth_components"]} == {"plugin_surface"}
