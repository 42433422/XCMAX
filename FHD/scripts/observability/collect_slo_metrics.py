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
import math
import os
import re
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
METRICS_DIR = ROOT / "metrics"
PRODUCTION_EVIDENCE_DIR = METRICS_DIR / "slo-production"

# This fixed target inventory/interval is checked against prometheus.production.yml.
# Do not discover only currently healthy targets: a disappeared target must block.
SCRAPE_INTERVAL_SECONDS = 15
SCRAPE_WINDOW_SECONDS = 86400
SCRAPE_TARGETS = {
    "fhd-api-stable": "127.0.0.1:5100",
    "modstore-api-production": "127.0.0.1:9999",
}
SCRAPE_SERVICES = {
    "fhd-api-stable": "fhd",
    "modstore-api-production": "modstore",
}
SCRAPE_QUERIES = {
    job: (
        f'sum(sum_over_time(up{{environment="production",job="{job}",'
        f'instance="{instance}",service="{SCRAPE_SERVICES[job]}"}}[1d]))'
    )
    for job, instance in SCRAPE_TARGETS.items()
}
# Host-local Prometheus address queried over `ssh host curl` (no TCP forwarding).
HOST_LOCAL_PROMETHEUS = "http://127.0.0.1:9091"

# Ratio denominators use the actual count. PromQL `> 0` (without `bool`)
# filters missing/zero traffic without rounding sparse traffic up to one RPS.
QUERIES = {
    "SLO-API-01": (
        '1 - ((sum(increase(api_requests_total{{environment="production",status=~"5.."}}[{w}])) '
        "or vector(0)) / (sum(increase(api_requests_total"
        '{{environment="production"}}[{w}])) > 0))'
    ),
    "SLO-API-02": (
        "histogram_quantile(0.95, sum by (le) (rate(api_request_duration_seconds_bucket"
        '{{environment="production",endpoint="/api/auth/login"}}[{w}]))) * 1000'
    ),
    "SLO-API-03": (
        '(sum(increase(api_requests_total{{environment="production",status=~"5.."}}[{w}])) '
        'or vector(0)) / (sum(increase(api_requests_total{{environment="production"}}[{w}])) > 0)'
    ),
    "SLO-AI-01": (
        "histogram_quantile(0.95, sum by (le) (rate(chat_stream_first_byte_seconds_bucket"
        '{{environment="production"}}[{w}]))) * 1000'
    ),
    "SLO-BUS-01": (
        '(1 - ((sum(increase(neurobus_events_dead_lettered_total{{environment="production"}}[{w}])) '
        'or vector(0)) + (sum(increase(neurobus_events_lost_total{{environment="production"}}[{w}])) '
        "or vector(0))) / (sum(increase(neurobus_events_published_total"
        '{{environment="production"}}[{w}])) > 0))'
    ),
    "SLO-BIZ-01": (
        "histogram_quantile(0.95, sum by (le) (rate(customer_op_duration_seconds_bucket"
        '{{environment="production"}}[{w}]))) * 1000'
    ),
    "SLO-BIZ-02": (
        '(sum(increase(customer_op_total{{environment="production",status="error"}}[{w}])) '
        'or vector(0)) / (sum(increase(customer_op_total{{environment="production"}}[{w}])) > 0)'
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
        "or vector(0)) / (sum(increase(mod_install_total"
        '{{environment="production",device_scope="external_customer"}}[{w}])) > 0))'
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


# Transient transport failures (ConnectionResetError on every run since
# 2026-10-17 through the forwarded port). Retry with backoff; never invent readings.
_TRANSIENT_QUERY_ERRORS = (
    ConnectionError,
    TimeoutError,
    urllib.error.URLError,
)


class SshTransport:
    """Run `curl` against the host-local Prometheus through an SSH exec channel.

    Exec channels do not depend on sshd TCP forwarding, so a disabled forward or
    a reset tunnel can no longer silently drop every reading.
    """

    def __init__(self, target: str, control_path: str = "") -> None:
        self.target = target
        self.control_path = control_path

    def get(self, path: str, params: dict[str, str]) -> dict[str, Any]:
        remote = ["curl", "-fsS", "--max-time", "60", "-G"]
        if "query" in params:
            remote += ["--data-urlencode", "query@-"]
        for key, value in params.items():
            if key != "query":
                remote += ["--data-urlencode", f"{key}={value}"]
        remote.append(f"{HOST_LOCAL_PROMETHEUS}{path}")
        command = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=20"]
        if self.control_path:
            command += ["-S", self.control_path]
        command += [self.target, shlex.join(remote)]
        try:
            proc = subprocess.run(
                command,
                input=params.get("query", "").encode(),
                capture_output=True,
                timeout=90,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError("ssh_exec_timeout") from exc
        if proc.returncode != 0:
            raise ConnectionError(f"ssh_exec_exit_{proc.returncode}")
        return json.loads(proc.stdout.decode())


def _prom_get(
    base_url: str,
    path: str,
    params: dict[str, str],
    bearer_token: str = "",
    ssh: SshTransport | None = None,
) -> dict[str, Any]:
    if ssh is not None:
        return ssh.get(path, params)
    url = f"{base_url.rstrip('/')}{path}?{urllib.parse.urlencode(params)}"
    headers = {"Connection": "close"}
    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


_DURATION_UNITS = {
    "y": 365.0,
    "w": 7.0,
    "d": 1.0,
    "h": 1 / 24,
    "m": 1 / 1440,
    "s": 1 / 86400,
    "ms": 1 / 86_400_000,
}


def measure_retention_days(
    base_url: str, bearer_token: str = "", ssh: SshTransport | None = None
) -> float | None:
    """Read --storage.tsdb.retention.time from the live server, not from a CI variable."""
    try:
        flags = _prom_get(base_url, "/api/v1/status/flags", {}, bearer_token, ssh)
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(flags, dict) or flags.get("status") != "success":
        return None
    data = flags.get("data")
    if not isinstance(data, dict):
        return None
    raw = str(data.get("storage.tsdb.retention.time") or "")
    parts = re.findall(r"(\d+)(ms|y|w|d|h|m|s)", raw)
    if not parts or "".join(n + u for n, u in parts) != raw:
        return None
    return sum(int(n) * _DURATION_UNITS[u] for n, u in parts)


def prom_query(
    base_url: str,
    expr: str,
    bearer_token: str = "",
    query_at: datetime | None = None,
    *,
    attempts: int = 4,
    backoff_seconds: float = 0.75,
    ssh: SshTransport | None = None,
) -> str | None:
    from tenacity import Retrying, retry_if_exception_type, stop_after_attempt, wait_incrementing

    params = {"query": expr}
    if query_at is not None:
        params["time"] = query_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
    for attempt in Retrying(
        retry=retry_if_exception_type(_TRANSIENT_QUERY_ERRORS),
        stop=stop_after_attempt(max(attempts, 1)),
        wait=wait_incrementing(start=backoff_seconds, increment=backoff_seconds),
        sleep=time.sleep,
        reraise=True,
    ):
        with attempt:
            data = _prom_get(base_url, "/api/v1/query", params, bearer_token, ssh)
            if not isinstance(data, dict) or data.get("status") != "success":
                raise RuntimeError("prometheus_query_failed")
            content = data.get("data")
            if not isinstance(content, dict) or not isinstance(content.get("result"), list):
                raise ValueError("prometheus_query_invalid_vector")
            results = content["result"]
            if not results:
                return None
            # Aggregate expressions must yield exactly one series; selecting
            # only the first could certify a healthy subset of failing targets.
            if len(results) != 1:
                raise ValueError("prometheus_query_ambiguous_series")
            sample = results[0].get("value") if isinstance(results[0], dict) else None
            if not isinstance(sample, list) or len(sample) != 2:
                raise ValueError("prometheus_query_invalid_sample")
            return str(sample[1])
    return None


def telemetry_admissible(payload: dict[str, Any]) -> bool:
    """True only when every SLO has a real sample and scrape coverage is intact."""
    if payload.get("source_status") != "available":
        return False
    if _numeric(payload.get("coverage")) != 1.0 or scrape_errors(payload):
        return False
    if (_numeric(payload.get("scrape_coverage")) or 0) < 0.99:
        return False
    if (
        payload.get("raw_metric_retention_source") != "prometheus_flags"
        or (_numeric(payload.get("raw_metric_retention_days")) or 0) < 120
    ):
        return False
    readings = payload.get("readings") or {}
    if not isinstance(readings, dict) or set(readings) != set(TARGETS):
        return False
    for slo_id, item in readings.items():
        if not isinstance(item, dict):
            return False
        value = _numeric(item.get("reading_numeric"))
        if meets_target(slo_id, value) is None:
            return False
        if (_numeric(item.get("sample_count")) or 0) <= 0:
            return False
        if (
            item.get("promql") != QUERIES[slo_id].format(w=payload.get("window"))
            or item.get("sample_promql") != SAMPLE_QUERIES[slo_id].format(w=payload.get("window"))
            or _numeric(item.get("reading")) != value
        ):
            return False
    return True


def _numeric(raw: Any) -> float | None:
    if isinstance(raw, bool):
        return None
    try:
        value = float(raw)
    except (ValueError, TypeError, OverflowError):
        return None
    return value if math.isfinite(value) else None


def scrape_errors(payload: dict[str, Any]) -> list[str]:
    """Recompute coverage from the fixed Prometheus inventory and raw counts."""
    errors: list[str] = []
    evidence = payload.get("scrape_evidence")
    evidence = evidence if isinstance(evidence, dict) else {}
    expected = SCRAPE_WINDOW_SECONDS / SCRAPE_INTERVAL_SECONDS
    for job, instance in SCRAPE_TARGETS.items():
        item = evidence.get(job)
        if not isinstance(item, dict):
            errors.append(f"{job}:scrape_evidence_missing")
            continue
        count = _numeric(item.get("successful_scrapes"))
        coverage = _numeric(item.get("coverage"))
        if (
            item.get("instance") != instance
            or item.get("promql") != SCRAPE_QUERIES[job]
            or item.get("window_seconds") != SCRAPE_WINDOW_SECONDS
            or item.get("interval_seconds") != SCRAPE_INTERVAL_SECONDS
            or item.get("expected_scrapes") != expected
        ):
            errors.append(f"{job}:scrape_source_mismatch")
        if (
            count is None
            or not 0 <= count <= expected + 1
            or coverage is None
            or not math.isclose(coverage, min(count / expected, 1.0), abs_tol=1e-12)
            or coverage < 0.99
        ):
            errors.append(f"{job}:scrape_coverage:{coverage}")
    return errors


def meets_target(slo_id: str, value: float | None) -> bool | None:
    if value is None:
        return None
    _name, threshold, op = TARGETS[slo_id]
    if not math.isfinite(value) or value < 0 or (threshold <= 1 and value > 1):
        return None
    return value >= threshold if op == "ge" else value < threshold


def _record_hash_is_valid(payload: dict[str, Any]) -> bool:
    candidate = dict(payload)
    expected = str(candidate.pop("evidence_hash", ""))
    candidate.pop("chain_hash", None)
    candidate.pop("all_pass", None)
    return bool(
        expected and expected == hashlib.sha256(_canonical_json(candidate).encode()).hexdigest()
    )


def _order_chain(
    pending: list[tuple[Path, dict[str, Any]]],
) -> tuple[list[dict[str, Any]], list[str], str]:
    pending = list(pending)
    records: list[dict[str, Any]] = []
    blockers: list[str] = []
    previous_hash = "0" * 64
    while pending:
        successors = [
            item for item in pending if item[1].get("previous_chain_hash") == previous_hash
        ]
        if len(successors) != 1:
            blockers.append("forked_hash_chain" if successors else "broken_hash_chain")
            break
        path, payload = successors[0]
        pending.remove(successors[0])
        expected = hashlib.sha256(
            f"{previous_hash}:{payload['evidence_hash']}".encode()
        ).hexdigest()
        if payload.get("chain_hash") != expected:
            blockers.append(f"{path.name}:invalid_chain_hash")
        previous_hash = str(payload.get("chain_hash") or "")
        records.append(payload)
    return records, blockers, previous_hash


def _legacy_preflight_audit(records: list[tuple[Path, dict[str, Any]]]) -> dict[str, Any]:
    """Fingerprint a reachable fork of unbound preflight records, never formal history."""
    successors: dict[str, list[str]] = {}
    inventory: list[dict[str, str]] = []
    hashes: set[str] = set()
    for path, payload in records:
        if payload.get("mode") != "preflight" or payload.get("release_id") != "":
            raise ValueError("legacy_fork_contains_formal_or_release_bound_evidence")
        if "chain_epoch" in payload or "legacy_chain_audit" in payload:
            raise ValueError("legacy_fork_contains_epoch_metadata")
        previous = str(payload.get("previous_chain_hash") or "")
        chain_hash = str(payload.get("chain_hash") or "")
        expected = hashlib.sha256(f"{previous}:{payload['evidence_hash']}".encode()).hexdigest()
        if not re.fullmatch(r"[0-9a-f]{64}", previous) or chain_hash != expected:
            raise ValueError("legacy_fork_has_invalid_chain_hash")
        if chain_hash in hashes:
            raise ValueError("legacy_fork_has_duplicate_record")
        hashes.add(chain_hash)
        successors.setdefault(previous, []).append(chain_hash)
        inventory.append(
            {
                "file": path.name,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "evidence_hash": payload["evidence_hash"],
                "chain_hash": chain_hash,
                "previous_chain_hash": previous,
            }
        )
    reached: set[str] = set()
    pending = list(successors.get("0" * 64, []))
    while pending:
        chain_hash = pending.pop()
        if chain_hash in reached:
            raise ValueError("legacy_fork_has_cycle")
        reached.add(chain_hash)
        pending.extend(successors.get(chain_hash, []))
    if reached != hashes:
        raise ValueError("legacy_fork_has_missing_predecessor")
    forks = [
        {"previous_chain_hash": previous, "successors": sorted(children)}
        for previous, children in sorted(successors.items())
        if len(children) > 1
    ]
    if not forks:
        raise ValueError("legacy_fork_audit_requires_a_fork")
    return {
        "schema": "xcagi.production_slo_legacy_fork_audit/v1",
        "reason": "legacy_unbound_preflight_fork",
        "record_count": len(inventory),
        "records": inventory,
        "forks": forks,
        "tips": sorted(hashes - successors.keys()),
    }


def load_evidence_chain(
    directory: Path, *, recover_preflight_fork: bool = False
) -> tuple[list[dict[str, Any]], list[str], str, str, dict[str, Any] | None]:
    """Validate the existing chain, including one explicitly audited legacy recovery.

    Old bytes stay in place. Only a fork made entirely of unbound preflight
    records can be archived by the first new epoch record. Its hash-bound
    payload contains the full original inventory; later deletion, rewriting,
    extra legacy records, or a fork in the new epoch fails closed.
    """
    blockers: list[str] = []
    legacy: list[tuple[Path, dict[str, Any]]] = []
    active: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted(directory.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError):
            blockers.append(f"{path.name}:invalid_json")
            continue
        if not isinstance(payload, dict) or not _record_hash_is_valid(payload):
            blockers.append(f"{path.name}:invalid_evidence_hash")
            continue
        try:
            stamp = datetime.fromisoformat(str(payload.get("generated_at")).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            stamp = None
        if (
            payload.get("schema") != "xcagi.production_slo_evidence/v1"
            or payload.get("environment") != "production"
            or stamp is None
            or stamp.tzinfo is None
        ):
            blockers.append(f"{path.name}:invalid_production_record")
        (active if "chain_epoch" in payload else legacy).append((path, payload))

    if not active:
        records, errors, tip = _order_chain(legacy)
        if recover_preflight_fork and not blockers and errors == ["forked_hash_chain"]:
            try:
                audit = _legacy_preflight_audit(legacy)
            except ValueError as exc:
                errors.append(str(exc))
            else:
                epoch = hashlib.sha256(_canonical_json(audit).encode()).hexdigest()
                return [], [], "0" * 64, epoch, audit
        return records, blockers + errors, tip, "", None

    records, errors, tip = _order_chain(active)
    blockers.extend(errors)
    audit = None
    epoch = ""
    try:
        audit = _legacy_preflight_audit(legacy)
    except ValueError as exc:
        blockers.append(str(exc))
    else:
        epoch = hashlib.sha256(_canonical_json(audit).encode()).hexdigest()
        if any(payload.get("chain_epoch") != epoch for _path, payload in active):
            blockers.append("legacy_chain_epoch_mismatch")
        roots = [
            payload for _path, payload in active if payload.get("previous_chain_hash") == "0" * 64
        ]
        if len(roots) != 1 or roots[0].get("legacy_chain_audit") != audit:
            blockers.append("legacy_chain_audit_mismatch")
        if any(
            "legacy_chain_audit" in payload for _path, payload in active if payload not in roots
        ):
            blockers.append("unexpected_legacy_chain_audit")
    # Audited preflight observations remain visible in the daily ledger. The
    # formal verifier still counts only the requested release's formal samples.
    return [payload for _path, payload in legacy] + records, blockers, tip, epoch, audit


def _write_immutable(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as exc:
        raise FileExistsError(f"refusing to overwrite SLO evidence: {path}") from exc


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
    ssh: SshTransport | None = None,
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
    source_errors: list[str] = []
    readings: dict[str, dict[str, Any]] = {}
    credentials_available = ssh is not None or bool(prom_url.strip() and prom_token.strip())
    if not credentials_available:
        source_errors.append("production_prometheus_credentials_unavailable")
        errors.extend(source_errors)
    retention_source = "declared"
    if credentials_available:
        measured = measure_retention_days(prom_url, prom_token, ssh)
        if measured is not None:
            raw_retention_days, retention_source = measured, "prometheus_flags"
    if retention_source != "prometheus_flags":
        errors.append("raw_metric_retention_not_measured")
    if raw_retention_days < 120:
        errors.append(f"raw_metric_retention_below_120_days:{raw_retention_days}")

    scrape_evidence: dict[str, dict[str, Any]] = {}
    expected_scrapes = SCRAPE_WINDOW_SECONDS / SCRAPE_INTERVAL_SECONDS
    for job, expr in SCRAPE_QUERIES.items():
        successful_scrapes = None
        if credentials_available:
            try:
                successful_scrapes = _numeric(
                    prom_query(prom_url, expr, bearer_token=prom_token, query_at=current, ssh=ssh)
                )
            except (OSError, ValueError, TypeError, RuntimeError) as exc:
                source_error = f"{job}:scrape_source_unavailable:{type(exc).__name__}"
                source_errors.append(source_error)
                errors.append(source_error)
        valid_count = (
            successful_scrapes is not None and 0 <= successful_scrapes <= expected_scrapes + 1
        )
        # One endpoint-boundary sample of scrape jitter is harmless; a faster
        # interval or duplicate target must not compensate for a missing target.
        ratio = (
            min(successful_scrapes / expected_scrapes, 1.0)
            if valid_count and successful_scrapes is not None
            else None
        )
        if ratio is None:
            errors.append(f"{job}:scrape_coverage_missing_or_invalid")
        elif ratio < 0.99:
            errors.append(f"{job}:scrape_coverage_below_99_percent")
        scrape_evidence[job] = {
            "instance": SCRAPE_TARGETS[job],
            "promql": expr,
            "window_seconds": SCRAPE_WINDOW_SECONDS,
            "interval_seconds": SCRAPE_INTERVAL_SECONDS,
            "expected_scrapes": expected_scrapes,
            "successful_scrapes": successful_scrapes,
            "coverage": ratio,
        }
    scrape_coverage = min(item["coverage"] or 0.0 for item in scrape_evidence.values())

    for slo_id, template in QUERIES.items():
        expr = template.format(w=window)
        sample_expr = SAMPLE_QUERIES[slo_id].format(w=window)
        raw: str | None = None
        sample_raw: str | None = None
        if credentials_available:
            try:
                raw = prom_query(prom_url, expr, bearer_token=prom_token, query_at=current, ssh=ssh)
                sample_raw = prom_query(
                    prom_url, sample_expr, bearer_token=prom_token, query_at=current, ssh=ssh
                )
            except (OSError, ValueError, TypeError, RuntimeError) as exc:
                source_error = f"{slo_id}:source_unavailable:{type(exc).__name__}"
                source_errors.append(source_error)
                errors.append(source_error)
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

    source_status = "source_unavailable" if source_errors else "available"
    coverage = sum(1 for item in readings.values() if item["reading_numeric"] is not None) / len(
        readings
    )
    day0_eligible = bool(
        source_status == "available"
        and not errors
        and coverage >= 0.99
        and scrape_coverage >= 0.99
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
        "transport": "ssh-exec" if ssh is not None else "http",
        "window": window,
        "raw_metric_retention_days": raw_retention_days,
        "raw_metric_retention_source": retention_source,
        "source_status": source_status,
        "source_errors": sorted(set(source_errors)),
        "coverage": coverage,
        "scrape_coverage": scrape_coverage,
        "scrape_evidence": scrape_evidence,
        "day0_eligible": day0_eligible,
        "errors": sorted(set(errors)),
        "readings": readings,
    }
    all_pass = (
        source_status == "available"
        and not errors
        and coverage == 1.0
        and all(item["passes"] is True for item in readings.values())
    )
    # One append owns both the predecessor and exclusive publication. filelock
    # is already pinned by the runtime; simultaneous collectors cannot fork it.
    from filelock import FileLock

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(out_path.parent / ".slo-evidence.lock", timeout=30):
        _records, blockers, previous_hash, epoch, audit = load_evidence_chain(
            out_path.parent, recover_preflight_fork=True
        )
        if blockers:
            raise ValueError("SLO evidence chain is invalid: " + ";".join(blockers))
        if epoch:
            payload["chain_epoch"] = epoch
            if previous_hash == "0" * 64:
                payload["legacy_chain_audit"] = audit
        payload["previous_chain_hash"] = previous_hash
        payload["evidence_hash"] = hashlib.sha256(_canonical_json(payload).encode()).hexdigest()
        payload["chain_hash"] = hashlib.sha256(
            f"{previous_hash}:{payload['evidence_hash']}".encode()
        ).hexdigest()
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
    parser.add_argument(
        "--ssh-target", default=os.environ.get("PRODUCTION_PROMETHEUS_SSH_TARGET", "")
    )
    parser.add_argument(
        "--ssh-control", default=os.environ.get("PRODUCTION_PROMETHEUS_SSH_CONTROL", "")
    )
    parser.add_argument("--out", default="")
    args = parser.parse_args()
    ssh = SshTransport(args.ssh_target, args.ssh_control) if args.ssh_target else None
    if ssh is not None:
        args.prom_url = HOST_LOCAL_PROMETHEUS

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
        for value in (
            os.environ.get("GITHUB_RUN_ID", ""),
            os.environ.get("GITHUB_RUN_ATTEMPT", ""),
        )
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
        ssh=ssh,
    )
    print(
        f"Wrote {out_path} source_status={payload['source_status']} "
        f"coverage={payload['coverage']} scrape_coverage={payload['scrape_coverage']} "
        f"all_pass={all_pass} day0_eligible={payload['day0_eligible']}"
    )
    # Missing / reset telemetry must fail loudly in every mode — never treat
    # source_unavailable or empty coverage as a successful preflight.
    if not telemetry_admissible(payload):
        return 2
    return 0 if args.mode == "preflight" or all_pass else 3


if __name__ == "__main__":
    sys.exit(main())
