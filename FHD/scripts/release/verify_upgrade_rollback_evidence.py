#!/usr/bin/env python3
"""Verify native release measurements and separately register unmeasured claims.

The legacy input has no authenticated machine observations: its booleans,
timestamps and hashes are supplied by the caller.  Schema validation must never
be promoted into proof that the production/physical-device exercises occurred.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import ntpath
import os
import re
import subprocess
import sys
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
DESKTOP_TARGETS = ("macos", "windows10", "windows11")
MAX_NATIVE_ARCHIVE_BYTES = 512 * 1024 * 1024  # Existing producers preserve screenshots/video.
WINDOWS_RESULTS = {
    "Clean": "passed",
    "Upgrade": "passed",
    "Gui": "gui_regression_passed",
    "Recovery": "gui_recovery_regression_passed",
    "Rollback": "rollback_passed",
}
GUI_CASES = {
    "normal_login",
    "tenant_identity",
    "customer",
    "product",
    "shipment_unit_readback",
    "visible_version",
    "purchase",
    "purchase_inbound",
    "sales_order",
    "shipping_delivery_export",
    "stock_out",
    "ui_readback",
    "ai_business",
}


def _read_native(root: Path, name: str, sources: dict[str, str]) -> Any:
    path = root / name
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("native evidence must stay inside its original artifact")
    if path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError("native evidence exceeds the per-file size limit")
    raw = path.read_bytes()
    sources[name] = hashlib.sha256(raw).hexdigest()
    return json.loads(raw.decode("utf-8-sig"))


def _native_windows_processes(row: dict, release_sha: str) -> None:
    """Recheck the existing PowerShell producer's observed PID/path/build details."""
    checks = row["checks"]
    for index, check in enumerate(checks):
        if not check["name"].endswith(".first_start_ready"):
            continue
        label = check["name"].split(".")[0]
        identity, owner, alive = checks[index + 1 : index + 4]
        pid = re.fullmatch(
            r"health=([^;]+); blockers=0; readyForUi=True; pid=([1-9]\d*)", check["detail"]
        )
        observed = dict(part.split("=", 1) for part in identity["detail"].split("; "))
        expected = row["baseline_sha"] if label == "old" else release_sha
        process = re.fullmatch(
            r"pid=([1-9]\d*); exe=(.+); actual_data=(.+); expected_data=(.+)", owner["detail"]
        )
        if (
            not pid
            or pid[1] == "unhealthy"
            or identity["name"] != f"{label}.runtime_build_identity"
            or observed.get("installed") != expected
            or (
                observed.get("running") != expected
                and not (
                    label == "old"
                    and observed.get("running") == ""
                    and observed.get("legacy_health_identity_missing") == "True"
                )
            )
            or owner["name"] != f"{label}.port_owner"
            or not process
            or not ntpath.isabs(process[2])
            or ntpath.basename(process[2]).lower() != "xcagi-backend.exe"
            or not ntpath.isabs(process[3])
            or ntpath.normcase(process[3]) != ntpath.normcase(process[4])
            or alive["name"] != f"{label}.no_restart"
            or alive["detail"] != f"original pid={pid[2]}"
        ):
            raise ValueError("native PID, installed/running build, or data owner mismatch")


