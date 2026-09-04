#!/usr/bin/env python3
"""Require two zero-finding scans for the same SHA on consecutive UTC days."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from security_release_gate import REQUIRED_SCANNERS, evaluate


def _scan_day(directory: Path):
    days = set()
    for scanner in REQUIRED_SCANNERS:
        payload = json.loads((directory / f"{scanner}.json").read_text(encoding="utf-8"))
        days.add(
            datetime.fromisoformat(str(payload["scanned_at"]).replace("Z", "+00:00"))
            .astimezone(UTC)
            .date()
        )
    if len(days) != 1:
        raise ValueError("scanner timestamps do not share one UTC date")
    return days.pop()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--previous-dir", type=Path, required=True)
    parser.add_argument("--current-dir", type=Path, required=True)
    parser.add_argument("--release-sha", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    # The current report must be <24h; the preceding calendar-day proof may be
    # up to 48h old solely to prove the required second daily zero scan.
    previous = evaluate(args.previous_dir, max_age_hours=48, release_sha=args.release_sha)
    current = evaluate(args.current_dir, release_sha=args.release_sha)
    blockers = [f"previous:{item}" for item in previous["blockers"]]
    blockers.extend(f"current:{item}" for item in current["blockers"])
    try:
        previous_day = _scan_day(args.previous_dir)
        current_day = _scan_day(args.current_dir)
        if (current_day - previous_day).days != 1:
            blockers.append("scans_are_not_on_consecutive_utc_days")
    except (KeyError, OSError, TypeError, ValueError) as exc:
        blockers.append(f"scan_pair_timestamp_invalid:{type(exc).__name__}")
    result = {
        "schema": "security-release-scan-pair/v1",
        "passed": not blockers,
        "release_sha": args.release_sha,
        "blockers": blockers,
    }
    rendered = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
