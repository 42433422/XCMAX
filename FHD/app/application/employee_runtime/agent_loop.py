"""员工多轮工具循环：最终派发限制在公布的工具集，授权异常及无效结果拒绝执行。"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Callable
from typing import Any

from app.application.tool_execution_deadline import (
    invocation_deadline,
    remaining_invocation_seconds,
)
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


_FAKE_EXECUTION_MARKERS = (
    "已调用",
    "已执行",
    "已发起",
    "结果如下",
    "执行成功",
    "查询成功",
    "¥",
    "￥",
    "$",
    "/件",
)


def _flatten_tool_transcript(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep execution receipts without replaying provider tool roles.

    The account's Xiaomi route accepts the first tool request, then rejects a
    follow-up that still carries assistant tool_calls and role=tool messages.
    """

    flat: list[dict[str, Any]] = []
    for item in messages:
        role = item.get("role")
        if role == "tool":
            flat.append(
                {
                    "role": "user",
                    "content": "工具执行回执（不可改写）：\n" + str(item.get("content") or ""),
                }
            )
            continue
        if role == "assistant" and item.get("tool_calls"):
            flat.append({"role": "assistant", "content": str(item.get("content") or "")})
            continue
        flat.append(dict(item))
    return flat


def _claims_unexecuted_result(content: str) -> bool:
    return any(marker in content for marker in _FAKE_EXECUTION_MARKERS) or any(
        phrase in content for phrase in ("参数已齐全", "请输出 tool_call", "我不会编造")
    )


def _textual_tool_calls(content: str, round_no: int) -> list[Any]:
    """Accept the market model's inline tool-call markup when native tool_calls are empty."""

    from types import SimpleNamespace

    found: list[Any] = []
    for index, block in enumerate(
        re.findall(r"<tool_call>(.*?)</tool_call>", content, flags=re.DOTALL)
    ):
        match = re.search(r"<function=([^>\s]+)>(.*?)</function>", block, flags=re.DOTALL)
        if match is None:
            match = re.search(r'<function name="([^"]+)">(.*?)</function>', block, flags=re.DOTALL)
        if match is None:
            continue
        body = match.group(2)
        pairs = re.findall(r"<parameter=([^>\s]+)>(.*?)</parameter>", body, flags=re.DOTALL)
        if not pairs:
            pairs = re.findall(
                r'<parameter name="([^"]+)">(.*?)</parameter>', body, flags=re.DOTALL
            )
        arguments = {str(key): str(value).strip() for key, value in pairs}
        found.append(
            SimpleNamespace(
                id=f"text-call-{round_no}-{index}",
                function=SimpleNamespace(
                    name=match.group(1).strip(),
                    arguments=json.dumps(arguments, ensure_ascii=False),
                ),
            )
        )
    return found


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
    """Reject malformed model arguments; keep _parse_args for legacy callers."""

    try:
        data = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}, "工具参数不是有效 JSON 对象"
    if not isinstance(data, dict):
        return {}, "工具参数必须是 JSON 对象"
    return data, None


def _tool_result_state(raw: str) -> tuple[bool, str | None, bool]:
    """Return success/error/verified; legacy data-only responses remain unverified."""

    try:
        payload = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return False, "工具返回不是有效 JSON", True
    if not isinstance(payload, dict):
        return False, "工具返回必须是 JSON 对象", True
    if payload.get("error") or payload.get("ok") is False:
        return False, str(payload.get("error") or "工具返回失败")[:500], True
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


