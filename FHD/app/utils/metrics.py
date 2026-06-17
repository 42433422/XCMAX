"""
Prometheus 指标模块

提供应用指标采集和暴露功能。
"""

import time
from collections.abc import Callable
from functools import wraps
from typing import Any

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, Info, generate_latest
from starlette.responses import Response

from app.utils.operational_errors import RECOVERABLE_ERRORS

materials_created_total = Counter(
    "materials_created_total", "Total number of materials created", ["category"]
)

materials_operations_duration_seconds = Histogram(
    "materials_operations_duration_seconds",
    "Duration of materials operations in seconds",
    ["operation"],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

api_requests_total = Counter(
    "api_requests_total", "Total number of API requests", ["method", "endpoint", "status"]
)

api_request_duration_seconds = Histogram(
    "api_request_duration_seconds",
    "API request duration in seconds",
    ["method", "endpoint"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

auth_login_duration_seconds = Histogram(
    "auth_login_duration_seconds",
    "Auth login/handshake duration in seconds",
    ["auth_method"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

chat_stream_first_byte_seconds = Histogram(
    "chat_stream_first_byte_seconds",
    "Time to first byte for chat streaming responses",
    ["model", "tenant_id"],
    buckets=(0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0),
)

ai_requests_total = Counter(
    "ai_requests_total", "Total number of AI service requests", ["service", "status"]
)

ai_request_duration_seconds = Histogram(
    "ai_request_duration_seconds",
    "AI request duration in seconds",
    ["service"],
    buckets=(0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0),
)

ai_request_errors_total = Counter(
    "ai_request_errors_total", "Total number of AI request errors", ["service", "error_type"]
)

active_requests = Gauge("active_requests", "Number of active requests")

circuit_breaker_state = Gauge(
    "circuit_breaker_state", "Circuit breaker state (0=closed, 1=half_open, 2=open)", ["name"]
)

circuit_breaker_failures_total = Counter(
    "circuit_breaker_failures_total",
    "Total number of circuit breaker failures",
    ["name", "circuit_state"],
)

# --- 语义缓存指标（app/infrastructure/cache/intent_cache.py）---------------
intent_cache_hits_total = Counter(
    "intent_cache_hits_total",
    "Number of intent/semantic cache hits (API call avoided)",
    ["scope", "mod_id"],
)

intent_cache_misses_total = Counter(
    "intent_cache_misses_total",
    "Number of intent/semantic cache misses (fell through to compute_fn)",
    ["scope", "mod_id"],
)

intent_cache_errors_total = Counter(
    "intent_cache_errors_total",
    "Number of errors raised inside intent cache layer (never surfaced to caller)",
    ["scope", "stage"],
)

intent_cache_compute_seconds = Histogram(
    "intent_cache_compute_seconds",
    "Wall-clock seconds spent in compute_fn on cache miss (i.e. saved per future hit)",
    ["scope"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
)

app_info = Info("app", "Application information")

# --- NeuroBus 事件计数（M0 Grafana / observability）---------------------------------
neurobus_events_published_total = Counter(
    "neurobus_events_published_total",
    "Total NeuroBus events published",
)
neurobus_events_lost_total = Counter(
    "neurobus_events_lost_total",
    "Total NeuroBus events lost (queue full / dropped)",
)
neurobus_events_dead_lettered_total = Counter(
    "neurobus_events_dead_lettered_total",
    "Total NeuroBus events moved to DLQ",
)

mod_sqlite_copy_present = Gauge(
    "mod_sqlite_copy_present",
    "Whether per-mod SQLite copy exists on disk (1=present)",
    ["mod_id"],
)


def _normalize_endpoint(path: str) -> str:
    if not path or path == "/":
        return "/"
    parts = path.strip("/").split("/")
    normalized: list[str] = []
    for part in parts:
        if part.isdigit() or (len(part) > 8 and part.replace("-", "").isalnum()):
            normalized.append("{id}")
        else:
            normalized.append(part)
    return "/" + "/".join(normalized)


def record_http_request(method: str, path: str, status_code: int, duration_seconds: float) -> None:
    endpoint = _normalize_endpoint(path)
    try:
        api_requests_total.labels(method=method, endpoint=endpoint, status=str(status_code)).inc()
        api_request_duration_seconds.labels(method=method, endpoint=endpoint).observe(
            duration_seconds
        )
    except RECOVERABLE_ERRORS:
        pass


def record_api_request(method: str, endpoint: str, status: int | str) -> None:
    """Increment api_requests_total（M0 / 本地 seed 用；endpoint 不做归一化）。"""
    try:
        api_requests_total.labels(method=method, endpoint=endpoint, status=str(status)).inc()
    except RECOVERABLE_ERRORS:
        pass


def record_ai_call(provider_id: str, operation: str, status: str, duration_seconds: float) -> None:
    """LLM Provider 统一埋点（见 infrastructure/llm/providers/*）。"""
    try:
        ai_requests_total.labels(service=provider_id, status=status).inc()
        ai_request_duration_seconds.labels(service=provider_id).observe(duration_seconds)
        if status == "error":
            ai_request_errors_total.labels(service=provider_id, error_type=operation).inc()
    except RECOVERABLE_ERRORS:
        pass


def record_neurobus_published(count: int = 1) -> None:
    if count > 0:
        neurobus_events_published_total.inc(count)


def record_neurobus_lost(count: int = 1) -> None:
    if count > 0:
        neurobus_events_lost_total.inc(count)


def record_neurobus_dead_lettered(count: int = 1) -> None:
    if count > 0:
        neurobus_events_dead_lettered_total.inc(count)


def refresh_mod_sqlite_copy_metrics(mod_ids: list[str]) -> int:
    """扫描 per-mod SQLite 副本是否落盘，更新 mod_sqlite_copy_present gauge。"""
    import os

    from app.db.init_db import DEFAULT_DB_FILES
    from app.db.sqlite_mod_paths import sqlite_filename_with_mod_suffix
    from app.utils.path_utils import get_app_data_dir

    ready = 0
    work_dir = get_app_data_dir()
    db_name = DEFAULT_DB_FILES[0]
    for mod_id in mod_ids:
        dest = sqlite_filename_with_mod_suffix(db_name, mod_id)
        present = os.path.isfile(os.path.join(work_dir, dest))
        mod_sqlite_copy_present.labels(mod_id=mod_id).set(1.0 if present else 0.0)
        if present:
            ready += 1
    return ready


def seed_local_observability_metrics(*, neuro_probe_events: int = 0) -> dict[str, int]:
    """本地/dev 仪表盘 seed：批量写入 api_requests_total 样本计数。"""
    _ = neuro_probe_events
    for status in ("200", "500"):
        for _ in range(5000):
            record_api_request("GET", "/api/health", status)
    return {"api_requests_seeded": 10000}


def init_metrics(app_name: str, version: str):
    """初始化应用指标"""
    app_info.info({"name": app_name, "version": version})


def metrics_endpoint() -> Response:
    """Prometheus metrics 端点处理函数"""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


def track_request_duration(method: str, endpoint: str):
    """请求持续时间追踪装饰器"""

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            active_requests.inc()
            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                duration = time.time() - start_time
                api_request_duration_seconds.labels(method=method, endpoint=endpoint).observe(
                    duration
                )
                return result
            finally:
                active_requests.dec()

        return wrapper

    return decorator


def track_ai_request(service: str):
    """AI 请求追踪装饰器"""

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                duration = time.time() - start_time
                ai_requests_total.labels(service=service, status="success").inc()
                ai_request_duration_seconds.labels(service=service).observe(duration)
                return result
            except RECOVERABLE_ERRORS as e:
                ai_requests_total.labels(service=service, status="error").inc()
                ai_request_errors_total.labels(service=service, error_type=type(e).__name__).inc()
                raise

        return wrapper

    return decorator
