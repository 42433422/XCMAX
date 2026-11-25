#!/usr/bin/env python3
"""Recompute desktop measurements; native qualification also needs Actions provenance.

This policy is shared with the producer. Short CI probes and locally submitted
JSON never certify physical devices. The existing release source collector binds
the original workflow attempt, registered runner jobs and immutable report bytes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from typing import Any

MIN_DURATION_SECONDS = 28800
MAX_SAMPLE_GAP_SECONDS = 90
MAX_RSS_BYTES = 2 * 1024**3
MAX_RSS_GROWTH_BYTES = 256 * 1024**2
MAX_HANDLES = 16384
MAX_HANDLE_GROWTH = 512
MAX_AVERAGE_CPU = 80
MAX_SUSTAINED_CPU = 95
MAX_SUSTAINED_CPU_SECONDS = 180
PLATFORMS = {"windows": "Windows", "macos-arm64": "Darwin", "macos-x64": "Darwin"}
ARCHITECTURES = {"windows": "x64", "macos-arm64": "arm64", "macos-x64": "x64"}
SCENARIOS = (
    "renderer_offline",
    "renderer_crash",
    "backend_crash",
    "desktop_restart",
    "multi_window",
    "clean_exit",
)
ENDPOINTS = ("/api/ping", "/api/health", "/api/desktop/status")
GUI_VIEWS = ("settings", "chat", "customers", "products")
FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
MAX_REPORT_BYTES = 16 * 1024**2
MAX_RENDERER_EVENTS = 100


def native_architecture(machine: Any) -> str | None:
    return {
        "amd64": "x64",
        "x86_64": "x64",
        "x64": "x64",
        "arm64": "arm64",
        "aarch64": "arm64",
    }.get(str(machine).lower())


def runner_labels(platform: str) -> set[str]:
    return {
        "self-hosted",
        "xcagi-physical",
        "windows" if platform == "windows" else "macos",
        ARCHITECTURES[platform],
    }


def _number(value: Any) -> bool:
    try:
        return type(value) in (int, float) and math.isfinite(value) and value >= 0
    except OverflowError:
        return False


def _stamp(value: Any) -> datetime | None:
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return stamp.astimezone(UTC) if stamp.tzinfo else None
    except (ValueError, OverflowError):
        return None


def _object(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def verify_platform(
    payload: dict[str, Any],
    *,
    platform: str,
    release_sha: str,
    product_version: str,
) -> dict[str, Any]:
    """Validate observed samples, without asserting their external provenance."""
    blockers: set[str] = set()
    payload = _object(payload)
    if (
        not FULL_SHA.fullmatch(release_sha)
        or payload.get("release_sha") != release_sha
        or payload.get("product_version") != product_version
    ):
        blockers.add("release_identity_mismatch")
    if (
        payload.get("schema") != "xcagi.desktop_soak/v1"
        or platform not in PLATFORMS
        or payload.get("platform") != platform
    ):
        blockers.add("schema_or_platform_mismatch")
    if payload.get("status") != "completed" or payload.get("blockers") != []:
        blockers.add("run_incomplete_or_failed")
    machine = _object(payload.get("machine"))
    if (
        machine.get("system") != PLATFORMS.get(platform)
        or not machine.get("release")
        or native_architecture(machine.get("machine")) != ARCHITECTURES.get(platform)
        or (PLATFORMS.get(platform) == "Darwin" and machine.get("rosetta_translated") is not False)
    ):
        blockers.add("native_os_identity_missing")
    artifact = _object(payload.get("artifact"))
    if (
        artifact.get("build_sha") != release_sha
        or artifact.get("version") != product_version
        or artifact.get("architecture") != ARCHITECTURES.get(platform)
        or any(
            not SHA256.fullmatch(str(artifact.get(key) or ""))
            for key in (
                "executable_sha256",
                "build_info_sha256",
                "app_asar_sha256",
                "backend_sha256",
            )
        )
    ):
        blockers.add("installed_artifact_identity_mismatch")
    requested = payload.get("requested_duration_seconds")
    if not _number(requested) or requested < MIN_DURATION_SECONDS:
        blockers.add("requested_duration_below_eight_hours")
    start, end = _stamp(payload.get("started_at")), _stamp(payload.get("finished_at"))
    if start is None or end is None or end < start:
        blockers.add("run_timestamps_invalid")

    samples = payload.get("samples")
    if not isinstance(samples, list) or not 2 <= len(samples) <= 100000:
        samples = []
        blockers.add("samples_missing_or_invalid")
    valid: list[dict] = []
    for sample in samples:
        row = _object(sample)
        integers = ("root_pid", "backend_pid", "rss_bytes", "handles", "process_count")
        numbers = (
            "elapsed_seconds",
            "root_create_time",
            "backend_create_time",
            "rss_bytes",
            "cpu_percent",
        )
        timestamp = _stamp(row.get("timestamp_utc"))
        if (
            any(type(row.get(key)) is not int or not _number(row[key]) for key in integers)
            or any(not _number(row.get(key)) for key in numbers)
            or not timestamp
            or (start and timestamp < start)
            or (end and timestamp > end)
        ):
            blockers.add("sample_values_invalid")
            continue
        if (
            row["root_pid"] <= 0
            or row["backend_pid"] <= 0
            or row["root_pid"] == row["backend_pid"]
            or row["process_count"] < 2
            or row["root_create_time"] <= 0
            or row["backend_create_time"] <= 0
            or row["rss_bytes"] <= 0
            or row["cpu_percent"] > 100
        ):
            blockers.add("sample_process_measurements_invalid")
            continue
        if (
            row.get("gui") is not True
            or row.get("gui_view") not in GUI_VIEWS
            or any(
                _object(row.get("endpoints")).get(endpoint) is not True for endpoint in ENDPOINTS
            )
        ):
            blockers.add("sample_readiness_failed")
        valid.append({**row, "utc": timestamp})

    duration = 0.0
    summary: dict[str, Any] = {"sample_count": len(samples)}
    summary["gui_view_counts"] = {
        view: sum(row.get("gui_view") == view for row in valid) for view in GUI_VIEWS
    }
    if not all(summary["gui_view_counts"].values()):
        blockers.add("gui_navigation_coverage_incomplete")
    if len(valid) >= 2:
        first, last = valid[0], valid[-1]
        duration = last["elapsed_seconds"] - first["elapsed_seconds"]
        if duration < MIN_DURATION_SECONDS or (_number(requested) and duration < requested):
            blockers.add("measured_duration_below_requirement")
        identities = {
            (r["root_pid"], r["root_create_time"], r["backend_pid"], r["backend_create_time"])
            for r in valid
        }
        if len(identities) != 1:
            blockers.add("unexpected_process_restart_during_soak")
        weighted_cpu, sustained = 0.0, 0.0
        for before, after in zip(valid, valid[1:]):
            delta = after["elapsed_seconds"] - before["elapsed_seconds"]
            wall_delta = (after["utc"] - before["utc"]).total_seconds()
            if (
                not 0 < delta <= MAX_SAMPLE_GAP_SECONDS
                or not 0 < wall_delta <= MAX_SAMPLE_GAP_SECONDS
            ):
                blockers.add("sample_gap_or_sequence_invalid")
            if abs(delta - wall_delta) > 5:
                blockers.add("monotonic_wall_clock_mismatch")
            weighted_cpu += after["cpu_percent"] * max(0.0, min(delta, MAX_SAMPLE_GAP_SECONDS))
            sustained = (
                sustained + max(0.0, delta) if after["cpu_percent"] >= MAX_SUSTAINED_CPU else 0.0
            )
            if sustained > MAX_SUSTAINED_CPU_SECONDS:
                blockers.add("sustained_cpu_exceeded")
        average_cpu = weighted_cpu / duration if duration > 0 else 100.0
        if average_cpu > MAX_AVERAGE_CPU:
            blockers.add("average_cpu_exceeded")
        # Compare settled five-minute windows, avoiding normal startup allocations.
        baseline = [
            row for row in valid if 300 <= row["elapsed_seconds"] - first["elapsed_seconds"] <= 600
        ]
        recent = [row for row in valid if last["elapsed_seconds"] - row["elapsed_seconds"] <= 300]
        if not baseline or not recent:
            blockers.add("resource_windows_missing")
        for field, maximum, growth_limit in (
            ("rss_bytes", MAX_RSS_BYTES, MAX_RSS_GROWTH_BYTES),
            ("handles", MAX_HANDLES, MAX_HANDLE_GROWTH),
        ):
            peak = max(row[field] for row in valid)
            growth = (
                median(row[field] for row in recent) - median(row[field] for row in baseline)
                if baseline and recent
                else None
            )
            summary[f"peak_{field}"] = peak
            summary[f"growth_{field}"] = growth
            if peak > maximum or (growth is not None and growth > growth_limit):
                blockers.add(f"{field}_budget_exceeded")
        summary["average_cpu_percent"] = average_cpu
        if abs((last["utc"] - first["utc"]).total_seconds() - duration) > MAX_SAMPLE_GAP_SECONDS:
            blockers.add("monotonic_wall_clock_mismatch")
    else:
        blockers.add("measured_duration_below_requirement")

    previous_finish = valid[-1]["utc"] if valid else start
    scenarios = _object(payload.get("scenarios"))
    for name in SCENARIOS:
        scenario = _object(scenarios.get(name))
        began, finished = _stamp(scenario.get("started_at")), _stamp(scenario.get("finished_at"))
        if scenario.get("passed") is not True:
            blockers.add(f"scenario_failed_or_missing:{name}")
        if (
            not began
            or not finished
            or not previous_finish
            or not end
            or not previous_finish <= began <= finished <= end
        ):
            blockers.add(f"scenario_sequence_invalid:{name}")
        previous_finish = finished
        if name in ("backend_crash", "desktop_restart"):
            before, after = scenario.get("before_pid"), scenario.get("after_pid")
            if (
                type(before) is not int
                or type(after) is not int
                or before <= 0
                or after <= 0
                or before == after
                or scenario.get("recovered") is not True
            ):
                blockers.add(f"scenario_recovery_unobserved:{name}")
            field = "backend_pid" if name == "backend_crash" else "root_pid"
            if not valid or before != valid[-1][field]:
                blockers.add(f"scenario_wrong_original_process:{name}")
        if name == "renderer_offline" and (
            scenario.get("offline_observed") is not True or scenario.get("recovered") is not True
        ):
            blockers.add("renderer_offline_transition_unobserved")
        if name == "renderer_crash" and (
            scenario.get("crashed_observed") is not True or scenario.get("recovered") is not True
        ):
            blockers.add("renderer_crash_recovery_unobserved")
        if name == "multi_window" and (
            type(scenario.get("opened")) is not int
            or scenario["opened"] < 2
            or type(scenario.get("remaining")) is not int
            or scenario["remaining"] != 1
        ):
            blockers.add("multi_window_cleanup_unobserved")
        if name == "clean_exit" and (
            type(scenario.get("remaining_processes")) is not int
            or scenario["remaining_processes"] != 0
        ):
            blockers.add("clean_exit_processes_remaining")
    events = payload.get("events")
    if not isinstance(events, list):
        events = []
        blockers.add("renderer_events_missing_or_invalid")
    summary["renderer_event_count"] = len(events)
    if len(events) > MAX_RENDERER_EVENTS:
        blockers.add("renderer_event_limit_exceeded")
    previous_event = start
    for value in events[:MAX_RENDERER_EVENTS]:
        event = _object(value)
        when = _stamp(event.get("timestamp_utc"))
        if (
            event.get("kind") not in ("renderer_crash", "renderer_page_error")
            or event.get("phase") not in ("launch", "login", "steady", *SCENARIOS)
            or not isinstance(event.get("timestamp_utc"), str)
            or not when
            or not start
            or not end
            or not previous_event
            or not start <= previous_event <= when <= end
            or (
                "message_sha256" in event
                and (
                    not isinstance(event["message_sha256"], str)
                    or not SHA256.fullmatch(event["message_sha256"])
                )
            )
        ):
            blockers.add("renderer_event_invalid")
            continue
        previous_event = when
        crash = _object(scenarios.get("renderer_crash"))
        began, finished = _stamp(crash.get("started_at")), _stamp(crash.get("finished_at"))
        if not (
            event["kind"] == event["phase"] == "renderer_crash"
            and began
            and finished
            and began <= when <= finished
        ):
            blockers.add("unexpected_renderer_event")
    return {
        "passed": not blockers,
        "verification_scope": "measurement_validation",
        "platform": platform,
        "architecture": ARCHITECTURES.get(platform),
        "measured_duration_seconds": max(0.0, duration),
        "summary": summary,
        "blockers": sorted(blockers),
    }


def _load(path: Path) -> tuple[dict, str]:
    with path.open("rb") as stream:
        raw = stream.read(MAX_REPORT_BYTES + 1)
    if len(raw) > MAX_REPORT_BYTES:
        raise ValueError("measurement report missing or too large")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("measurement report must be an object")
    return value, hashlib.sha256(raw).hexdigest()


def verify_files(
    paths: dict[str, Path],
    *,
    release_sha: str,
    product_version: str,
    provenance: dict | None = None,
) -> dict[str, Any]:
    per_platform, raw, digests = {}, {}, {}
    for platform in PLATFORMS:
        try:
            raw[platform], digests[platform] = _load(paths[platform])
            per_platform[platform] = verify_platform(
                raw[platform],
                platform=platform,
                release_sha=release_sha,
                product_version=product_version,
            )
        except (OSError, ValueError, KeyError):
            per_platform[platform] = {
                "passed": False,
                "platform": platform,
                "blockers": ["raw_report_missing_or_invalid"],
            }
    blockers = [
        f"{platform}:{reason}"
        for platform, result in per_platform.items()
        for reason in result["blockers"]
    ]
    measurements_passed = not blockers
    proof = _object(provenance)
    source = _object(_object(proof.get("sources")).get("desktop_soak"))
    jobs = _object(source.get("native_jobs"))
    provenance_valid = (
        proof.get("release_sha") == release_sha
        and source.get("workflow") == "fhd-desktop-soak.yml"
        and FULL_SHA.fullmatch(str(source.get("controller_sha") or "")) is not None
        and re.fullmatch(r"sha256:[0-9a-f]{64}", str(source.get("artifact_digest") or ""))
        is not None
        and all(
            type(source.get(key)) is int and source[key] > 0
            for key in ("run_id", "run_attempt", "artifact_id")
        )
        and source.get("reports") == digests
        and set(digests) == set(PLATFORMS)
    )
    runner_ids = set()
    for platform in PLATFORMS:
        job, payload = _object(jobs.get(platform)), raw.get(platform, {})
        machine = _object(payload.get("machine"))
        labels = job.get("labels") if isinstance(job.get("labels"), list) else []
        job_start, job_end = _stamp(job.get("started_at")), _stamp(job.get("completed_at"))
        start, end = _stamp(payload.get("started_at")), _stamp(payload.get("finished_at"))
        if not (
            type(job.get("runner_id")) is int
            and job["runner_id"] > 0
            and machine.get("runner_environment") == "self-hosted"
            and machine.get("runner_name")
            and machine["runner_name"] == job.get("runner_name")
            and runner_labels(platform) <= {str(label).lower() for label in labels}
            and job_start
            and start
            and end
            and job_end
            and job_start <= start <= end <= job_end
        ):
            provenance_valid = False
        runner_ids.add(str(job.get("runner_id")))
    if len(runner_ids) != len(PLATFORMS):
        provenance_valid = False
    if not provenance_valid:
        blockers.append("original_native_workflow_provenance_missing_or_invalid")
    return {
        "schema": "xcagi.desktop_soak_verification/v1",
        "release_sha": release_sha,
        "product_version": product_version,
        "passed": not blockers,
        "measurements_passed": measurements_passed,
        "verification_scope": "registered_native_runner"
        if provenance_valid
        else "local_measurements",
        "per_platform": per_platform,
        "blockers": blockers,
    }


def verify_bundle(
    directory: Path | None,
    *,
    release_sha: str,
    product_version: str,
    provenance: dict | None = None,
) -> dict[str, Any]:
    paths = (
        {platform: directory / f"{platform}.json" for platform in PLATFORMS} if directory else {}
    )
    return verify_files(
        paths, release_sha=release_sha, product_version=product_version, provenance=provenance
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--windows", type=Path, required=True)
    parser.add_argument(
        "--macos", type=Path, help="Legacy arm64 report path; x64 evidence is still required"
    )
    parser.add_argument("--macos-arm64", type=Path)
    parser.add_argument("--macos-x64", type=Path)
    parser.add_argument("--release-sha", required=True)
    parser.add_argument("--product-version", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--measurements-only",
        action="store_true",
        help="Validate measurements only; output cannot certify native provenance.",
    )
    args = parser.parse_args()
    result = verify_files(
        {
            platform: path
            for platform, path in {
                "windows": args.windows,
                "macos-arm64": args.macos_arm64 or args.macos,
                "macos-x64": args.macos_x64,
            }.items()
            if path is not None
        },
        release_sha=args.release_sha,
        product_version=args.product_version,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if args.measurements_only and result["measurements_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
