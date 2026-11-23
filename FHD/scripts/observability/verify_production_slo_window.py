#!/usr/bin/env python3
"""Verify a continuous formal production SLO evidence window."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from collect_slo_metrics import (
    QUERIES,
    SAMPLE_MINIMUMS,
    SAMPLE_QUERIES,
    SCRAPE_TARGETS,
    TARGETS,
    _numeric,
    load_evidence_chain,
    meets_target,
    scrape_errors,
    telemetry_admissible,
)


def _timestamp(value: Any) -> datetime | None:
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return stamp.astimezone(UTC) if stamp.tzinfo is not None else None
    except (TypeError, ValueError):
        return None


def _day(payload: dict[str, Any]) -> date | None:
    stamp = _timestamp(payload.get("generated_at"))
    return stamp.date() if stamp is not None else None


def _audit_summary(epoch: str, audit: dict[str, Any] | None) -> dict[str, Any] | None:
    if audit is None:
        return None
    return {
        "epoch": epoch,
        "reason": audit["reason"],
        "record_count": audit["record_count"],
        "forks": audit["forks"],
        "tips": audit["tips"],
    }


def _metric_errors(payload: dict[str, Any]) -> list[str]:
    """Re-evaluate measurements with the collector SSOT, not stored pass flags."""
    errors: list[str] = []
    readings = payload.get("readings")
    readings = readings if isinstance(readings, dict) else {}
    if set(readings) != set(TARGETS):
        errors.append("slo_metric_inventory_mismatch")
    for slo_id in TARGETS:
        item = readings.get(slo_id)
        if not isinstance(item, dict):
            continue
        value = _numeric(item.get("reading_numeric"))
        if (
            item.get("promql") != QUERIES[slo_id].format(w="90d")
            or item.get("sample_promql") != SAMPLE_QUERIES[slo_id].format(w="90d")
            or _numeric(item.get("reading")) != value
            or meets_target(slo_id, value) is not True
            or (_numeric(item.get("sample_count")) or 0) < SAMPLE_MINIMUMS[slo_id]
        ):
            errors.append(f"{slo_id}:target_or_sample_failed")
    return errors


def verify_window(
    evidence_dir: Path,
    *,
    release_id: str,
    required_days: int = 90,
    now: datetime | None = None,
) -> dict[str, Any]:
    observed_at = now or datetime.now(UTC)
    if observed_at.tzinfo is None:
        raise ValueError("verification time must include a timezone")
    if required_days <= 0 or not release_id:
        raise ValueError("a release identity and positive observation length are required")
    observed_at = observed_at.astimezone(UTC)
    records, blockers, previous_hash, epoch, audit = load_evidence_chain(evidence_dir)

    latest_by_day: dict[date, dict[str, Any]] = {}
    for payload in records:
        if payload.get("mode") != "formal" or payload.get("release_id") != release_id:
            continue
        stamp = _timestamp(payload.get("generated_at"))
        recorded_at = _timestamp(payload.get("recorded_at"))
        if stamp is None or recorded_at is None or recorded_at < stamp:
            blockers.append("invalid_collection_timestamp")
            continue
        if stamp > observed_at or recorded_at > observed_at:
            blockers.append("future_collection_record")
            continue
        day = stamp.date()
        previous = latest_by_day.get(day)
        # Backfills are committed later but must not supersede a newer sample.
        if previous is None or (stamp, recorded_at) >= (
            _timestamp(previous.get("generated_at")),
            _timestamp(previous.get("recorded_at")),
        ):
            latest_by_day[day] = payload

    formal_by_day: dict[date, dict[str, Any]] = {}
    for day, payload in latest_by_day.items():
        if (
            telemetry_admissible(payload)
            and all(
                isinstance(payload.get(key), (int, float))
                and not isinstance(payload[key], bool)
                and 0.99 <= payload[key] <= 1.0
                for key in ("coverage", "scrape_coverage")
            )
            and payload.get("day0_eligible") is True
        ):
            formal_by_day[day] = payload
    end = max(latest_by_day, default=None)
    latest_at = _timestamp(latest_by_day[end].get("generated_at")) if end is not None else None
    # Collection runs daily. Closure must use telemetry no older than one full
    # sampling period, measured from the sample instant, never the file mtime.
    if latest_at is None or observed_at - latest_at > timedelta(hours=24):
        blockers.append("latest_formal_sample_stale_or_missing")
    continuous: list[date] = []
    day = end
    while day is not None and day in formal_by_day:
        continuous.append(day)
        day -= timedelta(days=1)
    continuous.reverse()
    if len(continuous) < required_days:
        blockers.append(f"formal_continuous_days:{len(continuous)}/{required_days}")

    final = formal_by_day.get(end) if end is not None else None
    if final is None or final.get("window") != "90d":
        blockers.append("final_90d_sample_evidence_missing")
    else:
        blockers.extend(_metric_errors(final))
    return {
        "schema": "xcagi.production_slo_window_verification/v1",
        "passed": not blockers,
        "release_id": release_id,
        "verified_at": observed_at.isoformat(),
        "latest_sample_at": latest_at.isoformat() if latest_at is not None else "",
        "max_sample_age_hours": 24,
        "continuous_days": len(continuous),
        "day_0": continuous[0].isoformat() if continuous else "",
        "day_n": continuous[-1].isoformat() if continuous else "",
        "blockers": blockers,
        "chain_tip": previous_hash,
        "legacy_chain_audit": _audit_summary(epoch, audit),
    }


def observation_ledger(
    evidence_dir: Path, *, days: int = 7, now: datetime | None = None
) -> dict[str, Any]:
    """Day-by-day collection/scrape ledger: every gap or fault stays on record."""
    if days <= 0:
        raise ValueError("observation length must be positive")
    observed_at = now or datetime.now(UTC)
    if observed_at.tzinfo is None:
        raise ValueError("observation time must include a timezone")
    end = observed_at.astimezone(UTC).date()
    records, gaps, _chain_tip, epoch, audit = load_evidence_chain(evidence_dir)
    by_day: dict[date, list[dict[str, Any]]] = {}
    for payload in records:
        day = _day(payload)
        if day is not None:
            if day > end:
                gaps.append(f"{day}:future_collection_record")
                continue
            by_day.setdefault(day, []).append(payload)
    if not by_day:
        return {
            "passed": False,
            "days": [],
            "gaps": gaps + ["no_evidence"],
            "retention": None,
            "legacy_chain_audit": _audit_summary(epoch, audit),
        }
    entries: list[dict[str, Any]] = []
    for offset in range(days - 1, -1, -1):
        day = end - timedelta(days=offset)
        daily = by_day.get(day)
        if daily is None:
            gaps.append(f"{day}:no_collection_record")
            entries.append({"day": day.isoformat(), "recorded": False})
            continue
        payload = daily[-1]
        for record in daily:
            if record.get("source_status") != "available":
                gaps.append(f"{day}:source_unavailable")
            gaps.extend(f"{day}:{error}" for error in scrape_errors(record))
        evidence = payload.get("scrape_evidence")
        evidence = evidence if isinstance(evidence, dict) else {}
        targets = {
            job: evidence[job].get("coverage") if isinstance(evidence.get(job), dict) else None
            for job in SCRAPE_TARGETS
        }
        faults = sorted(
            e
            for e in payload.get("errors") or []
            if isinstance(e, str) and ("scrape" in e or "source_unavailable" in e)
        )
        entries.append(
            {
                "day": day.isoformat(),
                "recorded": True,
                "source_status": payload.get("source_status"),
                "target_coverage": targets,
                "faults": faults,
            }
        )
    latest = by_day[max(by_day)][-1]
    retention = {
        "days": latest.get("raw_metric_retention_days"),
        "source": latest.get("raw_metric_retention_source", "declared"),
    }
    if retention["source"] != "prometheus_flags" or (_numeric(retention["days"]) or 0) < 120:
        gaps.append(f"retention_not_measured_or_below_120d:{retention}")
    return {
        "schema": "xcagi.production_observation_ledger/v1",
        "passed": not gaps,
        "window": f"{(end - timedelta(days=days - 1)).isoformat()}..{end.isoformat()}",
        "days": entries,
        "gaps": sorted(set(gaps)),
        "retention": retention,
        "legacy_chain_audit": _audit_summary(epoch, audit),
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
