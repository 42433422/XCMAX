from __future__ import annotations

import subprocess
from pathlib import Path

from retort_engine.absorption import run_absorption
from tests.test_evidence_evaluator import create_focused_tool_package, create_incomplete_package, write_file


def git(cwd: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return result.stdout.strip()


def init_repo(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    git(root, "init", "-b", "main")
    git(root, "config", "user.email", "retort@example.test")
    git(root, "config", "user.name", "Retort Test")
    write_file(root / "README.md", "# own\n")
    git(root, "add", ".")
    git(root, "commit", "-m", "init")


def test_absorption_creates_branch_for_main_project_folder(tmp_path: Path) -> None:
    own = tmp_path / "own"
    external = tmp_path / "external"
    init_repo(own)
    create_incomplete_package(own)
    git(own, "add", ".")
    git(own, "commit", "-m", "package")
    create_focused_tool_package(external)
    result = run_absorption(own_project=str(own), external_path=str(external), branch_workflow=True, absorption_branch="retort/absorb-test", max_tasks=2)
    assert result.branch_workflow["created"] is True
    assert git(own, "branch", "--show-current") == "retort/absorb-test"


def test_branch_workflow_blocks_dirty_main_project(tmp_path: Path) -> None:
    own = tmp_path / "own"
    external = tmp_path / "external"
    init_repo(own)
    create_focused_tool_package(external)
    write_file(own / "dirty.txt", "dirty\n")
    result = run_absorption(own_project=str(own), external_path=str(external), branch_workflow=True)
    assert result.status == "blocked_by_branch_workflow"


def test_absorption_can_merge_branch_back_to_main(tmp_path: Path) -> None:
    own = tmp_path / "own"
    external = tmp_path / "external"
    init_repo(own)
    create_incomplete_package(own)
    git(own, "add", ".")
    git(own, "commit", "-m", "package")
    create_focused_tool_package(external)
    result = run_absorption(own_project=str(own), external_path=str(external), branch_workflow=True, absorption_branch="retort/absorb-merge-test", merge_after=True, max_tasks=2)
    assert result.branch_workflow["merged"] is True
    assert git(own, "branch", "--show-current") == "main"
