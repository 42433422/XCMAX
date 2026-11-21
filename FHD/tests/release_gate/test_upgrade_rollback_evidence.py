from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml


def _module():
    script = (
        Path(__file__).resolve().parents[2]
        / "scripts"
        / "release"
        / "verify_upgrade_rollback_evidence.py"
    )
    spec = importlib.util.spec_from_file_location("upgrade_rollback", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _evidence(sha: str):
    previous = "b" * 40
    start = datetime(2026, 9, 4, tzinfo=UTC)
    desktop = {
        "real_machine": True,
        "controlled_acceptance_device": True,
        "from_build_sha": previous,
        "installed_build_sha": sha,
        "rollback_build_sha": previous,
        "forward_build_sha": sha,
        "fault_injection_scope": "controlled_acceptance_device",
        "ota_passed": True,
        "cold_start_passed": True,
        "fault_rollback_passed": True,
        "data_retained": True,
        "evidence_sha256": "f" * 64,
        "data_before_sha256": "e" * 64,
        "data_after_sha256": "e" * 64,
        "ota_started_at": start.isoformat(),
        "installed_at": (start + timedelta(minutes=2)).isoformat(),
        "cold_started_at": (start + timedelta(minutes=3)).isoformat(),
        "fault_injected_at": (start + timedelta(minutes=4)).isoformat(),
        "rolled_back_at": (start + timedelta(minutes=6)).isoformat(),
        "forwarded_at": (start + timedelta(minutes=8)).isoformat(),
    }
    return {
        "server": {
            "environment": "production",
            "real_execution": True,
            "rollback_workflow_run_id": "12345",
            "forward_workflow_run_id": "12346",
            "previous_release_sha": previous,
            "failed_release_sha": sha,
            "rollback_release_sha": previous,
            "forward_release_sha": sha,
            "evidence_sha256": "d" * 64,
            "failure_detected_at": "2026-09-04T00:00:00Z",
            "rollback_started_at": "2026-09-04T00:02:00Z",
            "restored_at": "2026-09-04T00:20:00Z",
            "forwarded_at": "2026-09-04T00:25:00Z",
            "last_confirmed_write_at": "2026-09-04T00:00:00Z",
            "recovered_through_at": "2026-09-03T23:57:00Z",
            "data_consistent": True,
            "forward_passed": True,
        },
        "desktops": {name: dict(desktop) for name in ("macos", "windows10", "windows11")},
    }


def test_real_server_and_three_desktop_targets_pass() -> None:
    mod = _module()
    sha = "a" * 40
    evidence = _evidence(sha)
    evidence["desktops"]["macos"]["os_version"] = "26.3"
    evidence["desktops"]["windows10"]["os_version"] = "10.0.19045"
    evidence["desktops"]["windows11"]["os_version"] = "11.0.26100"
    assert mod.verify(evidence, release_sha=sha)["passed"] is True


def test_customer_device_or_synthetic_rollback_cannot_pass() -> None:
    mod = _module()
    sha = "a" * 40
    evidence = _evidence(sha)
    evidence["desktops"]["macos"]["os_version"] = "26.3"
    evidence["desktops"]["windows10"]["os_version"] = "10.0.19045"
    evidence["desktops"]["windows11"]["os_version"] = "11.0.26100"
    evidence["server"]["real_execution"] = False
    evidence["desktops"]["windows11"]["controlled_acceptance_device"] = False
    result = mod.verify(evidence, release_sha=sha)
    assert result["passed"] is False
    assert "server_real_production_rollback_missing" in result["blockers"]
    assert "windows11_real_controlled_device_missing" in result["blockers"]


def test_published_rollback_step_executes_from_its_workflow_directory(tmp_path) -> None:
    repo = Path(__file__).resolve().parents[3]
    workflow = yaml.safe_load(
        (repo / ".github/workflows/fhd-upgrade-rollback-evidence.yml").read_text()
    )
    step = next(item for item in workflow["jobs"]["verify"]["steps"] if "run" in item)
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    evidence = _evidence(sha)
    for target, version in (
        ("macos", "26.3"),
        ("windows10", "10.0.19045"),
        ("windows11", "11.0.26100"),
    ):
        evidence["desktops"][target]["os_version"] = version
    result = subprocess.run(
        ["bash", "-c", step["run"]],
        cwd=repo / workflow["defaults"]["run"]["working-directory"],
        env={
            **os.environ,
            "PATH": str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"],
            "RUNNER_TEMP": str(tmp_path),
            "RELEASE_SHA": sha,
            "EVIDENCE_JSON": json.dumps(evidence),
        },
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads((tmp_path / "upgrade-rollback-verification.json").read_text())["passed"]


def test_readback_preflight_runs_without_checkout_and_rejects_invalid_sha(
    tmp_path,
) -> None:
    repo = Path(__file__).resolve().parents[3]
    for path in (
        repo / "FHD/.github/workflows/release-convergence-readback.yml",
        repo / ".github/workflows/fhd-release-convergence-readback.yml",
    ):
        workflow = yaml.safe_load(path.read_text())
        job = workflow["jobs"]["readback"]
        step = job["steps"][0]
        defaults = job.get("defaults", workflow.get("defaults", {}))
        cwd = step.get("working-directory", defaults.get("run", {}).get("working-directory", "."))
        result = subprocess.run(
            ["bash", "-c", step["run"]],
            cwd=tmp_path / cwd,
            env={**os.environ, "ADMIN_TOKEN": "fixture-only", "RELEASE_SHA": "invalid"},
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert result.returncode == 1, result.stdout + result.stderr