def _as_mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def tool_catalog_rules(tools: list[dict[str, Any]]) -> str:
    """Tell the employee the exact catalog it may name or call."""

    if not tools:
        return "当前没有授权工具。用户要求使用任何工具时，直接说明该工具不可用，不要编造执行结果。"
    lines = ["当前授权工具（只能使用这些；未列出的工具都不可用，不能编造成执行结果）："]
    for spec in tools:
        if not isinstance(spec, dict):
            continue
        function = _as_mapping(spec.get("function"))
        name = str(function.get("name") or "").strip()
        if not name:
            continue
        parameters = _as_mapping(function.get("parameters"))
        properties = _as_mapping(parameters.get("properties"))
        required = [str(item) for item in (parameters.get("required") or [])]
        optional = [str(item) for item in properties if str(item) not in required]
        version = str(spec.get("version_id") or "").strip()
        lines.append(
            f"- {name}：{function.get('description') or '无说明'}。"
            f"必填：{'、'.join(required) or '无'}。可选：{'、'.join(optional) or '无'}。"
            + (f"版本：{version}。" if version else "")
        )
    lines.append(
        "规则：只按以上名称和说明回答，不要提及其他工具。"
        "用户没给齐必填参数时，先询问缺的必填项，不要发起调用，也不要编造结果；可选参数可以不提供。"
        "有多个相近工具时，只调用与用户意图一致的那一个。"
        "未授权或已下线的工具要明确说不可用，不要假装已经执行。"
        "历史消息里的工具执行回执是当时的版本快照，回答历史调用时原样引用回执中的 version_id 和 description，"
        "不要改写成当前说明；新的调用才使用上面的当前定义。"
        "真正调用时只输出："
        "<tool_call><function=工具名><parameter=参数名>参数值</parameter></function></tool_call>"
    )
    return "\n".join(lines)


def _missing_required(
    tools: list[dict[str, Any]], tool_name: str, args: dict[str, Any]
) -> list[str]:
    for spec in tools:
        function = _as_mapping(spec.get("function")) if isinstance(spec, dict) else {}
        if function.get("name") != tool_name:
            continue
        parameters = _as_mapping(function.get("parameters"))
        properties = _as_mapping(parameters.get("properties"))
        missing: list[str] = []
        for name in parameters.get("required") or []:
            key = str(name)
            if key in args:
                continue
            prop = properties.get(key) if isinstance(properties.get(key), dict) else {}
            if "default" not in prop:
                missing.append(key)
        return missing
    return []


def _restore_history(history: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    restored: list[dict[str, Any]] = []
    for item in history or []:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "")
        if role not in {"user", "assistant", "tool"}:
            continue
        restored.append({key: value for key, value in item.items() if value is not None})
    return restored


