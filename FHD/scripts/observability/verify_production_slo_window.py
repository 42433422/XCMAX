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
            and float(payload.get("scrape_coverage") or 0) >= 0.99
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


def observation_ledger(evidence_dir: Path, *, days: int = 7) -> dict[str, Any]:
    """Day-by-day collection/scrape ledger: every gap or fault stays on record."""
    by_day: dict[date, dict[str, Any]] = {}
    for path in sorted(evidence_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError):
            continue
        day = _day(payload) if isinstance(payload, dict) else None
        if day is not None:
            by_day[day] = payload
    if not by_day:
        return {"passed": False, "days": [], "gaps": ["no_evidence"], "retention": None}
    end = max(by_day)
    entries: list[dict[str, Any]] = []
    gaps: list[str] = []
    for offset in range(days - 1, -1, -1):
        day = end - timedelta(days=offset)
        payload = by_day.get(day)
        if payload is None:
            gaps.append(f"{day}:no_collection_record")
            entries.append({"day": day.isoformat(), "recorded": False})
            continue
        targets = {
            job: item.get("coverage")
            for job, item in (payload.get("scrape_evidence") or {}).items()
            if isinstance(item, dict)
        }
        faults = sorted(
            e for e in payload.get("errors") or [] if "scrape" in e or "source_unavailable" in e
        )
        if payload.get("source_status") != "available":
            gaps.append(f"{day}:source_unavailable")
        for job, coverage in targets.items():
            if coverage is None or float(coverage) < 0.99:
                gaps.append(f"{day}:{job}:scrape_coverage:{coverage}")
        entries.append(
            {
                "day": day.isoformat(),
                "recorded": True,
                "source_status": payload.get("source_status"),
                "target_coverage": targets,
                "faults": faults,
            }
        )
    latest = by_day[end]
    retention = {
        "days": latest.get("raw_metric_retention_days"),
        "source": latest.get("raw_metric_retention_source", "declared"),
    }
    if retention["source"] != "prometheus_flags" or float(retention["days"] or 0) < 120:
        gaps.append(f"retention_not_measured_or_below_120d:{retention}")
    return {
        "schema": "xcagi.production_observation_ledger/v1",
        "passed": not gaps,
        "window": f"{(end - timedelta(days=days - 1)).isoformat()}..{end.isoformat()}",
        "days": entries,
        "gaps": gaps,
        "retention": retention,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--release-id", default="")
    parser.add_argument("--required-days", type=int, default=90)
    parser.add_argument("--observation-days", type=int, default=0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.observation_days:
        result = observation_ledger(args.evidence_dir, days=args.observation_days)
    elif not args.release_id:
        parser.error("--release-id is required unless --observation-days is set")
    else:
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
