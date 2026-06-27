from __future__ import annotations

from pathlib import Path

import pytest

from retort_engine import external_sources
from retort_engine.external_sources import external_project_profile, materialize_external_source, parse_github_url, run_git_clone


def test_materialize_external_source_returns_local_directory(tmp_path: Path) -> None:
    external = tmp_path / "external"
    external.mkdir()

    assert materialize_external_source(str(external), tmp_path) == external.resolve()


def test_materialize_external_source_clones_github_into_retort_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, Path]] = []

    def fake_clone(url: str, target: Path) -> None:
        calls.append((url, target))
        target.mkdir(parents=True)
        (target / "README.md").write_text("# cloned\n", encoding="utf-8")

    monkeypatch.setattr(external_sources, "run_git_clone", fake_clone)

    first = materialize_external_source("https://github.com/owner/repo.git", tmp_path)
    second = materialize_external_source("https://github.com/owner/repo.git", tmp_path)
    stale = first / "stale.txt"
    stale.write_text("old\n", encoding="utf-8")
    refreshed = materialize_external_source("https://github.com/owner/repo.git", tmp_path, refresh=True)

    assert first == tmp_path / ".retort" / "cache" / "github" / "owner" / "repo"
    assert second == first
    assert refreshed == first
    assert calls == [
        ("https://github.com/owner/repo.git", first),
        ("https://github.com/owner/repo.git", first),
    ]
    assert not stale.exists()


def test_parse_github_url_accepts_https_and_ssh_forms() -> None:
    assert parse_github_url("https://github.com/openai/codex/tree/main") == ("openai", "codex")
    assert parse_github_url("git@github.com:owner/repo.git") == ("owner", "repo")
    assert parse_github_url("not-a-repo") is None


def test_external_project_profile_detects_depth_signals(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "tool.py").write_text(
        "code review pipeline reviewer reflection localization\n"
        "file group changed files diff hunk patch set\n"
        "benchmark precision recall evaluation\n"
        "plugin cli github action codex\n",
        encoding="utf-8",
    )

    profile = external_project_profile(tmp_path)

    assert profile == {
        "review_pipeline": True,
        "file_grouping": True,
        "benchmarking": True,
        "plugin_surface": True,
        "planet_frontend": False,
        "atmosphere_shader": False,
        "procedural_surface": False,
        "webgl_scene": False,
    }


def test_run_git_clone_raises_git_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class Result:
        returncode = 1
        stdout = ""
        stderr = "fatal: failed"

    monkeypatch.setattr(external_sources.subprocess, "run", lambda *_args, **_kwargs: Result())

    with pytest.raises(RuntimeError, match="fatal: failed"):
        run_git_clone("https://github.com/owner/repo.git", tmp_path / "repo")