def _terminal_tool_failure(tool_trace: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Summarize an unfinished/failed tool action for the final run result."""

    failed = [
        row
        for row in tool_trace
        if row.get("success") is False
        and not row.get("superseded_by")
        and not row.get("needs_user_input")
    ]
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
    history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """运行员工多轮工具循环，返回统一结果 dict。"""
    deadline = time.monotonic() + remaining_invocation_seconds(max(0.001, wall_time_limit_sec))
    try:
        from app.infrastructure.llm.client import (
            get_openai_compatible_client,
            require_api_key,
            resolve_chat_model,
        )

        require_api_key()
        client = get_openai_compatible_client()
    except RECOVERABLE_ERRORS:
        return {
            "handler": "agent",
            "ok": False,
            "degraded": True,
            "error": "LLM 不可用，agent 多轮循环已降级",
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
    allowed_tools = {(spec.get("function") or {}).get("name") for spec in tool_specs}
    user_payload = json.dumps({"task": task, "input": input_data or {}}, ensure_ascii=False)[:12000]
    user_content = task.strip() or user_payload
    if input_data:
        user_content = f"{user_content}\n{user_payload}"
    prompt = system_prompt or "你是智能员工助手。"
    catalog = tool_catalog_rules(tool_specs)
    if catalog:
        prompt = f"{prompt}\n\n{catalog}"
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": prompt},
        *_restore_history(history),
        {"role": "user", "content": user_content},
    ]

    tool_trace: list[dict[str, Any]] = []
    trajectory: list[dict[str, Any]] = []
    action_fingerprints: list[str] = []
    rounds = 0

    def expired_result(*, uncertain: bool = False) -> dict[str, Any]:
        return {
            "handler": "agent",
            "ok": False,
            "output": "",
            "rounds": rounds,
            "tool_calls": tool_trace,
            "trajectory": trajectory,
            "exit_status": "wall_time_limit",
            "retryable": False,
            "reconciliation_required": uncertain,
            "execution_state": "unknown" if uncertain else "stopped",
        }

    # Real OpenAI clients can otherwise retry beyond the remaining total budget.
    if callable(getattr(type(client), "with_options", None)):
        client = client.with_options(max_retries=0)
    for _ in range(max(1, max_iterations)):
        if time.monotonic() >= deadline:
            return expired_result()
        rounds += 1
        messages[:] = _flatten_tool_transcript(messages)
        try:
            with invocation_deadline(deadline):
                completion = client.chat.completions.create(
                    model=mdl,
                    messages=messages,
                    tools=tool_specs if tool_specs else None,
                    tool_choice="auto" if tool_specs else None,
                    timeout=max(0.001, deadline - time.monotonic()),
                )
        except RECOVERABLE_ERRORS:
            if time.monotonic() >= deadline:
                return expired_result()
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
                "session_messages": [
                    dict(item) for item in messages if item.get("role") != "system"
                ],
                "exit_status": "llm_error",
            }

        msg = completion.choices[0].message
        try:
            # 统一 Agent Runtime 计量接缝：员工多轮循环每轮 LLM 用量入账
            # （best-effort；计费不受 XCAGI_AGENT_RUNTIME_HOOKS 开关限制）。
            from app.application.agent_runtime.pipeline import (
                completion_usage,
                meter_llm_call,
            )

            meter_llm_call(
                source="employee_agent_loop",
                model=mdl,
                usage=completion_usage(completion),
                metadata={"employee_id": employee_id, "round": rounds},
            )
        except RECOVERABLE_ERRORS:
            logger.debug("employee agent loop metering skipped", exc_info=True)
        if time.monotonic() >= deadline:
            return expired_result()
        content = str(msg.content or "")
        tcs = list(getattr(msg, "tool_calls", None) or [])
        if not tcs:
            tcs = _textual_tool_calls(content, rounds)
            if tcs:
                content = re.sub(
                    r"<tool_call>.*?</tool_call>", "", content, flags=re.DOTALL
                ).strip()
        messages.append(
            {
                "role": "assistant",
                "content": content,
                "tool_calls": _format_tool_calls(tcs) if tcs else None,
            }
        )
        trajectory.append(
            {
                "round": rounds,
                "event": "assistant",
                "content": content[:2000],
                "tool_calls": _format_tool_calls(tcs) if tcs else [],
            }
        )

        if not tcs:
            if (
                tool_specs
                and _claims_unexecuted_result(content)
                and rounds < max(1, max_iterations)
            ):
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "上一条没有工具调用记录，不能当作执行结果。"
                            "参数齐全时只回复工具标记；缺必填参数就向用户询问；"
                            "工具不在授权清单里就说明不可用。不要编造价格或查询结果。"
                        ),
                    }
                )
                continue
            if tool_specs and _claims_unexecuted_result(content):
                content = "没有实际调用工具，不能把生成内容当作执行结果。"
            text = content.strip()
            session_messages = [dict(item) for item in messages if item.get("role") != "system"]
            terminal_failure = _terminal_tool_failure(tool_trace)
            if terminal_failure:
                return {
                    "handler": "agent",
                    "ok": False,
                    "output": text,
                    "rounds": rounds,
                    "tool_calls": tool_trace,
                    "trajectory": trajectory,
                    "session_messages": session_messages,
                    **terminal_failure,
                }
            return {
                "handler": "agent",
                "ok": True,
                "output": text,
                "rounds": rounds,
                "tool_calls": tool_trace,
                "trajectory": trajectory,
                "session_messages": session_messages,
                "exit_status": "completed",
            }

        for tc in tcs:
            if time.monotonic() >= deadline:
                return expired_result()
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
                        "action_id": tc_id,
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

            verdict: dict[str, Any] = {
                "ok": False,
                "reason": "工具不在员工授权白名单，未执行",
            }
            if tool_name in allowed_tools:
                verdict = {"ok": True}
                if gate is not None:
                    try:
                        verdict = gate(tool_name, args)
                    except RECOVERABLE_ERRORS:
                        logger.exception("employee tool gate failed closed: %s", tool_name)
                        verdict = {"ok": False, "reason": "工具授权检查失败，未执行"}
            if not isinstance(verdict, dict) or type(verdict.get("ok")) is not bool:
                verdict = {"ok": False, "reason": "工具授权结果无效，未执行"}
            if verdict["ok"] is True:
                missing = _missing_required(tool_specs, tool_name, args)
                if missing:
                    reason = (
                        "缺少必填参数 "
                        + "、".join(missing)
                        + "，未执行。请向用户询问这些参数，不要编造执行结果。"
                    )
                    verdict = {
                        "ok": False,
                        "reason": reason,
                        "needs_user_input": True,
                        "missing": missing,
                    }
            if verdict["ok"] is not True:
                reason = str(verdict.get("reason") or "blocked by employee gate")
                tool_trace.append(
                    {
                        "tool": tool_name,
                        "args": args,
                        "blocked": True,
                        "success": False,
                        "reason": reason,
                        "needs_user_input": bool(verdict.get("needs_user_input")),
                        "pending_approval": bool(verdict.get("pending_approval")),
                        "approval_request_ids": list(verdict.get("approval_request_ids") or []),
                    }
                )
                trajectory.append(
                    {
                        "round": rounds,
                        "event": "tool",
                        "tool": tool_name,
                        "action_id": tc_id,
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
                            {
                                "success": False,
                                "blocked": True,
                                "needs_user_input": bool(verdict.get("needs_user_input")),
                                "missing": list(verdict.get("missing") or []),
                                "reason": reason,
                            },
                            ensure_ascii=False,
                        ),
                    }
                )
                continue

            try:
                from app.application.tools.workflow import execute_workflow_tool

                if time.monotonic() >= deadline:
                    return expired_result()
                with invocation_deadline(deadline) as budget:
                    result_raw = execute_workflow_tool(
                        tool_name,
                        args,
                        workspace_root,
                        runtime_context={
                            "employee_id": employee_id,
                            "source": "employee_runtime",
                        },
                    )
                if time.monotonic() >= deadline or budget.uncertain:
                    tool_trace.append(
                        {
                            "tool": tool_name,
                            "action_id": tc_id,
                            "args": args,
                            "success": False,
                            "execution_state": "unknown",
                        }
                    )
                    return expired_result(uncertain=True)
            except RECOVERABLE_ERRORS:
                if time.monotonic() >= deadline:
                    return expired_result(uncertain=True)
                result_raw = json.dumps(
                    {
                        "success": False,
                        "error": "工具执行失败",
                        "execution_state": "unknown",
                        "retryable": False,
                    },
                    ensure_ascii=False,
                )
            try:
                result_payload = json.loads(str(result_raw))
            except (TypeError, json.JSONDecodeError):
                result_payload = None
            invalid_receipt = not isinstance(result_payload, dict)
            if invalid_receipt:
                result_payload = {}
            state = str(result_payload.get("execution_state") or result_payload.get("status") or "")
            unknown = (
                invalid_receipt
                or state in {"unknown", "accepted", "pending", "running"}
                or bool(result_payload.get("reconciliation_required"))
            )
            tool_success, tool_error, verified = _tool_result_state(str(result_raw))
            if unknown:
                tool_success, tool_error = (
                    False,
                    str(result_payload.get("error") or "工具结果待核对"),
                )
            if tool_success:
                for previous in reversed(tool_trace):
                    if (
                        previous.get("tool") == tool_name
                        and previous.get("invalid_arguments")
                        and not previous.get("superseded_by")
                    ):
                        previous["superseded_by"] = tc_id or f"round-{rounds}"
                        break
            tool_trace.append(
                {
                    "tool": tool_name,
                    "action_id": tc_id,
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
                    "action_id": tc_id,
                    "args": args,
                    "blocked": False,
                    "success": tool_success,
                    "verified": verified,
                    "result": str(result_raw)[:2000],
                }
            )
            tool_content = str(result_raw)[:8000]
            try:
                tool_payload = json.loads(str(result_raw))
            except json.JSONDecodeError:
                tool_payload = None
            if isinstance(tool_payload, dict) and tool_payload.get("version_id"):
                definition = _as_mapping(tool_payload.get("definition"))
                function = _as_mapping(definition.get("function"))
                tool_content = (
                    "调用快照"
                    f" version_id={tool_payload['version_id']}"
                    f" description={function.get('description') or ''}\n" + tool_content
                )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "content": tool_content,
                }
            )
            if unknown or (not tool_success and result_payload.get("retryable") is False):
                return {
                    "handler": "agent",
                    "ok": False,
                    "output": "",
                    "rounds": rounds,
                    "tool_calls": tool_trace,
                    "trajectory": trajectory,
                    "exit_status": "unknown" if unknown else "tool_failed",
                    "execution_state": (state or "unknown") if unknown else "failed",
                    "error": tool_error,
                    "retryable": False,
                    "reconciliation_required": unknown,
                }

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
