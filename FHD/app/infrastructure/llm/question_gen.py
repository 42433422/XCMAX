"""入库时自动生成检索问题（Q&A 索引增强），默认关闭。

Dify 的 Q&A 模式会为每个片段生成用户可能提出的问题，让「口语化问题」也能
命中正文里没有原词写法的资料。这里复用平台模型通道：

- ``XCAGI_KB_AUTO_QUESTIONS=1`` 开启（默认关闭，避免无谓模型调用）；
- ``XCAGI_KB_AUTO_QUESTIONS_PER_CHUNK`` 每个片段问题数（默认 3，1–8）；
- ``XCAGI_KB_AUTO_QUESTIONS_MAX_CHUNKS`` 每次入库最多处理的片段数（默认 20，1–200）。

模型不可用、超时或输出异常时静默跳过，入库本身不受影响。
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

_ENABLED_VALUES = frozenset({"1", "true", "yes", "on"})
SYSTEM_PROMPT = (
    "你是企业知识库的问题生成器。根据给定资料片段，生成用户可能提出的中文问题，"
    "每行一个，不要编号、不要解释，最多 {limit} 个。"
)
_MAX_INPUT_CHARS = 2000
_PREFIX = re.compile(r"^\s*(?:[-*•]|\d+[.、)）]|[（(]\d+[)）]|[一二三四五六七八九十]+[、.])\s*")


def auto_questions_enabled() -> bool:
    return (os.environ.get("XCAGI_KB_AUTO_QUESTIONS") or "").strip().lower() in _ENABLED_VALUES


def _bounded_env(name: str, default: int, *, low: int, high: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw.isdigit():
        return default
    return max(low, min(int(raw), high))


def questions_per_chunk() -> int:
    return _bounded_env("XCAGI_KB_AUTO_QUESTIONS_PER_CHUNK", 3, low=1, high=8)


def max_chunks() -> int:
    return _bounded_env("XCAGI_KB_AUTO_QUESTIONS_MAX_CHUNKS", 20, low=1, high=200)


def _parse_questions(raw: str, limit: int) -> list[str]:
    questions: list[str] = []
    for line in str(raw or "").splitlines():
        question = _PREFIX.sub("", line).strip()
        if not question or (len(question) < 6 and not question.endswith(("?", "？"))):
            continue
        if question in questions:
            continue
        questions.append(question)
        if len(questions) >= limit:
            break
    return questions


def get_question_llm_call() -> Callable[[str], list[str]] | None:
    """返回 (chunk_text) -> questions；未开启或没有平台模型时返回 None。"""
    if not auto_questions_enabled():
        return None
    from app.infrastructure.llm.knowledge_answer import platform_provider

    provider = platform_provider()
    if provider is None:
        return None
    limit = questions_per_chunk()

    def _call(text: str) -> list[str]:
        from app.infrastructure.llm.structured_output import complete_text_sync

        raw = complete_text_sync(
            [
                {"role": "system", "content": SYSTEM_PROMPT.format(limit=limit)},
                {"role": "user", "content": str(text or "")[:_MAX_INPUT_CHARS]},
            ],
            timeout_seconds=20,
            temperature=0.3,
            max_tokens=200,
            provider=provider,
        )
        return _parse_questions(raw, limit)

    return _call


def augment_chunks(chunks: list[Any]) -> None:
    """为前 N 个片段写入 ``metadata.auto_questions``；任何失败都不影响入库。"""
    if not chunks or not auto_questions_enabled():
        return
    call = get_question_llm_call()
    if call is None:
        return
    for chunk in chunks[: max_chunks()]:
        try:
            questions = call(getattr(chunk, "text", ""))
        except RECOVERABLE_ERRORS:
            continue
        if not questions:
            continue
        metadata = getattr(chunk, "metadata", None)
        if not isinstance(metadata, dict):
            metadata = {}
        chunk.metadata = {**metadata, "auto_questions": questions}
