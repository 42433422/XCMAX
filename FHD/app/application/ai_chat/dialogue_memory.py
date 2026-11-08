"""桌面聊天按会话保留用户原话，并把这些原话交给当前请求的模型。

统一聊天、流式聊天和 /api/ai/chat 都先经过这里。回复由模型完成函数写出。
同一 turn_id 的重复提交直接交回上一次结果，不重复执行。生成中断不会记成已完成。
"""

from __future__ import annotations

import asyncio
import hashlib
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
    "你在回答同一个会话里的连续对话。只用中文回答，不要输出思考过程。需要两句时不要并成一句。"
    "只根据本会话按时间排列的全部用户原话。连续重复的同一句只计一次。"
    "后一次明确纠正覆盖它点名的旧数字。已经被纠正替换掉的旧数字和旧总数不能再当成当前值，也不能再拿来相加。"
    "每一句增加都要加到该对象当时的人数或数量上，后面继续用加完的数。"
    "后一句只否定其中一次增加、并给出实际增加数时，只替换那一次，其他已经加上的增加仍然保留。"
    "保持不变表示不要再改这个对象，不是把它退回最初数字。"
    "数字、合计、假设或纠正才写算式，算式只用这一问真正用到的原话数字。不要另算没有被问到的乘积。"
    "如果、假设、模拟，以及要求暂时不要修改或只做风险分析的句子，不改变已经确认的数字。"
    "这种句子的同一条回复分成两句：第一句只写按这句算出的结果；第二句只写这次没有改动的已确认数字，并写明这些确认数字没有被这句假设替换。"
    "不要写在已确认数字上叠加。某个合计需要的数字用户没有给过，就写无法计算，不要把缺少的项当成 0，也不要用另一个旧总数把这问答完。"
    "用户没有给出的数字、角色、流程和结论不要编造。不知道就说明本会话没有这条信息。"
    "不要使用其他会话的数据。一句观察不要写成工单。"
)

_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()
_INFLIGHT: set[tuple[str, str]] = set()
_FINAL_STATUSES = frozenset({"completed", "failed", "cancelled", "rejected"})
_HARD_ERP = re.compile(
    r"(发货单|开单|打印标签|导入产品|导入数据库|导入到库|出库|"
    r"删除[\u4e00-\u9fffA-Za-z0-9]{0,12}(客户|产品|订单|记录))"
)
_NARRATIVE_STOCK = re.compile(r"(已经入库|入库后|本次入库|入库总|入库商品|每种入库)")
_HYPOTHETICAL = re.compile(r"(如果|假设|模拟|不要修改|只是模拟|暂时不要)")
_WHAT_IF = re.compile(r"(如果|假设|只是模拟|暂时不要修改|不要修改实际)")
_UNDO = re.compile(r"(撤销|恢复到|恢复原来|恢复原始)")
_REVISE_WHAT_IF = (
    "请只重写你刚写的回复，仍然只根据本会话的用户原话，不要新增用户没说过的数字。"
    "第一句先写加法，等号两边必须相等。第二句以「已确认未改：」开头，写出同一对象的总数和分类数，并重复算式里的基数。"
    "缺了必要数字就第一句只写无法计算，不要把其余数字补成这个合计。"
)
_REVISE_UNDO = (
    "请只重写你刚写的回复。这是撤销或恢复。"
    "只写恢复之后的已确认数字。不要把被撤销的演算结果写成当前值，也不要写「已确认未改」。"
)
_ERP_COMMAND = re.compile(r"(查一下|查询|帮我查|帮我删除|删除)")
_TICKET = re.compile(r"(提交|上报|反馈|建|创|登记).{0,12}(工单|缺陷)")
_CONFIRM = re.compile(r"^(确认|取消|好的|可以|同意|拒绝)[。.!！]?$")


def conversation_key(context: Mapping[str, Any] | None) -> str:
    from app.application.task_conversation_store import durable_user_id

    context = context or {}
    raw = str(context.get("conversation_id") or context.get("session_id") or "").strip()
    owner = durable_user_id(context.get("local_user_id") or context.get("actor_id"))
    if owner is None or not raw:
        return ""
    scope = [str(owner), str(context.get("tenant_id") or ""), str(context.get("mod_id") or ""), raw]
    return hashlib.sha256(json.dumps(scope, ensure_ascii=False).encode()).hexdigest()


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
        from app.application.ai_chat.dialogue_arbitration import is_dialogue_fact_message

        if not is_dialogue_fact_message(text):
            return False
    return True


