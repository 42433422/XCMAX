"""Privacy-safe public aggregates for the official visualization page.

The endpoint deliberately reads the same production artefacts that operators
use to verify releases: Nginx access logs for traffic and the public release
manifest for product delivery state.  It never returns request paths, client
addresses, account data, or conversation content.
"""

from __future__ import annotations

import copy
import glob
import gzip
import json
import os
import re
import threading
import time
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, TextIO
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Response
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

router = APIRouter(tags=["public-data"])

_DEFAULT_LOG_GLOB = "/var/log/nginx/xiu-ci.com.access.log*"
_DEFAULT_CACHE_TTL_SECONDS = 30
_DEFAULT_TREND_DAYS = 10
_SHANGHAI = ZoneInfo("Asia/Shanghai")
_MONTHS = {
    "Jan": 1,
    "Feb": 2,
    "Mar": 3,
    "Apr": 4,
    "May": 5,
    "Jun": 6,
    "Jul": 7,
    "Aug": 8,
    "Sep": 9,
    "Oct": 10,
    "Nov": 11,
    "Dec": 12,
}
_LOG_RE = re.compile(
    r"^\S+\s+\S+\s+\S+\s+\[(?P<stamp>[^\]]+)\]\s+"
    r'"(?P<method>[A-Z]+)\s+(?P<target>\S+)\s+HTTP/[^\"]+"\s+'
    r"(?P<status>\d{3})\s+\S+"
)
_STAMP_DATE_RE = re.compile(r"^(?P<day>\d{2})/(?P<month>[A-Z][a-z]{2})/(?P<year>\d{4}):")
_DOWNLOAD_PREFIXES = ("/xcagi-v", "/releases/stable/", "/downloads/kellai/")
_DOWNLOAD_PLATFORM_BY_SUFFIX = {
    ".exe": "windows",
    ".dmg": "macos",
    ".apk": "android",
}

_CACHE_LOCK = threading.Lock()
_CACHE_VALUE: dict[str, Any] | None = None
_CACHE_CREATED_MONOTONIC = 0.0


def _positive_int_env(name: str, default: int, *, maximum: int) -> int:
    try:
        value = int((os.environ.get(name) or "").strip())
    except ValueError:
        return default
    if value <= 0:
        return default
    return min(value, maximum)


def _cache_ttl_seconds() -> int:
    return _positive_int_env(
        "XIUCI_VISUALIZATION_CACHE_TTL_SECONDS",
        _DEFAULT_CACHE_TTL_SECONDS,
        maximum=300,
    )


def _trend_days() -> int:
    return _positive_int_env(
        "XIUCI_VISUALIZATION_TREND_DAYS",
        _DEFAULT_TREND_DAYS,
        maximum=31,
    )


def _release_manifest_path() -> Path:
    configured = (os.environ.get("XIUCI_VISUALIZATION_RELEASE_MANIFEST") or "").strip()
    if configured:
        return Path(configured).expanduser()
    site_root = Path(__file__).resolve().parents[2]
    candidates = (
        site_root / "download-release.json",
        site_root.parent / "FHD" / "config" / "download_release.json",
    )
    for path in candidates:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if (
            isinstance(raw, dict)
            and isinstance(raw.get("release_history"), list)
            and raw["release_history"]
        ):
            return path
    return candidates[0]


def _access_log_paths() -> list[Path]:
    pattern = (os.environ.get("XIUCI_VISUALIZATION_ACCESS_LOG_GLOB") or "").strip()
    matches = glob.glob(pattern or _DEFAULT_LOG_GLOB)
    return sorted((Path(match) for match in matches if Path(match).is_file()), key=str)


def _open_log(path: Path) -> TextIO:
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8", errors="replace")
    return path.open("r", encoding="utf-8", errors="replace")


def _parse_log_date(stamp: str) -> date | None:
    match = _STAMP_DATE_RE.match(stamp)
    if not match:
        return None
    month = _MONTHS.get(match.group("month"))
    if month is None:
        return None
    try:
        return date(int(match.group("year")), month, int(match.group("day")))
    except ValueError:
        return None


def _short_date(value: date | None) -> str | None:
    return value.strftime("%m.%d") if value is not None else None


