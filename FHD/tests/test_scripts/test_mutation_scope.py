"""Exercise the gate against actual monorepo diffs, including first pushes and errors."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts.ci.mutation_scope import changed_paths, requires_mutation


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


@pytest.fixture
def repository(tmp_path):
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.name", "Gate Test")
    git(tmp_path, "config", "user.email", "gate@example.invalid")
    return tmp_path


def commit(root: Path, name: str) -> str:
    file = root / name
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text("changed\n")
    git(root, "add", "--", name)
    git(root, "commit", "-qm", "gate fixture")
    return git(root, "rev-parse", "HEAD")


@pytest.mark.parametrize(
    "name",
    [
        "FHD/app/di/registry.py",
        "FHD/pyproject.toml",
        "FHD/.github/workflows/mutation-smoke.yml",
        "FHD/tests/test_contexts/test_space name.py",
    ],
)
def test_nested_cwd_preserves_repository_relative_scope(repository, name):
    before = commit(repository, "README.md")
    after = commit(repository, name)
    paths = changed_paths(repository / "FHD", before, after)
    assert paths == [name]
    assert requires_mutation(paths)


def test_unrelated_change_does_not_run_mutation(repository):
    before = commit(repository, "README.md")
    after = commit(repository, "FHD/docs/help.md")
    assert not requires_mutation(changed_paths(repository, before, after))


def test_first_push_checks_root_commit(repository):
    head = commit(repository, "FHD/app/contexts/context.py")
    assert requires_mutation(changed_paths(repository, "0" * 40, head))


def test_missing_revision_cannot_turn_into_successful_skip(repository):
    head = commit(repository, "README.md")
    with pytest.raises(subprocess.CalledProcessError):
        changed_paths(repository, "missing-commit", head)
