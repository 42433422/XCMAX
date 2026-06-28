from __future__ import annotations

import json
from pathlib import Path

from retort_engine.contracts import validate_contract
from retort_engine.multi_project_absorption_replay import build_multi_project_absorption_replay
from retort_engine.service import RetortService


def test_multi_project_absorption_replay_requires_distinct_ready_projects(tmp_path: Path) -> None:
    _write_run(tmp_path, "run-a", "packages/retort_engine/.retort/cache/github/qodo-ai/pr-agent", True)
    _write_employee_result(tmp_path, "run-a")
    _write_run(tmp_path, "run-b", "packages/retort_engine/.retort/cache/github/mopemope/pr-ai-review-bot", True)
    _write_employee_result(tmp_path, "run-b")

    result = build_multi_project_absorption_replay(tmp_path, min_projects=2)

    assert result["status"] == "ready"
    assert result["summary"]["ready_project_count"] == 2
    assert result["summary"]["distinct_source_count"] == 2
    assert result["summary"]["all_have_behavior_diff"] is True
    assert result["summary"]["all_have_behavior_tests"] is True
    assert result["summary"]["all_have_employee_results"] is True
    assert result["summary"]["all_have_per_run_code_graph_proof"] is True
    assert result["summary"]["latest_project_differs_from_previous"] is True
    assert result["summary"]["source_family_count"] == 2
    assert result["summary"]["heterogeneous_absorption_verified"] is True
    assert validate_contract("multi_project_absorption_replay_result", result)["valid"] is True


def test_multi_project_absorption_replay_fails_without_second_project(tmp_path: Path) -> None:
    _write_run(tmp_path, "run-a", "github/a", True)
    _write_employee_result(tmp_path, "run-a")

    result = build_multi_project_absorption_replay(tmp_path, min_projects=2)

    assert result["status"] == "needs_more_replay"
    assert result["summary"]["ready_project_count"] == 1


def test_service_exposes_multi_project_absorption_replay(tmp_path: Path) -> None:
    _write_run(tmp_path, "run-a", "packages/retort_engine/.retort/cache/github/qodo-ai/pr-agent", True)
    _write_employee_result(tmp_path, "run-a")
    _write_run(tmp_path, "run-b", "packages/retort_engine/.retort/cache/github/mopemope/pr-ai-review-bot", True)
    _write_employee_result(tmp_path, "run-b")

    result = RetortService().multi_project_absorption_replay({"project": str(tmp_path), "min_projects": 2})

    assert result["status"] == "ready"


def test_multi_project_absorption_replay_reports_historical_heterogeneous_families(tmp_path: Path) -> None:
    sources = [
        "retort://post-absorption-hardening/abc123",
        "packages/retort_engine/.retort/cache/github/qodo-ai/pr-agent",
        "packages/retort_engine/.retort/cache/github/mopemope/pr-ai-review-bot",
        "https://github.com/seddonym/import-linter",
        "https://github.com/EleutherAI/lm-evaluation-harness",
        "https://github.com/semgrep/semgrep",
    ]
    for index, source in enumerate(sources, start=1):
        run_id = f"run-{index:02d}"
        _write_run(tmp_path, run_id, source, True)
        _write_employee_result(tmp_path, run_id)

    result = build_multi_project_absorption_replay(tmp_path, min_projects=5)

    assert result["status"] == "ready"
    assert result["summary"]["historical_heterogeneous_absorption_verified"] is True
    assert result["summary"]["historical_architecture_source_count"] >= 1
    assert result["summary"]["historical_benchmark_source_count"] >= 1
    assert result["summary"]["historical_security_source_count"] >= 1
    assert result["summary"]["historical_source_family_count"] >= 5


def _write_run(root: Path, run_id: str, source: str, gates_passed: bool) -> None:
    run_dir = root / ".retort" / "real_absorption_runs"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / f"{run_id}.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "source": source,
                "gates_passed": gates_passed,
                "changed_files": [
                    str(root / "retort_engine" / "review_context_bias.py"),
                    str(root / "tests" / "test_review_context_bias.py"),
                ],
                "employee_results_path": str(root / ".retort" / "employee_results" / f"{run_id}.json"),
                "code_graph_proof": _code_graph_proof(run_id),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _code_graph_proof(run_id: str) -> dict[str, object]:
    return {
        "run_id": run_id,
        "passed": True,
        "per_run_required": True,
        "status": "ready",
        "summary": {"graph_status": "ready", "changed_file_count": 2},
        "evidence": {
            "style": "deterministic_post_absorption_code_graph",
            "scope": "per_real_absorption_run",
        },
    }


def _write_employee_result(root: Path, run_id: str) -> None:
    result_dir = root / ".retort" / "employee_results"
    result_dir.mkdir(parents=True, exist_ok=True)
    (result_dir / f"{run_id}.json").write_text(
        json.dumps(
            {
                "results": [{"task_id": "task", "status": "completed"}],
                "runtime_evidence": {"worker_review": {"status": "reviewed"}},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
