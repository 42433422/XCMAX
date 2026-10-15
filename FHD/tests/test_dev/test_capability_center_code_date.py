"""Stable commit dates and explicit Git failures for capability evidence."""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "成都修茈科技有限公司/scripts/build_capability_center.py"
SPEC = importlib.util.spec_from_file_location("build_capability_center", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


@pytest.mark.parametrize(
    "commit_time, expected",
    [
        ("2026-09-25T23:37:08+00:00", "2026-09-26"),
        ("2026-09-25T23:37:08Z", "2026-09-26"),
        ("2026-09-26T07:37:08+08:00", "2026-09-26"),
        ("2026-09-26T07:37:08", None),
    ],
)
def test_commit_date_uses_project_timezone(commit_time, expected) -> None:
    assert MODULE.project_code_date(commit_time) == expected


@pytest.fixture
def login_feature():
    catalog = json.loads(MODULE.CATALOG_PATH.read_text(encoding="utf-8"))
    return next(
        f
        for d in catalog["domains"]
        for m in d["modules"]
        for f in m["features"]
        if f["id"] == "base-login"
    )


@pytest.fixture
def git_run(monkeypatch):
    MODULE._is_ancestor.cache_clear()
    run = Mock(return_value=subprocess.CompletedProcess([], 0, "", ""))
    monkeypatch.setattr(MODULE.subprocess, "run", run)
    yield run
    MODULE._is_ancestor.cache_clear()


@pytest.mark.parametrize("returncode", [0, 1])
def test_only_git_ancestors_are_accepted(login_feature, git_run, returncode):
    git_run.return_value.returncode = returncode
    accepted = MODULE.reviewed_runs(login_feature, head="b" * 40)
    assert [r["_acceptance_path"] for r in accepted] == (
        login_feature["evidence"]["runs"] if returncode == 0 else []
    )
    assert git_run.call_count == len(login_feature["evidence"]["runs"])


@pytest.mark.parametrize(
    "failure",
    [
        subprocess.CompletedProcess([], 128, "", "fatal: missing commit"),
        subprocess.TimeoutExpired("git", 30),
        subprocess.CalledProcessError(128, "git"),
        OSError("Git unavailable"),
    ],
)
def test_git_query_failure_aborts_acceptance_and_is_not_cached(
    login_feature,
    git_run,
    failure,
):
    if isinstance(failure, Exception):
        git_run.side_effect = failure
    else:
        git_run.return_value = failure
    for _ in range(2):
        with pytest.raises(RuntimeError):
            MODULE.reviewed_runs(login_feature, head="b" * 40)
    assert git_run.call_count == 2
    git_run.side_effect = None
    git_run.return_value = subprocess.CompletedProcess([], 0, "", "")
    assert MODULE.reviewed_runs(login_feature, head="b" * 40)


def test_git_ancestry_cache_is_bound_to_commit_head_and_repository(git_run, tmp_path):
    commit, head = "a" * 40, "b" * 40
    assert MODULE._is_ancestor(commit, head, tmp_path)
    assert MODULE._is_ancestor(commit, head, tmp_path)
    git_run.assert_called_once_with(
        ["git", "merge-base", "--is-ancestor", commit, head],
        cwd=tmp_path,
        capture_output=True,
        timeout=30,
        check=False,
        encoding="utf-8",
        errors="replace",
    )
    assert MODULE._is_ancestor(commit, "c" * 40, tmp_path)
    assert MODULE._is_ancestor("d" * 40, head, tmp_path)
    assert MODULE._is_ancestor(commit, head, tmp_path / "other")
    assert git_run.call_count == 4
