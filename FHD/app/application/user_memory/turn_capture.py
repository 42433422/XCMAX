"""Legacy turn-capture facade: extraction produces reviewable MemoryV2 candidates."""

from __future__ import annotations

import logging
import os
from typing import Any

from app.application.user_memory.write import remember
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def extract_fact_candidates(user_message: str, assistant_reply: str = "") -> list[str]:
    from app.application.persy_memory_utils import extract_explicit_memories
    from app.infrastructure.memory.mem0_backend import get_long_term_memory

    candidates = None
    try:
        candidates = get_long_term_memory().extract_candidates(
            user_id="candidate-extraction",
            user_message=user_message,
        )
    except RECOVERABLE_ERRORS:
        logger.warning("candidate extraction unavailable", exc_info=True)
    if candidates is None:
        candidates = extract_explicit_memories(user_message)
    return [
        str(item["value"]["statement"])
        for item in candidates
        if isinstance(item.get("value"), dict) and item["value"].get("statement")
    ][:8]


def capture_turn(
    *,
    user_message: str,
    assistant_reply: str = "",
    owner_id: str,
    scope: str = "user",
    store: Any | None = None,
) -> list[dict[str, Any]]:
    if (os.environ.get("XCAGI_MEMORY_CAPTURE") or "1").strip().lower() in {
        "0",
        "false",
        "off",
        "no",
    }:
        return []
    if not str(owner_id or "").startswith(("personal-memory:v1:", "enterprise-memory:v1:")):
        return []
    return [
        remember(fact, scope=scope, owner_id=owner_id, source="chat_turn", store=store)
        for fact in extract_fact_candidates(user_message)
    ]


__all__ = ["capture_turn", "extract_fact_candidates"]
