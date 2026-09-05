"""Execute the real dispatch shell with inert children; never deploy in tests."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
SOURCE = REPO_ROOT / "FHD/.github/workflows/release-orchestrator.yml"
MIRROR = REPO_ROOT / ".github/workflows/fhd-release-orchestrator.yml"


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
    result, calls = _run_dispatch(tmp_path, step, "1234", "1200")
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
        assert fields["previous_security_scan_run_id"] == "1200"
        if call[0] == "fhd-deploy.yml":
            assert fields["action"] == "apply-latest"
            assert fields["action_id"] == "release:" + "a" * 40


@pytest.mark.parametrize(
    "current,previous", [("", "1200"), ("1234", ""), ("latest", "1200"), ("1234", "1234")]
)
def test_missing_malformed_or_same_run_evidence_stops_before_dispatch(tmp_path, current, previous):
    result, calls = _run_dispatch(tmp_path, _dispatch_step(SOURCE), current, previous)
    assert result.returncode != 0
    assert calls == []
