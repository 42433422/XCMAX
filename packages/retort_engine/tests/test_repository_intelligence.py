from pathlib import Path

from retort_engine.repository_intelligence import (
    build_ranked_repository_map,
    compare_repository_gaps,
    task_targets_from_map,
    tasks_from_repository_gaps,
)


def test_ranked_repository_map_uses_dependency_rank_and_focus(tmp_path: Path) -> None:
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "core.py").write_text(
        "def absorb_project():\n    return 1\n", encoding="utf-8"
    )
    (pkg / "left.py").write_text(
        "from pkg.core import absorb_project\n", encoding="utf-8"
    )
    (pkg / "right.py").write_text(
        "from pkg.core import absorb_project\n", encoding="utf-8"
    )

    result = build_ranked_repository_map(
        tmp_path, focus_terms=("absorb",), max_files=3, max_chars=1000
    )

    assert result["status"] == "ready"
    assert result["summary"]["dependency_edge_count"] == 2
    assert result["files"][0]["path"] == "pkg/core.py"
    assert result["files"][0]["page_rank"] > result["files"][1]["page_rank"]
    assert (
        result["evidence"]["algorithm"] == "personalized_file_pagerank_plus_focus_hits"
    )
    assert task_targets_from_map(result, limit=1)[0]["path"] == "pkg/core.py"


def test_ranked_repository_map_respects_context_budget(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x = 'absorb' * 100\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("y = 'absorb' * 100\n", encoding="utf-8")
    result = build_ranked_repository_map(
        tmp_path, focus_terms=("absorb",), max_files=1, max_chars=8
    )
    assert result["summary"]["selected_file_count"] == 1
    assert result["summary"]["used_chars"] == 8


def test_compare_repository_gaps_prefers_graph_decision(tmp_path: Path) -> None:
    own = tmp_path / "own"
    external = tmp_path / "ext"
    (own / "a").mkdir(parents=True)
    (external / "a").mkdir(parents=True)
    (own / "a" / "mod.py").write_text("def absorb():\n    return 1\n", encoding="utf-8")
    (external / "a" / "mod.py").write_text(
        "def absorb():\n    return 1\n\ndef agent_loop():\n    pass\n", encoding="utf-8"
    )
    gap = compare_repository_gaps(own, external, focus_terms=("absorb", "agent"))
    assert gap["summary"]["decision_source"] == "repository_graph_gap"
    assert gap["summary"]["marker_scan_is_auxiliary"] is True
    assert gap["gaps"]
    assert gap["gaps"][0]["suggested_own_targets"]
    assert gap["gaps"][0]["suggested_own_targets"][0].get("matched_for_external")


def test_tasks_from_repository_gaps_include_missing_symbols_and_targets(
    tmp_path: Path,
) -> None:
    own = tmp_path / "own"
    external = tmp_path / "ext"
    (own / "pkg").mkdir(parents=True)
    (external / "pkg").mkdir(parents=True)
    (own / "pkg" / "core.py").write_text(
        "def absorb():\n    return 1\n", encoding="utf-8"
    )
    (external / "pkg" / "core.py").write_text(
        "def absorb():\n    return 1\n\ndef agent_loop():\n    return 2\n\ndef rank_files():\n    return []\n",
        encoding="utf-8",
    )
    own_map = build_ranked_repository_map(
        own, focus_terms=("absorb", "agent"), max_files=8
    )
    gap = compare_repository_gaps(own, external, focus_terms=("absorb", "agent"))
    tasks = tasks_from_repository_gaps(gap, own_map, limit=3)
    assert tasks
    assert any("agent_loop" in (task.get("missing_symbols") or []) for task in tasks)
    assert all(task.get("target_files") for task in tasks)
    assert all(task.get("source") == "repository_graph_gap" for task in tasks)
