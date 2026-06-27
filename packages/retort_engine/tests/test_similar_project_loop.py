from __future__ import annotations

import json
from pathlib import Path

from retort_engine.similar_project_loop import build_absorption_saturation_report, build_similar_project_radar, run_similar_project_loop


def test_similar_project_radar_prefers_pr_review_depth(tmp_path: Path) -> None:
    project = tmp_path / "retort"
    project.mkdir()
    candidates = [
        {
            "fullName": "owner/deep-pr-reviewer",
            "url": "https://github.com/owner/deep-pr-reviewer",
            "description": "AI pull request code review with diff hunk inline comments",
            "stargazersCount": 20,
            "license": {"key": "mit"},
        },
        {
            "fullName": "owner/provider-market",
            "url": "https://github.com/owner/provider-market",
            "description": "model provider marketplace integration platform",
            "stargazersCount": 100,
            "license": {"key": "mit"},
        },
        {
            "fullName": "owner/gpl-pr-reviewer",
            "url": "https://github.com/owner/gpl-pr-reviewer",
            "description": "AI PR reviewer",
            "stargazersCount": 50,
            "license": {"key": "gpl-3.0"},
        },
    ]

    radar = build_similar_project_radar(project, candidates=candidates, min_score=55)

    assert radar["status"] == "ready"
    assert [item["full_name"] for item in radar["candidates"]] == ["owner/deep-pr-reviewer"]
    assert radar["candidates"][0]["similarity_depth_score"] >= 70
    assert any(item["reason"] == "license_not_allowed_for_auto_absorption" for item in radar["rejected"])


def test_similar_project_loop_dry_run_selects_depth_projects(tmp_path: Path) -> None:
    project = tmp_path / "retort"
    project.mkdir()

    result = run_similar_project_loop(
        project,
        sources=["https://github.com/one/pr-reviewer", "https://github.com/two/ai-pr-reviewer", "https://github.com/three/code-review-agent"],
        limit=2,
        dry_run=True,
    )

    assert result["status"] == "ready"
    assert result["summary"]["selected_count"] == 2
    assert all(run["status"] == "dry_run" for run in result["runs"])


def test_absorption_saturation_requires_green_recent_runs_and_no_remaining_candidates(tmp_path: Path) -> None:
    project = tmp_path / "retort"
    runs = project / ".retort" / "real_absorption_runs"
    runs.mkdir(parents=True)
    for index in range(4):
        (runs / f"run-{index}.json").write_text(
            json.dumps(
                {
                    "source": f"https://github.com/example/reviewer-{index}",
                    "status": "applied",
                    "gates_passed": True,
                    "changed_files": ["retort_engine/absorbed_capabilities.py"],
                    "external_profile": {"signals": ["review_pipeline"]},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    saturated = build_absorption_saturation_report(project, remaining_candidates=[])
    not_saturated = build_absorption_saturation_report(project, remaining_candidates=[{"url": "https://github.com/next/reviewer"}])

    assert saturated["status"] == "saturated"
    assert saturated["summary"]["consecutive_no_new_core_depth_count"] >= 3
    assert not_saturated["status"] == "not_saturated"
