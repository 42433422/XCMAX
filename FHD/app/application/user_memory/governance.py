"""Authority checks shared by MemoryV2, vector recall and model evidence."""

from __future__ import annotations

import json
from typing import Any


def authorized_personal_memory_id(context: dict[str, Any]) -> str:
    """Resolve a namespace only after validating the server-bound live actor."""
    from app.application.agent_task_context import scoped_personal_memory_id
    from app.infrastructure.auth.agent_mod_scope import validate_actor_context

    return "" if validate_actor_context(context) is not None else scoped_personal_memory_id(context)


def is_scoped_memory_owner(user_id: str) -> bool:
    return str(user_id or "").startswith(
        ("personal-memory:v1:", "enterprise-memory:v1:", "global-preference:v1:")
    )


def is_recallable_memory(record: Any) -> bool:
    return (
        isinstance(record, dict)
        and record.get("status") == "active"
        and record.get("eligible_for_planner") is True
        and record.get("source_policy") != "blocked"
    )


def memory_statement(record: dict[str, Any]) -> str:
    value = record.get("value")
    if isinstance(value, dict) and value.get("statement"):
        return str(value["statement"])
    rendered = (
        value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    )
    return f"{record.get('key') or '记忆'}：{rendered}"


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
    hits = []
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
