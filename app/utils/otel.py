"""
OpenTelemetry 与 Prometheus 延迟直方图（可选，通过环境变量启用）。

环境变量：
- OTEL_EXPORTER_OTLP_ENDPOINT — Jaeger/Tempo OTLP HTTP（如 http://localhost:4318/v1/traces）
- OTEL_SERVICE_NAME — 默认 xcagi
- XCAGI_OTEL_ENABLED — 1/true 显式开启（production 且设置了 endpoint 时自动开启）
"""

from __future__ import annotations

import contextlib
import logging
import os
from collections.abc import Iterator
from typing import Any

from prometheus_client import Histogram

logger = logging.getLogger(__name__)

HTTP_REQUEST_DURATION = Histogram(
    "xcagi_http_request_duration_seconds",
    "HTTP request latency",
    ["method", "route", "status"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

_tracer_provider: Any = None


def otel_enabled() -> bool:
    raw = os.environ.get("XCAGI_OTEL_ENABLED", "").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    if not endpoint:
        return False
    env = os.environ.get("FHD_ENV", "").strip().lower()
    return env in {"production", "prod", "staging"}


def setup_opentelemetry(app: Any | None = None) -> bool:
    """初始化 OTLP exporter + FastAPI 自动埋点。成功返回 True。"""
    global _tracer_provider
    if not otel_enabled():
        return False
    if _tracer_provider is not None:
        return True

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        logger.warning("OpenTelemetry packages not installed; pip install -r requirements-observability.txt")
        return False

    service = os.environ.get("OTEL_SERVICE_NAME", "xcagi")
    resource = Resource.create(
        {
            "service.name": service,
            "deployment.environment": os.environ.get("FHD_ENV", "development"),
        }
    )
    provider = TracerProvider(resource=resource)
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "http://127.0.0.1:4318/v1/traces")
    exporter = OTLPSpanExporter(endpoint=endpoint)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    _tracer_provider = provider

    if app is not None:
        try:
            from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

            FastAPIInstrumentor.instrument_app(app)
        except Exception as exc:
            logger.warning("FastAPI OTel instrumentation skipped: %s", exc)

    logger.info("OpenTelemetry enabled (service=%s endpoint=%s)", service, endpoint)
    return True


def get_tracer(name: str = "xcagi.business") -> Any:
    """返回 OTel tracer；未启用/未安装时返回 None（调用方需判空）。"""
    if _tracer_provider is None:
        return None
    try:
        from opentelemetry import trace

        return trace.get_tracer(name)
    except Exception:
        return None


@contextlib.contextmanager
def business_span(name: str, **attributes: Any) -> Iterator[Any]:
    """业务链路 span 上下文管理器（订单 / AI 调用 / 打印）。

    OTel 未启用时退化为 no-op，不影响业务逻辑。异常会标记 span 状态为 error。

    用法::

        with business_span("order.pay", order_id=oid, tenant_id=tid):
            do_payment()
    """
    tracer = get_tracer()
    if tracer is None:
        yield None
        return
    try:
        from opentelemetry.trace import Status, StatusCode

        with tracer.start_as_current_span(name) as span:
            for key, value in attributes.items():
                if value is not None:
                    try:
                        span.set_attribute(key, value)
                    except Exception:
                        pass
            try:
                yield span
            except Exception as exc:
                try:
                    span.set_status(Status(StatusCode.ERROR, str(exc)))
                    span.record_exception(exc)
                except Exception:
                    pass
                raise
    except ImportError:
        yield None


def shutdown_opentelemetry() -> None:
    global _tracer_provider
    if _tracer_provider is None:
        return
    try:
        _tracer_provider.shutdown()
    except Exception as exc:
        logger.debug("OTel shutdown: %s", exc)
    _tracer_provider = None
