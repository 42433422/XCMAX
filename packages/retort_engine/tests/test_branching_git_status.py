from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from retort_engine.branching import BranchWorkflowError, begin_absorption_branch, merge_absorption_branch
from retort_engine.git_status import blocking_git_status


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.strip()


def init_repo(root: Path) -> None:
    root.mkdir()
    git(root, "init", "-b", "main")
    git(root, "config", "user.email", "retort@example.test")
    git(root, "config", "user.name", "Retort Test")
    (root / "README.md").write_text("# own\n", encoding="utf-8")
    git(root, "add", ".")
    git(root, "commit", "-m", "init")


def test_blocking_git_status_ignores_runtime_cache_and_generated_outputs(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    init_repo(repo)
    generated = [
        repo / ".retort" / "absorption_state.json",
        repo / "__pycache__" / "core.cpython-312.pyc",
        repo / "tests" / "__pycache__" / "test_ok.cpython-312.pyc",
        repo / ".pytest_cache" / "README.md",
        repo / ".ruff_cache" / "CACHEDIR.TAG",
        repo / "docs" / "retort_external_review_report.json",
        repo / "docs" / "retort_new_gate.json",
        repo / "retort_absorbed_patterns.py",
        repo / "tests" / "test_absorbed_capabilities.py",
    ]
    for path in generated:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix == ".pyc":
            path.write_bytes(b"cache")
        else:
            path.write_text("{}\n", encoding="utf-8")

    assert blocking_git_status(repo, repo) == ""

    real_file = repo / "retort_engine" / "real_behavior.py"
    real_file.parent.mkdir()
    real_file.write_text("VALUE = 1\n", encoding="utf-8")

    blocking = blocking_git_status(repo, repo)
    assert "retort_engine/" in blocking
    assert "retort_external_review_report.json" not in blocking
    assert "__pycache__" not in blocking


def test_begin_absorption_branch_blocks_real_dirty_changes_not_runtime_state(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    init_repo(repo)
    (repo / ".retort").mkdir()
    (repo / ".retort" / "absorption_state.json").write_text("{}\n", encoding="utf-8")

    state = begin_absorption_branch(repo, source="https://github.com/example/reviewer", branch_name="retort/absorb-runtime-ok")

    assert state.status == "branch_created"
    assert state.base_branch == "main"
    assert state.absorption_branch == "retort/absorb-runtime-ok"

    git(repo, "checkout", "main")
    (repo / "real_dirty.py").write_text("VALUE = 1\n", encoding="utf-8")
    with pytest.raises(BranchWorkflowError, match="uncommitted changes"):
        begin_absorption_branch(repo, source="dirty", branch_name="retort/absorb-dirty")


def test_merge_absorption_branch_ignores_runtime_cache_and_creates_merge_commit(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    init_repo(repo)
    state = begin_absorption_branch(repo, source="https://github.com/example/reviewer", branch_name="retort/absorb-feature")
    (repo / "feature.py").write_text("VALUE = 1\n", encoding="utf-8")
    git(repo, "add", "feature.py")
    git(repo, "commit", "-m", "absorb feature")
    (repo / ".retort").mkdir()
    (repo / ".retort" / "employee_queue.jsonl").write_text("{}\n", encoding="utf-8")
    (repo / "__pycache__").mkdir()
    (repo / "__pycache__" / "feature.cpython-312.pyc").write_bytes(b"cache")

    merged = merge_absorption_branch(repo, state)

    assert merged.status == "merged"
    assert merged.merged is True
    assert git(repo, "branch", "--show-current") == "main"
    parents = git(repo, "show", "--no-patch", "--format=%P", "HEAD").split()
    assert len(parents) == 2
    assert blocking_git_status(repo, repo) == ""
