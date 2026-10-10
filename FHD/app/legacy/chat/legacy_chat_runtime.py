"""Chat and streaming entrypoints for the absorbed legacy planner."""

from __future__ import annotations

import json
from collections.abc import Iterable
from types import SimpleNamespace
from typing import Any

from app.infrastructure.llm.client import llm_client_scope


def _facade() -> Any:
    from app.legacy.chat import legacy_chat_adapter

    return legacy_chat_adapter


def _opening_tool_choice(
    user_message: str, tools: list[Any], runtime_context: dict[str, Any] | None
) -> Any:
    from app.application.agent_orchestrator.business_harness import forced_order_tool_choice
    from app.application.document_employee_routing import forced_document_tool_choice

    return (
        forced_document_tool_choice(user_message, tools, runtime_context)
        or forced_order_tool_choice(user_message, tools)
        or "auto"
    )


def _approval_wait_text() -> str:
    for record in _facade().get_last_tool_records():
        output = record.get("output") or {}
        if isinstance(output, dict) and output.get("pending_approval") is True:
            return str(output.get("message") or "审批请求已创建，请在业务审批中处理；尚未执行。")
    return ""


def chat(
    user_message: str,
    *,
    runtime_context: dict[str, Any] | None = None,
    system_prompt: str | None = None,
    workspace_root: str | None = None,
    max_iterations: int | None = None,
    db_write_token: str | None = None,
    model: str | None = None,
    client: Any | None = None,
) -> Any:
    _facade().reset_planner_tool_dedup_state()
    if max_iterations is None:
        max_iterations = 8
    sys = _facade().merge_system_prompt(system_prompt, runtime_context)
    messages: list[dict[str, Any]] = []
    if sys:
        messages.append({"role": "system", "content": sys})
    messages.append(
        {
            "role": "user",
            "content": _facade().build_openai_user_content(user_message, runtime_context),
        }
    )
    has_image_input = _facade().messages_have_image_parts(messages)
    if client is None:
        _facade().require_api_key()
        cli = _facade().get_openai_compatible_client()
    else:
        cli = client
    mdl = _facade()._resolve_chat_model_for_client(cli, model)
    tools = _facade()._get_workflow_tool_registry()
    tool_choice = _opening_tool_choice(user_message, tools, runtime_context)
    tool_outputs: list[str] = []
    for _ in range(max_iterations):
        c = cli.chat.completions.create(
            model=mdl,
            messages=messages,
            tools=tools if tools else None,
            tool_choice=tool_choice if tools else None,
        )
        msg = c.choices[0].message
        tcs = getattr(msg, "tool_calls", None) or []
        formatted_tool_calls = None
        if tcs:
            formatted_tool_calls = [
                {
                    "id": str(getattr(tc, "id", "") or ""),
                    "type": "function",
                    "function": {
                        "name": str(getattr(getattr(tc, "function", None), "name", "") or ""),
                        "arguments": str(
                            getattr(getattr(tc, "function", None), "arguments", "") or ""
                        ),
                    },
                }
                for tc in tcs
            ]
        messages.append(
            {"role": "assistant", "content": msg.content or "", "tool_calls": formatted_tool_calls}
        )
        if tcs:
            for tc in tcs:
                fn = getattr(tc, "function", None)
                tool_name = str(getattr(fn, "name", "") or "").strip()
                if tool_name:
                    tool_outputs.append(f"[调用工具: {tool_name}]")
            with llm_client_scope(cli, mdl):
                token_request = _facade().append_tool_messages(
                    messages,
                    tcs,
                    workspace_root=workspace_root,
                    runtime_context=runtime_context,
                    db_write_token=db_write_token,
                )
            if token_request and token_request.get("requires_token"):
                return json.dumps(
                    _facade()._attach_last_tool_records(
                        {
                            "requires_token": True,
                            "token_name": token_request.get("token_name"),
                            "token_description": token_request.get("token_description"),
                            "message": token_request.get("message"),
                            "tool_outputs": tool_outputs,
                        }
                    ),
                    ensure_ascii=False,
                )
            if waiting := _approval_wait_text():
                return _facade()._attach_last_tool_records(
                    {"response": waiting, "text": waiting, "pending_approval": True}
                )
            tool_choice = "auto"
            continue
        result = str(msg.content or "").strip()
        if has_image_input and (not result):
            raise _facade().EmptyMultimodalResponseError(
                f"模型 {mdl} 完成了图片处理请求，但没有返回可显示的正文。系统已停止重复空请求，请重试或切换视觉模型。"
            )
        full_response = result
        if tool_outputs:
            full_response = "\n".join(tool_outputs) + "\n\n" + result
        return _facade()._attach_last_tool_records(
            {
                "response": full_response,
                "thinking_steps": "\n".join(tool_outputs) if tool_outputs else None,
                "text": result,
            }
        )
    return _facade()._attach_last_tool_records(
        {
            "response": "对话达到最大迭代次数，未完成。",
            "thinking_steps": None,
            "text": "对话达到最大迭代次数，未完成。",
        }
    )


