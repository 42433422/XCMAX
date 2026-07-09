"""
User memory reference trace helpers.

Split from ``chat_trace.py`` (v10 线内迭代 · 巨石拆分).
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from app.application.agent_orchestrator.chat_trace_common import (
    _coerce_trace_int,
    _iter_payload_dicts,
    _trace_safe_value,
)
from app.application.agent_orchestrator.run_models import AgentRun, MemoryReference


def _memory_reference_signature(reference: MemoryReference) -> tuple[Any, ...]:
    first_hit = reference.hits[0] if reference.hits else {}
    return (
        reference.query,
        reference.memory_type,
        reference.source,
        len(reference.hits),
        reference.summary[:240],
        str(
            first_hit.get("chunk_id")
            or first_hit.get("id")
            or first_hit.get("content")
            or first_hit.get("text")
            or ""
        )[:120],
        reference.status,
        reference.error,
    )


def _has_user_memory_marker(item: dict[str, Any]) -> bool:
    marker_keys = {
        "user_memory_rag",
        "userMemoryRag",
        "user_memory_rag_summary",
        "userMemoryRagSummary",
        "user_memory_summary",
        "userMemorySummary",
        "user_memory_hits",
        "userMemoryHits",
        "user_memory_error",
        "userMemoryError",
    }
    if any(key in item for key in marker_keys):
        return True
    for key in ("summary", "memory_summary", "prompt_memory", "context"):
        value = item.get(key)
        if isinstance(value, str) and "UserMemoryRAG" in value:
            return True
    return False


def _iter_memory_payloads(payload: dict[str, Any]) -> Iterator[dict[str, Any]]:
    nested_keys = (
        "user_memory_rag",
        "userMemoryRag",
        "memory_reference",
        "memoryReference",
    )
    for item in _iter_payload_dicts(payload):
        if _has_user_memory_marker(item):
            yield item
        for key in nested_keys:
            candidate = item.get(key)
            if isinstance(candidate, dict):
                yield candidate


def _first_list_value(item: dict[str, Any], keys: tuple[str, ...]) -> list[Any]:
    for key in keys:
        value = item.get(key)
        if isinstance(value, list):
            return value
    return []


def _memory_reference_from_payload(
    item: dict[str, Any],
    *,
    default_query: str,
) -> MemoryReference | None:
    has_marker = _has_user_memory_marker(item)
    raw_hits = _first_list_value(
        item,
        (
            "user_memory_hits",
            "userMemoryHits",
            "memory_hits",
            "memoryHits",
            "hits",
        ),
    )
    hits = [
        dict(_trace_safe_value(hit))
        for hit in raw_hits
        if isinstance(hit, dict) and isinstance(_trace_safe_value(hit), dict)
    ]
    summary = str(
        item.get("user_memory_rag_summary")
        or item.get("userMemoryRagSummary")
        or item.get("user_memory_summary")
        or item.get("userMemorySummary")
        or item.get("memory_summary")
        or item.get("summary")
        or item.get("prompt_memory")
        or ""
    )
    error = str(
        item.get("user_memory_error")
        or item.get("userMemoryError")
        or item.get("memory_error")
        or item.get("memoryError")
        or ""
    )
    if not has_marker and not hits and "UserMemoryRAG" not in summary:
        return None
    if not hits and not summary and not error:
        return None

    query = str(
        item.get("query") or item.get("user_message") or item.get("message") or default_query or ""
    )
    memory_type = str(item.get("memory_type") or item.get("memoryType") or "user_memory")
    source = str(
        item.get("source")
        or item.get("memory_source")
        or item.get("memorySource")
        or item.get("index_id")
        or item.get("collection")
        or "user_memory_rag"
    )
    status = "failed" if error else "completed"
    return MemoryReference(
        query=query,
        memory_type=memory_type,
        source=source,
        hits=hits,
        summary=summary,
        status=status,
        error=error,
        metadata={
            "top_k": _coerce_trace_int(item.get("top_k") or item.get("topK")),
            "hit_count": len(hits),
            "raw_trace": _trace_safe_value(
                {
                    key: item.get(key)
                    for key in (
                        "query",
                        "user_message",
                        "source",
                        "memory_source",
                        "index_id",
                        "collection",
                        "top_k",
                        "user_memory_error",
                        "memory_error",
                    )
                    if key in item
                }
            ),
        },
    )


def _extract_memory_references(
    payload: dict[str, Any],
    *,
    query: str = "",
) -> list[MemoryReference]:
    references: list[MemoryReference] = []
    seen: set[tuple[Any, ...]] = set()
    for item in _iter_memory_payloads(payload):
        reference = _memory_reference_from_payload(item, default_query=query)
        if reference is None:
            continue
        signature = _memory_reference_signature(reference)
        if signature in seen:
            continue
        seen.add(signature)
        references.append(reference)
    return references


def _refresh_memory_metadata(run: AgentRun) -> None:
    run.metadata["memory_reference_count"] = len(run.memory_references)
    run.metadata["memory_hit_count"] = sum(
        len(reference.hits) for reference in run.memory_references
    )
    run.metadata["memory_sources"] = sorted(
        {reference.source for reference in run.memory_references if reference.source}
    )


def _append_memory_references_to_run(
    run: AgentRun,
    references: list[MemoryReference],
) -> None:
    existing = {_memory_reference_signature(reference) for reference in run.memory_references}
    for reference in references:
        signature = _memory_reference_signature(reference)
        if signature in existing:
            continue
        existing.add(signature)
        run.memory_references.append(reference)
        first_sources = [
            str(hit.get("source") or hit.get("chunk_id") or hit.get("id") or "")
            for hit in reference.hits[:5]
        ]
        run.add_event(
            "memory.recalled" if reference.status == "completed" else "memory.failed",
            f"记录用户记忆召回 {reference.memory_type}",
            {
                "reference_id": reference.reference_id,
                "query": reference.query,
                "memory_type": reference.memory_type,
                "source": reference.source,
                "hit_count": len(reference.hits),
                "summary_preview": reference.summary[:500],
                "hit_sources": first_sources,
                "error": reference.error,
            },
        )
    if run.memory_references:
        _refresh_memory_metadata(run)


def _append_memory_references_to_final_output(run: AgentRun) -> None:
    if not run.memory_references:
        return
    final_output = dict(run.final_output or {})
    final_output["memory_references"] = [reference.to_dict() for reference in run.memory_references]
    final_output["memory_hit_count"] = run.metadata.get("memory_hit_count", 0)
    run.final_output = final_output