def prepare_chat_turn(message: str, context: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """同一轮重复提交不再执行。进行中的轮次不会被另一条消息覆盖。"""
    key = conversation_key(context)
    if not key:
        return None
    turn_id = str((context or {}).get("turn_id") or "").strip()
    text = str(message or "").strip()
    with _lock(key):
        data = _read(key)
        prior = _user_turn(data, turn_id)
        if prior is not None and str(prior.get("content") or "") != text:
            return _payload(
                "这一轮编号已经对应另一条消息，没有覆盖它，也没有再次执行。", "failed", replay=True
            )
        if turn_id and (key, turn_id) in _INFLIGHT:
            return _payload("这一轮正在处理，不会重复执行。", "processing", replay=True)
        _close_abandoned(key, data)
        data = _read(key)
        if turn_id:
            prior = _user_turn(data, turn_id)
            assistant = _assistant_for(data, turn_id) if prior is not None else None
            if assistant is not None:
                stored = assistant.get("payload")
                if isinstance(stored, dict):
                    details = stored.get("data")
                    return {
                        **stored,
                        "data": {**(details if isinstance(details, dict) else {}), "replay": True},
                    }
                return _payload(
                    str(assistant.get("content") or ""), str(assistant.get("status") or "failed")
                )
        if should_answer_as_dialogue(text, context):
            _append_user(data, text, turn_id, context)
        if turn_id:
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
    if not key:
        return
    turn_id = str((context or {}).get("turn_id") or "").strip()
    text = str(message or "").strip()
    reply = ""
    if isinstance(payload, Mapping):
        reply = str(payload.get("response") or payload.get("message") or "")
    with _lock(key):
        data = _read(key)
        prior = _user_turn(data, turn_id)
        if prior is not None and str(prior.get("content") or "") != text:
            raise ValueError("turn_id 已绑定另一条消息")
        previous = _assistant_for(data, turn_id)
        if previous and previous.get("status") in _FINAL_STATUSES:
            _INFLIGHT.discard((key, turn_id))
            return
        previous_payload = previous.get("payload") if previous else None
        if isinstance(previous_payload, Mapping) and isinstance(payload, Mapping):
            previous_run = previous_payload.get("run_id") or previous_payload.get("agent_run_id")
            current_run = payload.get("run_id") or payload.get("agent_run_id")
            if previous_run and previous_run != current_run:
                raise ValueError("turn_id 不能切换到另一项执行")
        receipt = {
            "role": "assistant",
            "content": reply[:4000],
            "turn_id": turn_id,
            "status": status,
            "at": time.time(),
            "payload": _public_payload(payload, status),
        }
        in_turns = any(
            item.get("role") == "user" and item.get("turn_id") == turn_id
            for item in data.get("turns") or []
        )
        if in_turns or (not turn_id and should_answer_as_dialogue(text, context)):
            data["active"] = True
            stored = next(
                (
                    item
                    for item in data["turns"]
                    if turn_id
                    and item.get("role") == "assistant"
                    and item.get("turn_id") == turn_id
                ),
                None,
            )
            if stored is None:
                data["turns"].append(receipt)
            else:
                stored.update(receipt)
        if turn_id:
            receipts = data.setdefault("receipts", {})
            receipts[turn_id] = {**receipt, "message": text}
            _INFLIGHT.discard((key, turn_id))
        _write(key, data)


async def dialogue_reply(message: str, context: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """把本会话用户原话交给模型完成函数。当前句已在 prepare 时入账。"""
    text = str(message or "").strip()
    if not should_answer_as_dialogue(text, context):
        return None
    messages = _request_messages(text, context)
    try:
        reply = await _invoke_complete(messages)
        revise = (
            _REVISE_UNDO if _UNDO.search(text) else _REVISE_WHAT_IF if _WHAT_IF.search(text) else ""
        )
        if revise:
            try:
                reply = await _invoke_complete(
                    [
                        *messages,
                        {"role": "assistant", "content": str(reply or "")},
                        {"role": "user", "content": revise},
                    ]
                )
            except RECOVERABLE_ERRORS:
                pass
    except RECOVERABLE_ERRORS as exc:
        return _payload(f"模型没有完成回复：{exc}", "failed", context)
    return _payload(str(reply or "").strip(), "completed", context)


def _request_messages(text: str, context: Mapping[str, Any] | None) -> list[dict[str, str]]:
    key = conversation_key(context)
    loaded = _read(key) if key else {"turns": []}
    if not key:
        _append_user(loaded, text, "", context)
    return _model_messages(loaded, str((context or {}).get("turn_id") or ""))


def enrich_model_messages(
    messages: list[dict[str, Any]],
    message: str,
    context: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    """Add owned transcript to the existing model turn without replacing its execution chain."""
    if not conversation_key(context) or not should_answer_as_dialogue(message, context):
        return messages
    memory = _request_messages(message, context)
    # The current model message may contain images or tool protocol fields; preserve it.
    history = memory[1:]
    if history and history[-1].get("content") == message.strip():
        history = history[:-1]
    from app.application.ai_chat.confirmed_facts import fact_context_line

    fact_line = fact_context_line(context)
    if fact_line:
        messages = [messages[0], {"role": "system", "content": fact_line}, *messages[1:]]
    if not history:
        return messages
    return [
        *messages[:-1],
        {"role": "system", "content": memory[0]["content"]},
        *history,
        messages[-1],
    ]


def _model_messages(data: Mapping[str, Any], turn_id: str) -> list[dict[str, str]]:
    interrupted = any(
        item.get("role") == "assistant"
        and item.get("status") == "interrupted"
        and item.get("turn_id") != turn_id
        for item in data.get("turns") or []
        if isinstance(item, dict)
    )
    system = _SYSTEM
    if interrupted:
        system += "本会话有一轮生成中断，那一轮没有完成回复，不能把它当成已完成的分析。"
    user_turns = [
        item
        for item in data.get("turns") or []
        if isinstance(item, dict) and item.get("role") == "user"
    ]
    last_user = str(user_turns[-1].get("content") or "") if user_turns else ""
    if _WHAT_IF.search(last_user):
        system += (
            "最后一句是假设或要求暂时不要修改。回复固定两句。"
            "第一句先写加法，等号两边必须相等，基数必须来自用户原话或其逐步相加的结果，不要另起一个没出现过的基数。"
            "第二句以「已确认未改：」开头，写出同一对象上的总数和分类数，"
            "并且把第一句算式里的基数再写一遍。只写第一句算没答完。"
            "如果缺了必要数字，第一句只写无法计算，第二句不要把其余数字补成这个合计。"
        )
    if _UNDO.search(last_user):
        system += (
            "最后一句是在撤销或恢复。当前值改回这次撤销之前最后一次确认的数字。"
            "不要把刚被撤销的演算结果写成当前值。"
        )
    messages = [{"role": "system", "content": system}]
    for item in user_turns:
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
                messages=[dict(item) for item in messages],
                model=model,
                temperature=0,
                max_tokens=1500,
            )
            return str(result.choices[0].message.content or "")

        return await asyncio.to_thread(call)
    from app.mod_sdk.mod_employee_llm import mod_employee_complete

    parsed = await mod_employee_complete(
        [dict(item) for item in messages], max_tokens=1500, temperature=0
    )
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
            "waiting_approval": "等待授权",
            "unknown": "等待核对",
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
    if isinstance(payload, Mapping):
        copied = json.loads(json.dumps(payload, ensure_ascii=False, default=str))
        data = copied.get("data")
        copied["data"] = {**(data if isinstance(data, dict) else {}), "status": status}
        copied["execution_state"] = status
        copied.setdefault("response", str(copied.get("message") or ""))
        return dict(copied)
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
        if (
            item.get("role") == "user"
            and item.get("turn_id")
            and (key, item["turn_id"]) not in _INFLIGHT
        ):
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
    receipt = (data.get("receipts") or {}).get(turn_id)
    if isinstance(receipt, dict):
        return {"role": "user", "content": receipt.get("message"), "turn_id": turn_id}
    for item in data.get("turns") or []:
        if item.get("role") == "user" and item.get("turn_id") == turn_id:
            return dict(item)
    return None


def _assistant_for(data: dict[str, Any], turn_id: str) -> dict[str, Any] | None:
    if not turn_id:
        return None
    for item in data.get("turns") or []:
        if item.get("role") == "assistant" and item.get("turn_id") == turn_id:
            return dict(item)
    receipt = (data.get("receipts") or {}).get(turn_id)
    if isinstance(receipt, dict) and isinstance(receipt.get("payload"), dict):
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
    turns = (
        [item for item in data.get("turns", []) if isinstance(item, dict)]
        if isinstance(data.get("turns"), list)
        else []
    )
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
