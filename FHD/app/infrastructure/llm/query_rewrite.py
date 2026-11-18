"""多轮对话的检索查询改写（conversational query rewriting）。

把依赖上下文的追问改写成可独立检索的问题；未配置平台模型、超时或输出异常时
返回空字符串，调用方沿用原问题。``XCAGI_KB_QUERY_REWRITE=0`` 可关闭。
"""

from __future__ import annotations

import os
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

SYSTEM_PROMPT = (
    "你是检索查询改写器。根据对话历史，把用户最后一句改写成一条可独立检索的中文问题："
    "补全代词与省略的主语、保留关键实体与限定条件，不回答问题、不添加历史中不存在的信息。"
    "只输出改写后的问题本身，不要解释、不要引号。"
)

_MAX_TURNS = 6
_MAX_QUESTION_CHARS = 500
_DISABLED_VALUES = frozenset({"0", "false", "off", "no"})


def rewrite_enabled() -> bool:
    return (os.environ.get("XCAGI_KB_QUERY_REWRITE") or "").strip().lower() not in _DISABLED_VALUES


def _timeout_seconds() -> float:
    raw = (os.environ.get("XCAGI_KB_QUERY_REWRITE_TIMEOUT_S") or "").strip()
    try:
        return max(1.0, min(60.0, float(raw)))
    except ValueError:
        return 10.0


def _transcript(history: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for turn in history[-_MAX_TURNS:]:
        role = str(turn.get("role") or "").strip().lower()
        content = str(turn.get("content") or "").strip()
        if role not in {"user", "assistant"} or not content:
            continue
        label = "用户" if role == "user" else "助手"
        lines.append(f"{label}：{content[:800]}")
    return "\n".join(lines)


def _clean(text: str, question: str) -> str:
    first = (text or "").strip().splitlines()[0].strip() if (text or "").strip() else ""
    first = first.strip("\"'“”‘’「」『』《》 ")
    if not first or first == question.strip():
        return ""
    return first[:_MAX_QUESTION_CHARS]


def rewrite_query(question: str, history: list[dict[str, Any]] | None) -> str:
    """返回改写后的独立问题；不可用时返回空字符串。"""
    query = (question or "").strip()
    if not rewrite_enabled() or not query or not history:
        return ""
    transcript = _transcript(history)
    if not transcript:
        return ""
    from app.infrastructure.llm.knowledge_answer import platform_provider

    provider = platform_provider()
    if provider is None:
        return ""
    from app.infrastructure.llm.structured_output import complete_text_sync

    try:
        text = complete_text_sync(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"对话历史：\n{transcript}\n\n最后一句：{query}"},
            ],
            timeout_seconds=_timeout_seconds(),
            temperature=0.0,
            max_tokens=200,
            provider=provider,
        )
    except RECOVERABLE_ERRORS:
        return ""
    return _clean(text, query)
