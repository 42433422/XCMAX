"""Synthetic measurement fixtures exercise the verifier, never certify hardware."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from scripts.release.verify_desktop_soak import verify_bundle, verify_platform

SHA, VERSION = "a" * 40, "1.0.0.1"
START = datetime(2026, 11, 23, tzinfo=UTC)
TARGETS = {
    "windows": ("AMD64", "x64"),
    "macos-arm64": ("arm64", "arm64"),
    "macos-x64": ("x86_64", "x64"),
}


def raw_report(platform: str) -> dict:
    cases = {}
    for index, name in enumerate(
        (
            "renderer_offline",
            "renderer_crash",
            "backend_crash",
            "desktop_restart",
            "multi_window",
            "clean_exit",
        )
    ):
        cases[name] = {
            "passed": True,
            "started_at": (START + timedelta(seconds=28861 + 10 * index)).isoformat(),
            "finished_at": (START + timedelta(seconds=28866 + 10 * index)).isoformat(),
        }
    cases["renderer_offline"].update(offline_observed=True, recovered=True)
    cases["renderer_crash"].update(crashed_observed=True, recovered=True)
    cases["backend_crash"].update(before_pid=20, after_pid=21, recovered=True)
    cases["desktop_restart"].update(before_pid=10, after_pid=11, recovered=True)
    cases["multi_window"].update(opened=2, remaining=1)
    cases["clean_exit"].update(remaining_processes=0)
    return {
        "schema": "xcagi.desktop_soak/v1",
        "platform": platform,
        "release_sha": SHA,
        "product_version": VERSION,
        "requested_duration_seconds": 28800,
        "status": "completed",
        "blockers": [],
        "events": [],
        "started_at": START.isoformat(),
        "finished_at": (START + timedelta(seconds=28920)).isoformat(),
        "machine": {
            "runner_environment": "self-hosted",
            "runner_name": f"fixture-{platform}",
            "system": "Windows" if platform == "windows" else "Darwin",
            "release": "test-os",
            "machine": TARGETS.get(platform, TARGETS["macos-arm64"])[0],
            "rosetta_translated": False,
        },
        "artifact": {
            "build_sha": SHA,
            "version": VERSION,
            "architecture": TARGETS.get(platform, TARGETS["macos-arm64"])[1],
            **dict.fromkeys(
                ("executable_sha256", "build_info_sha256", "app_asar_sha256", "backend_sha256"),
                "c" * 64,
            ),
        },
        "samples": [
            {
                "elapsed_seconds": elapsed,
                "timestamp_utc": (START + timedelta(seconds=60 + elapsed)).isoformat(),
                "root_pid": 10,
                "root_create_time": 100.0,
                "backend_pid": 20,
                "backend_create_time": 101.0,
                "rss_bytes": 200 * 1024**2,
                "cpu_percent": 5.0,
                "handles": 100,
                "process_count": 5,
                "gui": True,
                "gui_view": ("settings", "chat", "customers", "products")[elapsed // 30 % 4],
                "endpoints": dict.fromkeys(
                    ("/api/ping", "/api/health", "/api/desktop/status"), True
                ),
            }
            for elapsed in range(0, 28801, 30)
        ],
        "scenarios": cases,
    }


def write_bundle(directory: Path) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    reports, jobs = {}, {}
    for index, platform in enumerate(TARGETS, 1):
        target = directory / f"{platform}.json"
        target.write_text(json.dumps(raw_report(platform)), encoding="utf-8")
        reports[platform] = hashlib.sha256(target.read_bytes()).hexdigest()
        jobs[platform] = {
            "id": 50 + index,
            "runner_id": index,
            "runner_name": f"fixture-{platform}",
            "labels": [
                "self-hosted",
                "xcagi-physical",
                "Windows" if platform == "windows" else "macOS",
                TARGETS[platform][1],
            ],
            "started_at": (START - timedelta(minutes=1)).isoformat(),
            "completed_at": (START + timedelta(hours=8, minutes=3)).isoformat(),
        }
    proof = {
        "release_sha": SHA,
        "repository": "42433422/XCMAX",
        "sources": {
            "desktop_soak": {
                "workflow": "fhd-desktop-soak.yml",
                "run_id": 5,
                "run_attempt": 2,
                "controller_sha": "b" * 40,
                "artifact_id": 15,
                "artifact_digest": "sha256:" + "d" * 64,
                "native_jobs": jobs,
                "reports": reports,
            }
        },
    }
    path = directory / "provenance.json"
    path.write_text(json.dumps(proof), encoding="utf-8")
    return directory, path


def test_full_measurements_need_original_native_provenance(tmp_path):
    directory, path = write_bundle(tmp_path)
    result = verify_bundle(directory, release_sha=SHA, product_version=VERSION)
    assert result["measurements_passed"] is True
    assert result["passed"] is False
    assert result["verification_scope"] == "local_measurements"
    result = verify_bundle(
        directory, release_sha=SHA, product_version=VERSION, provenance=json.loads(path.read_text())
    )
    assert result["passed"] is True
    assert result["verification_scope"] == "registered_native_runner"
    assert result["per_platform"]["windows"]["measured_duration_seconds"] == 28800
    assert {key: row["architecture"] for key, row in result["per_platform"].items()} == {
        "windows": "x64",
        "macos-arm64": "arm64",
        "macos-x64": "x64",
    }


def test_legacy_dual_os_receipts_cannot_certify_both_mac_architectures(tmp_path):
    directory, path = write_bundle(tmp_path)
    for platform in ("macos-arm64", "macos-x64"):
        (directory / f"{platform}.json").unlink(missing_ok=True)
    (directory / "macos.json").write_text(json.dumps(raw_report("macos")), encoding="utf-8")
    result = verify_bundle(
        directory, release_sha=SHA, product_version=VERSION, provenance=json.loads(path.read_text())
    )
    assert result["passed"] is False


def test_windows_arm_receipt_cannot_certify_native_x64():
    payload = raw_report("windows")
    payload["machine"]["machine"] = "ARM64"
    payload["artifact"]["architecture"] = "arm64"
    assert not verify_platform(
        payload, platform="windows", release_sha=SHA, product_version=VERSION
    )["passed"]


@pytest.mark.parametrize("translated", [True, None, 0])
def test_translated_or_unobserved_mac_process_cannot_certify_native_x64(translated):
    payload = raw_report("macos-x64")
    payload["machine"]["rosetta_translated"] = translated
    assert not verify_platform(
        payload, platform="macos-x64", release_sha=SHA, product_version=VERSION
    )["passed"]


@pytest.mark.parametrize(
    "fault", ["machine", "binary", "runner_arch", "same_mac_device", "missing_mac_x64"]
)
def test_mac_architectures_and_device_provenance_cannot_be_substituted(tmp_path, fault):
    directory, path = write_bundle(tmp_path)
    proof = json.loads(path.read_text())
    source = proof["sources"]["desktop_soak"]
    if fault in {"machine", "binary"}:
        report_path = directory / "macos-arm64.json"
        payload = json.loads(report_path.read_text())
        if fault == "machine":
            payload["machine"]["machine"] = "x86_64"
        else:
            payload["artifact"]["architecture"] = "x64"
        report_path.write_text(json.dumps(payload))
        source["reports"]["macos-arm64"] = hashlib.sha256(report_path.read_bytes()).hexdigest()
    elif fault == "runner_arch":
        source["native_jobs"]["macos-arm64"]["labels"] = [
            "self-hosted",
            "macos",
            "xcagi-physical",
            "x64",
        ]
    elif fault == "same_mac_device":
        source["native_jobs"]["macos-x64"]["runner_id"] = source["native_jobs"]["macos-arm64"][
            "runner_id"
        ]
    else:
        (directory / "macos-x64.json").unlink()
    assert not verify_bundle(directory, release_sha=SHA, product_version=VERSION, provenance=proof)[
        "passed"
    ]


@pytest.mark.parametrize(
    "fault",
    [
        "endpoint",
        "gui",
        "static_view",
        "restart",
        "gap",
        "short",
        "fake_clock",
        "nan",
        "missing_hash",
        "wrong_sha",
    ],
)
def test_incomplete_or_inconsistent_observations_cannot_pass(fault):
    payload = raw_report("windows")
    # Submitted summary flags cannot override a failing observation.
    payload.update(passed=True, real_machine=True)
    sample = payload["samples"][50]
    if fault == "endpoint":
        for row in payload["samples"]:
            row["endpoints"]["/api/desktop/status"] = False
    elif fault == "gui":
        sample["gui"] = False
    elif fault == "static_view":
        for row in payload["samples"]:
            row["gui_view"] = "settings"
    elif fault == "restart":
        sample["root_create_time"] += 1  # PID reuse must also count as a restart.
    elif fault == "gap":
        del payload["samples"][50:60]
    elif fault == "short":
        payload["requested_duration_seconds"] = 3
        payload["samples"] = payload["samples"][:2]
    elif fault == "fake_clock":
        for row in payload["samples"]:
            row["timestamp_utc"] = (
                START + timedelta(seconds=60 + row["elapsed_seconds"] / 100)
            ).isoformat()
    elif fault == "nan":
        sample["cpu_percent"] = float("nan")
    elif fault == "missing_hash":
        del payload["artifact"]["backend_sha256"]
    else:
        payload["artifact"]["build_sha"] = "f" * 40
    assert (
        verify_platform(payload, platform="windows", release_sha=SHA, product_version=VERSION)[
            "passed"
        ]
        is False
    )


@pytest.mark.parametrize(
    "fault",
    [
        "rss_growth",
        "handles_growth",
        "cpu_sustained",
        "recovery",
        "wrong_process",
        "scenario_missing",
        "renderer_recovery",
        "orphan",
    ],
)
def test_resource_leaks_and_unobserved_recovery_are_blocked(fault):
    payload = raw_report("macos-arm64")
    if fault in ("rss_growth", "handles_growth"):
        field, value = ("rss_bytes", 600 * 1024**2) if fault == "rss_growth" else ("handles", 2000)
        for row in payload["samples"][-11:]:
            row[field] = value
    elif fault == "cpu_sustained":
        for row in payload["samples"][50:60]:
            row["cpu_percent"] = 99
    elif fault == "recovery":
        payload["scenarios"]["backend_crash"]["after_pid"] = 20
    elif fault == "wrong_process":
        payload["scenarios"]["backend_crash"]["before_pid"] = 999
    elif fault == "scenario_missing":
        del payload["scenarios"]["renderer_offline"]
    elif fault == "renderer_recovery":
        payload["scenarios"]["renderer_crash"]["recovered"] = False
    else:
        payload["scenarios"]["clean_exit"]["remaining_processes"] = 1
    result = verify_platform(
        payload, platform="macos-arm64", release_sha=SHA, product_version=VERSION
    )
    assert result["passed"] is False
    assert result["blockers"]


@pytest.mark.parametrize(
    "fault", ["substituted_bytes", "runner_name", "labels", "same_runner", "prior_job", "workflow"]
)
def test_measurements_bind_to_original_artifact_and_registered_jobs(tmp_path, fault):
    directory, proof_path = write_bundle(tmp_path)
    proof = json.loads(proof_path.read_text())
    source = proof["sources"]["desktop_soak"]
    job = source["native_jobs"]["macos-arm64"]
    if fault == "substituted_bytes":
        path = directory / "macos-arm64.json"
        path.write_text(
            path.read_text() + "\n"
        )  # Even equivalent JSON is different original evidence.
    elif fault == "runner_name":
        job["runner_name"] = "unregistered-machine"
    elif fault == "labels":
        job["labels"] = ["macos-latest"]
    elif fault == "same_runner":
        job["runner_id"] = source["native_jobs"]["windows"]["runner_id"]
    elif fault == "prior_job":
        job["completed_at"] = START.isoformat()
    else:
        source["workflow"] = "another-workflow.yml"
    result = verify_bundle(directory, release_sha=SHA, product_version=VERSION, provenance=proof)
    assert result["measurements_passed"] is True
    assert result["passed"] is False


def test_cli_records_missing_platform_and_cannot_self_certify(tmp_path):
    directory, _ = write_bundle(tmp_path)
    script = Path(__file__).resolve().parents[2] / "scripts/release/verify_desktop_soak.py"
    output = tmp_path / "verdict.json"
    command = [
        sys.executable,
        str(script),
        "--windows",
        str(directory / "windows.json"),
        "--macos",
        str(directory / "macos-arm64.json"),
        "--macos-x64",
        str(directory / "macos-x64.json"),
        "--release-sha",
        SHA,
        "--product-version",
        VERSION,
        "--output",
        str(output),
    ]
    assert subprocess.run(command, capture_output=True, timeout=10).returncode == 1
    assert (
        subprocess.run(
            [*command, "--measurements-only"], capture_output=True, timeout=10
        ).returncode
        == 0
    )
    assert json.loads(output.read_text())["passed"] is False
    (directory / "macos-arm64.json").unlink()
    assert (
        subprocess.run(
            [*command, "--measurements-only"], capture_output=True, timeout=10
        ).returncode
        == 1
    )
    result = json.loads(output.read_text())
    assert result["per_platform"]["macos-arm64"]["blockers"] == ["raw_report_missing_or_invalid"]


def test_expected_injected_renderer_crash_event_is_allowed():
    payload = raw_report("windows")
    payload["events"] = [
        {
            "kind": "renderer_crash",
            "phase": "renderer_crash",
            "timestamp_utc": payload["scenarios"]["renderer_crash"]["started_at"],
        }
    ]
    result = verify_platform(payload, platform="windows", release_sha=SHA, product_version=VERSION)
    assert result["passed"] is True
    assert result["summary"]["renderer_event_count"] == 1


@pytest.mark.parametrize("fault", ["missing", "not_array", "malformed", "overflow"])
def test_renderer_event_log_is_mandatory_and_bounded(fault):
    payload = raw_report("macos-arm64")
    if fault == "missing":
        del payload["events"]
    elif fault == "not_array":
        payload["events"] = {}
    elif fault == "malformed":
        payload["events"] = [None]
    else:
        event = {
            "kind": "renderer_crash",
            "phase": "renderer_crash",
            "timestamp_utc": payload["scenarios"]["renderer_crash"]["started_at"],
        }
        payload["events"] = [event] * 101
    assert (
        verify_platform(payload, platform="macos-arm64", release_sha=SHA, product_version=VERSION)[
            "passed"
        ]
        is False
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"kind": "unknown"},
        {"phase": "unknown"},
        {"timestamp_utc": "2026-11-23T00:00:00"},
        {"message_sha256": "unhashed-message"},
        {"timestamp_utc": "2026-11-24T00:00:00Z"},
        {"phase": "steady", "timestamp_utc": "2026-11-23T01:00:00Z"},
        {"kind": "renderer_page_error", "phase": "login", "timestamp_utc": "2026-11-23T00:00:30Z"},
        {"kind": "renderer_page_error"},
        {"timestamp_utc": "2026-11-23T01:00:00Z"},  # Cannot relabel a steady crash as an injection.
    ],
)
def test_renderer_faults_between_good_samples_cannot_disappear(changes):
    payload = raw_report("windows")
    payload["events"] = [
        {
            "kind": "renderer_crash",
            "phase": "renderer_crash",
            "timestamp_utc": payload["scenarios"]["renderer_crash"]["started_at"],
            "message_sha256": "f" * 64,
            **changes,
        }
    ]
    result = verify_platform(payload, platform="windows", release_sha=SHA, product_version=VERSION)
    assert result["passed"] is False
    assert any("renderer_event" in blocker for blocker in result["blockers"])
