"""按会话保留用户原话，并据此回答连续对话。

普通聊天只把最近几句交给规划器。规划器会把「记住、纠正、假设、撤销」
误当成业务工具。这里把同一会话的用户原话落在桌面数据目录，重启后仍在，
回答时整份底稿进入系统提示，后说的纠正覆盖旧数字，假设和模拟不改已确认数据。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import threading
import time
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)
_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()
_DEDUP_SEC = 3.0
_USER_CAP = 1600
_ASSISTANT_CAP = 360
_PROMPT_USER_CHARS = 14000

_HARD_ERP = re.compile(
    r"(发货单|开单|打印标签|导入产品|导入数据库|导入到库|入库|出库|"
    r"删除[\u4e00-\u9fffA-Za-z0-9]{0,12}(客户|产品|订单|记录))"
)
# 连续对话里的「已经入库 / 入库后」是在记账，不是在执行入库单。
_NARRATIVE_STOCK = re.compile(r"(已经入库|入库后|本次入库|入库总|入库商品|每种入库)")
_HYPOTHETICAL = re.compile(r"(如果|假设|模拟|不要修改|只是模拟|暂时不要|测试)")
_SCENARIO = re.compile(
    r"(稳定性测试|测试方案|测试范围|测试项目|识别标记|星河科技|"
    r"窗口|撤销|不要修改|保持不变|暂时不要|只是模拟|如果|假设|"
    r"错误的|调整为|恢复原来|招聘|缺货|活跃客户|之前的对话|上次对话|"
    r"本会话|当前会话)"
)
_CONFIRM = re.compile(r"^(确认|取消|好的|可以|同意|拒绝)[。.!！]?$")
# 叙述里出现「客户」不等于要查库。只有明确的查询或删除口令才离开底稿。
_ERP_COMMAND = re.compile(r"(查一下|查询|帮我查|帮我删除|删除)")

Complete = Callable[[list[dict[str, str]]], Awaitable[str]]


def conversation_key(context: Mapping[str, Any] | None) -> str:
    raw = ""
    if context:
        raw = str(context.get("conversation_id") or context.get("session_id") or "")
    cleaned = re.sub(r"[^0-9A-Za-z_\-]", "", raw)[:80]
    return cleaned or "default"


def should_answer_as_dialogue(message: str, context: Mapping[str, Any] | None) -> bool:
    """连续对话走底稿。明确的开单、导入、删除仍交给原来的业务链路。"""
    text = str(message or "").strip()
    if not text or _CONFIRM.match(text):
        return False
    if context and (context.get("excel_file_path") or context.get("excel_analysis")):
        return False
    if _HARD_ERP.search(text) and not _HYPOTHETICAL.search(text):
        if not (_ledger_active(conversation_key(context)) and _NARRATIVE_STOCK.search(text)):
            return False
    if _SCENARIO.search(text):
        return True
    return _ledger_active(conversation_key(context)) and not _bare_business_command(text)


def build_messages(key: str, message: str) -> list[dict[str, str]]:
    ledger = _read(key)
    lines = ["【本会话用户原话底稿】按时间顺序。只准使用这里出现过的事实。"]
    used = 0
    omitted = 0
    kept: list[str] = []
    for item in ledger.get("turns") or []:
        if not isinstance(item, dict) or item.get("role") != "user":
            continue
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        line = f"U{len(kept) + omitted + 1}: {content}"
        if used + len(line) > _PROMPT_USER_CHARS:
            omitted += 1
            continue
        used += len(line)
        kept.append(line)
    if omitted:
        lines.append(f"（更早的 {omitted} 条用户原话超出长度，未放入本次提示）")
    lines.extend(kept)
    transcript = "\n".join(lines)
    system = (
        "你是企业桌面软件里的连续对话记忆。回答使用简体中文，直接给出结果。\n"
        "规则：\n"
        "1. 只使用底稿中的事实，不编造人数、金额、数量、名称或时间。\n"
        "2. 后出现的明确纠正覆盖旧数字。用户说「错误」「实际只」「调整为」「最终数据」时，以最后一次有效纠正为准。\n"
        "3. 「如果」「假设」「模拟」「暂时不要修改」「只是模拟」不改变已确认的数据。问当前真实值时回答确认值。\n"
        "4. 「撤销」模拟或新增时，回到该模拟之前已经确认的数据。\n"
        "5. 「恢复原来的限制」后，临时放宽的条件作废。\n"
        "6. 底稿没有给出的数字不要补。例如允许某部门招聘但没有招聘人数时，说明无法计算。\n"
        "7. 底稿里没有的另一组业务、另一个识别标记，要明确说当前会话没有提供，不能从别的会话借用。\n"
        "8. 不要输出工作流、计划编号或工具调用。\n"
        "9. 汇总时使用最后一次有效结果。后续加减或纠正已经覆盖的最初数字不能再写回报告。\n"
        "10. 件数、种数、人数、金额各自单独累计，同一个基数只加一次。\n"
        "11. 公司总人数必须等于各部门最后一次有效人数之和。不要只用最初总数加上其中一项变动。\n\n"
        f"{transcript}"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": f"请根据底稿回答最后一条用户原话：{message}"},
    ]


async def try_dialogue_memory_reply(
    message: str,
    context: Mapping[str, Any] | None = None,
    *,
    complete: Complete | None = None,
) -> dict[str, Any] | None:
    if not should_answer_as_dialogue(message, context):
        return None
    key = conversation_key(context)
    turn_id = str((context or {}).get("turn_id") or "").strip()
    text = str(message or "").strip()
    with _lock(key):
        cached = _cached_reply(key, text, turn_id)
        if cached is not None:
            return _payload(cached)
        _append(key, "user", text, turn_id)
        messages = build_messages(key, text)
        try:
            reply = await _complete(messages, complete)
        except RECOVERABLE_ERRORS:
            logger.warning("dialogue memory model call failed", exc_info=True)
            reply = ""
        if not reply:
            reply = "这次没有生成可靠回答。你刚才说的内容已经保留，请再问一次。未确认的数字不要当成结果。"
        _append(key, "assistant", reply, turn_id)
        return _payload(reply)


def _payload(reply: str) -> dict[str, Any]:
    return {
        "success": True,
        "message": "处理完成",
        "response": reply,
        "data": {
            "text": reply,
            "action": "dialogue_memory",
            "data": {"intent": "dialogue_memory"},
        },
    }


async def _complete(messages: list[dict[str, str]], complete: Complete | None) -> str:
    last_error: Exception | None = None
    for attempt in range(2):
        try:
            if complete is not None:
                text = str(await complete(messages) or "").strip()
            else:
                from app.infrastructure.llm.invoke import chat_completion_openai_format

                result = await chat_completion_openai_format(
                    messages,
                    temperature=0.1,
                    max_tokens=2200,
                    reasoning_enabled=False,
                )
                text = _content_of(result)
            if text:
                return text
        except RECOVERABLE_ERRORS as exc:
            last_error = exc
            logger.warning("dialogue memory model attempt %s failed", attempt + 1)
        if attempt == 0:
            await asyncio.sleep(0.4)
    if last_error is not None:
        logger.warning("dialogue memory model call failed", exc_info=last_error)
    return ""


def _content_of(result: Any) -> str:
    if not isinstance(result, dict):
        return ""
    choices = result.get("choices") or []
    if not choices or not isinstance(choices[0], dict):
        return ""
    message = choices[0].get("message") if isinstance(choices[0].get("message"), dict) else {}
    content = str(message.get("content") or "").strip()
    if content:
        return content
    return str(message.get("reasoning_content") or "").strip()


def _bare_business_command(text: str) -> bool:
    """已进入连续对话后，只有明确的查询或删除才交回业务链路。"""
    if _HYPOTHETICAL.search(text) or _SCENARIO.search(text):
        return False
    return bool(_ERP_COMMAND.search(text))


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
        return {"active": False, "turns": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except RECOVERABLE_ERRORS:
        return {"active": False, "turns": []}
    if not isinstance(data, dict):
        return {"active": False, "turns": []}
    turns = data.get("turns") if isinstance(data.get("turns"), list) else []
    return {"active": bool(data.get("active")), "turns": turns}


def _write(key: str, data: dict[str, Any]) -> None:
    path = _path(key)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def _append(key: str, role: str, content: str, turn_id: str) -> None:
    data = _read(key)
    cap = _USER_CAP if role == "user" else _ASSISTANT_CAP
    data["active"] = True
    data["turns"].append(
        {
            "role": role,
            "content": content[:cap],
            "turn_id": turn_id,
            "at": time.time(),
        }
    )
    data["turns"] = data["turns"][-240:]
    _write(key, data)


def _cached_reply(key: str, text: str, turn_id: str) -> str | None:
    turns = _read(key).get("turns") or []
    if turn_id:
        for index, item in enumerate(turns):
            if item.get("role") == "user" and item.get("turn_id") == turn_id:
                return _assistant_after(turns, index)
    if not turns:
        return None
    last_user = None
    last_index = -1
    for index, item in enumerate(turns):
        if item.get("role") == "user":
            last_user = item
            last_index = index
    if not last_user or str(last_user.get("content") or "") != text:
        return None
    if time.time() - float(last_user.get("at") or 0) > _DEDUP_SEC:
        return None
    return _assistant_after(turns, last_index)


def _assistant_after(turns: list[dict[str, Any]], index: int) -> str | None:
    for item in turns[index + 1 :]:
        if item.get("role") == "assistant":
            return str(item.get("content") or "")
        if item.get("role") == "user":
            return None
    return None


def _lock(key: str) -> threading.Lock:
    with _LOCKS_GUARD:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _LOCKS[key] = lock
        return lock


__all__ = [
    "build_messages",
    "conversation_key",
    "should_answer_as_dialogue",
    "try_dialogue_memory_reply",
]
