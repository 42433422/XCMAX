"""Allowlist and approval checks before invoking an explicit tool registry."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TypeVar

from app.utils.operational_errors import RECOVERABLE_ERRORS

from .ports import DispatchPorts, Payload, Tool
from .results import _err, _ok


async def handle_specialized(
    ports: DispatchPorts, employee_id: str, payload: Payload, ctx: Payload
) -> Payload:
    """专属工具调度入口。

    payload 形如：
        {"handler": "specialized", "tool": "run_pytest", "params": {...}}
    或：
        {"handler": "specialized", "tool": "list_tools"}
    """
    tool_name = str(payload.get("tool") or "").strip()
    if not tool_name:
        available = ports.allowed(employee_id)
        return _ok(
            f"员工 {employee_id} 可用 {len(available)} 个专属工具",
            employee_id=employee_id,
            available_tools=available,
            handler="specialized",
        )
    allowed = ports.allowed(employee_id)
    if tool_name not in allowed:
        return _err(
            f"工具 {tool_name!r} 不在员工 {employee_id} 的专属工具清单中。可用: {allowed}",
            employee_id=employee_id,
            available_tools=allowed,
        )
    fn = ports.registry.get(tool_name)
    if fn is None or not callable(fn):
        return _err(f"工具 {tool_name!r} 未实现")
    params = payload.get("params") or {}
    if not isinstance(params, dict):
        return _err("params 必须为对象")
    if tool_name in ports.write_tools():
        gate_verdict = await ports.write_gate(employee_id, tool_name, params, ctx)
        if not gate_verdict.get("ok", True):
            return _err(
                f"写操作被 gate 拦截: {gate_verdict.get('reason', '')}",
                blocked=True,
                gate_result=gate_verdict,
                pending_approval=bool(gate_verdict.get("pending_approval")),
                approval_request_ids=list(gate_verdict.get("approval_request_ids") or []),
            )
    try:
        result = await fn(params, ctx)
    except RECOVERABLE_ERRORS as exc:
        return _err(f"工具 {tool_name!r} 执行异常: {exc!r}")
    if not isinstance(result, dict):
        return _ok(f"工具 {tool_name!r} 完成", raw=result)
    result.setdefault("tool", tool_name)
    result.setdefault("employee_id", employee_id)
    result.setdefault("handler", "specialized")
    return result


ToolPorts = TypeVar("ToolPorts")


def bind_tool(
    operation: Callable[[ToolPorts, Payload, Payload], Awaitable[Payload]],
    ports: Callable[[], ToolPorts],
) -> Tool:
    """Bind an explicit component input at invocation time while retaining the public two-argument API."""

    async def invoke(params: Payload, ctx: Payload) -> Payload:
        return await operation(ports(), params, ctx)

    invoke.__name__ = f"tool_{operation.__name__}"
    invoke.__qualname__ = invoke.__name__
    invoke.__doc__ = operation.__doc__
    return invoke
