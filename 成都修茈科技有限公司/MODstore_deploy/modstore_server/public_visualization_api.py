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
from urllib.parse import unquote
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
    return Path(__file__).resolve().parents[2] / "download-release.json"


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

                    if method == "POST" and target == "/api/llm/chat/stream":
                        ai_total += 1
                        if status == 200:
                            ai_success += 1

                    target_lower = target.lower()
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
        },
    )


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


def _empty_token_metrics() -> dict[str, Any]:
    return {
        "platform_tokens": None,
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
    metrics = {
        "platform_tokens": chat_tokens + employee_tokens,
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
    ai.update(token_metrics)
    product, release_source = _read_product_metrics(_release_manifest_path())
    source_statuses = (traffic_source["status"], token_source["status"], release_source["status"])
    data_status = "live" if all(status == "live" for status in source_statuses) else "degraded"
    generated_at = datetime.now(tz=_SHANGHAI).isoformat(timespec="seconds")
    source_updates = [
        value
        for value in (
            traffic_source.get("source_updated_at"),
            token_source.get("source_updated_at"),
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
        "sources": {
            "gateway_logs": traffic_source,
            "token_ledger": token_source,
            "release_manifest": release_source,
        },
        "definitions": {
            "ai_requests": "生产网关滚动日志内 POST /api/llm/chat/stream 的请求数",
            "ai_success": "上述请求中 HTTP 200 的响应数",
            "platform_tokens": "对话计费日志 total_tokens 与 AI 员工执行度量 llm_tokens 之和，不重复汇总 Duty 节点副本",
            "model_usage": "模型分布仅按可精确归属的对话计费日志统计；历史 AI 员工度量未存模型名，不做推断",
            "complete_downloads": "安装包 GET 请求完整返回 HTTP 200 的响应数；排除 HEAD、分片与更新 ZIP",
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
