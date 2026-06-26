"""Token 估算公共工具。

提供粗略的 token 估算，用于上下文窗口管理、预算预检等场景。
估算系数与 LLM 实际 token 数存在偏差，**仅用于预算预检，不用于计费**。
计费以 LLM response.usage 为准（见 :mod:`app.infrastructure.billing.model_usage`）。

估算规则（与 :mod:`app.domain.neuro.cognition.attention_selector` 原实现保持一致）：

- 中文 1 字 ≈ 1.5 token
- 英文 1 词 ≈ 1.3 token
- 其他字符（标点、空白、数字、emoji 等）不计入
"""

from __future__ import annotations

import re

__all__ = ["estimate_tokens", "estimate_messages_tokens"]

_CN_CHAR_PATTERN = re.compile(r"[\u4e00-\u9fff]")
_EN_WORD_PATTERN = re.compile(r"[a-zA-Z]+")

# 估算系数（与 attention_selector 原实现一致，勿随意修改——会改变预算预检行为）
_CN_CHARS_PER_TOKEN = 1.5
_EN_WORDS_PER_TOKEN = 1.3


def estimate_tokens(text: str | None) -> int:
    """粗略估算文本的 token 数。

    中文 1 字 ≈ 1.5 token，英文 1 词 ≈ 1.3 token，其他字符不计入。

    Args:
        text: 待估算的文本。``None`` 或空字符串返回 ``0``。

    Returns:
        估算的 token 数（``int``，向下取整）。

    Examples:
        >>> estimate_tokens(None)
        0
        >>> estimate_tokens("")
        0
        >>> estimate_tokens("hello world")
        2
        >>> estimate_tokens("你好世界")
        6
    """
    if not text:
        return 0
    cn_chars = len(_CN_CHAR_PATTERN.findall(text))
    en_words = len(_EN_WORD_PATTERN.findall(text))
    return int(cn_chars * _CN_CHARS_PER_TOKEN + en_words * _EN_WORDS_PER_TOKEN)


def estimate_messages_tokens(messages: list[dict[str, str]] | None) -> int:
    """估算 OpenAI 格式 messages 列表的总 token 数。

    对每条 message 的 ``content`` 字段累加估算，忽略 ``role`` 字段的开销
    （``role`` 字段 token 数固定且较小，预算预检时忽略）。

    Args:
        messages: OpenAI 格式的消息列表，每条形如 ``{"role": "...", "content": "..."}``。
            ``None`` 或空列表返回 ``0``。

    Returns:
        估算的总 token 数。

    Examples:
        >>> estimate_messages_tokens(None)
        0
        >>> estimate_messages_tokens([])
        0
        >>> estimate_messages_tokens([{"role": "user", "content": "hi"}])
        1
    """
    if not messages:
        return 0
    total = 0
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        if isinstance(content, str):
            total += estimate_tokens(content)
        elif content is not None:
            # 非 str 内容（如多模态 list）转为 str 后估算
            total += estimate_tokens(str(content))
    return total
