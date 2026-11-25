"""Release iOS must bind the signed artifact to the exact mainline product SHA."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
WORKFLOWS = (
    (ROOT / "FHD/.github/workflows/release-ios.yml", "mobile-flutter-poc/build/ios/ipa/"),
    (ROOT / ".github/workflows/fhd-release-ios.yml", "FHD/mobile-flutter-poc/build/ios/ipa/"),
)


def _workflow(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("path,artifact_path", WORKFLOWS, ids=["source", "published"])
def test_ios_release_rejects_unpinned_checkout_and_only_uploads_identified_ipa(
    path: Path, artifact_path: str
) -> None:
    workflow = _workflow(path)
    inputs = workflow.get("on", workflow.get(True))["workflow_dispatch"]["inputs"]
    assert inputs["release_sha"]["required"] is True
    assert inputs["release_sha"]["type"] == "string"
    assert inputs["version"]["required"] is True
    assert "default" not in inputs["version"]
    assert inputs["submit_for_review"]["default"] is False

    job = workflow["jobs"]["build-and-distribute"]
    assert job["if"] == "github.ref == 'refs/heads/main'"
    steps = job["steps"]
    checkout = next(step for step in steps if step.get("uses") == "actions/checkout@v4")
    assert checkout["with"]["ref"] == "${{ inputs.release_sha }}"
    assert checkout["with"]["fetch-depth"] == 0
    assert checkout["with"]["persist-credentials"] is False

    guard = next(step for step in steps if step.get("name", "").startswith("Reject an unfrozen"))
    assert guard["env"]["RELEASE_SHA"] == "${{ inputs.release_sha }}"
    for required in ("git rev-parse HEAD", "git merge-base --is-ancestor",
                     "refs/remotes/origin/main", "test \"$(git rev-parse refs/remotes/origin/main)\""):
        assert required in guard["run"]

    version = next(step for step in steps if step.get("name") == "Resolve release version")
    assert "config/download_release.json" in version["run"]
    assert "catalog_version%.*" in version["run"]
    assert "marketing_version" in version["run"]

    signed = next(step for step in steps if step.get("name") == "Freeze signed IPA bytes and original build identity")
    assert "hashlib.file_digest" in signed["run"]
    assert "with archive.open('rb')" in signed["run"]
    assert "'verification_scope': 'build_artifact_not_physical_device'" in signed["run"]
    assert "xcagi-ios-build-info.json" in signed["run"]
    upload = next(step for step in steps if step.get("name") == "Upload IPA artifact")
    assert upload["with"]["path"] == artifact_path
    assert upload["with"]["if-no-files-found"] == "error"


def _git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


@pytest.mark.parametrize("path,_", WORKFLOWS, ids=["source", "published"])
@pytest.mark.parametrize("scenario", ["same_main", "wrong_sha", "main_moved"])
def test_ios_release_sha_guard_checks_actual_git_state(
    path: Path, _: str, scenario: str, tmp_path: Path
) -> None:
    step = next(
        row for row in _workflow(path)["jobs"]["build-and-distribute"]["steps"]
        if row.get("name", "").startswith("Reject an unfrozen")
    )
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "ci@example.invalid")
    _git(tmp_path, "config", "user.name", "CI")
    (tmp_path / "test.txt").write_text("first\n", encoding="utf-8")
    _git(tmp_path, "add", "test.txt")
    _git(tmp_path, "commit", "-qm", "first")
    release_sha = _git(tmp_path, "rev-parse", "HEAD")
    _git(tmp_path, "update-ref", "refs/remotes/origin/main", release_sha)
    if scenario == "main_moved":
        (tmp_path / "test.txt").write_text("second\n", encoding="utf-8")
        _git(tmp_path, "commit", "-qam", "second")
        new_main = _git(tmp_path, "rev-parse", "HEAD")
        _git(tmp_path, "update-ref", "refs/remotes/origin/main", new_main)
        _git(tmp_path, "checkout", "-q", "--detach", release_sha)
    if scenario == "wrong_sha":
        release_sha = "f" * 40
    result = subprocess.run(
        ["bash", "-e", "-c", step["run"]],
        cwd=tmp_path,
        env={**os.environ, "RELEASE_SHA": release_sha},
        capture_output=True,
        text=True,
        check=False,
    )
    assert (result.returncode == 0) == (scenario == "same_main"), result.stderr
