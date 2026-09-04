#!/usr/bin/env python3
"""Verify a continuous formal production SLO evidence window."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _record_hash_is_valid(payload: dict[str, Any]) -> bool:
    candidate = dict(payload)
    expected = str(candidate.pop("evidence_hash", ""))
    candidate.pop("chain_hash", None)
    candidate.pop("all_pass", None)
    actual = hashlib.sha256(_canonical(candidate).encode()).hexdigest()
    return bool(expected and expected == actual)


def _day(payload: dict[str, Any]) -> date | None:
    try:
        return datetime.fromisoformat(str(payload["generated_at"]).replace("Z", "+00:00")).date()
    except (KeyError, TypeError, ValueError):
        return None


def verify_window(
    evidence_dir: Path,
    *,
    release_id: str,
    required_days: int = 90,
) -> dict[str, Any]:
    blockers: list[str] = []
    records: list[dict[str, Any]] = []
    previous_hash = "0" * 64
    for path in sorted(evidence_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError):
            blockers.append(f"{path.name}:invalid_json")
            continue
        if not isinstance(payload, dict) or not _record_hash_is_valid(payload):
            blockers.append(f"{path.name}:invalid_evidence_hash")
            continue
        if payload.get("previous_chain_hash") != previous_hash:
            blockers.append(f"{path.name}:broken_hash_chain")
        expected_chain = hashlib.sha256(
            f"{previous_hash}:{payload['evidence_hash']}".encode()
        ).hexdigest()
        if payload.get("chain_hash") != expected_chain:
            blockers.append(f"{path.name}:invalid_chain_hash")
        previous_hash = str(payload.get("chain_hash") or "")
        records.append(payload)

    formal_by_day: dict[date, dict[str, Any]] = {}
    for payload in records:
        day = _day(payload)
        if (
            day is not None
            and payload.get("mode") == "formal"
            and payload.get("release_id") == release_id
            and payload.get("source_status") == "available"
            and float(payload.get("coverage") or 0) >= 0.99
            and payload.get("day0_eligible") is True
        ):
            formal_by_day[day] = payload
    days = sorted(formal_by_day)
    longest: list[date] = []
    current: list[date] = []
    for day in days:
        if not current or day == current[-1] + timedelta(days=1):
            current.append(day)
        else:
            if len(current) > len(longest):
                longest = current
            current = [day]
    if len(current) > len(longest):
        longest = current
    if len(longest) < required_days:
        blockers.append(f"formal_continuous_days:{len(longest)}/{required_days}")

    final = formal_by_day.get(longest[-1]) if longest else None
    if final is None or final.get("window") != "90d":
        blockers.append("final_90d_sample_evidence_missing")
    else:
        readings = final.get("readings") if isinstance(final.get("readings"), dict) else {}
        for slo_id, reading in readings.items():
            if not isinstance(reading, dict) or reading.get("passes") is not True:
                blockers.append(f"{slo_id}:target_or_sample_failed")
        if len(readings) != 10:
            blockers.append(f"slo_metric_count:{len(readings)}/10")
    return {
        "schema": "xcagi.production_slo_window_verification/v1",
        "passed": not blockers,
        "release_id": release_id,
        "continuous_days": len(longest),
        "day_0": longest[0].isoformat() if longest else "",
        "day_n": longest[-1].isoformat() if longest else "",
        "blockers": blockers,
        "chain_tip": previous_hash,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--required-days", type=int, default=90)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = verify_window(
        args.evidence_dir,
        release_id=args.release_id,
        required_days=args.required_days,
    )
    rendered = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
