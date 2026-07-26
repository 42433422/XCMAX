from __future__ import annotations

from pathlib import Path

import yaml

FHD_ROOT = Path(__file__).resolve().parents[2]


def _workflow(name: str) -> dict:
    path = FHD_ROOT / ".github" / "workflows" / name
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _run_commands(job: dict) -> list[str]:
    return [str(step.get("run") or "") for step in job.get("steps") or [] if isinstance(step, dict)]


def test_every_direct_release_entry_runs_blocking_ssot_gate() -> None:
    release_jobs = {
        "release-desktop.yml": "release-preflight",
        "release-web.yml": "docker",
        "release-android.yml": "assemble-release",
        "release-ios.yml": "build-and-distribute",
        "release-orchestrator.yml": "verify-version-anchors",
        "release-gate-ci.yml": "release-gate",
    }
    for workflow_name, job_name in release_jobs.items():
        job = _workflow(workflow_name)["jobs"][job_name]
        commands = _run_commands(job)
        assert any("ssot_cli.py gate" in command for command in commands), workflow_name
        assert not bool(job.get("continue-on-error", False)), workflow_name


def test_release_and_image_jobs_depend_on_both_foundation_gates() -> None:
    jobs = _workflow("ci-cd.yml")["jobs"]
    for job_name in (
        "pack-verify",
        "container-scan",
        "docker-build-fhd-api",
        "docker-build",
        "release-verify",
    ):
        needs = jobs[job_name].get("needs") or []
        if isinstance(needs, str):
            needs = [needs]
        assert "ssot-drift-gate" in needs, job_name
        assert "schema-ssot-gate" in needs, job_name
