"""回合结束后把用户显性偏好沉淀成长期记忆（规则抽取，不额外调用模型）。"""

from __future__ import annotations

import os
import re
from typing import Any

from app.application.user_memory.write import remember
from app.utils.operational_errors import BOUNDARY_ERRORS

# 只在用户明确表达长期偏好或身份信息时才沉淀，避免把一次性问题写进记忆。
_MARKERS = ("记住", "以后", "今后", "下次", "默认", "我喜欢", "我们公司", "我们厂", "我们的")
_SENTENCE_SEP = re.compile(r"[。；;！!？?\n]")
_MIN_LEN = 4
_MAX_LEN = 120
_MAX_FACTS = 2


def _enabled() -> bool:
    raw = (os.environ.get("XCAGI_MEMORY_CAPTURE") or "1").strip().lower()
    return raw not in {"0", "false", "off", "no"}


def extract_fact_candidates(user_message: str, assistant_reply: str = "") -> list[str]:
    """从用户消息里挑出带长期含义的句子。助手回复不作为事实来源。"""
    text = str(user_message or "").strip()
    if not text:
        return []
    facts: list[str] = []
    for raw in _SENTENCE_SEP.split(text):
        sentence = raw.strip(" \t，,、：:")
        if not (_MIN_LEN <= len(sentence) <= _MAX_LEN):
            continue
        if not any(marker in sentence for marker in _MARKERS):
            continue
        if sentence not in facts:
            facts.append(sentence)
        if len(facts) >= _MAX_FACTS:
            break
    return facts


def capture_turn(
    *,
    user_message: str,
    assistant_reply: str = "",
    owner_id: str,
    scope: str = "global",
    store: Any | None = None,
) -> list[dict[str, Any]]:
    """把本轮的显性偏好写进 recall_facts；任何异常不影响对话主流程。"""
    if not _enabled():
        return []
    owner = str(owner_id or "").strip()
    if not owner:
        return []
    results: list[dict[str, Any]] = []
    for fact in extract_fact_candidates(user_message, assistant_reply):
        try:
            results.append(
                remember(
                    fact,
                    scope=scope,
                    owner_id=owner,
                    source="chat_turn",
                    importance=0.6,
                    store=store,
                )
            )
        except BOUNDARY_ERRORS:
            continue
    return results


__all__ = ["capture_turn", "extract_fact_candidates"]
