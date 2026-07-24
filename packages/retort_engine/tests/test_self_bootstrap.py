from pathlib import Path
from unittest.mock import patch

import pytest

from retort_engine.self_bootstrap import (
    FRONTIER_SOURCES,
    build_self_bootstrap_plan,
    build_self_depth_report,
    external_improvement_gate,
    record_frontier_source_absorption,
)


def _project(tmp_path: Path) -> Path:
    (tmp_path / "retort_engine").mkdir()
    (tmp_path / "tests").mkdir()
    for path in (
        "retort_engine/repository_intelligence.py",
        "retort_engine/bounded_agent_loop.py",
        "retort_engine/issue_capability_benchmark.py",
        "tests/test_repository_intelligence.py",
        "tests/test_bounded_agent_loop.py",
        "tests/test_issue_capability_benchmark.py",
    ):
        target = tmp_path / path
        target.write_text(
            "def absorb_agent_benchmark():\n    return True\n", encoding="utf-8"
        )
    return tmp_path


@pytest.mark.keep_self_depth_gate
def test_self_bootstrap_locks_other_modules_until_sources_and_strict_proof(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    report = build_self_depth_report(project)
    assert report["external_improvement_allowed"] is False
    assert report["summary"]["missing"]
    assert external_improvement_gate(project, tmp_path / "other")["status"] == "blocked"
    assert build_self_bootstrap_plan(project)["status"] == "self_deepening_only"


def test_source_record_requires_exact_reviewed_revision(tmp_path: Path) -> None:
    project = _project(tmp_path)
    source = FRONTIER_SOURCES[0]
    try:
        record_frontier_source_absorption(
            project,
            source_id=source["source_id"],
            source_revision="wrong",
            gate_evidence=["pytest passed"],
        )
    except ValueError as exc:
        assert "revision" in str(exc)
    else:
        raise AssertionError("wrong source revision must be rejected")

    fake_layers = {
        "repository_intelligence": {"passed": True, "metrics": {}},
        "bounded_execution": {"passed": True, "metrics": {}},
        "reproducible_evaluation": {"passed": True, "metrics": {}},
        "verified_task_synthesis": {"passed": True, "metrics": {}},
    }
    with patch(
        "retort_engine.self_bootstrap._behavior_layers", return_value=fake_layers
    ):
        result = record_frontier_source_absorption(
            project,
            source_id=source["source_id"],
            source_revision=source["revision"],
            gate_evidence=["pytest tests/test_repository_intelligence.py: passed"],
        )
    assert result["status"] == "recorded"
    assert (
        build_self_bootstrap_plan(project)["summary"]["strictly_recorded_source_count"]
        == 1
    )


@pytest.mark.keep_self_depth_gate
def test_core_absorb_blocks_other_modules_when_self_depth_incomplete(
    tmp_path: Path,
) -> None:
    from retort_engine.core import absorb

    other = tmp_path / "other-module"
    other.mkdir()
    with patch(
        "retort_engine.core.external_improvement_gate",
        return_value={"status": "blocked", "missing": ["behavior:x"]},
    ):
        result = absorb({"own_project": str(other), "external_path": str(other)})
    assert result["status"] == "blocked_by_self_depth_gate"
