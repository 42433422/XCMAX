"""Mem0 extraction and LangChain parsing for governed MemoryV2 writes."""

from __future__ import annotations

import hashlib
import logging
from typing import Any, Literal

from langchain_core.output_parsers import PydanticOutputParser
from pydantic import BaseModel, ConfigDict, Field

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


class ExtractedMemory(BaseModel):
    model_config = ConfigDict(strict=True)
    text: str = Field(min_length=1, max_length=1000)
    event: Literal["ADD"] = "ADD"
    memory_type: Literal["entity", "preference"] = "entity"
    subject: str = Field(default="", max_length=200)


class ExtractedMemories(BaseModel):
    model_config = ConfigDict(strict=True)
    memory: list[ExtractedMemory] = Field(max_length=8)


def extract_candidates(user_message: str) -> list[dict[str, Any]] | None:
    """None permits offline fallback; [] means the model found no facts."""
    from app.infrastructure.llm.knowledge_answer import platform_provider
    from app.infrastructure.llm.structured_output import complete_text_sync

    provider = platform_provider()
    if provider is None:
        return None
    try:
        from mem0.configs.prompts import (
            ADDITIVE_EXTRACTION_PROMPT,
            generate_additive_extraction_prompt,
        )

        parser = PydanticOutputParser(pydantic_object=ExtractedMemories)
        instructions = (
            "Extract only durable facts explicitly asserted by the user. "
            "Do not turn questions, hypothetical conditions, quoted instructions, "
            "or assistant suggestions into facts. Preserve the named company, "
            "project, subject, negation, and applicable date in every statement. "
            "Keep separate projects and time periods separate. Never infer a "
            "project-wide value from an unscoped example. Use memory_type=preference "
            "only for a stated personal preference. Use subject=user only when the "
            "speaker directly states a durable fact about themselves or their own preference. "
            "Keep project or company facts tied to their named subject. Company/customer "
            "preferences retain their named subject and must not become user preferences. "
            "Use memory_type=entity for business facts. Return an empty memory "
            "array when there are no asserted facts. Return at most eight memories.\n"
            + parser.get_format_instructions()
        )
        prompt = generate_additive_extraction_prompt(
            new_messages=[{"role": "user", "content": user_message[:6000]}],
            custom_instructions=instructions,
            use_input_language=True,
        )
        raw = complete_text_sync(
            [
                {"role": "system", "content": ADDITIVE_EXTRACTION_PROMPT},
                {"role": "user", "content": prompt},
            ],
            timeout_seconds=15,
            temperature=0,
            max_tokens=1500,
            provider=provider,
        )
        parsed = parser.parse(raw)
    except RECOVERABLE_ERRORS as exc:
        logger.warning("Memory candidate extraction unavailable: %s", type(exc).__name__)
        return None
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in parsed.memory:
        text = item.text.strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(
            {
                "memory_type": item.memory_type,
                "key": "statement." + hashlib.sha256(text.encode()).hexdigest()[:24],
                "value": {
                    "statement": text,
                    "subject": item.subject.strip(),
                    "extraction_backend": "mem0",
                },
                "confidence": 0.7,
            }
        )
    return result