def verify_windows_native(
    root: Path,
    *,
    release_sha: str,
    version: str,
    installer_sha256: str,
) -> dict[str, Any]:
    """Re-read the existing five-mode producer, after Actions provenance verification.

    The original artifacts must come from the verified main-branch
    windows-candidate-acceptance workflow.  This validates its measurements, not
    customer Win10/Win11 coverage, and cannot turn submitted claims into proof.
    """
    blockers: list[str] = []
    sources: dict[str, str] = {}
    modes: dict[str, dict] = {}
    now = datetime.now(UTC)
    if not FULL_SHA.fullmatch(release_sha) or not SHA256.fullmatch(installer_sha256):
        blockers.append("windows_candidate_identity_invalid")
    required = {
        "Clean": {"candidate.login", "candidate.enterprise", "build_info", "backup_restore_copy"},
        "Upgrade": {
            "old_installer_hash",
            "app_update.candidate_build",
            "upgrade.health_commit",
            "owned_state.verify",
            "owned_state.main-verify",
            "retention.uninstalled",
        },
        "Gui": {"normal_gui_business"},
        "Recovery": {"normal_gui_faults", "backup_restore_copy", "backup_restore_enterprise"},
        "Rollback": {
            "old_installer_hash",
            "app_update.natural_marker",
            "app_update.natural_database_backup",
            "rollback.database_changed",
            "rollback.database_hash",
            "rollback.app_file_hashes",
            "rollback.same_enterprise",
            "owned_state.verify",
            "owned_state.main-verify",
        },
    }
    for mode, expected in WINDOWS_RESULTS.items():
        prefix = f"windows-candidate-evidence-{mode}-{release_sha}"
        try:
            row = _read_native(root, f"{prefix}/acceptance.json", sources)
            if not isinstance(row, dict):
                raise ValueError("acceptance must be an object")
            checks = row.get("checks")
            check_names = (
                {item.get("name") for item in checks if isinstance(item, dict)}
                if isinstance(checks, list)
                else set()
            )
            names = {"account_configuration", "isolated_runner", "isolated_tasks"} | required[mode]
            label = "old" if mode == "Rollback" else "candidate"
            names |= {
                f"{label}.{name}"
                for name in (
                    "first_start_ready",
                    "runtime_build_identity",
                    "port_owner",
                    "no_restart",
                )
            }
            if (
                row.get("mode") != mode
                or row.get("result") != expected
                or row.get("candidate_sha") != release_sha
                or row.get("candidate_sha256") != installer_sha256
                or row.get("candidate_on_main") is not True
                or not checks
                or not names <= check_names
                or any(
                    not isinstance(check, dict) or check.get("passed") is not True
                    for check in checks
                )
                or row.get("customer_acceptance") != "not_verified"
                or not isinstance(row.get("runner"), dict)
                or "Windows" not in str(row["runner"].get("caption", ""))
            ):
                raise ValueError("native mode identity, checks, or runner scope mismatch")
            start = _time(row, "started_at", blockers, mode)
            end = _time(row, "finished_at", blockers, mode)
            if not start or not end or not start <= end <= now:
                raise ValueError("native mode time sequence invalid")
            _native_windows_processes(row, release_sha)
            if mode in {"Gui", "Recovery"}:
                gui = _read_native(root, f"{prefix}/gui-business.json", sources)
                cases = GUI_CASES | (
                    {"controlled_stock_failure", "authorization_cancel"}
                    if mode == "Recovery"
                    else set()
                )
                if (
                    not isinstance(gui, dict)
                    or gui.get("result") != "business_regression_passed"
                    or gui.get("phase") != ("business" if mode == "Gui" else "faults")
                    or gui.get("unfinished") != []
                    or not gui.get("cases")
                    or not cases <= {case["id"] for case in gui["cases"]}
                    or gui.get("full_customer_acceptance") != "not_verified"
                    or any(case.get("status") != "passed" for case in gui["cases"])
                ):
                    raise ValueError("native GUI regression incomplete")
            modes[mode] = row
        except (OSError, ValueError, TypeError, AttributeError, KeyError):
            blockers.append(f"windows_{mode.lower()}_native_evidence_invalid")
    if "Rollback" in modes:
        try:
            row = modes["Rollback"]
            prefix = f"windows-candidate-evidence-Rollback-{release_sha}"
            marker = _read_native(root, f"{prefix}/natural-rollback-marker.json", sources)
            applied = _read_native(root, f"{prefix}/rollback-applied.last.json", sources)
            owned = _read_native(root, f"{prefix}/owned-fixtures.json", sources)
            app = _read_native(root, f"{prefix}/original-app-files.json", sources)
            old = f"{row['baseline_version']}+{row['baseline_sha']}"
            new = f"{version}+{release_sha}"
            if (
                not FULL_SHA.fullmatch(row["baseline_sha"])
                or row["baseline_sha"] == release_sha
                or marker.get("mode") != "windows-full"
                or marker.get("fromVersion") != old
                or marker.get("toVersion") != new
                or applied.get("fromVersion") != new
                or applied.get("toVersion") != old
                or not applied.get("operationId")
                or not applied.get("reason")
                or (marker.get("operationId") and applied["operationId"] != marker["operationId"])
                or not isinstance(app, dict)
                or not app
                or any(not SHA256.fullmatch(value) for value in app.values())
                or marker.get("expectedAppFiles") != app
                or not isinstance(owned, list)
                or not owned
                or not any(item.get("absolute_length") == 261 for item in owned)
                or any(
                    not SHA256.fullmatch(item["sha256"])
                    or marker.get("expectedOwnedFiles", {}).get(item["path"]) != item["sha256"]
                    for item in owned
                )
            ):
                raise ValueError("native rollback artifacts do not identify the same transaction")
            prepared = _time(marker, "preparedAt", blockers, "windows_rollback")
            started = _time(applied, "appliedAt", blockers, "windows_rollback")
            completed = _time(applied, "completedAt", blockers, "windows_rollback")
            if (
                not prepared
                or not started
                or not completed
                or not prepared <= started <= completed <= now
            ):
                raise ValueError("native rollback event order invalid")
            digests = {
                item["name"]: str(item.get("detail", "")).removeprefix("sha256=")
                for item in row["checks"]
                if item["name"] in {"app_update.natural_database_backup", "rollback.database_hash"}
            }
            before = digests.get("app_update.natural_database_backup", "")
            if (
                not SHA256.fullmatch(before)
                or digests.get("rollback.database_hash") != before
                or marker.get("expectedDatabaseSha256") != before
            ):
                raise ValueError("native restored database differs from the original snapshot")
        except (OSError, ValueError, TypeError, AttributeError, KeyError):
            blockers.append("windows_rollback_raw_transaction_invalid")
    return {
        "schema": "xcagi.windows_lifecycle_measurements/v1",
        "passed": not blockers,
        "verification_scope": "native_windows_runner_lifecycle",
        "customer_acceptance": "not_verified",
        "release_sha": release_sha,
        "installer_sha256": installer_sha256,
        "modes": sorted(modes),
        "sources": sources,
        "blockers": blockers,
    }


