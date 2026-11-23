"""Compatibility retrieval reads the confirmed authority, never legacy raw facts."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.application.user_memory.policy import (
    is_scoped_memory_owner,
    memory_statement,
)
from app.application.user_memory.relation_retrieval import relation_paths, select_effective_records
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
    eligible, _, _ = select_effective_records(records)
    for record in eligible:
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
    eligible, _, _ = select_effective_records(
        memory_service.list_memories(user_id, status="active")
    )
    current = {str(record.get("memory_id") or ""): record for record in eligible}
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
        path = metadata.get("relation_path")
        checked_path: list[dict[str, Any]] = []
        if path:
            if not isinstance(path, list) or len(path) > 3:
                continue
            for step in path:
                if not isinstance(step, dict):
                    break
                step_id = str(step.get("memory_id") or "")
                previous = current.get(step_id)
                if (previous is None or step.get("scope") != "owner"
                        or step.get("revision") != previous.get("revision")):
                    break
                checked_path.append({**step, "statement": memory_statement(previous)})
            if len(checked_path) != len(path) or checked_path[-1]["memory_id"] != source_id:
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
                    **({"relation_path": checked_path} if checked_path else {}),
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
    authority = get_user_memory_service()
    hits: list[dict[str, Any]] = []
    eligible, _, _ = select_effective_records(authority.list_memories(user_id, status="active"))
    for record in eligible:
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
    ranked = sorted(hits, key=lambda hit: hit["score"], reverse=True)
    related = relation_recall_hits(user_id, query, memory_service=authority)
    return merge_relation_hits(ranked, related, limit=limit)


def relation_recall_hits(
    user_id: str, query: str, *, memory_service: Any = None
) -> list[dict[str, Any]]:
    """Use the same bounded relation traversal in the Agent's original recall path."""
    if not is_scoped_memory_owner(user_id):
        return []
    if memory_service is None:
        from app.domain.shared_services.user_memory_service import get_user_memory_service

        memory_service = get_user_memory_service()
    raw = memory_service.list_memories(user_id, status="active")
    if not isinstance(raw, list):
        return []
    eligible, _, _ = select_effective_records(raw)
    rows = [
        {**row, "scope": "owner", "statement": memory_statement(row)}
        for row in eligible
    ]
    paths, _ = relation_paths(query, rows, max_hops=2)
    hits = []
    for row in rows:
        source_id = str(row.get("memory_id") or "")
        path = paths.get(("owner", source_id), [])
        if len(path) < 2:
            continue
        hits.append({
            "content": row["statement"],
            "memory": row["statement"],
            "score": round(0.68 / len(path) ** 0.5, 6),
            "chunk_id": source_id,
            "metadata": {
                "source": "memory_v2_relation",
                "source_memory_id": source_id,
                "source_revision": int(row.get("revision") or 1),
                "source_owner_id": user_id,
                "relation_path": path,
                "retrieval_mode": "relation",
            },
        })
    return filter_recalled_memories(user_id, hits, memory_service=memory_service)


def merge_relation_hits(
    direct: list[dict[str, Any]], related: list[dict[str, Any]], *, limit: int
) -> list[dict[str, Any]]:
    bounded = max(1, min(20, int(limit)))
    seen = {
        str((hit.get("metadata") or {}).get("source_memory_id") or hit.get("chunk_id") or "")
        for hit in direct
    }
    extra = [
        hit for hit in sorted(related, key=lambda item: -float(item.get("score") or 0.0))
        if str(hit["metadata"]["source_memory_id"]) not in seen
    ]
    if not extra or bounded == 1:
        return (direct or extra)[:bounded]
    # Reserve at most one graph-only slot rather than pretending its score is vector cosine.
    primary = direct[: bounded - 1]
    return [*primary, *extra[: bounded - len(primary)]]


def format_relation_evidence(hit: dict[str, Any]) -> str:
    metadata = hit.get("metadata")
    path = metadata.get("relation_path") if isinstance(metadata, dict) else None
    if not isinstance(path, list) or len(path) < 2:
        return ""
    evidence = "；".join(
        str(step.get("statement") or "").replace("\\n", " ")[:120]
        for step in path[:3] if isinstance(step, dict)
    )
    return f"（关联记录，仅供参考，不能证明身份或传递关系：{evidence}）" if evidence else ""
