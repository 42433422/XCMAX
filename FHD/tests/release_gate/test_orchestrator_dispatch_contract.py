"""Execute the real dispatch shell with inert children; never deploy in tests."""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
SOURCE = REPO_ROOT / "FHD/.github/workflows/release-orchestrator.yml"
MIRROR = REPO_ROOT / ".github/workflows/fhd-release-orchestrator.yml"


def test_dispatch_product_version_matches_current_release_anchor():
    expected = re.search(
        r"\*\*XCAGI 稳定产品版本\*\* \| `([\d.]+)`",
        (REPO_ROOT / "FHD/VERSION.md").read_text(encoding="utf-8"),
    ).group(1)
    for path in (SOURCE, MIRROR):
        workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
        dispatch = workflow.get("on", workflow.get(True))["workflow_dispatch"]
        value = dispatch["inputs"]["product_version"]
        assert value["default"] == expected and value["options"] == [expected]


def _dispatch_step(workflow_path: Path) -> dict:
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    return next(
        step for step in workflow["jobs"]["deploy-servers-in-order"]["steps"] if "run" in step
    )


def _run_dispatch(tmp_path: Path, step: dict, current: str, previous: str):
    helper = tmp_path / "FHD/scripts/release/dispatch_workflow_and_wait.sh"
    helper.parent.mkdir(parents=True)
    helper.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "with open(os.environ['DISPATCH_CALLS'], 'a') as out:\n"
        "    out.write(json.dumps(sys.argv[1:]) + '\\n')\n",
        encoding="utf-8",
    )
    helper.chmod(0o755)
    mock_bin = tmp_path / "bin"
    mock_bin.mkdir()
    git = mock_bin / "git"
    git.write_text('#!/bin/sh\nprintf "%s\\n" "$RELEASE_SHA"\n', encoding="utf-8")
    git.chmod(0o755)
    calls = tmp_path / "calls.jsonl"
    result = subprocess.run(
        ["bash", "-c", step["run"]],
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": f"{mock_bin}:{os.environ['PATH']}",
            "DISPATCH_CALLS": str(calls),
            "RELEASE_SHA": "a" * 40,
            "PRODUCT_VERSION": "1.0.0.1",
            "SECURITY_SCAN_RUN_ID": current,
            "PREVIOUS_SECURITY_SCAN_RUN_ID": previous,
        },
        capture_output=True,
        text=True,
        check=False,
    )
    recorded = (
        [json.loads(line) for line in calls.read_text().splitlines()] if calls.exists() else []
    )
    return result, recorded


@pytest.mark.parametrize("workflow_path", [SOURCE, MIRROR], ids=["source", "published"])
def test_each_production_dispatch_keeps_validated_sha_and_scan_pair(tmp_path, workflow_path):
    jobs = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))["jobs"]
    assert jobs["verify-version-anchors"]["needs"] == "security-preflight"
    assert jobs["deploy-servers-in-order"]["needs"] == "verify-version-anchors"
    assert "verify_security_scan_pair.py" in str(jobs["security-preflight"])
    step = _dispatch_step(workflow_path)
    for name, input_name in (
        ("RELEASE_SHA", "release_sha"),
        ("SECURITY_SCAN_RUN_ID", "security_scan_run_id"),
        ("PREVIOUS_SECURITY_SCAN_RUN_ID", "previous_security_scan_run_id"),
    ):
        assert step["env"][name] == "${{ inputs." + input_name + " }}"
    assert "${{ inputs." not in step["run"]
    result, calls = _run_dispatch(tmp_path, step, "1234", "1234")
    assert result.returncode == 0, result.stderr
    assert [call[0] for call in calls] == [
        "fhd-ci-cd.yml",
        "modstore-prod-deploy.yml",
        "fhd-ci-cd.yml",
        "fhd-deploy.yml",
        "fhd-production-observability.yml",
    ]
    for call in calls[1:4]:
        fields = dict(
            call[index + 1].split("=", 1) for index, arg in enumerate(call) if arg == "-f"
        )
        assert fields.get("release_sha", fields.get("git_sha")) == "a" * 40
        assert fields["security_scan_run_id"] == "1234"
        assert fields["previous_security_scan_run_id"] == "1234"
        if call[0] == "fhd-deploy.yml":
            assert fields["action"] == "apply-latest"
            assert fields["action_id"] == "release:" + "a" * 40


