#!/usr/bin/env python3
"""Validate real server and desktop OTA/rollback acceptance evidence."""

from __future__ import annotations

import argparse
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
DESKTOP_TARGETS = ("macos", "windows10", "windows11")


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
    return {
        "schema": "xcagi.upgrade_rollback_verification/v1",
        "passed": not blockers,
        "release_sha": release_sha,
        "server_rto_minutes": rto if rto != float("inf") else None,
        "server_rpo_minutes": rpo if rpo != float("inf") else None,
        "blockers": blockers,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--release-sha", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    payload = json.loads(args.evidence.read_text(encoding="utf-8"))
    result = verify(payload, release_sha=args.release_sha.lower())
    rendered = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
