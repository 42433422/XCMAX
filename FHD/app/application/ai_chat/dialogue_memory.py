"""桌面聊天按会话保留用户原话，并把这些原话交给当前请求的模型。

统一聊天、流式聊天和 /api/ai/chat 都先经过这里。回复由模型完成函数写出。
同一 turn_id 的重复提交直接交回上一次结果，不重复执行。生成中断不会记成已完成。
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import threading
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

Complete = Callable[[Sequence[Mapping[str, str]]], str | Awaitable[str]]
_complete_override: Complete | None = None
_SYSTEM = (
    "你在回答同一个会话里的连续对话。只用中文直接回答最后一句，不要输出思考过程。"
    "只根据本会话按时间排列的用户原话。后一次明确纠正覆盖旧数字。"
    "如果、假设、模拟，以及要求暂时不要修改或只做风险分析的内容，只用于回答这一问，不改变已经确认的数字。"
    "用户没有给出的数字、角色、流程和结论不要编造。不知道就说明本会话没有这条信息。"
    "不要使用其他会话的数据。一句观察不要写成工单。"
)

_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()
_INFLIGHT: set[tuple[str, str]] = set()
_HARD_ERP = re.compile(
    r"(发货单|开单|打印标签|导入产品|导入数据库|导入到库|出库|"
    r"删除[\u4e00-\u9fffA-Za-z0-9]{0,12}(客户|产品|订单|记录))"
)
_NARRATIVE_STOCK = re.compile(r"(已经入库|入库后|本次入库|入库总|入库商品|每种入库)")
_HYPOTHETICAL = re.compile(r"(如果|假设|模拟|不要修改|只是模拟|暂时不要)")
_ERP_COMMAND = re.compile(r"(查一下|查询|帮我查|帮我删除|删除)")
_TICKET = re.compile(r"(提交|上报|反馈|建|创|登记).{0,12}(工单|缺陷)")
_CONFIRM = re.compile(r"^(确认|取消|好的|可以|同意|拒绝)[。.!！]?$")


def conversation_key(context: Mapping[str, Any] | None) -> str:
    raw = ""
    if context:
        raw = str(context.get("conversation_id") or context.get("session_id") or "")
    cleaned = re.sub(r"[^0-9A-Za-z_\-]", "", raw)[:80]
    return cleaned or "default"


def set_dialogue_complete(complete: Complete | None) -> None:
    """测试注入模型完成函数。生产路径不设置，走当前请求的模型客户端。"""
    global _complete_override
    _complete_override = complete


def should_answer_as_dialogue(message: str, context: Mapping[str, Any] | None) -> bool:
    """普通对话交给本会话模型和原话。开单、导入、删除、查库和明确建单仍走原链路。"""
    text = str(message or "").strip()
    if not text or _CONFIRM.match(text):
        return False
    if context and (context.get("excel_file_path") or context.get("excel_analysis")):
        return False
    if _TICKET.search(text):
        return False
    if _HARD_ERP.search(text) and not _HYPOTHETICAL.search(text):
        if not _NARRATIVE_STOCK.search(text):
            return False
    if _ERP_COMMAND.search(text) and not _HYPOTHETICAL.search(text):
        return False
    return True


def prepare_chat_turn(message: str, context: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """同一轮重复提交不再执行。进行中的轮次不会被另一条消息覆盖。"""
    key = conversation_key(context)
    turn_id = str((context or {}).get("turn_id") or "").strip()
    text = str(message or "").strip()
    with _lock(key):
        data = _read(key)
        if turn_id and (key, turn_id) in _INFLIGHT:
            return _payload("这一轮正在处理，不会重复执行。", "processing", replay=True)
        _close_abandoned(key, data)
        data = _read(key)
        if turn_id:
            prior = _user_turn(data, turn_id)
            if prior is not None and str(prior.get("content") or "") != text:
                return _payload(
                    "这一轮编号已经对应另一条消息，没有覆盖它，也没有再次执行。",
                    "failed",
                    replay=True,
                )
            assistant = _assistant_for(data, turn_id) if prior is not None else None
            if assistant is not None:
                stored = assistant.get("payload")
                if isinstance(stored, dict) and stored.get("response"):
                    return stored
                return _payload(str(assistant.get("content") or ""), str(assistant.get("status") or "failed"))
        if should_answer_as_dialogue(text, context):
            _append_user(data, text, turn_id, context)
        elif turn_id:
            data.setdefault("receipts", {})[turn_id] = {
                "message": text,
                "status": "processing",
                "at": time.time(),
            }
        if turn_id:
            _INFLIGHT.add((key, turn_id))
        _write(key, data)
        return None


def settle_chat_turn(
    message: str,
    context: Mapping[str, Any] | None,
    payload: Mapping[str, Any] | None,
    status: str,
) -> None:
    key = conversation_key(context)
    turn_id = str((context or {}).get("turn_id") or "").strip()
    text = str(message or "").strip()
    reply = ""
    if isinstance(payload, Mapping):
        reply = str(payload.get("response") or payload.get("message") or "")
    with _lock(key):
        data = _read(key)
        if turn_id and _assistant_for(data, turn_id):
            _INFLIGHT.discard((key, turn_id))
            return
        in_turns = any(
            item.get("role") == "user" and item.get("turn_id") == turn_id
            for item in data.get("turns") or []
        )
        if in_turns or (not turn_id and should_answer_as_dialogue(text, context)):
            data["active"] = True
            data["turns"].append(
                {
                    "role": "assistant",
                    "content": reply[:4000],
                    "turn_id": turn_id,
                    "status": status,
                    "at": time.time(),
                    "payload": _public_payload(payload, status),
                }
            )
        if turn_id:
            receipts = data.setdefault("receipts", {})
            receipts[turn_id] = {
                "message": text,
                "status": status,
                "at": time.time(),
                "payload": _public_payload(payload, status),
            }
            _INFLIGHT.discard((key, turn_id))
        _write(key, data)


async def dialogue_reply(message: str, context: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """把本会话用户原话交给模型完成函数。当前句已在 prepare 时入账。"""
    text = str(message or "").strip()
    if not should_answer_as_dialogue(text, context):
        return None
    loaded = _read(conversation_key(context))
    messages = _model_messages(loaded, str((context or {}).get("turn_id") or ""))
    try:
        reply = await _invoke_complete(messages)
    except RECOVERABLE_ERRORS as exc:
        return _payload(f"模型没有完成回复：{exc}", "failed", context)
    return _payload(str(reply or "").strip(), "completed", context)


def _model_messages(data: Mapping[str, Any], turn_id: str) -> list[dict[str, str]]:
    interrupted = any(
        item.get("role") == "assistant" and item.get("status") == "interrupted" and item.get("turn_id") != turn_id
        for item in data.get("turns") or []
        if isinstance(item, dict)
    )
    system = _SYSTEM
    if interrupted:
        system += "本会话有一轮生成中断，那一轮没有完成回复，不能把它当成已完成的分析。"
    messages = [{"role": "system", "content": system}]
    for item in data.get("turns") or []:
        if not isinstance(item, dict) or item.get("role") != "user":
            continue
        content = str(item.get("content") or "")
        names = [
            str(attachment.get("name"))
            for attachment in item.get("attachments") or []
            if isinstance(attachment, dict) and attachment.get("name")
        ]
        if names:
            content += "\n附件：" + "、".join(names)
        messages.append({"role": "user", "content": content})
    return messages


async def _invoke_complete(messages: Sequence[Mapping[str, str]]) -> str:
    complete = _complete_override or _desktop_complete
    result = complete(messages)
    if asyncio.iscoroutine(result):
        result = await result
    return str(result or "")


async def _desktop_complete(messages: Sequence[Mapping[str, str]]) -> str:
    """使用当前请求已经解析的桌面模型客户端。"""
    from app.infrastructure.llm.client import get_llm_client

    client = get_llm_client()
    if client is not None:
        model = getattr(client, "default_model", None)

        def call() -> str:
            result = client.chat.completions.create(
                messages=list(messages),
                model=model,
                temperature=0.2,
                max_tokens=1500,
            )
            return str(result.choices[0].message.content or "")

        return await asyncio.to_thread(call)
    from app.mod_sdk.mod_employee_llm import mod_employee_complete

    parsed = await mod_employee_complete(list(messages), max_tokens=1500, temperature=0.2)
    if not parsed.get("success"):
        raise RuntimeError(str(parsed.get("error") or "模型没有返回"))
    return str(parsed.get("content") or "")


def turn_status(key: str, turn_id: str) -> str:
    data = _read(key)
    assistant = _assistant_for(data, turn_id)
    if assistant:
        return str(assistant.get("status") or "")
    if (key, turn_id) in _INFLIGHT:
        return "processing"
    prior = _user_turn(data, turn_id)
    if prior is None:
        return ""
    return "interrupted"


def _payload(
    reply: str, status: str, context: Mapping[str, Any] | None = None, *, replay: bool = False
) -> dict[str, Any]:
    attachments = []
    if context:
        raw = context.get("multimodal_attachments") or context.get("attachments") or []
        if isinstance(raw, list):
            attachments = raw
    body = {
        "success": status == "completed",
        "message": {
            "completed": "处理完成",
            "processing": "处理中",
            "failed": "失败",
            "interrupted": "中断",
        }.get(status, status),
        "response": reply,
        "data": {
            "text": reply,
            "action": "dialogue_memory",
            "status": status,
            "replay": replay,
            "data": {
                "intent": "dialogue_memory",
                "status": status,
                "attachments": attachments,
            },
        },
    }
    return body


def _public_payload(payload: Mapping[str, Any] | None, status: str) -> dict[str, Any]:
    if isinstance(payload, Mapping) and payload.get("response"):
        copied = json.loads(json.dumps(payload, ensure_ascii=False, default=str))
        data = copied.get("data")
        if isinstance(data, dict):
            data["status"] = status
        return copied
    return _payload(str((payload or {}).get("response") or ""), status)


def _append_user(
    data: dict[str, Any], text: str, turn_id: str, context: Mapping[str, Any] | None
) -> None:
    data["active"] = True
    attachments = []
    if context:
        raw = context.get("multimodal_attachments") or context.get("attachments") or []
        if isinstance(raw, list):
            attachments = raw
    data["turns"].append(
        {
            "role": "user",
            "content": text[:8000],
            "turn_id": turn_id,
            "status": "accepted",
            "at": time.time(),
            "attachments": attachments,
        }
    )


def _close_abandoned(key: str, data: dict[str, Any]) -> None:
    turns = data.get("turns") or []
    changed = False
    index = 0
    while index < len(turns):
        item = turns[index]
        if item.get("role") == "user" and item.get("turn_id") and (key, item["turn_id"]) not in _INFLIGHT:
            if _assistant_for(data, str(item["turn_id"])) is None:
                turns.insert(
                    index + 1,
                    {
                        "role": "assistant",
                        "content": "生成中断，没有完成回复。未完成的内容不能当成已完成的分析。",
                        "turn_id": item["turn_id"],
                        "status": "interrupted",
                        "at": time.time(),
                        "payload": _payload(
                            "生成中断，没有完成回复。未完成的内容不能当成已完成的分析。",
                            "interrupted",
                        ),
                    },
                )
                changed = True
                index += 1
        index += 1
    if changed:
        _write(key, data)


def _user_turn(data: dict[str, Any], turn_id: str) -> dict[str, Any] | None:
    if not turn_id:
        return None
    for item in data.get("turns") or []:
        if item.get("role") == "user" and item.get("turn_id") == turn_id:
            return item
    receipt = (data.get("receipts") or {}).get(turn_id)
    if isinstance(receipt, dict):
        return {"role": "user", "content": receipt.get("message"), "turn_id": turn_id}
    return None


def _assistant_for(data: dict[str, Any], turn_id: str) -> dict[str, Any] | None:
    if not turn_id:
        return None
    for item in data.get("turns") or []:
        if item.get("role") == "assistant" and item.get("turn_id") == turn_id:
            return item
    receipt = (data.get("receipts") or {}).get(turn_id)
    if isinstance(receipt, dict) and receipt.get("status") in {"completed", "failed", "interrupted"}:
        return receipt
    return None


def _memory_dir() -> Path:
    override = os.environ.get("XCAGI_DIALOGUE_MEMORY_DIR", "").strip()
    if override:
        root = Path(override)
    else:
        from app.desktop_runtime.desktop_runtime_paths import get_desktop_data_dir

        root = get_desktop_data_dir() / "dialogue-memory"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _path(key: str) -> Path:
    return _memory_dir() / f"{key}.json"


def _read(key: str) -> dict[str, Any]:
    path = _path(key)
    if not path.is_file():
        return {"active": False, "turns": [], "receipts": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except RECOVERABLE_ERRORS:
        return {"active": False, "turns": [], "receipts": {}}
    if not isinstance(data, dict):
        return {"active": False, "turns": [], "receipts": {}}
    turns = data.get("turns") if isinstance(data.get("turns"), list) else []
    receipts = data.get("receipts") if isinstance(data.get("receipts"), dict) else {}
    return {"active": bool(data.get("active")), "turns": turns, "receipts": receipts}


def _write(key: str, data: dict[str, Any]) -> None:
    turns = data.get("turns") or []
    if len(turns) > 800:
        data["turns"] = turns[-800:]
    path = _path(key)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def _lock(key: str) -> threading.Lock:
    with _LOCKS_GUARD:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _LOCKS[key] = lock
        return lock


__all__ = [
    "conversation_key",
    "dialogue_reply",
    "prepare_chat_turn",
    "set_dialogue_complete",
    "settle_chat_turn",
    "should_answer_as_dialogue",
    "turn_status",
]
