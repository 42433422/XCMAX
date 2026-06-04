#!/usr/bin/env python3
"""Merge k6 results.json into perf/metrics.json for GitHub Pages dashboard."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _metric_value(metrics: dict[str, Any], name: str, key: str) -> float | None:
    block = metrics.get(name) or {}
    values = block.get("values") if isinstance(block, dict) else None
    if not isinstance(values, dict):
        return None
    val = values.get(key)
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def extract_run(k6_data: dict[str, Any], *, run_id: str, ref: str, sha: str) -> dict[str, Any]:
    metrics = k6_data.get("metrics") or {}
    return {
        "run_id": run_id,
        "ref": ref,
        "sha": sha[:12] if sha else "",
        "ts": datetime.now(timezone.utc).isoformat(),
        "p99_ms": _metric_value(metrics, "http_req_duration", "p(99)"),
        "error_rate": _metric_value(metrics, "http_req_failed", "rate"),
        "rps": _metric_value(metrics, "http_reqs", "rate"),
    }


def load_history(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("runs"), list):
        return data["runs"]
    return []


def save_history(path: Path, runs: list[dict[str, Any]], *, max_runs: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    trimmed = runs[-max_runs:]
    path.write_text(
        json.dumps(
            {"runs": trimmed, "updated_at": datetime.now(timezone.utc).isoformat()}, indent=2
        ),
        encoding="utf-8",
    )


def regression_warning(
    runs: list[dict[str, Any]], *, window: int = 7, threshold: float = 0.2
) -> str | None:
    p99_values = [r["p99_ms"] for r in runs if r.get("p99_ms") is not None]
    if len(p99_values) < window + 1:
        return None
    baseline = statistics.median(p99_values[-(window + 1) : -1])
    latest = p99_values[-1]
    if baseline <= 0:
        return None
    if latest > baseline * (1 + threshold):
        return (
            f"P99 regression: latest {latest:.1f}ms vs median-of-{window} "
            f"{baseline:.1f}ms (>{threshold:.0%} worse)"
        )
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--k6-results", type=Path, required=True)
    parser.add_argument("--metrics-out", type=Path, default=Path("perf/metrics.json"))
    parser.add_argument("--max-runs", type=int, default=100)
    parser.add_argument("--run-id", default="")
    parser.add_argument("--ref", default="main")
    parser.add_argument("--sha", default="")
    args = parser.parse_args()

    if not args.k6_results.is_file():
        print(f"::error::Missing k6 results: {args.k6_results}", file=sys.stderr)
        return 1

    k6_data = json.loads(args.k6_results.read_text(encoding="utf-8"))
    run = extract_run(
        k6_data,
        run_id=args.run_id or args.sha or "local",
        ref=args.ref,
        sha=args.sha,
    )

    history = load_history(args.metrics_out)
    history.append(run)
    save_history(args.metrics_out, history, max_runs=args.max_runs)

    warn = regression_warning(history)
    if warn:
        print(f"::warning::{warn}")

    print(
        f"Appended perf run; total={len(history[-args.max_runs :])} entries -> {args.metrics_out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
