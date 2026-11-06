"""Per-conversation confirmed facts. The model cannot overwrite them.

Hypothesis text is reported and then discarded. A correction or undo changes
only the confirmed value the user named. Other conversations, users, and
tenants never see this state.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from typing import Any, Mapping

from app.application.ai_chat.dialogue_arbitration import (
    is_dialogue_fact_message,
    is_explicit_enterprise_customer_query,
)
from app.application.ai_chat.dialogue_memory import _memory_dir, conversation_key
from app.utils.operational_errors import RECOVERABLE_ERRORS

_FIELDS = {
    "客户.总数": ("客户", "总数"),
    "客户.A类": ("客户", "A类"),
    "客户.B类": ("客户", "B类"),
    "合同.总额": ("合同", "总额"),
    "会话.标记": ("会话", "标记"),
}


def try_confirmed_fact_reply(
    message: str, context: Mapping[str, Any] | None
) -> dict[str, Any] | None:
    text = _normalize(message)
    if (
        not text
        or is_explicit_enterprise_customer_query(text)
        or not is_dialogue_fact_message(text)
    ):
        return None
    key = conversation_key(context)
    if not key:
        return None
    turn_id = str((context or {}).get("turn_id") or "").strip()
    state = _read(key)
    if turn_id and turn_id in state["applied"]:
        return _public(state["applied"][turn_id], state, context)
    operation = _operation(text)
    if operation is None:
        return None
    reply = _apply(
        state, operation, text, turn_id, str((context or {}).get("conversation_id") or "")
    )
    if turn_id:
        state["applied"][turn_id] = reply
    _write(key, state)
    return _public(reply, state, context)


def confirmed_continuity_reply(context: Mapping[str, Any] | None) -> dict[str, str] | None:
    """Keep the confirmed ledger when smalltalk would otherwise greet a new user."""
    key = conversation_key(context)
    if not key:
        return None
    reply = _render(_read(key), "已确认")
    if reply == "本会话没有已确认的这条信息。":
        return None
    return {
        "response": reply,
        "text": reply,
        "thinking_steps": "[已确认事实：继续当前会话]",
        "action": "confirmed_facts",
        "trace_intent": "confirmed_facts",
    }


def fact_context_line(context: Mapping[str, Any] | None) -> str:
    key = conversation_key(context)
    if not key:
        return ""
    facts = _read(key)["facts"]
    if not facts:
        return ""
    shown = "；".join(
        f"{item['object']}.{item['field']}={item['value']}"
        for item in facts.values()
        if item.get("status") == "confirmed"
    )
    return "本会话已确认事实（假设和未确认的话不能改这些值）：" + shown


def _operation(text: str) -> str | None:
    if re.search(r"撤销", text) and "合同" in text:
        return "undo_contract"
    if re.search(r"撤销", text):
        return "undo"
    if re.search(r"恢复(?:到)?最初|恢复基线|恢复原来|恢复原始", text):
        return "restore"
    if re.search(r"假设|如果|暂时不要|不要修改|只做风险", text):
        return "hypothesis"
    if re.search(r"更正|改正|纠正", text):
        return "correction"
    if re.search(r"增加|减少", text):
        return "delta"
    if _absolute(text) or re.search(r"记下|记住", text):
        return "establish"
    if re.search(r"多少|是什么|是多少|再问|实际|已确认", text):
        return "ask"
    return None


def _apply(
    state: dict[str, Any], operation: str, text: str, turn_id: str, conversation_id: str
) -> str:
    if operation == "undo":
        return _undo(state, conversation_id, turn_id, None)
    if operation == "undo_contract":
        return _undo(state, conversation_id, turn_id, "合同.总额")
    if operation == "restore":
        return _restore(state, conversation_id, turn_id)
    if operation == "hypothesis":
        return _hypothesis(state, text)
    if operation == "correction":
        return _correction(state, text, conversation_id, turn_id)
    if operation == "delta":
        return _delta(state, text, conversation_id, turn_id)
    if operation == "establish":
        return _establish(state, text, conversation_id, turn_id)
    return _render(state, "已确认")


def _establish(state: dict[str, Any], text: str, conversation_id: str, turn_id: str) -> str:
    found = _absolute(text)
    if not found:
        return _render(state, "已确认")
    before = _current_map(state)
    for fact_id, value in found.items():
        _put(state, fact_id, value, conversation_id, turn_id)
    if "客户.总数" in found and not state["baseline"]:
        state["baseline"] = {
            fact_id: state["facts"][fact_id]["value"]
            for fact_id in ("客户.总数", "客户.A类", "客户.B类")
            if fact_id in state["facts"]
        }
    _push(state, "establish", "客户", before, turn_id, {})
    return _render(state, "已确认")


def _delta(state: dict[str, Any], text: str, conversation_id: str, turn_id: str) -> str:
    delta = _deltas(text)
    if not delta:
        return "本会话还没有可以增减的已确认数字。"
    before = _current_map(state)
    for fact_id, amount in delta.items():
        current = int(before.get(fact_id) or 0)
        _put(state, fact_id, current + amount, conversation_id, turn_id)
    _push(state, "delta", "客户", before, turn_id, delta)
    return _render(state, "已确认")


def _correction(state: dict[str, Any], text: str, conversation_id: str, turn_id: str) -> str:
    delta = _deltas(text)
    origin = None
    for revision in reversed(state["revisions"]):
        if revision.get("kind") == "delta" and revision.get("object") == "客户":
            origin = revision.get("before") or {}
            break
    if origin is None or not delta:
        return "没有找到可以更正的上一次客户数量修改。"
    before = _current_map(state)
    for fact_id, amount in delta.items():
        base = int(origin.get(fact_id) or 0)
        _put(state, fact_id, base + amount, conversation_id, turn_id)
    _push(state, "correction", "客户", before, turn_id, delta)
    return _render(state, "已更正并确认")


def _hypothesis(state: dict[str, Any], text: str) -> str:
    imagined = _current_map(state)
    if "合同" in text and not re.search(r"客户|[AB]类", text):
        money = _money(text)
        if money is None:
            return "无法计算。已确认未改：" + _render(state, "")
        imagined["合同.总额"] = money
        return f"假设结果：合同总额{money}万元。已确认未改：" + _render(state, "")
    for fact_id, amount in _deltas(text).items():
        imagined[fact_id] = int(imagined.get(fact_id) or 0) + amount
    money = _money(text)
    if money is not None and "合同" in text:
        imagined["合同.总额"] = money
    return "假设结果：" + _render_map(imagined) + "。已确认未改：" + _render(state, "")


def _restore(state: dict[str, Any], conversation_id: str, turn_id: str) -> str:
    if not state["baseline"]:
        return "本会话没有可恢复的客户基线。"
    before = _current_map(state)
    for fact_id, value in state["baseline"].items():
        _put(state, fact_id, value, conversation_id, turn_id)
    _push(state, "restore", "客户", before, turn_id, {})
    return _render(state, "已恢复基线")


def _undo(state: dict[str, Any], conversation_id: str, turn_id: str, only: str | None) -> str:
    index = None
    for cursor in range(len(state["revisions"]) - 1, -1, -1):
        revision = state["revisions"][cursor]
        before = revision.get("before") or {}
        if only is None or only in before or only in (revision.get("after") or {}):
            index = cursor
            break
    if index is None:
        return "没有可撤销的已确认修改。" + _render(state, "已确认")
    revision = state["revisions"].pop(index)
    for fact_id, value in (revision.get("before") or {}).items():
        if only and fact_id != only:
            continue
        _put(
            state,
            fact_id,
            value,
            conversation_id,
            turn_id,
            undo_link=str(revision.get("revision_id") or ""),
        )
    return _render(state, "已撤销")


def _put(
    state: dict[str, Any],
    fact_id: str,
    value: Any,
    conversation_id: str,
    turn_id: str,
    *,
    undo_link: str | None = None,
) -> None:
    obj, field = _FIELDS[fact_id]
    prior = state["facts"].get(fact_id)
    state["facts"][fact_id] = {
        "fact_id": fact_id,
        "conversation_id": conversation_id,
        "object": obj,
        "field": field,
        "value": value,
        "prior_value": None if prior is None else prior.get("value"),
        "source_turn_id": turn_id,
        "status": "confirmed",
        "modified_at": time.time(),
        "undo_link": undo_link or (None if prior is None else prior.get("fact_id")),
    }


def _push(
    state: dict[str, Any],
    kind: str,
    obj: str,
    before: dict[str, Any],
    turn_id: str,
    delta: dict[str, int],
) -> None:
    after = _current_map(state)
    state["revisions"].append(
        {
            "revision_id": uuid.uuid4().hex,
            "kind": kind,
            "object": obj,
            "turn_id": turn_id,
            "before": dict(before),
            "after": after,
            "delta": delta,
            "at": time.time(),
        }
    )


def _absolute(text: str) -> dict[str, Any]:
    found: dict[str, Any] = {}
    total = re.search(r"客户总数(?:是|为|有|：|:)?\s*(\d+)", text)
    if total and not re.search(r"增加|减少|更正", text):
        found["客户.总数"] = int(total.group(1))
    if not re.search(r"增加|减少|更正", text):
        for letter in ("A", "B"):
            match = re.search(rf"{letter}类(?:客户)?(?:是|为|有|：|:)?\s*(\d+)", text)
            if match:
                found[f"客户.{letter}类"] = int(match.group(1))
    money = _money(text)
    if money is not None and not re.search(r"假设|暂时不要|不要修改", text):
        found["合同.总额"] = money
    marker = re.search(r"(?:会话)?标记(?:是|为|：|:)?\s*([0-9A-Za-z\u4e00-\u9fff]+-\d+)", text)
    if marker and "假设" not in text:
        found["会话.标记"] = marker.group(1)
    return found


def _deltas(text: str) -> dict[str, int]:
    delta: dict[str, int] = {}
    for letter in ("A", "B"):
        match = re.search(rf"{letter}类(?:客户)?(?:再)?(增加|新增|减少)\s*(\d+)", text)
        if match:
            sign = -1 if match.group(1) == "减少" else 1
            delta[f"客户.{letter}类"] = sign * int(match.group(2))
            continue
        plain = re.search(rf"{letter}类(?:客户)?\s*(\d+)", text)
        if plain and re.search(r"增加|更正|减少", text):
            delta[f"客户.{letter}类"] = int(plain.group(1))
    total = re.search(r"(?:增加|新增)\s*(\d+)\s*(?:个|家)?\s*客户", text)
    if total:
        delta["客户.总数"] = int(total.group(1))
    elif any(key.startswith("客户.") and key != "客户.总数" for key in delta):
        delta["客户.总数"] = sum(amount for key, amount in delta.items() if key != "客户.总数")
    return delta


def _money(text: str) -> int | None:
    match = re.search(r"(\d+)\s*万元", text)
    return int(match.group(1)) if match else None


def _current_map(state: dict[str, Any]) -> dict[str, Any]:
    return {fact_id: item.get("value") for fact_id, item in state["facts"].items()}


def _render(state: dict[str, Any], prefix: str) -> str:
    body = _render_map(_current_map(state))
    if not body:
        return "本会话没有已确认的这条信息。"
    return f"{prefix}：{body}" if prefix else body


def _render_map(values: Mapping[str, Any]) -> str:
    customer = []
    if values.get("客户.总数") is not None:
        customer.append(f"客户总数{values['客户.总数']}")
    if values.get("客户.A类") is not None:
        customer.append(f"A类{values['客户.A类']}")
    if values.get("客户.B类") is not None:
        customer.append(f"B类{values['客户.B类']}")
    tail = []
    if values.get("合同.总额") is not None:
        tail.append(f"合同总额{values['合同.总额']}万元")
    if values.get("会话.标记"):
        tail.append(f"会话标记{values['会话.标记']}")
    return "。".join(part for part in ("，".join(customer), "，".join(tail)) if part)


def _public(reply: str, state: dict[str, Any], context: Mapping[str, Any] | None) -> dict[str, Any]:
    facts = list(state["facts"].values())
    body = {
        "success": True,
        "message": "处理完成",
        "response": reply,
        "data": {
            "text": reply,
            "action": "confirmed_facts",
            "status": "completed",
            "facts": facts,
            "conversation_id": str((context or {}).get("conversation_id") or ""),
            "data": {"intent": "confirmed_facts", "facts": facts},
        },
    }
    return body


def _normalize(message: str) -> str:
    return str(message or "").translate(str.maketrans("０１２３４５６７８９", "0123456789")).strip()


def _empty() -> dict[str, Any]:
    return {"facts": {}, "baseline": {}, "revisions": [], "applied": {}}


def _path(key: str):
    return _memory_dir() / f"{key}-facts.json"


def _read(key: str) -> dict[str, Any]:
    path = _path(key)
    if not path.is_file():
        return _empty()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except RECOVERABLE_ERRORS:
        return _empty()
    if not isinstance(data, dict):
        return _empty()
    facts = data.get("facts") if isinstance(data.get("facts"), dict) else {}
    revisions = data.get("revisions") if isinstance(data.get("revisions"), list) else []
    applied = data.get("applied") if isinstance(data.get("applied"), dict) else {}
    baseline = data.get("baseline") if isinstance(data.get("baseline"), dict) else {}
    return {"facts": facts, "baseline": baseline, "revisions": revisions, "applied": applied}


def _write(key: str, state: dict[str, Any]) -> None:
    path = _path(key)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)
