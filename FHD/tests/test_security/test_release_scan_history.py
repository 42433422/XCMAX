"""Exercise the actual release checkout guard on full and shallow Git histories."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "FHD/.github/workflows/security-full-scan.yml"


def _git(cwd: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=cwd, text=True).strip()


def _steps() -> list[dict]:
    return yaml.safe_load(SOURCE.read_text(encoding="utf-8"))["jobs"]["scan-and-gate"]["steps"]


def test_full_scan_history_contract_and_generated_mirror():
    steps = _steps()
    checkout = next(s for s in steps if s.get("uses", "").startswith("actions/checkout@"))
    assert checkout["with"]["fetch-depth"] == 0
    assert checkout["with"]["ref"] == "${{ inputs.release_sha }}"
    scan = next(s for s in steps if s.get("name") == "Run gitleaks without hiding findings")
    assert '--log-opts="--full-history HEAD"' in scan["run"]
    assert "--redact" in scan["run"] and "--no-git" not in scan["run"]
    mirror = (ROOT / ".github/workflows/fhd-security-full-scan.yml").read_text(encoding="utf-8")
    source_lines = SOURCE.read_text(encoding="utf-8").splitlines(keepends=True)
    assert mirror.splitlines(keepends=True)[2:] == source_lines


@pytest.mark.parametrize("depth,wrong_sha", [(None, False), (1, False), (None, True)])
def test_release_checkout_guard_rejects_shallow_or_wrong_sha(tmp_path, depth, wrong_sha):
    origin = tmp_path / "origin"
    origin.mkdir()
    _git(origin, "init", "-q")
    _git(origin, "config", "user.email", "fixture@example.invalid")
    _git(origin, "config", "user.name", "history-fixture")
    marker = "SYNTHETIC_REMOVED_HISTORY_MARKER"
    source = origin / "removed.txt"
    source.write_text(marker, encoding="utf-8")
    _git(origin, "add", ".")
    _git(origin, "commit", "-qm", "synthetic historical record")
    _git(origin, "rm", "removed.txt")
    _git(origin, "commit", "-qm", "remove from current tree only")
    clone = tmp_path / "clone"
    flags = ["--depth", str(depth)] if depth else []
    _git(tmp_path, "clone", "-q", *flags, origin.as_uri(), str(clone))
    head = _git(clone, "rev-parse", "HEAD")
    lock = next(s for s in _steps() if s.get("name") == "Lock scan checkout to exact SHA")
    script = lock["run"].replace("${{ inputs.release_sha }}", "0" * 40 if wrong_sha else head)
    result = subprocess.run(
        ["bash", "-c", script],
        cwd=clone,
        capture_output=True,
        env={**os.environ, "RUNNER_TEMP": str(tmp_path / "evidence")},
    )
    assert (result.returncode == 0) is (depth is None and not wrong_sha)
    if result.returncode == 0:
        assert not (clone / "removed.txt").exists()
        assert marker in _git(clone, "log", "-p", "--full-history", "HEAD")
