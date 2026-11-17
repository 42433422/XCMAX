"""知识库问答的默认 LLM 合成通道（不可用时由调用方回退抽取式答案）。

开关 ``XCAGI_KB_ANSWER_LLM=0`` 可关闭；超时 ``XCAGI_KB_ANSWER_TIMEOUT_S`` 默认 30 秒。
只有平台模型已配置（``get_active_provider`` 解析成功）时才返回可调用对象，
未配置或依赖异常一律返回 ``None``，保持既有确定性答案解析不变。
"""

from __future__ import annotations

import os
from collections.abc import Callable

from app.utils.operational_errors import RECOVERABLE_ERRORS

SYSTEM_PROMPT = (
    "你是企业知识库助手。只能依据用户提供的资料回答，资料不足时明确说明资料中没有，"
    "不要编造。回答简洁，并在引用资料处使用编号标记，如 [1][2]。"
)

_DISABLED_VALUES = frozenset({"0", "false", "off", "no"})


def _disabled() -> bool:
    return (os.environ.get("XCAGI_KB_ANSWER_LLM") or "").strip().lower() in _DISABLED_VALUES


def _timeout_seconds() -> float:
    raw = (os.environ.get("XCAGI_KB_ANSWER_TIMEOUT_S") or "").strip()
    try:
        return max(1.0, min(120.0, float(raw)))
    except ValueError:
        return 30.0


def platform_provider() -> object | None:
    """解析当前平台模型 provider；未配置或依赖异常时返回 None。"""
    try:
        from app.infrastructure.llm.providers.registry import get_active_provider

        return get_active_provider()
    except RECOVERABLE_ERRORS:
        return None


def get_kb_answer_llm_call() -> Callable[[str, str], str] | None:
    """返回 (query, passages) -> answer 的合成调用；无平台模型时返回 None。"""
    if _disabled():
        return None
    provider = platform_provider()
    if provider is None:
        return None
    timeout = _timeout_seconds()

    def _call(query: str, passages: str) -> str:
        from app.infrastructure.llm.structured_output import complete_text_sync

        try:
            return complete_text_sync(
                [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": f"资料：\n{passages}\n\n问题：{query}"},
                ],
                timeout_seconds=timeout,
                temperature=0.2,
                max_tokens=900,
                provider=provider,
            ).strip()
        except RECOVERABLE_ERRORS:
            return ""

    return _call
