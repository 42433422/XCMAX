"""Pure token estimation helpers for cognition-domain budgeting."""

from __future__ import annotations

import re

__all__ = ["estimate_tokens", "estimate_messages_tokens"]

_CN_CHAR_PATTERN = re.compile(r"[\u4e00-\u9fff]")
_EN_WORD_PATTERN = re.compile(r"[a-zA-Z]+")

_CN_CHARS_PER_TOKEN = 1.5
_EN_WORDS_PER_TOKEN = 1.3


def estimate_tokens(text: str | None) -> int:
    """Roughly estimate text tokens for context-window budgeting."""
    if not text:
        return 0
    cn_chars = len(_CN_CHAR_PATTERN.findall(text))
    en_words = len(_EN_WORD_PATTERN.findall(text))
    return int(cn_chars * _CN_CHARS_PER_TOKEN + en_words * _EN_WORDS_PER_TOKEN)


def estimate_messages_tokens(messages: list[dict[str, str]] | None) -> int:
    """Estimate total tokens for OpenAI-style messages."""
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
            total += estimate_tokens(str(content))
    return total