def chat_stream_text(
    user_message: str,
    *,
    runtime_context: dict[str, Any] | None = None,
    system_prompt: str | None = None,
    workspace_root: str | None = None,
    max_iterations: int | None = None,
    db_write_token: str | None = None,
    model: str | None = None,
    client: Any | None = None,
) -> Iterable[str | dict[str, Any]]:
    _facade().reset_planner_tool_dedup_state()
    if max_iterations is None:
        max_iterations = 8
    sys = _facade().merge_system_prompt(system_prompt, runtime_context)
    messages: list[dict[str, Any]] = []
    if sys:
        messages.append({"role": "system", "content": sys})
    messages.append(
        {
            "role": "user",
            "content": _facade().build_openai_user_content(user_message, runtime_context),
        }
    )
    has_image_input = _facade().messages_have_image_parts(messages)
    if client is None:
        _facade().require_api_key()
        cli = _facade().get_openai_compatible_client()
    else:
        cli = client
    mdl = _facade()._resolve_chat_model_for_client(cli, model)
    tools = _facade()._get_workflow_tool_registry()
    tool_choice = _opening_tool_choice(user_message, tools, runtime_context)
    for _ in range(max_iterations):
        stream = cli.chat.completions.create(
            model=mdl,
            messages=messages,
            stream=True,
            tools=tools if tools else None,
            tool_choice=tool_choice if tools else None,
        )
        text_parts: list[str] = []
        tool_calls_by_idx: dict[int, Any] = {}
        finish_reason = None
        for chunk in stream:
            choice = chunk.choices[0]
            finish_reason = getattr(choice, "finish_reason", None)
            delta = getattr(choice, "delta", None)
            if delta is None:
                continue
            content = getattr(delta, "content", None)
            if content:
                text_parts.append(str(content))
                yield str(content)
            tc_list = getattr(delta, "tool_calls", None) or []
            for position, tc in enumerate(tc_list):
                index = getattr(tc, "index", None)
                idx = position if index is None else int(index)
                cur = tool_calls_by_idx.get(idx)
                if cur is None:
                    cur = {
                        "id": getattr(tc, "id", None),
                        "function": {
                            "name": getattr(getattr(tc, "function", None), "name", None),
                            "arguments": getattr(getattr(tc, "function", None), "arguments", "")
                            or "",
                        },
                    }
                    tool_calls_by_idx[idx] = cur
                else:
                    fn = getattr(tc, "function", None)
                    fn_name = getattr(fn, "name", None)
                    if fn_name:
                        cur["function"]["name"] = fn_name
                    cur["function"]["arguments"] += str(getattr(fn, "arguments", "") or "")
        if tool_calls_by_idx:
            for v in tool_calls_by_idx.values():
                tool_name = str(v.get("function", {}).get("name", "") or "")
                raw_args = str(v.get("function", {}).get("arguments") or "")
                if tool_name:
                    label = _facade()._tool_stream_call_label(tool_name, raw_args)
                    yield f"\n[正在调用工具: {label}]\n"
                    slow = _facade()._slow_tool_wait_message(tool_name, raw_args)
                    if slow:
                        yield slow
        if finish_reason == "tool_calls" or tool_calls_by_idx:
            tcs = [
                SimpleNamespace(
                    id=v.get("id") or "",
                    function=SimpleNamespace(**v["function"]),
                )
                for v in tool_calls_by_idx.values()
            ]
            formatted_tool_calls = [
                {
                    "id": t.id,
                    "type": "function",
                    "function": {"name": t.function.name, "arguments": t.function.arguments},
                }
                for t in tcs
            ]
            messages.append(
                {"role": "assistant", "content": "", "tool_calls": formatted_tool_calls}
            )
            with llm_client_scope(cli, mdl):
                token_request = _facade().append_tool_messages(
                    messages,
                    tcs,
                    workspace_root=workspace_root,
                    runtime_context=runtime_context,
                    db_write_token=db_write_token,
                )
            if token_request and token_request.get("requires_token"):
                yield {
                    "_planner_sse": "requires_token",
                    "token_name": token_request.get("token_name") or "DB_WRITE_TOKEN",
                    "token_description": token_request.get("token_description")
                    or token_request.get("message")
                    or "数据库写入授权令牌",
                    "message": token_request.get("message"),
                }
                return
            if waiting := _approval_wait_text():
                yield waiting
                return
            n_tail = len(tcs)
            tool_payloads: list[dict[str, Any]] = []
            if n_tail:
                for m in messages[-n_tail:]:
                    if m.get("role") != "tool":
                        continue
                    try:
                        tool_payloads.append(json.loads(str(m.get("content") or "{}")))
                    except json.JSONDecodeError:
                        tool_payloads.append({})
                while len(tool_payloads) < n_tail:
                    tool_payloads.append({})
            yield _facade()._post_tool_round_hint(tcs, tool_payloads)
            tool_choice = "auto"
            continue
        if text_parts:
            return
        if has_image_input:
            raise _facade().EmptyMultimodalResponseError(
                f"模型 {mdl} 完成了图片处理请求，但没有返回可显示的正文。系统已停止重复空请求，请重试或切换视觉模型。"
            )
    yield {"_planner_sse": "error", "message": "对话达到最大迭代次数，未完成。"}


