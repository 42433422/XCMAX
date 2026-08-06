"""员工多轮工具调用循环（OpenAI function-calling ReAct）。

替换旧的单轮 ``agent_runner._chat_completion``：员工 ``agent`` handler 现在可以
跨多轮调用工具（来自工作流工具注册表），并对每次 tool_call 套一个可选 gate
（P1 接入 WorkspaceGuard + risk_gate）。

复用既有积木：
- LLM 客户端：``app.infrastructure.llm.client.get_openai_compatible_client``
- 工具执行：``app.application.tools.workflow.execute_workflow_tool``
- 工具清单：``app.application.tools.workflow.get_workflow_tool_registry``

同步实现（沿用 legacy_chat_adapter 的同步 OpenAI 客户端），由 executor 同步调用。
无 API Key / offline 时优雅降级（返回 degraded 标记，不抛错）。
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

# gate 签名：(tool_name, args) -> {"ok": bool, "reason": str}
GateFn = Callable[[str, dict[str, Any]], dict[str, Any]]

_DEFAULT_MAX_ITERATIONS = 6


def default_employee_tools() -> list[dict[str, Any]]:
    """员工默认可用工具：工作流基础工具，剔除「员工包工具」本身以避免递归调用。"""
    try:
        from app.application.tools.workflow import get_workflow_tool_registry
        from app.mod_sdk.employee_tool_registry import is_employee_tool

        reg = get_workflow_tool_registry() or []
        out: list[dict[str, Any]] = []
        for spec in reg:
            name = ""
            if isinstance(spec, dict):
                name = str((spec.get("function") or {}).get("name") or "")
            if name and is_employee_tool(name):
                continue
            out.append(spec)
        return out
    except RECOVERABLE_ERRORS:
        logger.debug("default_employee_tools fallback to empty", exc_info=True)
        return []


def _format_tool_calls(tcs: Any) -> list[dict[str, Any]]:
    formatted: list[dict[str, Any]] = []
    for tc in tcs:
        fn = getattr(tc, "function", None)
        formatted.append(
            {
                "id": str(getattr(tc, "id", "") or ""),
                "type": "function",
                "function": {
                    "name": str(getattr(fn, "name", "") or ""),
                    "arguments": str(getattr(fn, "arguments", "") or ""),
                },
            }
        )
    return formatted


def _parse_args(raw: str) -> dict[str, Any]:
    try:
        data = json.loads(raw or "{}")
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def _parse_tool_args(raw: str) -> tuple[dict[str, Any], str | None]:
    """Parse one model function-call payload without silently executing bad JSON.

    ``_parse_args`` is kept as the historic, lenient helper used by callers and
    tests.  An agent loop has a different safety contract: malformed arguments
    are an invalid tool call, not an invitation to execute the tool with an
    empty object.  The model receives a structured error and can repair the
    call on a later round.
    """

    try:
        data = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}, "工具参数不是有效 JSON 对象"
    if not isinstance(data, dict):
        return {}, "工具参数必须是 JSON 对象"
    return data, None


def _tool_result_state(raw: str) -> tuple[bool, str | None, bool]:
    """Return ``(success, error, verified)`` for a workflow tool result.

    The legacy workflow surface predates a uniform output schema.  A structured
    ``success`` field is authoritative; an explicit error/token request is a
    failure or unfinished action.  Older read-only tools that return a useful
    object without either field remain compatible but are marked unverified in
    the trace, rather than being mistaken for proof of a consequential action.
    """

    try:
        payload = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return False, "工具返回不是有效 JSON", True
    if not isinstance(payload, dict):
        return False, "工具返回必须是 JSON 对象", True
    if "success" in payload:
        if payload.get("success") is True:
            return True, None, True
        return (
            False,
            str(payload.get("error") or payload.get("message") or "工具返回失败")[:500],
            True,
        )
    if payload.get("requires_token") or payload.get("pending_approval"):
        return (
            False,
            str(payload.get("message") or "工具等待授权")[:500],
            True,
        )
    if payload.get("error"):
        return False, str(payload.get("error"))[:500], True
    # Older read-only handlers can return data without a success envelope.
    # Preserve their compatibility, but make the weaker proof visible in the
    # trajectory and never use it to justify a side-effect claim.
    return True, None, False


def _terminal_tool_failure(tool_trace: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Summarize an unfinished/failed tool action for the final run result."""

    failed = [row for row in tool_trace if row.get("success") is False]
    if not failed:
        return None
    first = failed[0]
    if first.get("pending_approval"):
        return {
            "exit_status": "waiting_approval",
            "error": str(first.get("reason") or "工具等待用户授权"),
            "pending_approval": True,
        }
    if first.get("blocked"):
        return {
            "exit_status": "tool_blocked",
            "error": str(first.get("reason") or "工具调用被拦截"),
        }
    return {
        "exit_status": "tool_failed",
        "error": str(first.get("error") or first.get("reason") or "工具调用失败"),
    }