@pytest.mark.parametrize("current,previous", [("", "1200"), ("1234", ""), ("latest", "1200")])
def test_missing_or_malformed_evidence_stops_before_dispatch(tmp_path, current, previous):
    result, calls = _run_dispatch(tmp_path, _dispatch_step(SOURCE), current, previous)
    assert result.returncode != 0
    assert calls == []

@pytest.mark.parametrize("workflow_path", [SOURCE, MIRROR], ids=["source", "published"])
def test_desktop_production_dispatch_is_not_the_default_candidate_lane(workflow_path):
    jobs = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))["jobs"]
    check = str(jobs["verify-version-anchors"])
    assert "Test-only candidate cannot trigger production deployments" in check
    assert "windows_interim_release" in check
    assert jobs["deploy-servers-in-order"]["needs"] == "verify-version-anchors"
    step = next(s for s in jobs["dispatch-client-releases"]["steps"] if "run" in s)
    run = step["run"]
    for flag in ("windows_installer_only=false", "candidate_only=false", "verify_only=false"):
        assert f"-f {flag}" in run
    assert '"Release Desktop ${XCAGI_RELEASE_SHA}"' in run


@pytest.mark.parametrize("scenario,expected_ok", [
    ("exact", True), ("duplicate", False), ("wrong_sha", False), ("candidate_suffix", False)
])
def test_dispatch_correlates_exact_title_and_frozen_sha(tmp_path, scenario, expected_ok):
    sha = "a" * 40
    helper = REPO_ROOT / "FHD/scripts/release/dispatch_workflow_and_wait.sh"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "gh"
    fake.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "args = sys.argv[1:]\n"
        "if args[:2] == ['workflow', 'run']: sys.exit(0)\n"
        "if args[:2] == ['run', 'list']:\n"
        "    print(os.environ['FAKE_WORKFLOW_RUNS']); sys.exit(0)\n"
        "if args[:2] == ['run', 'watch']: sys.exit(0)\n"
        "sys.exit(2)\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    # Make "no exact match" terminate immediately instead of polling for five minutes.
    fast_sleep = bin_dir / "sleep"
    fast_sleep.write_text("#!/bin/sh\nexit 3\n", encoding="utf-8")
    fast_sleep.chmod(0o755)
    row = dict(databaseId=202, displayTitle=f"Release Desktop {sha}",
               createdAt="2099-01-01T00:00:00Z", headSha=sha)
    if scenario == "duplicate":
        rows = [row, {**row, "databaseId": 203}]
    elif scenario == "wrong_sha":
        rows = [{**row, "headSha": "b" * 40}]
    elif scenario == "candidate_suffix":
        rows = [{**row, "displayTitle": row["displayTitle"] + " · Windows candidate"}]
    else:
        rows = [row]
    result = subprocess.run(
        ["bash", str(helper), "fhd-release-desktop.yml", row["displayTitle"]],
        env={**os.environ, "GH_TOKEN": "inert", "GH_REPO": "test/repo",
             "RELEASE_SHA": sha, "FAKE_WORKFLOW_RUNS": json.dumps(rows),
             "PATH": f"{bin_dir}:{os.environ['PATH']}"},
        capture_output=True, text=True, timeout=12, check=False,
    )
    assert (result.returncode == 0) == expected_ok, result.stderr
    if scenario == "duplicate":
        assert "Ambiguous dispatched run identity" in result.stderr
