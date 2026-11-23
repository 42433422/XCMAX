from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
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


def test_well_formed_claims_do_not_prove_real_server_or_desktop_acceptance() -> None:
    mod = _module()
    sha = "a" * 40
    evidence = _evidence(sha)
    evidence["desktops"]["macos"]["os_version"] = "26.3"
    evidence["desktops"]["windows10"]["os_version"] = "10.0.19045"
    evidence["desktops"]["windows11"]["os_version"] = "11.0.26100"
    evidence["verification_scope"] = "measured_native_acceptance"  # Caller cannot self-certify.
    result = mod.verify(evidence, release_sha=sha)
    assert result["structural_passed"] is True
    assert result["passed"] is False
    assert result["verification_scope"] == "submitted_claims"
    assert result["blockers"] == ["independent_native_measurements_missing"]


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
    registered = json.loads((tmp_path / "upgrade-rollback-verification.json").read_text())
    assert registered["structural_passed"] is True
    assert registered["passed"] is False
    # Registering inputs is useful, but the release consumer must retain failure.
    verify = subprocess.run(
        [
            sys.executable,
            str(repo / "FHD/scripts/release/verify_upgrade_rollback_evidence.py"),
            "--evidence",
            str(tmp_path / "upgrade-rollback-raw.json"),
            "--release-sha",
            sha,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert verify.returncode == 1
    assert json.loads(verify.stdout)["verification_scope"] == "submitted_claims"


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


def _native_windows(root, sha):
    """Synthetic copies of the existing producer's artifacts; never physical proof."""
    start = datetime(2026, 9, 4, tzinfo=UTC)
    fields = {
        "Clean": "candidate.login candidate.enterprise build_info backup_restore_copy",
        "Upgrade": "old_installer_hash app_update.candidate_build upgrade.health_commit owned_state.verify owned_state.main-verify retention.uninstalled",
        "Gui": "normal_gui_business",
        "Recovery": "normal_gui_faults backup_restore_copy backup_restore_enterprise",
        "Rollback": "old_installer_hash app_update.natural_marker app_update.natural_database_backup rollback.database_changed rollback.database_hash rollback.app_file_hashes rollback.same_enterprise owned_state.verify owned_state.main-verify",
    }
    for mode, result in _module().WINDOWS_RESULTS.items():
        directory = root / f"windows-candidate-evidence-{mode}-{sha}"
        directory.mkdir(parents=True)
        label = "old" if mode == "Rollback" else "candidate"
        names = ("account_configuration isolated_runner isolated_tasks " + fields[mode]).split()
        names += [
            f"{label}.{name}"
            for name in ("first_start_ready", "runtime_build_identity", "port_owner", "no_restart")
        ]
        row = {
            "mode": mode,
            "candidate_sha": sha,
            "candidate_sha256": "c" * 64,
            "candidate_on_main": True,
            "baseline_sha": "b" * 40,
            "baseline_version": "1.0.0.6",
            "result": result,
            "customer_acceptance": "not_verified",
            "runner": {
                "caption": "Microsoft Windows Server 2025",
                "customer_windows_10_11": "not_verified",
            },
            "started_at": start.isoformat(),
            "finished_at": (start + timedelta(minutes=20)).isoformat(),
            "checks": [
                {"name": name, "passed": True, "detail": "sha256=" + "d" * 64} for name in names
            ],
        }
        expected = "b" * 40 if label == "old" else sha
        details = {
            "first_start_ready": "health=healthy; blockers=0; readyForUi=True; pid=123",
            "runtime_build_identity": f"installed={expected}; running={expected}; legacy_health_identity_missing=False; release=1.0.0.7",
            "port_owner": r"pid=124; exe=C:\Programs\XCAGI\resources\backend\xcagi-backend.exe; actual_data=C:\isolated-data; expected_data=C:\isolated-data",
            "no_restart": "original pid=123",
        }
        for check in row["checks"]:
            if check["name"].startswith(f"{label}.") and check["name"].split(".")[1] in details:
                check["detail"] = details[check["name"].split(".")[1]]
        (directory / "acceptance.json").write_text(json.dumps(row), encoding="utf-8-sig")
        if mode in {"Gui", "Recovery"}:
            (directory / "gui-business.json").write_text(
                json.dumps(
                    {
                        "phase": "business" if mode == "Gui" else "faults",
                        "result": "business_regression_passed",
                        "unfinished": [],
                        "full_customer_acceptance": "not_verified",
                        "cases": [
                            {"id": name, "status": "passed"}
                            for name in sorted(
                                _module().GUI_CASES
                                | (
                                    {"controlled_stock_failure", "authorization_cancel"}
                                    if mode == "Recovery"
                                    else set()
                                )
                            )
                        ],
                    }
                )
            )
        if mode == "Rollback":
            old, new = f"1.0.0.6+{'b' * 40}", f"1.0.0.7+{sha}"
            (directory / "natural-rollback-marker.json").write_text(
                json.dumps(
                    {
                        "mode": "windows-full",
                        "fromVersion": old,
                        "toVersion": new,
                        "operationId": "native-operation",
                        "preparedAt": start.isoformat(),
                        "expectedOwnedFiles": {"mods/example/config.json": "e" * 64},
                        "expectedAppFiles": {"XCAGI.exe": "f" * 64},
                        "expectedDatabaseSha256": "d" * 64,
                    }
                )
            )
            (directory / "rollback-applied.last.json").write_text(
                json.dumps(
                    {
                        "fromVersion": new,
                        "toVersion": old,
                        "operationId": "native-operation",
                        "reason": "controlled startup failure",
                        "appliedAt": (start + timedelta(minutes=5)).isoformat(),
                        "completedAt": (start + timedelta(minutes=6)).isoformat(),
                    }
                )
            )
            (directory / "owned-fixtures.json").write_text(
                json.dumps(
                    [
                        {
                            "path": "mods/example/config.json",
                            "sha256": "e" * 64,
                            "absolute_length": 261,
                        }
                    ]
                )
            )
            (directory / "original-app-files.json").write_text(json.dumps({"XCAGI.exe": "f" * 64}))


def test_native_windows_raw_transaction_passes_only_its_measured_scope(tmp_path):
    sha = "a" * 40
    _native_windows(tmp_path, sha)
    result = _module().verify_windows_native(
        tmp_path, release_sha=sha, version="1.0.0.7", installer_sha256="c" * 64
    )
    assert result["passed"] is True
    assert result["verification_scope"] == "native_windows_runner_lifecycle"
    assert result["customer_acceptance"] == "not_verified"
    assert len(result["modes"]) == 5
    assert len(result["sources"]) == 11


@pytest.mark.parametrize(
    "corruption",
    [
        "missing_mode",
        "wrong_hash",
        "fake_check",
        "wrong_operation",
        "wrong_owned_hash",
        "wrong_database",
        "wrong_snapshot",
        "missing_original",
        "failed_gui",
        "missing_gui_case",
        "wrong_pid",
        "wrong_runtime",
        "wrong_data_owner",
        "not_main",
    ],
)
def test_native_windows_rejects_missing_or_mismatched_measurements(tmp_path, corruption):
    sha = "a" * 40
    _native_windows(tmp_path, sha)
    directory = tmp_path / f"windows-candidate-evidence-Rollback-{sha}"
    if corruption == "missing_mode":
        (tmp_path / f"windows-candidate-evidence-Clean-{sha}" / "acceptance.json").unlink()
    elif corruption == "missing_original":
        (directory / "original-app-files.json").unlink()
    else:
        name = {
            "wrong_operation": "rollback-applied.last.json",
            "wrong_owned_hash": "owned-fixtures.json",
            "failed_gui": "gui-business.json",
            "missing_gui_case": "gui-business.json",
            "wrong_snapshot": "natural-rollback-marker.json",
        }.get(corruption, "acceptance.json")
        if corruption in {"failed_gui", "missing_gui_case"}:
            directory = tmp_path / f"windows-candidate-evidence-Gui-{sha}"
        path = directory / name
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        if corruption == "wrong_hash":
            value["candidate_sha256"] = "0" * 64
        if corruption == "fake_check":
            value["checks"] = [{"name": "anything", "passed": True}]
        if corruption == "wrong_operation":
            value["operationId"] = "another-operation"
        if corruption == "wrong_owned_hash":
            value[0]["sha256"] = "0" * 64
        if corruption == "failed_gui":
            value["unfinished"] = ["ai_business"]
        if corruption == "missing_gui_case":
            value["cases"] = value["cases"][:-1]
        if corruption == "wrong_snapshot":
            value["expectedAppFiles"] = {"XCAGI.exe": "0" * 64}
        if corruption == "not_main":
            value["candidate_on_main"] = False
        if corruption in {"wrong_pid", "wrong_runtime", "wrong_data_owner"}:
            field, detail = {
                "wrong_pid": ("old.no_restart", "original pid=999"),
                "wrong_runtime": (
                    "old.runtime_build_identity",
                    f"installed={'b' * 40}; running={'a' * 40}; legacy_health_identity_missing=False; release=old",
                ),
                "wrong_data_owner": (
                    "old.port_owner",
                    r"pid=124; exe=C:\Programs\XCAGI\resources\backend\xcagi-backend.exe; actual_data=C:\another-profile; expected_data=C:\isolated-data",
                ),
            }[corruption]
            next(check for check in value["checks"] if check["name"] == field)["detail"] = detail
        if corruption == "wrong_database":
            next(check for check in value["checks"] if check["name"] == "rollback.database_hash")[
                "detail"
            ] = "sha256=" + "0" * 64
        path.write_text(json.dumps(value))
    result = _module().verify_windows_native(
        tmp_path, release_sha=sha, version="1.0.0.7", installer_sha256="c" * 64
    )
    assert result["passed"] is False
    assert result["blockers"]


def _native_mac(sha):
    return {
        "scope": "installed startup only",
        "startupResult": "PASS",
        "systemIntegration": True,
        "finalCandidatePass": False,
        "version": "1.0.0.7",
        "sha": sha,
        "packageSha": "c" * 64,
        "pid": 123,
        "dataPath": "/tmp/native-data",
        "runtime": {
            "resourcesPath": "/tmp/install/XCAGI.app/Contents/Resources",
            "dataPath": "/tmp/native-data",
        },
        "health": {"version": "1.0.0.7", "git_sha": sha, "runtime": {"status": "healthy"}},
        "ui": {"loginVisible": True},
        "finishedAt": "2026-09-04T00:00:00Z",
    }


def test_native_mac_startup_does_not_claim_ota_or_customer_acceptance():
    sha = "a" * 40
    result = _module().verify_macos_startup(
        _native_mac(sha), release_sha=sha, version="1.0.0.7", installer_sha256="c" * 64
    )
    assert result["passed"] is True
    assert result["ota_rollback"] == result["customer_acceptance"] == "not_verified"


@pytest.mark.parametrize(
    "field,value",
    [
        ("packageSha", "b" * 64),
        ("sha", "b" * 40),
        ("startupResult", "FAIL"),
        ("systemIntegration", False),
        ("finalCandidatePass", True),
        ("pid", 0),
        ("exitError", "process failed to close"),
    ],
)
def test_native_mac_requires_original_package_and_system_startup(field, value):
    sha = "a" * 40
    payload = _native_mac(sha)
    payload[field] = value
    assert (
        _module().verify_macos_startup(
            payload, release_sha=sha, version="1.0.0.7", installer_sha256="c" * 64
        )["passed"]
        is False
    )


def test_native_mac_packaged_probe_fails_before_artifact_publication(tmp_path):
    repo = Path(__file__).resolve().parents[3]
    workflow = yaml.safe_load((repo / "FHD/.github/workflows/release-desktop.yml").read_text())
    steps = workflow["jobs"]["macos"]["steps"]
    probe = next(
        step
        for step in steps
        if step.get("name") == "Install and launch each signed macOS package before publication"
    )
    publish = next(
        step
        for step in steps
        if step.get("with", {}).get("name") == "xcagi-desktop-macos-enterprise"
    )
    assert steps.index(probe) < steps.index(publish)
    assert probe["env"]["XCAGI_ACCEPTANCE_SYSTEM_INTEGRATION"] == "1"
    assert workflow["jobs"]["generate-manifest"]["needs"] == [
        "release-preflight",
        "windows",
        "windows-acceptance",
        "macos",
    ]
    script_dir = tmp_path / "scripts/package"
    script_dir.mkdir(parents=True)
    (script_dir / "acceptance-macos.sh").write_text("exit 27\n")
    artifacts = tmp_path / "release/xcagi-v1.0.0.7/enterprise"
    artifacts.mkdir(parents=True)
    (artifacts / "candidate.dmg").write_bytes(b"fixture package")
    result = subprocess.run(
        ["bash", "-c", probe["run"].replace("${{ inputs.version }}", "1.0.0.7")],
        cwd=tmp_path,
        env={**os.environ, "RUNNER_TEMP": str(tmp_path), "XCAGI_BUILD_SHA": "a" * 40},
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 27, result.stdout + result.stderr


def test_mac_evidence_archive_excludes_installed_application_and_runtime_data(tmp_path):
    repo = Path(__file__).resolve().parents[3]
    workflow = yaml.safe_load((repo / "FHD/.github/workflows/release-desktop.yml").read_text())
    upload = next(
        step
        for step in workflow["jobs"]["macos"]["steps"]
        if step.get("with", {}).get("name") == "xcagi-macos-installed-startup"
    )
    root = tmp_path / "macos-installed-startup/candidate.dmg"
    permitted = {
        "installed-startup.json",
        "startup-verification.json",
        "installed-login.png",
        "videos/probe.webm",
    }
    for name in permitted | {
        "install/XCAGI.app/Contents/Resources/icon.png",
        "install/installed-startup.json",
        "data/xcagi.db",
        "data/installed-login.png",
    }:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture")
    uploaded = {
        path.relative_to(root).as_posix()
        for pattern in upload["with"]["path"].splitlines()
        for path in tmp_path.glob(pattern.removeprefix("${{ runner.temp }}/"))
    }
    assert uploaded == permitted


def test_formal_publication_requires_complete_native_jobs_and_rechecks_original_bytes():
    repo = Path(__file__).resolve().parents[3]
    workflow = yaml.safe_load((repo / "FHD/.github/workflows/release-desktop.yml").read_text())
    acceptance = workflow["jobs"]["windows-acceptance"]
    assert acceptance["needs"] == "windows"
    assert acceptance["uses"] == "./.github/workflows/fhd-windows-candidate-acceptance.yml"
    assert acceptance["secrets"] == "inherit"
    assert (
        acceptance["with"]["current_release_attempt"] == "${{ format('{0}', github.run_attempt) }}"
    )
    # Caller holds no account lock: the reusable workflow owns the single existing lock.
    assert "concurrency" not in workflow
    job = workflow["jobs"]["generate-manifest"]
    assert "windows-acceptance" in job["needs"]
    for dependency in job["needs"]:
        for status in ("success", "failure", "skipped", "cancelled"):
            results = dict.fromkeys(job["needs"], "success")
            results[dependency] = status
            condition = (
                job["if"].replace("always()", "True").replace("inputs.verify_only != true", "True")
            )
            condition = re.sub(
                r"needs\.([\w-]+)\.result == 'success'",
                lambda match: str(results[match[1]] == "success"),
                condition,
            )
            assert eval(condition.replace("&&", "and"), {"__builtins__": {}}, {}) is (
                status == "success"
            ), status
    steps = job["steps"]
    verify = next(
        step
        for step in steps
        if step.get("name")
        == "Verify Windows lifecycle measurements against the bytes being published"
    )
    publish = next(
        step
        for step in steps
        if step.get("name") == "Publish unified Windows + macOS release to CVM"
    )
    assert steps.index(verify) < steps.index(publish)
    assert 'sha256sum "$installer"' in verify["run"]
    for platform in ("windows", "macos"):
        upload = next(
            step
            for step in workflow["jobs"][platform]["steps"]
            if step.get("with", {}).get("name") == f"xcagi-desktop-{platform}-enterprise"
        )
        assert "xcagi-v*/" not in upload["with"]["path"]
        assert all(
            path.startswith("FHD/release/xcagi-v${{ inputs.version }}/enterprise/")
            for path in upload["with"]["path"].splitlines()
        )
    spec = importlib.util.spec_from_file_location(
        "workflow_publisher", repo / "scripts/dev/publish_ci_workflows_to_root.py"
    )
    publisher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(publisher)
    _, rendered = publisher._render_fhd(repo / "FHD/.github/workflows/release-desktop.yml")
    assert yaml.safe_load(rendered)["jobs"]["windows-acceptance"]["uses"] == acceptance["uses"]


@pytest.mark.parametrize("current", [False, True])
@pytest.mark.parametrize(
    "mutation",
    [
        "valid",
        "controller_newer",
        "nonancestor_controller",
        "old_attempt_artifact",
        "changed_attempt",
        "digest",
        "downloaded_bytes",
        "fork",
        "wrong_workflow",
        "failed",
        "incomplete",
    ],
)
def test_native_source_binds_original_zip_bytes_and_attempt(
    tmp_path, monkeypatch, current, mutation
):
    sha, repository = "a" * 40, "fixture/repo"
    controller = "c" * 40 if mutation in {"controller_newer", "nonancestor_controller"} else sha
    _native_windows(tmp_path, sha)
    mod = _module()
    measurements = mod.verify_windows_native(
        tmp_path, release_sha=sha, version="1.0.0.7", installer_sha256="c" * 64
    )
    run = {
        "id": 7,
        "run_attempt": 2,
        "head_sha": controller,
        "head_branch": "main",
        "repository": {"full_name": repository},
        "head_repository": {"full_name": repository},
        "event": "workflow_dispatch",
        "status": "in_progress" if current else "completed",
        "conclusion": None if current else "success",
        "path": ".github/workflows/fhd-release-desktop.yml"
        if current
        else ".github/workflows/fhd-windows-candidate-acceptance.yml",
        "run_started_at": "2026-09-04T00:00:00Z",
        "updated_at": "2026-09-04T00:00:00Z" if current else "2026-09-04T00:30:00Z",
    }
    monkeypatch.setenv("GITHUB_RUN_ID", "7")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "2")
    monkeypatch.setenv("GITHUB_SHA", controller)
    monkeypatch.setenv(
        "GITHUB_WORKFLOW_REF",
        "fixture/repo/.github/workflows/fhd-release-desktop.yml@refs/heads/main",
    )
    artifacts, archives = [], {}
    for number, mode in enumerate(mod.WINDOWS_RESULTS, 11):
        name = f"windows-candidate-evidence-{mode}-{sha}"
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as bundle:
            for path in (tmp_path / name).iterdir():
                bundle.writestr(path.name, path.read_bytes())
        archives[number] = stream.getvalue()
        artifacts.append(
            {
                "id": number,
                "name": name,
                "expired": False,
                "size_in_bytes": len(archives[number]),
                "workflow_run": {"id": 7, "head_sha": controller},
                "created_at": "2026-09-04T00:25:00Z",
                "digest": "sha256:" + hashlib.sha256(archives[number]).hexdigest(),
            }
        )
    listing = {"total_count": 5, "artifacts": artifacts}
    if mutation == "old_attempt_artifact":
        artifacts[0]["created_at"] = "2026-09-03T23:59:00Z"
    if mutation == "digest":
        artifacts[0]["digest"] = "sha256:" + "0" * 64
    if mutation == "fork":
        run["head_repository"] = {"full_name": "fork/repo"}
    if mutation == "wrong_workflow":
        run["path"] = ".github/workflows/unrelated.yml"
    if mutation == "failed":
        run["conclusion"] = "failure"
    if mutation == "incomplete":
        listing["total_count"] = 6
    if mutation == "downloaded_bytes":
        path = tmp_path / f"windows-candidate-evidence-Clean-{sha}/acceptance.json"
        path.write_bytes(path.read_bytes() + b"\n")
    route, readbacks = f"repos/{repository}/actions/runs/7", 0

    def api(path):
        nonlocal readbacks
        if "/compare/" in path:
            return {"status": "diverged" if mutation == "nonancestor_controller" else "ahead"}
        if path == route:
            readbacks += 1
            return (
                {**run, "run_attempt": 3}
                if mutation == "changed_attempt" and readbacks > 1
                else run
            )
        if path.endswith("/attempts/2"):
            return dict(run)
        if path.endswith("/artifacts?per_page=100&page=1"):
            return listing
        if path.endswith("/artifacts?per_page=100&page=2"):
            return {"total_count": 6, "artifacts": []}
        raise AssertionError(path)

    def download(path, destination):
        destination.write_bytes(archives[int(path.split("/")[-2])])

    def verify():
        return mod.verify_windows_provenance(
            tmp_path,
            sources=measurements["sources"],
            repository=repository,
            run_id="7",
            release_sha=sha,
            current_run_attempt=(7, 2) if current else None,
            api=api,
            download=download,
        )

    if mutation in {"valid", "controller_newer"}:
        proof = verify()
        assert set(proof) == set(mod.WINDOWS_RESULTS)
        assert all(row["run_attempt"] == 2 for row in proof.values())
    else:
        with pytest.raises(ValueError):
            verify()
