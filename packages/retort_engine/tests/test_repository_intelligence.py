from pathlib import Path

from retort_engine.repository_intelligence import build_ranked_repository_map


def test_ranked_repository_map_uses_dependency_rank_and_focus(tmp_path: Path) -> None:
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "core.py").write_text("def absorb_project():\n    return 1\n", encoding="utf-8")
    (pkg / "left.py").write_text("from pkg.core import absorb_project\n", encoding="utf-8")
    (pkg / "right.py").write_text("from pkg.core import absorb_project\n", encoding="utf-8")

    result = build_ranked_repository_map(tmp_path, focus_terms=("absorb",), max_files=3, max_chars=1000)

    assert result["status"] == "ready"
    assert result["summary"]["dependency_edge_count"] == 2
    assert result["files"][0]["path"] == "pkg/core.py"
    assert result["files"][0]["page_rank"] > result["files"][1]["page_rank"]
    assert result["evidence"]["algorithm"] == "personalized_file_pagerank_plus_focus_hits"


def test_ranked_repository_map_respects_context_budget(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x = 'absorb' * 100\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("y = 'absorb' * 100\n", encoding="utf-8")
    result = build_ranked_repository_map(tmp_path, focus_terms=("absorb",), max_files=1, max_chars=8)
    assert result["summary"]["selected_file_count"] == 1
    assert result["summary"]["used_chars"] == 8
