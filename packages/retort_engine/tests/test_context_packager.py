from __future__ import annotations

from pathlib import Path

from retort_engine.context_packager import build_context_pack


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_context_pack_ranks_focus_terms_and_skips_generated_dirs(tmp_path: Path) -> None:
    write(
        tmp_path / "retort_engine" / "review.py",
        "def review():\n    return 'retort absorb context graph review review security'\n",
    )
    write(tmp_path / "retort_engine" / "other.py", "def other():\n    return 'small'\n")
    write(tmp_path / "docs" / "notes.md", "context review benchmark\n")
    write(tmp_path / "docs" / "retort_absorption_log.md", "review context " * 200)
    write(tmp_path / "node_modules" / "pkg" / "index.js", "retort absorb context review security\n")

    pack = build_context_pack(
        tmp_path,
        focus_terms=["Review", "context", "review", "security"],
        max_files=3,
        max_chars=500,
    )

    assert pack["status"] == "ready"
    assert pack["focus_terms"] == ["review", "context", "security"]
    assert pack["summary"]["selected_file_count"] <= 3
    assert pack["summary"]["used_chars"] <= 500
    assert pack["files"][0]["path"] == "retort_engine/review.py"
    assert all(not item["path"].startswith("node_modules/") for item in pack["files"])
    assert all(not item["path"].startswith("docs/retort_") for item in pack["files"])
    assert pack["evidence"]["style"] == "deterministic_context_packaging"


def test_context_pack_respects_character_budget(tmp_path: Path) -> None:
    write(tmp_path / "a.py", "review context security " * 100)
    write(tmp_path / "b.py", "review context " * 100)

    pack = build_context_pack(tmp_path, focus_terms=["review"], max_files=2, max_chars=80)

    assert pack["status"] == "ready"
    assert pack["summary"]["used_chars"] <= 80
    assert sum(len(item["excerpt"]) for item in pack["files"]) <= 80


def test_context_pack_falls_back_to_deterministic_files_without_term_hits(tmp_path: Path) -> None:
    write(tmp_path / "b.py", "def b():\n    return 2\n")
    write(tmp_path / "a.py", "def a():\n    return 1\n")

    pack = build_context_pack(tmp_path, focus_terms=["missing-term"], max_files=1)

    assert pack["status"] == "ready"
    assert pack["files"][0]["path"] == "a.py"
    assert pack["files"][0]["reason"] == "fallback_candidate"