def verify_macos_startup(
    payload: dict[str, Any],
    *,
    release_sha: str,
    version: str,
    installer_sha256: str,
) -> dict[str, Any]:
    """Bind the existing installed Playwright probe to the actual signed DMG."""
    if not isinstance(payload, dict):
        payload = {}
    runtime = payload.get("runtime") or {}
    health = payload.get("health") or {}
    blockers: list[str] = []
    if not FULL_SHA.fullmatch(release_sha) or not SHA256.fullmatch(installer_sha256):
        blockers.append("macos_candidate_identity_invalid")
    if (
        payload.get("scope") != "installed startup only"
        or payload.get("startupResult") != "PASS"
        or payload.get("systemIntegration") is not True
        or payload.get("finalCandidatePass") is not False
        or payload.get("version") != version
        or payload.get("sha") != release_sha
        or payload.get("packageSha") != installer_sha256
        or type(payload.get("pid")) is not int
        or payload["pid"] <= 0
        or not isinstance(runtime, dict)
        or not runtime.get("resourcesPath")
        or runtime.get("dataPath") != payload.get("dataPath")
        or not isinstance(health, dict)
        or health.get("git_sha") != release_sha
        or health.get("version") != version
        or not isinstance(health.get("runtime"), dict)
        or health["runtime"].get("status") != "healthy"
        or not isinstance(payload.get("ui"), dict)
        or payload["ui"].get("loginVisible") is not True
        or payload.get("error")
        or payload.get("exitError")
    ):
        blockers.append("macos_installed_startup_measurements_invalid")
    finished = _time(payload, "finishedAt", blockers, "macos_startup")
    if finished and finished > datetime.now(UTC):
        blockers.append("macos_startup_timestamp_in_future")
    return {
        "schema": "xcagi.macos_startup_measurements/v1",
        "passed": not blockers,
        "verification_scope": "native_installed_startup",
        "release_sha": release_sha,
        "installer_sha256": installer_sha256,
        "customer_acceptance": "not_verified",
        "ota_rollback": "not_verified",
        "blockers": blockers,
    }


