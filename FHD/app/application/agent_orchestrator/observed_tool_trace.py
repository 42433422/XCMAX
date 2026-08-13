"""Persist authenticated observations without entering the tool execution path."""

from __future__ import annotations

from typing import Any

from app.application.agent_orchestrator.run_models import (
    AgentRun,
    AgentStep,
    ToolCall,
    utc_now_iso,
)
from app.application.agent_orchestrator.run_repository import get_agent_run_repository
from app.application.agent_orchestrator.task_context import apply_task_context
from app.application.agent_orchestrator.tool_spec import ToolActionSpecV2

_MAX_TEXT = 4000
_MAX_ITEMS = 40
_TASK_CONTEXT_KEYS = (
    "tenant_id",
    "task_id",
    "conversation_id",
    "session_id",
    "task_title",
    "workspace_id",
    "workspace_path",
    "workspace_isolation",
)


def _safe_value(value: Any, *, depth: int = 0) -> Any:
    if depth >= 4:
        return str(value)[:_MAX_TEXT]
    if isinstance(value, str):
        return value[:_MAX_TEXT]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [_safe_value(item, depth=depth + 1) for item in value[:_MAX_ITEMS]]
    if isinstance(value, dict):
        return {
            str(key)[:160]: _safe_value(child, depth=depth + 1)
            for key, child in list(value.items())[:_MAX_ITEMS]
        }
    return str(value)[:_MAX_TEXT]


def _task_runtime_context(
    runtime_context: dict[str, Any] | None,
    *,
    user_id: str,
) -> dict[str, Any]:
    source = runtime_context or {}
    context = {
        key: str(source.get(key) or "").strip()[:1024]
        for key in _TASK_CONTEXT_KEYS
        if source.get(key)
    }
    context.update(
        {
            "local_user_id": user_id,
            "actor_id": user_id,
            "trace_mode": "desktop_observed_tool",
            "observation_trust": "authenticated_client",
        }
    )
    return context


def create_observed_tool_trace_run(
    *,
    spec: ToolActionSpecV2,
    user_id: str,
    message: str,
    params: dict[str, Any],
    output: dict[str, Any],
    response: str = "",
    runtime_context: dict[str, Any] | None = None,
    source: str = "desktop_fast_path",
) -> AgentRun:
    """Record one already-completed tool call; this function never executes a tool."""
    safe_params = _safe_value(params)
    safe_output = _safe_value(output)
    assert isinstance(safe_params, dict)
    assert isinstance(safe_output, dict)
    succeeded = safe_output.get("success") is not False
    status = "completed" if succeeded else "failed"
    finished_at = utc_now_iso()
    runtime = _task_runtime_context(runtime_context, user_id=user_id)
    run = AgentRun(
        user_id=user_id,
        message=str(message or "")[:_MAX_TEXT],
        status=status,
        intent=f"{spec.tool_id}_{spec.action}",
        metadata={
            "channel": "desktop_observed_tool",
            "source": str(source or "desktop_fast_path")[:160],
            "trace_mode": "desktop_observed_tool",
            "runtime_context": runtime,
            "tool_call_count": 1,
            "cost_units_total": int(spec.cost_units or 0),
            "non_retryable": True,
        },
    )
    apply_task_context(run, runtime)
    step = AgentStep(
        node_id=f"observed_{spec.tool_id}_{spec.action}".replace(".", "_"),
        tool_id=spec.tool_id,
        action=spec.action,
        params=safe_params,
        risk=spec.risk,
        idempotent=spec.idempotent,
        description="桌面快速路径已执行工具调用",
        status=status,
        output=safe_output,
        finished_at=finished_at,
    )
    call = ToolCall(
        step_id=step.step_id,
        node_id=step.node_id,
        tool_id=step.tool_id,
        action=step.action,
        params=safe_params,
        status=status,
        output=safe_output,
        error="" if succeeded else "observed tool reported failure",
        cost_units=int(spec.cost_units or 0),
        permission=spec.permission,
        finished_at=finished_at,
        metadata={"observed": True, "risk": spec.risk, "idempotent": spec.idempotent},
    )
    run.steps.append(step)
    run.tool_calls.append(call)
    run.final_output = {
        "response": str(response or "")[:_MAX_TEXT],
        "node_outputs": {step.node_id: safe_output},
        "tool_calls": [call.to_dict()],
        "cost_units_total": int(spec.cost_units or 0),
    }
    run.add_event(
        "run.created",
        "桌面工具观察已进入 AgentRun 追踪",
        {"source": run.metadata["source"], "observed": True},
    )
    run.add_event(
        "tool.completed" if succeeded else "tool.failed",
        f"记录桌面工具 {spec.tool_id}.{spec.action}",
        {"step_id": step.step_id, "call_id": call.call_id, "observed": True},
    )
    run.add_event(
        "run.completed" if succeeded else "run.failed",
        "桌面工具调用追踪完成" if succeeded else "桌面工具调用报告失败",
        {"observed": True},
    )
    return get_agent_run_repository().save(run)


__all__ = ["create_observed_tool_trace_run"]
