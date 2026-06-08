"""Prometheus metrics for the FastAPI service."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

REQUEST_COUNT = Counter(
    "modstore_http_requests_total",
    "Total HTTP requests handled by MODstore FastAPI.",
    ("method", "path", "status", "outcome"),
)

REQUEST_LATENCY = Histogram(
    "modstore_http_request_duration_seconds",
    "HTTP request latency for MODstore FastAPI.",
    ("method", "path"),
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)

PROXY_COUNT = Counter(
    "modstore_payment_proxy_requests_total",
    "Total FastAPI gateway requests proxied to the Java payment service.",
    ("method", "path", "status", "outcome"),
)

PROXY_LATENCY = Histogram(
    "modstore_payment_proxy_duration_seconds",
    "FastAPI gateway latency when proxying payment requests to Java.",
    ("method", "path"),
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30),
)

CSP_REPORT_ONLY_VIOLATIONS = Counter(
    "modstore_csp_report_only_violations_total",
    "Violations reported by browsers under Content-Security-Policy-Report-Only.",
)

REALTIME_WS_EVENTS = Counter(
    "modstore_realtime_ws_events_total",
    "WebSocket realtime channel (/api/realtime/ws) events for debugging proxy and client behavior.",
    ("event",),
)


def observe_csp_violation() -> None:
    CSP_REPORT_ONLY_VIOLATIONS.inc()


def observe_realtime_ws_event(event: str) -> None:
    """event: accepted | auth_fail | ready | ready_send_fail | unregister | ping | idle_timeout."""
    REALTIME_WS_EVENTS.labels(event).inc()


def _route_path(request: Request) -> str:
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    return str(path or request.url.path)


def _status_outcome(status_code: int) -> str:
    if status_code >= 500:
        return "server_error"
    if status_code >= 400:
        return "client_error"
    if status_code >= 300:
        return "redirect"
    return "success"


def observe_payment_proxy(method: str, path: str, status_code: int, elapsed_seconds: float) -> None:
    outcome = _status_outcome(status_code)
    status = str(status_code)
    PROXY_COUNT.labels(method, path, status, outcome).inc()
    PROXY_LATENCY.labels(method, path).observe(elapsed_seconds)


def install_metrics(app: FastAPI) -> None:
    @app.middleware("http")
    async def prometheus_metrics_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if request.url.path == "/metrics":
            return await call_next(request)
        started = time.perf_counter()
        response = await call_next(request)
        elapsed = time.perf_counter() - started
        path = _route_path(request)
        REQUEST_COUNT.labels(
            request.method,
            path,
            str(response.status_code),
            _status_outcome(response.status_code),
        ).inc()
        REQUEST_LATENCY.labels(request.method, path).observe(elapsed)
        return response

    @app.get("/metrics", include_in_schema=False)
    def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
