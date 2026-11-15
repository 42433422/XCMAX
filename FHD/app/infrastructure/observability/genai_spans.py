"""OpenTelemetry GenAI 语义约定：工具执行 span 埋点。

只提供最小埋点能力：SDK 未初始化时 ``get_tracer`` 返回 NoOpTracer，
埋点自身失败一律降级为 no-op，不影响工具调用与业务异常语义。
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from opentelemetry.trace import Span
from opentelemetry.trace import get_tracer as _otel_get_tracer

from app.utils.operational_errors import BOUNDARY_ERRORS, RECOVERABLE_ERRORS


def get_tracer() -> Any:
    """返回本模块 tracer；未配置 TracerProvider 时即 NoOpTracer。"""
    return _otel_get_tracer(__name__)


def _set_attribute(span: Span, key: str, value: Any) -> None:
    """写入属性，失败时仅降级为 no-op。"""
    try:
        span.set_attribute(key, value)
    except RECOVERABLE_ERRORS:
        pass


def _record_exception(span: Span, exc: BaseException) -> None:
    """记录异常事件，失败时仅降级为 no-op。"""
    try:
        span.record_exception(exc)
    except RECOVERABLE_ERRORS:
        pass


@contextmanager
def tool_call_span(
    *,
    tool_id: str,
    action: str,
    node_id: str,
    run_id: str | None = None,
) -> Iterator[Span | None]:
    """包裹一次实际工具调用，产出 ``execute_tool {tool_id}.{action}`` span。

    异常照常向上抛出（仅额外记录 ``error.type``）；成功退出时标记调用成功。
    """
    attributes: dict[str, Any] = {
        "gen_ai.operation.name": "execute_tool",
        "gen_ai.tool.name": str(tool_id),
        "gen_ai.tool.call.id": str(node_id),
    }
    if run_id:
        attributes["gen_ai.agent.id"] = str(run_id)
    span: Span | None = None
    tracer = get_tracer()
    if tracer is None:
        # 没有可用 tracer：整体降级为 no-op，仍照常传递异常。
        yield None
        return
    try:
        span = tracer.start_span(f"execute_tool {tool_id}.{action}", attributes=attributes)
    except RECOVERABLE_ERRORS:
        span = None
    try:
        yield span
        if span is not None:
            _set_attribute(span, "gen_ai.tool.call.result", "success")
    except BOUNDARY_ERRORS as exc:
        # 只做记录，异常原样抛出：埋点不改变业务失败语义。
        if span is not None:
            _set_attribute(span, "error.type", type(exc).__name__)
            _record_exception(span, exc)
        raise
    finally:
        if span is not None:
            try:
                span.end()
            except RECOVERABLE_ERRORS:
                pass