def chat_stream_sse_events(
    user_message: str,
    *,
    runtime_context: dict[str, Any] | None = None,
    system_prompt: str | None = None,
    workspace_root: str | None = None,
    max_iterations: int | None = None,
    db_write_token: str | None = None,
    model: str | None = None,
    client: Any | None = None,
):
    for item in _facade().chat_stream_text(
        user_message,
        runtime_context=runtime_context,
        system_prompt=system_prompt,
        workspace_root=workspace_root,
        max_iterations=max_iterations,
        db_write_token=db_write_token,
        model=model,
        client=client,
    ):
        if isinstance(item, dict) and item.get("_planner_sse") == "error":
            yield {
                "type": "error",
                "message": item["message"],
                "result": _facade()._attach_last_tool_records({}),
            }
            return
        if isinstance(item, dict) and item.get("_planner_sse") == "requires_token":
            td = str(
                item.get("token_description") or item.get("message") or "数据库写入授权令牌"
            ).strip()
            tn = str(item.get("token_name") or "DB_WRITE_TOKEN").strip()
            yield {"type": "token", "text": f"\n[需要授权: {td}]\n"}
            yield {
                "type": "requires_token",
                "token_name": tn,
                "token_description": td,
                "result": _facade()._attach_last_tool_records({}),
            }
            return
        yield {"type": "token", "text": str(item)}
    yield {"type": "done", "result": _facade()._attach_last_tool_records({})}
