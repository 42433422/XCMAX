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


def run_employee_agent_loop(
    *,
    employee_id: str,
    system_prompt: str,
    task: str,
    input_data: dict[str, Any] | None = None,
    tools: list[dict[str, Any]] | None = None,
    workspace_root: str | None = None,
    max_iterations: int = _DEFAULT_MAX_ITERATIONS,
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
            "output": "",
            "rounds": 0,
            "tool_calls": [],
        }

    mdl = model or resolve_chat_model()
    tool_specs = tools if tools is not None else default_employee_tools()
    user_payload = json.dumps({"task": task, "input": input_data or {}}, ensure_ascii=False)[:12000]
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt or "你是智能员工助手。"},
        {"role": "user", "content": user_payload},
    ]

    tool_trace: list[dict[str, Any]] = []
    rounds = 0
    for _ in range(max(1, max_iterations)):
        rounds += 1
        try:
            completion = client.chat.completions.create(
                model=mdl,
                messages=messages,
                tools=tool_specs if tool_specs else None,
                tool_choice="auto" if tool_specs else None,
            )
        except RECOVERABLE_ERRORS as exc:
            logger.exception("employee agent loop LLM call failed emp=%s", employee_id)
            return {
                "handler": "agent",
                "ok": False,
                "error": str(exc)[:400],
                "output": "",
                "rounds": rounds,
                "tool_calls": tool_trace,
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

        if not tcs:
            text = str(msg.content or "").strip()
            return {
                "handler": "agent",
                "ok": True,
                "output": text,
                "rounds": rounds,
                "tool_calls": tool_trace,
            }

        for tc in tcs:
            fn = getattr(tc, "function", None)
            tool_name = str(getattr(fn, "name", "") or "").strip()
            args = _parse_args(str(getattr(fn, "arguments", "") or ""))
            tc_id = str(getattr(tc, "id", "") or "")

            if gate is not None:
                try:
                    verdict = gate(tool_name, args)
                except RECOVERABLE_ERRORS:
                    verdict = {"ok": True}
                if not verdict.get("ok", True):
                    reason = str(verdict.get("reason") or "blocked by employee gate")
                    tool_trace.append({"tool": tool_name, "blocked": True, "reason": reason})
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
            tool_trace.append({"tool": tool_name, "args": args})
            messages.append(
                {"role": "tool", "tool_call_id": tc_id, "content": str(result_raw)[:8000]}
            )

    return {
        "handler": "agent",
        "ok": True,
        "output": "（已达到最大迭代次数，返回当前进展）",
        "rounds": rounds,
        "tool_calls": tool_trace,
        "max_iterations_reached": True,
    }


__all__ = ["GateFn", "default_employee_tools", "run_employee_agent_loop"]
