#!/usr/bin/env python3
"""Derive DORA metrics from metrics/deploy_events.jsonl."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def _parse_ts(raw: str) -> datetime:
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))


def _hours_between(a: str, b: str) -> float:
    return max(0.0, (_parse_ts(b) - _parse_ts(a)).total_seconds() / 3600.0)


def load_events(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    events: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        events.append(json.loads(line))
    return events


def compute_dora(events: list[dict], window_days: int = 7) -> dict:
    now = datetime.now(timezone.utc)
    cutoff = now.timestamp() - window_days * 86400
    recent = [
        e
        for e in events
        if _parse_ts(e["deployed_at"]).timestamp() >= cutoff
    ]
    successes = [e for e in recent if e.get("status") == "success"]
    failures = [e for e in recent if e.get("status") == "failed"]
    rollbacks = [e for e in recent if e.get("status") == "rollback" or e.get("restored_at")]

    lead_times = [
        _hours_between(e.get("commit_at", e["deployed_at"]), e["deployed_at"])
        for e in successes
        if e.get("commit_at")
    ]
    mttr_samples = [
        _hours_between(e["deployed_at"], e["restored_at"])
        for e in recent
        if e.get("restored_at")
    ]

    total = len(recent)
    fail_rate = (len(failures) / total) if total else 0.0

    return {
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "window_days": window_days,
        "event_count": total,
        "deployment_frequency_per_day": round(len(successes) / max(window_days, 1), 4),
        "lead_time_for_changes_hours": round(
            sorted(lead_times)[len(lead_times) // 2] if lead_times else 0.0, 4
        ),
        "mean_time_to_restore_hours": round(
            sum(mttr_samples) / len(mttr_samples) if mttr_samples else 0.0, 4
        ),
        "change_failure_rate": round(fail_rate, 4),
        "successes": len(successes),
        "failures": len(failures),
        "rollbacks": len(rollbacks),
    }


def main() -> None:
    p = argparse.ArgumentParser(description="Collect DORA metrics from deploy_events.jsonl")
    p.add_argument(
        "--input",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "metrics" / "deploy_events.jsonl",
    )
    p.add_argument("--window-days", type=int, default=7)
    p.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Default: metrics/dora-YYYYMMDD.json next to input",
    )
    args = p.parse_args()
    events = load_events(args.input)
    report = compute_dora(events, window_days=args.window_days)
    out = args.output or args.input.parent / f"dora-{datetime.now(timezone.utc):%Y%m%d}.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
