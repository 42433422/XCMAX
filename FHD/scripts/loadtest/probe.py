#!/usr/bin/env python3
"""
Lightweight concurrency probe using only the standard library.
Hits GET /api/health by default; use --suite desktop-mods for Mod 列表探针。
See docs/PERFORMANCE_LOAD_TESTING.md.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

try:
    from app.utils.operational_errors import RECOVERABLE_ERRORS
except ImportError:  # pragma: no cover - standalone execution outside FHD PYTHONPATH
    RECOVERABLE_ERRORS = (OSError, TimeoutError, urllib.error.URLError)


def one_get(url: str, timeout: float) -> tuple[int, float]:
    t0 = time.perf_counter()
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            _ = resp.read()
            code = resp.status
    except urllib.error.HTTPError as e:
        code = e.code
    except RECOVERABLE_ERRORS:
        code = -1
    dt = time.perf_counter() - t0
    return code, dt


def _percentile_ms(sorted_latencies_s: list[float], p: float) -> float:
    if not sorted_latencies_s:
        return 0.0
    idx = min(int(round((len(sorted_latencies_s) - 1) * p)), len(sorted_latencies_s) - 1)
    return round(sorted_latencies_s[idx] * 1000.0, 2)


def evaluate_probe_budget(
    metrics: dict[str, Any],
    *,
    max_p95_ms: float | None = None,
    max_error_rate: float = 0.0,
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    error_rate = float(metrics.get("error_rate", 1.0))
    if error_rate > max_error_rate:
        reasons.append(f"error_rate_exceeded:{error_rate:.4f}>{max_error_rate:.4f}")
    p95_ms = float(metrics.get("p95_ms", 0.0))
    if max_p95_ms is not None and p95_ms > max_p95_ms:
        reasons.append(f"p95_ms_exceeded:{p95_ms:.2f}>{max_p95_ms:.2f}")
    return len(reasons) == 0, reasons


def measure_probe(
    url: str,
    workers: int,
    total: int,
    timeout: float,
    *,
    max_p95_ms: float | None = None,
    max_error_rate: float = 0.0,
) -> dict[str, Any]:
    wall0 = time.perf_counter()
    latencies: list[float] = []
    codes: dict[int, int] = {}

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(one_get, url, timeout) for _ in range(total)]
        for f in concurrent.futures.as_completed(futs):
            code, dt = f.result()
            latencies.append(dt)
            codes[code] = codes.get(code, 0) + 1

    wall = max(time.perf_counter() - wall0, 1e-9)
    latencies.sort()
    ok = codes.get(200, 0)
    error_rate = round((total - ok) / total, 6) if total > 0 else 1.0
    metrics: dict[str, Any] = {
        "url": url,
        "total": total,
        "workers": workers,
        "wall_s": round(wall, 3),
        "rps": round(total / wall, 1),
        "status_codes": {str(k): v for k, v in sorted(codes.items())},
        "http_200": ok,
        "error_rate": error_rate,
        "p50_ms": _percentile_ms(latencies, 0.50),
        "p95_ms": _percentile_ms(latencies, 0.95),
        "p99_ms": _percentile_ms(latencies, 0.99),
    }
    passed, reasons = evaluate_probe_budget(
        metrics, max_p95_ms=max_p95_ms, max_error_rate=max_error_rate
    )
    metrics["passed"] = passed
    metrics["failure_reasons"] = reasons
    return metrics


def run_probe(
    url: str,
    workers: int,
    total: int,
    timeout: float,
    *,
    max_p95_ms: float | None = None,
    max_error_rate: float = 0.0,
) -> tuple[int, dict[str, Any]]:
    metrics = measure_probe(
        url,
        workers,
        total,
        timeout,
        max_p95_ms=max_p95_ms,
        max_error_rate=max_error_rate,
    )
    print(f"url={metrics['url']}")
    print(
        f"total={metrics['total']} workers={metrics['workers']} "
        f"wall_s={metrics['wall_s']:.3f} rps={metrics['rps']:.1f}"
    )
    print(f"status_codes={metrics['status_codes']} http_200={metrics['http_200']}")
    print(
        f"latency_ms p50={metrics['p50_ms']:.2f} "
        f"p95={metrics['p95_ms']:.2f} p99={metrics['p99_ms']:.2f}"
    )
    if not metrics["passed"]:
        print(f"budget_failed={metrics['failure_reasons']}")
    return (0 if metrics["passed"] else 1), metrics


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Concurrent GET probe for XCAGI API")
    p.add_argument(
        "--base", default="http://127.0.0.1:8000", help="API origin without trailing path"
    )
    p.add_argument("--url", default="", help="Full URL (overrides --base and --path)")
    p.add_argument("--path", default="/api/health", help="Path when using --base")
    p.add_argument(
        "--suite",
        choices=["health", "desktop-mods", "regular-pages"],
        default="health",
        help="Preset path sets",
    )
    p.add_argument("--workers", type=int, default=50, help="Concurrent workers")
    p.add_argument("--total", type=int, default=500, help="Total requests per URL")
    p.add_argument("--timeout", type=float, default=30.0, help="Per-request timeout (seconds)")
    p.add_argument(
        "--max-p95-ms",
        type=float,
        default=None,
        help="Optional P95 latency budget in ms (e.g. 500)",
    )
    p.add_argument(
        "--max-error-rate",
        type=float,
        default=0.0,
        help="Maximum allowed non-200 error rate (0.0 - 1.0)",
    )
    p.add_argument(
        "--json-out",
        default="",
        help="Optional path to write structured JSON report",
    )
    args = p.parse_args(argv)

    if args.workers < 1 or args.total < 1:
        print("workers and total must be >= 1", file=sys.stderr)
        return 2
    if args.max_p95_ms is not None and args.max_p95_ms <= 0:
        print("max-p95-ms must be > 0", file=sys.stderr)
        return 2
    if not (0.0 <= args.max_error_rate <= 1.0):
        print("max-error-rate must be between 0.0 and 1.0", file=sys.stderr)
        return 2

    base = args.base.rstrip("/")
    if args.suite == "desktop-mods":
        paths = ["/api/health", "/api/mods/", "/api/mods/loading-status", "/api/desktop/status"]
    elif args.suite == "regular-pages":
        paths = ["/api/health", "/api/ping", "/api/mods/loading-status", "/api/desktop/status"]
    else:
        paths = [args.path if args.path.startswith("/") else f"/{args.path}"]

    exit_code = 0
    results: list[dict[str, Any]] = []
    for path in paths:
        url = args.url.strip() if args.url.strip() else urljoin(base + "/", path.lstrip("/"))
        print(f"\n--- probe {path} ---")
        code, metrics = run_probe(
            url,
            args.workers,
            args.total,
            args.timeout,
            max_p95_ms=args.max_p95_ms,
            max_error_rate=args.max_error_rate,
        )
        results.append(metrics)
        if code != 0:
            exit_code = code

    if args.json_out:
        out_path = Path(args.json_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        report = {
            "source_sha": os.environ.get("GITHUB_SHA") or os.environ.get("SOURCE_SHA") or None,
            "suite": args.suite,
            "budgets": {
                "max_p95_ms": args.max_p95_ms,
                "max_error_rate": args.max_error_rate,
            },
            "passed": exit_code == 0,
            "results": results,
        }
        out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