def run_employee_agent_loop(
    *,
    employee_id: str,
    system_prompt: str,
    task: str,
    input_data: dict[str, Any] | None = None,
    tools: list[dict[str, Any]] | None = None,
    workspace_root: str | None = None,
    max_iterations: int = _DEFAULT_MAX_ITERATIONS,
    wall_time_limit_sec: float = 300.0,
    repeat_limit: int = 3,
    gate: GateFn | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """运行员工多轮工具循环，返回统一结果 dict。"""
    try:
        from app.infrastructure.llm.client import (
            get_openai_compatible_client,
            require_api_key,
            resolve_chat_model,
        )

        require_api_key()
        client = get_openai_compatible_client()
    except (RuntimeError, *RECOVERABLE_ERRORS) as exc:
        return {
            "handler": "agent",
            "ok": False,
            "degraded": True,
            "error": f"LLM 不可用，agent 多轮循环降级：{str(exc)[:200]}",
            "error_code": "employee_llm_not_configured",
            "retryable": False,
            "output": "",
            "rounds": 0,
            "tool_calls": [],
            "trajectory": [],
            "exit_status": "llm_unavailable",
        }

    mdl = model or resolve_chat_model()
    tool_specs = tools if tools is not None else default_employee_tools()
    user_payload = json.dumps({"task": task, "input": input_data or {}}, ensure_ascii=False)[:12000]
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt or "你是智能员工助手。"},
        {"role": "user", "content": user_payload},
    ]

    tool_trace: list[dict[str, Any]] = []
    trajectory: list[dict[str, Any]] = []
    action_fingerprints: list[str] = []
    started = time.monotonic()
    rounds = 0
    for _ in range(max(1, max_iterations)):
        if time.monotonic() - started >= max(0.001, wall_time_limit_sec):
            return {
                "handler": "agent",
                "ok": False,
                "output": "",
                "rounds": rounds,
                "tool_calls": tool_trace,
                "trajectory": trajectory,
                "exit_status": "wall_time_limit",
            }
        rounds += 1
        try:
            completion = client.chat.completions.create(
                model=mdl,
                messages=messages,
                tools=tool_specs if tool_specs else None,
                tool_choice="auto" if tool_specs else None,
            )
        except RECOVERABLE_ERRORS:
            logger.exception("employee agent loop LLM call failed")
            return {
                "handler": "agent",
                "ok": False,
                "error": "员工模型调用失败，请稍后重试",
                "error_code": "employee_llm_call_failed",
                "retryable": True,
                "output": "",
                "rounds": rounds,
                "tool_calls": tool_trace,
                "trajectory": trajectory,
                "exit_status": "llm_error",
            }

        msg = completion.choices[0].message
        tcs = getattr(msg, "tool_calls", None) or []
        messages.append(
            {
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": _format_tool_calls(tcs) if tcs else None,
            }
        )
        trajectory.append(
            {
                "round": rounds,
                "event": "assistant",
                "content": str(msg.content or "")[:2000],
                "tool_calls": _format_tool_calls(tcs) if tcs else [],
            }
        )

        if not tcs:
            text = str(msg.content or "").strip()
            terminal_failure = _terminal_tool_failure(tool_trace)
            if terminal_failure:
                return {
                    "handler": "agent",
                    "ok": False,
                    "output": text,
                    "rounds": rounds,
                    "tool_calls": tool_trace,
                    "trajectory": trajectory,
                    **terminal_failure,
                }
            return {
                "handler": "agent",
                "ok": True,
                "output": text,
                "rounds": rounds,
                "tool_calls": tool_trace,
                "trajectory": trajectory,
                "exit_status": "completed",
            }

        for tc in tcs:
            fn = getattr(tc, "function", None)
            tool_name = str(getattr(fn, "name", "") or "").strip()
            raw_arguments = str(getattr(fn, "arguments", "") or "")
            args, args_error = _parse_tool_args(raw_arguments)
            tc_id = str(getattr(tc, "id", "") or "")
            if args_error:
                tool_trace.append(
                    {
                        "tool": tool_name,
                        "args": args,
                        "success": False,
                        "error": args_error,
                        "invalid_arguments": True,
                    }
                )
                trajectory.append(
                    {
                        "round": rounds,
                        "event": "tool",
                        "tool": tool_name,
                        "args": args,
                        "blocked": True,
                        "success": False,
                        "result": args_error,
                    }
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc_id,
                        "content": json.dumps(
                            {"success": False, "error": args_error}, ensure_ascii=False
                        ),
                    }
                )
                continue
            fingerprint = json.dumps(
                {"tool": tool_name, "args": args}, ensure_ascii=False, sort_keys=True
            )
            action_fingerprints.append(fingerprint)
            if (
                repeat_limit >= 2
                and len(action_fingerprints) >= repeat_limit
                and len(set(action_fingerprints[-repeat_limit:])) == 1
            ):
                return {
                    "handler": "agent",
                    "ok": False,
                    "output": "",
                    "rounds": rounds,
                    "tool_calls": tool_trace,
                    "trajectory": trajectory,
                    "exit_status": "stuck_repeating_action",
                    "repeat_count": repeat_limit,
                }

            if gate is not None:
                try:
                    verdict = gate(tool_name, args)
                except RECOVERABLE_ERRORS:
                    logger.exception("employee tool gate failed closed: %s", tool_name)
                    verdict = {"ok": False, "reason": "工具授权检查失败，未执行"}
                if not verdict.get("ok", True):
                    reason = str(verdict.get("reason") or "blocked by employee gate")
                    tool_trace.append(
                        {
                            "tool": tool_name,
                            "args": args,
                            "blocked": True,
                            "success": False,
                            "reason": reason,
                            "pending_approval": bool(verdict.get("pending_approval")),
                            "approval_request_ids": list(verdict.get("approval_request_ids") or []),
                        }
                    )
                    trajectory.append(
                        {
                            "round": rounds,
                            "event": "tool",
                            "tool": tool_name,
                            "args": args,
                            "blocked": True,
                            "success": False,
                            "result": reason,
                        }
                    )
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc_id,
                            "content": json.dumps(
                                {"success": False, "blocked": True, "reason": reason},
                                ensure_ascii=False,
                            ),
                        }
                    )
                    continue

            try:
                from app.application.tools.workflow import execute_workflow_tool

                result_raw = execute_workflow_tool(tool_name, args, workspace_root)
            except RECOVERABLE_ERRORS as exc:
                result_raw = json.dumps(
                    {"success": False, "error": str(exc)[:300]}, ensure_ascii=False
                )
            tool_success, tool_error, verified = _tool_result_state(str(result_raw))
            tool_trace.append(
                {
                    "tool": tool_name,
                    "args": args,
                    "success": tool_success,
                    "error": tool_error,
                    "verified": verified,
                }
            )
            trajectory.append(
                {
                    "round": rounds,
                    "event": "tool",
                    "tool": tool_name,
                    "args": args,
                    "blocked": False,
                    "success": tool_success,
                    "verified": verified,
                    "result": str(result_raw)[:2000],
                }
            )
            messages.append(
                {"role": "tool", "tool_call_id": tc_id, "content": str(result_raw)[:8000]}
            )

    return {
        "handler": "agent",
        "ok": False,
        "error": "已达到最大迭代次数，任务尚未完成",
        "output": "（已达到最大迭代次数，任务尚未完成）",
        "rounds": rounds,
        "tool_calls": tool_trace,
        "max_iterations_reached": True,
        "trajectory": trajectory,
        "exit_status": "max_iterations",
    }


__all__ = ["GateFn", "default_employee_tools", "run_employee_agent_loop"]
