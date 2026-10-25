"""State projection and callback scopes for independent workflow invocations."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

from .workflow_types import NodeExecutionResult, StateSchema, apply_state_schema

logger = logging.getLogger(__name__)
StateEventCallback = Callable[[dict[str, Any]], object]


def append_node_trace(runtime_context: dict[str, Any], result: NodeExecutionResult) -> None:
    runtime_context.setdefault("workflow_trace", [])
    trace = runtime_context["workflow_trace"]
    if not isinstance(trace, list):
        runtime_context["workflow_trace"] = trace = []
    trace.append(
        {
            "node_id": result.node_id,
            "tool_id": result.tool_id,
            "action": result.action,
            "success": result.success,
            "output": deepcopy(result.output),
            "retries": result.retries,
            "retryable": result.retryable,
            "duration_ms": result.duration_ms,
            "error": result.error,
            "recovery_hint": result.recovery_hint,
        }
    )


def merge_state_schema(
    runtime_context: dict[str, Any],
    result: NodeExecutionResult,
    schema: StateSchema,
) -> None:
    """用 StateSchema 校验/归并 runtime_context；校验失败记录到节点结果，不中断执行。"""
    try:
        apply_state_schema(runtime_context, schema)
    except ValueError as exc:
        msg = str(exc)
        result.error = (result.error + "; " if result.error else "") + msg
        logger.warning("StateSchema 校验失败 node=%s: %s", result.node_id, msg)


def summarize_output(output: object) -> str:
    if not isinstance(output, dict):
        return str(output)[:200]
    if output.get("success") is True:
        msg = str(output.get("message") or output.get("answer") or "").strip()
        if msg:
            return msg[:200]
        data = output.get("data")
        if data is not None:
            if isinstance(data, list):
                return f"返回 {len(data)} 条数据"
            return str(data)[:200]
    err = str(output.get("error") or output.get("message") or "").strip()
    if err:
        return f"错误: {err[:100]}"
    return str(output)[:200]


def record_result(
    result: NodeExecutionResult,
    runtime_context: dict[str, Any],
    schema: StateSchema,
    emit: Callable[[NodeExecutionResult], None],
    append_trace: Callable[[dict[str, Any], NodeExecutionResult], None] = append_node_trace,
    merge_schema: Callable[
        [dict[str, Any], NodeExecutionResult, StateSchema], None
    ] = merge_state_schema,
) -> None:
    """Project each result once, on the scheduling thread, before publishing it."""
    runtime_context.setdefault("node_outputs", {})[result.node_id] = result.output
    append_trace(runtime_context, result)
    merge_schema(runtime_context, result, schema)
    emit(result)


class StateEvents:
    """Per-engine, context-local callback overrides, inherited by nested runs."""

    def __init__(self) -> None:
        self._callback: ContextVar[StateEventCallback | None] = ContextVar(
            "workflow_state_callback", default=None
        )

    @contextmanager
    def scope(self, callback: StateEventCallback | None) -> Iterator[None]:
        if callback is None:
            yield
            return
        token = self._callback.set(callback)
        try:
            yield
        finally:
            self._callback.reset(token)

    def emit(
        self,
        result: NodeExecutionResult,
        default_callback: StateEventCallback | None,
        event_logger: logging.Logger,
    ) -> None:
        callback = self._callback.get()
        if callback is None:
            callback = default_callback
        if callback is None:
            return
        try:
            callback(
                {
                    "type": "state.update",
                    "node_id": result.node_id,
                    "status": "succeeded" if result.success else "failed",
                    "output_summary": summarize_output(result.output),
                }
            )
        except RECOVERABLE_ERRORS:
            event_logger.warning(
                "state_event_callback failed node=%s", result.node_id, exc_info=True
            )
