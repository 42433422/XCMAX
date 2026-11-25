"""Release iOS must bind the signed artifact to the exact mainline product SHA."""

from __future__ import annotations

import json
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
    assert inputs["build_number"]["required"] is True
    assert "default" not in inputs["build_number"]
    assert inputs["submit_for_review"]["default"] is False
    assert inputs["distribute_to_testflight"]["default"] is False

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
    assert "config/download_release.json" not in version["run"]
    assert "catalog_version%.*" not in version["run"]
    assert "GITHUB_RUN_NUMBER" not in version["run"]
    assert "marketing_version" in version["run"]

    signed = next(step for step in steps if step.get("name") == "Freeze signed IPA bytes and original build identity")
    assert "hashlib.file_digest" in signed["run"]
    assert "with archive.open('rb')" in signed["run"]
    assert "'verification_scope': 'build_artifact_not_physical_device'" in signed["run"]
    assert "xcagi-ios-build-info.json" in signed["run"]
    for proof in ("CFBundleIdentifier", "CFBundleShortVersionString", "CFBundleVersion",
                  "codesign", "TeamIdentifier", "'sku': 'personal'"):
        assert proof in signed["run"]
    personal = next(step for step in steps if step.get("name") == "Reject unverified personal iOS App Store identity")
    assert personal["env"]["PERSONAL_BUNDLE_ID"] == "${{ vars.IOS_PERSONAL_APP_STORE_BUNDLE_ID }}"
    assert personal["env"]["PERSONAL_APP_STORE_ID"] == "${{ vars.IOS_PERSONAL_APP_STORE_APP_ID }}"

    upload = next(step for step in steps if step.get("name") == "Upload IPA artifact")
    assert upload["with"]["path"] == artifact_path
    assert upload["with"]["if-no-files-found"] == "error"
    distribution = next(step for step in steps if step.get("name") == "Upload to TestFlight or submit for review")
    assert distribution["if"] == "inputs.distribute_to_testflight"
    decode_key = next(step for step in steps if step.get("name") == "Decode App Store Connect API key")
    assert decode_key["if"] == "inputs.distribute_to_testflight"


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


@pytest.mark.parametrize("path,_", WORKFLOWS, ids=["source", "published"])
@pytest.mark.parametrize(
    "distribute,submit,allowed",
    [
        ("false", "false", True),
        ("true", "false", True),
        ("true", "true", True),
        ("false", "true", False),
    ],
)
def test_app_review_requires_explicit_distribution_authorization(
    path: Path, _: str, distribute: str, submit: str, allowed: bool
) -> None:
    step = next(
        row for row in _workflow(path)["jobs"]["build-and-distribute"]["steps"]
        if row.get("name") == "Require explicit distribution approval for App Review"
    )
    result = subprocess.run(
        ["bash", "-e", "-c", step["run"]],
        env={
            **os.environ,
            "DISTRIBUTE_TO_TESTFLIGHT": distribute,
            "SUBMIT_FOR_REVIEW": submit,
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert (result.returncode == 0) == allowed


@pytest.mark.parametrize("path,_", WORKFLOWS, ids=["source", "published"])
@pytest.mark.parametrize("scenario", ["valid", "missing_build", "invalid_version", "invalid_build"])
def test_ios_release_version_treats_dispatch_inputs_as_data(
    path: Path, _: str, scenario: str, tmp_path: Path
) -> None:
    step = next(
        row for row in _workflow(path)["jobs"]["build-and-distribute"]["steps"]
        if row.get("name") == "Resolve release version"
    )
    assert step["env"]["REQUESTED_MARKETING_VERSION"] == "${{ inputs.version }}"
    assert step["env"]["REQUESTED_BUILD_NUMBER"] == "${{ inputs.build_number }}"
    assert "${{" not in step["run"]
    app = tmp_path / "mobile-flutter-poc"
    app.mkdir()
    output = tmp_path / "output"
    marker = app / "unexpected-execution"
    invalid = '$(touch unexpected-execution)'
    result = subprocess.run(
        ["bash", "-e", "-c", step["run"]],
        cwd=app,
        env={
            **os.environ,
            "REQUESTED_MARKETING_VERSION": invalid if scenario == "invalid_version" else "1.2.3",
            "REQUESTED_BUILD_NUMBER": invalid if scenario == "invalid_build" else (
                "" if scenario == "missing_build" else "42"
            ),
            "GITHUB_RUN_NUMBER": "43",
            "GITHUB_OUTPUT": str(output),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert not marker.exists()
    if scenario in {"invalid_version", "invalid_build", "missing_build"}:
        assert result.returncode != 0
        assert not output.exists()
    else:
        assert result.returncode == 0, result.stderr
        assert output.read_text(encoding="utf-8").splitlines() == [
            "marketing_version=1.2.3", "build_number=42"
        ]

@pytest.mark.parametrize("path,_", WORKFLOWS, ids=["source", "published"])
@pytest.mark.parametrize("scenario", [
    "valid", "frozen", "inactive", "bundle_mismatch", "store_mismatch", "missing_bundle",
])
def test_personal_ios_identity_gate_fail_closed(
    path: Path, _: str, scenario: str, tmp_path: Path
) -> None:
    """Personal target must be active and all release identity sources must agree."""
    step = next(
        row for row in _workflow(path)["jobs"]["build-and-distribute"]["steps"]
        if row.get("name") == "Reject unverified personal iOS App Store identity"
    )
    mobile = tmp_path / "mobile-flutter-poc"
    ios = mobile / "ios"
    (ios / "fastlane").mkdir(parents=True)
    (ios / "Runner.xcodeproj").mkdir()
    (tmp_path / "config").mkdir()
    bundle = "com.example.xcagi.personal"
    store_id = "123456789"
    (ios / "fastlane/Fastfile").write_text(
        f'APP_IDENTIFIER = "{bundle}"\nAPP_STORE_ID = "{store_id}"\n', encoding="utf-8"
    )
    (ios / "fastlane/Matchfile").write_text(
        f'app_identifier("{bundle}")\n', encoding="utf-8"
    )
    (ios / "Runner.xcodeproj/project.pbxproj").write_text(
        f'PRODUCT_BUNDLE_IDENTIFIER = {bundle};\n', encoding="utf-8"
    )
    active = ["enterprise"] if scenario == "inactive" else ["enterprise", "personal"]
    frozen = ["personal"] if scenario == "frozen" else []
    (tmp_path / "config/download_release.json").write_text(
        json.dumps({"active_skus": active, "frozen_skus": frozen}),
        encoding="utf-8",
    )
    result = subprocess.run(
        ["bash", "-e", "-c", step["run"]],
        cwd=mobile,
        env={
            **os.environ,
            "PERSONAL_BUNDLE_ID": "" if scenario == "missing_bundle" else (
                "com.example.other" if scenario == "bundle_mismatch" else bundle
            ),
            "PERSONAL_APP_STORE_ID": "999999999" if scenario == "store_mismatch" else store_id,
        },
        capture_output=True, text=True, check=False,
    )
    assert (result.returncode == 0) == (scenario == "valid"), result.stderr
