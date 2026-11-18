"""Compatibility retrieval reads the confirmed authority, never legacy raw facts."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.application.user_memory.governance import is_recallable_memory, memory_statement
from app.application.user_memory.write import MemoryFactsStore, default_memory_store

CONTEXT_HEADER = "【相关记忆】"


def score_memory(query: str, record: dict[str, Any], now: datetime | str | None = None) -> float:
    from app.application.persy_memory_utils import _lexical_score, _search_tokens

    return _lexical_score(
        query, _search_tokens(query), str(record.get("text") or memory_statement(record))
    )


def search(
    query: str,
    *,
    scope: str,
    owner_id: str,
    limit: int = 5,
    min_score: float = 0.05,
    now: datetime | str | None = None,
    store: MemoryFactsStore | None = None,
) -> list[dict[str, Any]]:
    owner = str(owner_id or "").strip()
    if not owner.startswith(
        ("personal-memory:v1:", "enterprise-memory:v1:", "global-preference:v1:")
    ):
        return []
    memory = (store or default_memory_store()).get_memory(owner)
    records = memory.memory_v2_records if memory is not None else []
    hits = []
    for record in records:
        if not is_recallable_memory(record):
            continue
        text = memory_statement(record)
        score = score_memory(query, {"text": text})
        if score <= 0 or score < float(min_score):
            continue
        hits.append(
            {
                "id": record["memory_id"],
                "text": text,
                "score": score,
                "revision": int(record.get("revision") or 1),
                "updated_at": str(record.get("updated_at") or ""),
            }
        )
    return sorted(hits, key=lambda item: -item["score"])[: max(0, int(limit))]


def build_memory_context(
    query: str,
    *,
    scope: str,
    owner_id: str,
    limit: int = 5,
    max_chars: int = 800,
    now: datetime | str | None = None,
    store: MemoryFactsStore | None = None,
) -> str:
    hits = search(query, scope=scope, owner_id=owner_id, limit=limit, now=now, store=store)
    if not hits or max_chars <= 0:
        return ""
    lines = [CONTEXT_HEADER]
    lines.extend(f"{index}. {hit['text']}" for index, hit in enumerate(hits, start=1))
    return "\n".join(lines)[:max_chars]