def verify_native_run(
    *,
    repository: str,
    run_id: str,
    release_sha: str,
    current_run_attempt: tuple[int, int] | None = None,
    api=None,
) -> dict[str, Any]:
    """Authenticate completed standalone acceptance or this exact formal caller."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from build_closure_reports import _github_api

    if (
        not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository or "")
        or not re.fullmatch(r"[1-9][0-9]*", run_id or "")
        or not FULL_SHA.fullmatch(release_sha)
    ):
        raise ValueError("native source repository and run are required")
    if current_run_attempt is not None and (
        current_run_attempt
        != (int(os.environ["GITHUB_RUN_ID"]), int(os.environ["GITHUB_RUN_ATTEMPT"]))
        or os.environ.get("GITHUB_WORKFLOW_REF")
        != f"{repository}/.github/workflows/fhd-release-desktop.yml@refs/heads/main"
    ):
        raise ValueError("only the current formal release may consume in-progress measurements")
    api = api or _github_api
    run = api(f"repos/{repository}/actions/runs/{run_id}")
    attempt, controller = run.get("run_attempt"), run.get("head_sha", "")
    same_run = current_run_attempt is not None
    workflow = "fhd-release-desktop.yml" if same_run else "fhd-windows-candidate-acceptance.yml"
    if not (
        str(run.get("id")) == run_id
        and type(attempt) is int
        and attempt > 0
        and run.get("repository", {}).get("full_name") == repository
        and run.get("head_repository", {}).get("full_name") == repository
        and run.get("path") == f".github/workflows/{workflow}"
        and run.get("head_branch") == "main"
        and run.get("event") == "workflow_dispatch"
        and FULL_SHA.fullmatch(controller)
        and (
            (
                same_run
                and current_run_attempt == (run["id"], attempt)
                and controller == os.environ.get("GITHUB_SHA")
                and run.get("status") == "in_progress"
                and run.get("conclusion") is None
            )
            or (
                not same_run
                and run.get("status") == "completed"
                and run.get("conclusion") == "success"
            )
        )
    ):
        raise ValueError("native source workflow or attempt mismatch")
    if controller != release_sha and any(
        api(f"repos/{repository}/compare/{base}...{head}").get("status")
        not in {"ahead", "identical"}
        for base, head in ((release_sha, controller), (controller, "main"))
    ):
        raise ValueError("native source controller is outside the release mainline")
    return run


def verify_windows_provenance(
    root: Path,
    *,
    sources: dict[str, str],
    repository: str,
    run_id: str,
    release_sha: str,
    current_run_attempt: tuple[int, int] | None = None,
    api=None,
    download=None,
) -> dict[str, Any]:
    """Bind each consumed raw file to the original Actions ZIP and current attempt."""
    run = verify_native_run(
        repository=repository,
        run_id=run_id,
        release_sha=release_sha,
        current_run_attempt=current_run_attempt,
        api=api,
    )
    from build_closure_reports import _download, _github_api, collect_source_artifact

    api, download = api or _github_api, download or _download
    proof = {}
    with tempfile.TemporaryDirectory(prefix="windows-native-source-") as temporary:
        original = Path(temporary)
        for mode in WINDOWS_RESULTS:
            name = f"windows-candidate-evidence-{mode}-{release_sha}"
            if f"{name}/acceptance.json" not in sources:
                raise ValueError("native measurements were not consumed for every mode")
            proof[mode] = collect_source_artifact(
                repository=repository,
                run=run,
                name=name,
                label=name,
                output_dir=original,
                api=api,
                download=download,
                current_run_attempt=current_run_attempt,
                max_archive_bytes=MAX_NATIVE_ARCHIVE_BYTES,
            )
            for filename, digest in sources.items():
                if not filename.startswith(f"{name}/"):
                    continue
                observed: dict[str, str] = {}
                _read_native(root, filename, observed)
                if (
                    hashlib.sha256((original / filename).read_bytes()).hexdigest() != digest
                    or observed[filename] != digest
                ):
                    raise ValueError(
                        "downloaded native measurements differ from the original artifact"
                    )
    return proof


def _time(row: dict[str, Any], field: str, blockers: list[str], prefix: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(row.get(field) or "").replace("Z", "+00:00"))
    except ValueError:
        parsed = None
    if parsed is None or parsed.tzinfo is None:
        blockers.append(f"{prefix}_{field}_invalid")
        return None
    return parsed.astimezone(UTC)


def verify(payload: dict[str, Any], *, release_sha: str) -> dict[str, Any]:
    blockers: list[str] = []
    if not FULL_SHA.fullmatch(release_sha):
        blockers.append("release_sha_invalid")
    server = payload.get("server") if isinstance(payload.get("server"), dict) else {}
    if server.get("environment") != "production" or server.get("real_execution") is not True:
        blockers.append("server_real_production_rollback_missing")
    for field in ("rollback_workflow_run_id", "forward_workflow_run_id"):
        if not str(server.get(field) or "").strip():
            blockers.append(f"server_{field}_missing")
    previous_sha = str(server.get("previous_release_sha") or "").lower()
    if not FULL_SHA.fullmatch(previous_sha) or previous_sha == release_sha:
        blockers.append("server_previous_release_sha_invalid")
    if str(server.get("failed_release_sha") or "").lower() != release_sha:
        blockers.append("server_failed_release_sha_mismatch")
    if str(server.get("rollback_release_sha") or "").lower() != previous_sha:
        blockers.append("server_rollback_release_sha_mismatch")
    if str(server.get("forward_release_sha") or "").lower() != release_sha:
        blockers.append("server_forward_release_sha_mismatch")
    if not SHA256.fullmatch(str(server.get("evidence_sha256") or "").lower()):
        blockers.append("server_evidence_digest_invalid")

    detected_at = _time(server, "failure_detected_at", blockers, "server")
    rollback_started_at = _time(server, "rollback_started_at", blockers, "server")
    restored_at = _time(server, "restored_at", blockers, "server")
    forwarded_at = _time(server, "forwarded_at", blockers, "server")
    last_write_at = _time(server, "last_confirmed_write_at", blockers, "server")
    recovered_through_at = _time(server, "recovered_through_at", blockers, "server")
    rto = (
        (restored_at - detected_at).total_seconds() / 60
        if detected_at and restored_at and restored_at >= detected_at
        else float("inf")
    )
    rpo = (
        max(0.0, (last_write_at - recovered_through_at).total_seconds() / 60)
        if last_write_at and recovered_through_at
        else float("inf")
    )
    if not (
        detected_at
        and rollback_started_at
        and restored_at
        and forwarded_at
        and detected_at <= rollback_started_at <= restored_at <= forwarded_at
    ):
        blockers.append("server_event_sequence_invalid")
    if rto > 30:
        blockers.append("server_rto_exceeds_30_minutes")
    if rpo > 5:
        blockers.append("server_rpo_exceeds_5_minutes")
    if server.get("data_consistent") is not True or server.get("forward_passed") is not True:
        blockers.append("server_data_or_forward_verification_failed")

    desktops = payload.get("desktops") if isinstance(payload.get("desktops"), dict) else {}
    for target in DESKTOP_TARGETS:
        row = desktops.get(target) if isinstance(desktops.get(target), dict) else {}
        if (
            row.get("real_machine") is not True
            or row.get("controlled_acceptance_device") is not True
        ):
            blockers.append(f"{target}_real_controlled_device_missing")
        from_sha = str(row.get("from_build_sha") or "").lower()
        if not FULL_SHA.fullmatch(from_sha) or from_sha == release_sha:
            blockers.append(f"{target}_from_sha_invalid")
        if str(row.get("installed_build_sha") or "").lower() != release_sha:
            blockers.append(f"{target}_installed_sha_mismatch")
        if str(row.get("rollback_build_sha") or "").lower() != from_sha:
            blockers.append(f"{target}_rollback_sha_mismatch")
        if str(row.get("forward_build_sha") or "").lower() != release_sha:
            blockers.append(f"{target}_forward_sha_mismatch")
        if row.get("fault_injection_scope") != "controlled_acceptance_device":
            blockers.append(f"{target}_fault_scope_invalid")
        if target == "windows10" and not str(row.get("os_version") or "").startswith("10."):
            blockers.append("windows10_os_version_invalid")
        if target == "windows11" and not str(row.get("os_version") or "").startswith("11."):
            blockers.append("windows11_os_version_invalid")
        for field in ("ota_passed", "cold_start_passed", "fault_rollback_passed", "data_retained"):
            if row.get(field) is not True:
                blockers.append(f"{target}_{field}_failed")
        if not SHA256.fullmatch(str(row.get("evidence_sha256") or "").lower()):
            blockers.append(f"{target}_evidence_digest_invalid")
        before_digest = str(row.get("data_before_sha256") or "").lower()
        after_digest = str(row.get("data_after_sha256") or "").lower()
        if not SHA256.fullmatch(before_digest) or after_digest != before_digest:
            blockers.append(f"{target}_data_digest_mismatch")
        event_times = [
            _time(row, field, blockers, target)
            for field in (
                "ota_started_at",
                "installed_at",
                "cold_started_at",
                "fault_injected_at",
                "rolled_back_at",
                "forwarded_at",
            )
        ]
        if any(value is None for value in event_times) or event_times != sorted(event_times):
            blockers.append(f"{target}_event_sequence_invalid")
    structural_passed = not blockers
    blockers.append("independent_native_measurements_missing")
    return {
        "schema": "xcagi.upgrade_rollback_verification/v1",
        "passed": False,
        "structural_passed": structural_passed,
        "verification_scope": "submitted_claims",
        "release_sha": release_sha,
        "server_rto_minutes": rto if rto != float("inf") else None,
        "server_rpo_minutes": rpo if rpo != float("inf") else None,
        "blockers": blockers,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--evidence", type=Path)
    source.add_argument("--windows-native-dir", type=Path)
    source.add_argument("--macos-startup", type=Path)
    parser.add_argument("--release-sha", required=True)
    parser.add_argument("--version", default="")
    parser.add_argument("--installer-sha256", default="")
    parser.add_argument("--repository")
    parser.add_argument("--source-run-id")
    parser.add_argument("--current-run-attempt", type=int)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--register-claims",
        action="store_true",
        help="Validate and archive claims only; the result remains passed=false.",
    )
    args = parser.parse_args()
    source_requested = any(
        value is not None
        for value in (args.repository, args.source_run_id, args.current_run_attempt)
    )
    if source_requested and not args.windows_native_dir:
        parser.error("Actions source arguments require --windows-native-dir")
    if args.windows_native_dir or args.macos_startup:
        if args.register_claims or not re.fullmatch(r"[0-9]+(?:\.[0-9]+){3}", args.version):
            parser.error("native measurements require a product version and cannot register claims")
        kwargs = {
            "release_sha": args.release_sha,
            "version": args.version,
            "installer_sha256": args.installer_sha256,
        }
        result = (
            verify_windows_native(args.windows_native_dir, **kwargs)
            if args.windows_native_dir
            else verify_macos_startup(
                json.loads(args.macos_startup.read_text(encoding="utf-8")), **kwargs
            )
        )
        if result["passed"] and args.windows_native_dir and source_requested:
            try:
                current = None
                if args.current_run_attempt is not None:
                    current = (int(args.source_run_id), args.current_run_attempt)
                result["provenance"] = verify_windows_provenance(
                    args.windows_native_dir,
                    sources=result["sources"],
                    repository=args.repository,
                    run_id=args.source_run_id,
                    release_sha=args.release_sha,
                    current_run_attempt=current,
                )
            except (
                OSError,
                ValueError,
                TypeError,
                KeyError,
                AttributeError,
                subprocess.SubprocessError,
                zipfile.BadZipFile,
            ) as error:
                result["passed"] = False
                result["blockers"].append(f"windows_native_source_invalid:{type(error).__name__}")
    else:
        payload = json.loads(args.evidence.read_text(encoding="utf-8"))
        result = verify(payload, release_sha=args.release_sha.lower())
    rendered = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if result["passed"] or (args.register_claims and result["structural_passed"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
