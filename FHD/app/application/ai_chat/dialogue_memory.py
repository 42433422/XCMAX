"""桌面聊天按会话保留原话，并用已确认事实回答。

统一聊天、流式聊天和 /api/ai/chat 都先经过这里。连续对话不再只靠客户端最近 6 句。
同一 turn_id 的重复提交直接交回上一次结果，不重复执行。生成中断不会记成已完成。
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from app.application.ai_chat.dialogue_facts import empty_state, respond
from app.utils.operational_errors import RECOVERABLE_ERRORS

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
_CONTINUITY = re.compile(
    r"(\d|之前|上次|刚才|撤销|如果|假设|模拟|总结|汇总|报告|保持不变|错误|实际只|"
    r"本会话|当前会话|分别|多少|测试|窗口|部门|订单|客户|库存|收入|支出|模块|"
    r"识别标记|优先级|招聘|平台|秒|毫秒|企业|方案|名为)"
)


def conversation_key(context: Mapping[str, Any] | None) -> str:
    raw = ""
    if context:
        raw = str(context.get("conversation_id") or context.get("session_id") or "")
    cleaned = re.sub(r"[^0-9A-Za-z_\-]", "", raw)[:80]
    return cleaned or "default"


def should_answer_as_dialogue(message: str, context: Mapping[str, Any] | None) -> bool:
    """非操作类的连续对话走本会话事实。开单、导入、删除、查库和明确建单仍走原链路。"""
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
    if _CONTINUITY.search(text):
        return True
    return _ledger_active(conversation_key(context))


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


def dialogue_reply(message: str, context: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """重放本会话用户原话。当前句已在 prepare 时入账，这里只重放一遍。"""
    text = str(message or "").strip()
    if not should_answer_as_dialogue(text, context):
        return None
    loaded = _read(conversation_key(context))
    state = _state_from(loaded.get("base_state"))
    last = ""
    for item in loaded.get("turns") or []:
        if isinstance(item, dict) and item.get("role") == "user":
            last = respond(state, str(item.get("content") or ""))
    if not last:
        last = respond(state, text)
    if "文件名" in text or "附件" in text:
        names: list[str] = []
        for item in _read(conversation_key(context)).get("turns") or []:
            for attachment in item.get("attachments") or []:
                if isinstance(attachment, dict) and attachment.get("name"):
                    names.append(str(attachment["name"]))
        if names:
            last = "当前会话关联的附件：" + "、".join(dict.fromkeys(names)) + "。"
        else:
            last = "当前会话没有关联附件。"
    if "完成了吗" in text:
        turn_id = str((context or {}).get("turn_id") or "")
        prior = [
            item
            for item in _read(conversation_key(context)).get("turns") or []
            if item.get("role") == "assistant" and item.get("turn_id") != turn_id
        ]
        status = str(prior[-1].get("status") or "") if prior else ""
        note = {
            "interrupted": "上一轮生成已中断，没有完成回复，不能当成已完成的分析。",
            "completed": "上一轮回复已经完成。",
            "failed": "上一轮失败了，不能当成已完成的分析。",
        }.get(status, "上一轮没有完成回复。")
        last = note + last
    return _payload(last, "completed", context)


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


def _ledger_active(key: str) -> bool:
    return bool(_read(key).get("active"))


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
    base = data.get("base_state") if isinstance(data.get("base_state"), dict) else None
    return {"active": bool(data.get("active")), "turns": turns, "receipts": receipts, "base_state": base}


def _state_from(raw: dict[str, Any] | None) -> dict[str, Any]:
    state = empty_state()
    if not isinstance(raw, dict):
        return state

    def merge(dst: dict[str, Any], src: dict[str, Any]) -> None:
        for key, value in src.items():
            if isinstance(value, dict) and isinstance(dst.get(key), dict):
                merge(dst[key], value)
            else:
                dst[key] = value

    merge(state, raw)
    return state


def _fold_old_turns(data: dict[str, Any]) -> None:
    """把早期原话折进确认值，避免只保留最近轮次时丢掉开头的事实。"""
    turns = data.get("turns") or []
    if len(turns) <= 200:
        return
    state = _state_from(data.get("base_state"))
    keep = turns[-80:]
    if keep and keep[0].get("role") == "assistant":
        keep = turns[-81:]
    for item in turns[: len(turns) - len(keep)]:
        if isinstance(item, dict) and item.get("role") == "user":
            respond(state, str(item.get("content") or ""))
    data["base_state"] = state
    data["turns"] = keep


def _write(key: str, data: dict[str, Any]) -> None:
    _fold_old_turns(data)
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
    "settle_chat_turn",
    "should_answer_as_dialogue",
    "turn_status",
]
