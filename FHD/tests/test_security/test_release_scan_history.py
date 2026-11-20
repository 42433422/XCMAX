"""Execute the release trust guard against real merged and unmerged Git histories."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "FHD/.github/workflows/security-full-scan.yml"


def _git(cwd: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=cwd, text=True, timeout=15).strip()


def _steps() -> list[dict]:
    return yaml.safe_load(SOURCE.read_text(encoding="utf-8"))["jobs"]["scan-and-gate"]["steps"]


def test_full_scan_history_contract_and_generated_mirror():
    job = yaml.safe_load(SOURCE.read_text(encoding="utf-8"))["jobs"]["scan-and-gate"]
    assert job["if"] == "github.ref == 'refs/heads/main'"
    steps = _steps()
    checkout, guard = steps[:2]
    assert checkout["uses"] == "actions/checkout@11d5960a326750d5838078e36cf38b85af677262"
    assert checkout["with"]["fetch-depth"] == 0
    assert checkout["with"]["ref"] == "${{ inputs.release_sha || 'main' }}"
    assert checkout["with"]["persist-credentials"] is False
    assert guard["id"] == "scan-source"
    assert guard["env"]["RELEASE_SHA"] == "${{ inputs.release_sha || '' }}"
    assert not guard.get("continue-on-error", False)
    assert "secrets." not in yaml.safe_dump(steps[:2])
    for step in steps[2:]:
        if "run" in step and "always()" in step.get("if", ""):
            if step["run"].strip() != "exit 1":
                assert "steps.scan-source.outcome == 'success'" in step["if"]
    scan = next(s for s in steps if s.get("name") == "Run gitleaks without hiding findings")
    assert '--log-opts="--full-history HEAD"' in scan["run"]
    assert "--redact" in scan["run"] and "--no-git" not in scan["run"]
    mirror = (ROOT / ".github/workflows/fhd-security-full-scan.yml").read_text(encoding="utf-8")
    source_lines = SOURCE.read_text(encoding="utf-8").splitlines(keepends=True)
    assert mirror.splitlines(keepends=True)[2:] == source_lines


@pytest.mark.parametrize(
    "depth,case",
    [
        (None, "main"),
        (None, "ancestor"),
        (None, "auto"),
        (None, "unmerged"),
        (1, "main"),
        (None, "wrong_sha"),
        (None, "nonmain_ref"),
        (None, "wrong_repository"),
        (None, "missing_main"),
        (None, "invalid_sha"),
    ],
)
def test_release_checkout_guard_rejects_untrusted_history(tmp_path, depth, case):
    origin = tmp_path / "origin"
    origin.mkdir()
    _git(origin, "init", "-q", "-b", "main")
    _git(origin, "config", "user.email", "fixture@example.invalid")
    _git(origin, "config", "user.name", "history-fixture")
    marker = "SYNTHETIC_REMOVED_HISTORY_MARKER"
    source = origin / "removed.txt"
    source.write_text(marker, encoding="utf-8")
    _git(origin, "add", ".")
    _git(origin, "commit", "-qm", "synthetic historical record")
    _git(origin, "rm", "removed.txt")
    _git(origin, "commit", "-qm", "remove from current tree only")
    ancestor = _git(origin, "rev-parse", "HEAD")
    _git(origin, "commit", "-qm", "advance main", "--allow-empty")
    _git(origin, "checkout", "-qb", "candidate")
    _git(origin, "commit", "-qm", "unmerged candidate", "--allow-empty")
    unmerged = _git(origin, "rev-parse", "HEAD")
    _git(origin, "checkout", "-q", "main")
    clone = tmp_path / "clone"
    flags = ["--depth", str(depth)] if depth else []
    _git(tmp_path, "clone", "-q", *flags, origin.as_uri(), str(clone))
    if case in {"ancestor", "unmerged"}:
        _git(clone, "checkout", "-q", "--detach", ancestor if case == "ancestor" else unmerged)
    if case == "missing_main":
        _git(clone, "update-ref", "-d", "refs/remotes/origin/main")
    head = _git(clone, "rev-parse", "HEAD")
    lock = next(s for s in _steps() if s.get("name") == "Lock scan checkout to exact SHA")
    release_sha = "" if case == "auto" else (ancestor if case == "wrong_sha" else head)
    if case == "invalid_sha":
        release_sha = "$(touch guard-injection)"
    evidence = tmp_path / "evidence"
    result = subprocess.run(
        ["bash", "-c", lock["run"]],
        cwd=clone,
        capture_output=True,
        timeout=15,
        env={
            **os.environ,
            "RUNNER_TEMP": str(evidence),
            "RELEASE_SHA": release_sha,
            "GITHUB_REF": "refs/heads/candidate" if case == "nonmain_ref" else "refs/heads/main",
            "GITHUB_SERVER_URL": tmp_path.as_uri(),
            "GITHUB_REPOSITORY": "other" if case == "wrong_repository" else "origin",
            "GITHUB_OUTPUT": str(tmp_path / "github_output"),
        },
    )
    accepted = depth is None and case in {"main", "ancestor", "auto"}
    assert (result.returncode == 0) is accepted, result.stderr
    assert evidence.exists() is accepted
    assert not (clone / "guard-injection").exists()
    if result.returncode == 0:
        assert not (clone / "removed.txt").exists()
        assert (tmp_path / "github_output").read_text(encoding="utf-8").strip() == f"sha={head}"
        assert marker in _git(clone, "log", "-p", "--full-history", "HEAD")
