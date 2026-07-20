"""CVM + 本机双端 health 系统状态日报（2026-07-20 Week 3 任务 4）。

每 30 分钟采样所有 endpoint 的 /api/health，写入 JSONL；每天 23:55 Asia/Shanghai
滚一份日报 JSON，含每端可用率 / 状态分类（ok|warn|critical）/ 样本数 / 失败样本。

设计要点：
- ``httpx.Client(trust_env=False)`` 绕过 http_proxy 环境变量，否则本机
  ``http://127.0.0.1:8788`` 会走代理 502。
- 原子写日报：``report.json.tmp`` + ``os.replace``。
- 样本与日报同目录 ``$MODSTORE_RUNTIME_DIR/``，与 self_maintenance_loop_memory
  并列，便于 ops 一把抓。
- 采样失败也写样本（``ok=False``），可用率分母是总样本数，不是成功样本数。
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_DEFAULT_ENDPOINTS = (
    "cvm|https://xiu-ci.com/fhd-api/api/health",
    "local_api|http://127.0.0.1:8788/api/health",
    "local_scheduler|http://127.0.0.1:8789/api/health",
)
_SAMPLE_FILENAME = "system_status_health.jsonl"
_REPORT_FILENAME = "system_status_daily_report.json"
_SAMPLE_RETENTION_DAYS = 14
_AVAIL_OK_THRESHOLD = 99.0
_AVAIL_WARN_THRESHOLD = 95.0


def _runtime_dir() -> Path:
    """Return MODSTORE_RUNTIME_DIR or fallback to ~/Library/Application Support/XCMAX/modstore-daily/runtime."""
    raw = os.environ.get("MODSTORE_RUNTIME_DIR")
    if raw:
        return Path(raw)
    return Path.home() / "Library" / "Application Support" / "XCMAX" / "modstore-daily" / "runtime"


def _sample_path() -> Path:
    return _runtime_dir() / _SAMPLE_FILENAME


def _report_path() -> Path:
    return _runtime_dir() / _REPORT_FILENAME


def configured_endpoints() -> List[Tuple[str, str]]:
    """Parse MODSTORE_SYSTEM_STATUS_ENDPOINTS env (``name|url,name|url``).

    Empty/malformed entries are dropped. Falls back to the 3-endpoint default
    (CVM + local API + local scheduler) when env is unset/empty.
    """
    raw = os.environ.get("MODSTORE_SYSTEM_STATUS_ENDPOINTS", "").strip()
    if not raw:
        return [(name, url) for name, url in (item.split("|", 1) for item in _DEFAULT_ENDPOINTS)]

    endpoints: List[Tuple[str, str]] = []
    for item in raw.split(","):
        item = item.strip()
        if not item or "|" not in item:
            continue
        name, url = item.split("|", 1)
        name = name.strip()
        url = url.strip()
        if name and url:
            endpoints.append((name, url))
    return endpoints


def probe_endpoint(name: str, url: str, timeout: float = 5.0) -> Dict[str, Any]:
    """Probe a single endpoint with ``httpx.Client(trust_env=False)``.

    ``trust_env=False`` is critical: the dev box has ``http_proxy=127.0.0.1:7890``
    in env, which makes local ``http://127.0.0.1:*`` requests route through the
    proxy and 502. Disabling env proxy lookup forces direct connection.

    Returns a sample dict with ``ok`` / ``status_code`` / ``latency_ms`` /
    ``error``. Never raises — callers (APScheduler) need stable behavior.
    """
    import httpx

    started = time.monotonic()
    try:
        with httpx.Client(timeout=timeout, trust_env=False) as client:
            response = client.get(url)
        latency_ms = round((time.monotonic() - started) * 1000.0, 1)
        ok = response.status_code == 200
        body: Any = None
        try:
            body = response.json()
        except Exception:
            body = None
        return {
            "name": name,
            "url": url,
            "ok": ok,
            "status_code": response.status_code,
            "latency_ms": latency_ms,
            "body": body if ok else None,
            "error": None if ok else f"unexpected status {response.status_code}",
        }
    except httpx.HTTPError as exc:
        latency_ms = round((time.monotonic() - started) * 1000.0, 1)
        return {
            "name": name,
            "url": url,
            "ok": False,
            "status_code": None,
            "latency_ms": latency_ms,
            "body": None,
            "error": f"{type(exc).__name__}: {exc}",
        }
    except Exception as exc:  # pragma: no cover - defensive
        latency_ms = round((time.monotonic() - started) * 1000.0, 1)
        return {
            "name": name,
            "url": url,
            "ok": False,
            "status_code": None,
            "latency_ms": latency_ms,
            "body": None,
            "error": f"{type(exc).__name__}: {exc}",
        }


def append_sample(sample: Dict[str, Any]) -> None:
    """Append one sample record to JSONL. Auto-creates parent dir."""
    path = _sample_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(sample, ensure_ascii=False, separators=(",", ":")) + "\n"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line)


def sample_once() -> Dict[str, Any]:
    """Probe all configured endpoints and append one aggregate sample.

    Returns the sample dict (also written to disk). Errors per-endpoint are
    captured inside ``endpoints[]`` — the function itself never raises.
    """
    now = _utc_now()
    endpoints = configured_endpoints()
    probes = [probe_endpoint(name, url) for name, url in endpoints]
    sample = {
        "timestamp": _iso(now),
        "ok_count": sum(1 for p in probes if p.get("ok")),
        "total_count": len(probes),
        "endpoints": probes,
    }
    try:
        append_sample(sample)
    except Exception:
        logger.exception("append system_status sample failed")
    return sample


def _read_samples(limit: int = 5000) -> List[Dict[str, Any]]:
    path = _sample_path()
    if not path.exists():
        return []
    samples: List[Dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    samples.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except Exception:
        logger.exception("read system_status samples failed")
        return []
    if limit > 0:
        return samples[-limit:]
    return samples


def compute_availability(
    samples: List[Dict[str, Any]], window_hours: int = 24
) -> Dict[str, Dict[str, Any]]:
    """Per-endpoint availability over the last ``window_hours``.

    Returns ``{name: {total, ok, availability_pct, last_status, last_error, last_ts}}``.
    Samples without the endpoint name (old/malformed) are skipped.
    """
    cutoff = _utc_now() - timedelta(hours=window_hours)
    by_endpoint: Dict[str, Dict[str, Any]] = {}

    for sample in samples:
        ts = _parse_iso(sample.get("timestamp"))
        if ts is None or ts < cutoff:
            continue
        for probe in sample.get("endpoints") or []:
            if not isinstance(probe, dict):
                continue
            name = str(probe.get("name") or "")
            if not name:
                continue
            entry = by_endpoint.setdefault(
                name, {"total": 0, "ok": 0, "last_status": None, "last_error": None, "last_ts": None}
            )
            entry["total"] += 1
            if probe.get("ok"):
                entry["ok"] += 1
                entry["last_status"] = probe.get("status_code")
                entry["last_error"] = None
            else:
                entry["last_status"] = probe.get("status_code")
                entry["last_error"] = probe.get("error")
            entry["last_ts"] = sample.get("timestamp")

    for entry in by_endpoint.values():
        total = entry["total"]
        entry["availability_pct"] = round((entry["ok"] / total * 100.0) if total else 0.0, 2)
    return by_endpoint


def _classify_health(avail_pct: float) -> str:
    if avail_pct >= _AVAIL_OK_THRESHOLD:
        return "ok"
    if avail_pct >= _AVAIL_WARN_THRESHOLD:
        return "warn"
    return "critical"


def generate_daily_report(
    samples: List[Dict[str, Any]], date: Optional[datetime] = None
) -> Dict[str, Any]:
    """Build the daily report dict from samples.

    ``date`` is the report date (defaults to UTC now). The report covers the
    24h window ending at ``date``. Each endpoint gets availability %, health
    class, total/ok sample counts, last error.
    """
    report_time = date or _utc_now()
    availability = compute_availability(samples, window_hours=24)
    overall_ok = 0
    overall_total = 0
    endpoints_summary: List[Dict[str, Any]] = []
    for name, entry in sorted(availability.items()):
        avail = float(entry.get("availability_pct") or 0.0)
        endpoints_summary.append(
            {
                "name": name,
                "availability_pct": avail,
                "health": _classify_health(avail),
                "total_samples": entry["total"],
                "ok_samples": entry["ok"],
                "last_status_code": entry["last_status"],
                "last_error": entry["last_error"],
                "last_sample_ts": entry["last_ts"],
            }
        )
        overall_ok += entry["ok"]
        overall_total += entry["total"]

    overall_avail = round((overall_ok / overall_total * 100.0) if overall_total else 0.0, 2)
    return {
        "report_date": _iso(report_time),
        "window_hours": 24,
        "overall": {
            "availability_pct": overall_avail,
            "health": _classify_health(overall_avail),
            "total_samples": overall_total,
            "ok_samples": overall_ok,
        },
        "endpoints": endpoints_summary,
        "sample_file": str(_sample_path()),
    }


def write_daily_report(report: Dict[str, Any]) -> Path:
    """Atomically write the daily report JSON (``.tmp`` + ``os.replace``)."""
    path = _report_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2, sort_keys=True)
    os.replace(tmp, path)
    return path


def cleanup_old_samples(days: int = _SAMPLE_RETENTION_DAYS) -> int:
    """Drop samples older than ``days`` days from the JSONL. Returns dropped count."""
    cutoff = _utc_now() - timedelta(days=days)
    path = _sample_path()
    if not path.exists():
        return 0
    kept: List[str] = []
    dropped = 0
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line_stripped = line.strip()
                if not line_stripped:
                    continue
                try:
                    sample = json.loads(line_stripped)
                except json.JSONDecodeError:
                    continue
                ts = _parse_iso(sample.get("timestamp"))
                if ts is None or ts < cutoff:
                    dropped += 1
                    continue
                kept.append(line_stripped)
    except Exception:
        logger.exception("read samples for cleanup failed")
        return 0
    if dropped == 0:
        return 0
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        for line in kept:
            fh.write(line + "\n")
    os.replace(tmp, path)
    return dropped


# ---- ISO time helpers (mirrors self_maintenance_loop_runner) ---------------


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _parse_iso(value: Any) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# ---- APScheduler entry points ---------------------------------------------


def system_status_sample_job() -> None:
    """APScheduler entry: probe endpoints + append sample + cleanup old samples.

    Registered as ``IntervalTrigger(minutes=30)`` in ``workflow_scheduler``.
    """
    try:
        sample_once()
    except Exception:
        logger.exception("system_status_sample_job failed")
    try:
        cleanup_old_samples()
    except Exception:
        logger.exception("cleanup_old_samples failed")


def system_status_daily_summary_job() -> None:
    """APScheduler entry: roll 24h samples into a daily report JSON.

    Registered as ``CronTrigger(hour=23, minute=55, timezone=Asia/Shanghai)``
    in ``workflow_scheduler``.
    """
    try:
        samples = _read_samples()
        report = generate_daily_report(samples)
        path = write_daily_report(report)
        logger.info(
            "system_status daily report written: path=%s overall=%s health=%s endpoints=%d",
            path,
            report["overall"]["availability_pct"],
            report["overall"]["health"],
            len(report["endpoints"]),
        )
    except Exception:
        logger.exception("system_status_daily_summary_job failed")