def _iso_date(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _empty_traffic_metrics() -> tuple[dict[str, Any], dict[str, Any]]:
    return (
        {
            "chat_requests": None,
            "chat_success": None,
            "success_rate": None,
            "window_start": None,
            "window_end": None,
            "window_start_short": None,
            "window_end_short": None,
        },
        {
            "total": None,
            "platforms": {"windows": None, "macos": None, "android": None},
            "products": {"xcagi": None, "kellai": None},
            "daily": [],
            "window_start": None,
            "window_end": None,
            "window_start_short": None,
            "window_end_short": None,
        },
    )


def _read_traffic_metrics(
    paths: list[Path],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    ai_total = 0
    ai_success = 0
    api_requests = 0
    api_5xx = 0
    mod_requests = 0
    downloads_total = 0
    download_platforms: Counter[str] = Counter()
    download_products: Counter[str] = Counter()
    download_daily: Counter[date] = Counter()
    retained_start: date | None = None
    retained_end: date | None = None
    parsed_lines = 0
    unreadable_files = 0
    source_mtime = 0.0

    for path in paths:
        try:
            source_mtime = max(source_mtime, path.stat().st_mtime)
            with _open_log(path) as handle:
                for line in handle:
                    match = _LOG_RE.match(line)
                    if not match:
                        continue
                    request_date = _parse_log_date(match.group("stamp"))
                    if request_date is None:
                        continue
                    parsed_lines += 1
                    retained_start = (
                        request_date
                        if retained_start is None
                        else min(retained_start, request_date)
                    )
                    retained_end = (
                        request_date if retained_end is None else max(retained_end, request_date)
                    )

                    method = match.group("method")
                    status = int(match.group("status"))
                    target = unquote(match.group("target").partition("?")[0])
                    target_lower = target.lower()

                    if target.startswith("/api/"):
                        api_requests += 1
                        if 500 <= status <= 599:
                            api_5xx += 1
                        if target_lower.startswith(("/api/mod-store", "/api/mods")):
                            mod_requests += 1

                    if method == "POST" and target == "/api/llm/chat/stream":
                        ai_total += 1
                        if status == 200:
                            ai_success += 1

                    if method != "GET" or status != 200:
                        continue
                    if not target_lower.startswith(_DOWNLOAD_PREFIXES):
                        continue
                    platform = next(
                        (
                            name
                            for suffix, name in _DOWNLOAD_PLATFORM_BY_SUFFIX.items()
                            if target_lower.endswith(suffix)
                        ),
                        None,
                    )
                    if platform is None:
                        continue
                    downloads_total += 1
                    download_platforms[platform] += 1
                    product = "kellai" if target_lower.startswith("/downloads/kellai/") else "xcagi"
                    download_products[product] += 1
                    download_daily[request_date] += 1
        except (OSError, EOFError):
            unreadable_files += 1

    if parsed_lines == 0:
        ai, downloads = _empty_traffic_metrics()
        return (
            ai,
            downloads,
            {
                "status": "unavailable",
                "files_scanned": len(paths),
                "files_unreadable": unreadable_files,
                "parsed_lines": 0,
                "source_updated_at": None,
                "api_requests": 0,
                "api_5xx": 0,
                "mod_requests": 0,
            },
        )

    ai_rate = round(ai_success / ai_total * 100, 2) if ai_total else 0.0
    ai = {
        "chat_requests": ai_total,
        "chat_success": ai_success,
        "success_rate": ai_rate,
        "window_start": _iso_date(retained_start),
        "window_end": _iso_date(retained_end),
        "window_start_short": _short_date(retained_start),
        "window_end_short": _short_date(retained_end),
    }

    daily: list[dict[str, Any]] = []
    if retained_end is not None:
        first_day = retained_end - timedelta(days=_trend_days() - 1)
        for offset in range(_trend_days()):
            day = first_day + timedelta(days=offset)
            daily.append(
                {
                    "date": _short_date(day),
                    "iso_date": day.isoformat(),
                    "count": download_daily[day],
                }
            )

    downloads = {
        "total": downloads_total,
        "platforms": {
            "windows": download_platforms["windows"],
            "macos": download_platforms["macos"],
            "android": download_platforms["android"],
        },
        "products": {
            "xcagi": download_products["xcagi"],
            "kellai": download_products["kellai"],
        },
        "daily": daily,
        "window_start": _iso_date(retained_start),
        "window_end": _iso_date(retained_end),
        "window_start_short": _short_date(retained_start),
        "window_end_short": _short_date(retained_end),
    }
    source_updated_at = (
        datetime.fromtimestamp(source_mtime, tz=_SHANGHAI).isoformat(timespec="seconds")
        if source_mtime
        else None
    )
    source_status = "live" if unreadable_files == 0 else "degraded"
    return (
        ai,
        downloads,
        {
            "status": source_status,
            "files_scanned": len(paths),
            "files_unreadable": unreadable_files,
            "parsed_lines": parsed_lines,
            "source_updated_at": source_updated_at,
            "api_requests": api_requests,
            "api_5xx": api_5xx,
            "mod_requests": mod_requests,
            "window_days": (
                (retained_end - retained_start).days + 1
                if retained_start and retained_end
                else None
            ),
        },
    )


def _prometheus_base_url() -> str:
    return (os.environ.get("XIUCI_VISUALIZATION_PROMETHEUS_URL") or "http://127.0.0.1:9090").rstrip(
        "/"
    )


def _prometheus_job() -> str:
    return (os.environ.get("XIUCI_VISUALIZATION_PROM_JOB") or "xcagi-backend").strip() or (
        "xcagi-backend"
    )


def _prom_instant(expr: str) -> float | None:
    url = f"{_prometheus_base_url()}/api/v1/query?query={quote(expr)}"
    request = Request(url, headers={"Accept": "application/json"})
    try:
        with urlopen(request, timeout=0.8) as response:  # noqa: S310 — ops localhost/env URL
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
    except (HTTPError, URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("status") != "success":
        return None
    result = (
        ((payload.get("data") or {}).get("result"))
        if isinstance(payload.get("data"), dict)
        else None
    )
    if not isinstance(result, list) or not result:
        return None
    try:
        value = float(result[0]["value"][1])
    except (KeyError, TypeError, ValueError, IndexError):
        return None
    return value if value == value else None  # NaN guard


_METRIC_LINE_RE = re.compile(
    r"^(?P<name>[a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{(?P<labels>[^}]*)\})?\s+(?P<value>[-+0-9.eE]+)\s*$"
)
_LABEL_RE = re.compile(r'([a-zA-Z_][a-zA-Z0-9_]*)="((?:\\.|[^"\\])*)"')


def _metrics_base_url() -> str:
    return (
        os.environ.get("XIUCI_VISUALIZATION_METRICS_URL") or "http://127.0.0.1:9999/metrics"
    ).strip()


def _parse_metric_labels(raw: str | None) -> dict[str, str]:
    if not raw:
        return {}
    return {m.group(1): m.group(2).replace('\\"', '"') for m in _LABEL_RE.finditer(raw)}


def _scrape_app_metrics() -> dict[str, Any]:
    """解析本机应用 /metrics（Prometheus 不可达时的回退源）。"""
    url = _metrics_base_url()
    if not url:
        return {}
    request = Request(url, headers={"Accept": "text/plain"})
    try:
        with urlopen(request, timeout=0.8) as response:  # noqa: S310 — ops localhost/env URL
            body = response.read().decode("utf-8", errors="replace")
    except (HTTPError, URLError, TimeoutError, OSError, ValueError):
        return {}

    counters: dict[str, float] = {}
    gauges: dict[str, float] = {}
    hist_buckets: dict[str, list[tuple[float, float]]] = {}
    ai_hist_buckets: list[tuple[float, float]] = []
    mod_hist_buckets: list[tuple[float, float]] = []
    labeled_counters: list[tuple[str, dict[str, str], float]] = []

    for line in body.splitlines():
        if not line or line.startswith("#"):
            continue
        match = _METRIC_LINE_RE.match(line)
        if not match:
            continue
        name = match.group("name")
        labels = _parse_metric_labels(match.group("labels"))
        try:
            value = float(match.group("value"))
        except ValueError:
            continue
        if name.endswith("_bucket") and "le" in labels:
            base = name[: -len("_bucket")]
            try:
                le = float("inf") if labels["le"] == "+Inf" else float(labels["le"])
            except ValueError:
                continue
            hist_buckets.setdefault(base, []).append((le, value))
            path = labels.get("path") or ""
            if "/api/llm/" in path or "/chat/stream" in path:
                ai_hist_buckets.append((le, value))
            if any(
                token in path for token in ("/api/mods", "/market/", "/v1/packages", "/mod-store")
            ):
                mod_hist_buckets.append((le, value))
        elif labels:
            labeled_counters.append((name, labels, value))
            counters[name] = counters.get(name, 0.0) + value
        else:
            gauges[name] = value
            counters[name] = counters.get(name, 0.0) + value

    def histogram_quantile(buckets: list[tuple[float, float]], q: float = 0.95) -> float | None:
        if not buckets:
            return None
        by_le: dict[float, float] = {}
        for le, count in buckets:
            by_le[le] = by_le.get(le, 0.0) + count
        ordered = sorted(by_le.items(), key=lambda item: item[0])
        total = ordered[-1][1] if ordered else 0.0
        if total <= 0:
            return 0.0
        target = total * q
        prev_le = 0.0
        prev_count = 0.0
        for le, count in ordered:
            if count >= target:
                if le == float("inf"):
                    return prev_le
                span = max(le - prev_le, 0.0)
                weight = (target - prev_count) / max(count - prev_count, 1e-9)
                return prev_le + span * weight
            prev_le, prev_count = le, count
        return prev_le

    total_req = sum(
        v for name, labels, v in labeled_counters if name == "modstore_http_requests_total"
    )
    err_req = sum(
        v
        for name, labels, v in labeled_counters
        if name == "modstore_http_requests_total" and labels.get("outcome") == "server_error"
    )
    # 兼容旧名 neurobus_events_* 与现行 modstore_domain_events_*
    bus_metric_names = (
        "modstore_domain_events_published_total",
        "neurobus_events_published_total",
    )
    bus_metric_present = any(name in body for name in bus_metric_names)
    published = None
    for name in bus_metric_names:
        if name in gauges:
            published = gauges[name]
            break
        if name in counters:
            published = counters[name]
            break
    if published is None and bus_metric_present:
        published = 0.0
    lost = gauges.get("neurobus_events_lost_total")
    if lost is None:
        lost = counters.get("neurobus_events_lost_total")
    if lost is None:
        lost = counters.get("modstore_domain_events_lost_total")
    dlq = gauges.get("neurobus_events_dead_lettered_total")
    if dlq is None:
        dlq = counters.get("neurobus_events_dead_lettered_total")
    if dlq is None:
        dlq = counters.get("modstore_domain_events_dead_lettered_total")
    if published is not None:
        lost = 0.0 if lost is None else float(lost)
        dlq = 0.0 if dlq is None else float(dlq)
    breaker_raw = gauges.get("circuit_breaker_state")
    if breaker_raw is None:
        breaker_raw = counters.get("circuit_breaker_state")
    # 0=closed 1=half_open 2=open → OPEN 路数；总线指标存在但无 gauge 时按 closed=0
    if breaker_raw is not None:
        breaker_open = 1.0 if float(breaker_raw) >= 2 else 0.0
    elif published is not None:
        breaker_open = 0.0
    else:
        breaker_open = None
    delivery = None
    if published is not None:
        denom = max(float(published), 1.0)
        delivery = max(0.0, 100.0 * (1.0 - (float(lost) + float(dlq)) / denom))

    p95 = histogram_quantile(hist_buckets.get("modstore_http_request_duration_seconds") or [])
    mod_p95 = histogram_quantile(mod_hist_buckets) or p95
    ai_p95 = histogram_quantile(ai_hist_buckets) or p95
    active = gauges.get("active_requests")
    if active is None and total_req >= 0 and body.strip():
        # 应用未导出 active_requests 时，能刮到 /metrics 即按 0 展示，避免整格空白
        active = 0.0
    return {
        "p95_ms": (p95 * 1000.0) if p95 is not None else None,
        "mod_p95_ms": (mod_p95 * 1000.0) if mod_p95 is not None else None,
        "active": active,
        "err_rate": (err_req / total_req * 100.0) if total_req > 0 else None,
        "sqlite_ready": 100.0,  # 能刮到应用 metrics 即视为目录服务进程就绪
        "neuro_delivery": delivery,
        "bus_publish": float(published) if published is not None else None,
        "bus_loss": float(lost) + float(dlq) if published is not None else None,
        "breaker_open": breaker_open,
        "ai_p95_ms": (ai_p95 * 1000.0) if ai_p95 is not None else None,
        "raw_request_total": total_req,
    }


def _bus_runtime_metrics() -> dict[str, float | None]:
    """进程内 NeuroBus 统计（单 worker；补 Prometheus 无样本时的缺口）。"""
    try:
        from modstore_server.eventing.global_bus import neuro_bus

        stats = neuro_bus.get_stats()
    except Exception:
        return {}
    if not isinstance(stats, dict):
        return {}
    published = float(stats.get("published") or 0)
    dropped = float(stats.get("dropped") or 0)
    errors = float(stats.get("errors") or 0)
    state = str(stats.get("circuit_breaker_state") or "closed").lower()
    breaker_open = 1.0 if state == "open" else 0.0
    loss = dropped + errors
    delivery = max(0.0, 100.0 * (1.0 - loss / max(published, 1.0)))
    return {
        "bus_publish": published,
        "bus_loss": loss,
        "breaker_open": breaker_open,
        "neuro_delivery": delivery,
    }


def _host_infra_metrics() -> dict[str, float | None]:
    """CVM 单机回退：负载 / 内存 / 根分区，不依赖 K8s。"""
    cpu_pct: float | None = None
    mem_gib: float | None = None
    disk_pct: float | None = None
    try:
        load1 = os.getloadavg()[0]
        nproc = max(os.cpu_count() or 1, 1)
        cpu_pct = min(100.0, max(0.0, load1 / nproc * 100.0))
    except (AttributeError, OSError):
        cpu_pct = None
    try:
        meminfo = Path("/proc/meminfo").read_text(encoding="utf-8")
        total_kb = avail_kb = None
        for line in meminfo.splitlines():
            if line.startswith("MemTotal:"):
                total_kb = float(line.split()[1])
            elif line.startswith("MemAvailable:"):
                avail_kb = float(line.split()[1])
        if total_kb and avail_kb is not None:
            mem_gib = max(0.0, (total_kb - avail_kb) * 1024.0 / 1024**3)
    except (OSError, ValueError, IndexError):
        mem_gib = None
    try:
        usage = os.statvfs("/")
        total = usage.f_blocks * usage.f_frsize
        free = usage.f_bavail * usage.f_frsize
        if total > 0:
            disk_pct = (1.0 - free / total) * 100.0
    except (AttributeError, OSError, ZeroDivisionError):
        disk_pct = None
    return {
        "cpu_pct": cpu_pct,
        "mem_gib": mem_gib,
        "disk_pct": disk_pct,
        "restarts": 0.0,
    }


def _panel(title: str, value: Any, unit: str = "", *, cls: str = "c") -> dict[str, Any]:
    return {"title": title, "value": value, "unit": unit, "cls": cls}


def _fmt_num(value: float | None, *, digits: int = 0) -> float | int | None:
    if value is None:
        return None
    if digits <= 0:
        return int(round(value))
    return round(value, digits)


def _coalesce(*values: float | None) -> float | None:
    for value in values:
        if value is not None:
            return value
    return None


def _build_monitor_payload(traffic_source: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """公开监控仪表盘：Prometheus → 本机 /metrics → 主机/网关日志。"""
    job = _prometheus_job()
    p95 = _prom_instant(
        f'histogram_quantile(0.95, sum by (le) (rate(api_request_duration_seconds_bucket{{job="{job}"}}[5m]))) * 1000'
    )
    rps = _prom_instant(f'sum(rate(api_requests_total{{job="{job}"}}[1m]))')
    err_rate = _prom_instant(
        f'sum(rate(api_requests_total{{job="{job}",status=~"5.."}}[5m])) '
        f'/ clamp_min(sum(rate(api_requests_total{{job="{job}"}}[5m])), 1) * 100'
    )
    active = _prom_instant("sum(active_requests)")
    pod_cpu = _prom_instant(
        'sum(rate(container_cpu_usage_seconds_total{pod=~"xcagi.*",container!=""}[5m])) * 100'
    )
    pod_mem = _prom_instant('sum(container_memory_usage_bytes{pod=~"xcagi.*",container!=""})')
    disk = _prom_instant(
        '100 * (1 - (node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint="/"}))'
    )
    restarts = _prom_instant(
        'sum(increase(kube_pod_container_status_restarts_total{pod=~"xcagi.*"}[1h]))'
    )
    mod_qps = _prom_instant(
        f'sum(rate(api_requests_total{{job="{job}",endpoint=~"/api/(mod-store|mods).*"}}[1m]))'
    )
    sqlite_ready = _prom_instant(
        f'sum(mod_sqlite_copy_present{{job="{job}"}}) / clamp_min(count(mod_sqlite_copy_present{{job="{job}"}}), 1) * 100'
    )
    neuro_delivery = _prom_instant(
        "100 * (1 - (sum(rate(neurobus_events_lost_total[5m])) + sum(rate(neurobus_events_dead_lettered_total[5m]))) "
        "/ clamp_min(sum(rate(neurobus_events_published_total[5m])), 1))"
    )
    mod_p95 = _prom_instant(
        f'histogram_quantile(0.95, sum by (le) (rate(api_request_duration_seconds_bucket{{job="{job}",'
        f'endpoint=~"/api/(mod-store|mods).*"}}[5m]))) * 1000'
    )
    bus_publish = _prom_instant("sum(rate(neurobus_events_published_total[1m]))")
    bus_loss = _prom_instant(
        "sum(increase(neurobus_events_lost_total[5m])) + sum(increase(neurobus_events_dead_lettered_total[5m]))"
    )
    breaker = _prom_instant("max(circuit_breaker_state) or on() vector(0)")
    ai_p95 = _prom_instant(
        f'histogram_quantile(0.95, sum by (le) (rate(ai_request_duration_seconds_bucket{{job="{job}"}}[5m]))) * 1000'
    )

    app_metrics = _scrape_app_metrics()
    bus_runtime = _bus_runtime_metrics()
    host = _host_infra_metrics()

    p95 = _coalesce(p95, app_metrics.get("p95_ms"))
    active = _coalesce(active, app_metrics.get("active"))
    err_rate = _coalesce(err_rate, app_metrics.get("err_rate"))
    mod_p95 = _coalesce(mod_p95, app_metrics.get("mod_p95_ms"))
    sqlite_ready = _coalesce(sqlite_ready, app_metrics.get("sqlite_ready"))
    neuro_delivery = _coalesce(
        neuro_delivery, app_metrics.get("neuro_delivery"), bus_runtime.get("neuro_delivery")
    )
    # 无 Prometheus rate 时：用累计事件量（条）代替「条/秒」，避免整块离线
    bus_publish_rate = bus_publish
    bus_publish_total = _coalesce(app_metrics.get("bus_publish"), bus_runtime.get("bus_publish"))
    bus_loss = _coalesce(bus_loss, app_metrics.get("bus_loss"), bus_runtime.get("bus_loss"))
    breaker = _coalesce(
        (1.0 if breaker is not None and breaker >= 2 else 0.0) if breaker is not None else None,
        app_metrics.get("breaker_open"),
        bus_runtime.get("breaker_open"),
    )
    ai_p95 = _coalesce(ai_p95, app_metrics.get("ai_p95_ms"))

    use_host_infra = not any(v is not None for v in (pod_cpu, pod_mem, disk, restarts))
    if use_host_infra:
        pod_cpu = host.get("cpu_pct")
        pod_mem_gib = host.get("mem_gib")
        disk = host.get("disk_pct")
        restarts = host.get("restarts")
    else:
        pod_mem_gib = (pod_mem / 1024 / 1024 / 1024) if pod_mem is not None else None

    prom_hits = sum(
        1
        for value in (
            p95,
            rps,
            err_rate,
            active,
            pod_cpu,
            pod_mem_gib,
            disk,
            restarts,
            mod_qps,
            sqlite_ready,
            neuro_delivery,
            mod_p95,
            bus_publish_rate,
            bus_loss,
            breaker,
            ai_p95,
        )
        if value is not None
    )
    metrics_live = bool(app_metrics)

    api_requests = int(traffic_source.get("api_requests") or 0)
    api_5xx = int(traffic_source.get("api_5xx") or 0)
    mod_requests = int(traffic_source.get("mod_requests") or 0)
    window_days = int(traffic_source.get("window_days") or 0) or None
    log_err_rate = round(api_5xx / api_requests * 100, 2) if api_requests else None
    log_rps = (
        round(api_requests / (window_days * 86400), 4) if api_requests and window_days else None
    )
    log_mod_qps = (
        round(mod_requests / (window_days * 86400), 4) if mod_requests and window_days else None
    )

    if rps is not None:
        api_mode = "live"
    elif p95 is not None or active is not None or err_rate is not None:
        api_mode = "metrics"
    elif api_requests:
        api_mode = "logs"
    else:
        api_mode = "offline"

    if use_host_infra and any(v is not None for v in (pod_cpu, pod_mem_gib, disk)):
        infra_mode = "host"
    elif not use_host_infra and any(v is not None for v in (pod_cpu, pod_mem_gib, disk, restarts)):
        infra_mode = "live"
    else:
        infra_mode = "offline"
    mod_mode = (
        "live"
        if mod_qps is not None
        else (
            "metrics"
            if any(v is not None for v in (sqlite_ready, neuro_delivery, mod_p95))
            else ("logs" if mod_requests else "offline")
        )
    )
    bus_mode = (
        "live"
        if bus_publish_rate is not None
        else (
            "metrics"
            if any(v is not None for v in (bus_publish_total, bus_loss, breaker, ai_p95))
            else "offline"
        )
    )

    bus_volume_value = _coalesce(bus_publish_rate, bus_publish_total)
    bus_volume_unit = "条/秒" if bus_publish_rate is not None else "条"
    bus_volume_title = "事件量 / 秒" if bus_publish_rate is not None else "事件累计"
    bus_loss_title = "丢失+DLQ 5m" if bus_publish_rate is not None else "丢失+DLQ 累计"

    monitor = {
        "title": "监控仪表盘 · Grafana / Prometheus / Loki",
        "subtitle": "4 块公开聚合面板 · Prometheus / 本机 metrics / 主机与网关日志回退",
        "stack": {
            "grafana_dashboards": 4,
            "prometheus": (
                "live"
                if (rps is not None or bus_publish_rate is not None)
                else ("metrics" if metrics_live else "unavailable")
            ),
            "loki": "provisioned",
            "alertmanager": "provisioned",
        },
        "live_note": (
            f"聚合命中 {prom_hits} 项"
            + (" · 含本机 /metrics" if metrics_live else "")
            + (" · 主机指标" if use_host_infra else "")
        ),
        "dashboards": [
            {
                "id": "api",
                "title": "XCAGI · API 总览",
                "desc": "xcagi-api-overview · RED 指标 · modstore_http_* / 网关日志",
                "status": api_mode,
                "panels": [
                    _panel("API 延迟 P95", _fmt_num(p95), "ms", cls="c"),
                    _panel(
                        "请求量 / 秒",
                        _fmt_num(rps, digits=2) if rps is not None else _fmt_num(log_rps, digits=4),
                        "次/秒",
                        cls="b",
                    ),
                    _panel(
                        "5xx 错误率",
                        (
                            _fmt_num(err_rate, digits=2)
                            if err_rate is not None
                            else _fmt_num(log_err_rate, digits=2)
                        ),
                        "%",
                        cls="g",
                    ),
                    _panel("活跃请求", _fmt_num(active), "个", cls="o"),
                ],
            },
            {
                "id": "infra",
                "title": "XCAGI · 基础设施",
                "desc": (
                    "xcagi-infrastructure · 本机 CPU/内存/磁盘"
                    if use_host_infra
                    else "xcagi-infrastructure · node / container 指标"
                ),
                "status": infra_mode,
                "panels": [
                    _panel(
                        "CPU 负载" if use_host_infra else "Pod CPU 使用率",
                        _fmt_num(pod_cpu, digits=1),
                        "%",
                        cls="c",
                    ),
                    _panel(
                        "内存已用" if use_host_infra else "Pod 内存",
                        _fmt_num(pod_mem_gib, digits=2),
                        "GiB",
                        cls="b",
                    ),
                    _panel("磁盘 /（根分区）", _fmt_num(disk), "%", cls="y"),
                    _panel(
                        "服务重启计数" if use_host_infra else "Pod 重启（1 小时）",
                        _fmt_num(restarts),
                        "次",
                        cls="g",
                    ),
                ],
            },
            {
                "id": "mod",
                "title": "XCAGI · Mod 商店",
                "desc": "xcagi-mod-store · Mod API 与目录流量",
                "status": mod_mode,
                "panels": [
                    _panel(
                        "目录 QPS",
                        (
                            _fmt_num(mod_qps, digits=2)
                            if mod_qps is not None
                            else _fmt_num(log_mod_qps, digits=4)
                        ),
                        "次/秒",
                        cls="c",
                    ),
                    _panel("SQLite 就绪率", _fmt_num(sqlite_ready), "%", cls="b"),
                    _panel("NeuroBus 投递率", _fmt_num(neuro_delivery, digits=2), "%", cls="g"),
                    _panel("Mod API P95", _fmt_num(mod_p95), "ms", cls="p"),
                ],
            },
            {
                "id": "bus",
                "title": "XCAGI · 神经总线",
                "desc": "xcagi-neurobus · modstore_domain_events_* · circuit_breaker_state",
                "status": bus_mode,
                "panels": [
                    _panel(
                        bus_volume_title,
                        _fmt_num(bus_volume_value, digits=2),
                        bus_volume_unit,
                        cls="c",
                    ),
                    _panel(bus_loss_title, _fmt_num(bus_loss), "条", cls="g"),
                    _panel("断路器 OPEN", _fmt_num(breaker), "路", cls="g"),
                    _panel("AI 请求 P95", _fmt_num(ai_p95), "ms", cls="p"),
                ],
            },
        ],
        "issues": [],
    }
    source = {
        "status": "live" if prom_hits or api_requests or metrics_live else "unavailable",
        "prometheus": monitor["stack"]["prometheus"],
        "app_metrics": "live" if metrics_live else "unavailable",
        "host_metrics": "live" if use_host_infra else "unused",
        "gateway_logs": traffic_source.get("status") or "unavailable",
        "source_updated_at": traffic_source.get("source_updated_at"),
        "prom_hits": prom_hits,
    }
    return monitor, source


def _read_product_metrics(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("release manifest root must be an object")
        history = raw.get("release_history")
        history = history if isinstance(history, list) else []
        current = history[0] if history and isinstance(history[0], dict) else {}
        platforms = current.get("platforms") if isinstance(current, dict) else []
        platforms = platforms if isinstance(platforms, list) else []
        release_ready = raw.get("release_ready")
        release_ready = release_ready if isinstance(release_ready, bool) else None
        product = {
            "stable_version": raw.get("version_lock") or raw.get("download_version"),
            "release_iterations": len(history),
            "delivery_platforms": len(platforms),
            "release_ready": release_ready,
            "release_status": (
                "READY" if release_ready is True else "PENDING" if release_ready is False else None
            ),
        }
        source_updated_at = datetime.fromtimestamp(path.stat().st_mtime, tz=_SHANGHAI).isoformat(
            timespec="seconds"
        )
        return product, {"status": "live", "source_updated_at": source_updated_at}
    except (OSError, ValueError, json.JSONDecodeError):
        return {
            "stable_version": None,
            "release_iterations": None,
            "delivery_platforms": None,
            "release_ready": None,
            "release_status": None,
        }, {"status": "unavailable", "source_updated_at": None}


def _token_engine():
    from modstore_server.env_loader import load_modstore_env
    from modstore_server.models import get_engine

    load_modstore_env(Path(__file__).resolve().parents[1])
    return get_engine()


def _as_shanghai_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    parsed = value
    if not isinstance(parsed, datetime):
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo("UTC"))
    return parsed.astimezone(_SHANGHAI)


def _platform_made_snapshot_candidates() -> list[Path]:
    configured = (os.environ.get("XIUCI_PLATFORM_MADE_TOKENS_PATH") or "").strip()
    if configured:
        return [Path(configured).expanduser()]
    site_root = Path(__file__).resolve().parents[2]
    return [
        site_root / "data" / "platform_made_tokens.json",
        Path("/root/成都修茈科技有限公司/data/platform_made_tokens.json"),
        Path("/opt/xcmax/current/成都修茈科技有限公司/data/platform_made_tokens.json"),
        Path("/opt/xcmax/releases/current/成都修茈科技有限公司/data/platform_made_tokens.json"),
    ]


def _platform_made_snapshot_path() -> Path:
    for path in _platform_made_snapshot_candidates():
        if path.is_file():
            return path
    return _platform_made_snapshot_candidates()[0]


def _empty_made_token_metrics() -> dict[str, Any]:
    return {
        "platform_made_tokens": None,
        "platform_made_prompt_tokens": None,
        "platform_made_completion_tokens": None,
        "platform_made_sources": [],
        "platform_made_collected_at": None,
        # 兼容旧字段名：制作 Token（管理端算法），不再表示线上使用量
        "platform_tokens": None,
    }


def _read_platform_made_metrics() -> tuple[dict[str, Any], dict[str, Any]]:
    """读取管理端同源的「平台制作 Token」公开快照。"""
    last_path = _platform_made_snapshot_path()
    for path in _platform_made_snapshot_candidates():
        last_path = path
        try:
            if not path.is_file():
                continue
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("platform made snapshot root must be an object")
            made = int(raw.get("platform_made_tokens") or 0)
            sources_raw = raw.get("sources")
            sources: list[dict[str, Any]] = []
            if isinstance(sources_raw, list):
                for item in sources_raw:
                    if not isinstance(item, dict):
                        continue
                    sources.append(
                        {
                            "key": str(item.get("key") or ""),
                            "label": str(item.get("label") or item.get("key") or ""),
                            "available": bool(item.get("available")),
                            "total_tokens": int(item.get("total_tokens") or 0),
                            "estimated": bool(item.get("estimated")),
                        }
                    )
            metrics = {
                "platform_made_tokens": made,
                "platform_made_prompt_tokens": int(raw.get("platform_made_prompt_tokens") or 0),
                "platform_made_completion_tokens": int(
                    raw.get("platform_made_completion_tokens") or 0
                ),
                "platform_made_sources": sources,
                "platform_made_collected_at": str(
                    raw.get("collected_at") or raw.get("generated_at") or ""
                )
                or None,
                "platform_tokens": made,
            }
            source_updated_at = (
                str(raw.get("generated_at") or raw.get("collected_at") or "") or None
            )
            return metrics, {
                "status": "live",
                "source_updated_at": source_updated_at,
                "snapshot_path": str(path),
            }
        except (OSError, ValueError, json.JSONDecodeError, TypeError):
            continue
    return _empty_made_token_metrics(), {
        "status": "unavailable",
        "source_updated_at": None,
        "snapshot_path": str(last_path),
    }


def _empty_token_metrics() -> dict[str, Any]:
    return {
        "platform_usage_tokens": None,
        "chat_tokens": None,
        "employee_tokens": None,
        "prompt_tokens": None,
        "completion_tokens": None,
        "estimated_chat_tokens": None,
        "top_chat_model": None,
        "top_chat_provider": None,
        "top_chat_model_tokens": None,
        "top_chat_model_calls": None,
        "top_chat_model_share": None,
        "chat_models": [],
        "token_records": None,
        "token_window_start": None,
        "token_window_end": None,
        "token_window_start_short": None,
        "token_window_end_short": None,
    }


def _read_token_metrics() -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        engine = _token_engine()
        with engine.connect() as connection:
            chat = connection.execute(text("""
                    SELECT COUNT(*) AS records,
                           COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
                           COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
                           COALESCE(SUM(total_tokens), 0) AS total_tokens,
                           COALESCE(SUM(CASE WHEN estimated THEN total_tokens ELSE 0 END), 0)
                               AS estimated_tokens,
                           MIN(created_at) AS first_at,
                           MAX(created_at) AS last_at
                    FROM llm_call_logs
                    WHERE status = 'success' AND total_tokens > 0
                    """)).mappings().one()
            employee = connection.execute(text("""
                    SELECT COUNT(*) AS records,
                           COALESCE(SUM(llm_tokens), 0) AS total_tokens,
                           MIN(created_at) AS first_at,
                           MAX(created_at) AS last_at
                    FROM employee_execution_metrics
                    WHERE llm_tokens > 0
                    """)).mappings().one()
            model_rows = connection.execute(text("""
                    SELECT model,
                           provider,
                           COUNT(*) AS calls,
                           COALESCE(SUM(total_tokens), 0) AS tokens
                    FROM llm_call_logs
                    WHERE status = 'success' AND total_tokens > 0
                    GROUP BY model, provider
                    ORDER BY tokens DESC
                    """)).mappings().all()
    except (SQLAlchemyError, OSError, ValueError):
        return _empty_token_metrics(), {"status": "unavailable", "source_updated_at": None}

    chat_tokens = int(chat["total_tokens"] or 0)
    employee_tokens = int(employee["total_tokens"] or 0)
    first_values = [
        parsed
        for parsed in (
            _as_shanghai_datetime(chat["first_at"]),
            _as_shanghai_datetime(employee["first_at"]),
        )
        if parsed is not None
    ]
    last_values = [
        parsed
        for parsed in (
            _as_shanghai_datetime(chat["last_at"]),
            _as_shanghai_datetime(employee["last_at"]),
        )
        if parsed is not None
    ]
    window_start = min(first_values) if first_values else None
    window_end = max(last_values) if last_values else None
    chat_models = [
        {
            "model": str(row["model"] or "unknown"),
            "provider": str(row["provider"] or "unknown"),
            "calls": int(row["calls"] or 0),
            "tokens": int(row["tokens"] or 0),
            "share": (
                round(int(row["tokens"] or 0) / chat_tokens * 100, 2) if chat_tokens else 0.0
            ),
        }
        for row in model_rows
    ]
    top_model = chat_models[0] if chat_models else None
    usage_tokens = chat_tokens + employee_tokens
    metrics = {
        "platform_usage_tokens": usage_tokens,
        "chat_tokens": chat_tokens,
        "employee_tokens": employee_tokens,
        "prompt_tokens": int(chat["prompt_tokens"] or 0),
        "completion_tokens": int(chat["completion_tokens"] or 0),
        "estimated_chat_tokens": int(chat["estimated_tokens"] or 0),
        "top_chat_model": top_model["model"] if top_model else None,
        "top_chat_provider": top_model["provider"] if top_model else None,
        "top_chat_model_tokens": top_model["tokens"] if top_model else None,
        "top_chat_model_calls": top_model["calls"] if top_model else None,
        "top_chat_model_share": top_model["share"] if top_model else None,
        "chat_models": chat_models,
        "token_records": int(chat["records"] or 0) + int(employee["records"] or 0),
        "token_window_start": window_start.date().isoformat() if window_start else None,
        "token_window_end": window_end.date().isoformat() if window_end else None,
        "token_window_start_short": _short_date(window_start.date()) if window_start else None,
        "token_window_end_short": _short_date(window_end.date()) if window_end else None,
    }
    return metrics, {
        "status": "live",
        "source_updated_at": window_end.isoformat(timespec="seconds") if window_end else None,
        "chat_records": int(chat["records"] or 0),
        "employee_records": int(employee["records"] or 0),
        "model_coverage": "chat_ledger_only",
    }


def _build_public_visualization_data() -> dict[str, Any]:
    log_paths = _access_log_paths()
    ai, downloads, traffic_source = _read_traffic_metrics(log_paths)
    token_metrics, token_source = _read_token_metrics()
    made_metrics, made_source = _read_platform_made_metrics()
    ai.update(token_metrics)
    ai.update(made_metrics)
    product, release_source = _read_product_metrics(_release_manifest_path())
    monitor, monitor_source = _build_monitor_payload(traffic_source)
    # 制作快照 / 监控 Prom 可选；缺失时不把整页打成 offline
    source_statuses = (traffic_source["status"], token_source["status"], release_source["status"])
    data_status = "live" if all(status == "live" for status in source_statuses) else "degraded"
    generated_at = datetime.now(tz=_SHANGHAI).isoformat(timespec="seconds")
    source_updates = [
        value
        for value in (
            traffic_source.get("source_updated_at"),
            token_source.get("source_updated_at"),
            made_source.get("source_updated_at"),
            monitor_source.get("source_updated_at"),
            release_source.get("source_updated_at"),
        )
        if value
    ]
    return {
        "schema": "xiu-ci.public-visualization/v1",
        "data_status": data_status,
        "generated_at": generated_at,
        "source_updated_at": max(source_updates) if source_updates else None,
        "cache_ttl_seconds": _cache_ttl_seconds(),
        "ai": ai,
        "downloads": downloads,
        "product": product,
        "monitor": monitor,
        "sources": {
            "gateway_logs": traffic_source,
            "token_ledger": token_source,
            "platform_made_tokens": made_source,
            "monitor": monitor_source,
            "release_manifest": release_source,
        },
        "definitions": {
            "ai_requests": "生产网关滚动日志内 POST /api/llm/chat/stream 的请求数",
            "ai_success": "上述请求中 HTTP 200 的响应数",
            "platform_made_tokens": (
                "管理端同源算法：FHD 本地账本 + Cursor + Codex + Trae + mimo 五源合计"
            ),
            "platform_usage_tokens": (
                "线上平台使用量：对话计费日志 total_tokens 与 AI 员工执行度量 llm_tokens 之和，"
                "不重复汇总 Duty 节点副本"
            ),
            "platform_tokens": "同 platform_made_tokens（兼容旧字段）",
            "model_usage": "模型分布仅按可精确归属的对话计费日志统计；历史 AI 员工度量未存模型名，不做推断",
            "complete_downloads": "安装包 GET 请求完整返回 HTTP 200 的响应数；排除 HEAD、分片与更新 ZIP",
            "monitor": "监控仪表盘公开聚合：优先本机 Prometheus，回退网关访问日志；不含 Grafana 截图与告警明细",
        },
        "privacy": "仅提供聚合指标，不包含 IP、账户、对话内容、单用户 Token 账单或请求明细",
    }


def clear_public_visualization_cache() -> None:
    """Clear the per-process cache; exposed for tests and controlled reloads."""

    global _CACHE_VALUE, _CACHE_CREATED_MONOTONIC
    with _CACHE_LOCK:
        _CACHE_VALUE = None
        _CACHE_CREATED_MONOTONIC = 0.0


def get_public_visualization_data() -> dict[str, Any]:
    global _CACHE_VALUE, _CACHE_CREATED_MONOTONIC
    now = time.monotonic()
    ttl = _cache_ttl_seconds()
    with _CACHE_LOCK:
        if _CACHE_VALUE is not None and now - _CACHE_CREATED_MONOTONIC < ttl:
            return copy.deepcopy(_CACHE_VALUE)
        value = _build_public_visualization_data()
        _CACHE_VALUE = value
        _CACHE_CREATED_MONOTONIC = time.monotonic()
        return copy.deepcopy(value)


@router.get(
    "/api/public/visualization",
    summary="官网 AI 业务、软件下载与版本交付实时聚合",
)
def public_visualization(response: Response) -> dict[str, Any]:
    response.headers["Cache-Control"] = "public, max-age=15, stale-if-error=60"
    payload = get_public_visualization_data()
    response.headers["X-Data-Generated-At"] = payload["generated_at"]
    return payload
