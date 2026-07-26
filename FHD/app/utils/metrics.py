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

# --- 业务 SLI 指标（SLO-BIZ-01..05）----------------------------------------------
# 对应 docs/SLO.md "业务 SLO (BIZ 五域)"；标签基数 < 20（铁律 8）。
# 设计：与 SLO-API/AI/BUS 技术域并列，补齐客户/文档/导出/MOD 业务可观测性。
customer_op_total = Counter(
    "customer_op_total",
    "Total customer CRUD operations (create/update/delete/query)",
    ["operation", "status"],
)

customer_op_duration_seconds = Histogram(
    "customer_op_duration_seconds",
    "Customer CRUD operation duration in seconds",
    ["operation"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

doc_recognition_total = Counter(
    "doc_recognition_total",
    "Total document recognition operations (OCR/Excel/Word parsing)",
    ["doc_type", "status"],
)

doc_recognition_duration_seconds = Histogram(
    "doc_recognition_duration_seconds",
    "Document recognition duration in seconds (parse → structured data)",
    ["doc_type"],
    buckets=(0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0),
)

export_task_total = Counter(
    "export_task_total",
    "Total export tasks (Excel/CSV/PDF generation)",
    ["export_type", "status"],
)

export_task_duration_seconds = Histogram(
    "export_task_duration_seconds",
    "Export task duration in seconds (queue → file ready)",
    ["export_type"],
    buckets=(0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0),
)

mod_install_total = Counter(
    "mod_install_total",
    "Total mod install/uninstall operations",
    ["operation", "status"],
)

# --- 通用 ETL（不得使用文件名、字段值、租户或业务原文作为 label）-------------
etl_runs_total = Counter(
    "etl_runs_total",
    "General ETL runs by phase and stable outcome",
    ["phase", "target_type", "status"],
)
etl_run_duration_seconds = Histogram(
    "etl_run_duration_seconds",
    "General ETL phase duration",
    ["phase", "target_type"],
    buckets=(0.1, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300, 900),
)
etl_rows_total = Counter(
    "etl_rows_total",
    "General ETL rows by deterministic decision",
    ["target_type", "decision"],
)
etl_manual_corrections_total = Counter(
    "etl_manual_corrections_total",
    "General ETL mapping or row action corrections",
    ["kind"],
)
etl_retries_total = Counter("etl_retries_total", "General ETL retry operations", ["target_type"])
etl_rollbacks_total = Counter(
    "etl_rollbacks_total", "General ETL rollback operations", ["target_type", "status"]
)
etl_llm_degradations_total = Counter(
    "etl_llm_degradations_total",
    "General ETL previews completed without LLM advisory",
    ["target_type"],
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


# --- 业务 SLI record_* 辅助函数（SLO-BIZ-01..05）-------------------------------
# 业务路由按需调用；fail-open（RECOVERABLE_ERRORS 不抛错，铁律 9 CI 容错）。
# status 取值约束：success / error（与 api_requests_total 风格一致）。


def record_customer_op(operation: str, status: str, duration_seconds: float) -> None:
    """客户 CRUD 操作埋点（SLO-BIZ-01/02）。

    operation: create / update / delete / query
    status: success / error
    """
    try:
        customer_op_total.labels(operation=operation, status=status).inc()
        customer_op_duration_seconds.labels(operation=operation).observe(duration_seconds)
    except RECOVERABLE_ERRORS:
        pass


def record_doc_recognition(doc_type: str, status: str, duration_seconds: float) -> None:
    """文档识别埋点（SLO-BIZ-03）。

    doc_type: excel / word / ocr / pdf
    status: success / error
    """
    try:
        doc_recognition_total.labels(doc_type=doc_type, status=status).inc()
        doc_recognition_duration_seconds.labels(doc_type=doc_type).observe(duration_seconds)
    except RECOVERABLE_ERRORS:
        pass


def record_export_task(export_type: str, status: str, duration_seconds: float) -> None:
    """数据导出任务埋点（SLO-BIZ-04）。

    export_type: excel / csv / pdf
    status: success / error
    """
    try:
        export_task_total.labels(export_type=export_type, status=status).inc()
        export_task_duration_seconds.labels(export_type=export_type).observe(duration_seconds)
    except RECOVERABLE_ERRORS:
        pass


def record_mod_install(operation: str, status: str) -> None:
    """MOD 安装/卸载埋点（SLO-BIZ-05）。

    operation: install / uninstall / activate / deactivate
    status: success / error
    """
    try:
        mod_install_total.labels(operation=operation, status=status).inc()
    except RECOVERABLE_ERRORS:
        pass


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
