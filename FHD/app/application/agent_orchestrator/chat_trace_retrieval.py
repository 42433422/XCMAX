"""
RAG retrieval trace helpers.

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
from app.application.agent_orchestrator.run_models import AgentRun, RetrievalCall


def _retrieval_signature(call: RetrievalCall) -> tuple[Any, ...]:
    first_chunk = call.chunks[0] if call.chunks else {}
    first_citation = call.citations[0] if call.citations else {}
    return (
        call.query,
        call.retriever,
        call.source,
        len(call.chunks),
        len(call.citations),
        str(
            first_chunk.get("chunk_index") or first_chunk.get("id") or first_chunk.get("text") or ""
        )[:120],
        str(
            first_citation.get("source")
            or first_citation.get("chunk_index")
            or first_citation.get("text")
            or ""
        )[:120],
        call.status,
        call.error,
    )


def _iter_retrieval_payloads(payload: dict[str, Any]) -> Iterator[dict[str, Any]]:
    for item in _iter_payload_dicts(payload):
        chunks = item.get("chunks")
        citations = item.get("citations")
        rag_enabled = item.get("rag_enabled")
        rag_error = item.get("rag_error") or item.get("retrieval_error")
        if (
            isinstance(chunks, list)
            or isinstance(citations, list)
            or rag_enabled is True
            or rag_error
        ):
            yield item


def _retrieval_call_from_payload(
    item: dict[str, Any], *, default_query: str
) -> RetrievalCall | None:
    raw_chunks = item.get("chunks")
    raw_citations = item.get("citations")
    chunks = [
        dict(_trace_safe_value(chunk))
        for chunk in (raw_chunks if isinstance(raw_chunks, list) else [])
        if isinstance(chunk, dict)
    ]
    citations = [
        dict(_trace_safe_value(citation))
        for citation in (raw_citations if isinstance(raw_citations, list) else [])
        if isinstance(citation, dict)
    ]
    error = str(item.get("rag_error") or item.get("retrieval_error") or item.get("error") or "")
    if not chunks and not citations and not error:
        return None

    status = "failed" if error else "completed"
    query = str(item.get("query") or item.get("user_message") or default_query or "")
    retriever = str(item.get("retriever") or item.get("retriever_id") or "rag")
    source = str(
        item.get("dataset_id")
        or item.get("source")
        or item.get("document_id")
        or item.get("knowledge_source")
        or ""
    )
    top_k = _coerce_trace_int(item.get("top_k")) or len(chunks)
    return RetrievalCall(
        query=query,
        retriever=retriever,
        source=source,
        top_k=top_k,
        chunks=chunks,
        citations=citations,
        status=status,
        error=error,
        metadata={
            "rag_enabled": bool(item.get("rag_enabled", True)),
            "raw_trace": _trace_safe_value(
                {
                    key: item.get(key)
                    for key in (
                        "query",
                        "user_message",
                        "dataset_id",
                        "source",
                        "document_id",
                        "top_k",
                        "rag_enabled",
                        "rag_error",
                    )
                    if key in item
                }
            ),
        },
    )


def _extract_retrieval_calls(payload: dict[str, Any], *, query: str = "") -> list[RetrievalCall]:
    calls: list[RetrievalCall] = []
    seen: set[tuple[Any, ...]] = set()
    for item in _iter_retrieval_payloads(payload):
        call = _retrieval_call_from_payload(item, default_query=query)
        if call is None:
            continue
        signature = _retrieval_signature(call)
        if signature in seen:
            continue
        seen.add(signature)
        calls.append(call)
    return calls


def _refresh_retrieval_metadata(run: AgentRun) -> None:
    run.metadata["retrieval_call_count"] = len(run.retrieval_calls)
    run.metadata["retrieval_chunk_count"] = sum(len(call.chunks) for call in run.retrieval_calls)
    run.metadata["citation_count"] = sum(len(call.citations) for call in run.retrieval_calls)
    if run.retrieval_calls:
        last_call = run.retrieval_calls[-1]
        run.metadata["retriever"] = last_call.retriever
        run.metadata["retrieval_source"] = last_call.source


def _append_retrieval_calls_to_run(run: AgentRun, calls: list[RetrievalCall]) -> None:
    existing = {_retrieval_signature(call) for call in run.retrieval_calls}
    for call in calls:
        signature = _retrieval_signature(call)
        if signature in existing:
            continue
        existing.add(signature)
        run.retrieval_calls.append(call)
        citation_sources = [
            str(citation.get("source") or citation.get("chunk_index") or "")
            for citation in call.citations[:5]
        ]
        run.add_event(
            "rag.retrieved" if call.status == "completed" else "rag.failed",
            f"记录 RAG 检索 {call.retriever}",
            {
                "call_id": call.call_id,
                "query": call.query,
                "retriever": call.retriever,
                "source": call.source,
                "top_k": call.top_k,
                "chunk_count": len(call.chunks),
                "citation_count": len(call.citations),
                "citation_sources": citation_sources,
                "error": call.error,
            },
        )
    if run.retrieval_calls:
        _refresh_retrieval_metadata(run)


def _append_retrieval_calls_to_final_output(run: AgentRun) -> None:
    if not run.retrieval_calls:
        return
    final_output = dict(run.final_output or {})
    final_output["retrieval_calls"] = [call.to_dict() for call in run.retrieval_calls]
    final_output["retrieval_chunk_count"] = run.metadata.get("retrieval_chunk_count", 0)
    final_output["citation_count"] = run.metadata.get("citation_count", 0)
    run.final_output = final_output
