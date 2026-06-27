from __future__ import annotations

import json
import subprocess
from pathlib import Path

from retort_engine import similar_project_loop as loop_module
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


def test_similar_project_radar_uses_pr_token_boundary(tmp_path: Path) -> None:
    project = tmp_path / "retort"
    project.mkdir()
    candidates = [
        {
            "fullName": "owner/prettier-formatter",
            "url": "https://github.com/owner/prettier-formatter",
            "description": "AI review diff",
            "stargazersCount": 50,
            "license": {"key": "mit"},
        },
        {
            "fullName": "owner/pr-reviewer",
            "url": "https://github.com/owner/pr-reviewer",
            "description": "AI review diff",
            "stargazersCount": 1,
            "license": {"key": "mit"},
        },
    ]

    radar = build_similar_project_radar(project, candidates=candidates, min_score=55)

    assert [item["full_name"] for item in radar["candidates"]] == ["owner/pr-reviewer"]
    prettier = next(item for item in radar["rejected"] if item["full_name"] == "owner/prettier-formatter")
    assert prettier["similarity_depth_score"] < 55


def test_similar_project_radar_reports_search_failure(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "retort"
    project.mkdir()

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args=args, returncode=2, stdout="", stderr="gh auth failed\nlogin required")

    monkeypatch.setattr(loop_module.subprocess, "run", fake_run)

    radar = build_similar_project_radar(project)

    assert radar["status"] == "search_failed"
    assert radar["summary"]["search_returncode"] == 2
    assert "login required" in radar["summary"]["search_stderr_tail"]
    assert radar["candidates"] == []


def test_absorption_saturation_reports_search_failure(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "retort"
    runs = project / ".retort" / "real_absorption_runs"
    runs.mkdir(parents=True)
    for index in range(3):
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

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="network unavailable")

    monkeypatch.setattr(loop_module.subprocess, "run", fake_run)

    report = build_absorption_saturation_report(project)

    assert report["status"] == "search_failed"
    assert report["summary"]["saturated"] is False
    assert report["summary"]["saturation_basis"] == "search_failed"
    assert "network unavailable" in report["summary"]["search_error"]


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


def test_similar_project_loop_reports_no_candidates_instead_of_ready(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "retort"
    project.mkdir()

    def fake_radar(*args, **kwargs):
        return {"status": "no_candidates", "summary": {"search_status": "provided"}, "candidates": [], "rejected": []}

    monkeypatch.setattr(loop_module, "build_similar_project_radar", fake_radar)

    result = run_similar_project_loop(project, dry_run=False)

    assert result["status"] == "no_candidates"
    assert result["summary"]["selected_count"] == 0
    assert result["runs"] == []


def test_similar_project_loop_isolates_absorb_failures_and_uses_safe_defaults(tmp_path: Path, monkeypatch) -> None:
    from retort_engine import core as core_module

    project = tmp_path / "retort"
    project.mkdir()
    payloads: list[dict] = []

    def fake_absorb(payload: dict) -> dict:
        payloads.append(payload)
        if len(payloads) == 1:
            raise RuntimeError("first candidate failed")
        return {
            "status": "absorption_execution_applied",
            "execution": {"status": "applied", "gates_passed": True, "changed_files": ["retort_engine/example.py"]},
            "branch_workflow": {"status": "merged"},
            "tasks": [{"task_id": "retort-depth"}],
        }

    monkeypatch.setattr(core_module, "absorb", fake_absorb)

    result = run_similar_project_loop(
        project,
        sources=["https://github.com/one/pr-reviewer", "https://github.com/two/ai-pr-reviewer"],
        limit=2,
    )

    assert result["status"] == "needs_attention"
    assert [run["status"] for run in result["runs"]] == ["absorption_failed", "absorption_execution_applied"]
    assert "first candidate failed" in result["runs"][0]["error"]
    assert len(payloads) == 2
    assert all(payload["allow_dirty_branch"] is False for payload in payloads)
    assert all(payload["use_llm"] is False for payload in payloads)


def test_absorption_saturation_accepts_no_new_core_depth_even_with_remaining_candidates(tmp_path: Path) -> None:
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

    saturated = build_absorption_saturation_report(
        project,
        remaining_candidates=[
            {"url": "https://github.com/next/reviewer", "similarity_depth_score": 95, "license_allowed": True, "already_absorbed": False}
        ],
    )

    assert saturated["status"] == "saturated"
    assert saturated["summary"]["consecutive_no_new_core_depth_count"] >= 3
    assert saturated["summary"]["remaining_strong_depth_candidate_count"] == 1
    assert saturated["summary"]["saturation_basis"] == "recent_absorptions_add_no_new_core_depth"


def test_absorption_saturation_treats_low_score_remaining_candidates_as_saturated(tmp_path: Path) -> None:
    project = tmp_path / "retort"
    runs = project / ".retort" / "real_absorption_runs"
    runs.mkdir(parents=True)
    for index, signal in enumerate(["review_pipeline", "file_grouping", "benchmarking"]):
        (runs / f"run-{index}.json").write_text(
            json.dumps(
                {
                    "source": f"https://github.com/example/reviewer-{index}",
                    "status": "applied",
                    "gates_passed": True,
                    "changed_files": ["retort_engine/absorbed_capabilities.py"],
                    "external_profile": {"signals": [signal]},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    saturated = build_absorption_saturation_report(
        project,
        remaining_candidates=[
            {"url": "https://github.com/low/formatter", "similarity_depth_score": 32, "license_allowed": True, "already_absorbed": False}
        ],
    )

    assert saturated["status"] == "saturated"
    assert saturated["summary"]["remaining_strong_depth_candidate_count"] == 0
    assert saturated["summary"]["saturation_basis"] == "remaining_candidates_below_min_score"


def test_absorption_saturation_recognizes_new_frontier_depth_signals(tmp_path: Path) -> None:
    project = tmp_path / "retort"
    runs = project / ".retort" / "real_absorption_runs"
    runs.mkdir(parents=True)
    for index, signal in enumerate(["review_pipeline", "codebase_graph", "static_analysis", "context_packaging"]):
        (runs / f"run-{index}.json").write_text(
            json.dumps(
                {
                    "source": f"https://github.com/example/frontier-{index}",
                    "status": "applied",
                    "gates_passed": True,
                    "changed_files": ["retort_engine/absorbed_capabilities.py"],
                    "external_profile": {"signals": [signal]},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    report = build_absorption_saturation_report(
        project,
        remaining_candidates=[
            {"url": "https://github.com/next/frontier", "similarity_depth_score": 90, "license_allowed": True, "already_absorbed": False}
        ],
    )

    assert report["status"] == "not_saturated"
    assert report["summary"]["consecutive_no_new_core_depth_count"] == 0
