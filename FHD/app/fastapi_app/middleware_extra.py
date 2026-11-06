"""请求上下文、访问日志、Neuro HTTP trace、Prometheus /metrics、HTTP SLI。"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from typing import Any

from fastapi import FastAPI, Request

from app.request_active_mod_ctx import (
    parse_active_mod_header,
    reset_request_active_mod_id,
    set_request_active_mod_id,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

_AI_STREAM_MARKERS = ("/ai/", "/agent/", "/chat", "/employee", "/tutorial")


def _is_ai_event_stream(path: str, content_type: str) -> bool:
    normalized = path.lower()
    return content_type.lower().startswith("text/event-stream") and any(
        marker in normalized for marker in _AI_STREAM_MARKERS
    )


def _instrument_first_byte(response: Any, *, path: str, started: float) -> None:
    content_type = str(response.headers.get("content-type") or "")
    iterator = getattr(response, "body_iterator", None)
    if not _is_ai_event_stream(path, content_type) or iterator is None:
        return

    async def measured_iterator() -> AsyncIterator[Any]:
        recorded = False
        async for chunk in iterator:
            if not recorded and chunk:
                try:
                    from app.utils.metrics import record_chat_stream_first_byte

                    record_chat_stream_first_byte(time.perf_counter() - started)
                except RECOVERABLE_ERRORS:
                    pass
                recorded = True
            yield chunk

    response.body_iterator = measured_iterator()


def register_http_sli_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def prometheus_http_sli(request: Request, call_next):
        path = request.url.path or ""
        if path == "/metrics":
            return await call_next(request)
        started = time.perf_counter()
        response = await call_next(request)
        try:
            from app.utils.metrics import record_business_http_request, record_http_request

            duration = time.perf_counter() - started
            record_http_request(request.method, path, response.status_code, duration)
            record_business_http_request(request.method, path, response.status_code, duration)
            _instrument_first_byte(response, path=path, started=started)
        except RECOVERABLE_ERRORS:
            pass
        return response


def register_extra_middleware(app: FastAPI) -> None:
    """注册应用级 HTTP 中间件（内层：上下文与访问日志）。"""
    register_http_sli_middleware(app)

    @app.middleware("http")
    async def http_request_context(request: Request, call_next):
        from app.http.request_context import reset_current_http_request, set_current_http_request

        token = set_current_http_request(request)
        try:
            return await call_next(request)
        finally:
            reset_current_http_request(token)

    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        import hashlib
        import os

        from app.application.network_stability import format_http_trace_line, lane_for_path
        from app.middleware.request_id import ensure_request_id

        verbose = (os.environ.get("XCAGI_REQUEST_LOG") or "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        path = request.url.path or ""
        request_id = ensure_request_id(request)
        started = time.perf_counter()
        active_mod = parse_active_mod_header(request.headers)
        am_token = set_request_active_mod_id(active_mod)
        try:
            response = await call_next(request)
            if "x-request-id" not in {key.lower() for key in response.headers.keys()}:
                response.headers["X-Request-ID"] = request_id
            duration_ms = (time.perf_counter() - started) * 1000
            noisy = path.startswith("/assets/") or path in {"/api/health", "/health", "/metrics"}
            cookie = request.headers.get("cookie") or ""
            session_ref = hashlib.sha256(cookie.encode()).hexdigest()[:8] if cookie else ""
            tenant = request.headers.get("x-xcagi-tenant") or ""
            if not tenant.replace("-", "").isalnum():
                tenant = ""
            if not noisy and (verbose or response.status_code >= 400 or logger.isEnabledFor(logging.DEBUG)):
                line = format_http_trace_line(
                    request_id=request_id,
                    method=request.method,
                    path=path,
                    status=response.status_code,
                    duration_ms=duration_ms,
                    error_code=response.headers.get("x-error-code") or "",
                    tenant=tenant[:64],
                    task=(request.headers.get("x-xcagi-task-id") or "")[:64],
                    session_ref=session_ref,
                )
                logger.log(logging.INFO if verbose or response.status_code >= 400 else logging.DEBUG, line)
            lane = response.headers.get("x-stability-lane") or lane_for_path(path)
            if lane and not noisy:
                logging.getLogger("app.stability").info(
                    format_http_trace_line(
                        request_id=request_id,
                        method=request.method,
                        path=path,
                        status=response.status_code,
                        duration_ms=duration_ms,
                        error_code=response.headers.get("x-error-code") or "",
                        tenant=tenant[:64],
                        task=(request.headers.get("x-xcagi-task-id") or "")[:64],
                        session_ref=session_ref,
                        lane=lane,
                    )
                )
            return response
        finally:
            reset_request_active_mod_id(am_token)

    @app.middleware("http")
    async def neuro_http_trace_outer(request: Request, call_next):
        from app.middleware.neuro_http_trace import neuro_http_trace_middleware

        return await neuro_http_trace_middleware(request, call_next)


def register_prometheus_metrics(app: FastAPI) -> None:
    """注册 Prometheus 监控端点"""
    try:
        from fastapi.responses import Response
        from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

        @app.get("/metrics")
        async def metrics_endpoint():
            return Response(
                content=generate_latest(),
                media_type=CONTENT_TYPE_LATEST,
            )

        logger.info("✅ Prometheus 监控端点已注册 (/metrics)")
    except ImportError:
        logger.warning("⚠️ prometheus_client 未安装，监控端点不可用")
    except RECOVERABLE_ERRORS as e:
        logger.warning("⚠️ Prometheus 监控端点注册失败：%s", e)
