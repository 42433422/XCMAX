#!/usr/bin/env python3
"""SLA 实测分析报告 — 读取 sla_measurements.jsonl，输出 P50/P99/P999 + 达标率。"""
from __future__ import annotations

import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path


def analyze(log_path: Path) -> dict:
    """分析 SLA 测量数据。"""
    by_level_op: dict[str, list[float]] = defaultdict(list)
    sla_hit_count: dict[str, int] = defaultdict(int)
    total_count: dict[str, int] = defaultdict(int)

    with log_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            key = f"{row['level']}@{row['operation']}"
            by_level_op[key].append(row["latency_ms"])
            total_count[key] += 1
            if row["sla_hit"]:
                sla_hit_count[key] += 1

    report = {}
    for key, latencies in by_level_op.items():
        latencies_sorted = sorted(latencies)
        n = len(latencies_sorted)
        p50 = latencies_sorted[int(n * 0.50)]
        p99 = latencies_sorted[int(n * 0.99)] if n >= 100 else latencies_sorted[-1]
        p999 = latencies_sorted[int(n * 0.999)] if n >= 1000 else latencies_sorted[-1]
        hit_rate = sla_hit_count[key] / total_count[key] if total_count[key] else 0.0
        report[key] = {
            "count": n,
            "p50_ms": round(p50, 3),
            "p99_ms": round(p99, 3),
            "p999_ms": round(p999, 3),
            "sla_hit_rate": round(hit_rate, 4),
        }
    return report


def main() -> int:
    log_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("metrics/sla_measurements.jsonl")
    if not log_path.exists():
        print(f"ERROR: {log_path} not found", file=sys.stderr)
        return 1

    report = analyze(log_path)
    print(f"{'Level@Operation':<40} {'Count':>6} {'P50ms':>8} {'P99ms':>8} {'P999ms':>8} {'HitRate':>8}")
    print("-" * 80)
    for key, stats in sorted(report.items()):
        print(
            f"{key:<40} {stats['count']:>6} {stats['p50_ms']:>8} "
            f"{stats['p99_ms']:>8} {stats['p999_ms']:>8} {stats['sla_hit_rate']:>8.2%}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
