"""Compatibility retrieval reads the confirmed authority, never legacy raw facts."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.application.user_memory.write import MemoryFactsStore, default_memory_store
from app.domain.user_memory.policy import (
    is_recallable_memory,
    is_scoped_memory_owner,
    memory_statement,
)

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


def filter_recalled_memories(
    user_id: str, hits: list[dict[str, Any]], *, memory_service: Any = None
) -> list[dict[str, Any]]:
    """Indexes propose matches; only the current authority revision supplies facts.

    Legacy raw turns and indexes without provenance are intentionally not adopted.
    This also fences stale replicas when deletion, correction or indexing fails.
    """
    if not is_scoped_memory_owner(user_id) or not hits:
        return []
    if memory_service is None:
        from app.domain.shared_services.user_memory_service import get_user_memory_service

        memory_service = get_user_memory_service()
    current = {
        str(record.get("memory_id") or ""): record
        for record in memory_service.list_memories(user_id, status="active")
        if is_recallable_memory(record)
    }
    accepted: list[dict[str, Any]] = []
    for hit in hits:
        if not isinstance(hit, dict):
            continue
        metadata = hit.get("metadata")
        if not isinstance(metadata, dict):
            continue
        source_id = str(metadata.get("source_memory_id") or "")
        if metadata.get("source_owner_id") != user_id:
            continue
        record = current.get(source_id)
        if record is None:
            continue
        try:
            revision = int(metadata.get("source_revision") or 0)
        except (TypeError, ValueError):
            continue
        if revision <= 0 or revision != int(record.get("revision") or 1):
            continue
        text = memory_statement(record)
        accepted.append(
            {
                **hit,
                "content": text,
                "memory": text,
                "text": text,
                "metadata": {
                    **metadata,
                    "status": "active",
                    "eligible_for_planner": True,
                    "source_policy": record.get("source_policy"),
                },
            }
        )
    return accepted


def recall_authoritative_memories(user_id: str, query: str, limit: int = 5) -> list[dict[str, Any]]:
    """Reuse Persy's bounded lexical fallback when a projection needs rebuilding."""
    from app.application.persy_memory_utils import _lexical_score, _search_tokens
    from app.domain.shared_services.user_memory_service import get_user_memory_service

    if not is_scoped_memory_owner(user_id):
        return []
    tokens = _search_tokens(query)
    hits: list[dict[str, Any]] = []
    for record in get_user_memory_service().list_memories(user_id, status="active"):
        if not is_recallable_memory(record):
            continue
        text = memory_statement(record)
        score = _lexical_score(query, tokens, text)
        if score <= 0:
            continue
        hits.append(
            {
                "content": text,
                "memory": text,
                "score": score,
                "chunk_id": str(record["memory_id"]),
                "metadata": {
                    "source": "memory_v2",
                    "source_memory_id": record["memory_id"],
                    "source_revision": int(record.get("revision") or 1),
                    "source_owner_id": user_id,
                },
            }
        )
    return sorted(hits, key=lambda hit: hit["score"], reverse=True)[:limit]
