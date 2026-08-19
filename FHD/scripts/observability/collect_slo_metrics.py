#!/usr/bin/env python3
"""Collect SLO readings from Prometheus → metrics/slo-measured-YYYYMMDD.json."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
METRICS_DIR = ROOT / "metrics"

QUERIES = {
    "SLO-API-01": (
        '1 - (sum(rate(api_requests_total{{status=~"5.."}}[{w}])) '
        "/ clamp_min(sum(rate(api_requests_total[{w}])),1))"
    ),
    "SLO-API-02": (
        "histogram_quantile(0.95, sum by (le) "
        '(rate(api_request_duration_seconds_bucket{{endpoint="/api/auth/login"}}[{w}]))) * 1000'
    ),
    "SLO-API-03": (
        'sum(rate(api_requests_total{{status=~"5.."}}[{w}])) '
        "/ sum(rate(api_requests_total[{w}]))"
    ),
    "SLO-AI-01": (
        "histogram_quantile(0.95, sum by (le) "
        "(rate(chat_stream_first_byte_seconds_bucket[{w}]))) * 1000"
    ),
    "SLO-BUS-01": (
        "1 - (sum(rate(neurobus_events_dead_lettered_total[{w}])) + "
        "sum(rate(neurobus_events_lost_total[{w}]))) / "
        "clamp_min(sum(rate(neurobus_events_published_total[{w}])),1)"
    ),
    # --- 业务 SLO（SLO-BIZ-01..05）---
    # 指标定义见 app/utils/metrics.py "业务 SLI 指标" 段；目标值与 docs/SLO.md 一致。
    "SLO-BIZ-01": (
        "histogram_quantile(0.95, sum by (le) "
        "(rate(customer_op_duration_seconds_bucket[{w}]))) * 1000"
    ),
    "SLO-BIZ-02": (
        'sum(rate(customer_op_total{{status="error"}}[{w}])) '
        "/ clamp_min(sum(rate(customer_op_total[{w}])),1)"
    ),
    "SLO-BIZ-03": (
        "histogram_quantile(0.95, sum by (le) "
        "(rate(doc_recognition_duration_seconds_bucket[{w}]))) * 1000"
    ),
    "SLO-BIZ-04": (
        "histogram_quantile(0.95, sum by (le) "
        "(rate(export_task_duration_seconds_bucket[{w}]))) * 1000"
    ),
    "SLO-BIZ-05": (
        '1 - sum(rate(mod_install_total{{status="error"}}[{w}])) '
        "/ clamp_min(sum(rate(mod_install_total[{w}])),1)"
    ),
}

TARGETS = {
    "SLO-API-01": ("availability", 0.999, "ge"),
    "SLO-API-02": ("login_p95_ms", 500, "lt"),
    "SLO-API-03": ("error_rate", 0.001, "lt"),
    "SLO-AI-01": ("ai_chat_p95_ms", 1500, "lt"),
    "SLO-BUS-01": ("neurobus_delivery", 0.9995, "ge"),
    # --- 业务 SLO 目标 ---
    "SLO-BIZ-01": ("customer_op_p95_ms", 800, "lt"),
    "SLO-BIZ-02": ("customer_op_error_rate", 0.005, "lt"),
    "SLO-BIZ-03": ("doc_recognition_p95_ms", 5000, "lt"),
    "SLO-BIZ-04": ("export_task_p95_ms", 30000, "lt"),
    "SLO-BIZ-05": ("mod_install_success_rate", 0.99, "ge"),
}


def prom_query(base_url: str, expr: str) -> str | None:
    url = f"{base_url.rstrip('/')}/api/v1/query?{urllib.parse.urlencode({'query': expr})}"
    with urllib.request.urlopen(url, timeout=30) as resp:
        data = json.loads(resp.read().decode())
    results = data.get("data", {}).get("result", [])
    if not results:
        return None
    return str(results[0]["value"][1])


def meets_target(slo_id: str, value: float | None) -> bool | None:
    if value is None:
        return None
    _name, threshold, op = TARGETS[slo_id]
    if op == "ge":
        return value >= threshold
    return value < threshold


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prom-url", default=os.environ.get("PROMETHEUS_URL", "http://127.0.0.1:9091"))
    parser.add_argument("--window", default="30d", choices=["7d", "30d", "15m", "1h"])
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    day = datetime.now(UTC).strftime("%Y%m%d")
    out_path = Path(args.out) if args.out else METRICS_DIR / f"slo-measured-{day}.json"

    readings: dict[str, dict] = {}
    for slo_id, template in QUERIES.items():
        expr = template.format(w=args.window)
        raw = prom_query(args.prom_url, expr)
        val = float(raw) if raw not in (None, "NaN", "nan") else None
        readings[slo_id] = {
            "promql": expr,
            "reading": raw,
            "reading_numeric": val,
            "meets_target": meets_target(slo_id, val),
        }

    payload = {
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "prometheus_url": args.prom_url,
        "window": args.window,
        "readings": readings,
    }
    METRICS_DIR.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {out_path}")

    snapshot_path = METRICS_DIR / "sla-snapshot.json"
    if snapshot_path.is_file():
        snap = json.loads(snapshot_path.read_text(encoding="utf-8"))
        for slo in snap.get("slos", []):
            sid = slo.get("id")
            if sid in readings and readings[sid]["reading"] is not None:
                slo["baseline_measured"] = readings[sid]["reading"]
                slo["baseline_window"] = args.window
        snap["last_prometheus_collect"] = payload["generated_at"]
        snapshot_path.write_text(json.dumps(snap, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    return 0


if __name__ == "__main__":
    sys.exit(main())
