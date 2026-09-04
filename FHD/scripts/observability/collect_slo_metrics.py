#!/usr/bin/env python3
"""Collect production SLO evidence without seed/snapshot fallbacks.

Every production run is an immutable, hash-chained evidence record. Missing
credentials, Prometheus failures, empty readings, or insufficient samples are
recorded explicitly and never converted into a passing zero-error result.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
METRICS_DIR = ROOT / "metrics"
PRODUCTION_EVIDENCE_DIR = METRICS_DIR / "slo-production"

QUERIES = {
    "SLO-API-01": (
        '1 - ((sum(rate(api_requests_total{{environment="production",status=~"5.."}}[{w}])) '
        "or vector(0)) / clamp_min(sum(rate(api_requests_total"
        '{{environment="production"}}[{w}])),1))'
    ),
    "SLO-API-02": (
        "histogram_quantile(0.95, sum by (le) (rate(api_request_duration_seconds_bucket"
        '{{environment="production",endpoint="/api/auth/login"}}[{w}]))) * 1000'
    ),
    "SLO-API-03": (
        '(sum(rate(api_requests_total{{environment="production",status=~"5.."}}[{w}])) '
        'or vector(0)) / clamp_min(sum(rate(api_requests_total{{environment="production"}}[{w}])),1)'
    ),
    "SLO-AI-01": (
        "histogram_quantile(0.95, sum by (le) (rate(chat_stream_first_byte_seconds_bucket"
        '{{environment="production"}}[{w}]))) * 1000'
    ),
    "SLO-BUS-01": (
        '(1 - ((sum(increase(neurobus_events_dead_lettered_total{{environment="production"}}[{w}])) '
        'or vector(0)) + (sum(increase(neurobus_events_lost_total{{environment="production"}}[{w}])) '
        "or vector(0))) / clamp_min(sum(increase(neurobus_events_published_total"
        '{{environment="production"}}[{w}])),1))'
    ),
    "SLO-BIZ-01": (
        "histogram_quantile(0.95, sum by (le) (rate(customer_op_duration_seconds_bucket"
        '{{environment="production"}}[{w}]))) * 1000'
    ),
    "SLO-BIZ-02": (
        '(sum(increase(customer_op_total{{environment="production",status="error"}}[{w}])) '
        'or vector(0)) / clamp_min(sum(increase(customer_op_total{{environment="production"}}[{w}])),1)'
    ),
    "SLO-BIZ-03": (
        "histogram_quantile(0.95, sum by (le) (rate(doc_recognition_duration_seconds_bucket"
        '{{environment="production"}}[{w}]))) * 1000'
    ),
    "SLO-BIZ-04": (
        "histogram_quantile(0.95, sum by (le) (rate(export_task_duration_seconds_bucket"
        '{{environment="production"}}[{w}]))) * 1000'
    ),
    "SLO-BIZ-05": (
        '(1 - (sum(increase(mod_install_total{{environment="production",device_scope="external_customer",status="error"}}[{w}])) '
        "or vector(0)) / clamp_min(sum(increase(mod_install_total"
        '{{environment="production",device_scope="external_customer"}}[{w}])),1))'
    ),
}

TARGETS = {
    "SLO-API-01": ("availability", 0.999, "ge"),
    "SLO-API-02": ("login_p95_ms", 500, "lt"),
    "SLO-API-03": ("error_rate", 0.001, "lt"),
    "SLO-AI-01": ("ai_chat_p95_ms", 1500, "lt"),
    "SLO-BUS-01": ("neurobus_delivery", 0.9995, "ge"),
    "SLO-BIZ-01": ("customer_op_p95_ms", 800, "lt"),
    "SLO-BIZ-02": ("customer_op_error_rate", 0.005, "lt"),
    "SLO-BIZ-03": ("doc_recognition_p95_ms", 5000, "lt"),
    "SLO-BIZ-04": ("export_task_p95_ms", 30000, "lt"),
    "SLO-BIZ-05": ("mod_install_success_rate", 0.99, "ge"),
}

SAMPLE_QUERIES = {
    "SLO-API-01": 'sum(increase(api_requests_total{{environment="production"}}[{w}]))',
    "SLO-API-02": 'sum(increase(api_request_duration_seconds_count{{environment="production",endpoint="/api/auth/login"}}[{w}]))',
    "SLO-API-03": 'sum(increase(api_requests_total{{environment="production"}}[{w}]))',
    "SLO-AI-01": 'sum(increase(chat_stream_first_byte_seconds_count{{environment="production"}}[{w}]))',
    "SLO-BUS-01": 'sum(increase(neurobus_events_published_total{{environment="production"}}[{w}]))',
    "SLO-BIZ-01": 'sum(increase(customer_op_duration_seconds_count{{environment="production"}}[{w}]))',
    "SLO-BIZ-02": 'sum(increase(customer_op_total{{environment="production"}}[{w}]))',
    "SLO-BIZ-03": 'sum(increase(doc_recognition_duration_seconds_count{{environment="production"}}[{w}]))',
    "SLO-BIZ-04": 'sum(increase(export_task_duration_seconds_count{{environment="production"}}[{w}]))',
    "SLO-BIZ-05": 'sum(increase(mod_install_total{{environment="production",device_scope="external_customer"}}[{w}]))',
}

SAMPLE_MINIMUMS = {
    "SLO-API-01": 10_000,
    "SLO-API-02": 100,
    "SLO-API-03": 10_000,
    "SLO-AI-01": 100,
    "SLO-BUS-01": 1_000,
    "SLO-BIZ-01": 100,
    "SLO-BIZ-02": 100,
    "SLO-BIZ-03": 30,
    "SLO-BIZ-04": 30,
    "SLO-BIZ-05": 6,
}


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def prom_query(
    base_url: str,
    expr: str,
    bearer_token: str = "",
    query_at: datetime | None = None,
) -> str | None:
    params = {"query": expr}
    if query_at is not None:
        params["time"] = query_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
    url = f"{base_url.rstrip('/')}/api/v1/query?{urllib.parse.urlencode(params)}"
    headers = {"Authorization": f"Bearer {bearer_token}"} if bearer_token else {}
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode())
    if data.get("status") != "success":
        raise RuntimeError("prometheus_query_failed")
    results = data.get("data", {}).get("result", [])
    if not results:
        return None
    return str(results[0]["value"][1])


def _numeric(raw: str | None) -> float | None:
    if raw in (None, "NaN", "nan", "+Inf", "-Inf"):
        return None
    return float(raw)


def meets_target(slo_id: str, value: float | None) -> bool | None:
    if value is None:
        return None
    _name, threshold, op = TARGETS[slo_id]
    return value >= threshold if op == "ge" else value < threshold


def _latest_chain_hash(directory: Path) -> str:
    for path in sorted(directory.glob("*.json"), reverse=True):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        value = str(payload.get("chain_hash") or "")
        if len(value) == 64:
            return value
    return "0" * 64


def _write_immutable(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"refusing to overwrite SLO evidence: {path}")
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def collect(
    *,
    prom_url: str,
    prom_token: str,
    window: str,
    mode: str,
    release_id: str,
    raw_retention_days: int,
    out_path: Path,
    now: datetime | None = None,
    evidence_at: datetime | None = None,
    backfill_reason: str = "",
) -> tuple[dict[str, Any], bool]:
    recorded_at = (now or datetime.now(UTC)).astimezone(UTC)
    current = (evidence_at or recorded_at).astimezone(UTC)
    is_backfill = evidence_at is not None
    if is_backfill:
        age = recorded_at - current
        if age < timedelta(0) or age > timedelta(hours=24):
            raise ValueError("SLO backfill evidence_at must be within the preceding 24 hours")
        if not backfill_reason.strip():
            raise ValueError("SLO backfill requires a non-empty reason")
    errors: list[str] = []
    readings: dict[str, dict[str, Any]] = {}
    credentials_available = bool(prom_url.strip() and prom_token.strip())
    if not credentials_available:
        errors.append("production_prometheus_credentials_unavailable")
    if raw_retention_days < 120:
        errors.append(f"raw_metric_retention_below_120_days:{raw_retention_days}")

    for slo_id, template in QUERIES.items():
        expr = template.format(w=window)
        sample_expr = SAMPLE_QUERIES[slo_id].format(w=window)
        raw: str | None = None
        sample_raw: str | None = None
        if credentials_available:
            try:
                raw = prom_query(prom_url, expr, bearer_token=prom_token, query_at=current)
                sample_raw = prom_query(
                    prom_url, sample_expr, bearer_token=prom_token, query_at=current
                )
            except (OSError, ValueError, TypeError, RuntimeError) as exc:
                errors.append(f"{slo_id}:source_unavailable:{type(exc).__name__}")
        value = _numeric(raw)
        sample_count = _numeric(sample_raw)
        sample_minimum = SAMPLE_MINIMUMS[slo_id]
        sample_sufficient = sample_count is not None and sample_count >= sample_minimum
        reading_pass = meets_target(slo_id, value)
        readings[slo_id] = {
            "promql": expr,
            "sample_promql": sample_expr,
            "reading": raw,
            "reading_numeric": value,
            "sample_count": sample_count,
            "sample_minimum": sample_minimum,
            "sample_sufficient": sample_sufficient,
            "meets_target": reading_pass,
            "passes": reading_pass is True and sample_sufficient,
        }
        if value is None:
            errors.append(f"{slo_id}:empty_reading")
        if sample_count is None:
            errors.append(f"{slo_id}:empty_sample_count")

    source_status = "available" if not errors else "source_unavailable"
    coverage = sum(1 for item in readings.values() if item["reading_numeric"] is not None) / len(
        readings
    )
    day0_eligible = bool(
        source_status == "available"
        and coverage >= 0.99
        and all(
            item["sample_count"] is not None and item["sample_count"] > 0
            for item in readings.values()
        )
    )
    payload: dict[str, Any] = {
        "schema": "xcagi.production_slo_evidence/v1",
        "generated_at": current.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "recorded_at": recorded_at.isoformat().replace("+00:00", "Z"),
        "backfill": is_backfill,
        "backfill_reason": backfill_reason.strip() if is_backfill else "",
        "environment": "production",
        "mode": mode,
        "release_id": release_id,
        "prometheus_url": prom_url,
        "window": window,
        "raw_metric_retention_days": raw_retention_days,
        "source_status": source_status,
        "coverage": coverage,
        "day0_eligible": day0_eligible,
        "errors": sorted(set(errors)),
        "readings": readings,
    }
    previous_hash = _latest_chain_hash(out_path.parent)
    payload["previous_chain_hash"] = previous_hash
    payload["evidence_hash"] = hashlib.sha256(_canonical_json(payload).encode()).hexdigest()
    payload["chain_hash"] = hashlib.sha256(
        f"{previous_hash}:{payload['evidence_hash']}".encode()
    ).hexdigest()
    all_pass = (
        source_status == "available"
        and coverage == 1.0
        and all(item["passes"] is True for item in readings.values())
    )
    payload["all_pass"] = all_pass
    _write_immutable(out_path, payload)
    return payload, all_pass


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prom-url", default=os.environ.get("PRODUCTION_PROMETHEUS_URL", ""))
    parser.add_argument("--prom-token", default=os.environ.get("PRODUCTION_PROMETHEUS_TOKEN", ""))
    parser.add_argument("--window", default="30d", choices=["1d", "7d", "30d", "90d", "15m", "1h"])
    parser.add_argument("--mode", choices=["preflight", "formal"], default="preflight")
    parser.add_argument("--release-id", default="")
    parser.add_argument("--evidence-at", default="")
    parser.add_argument("--backfill-reason", default="")
    parser.add_argument(
        "--raw-retention-days",
        type=int,
        default=int(os.environ.get("PRODUCTION_PROMETHEUS_RETENTION_DAYS", "0") or 0),
    )
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    if args.mode == "formal" and not args.release_id:
        parser.error("--release-id is required in formal mode")
    recorded_at = datetime.now(UTC)
    evidence_at = None
    if args.evidence_at:
        try:
            evidence_at = datetime.fromisoformat(args.evidence_at.replace("Z", "+00:00"))
        except ValueError as exc:
            parser.error(f"--evidence-at is invalid: {exc}")
        if evidence_at.tzinfo is None:
            parser.error("--evidence-at must include a timezone")
    stamp = recorded_at.strftime("%Y%m%dT%H%M%SZ")
    suffix = "-".join(
        value
        for value in (os.environ.get("GITHUB_RUN_ID", ""), os.environ.get("GITHUB_RUN_ATTEMPT", ""))
        if value
    )
    filename = f"{stamp}{('-' + suffix) if suffix else ''}.json"
    out_path = Path(args.out) if args.out else PRODUCTION_EVIDENCE_DIR / filename
    payload, all_pass = collect(
        prom_url=args.prom_url,
        prom_token=args.prom_token,
        window=args.window,
        mode=args.mode,
        release_id=args.release_id,
        raw_retention_days=args.raw_retention_days,
        out_path=out_path,
        now=recorded_at,
        evidence_at=evidence_at,
        backfill_reason=args.backfill_reason,
    )
    print(f"Wrote {out_path} source_status={payload['source_status']} all_pass={all_pass}")
    if payload["source_status"] != "available":
        return 2
    return 0 if args.mode == "preflight" or all_pass else 3


if __name__ == "__main__":
    sys.exit(main())
