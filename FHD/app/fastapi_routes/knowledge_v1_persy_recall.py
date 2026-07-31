"""Persy recall + ERP ontology merge helpers (extracted for source-governance)."""
from __future__ import annotations

from typing import Any, Callable

from fastapi import Request

_PERSY_DATASET_ID = "persy-knowledge"


def merge_persy_recall(
    payload: dict[str, Any],
    *,
    request: Request,
    params: dict[str, Any],
    dataset_access_context_from_request: Callable[..., Any],
    persy_memory_service: Callable[[], Any],
) -> dict[str, Any]:
    payload: dict[str, Any],
    *,
    request: Request,
    params: dict[str, Any],
) -> dict[str, Any]:
    from app.application.erp_domain_ontology import (
        query_erp_ontology,
        summarize_erp_ontology_chunks,
    )

    if str(params.get("dataset_id") or "") != _PERSY_DATASET_ID or not payload.get("success"):
        return payload
    query_text = str(params.get("query") or "").strip()
    if not query_text:
        return payload
    memory_result = persy_memory_service().query(
        access_context=dataset_access_context_from_request(request),
        query=query_text,
        top_k=max(1, min(int(params.get("top_k") or 5), 20)),
        reinforce=True,
    )
    result = dict(payload)
    result["persy_memory"] = {
        "available": bool(memory_result.get("success")),
        "count": len(memory_result.get("chunks") or []),
        "retriever": str(memory_result.get("retriever") or ""),
    }
    if not memory_result.get("success"):
        result["persy_memory"]["error_code"] = str(memory_result.get("error_code") or "")
        memory_chunks: list[dict[str, Any]] = []
    else:
        memory_chunks = [
            dict(chunk) for chunk in memory_result.get("chunks", []) if isinstance(chunk, dict)
        ]

    knowledge_chunks = [
        dict(chunk) for chunk in payload.get("chunks", []) if isinstance(chunk, dict)
    ]
    erp_result = query_erp_ontology(
        query_text,
        top_k=max(1, min(int(params.get("top_k") or 5), 12)),
    )
    erp_chunks = [dict(chunk) for chunk in erp_result.get("chunks", []) if isinstance(chunk, dict)]
    result["erp_ontology"] = {
        "available": bool(erp_result.get("success")),
        "count": len(erp_chunks),
        "retriever": str(erp_result.get("retriever") or ""),
        "ontology_version": str(erp_result.get("ontology_version") or ""),
    }
    seen: set[str] = set()
    merged_chunks: list[dict[str, Any]] = []
    for chunk in sorted(
        [*memory_chunks, *erp_chunks, *knowledge_chunks],
        key=lambda item: float(item.get("score") or 0.0),
        reverse=True,
    ):
        metadata = chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {}
        fingerprint = str(
            metadata.get("memory_id")
            or metadata.get("erp_ontology_id")
            or metadata.get("document_id")
            or f"{chunk.get('source')}:{chunk.get('chunk_index')}:{chunk.get('text')}"
        )
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        merged_chunks.append(chunk)
    result["chunks"] = merged_chunks[: max(2, min(int(params.get("top_k") or 5) * 2, 40))]

    citations = [
        dict(citation) for citation in payload.get("citations", []) if isinstance(citation, dict)
    ]
    for chunk in memory_chunks:
        memory_metadata = chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {}
        citations.append(
            {
                "index": len(citations) + 1,
                "source": "对话记忆",
                "text": str(chunk.get("text") or ""),
                "score": chunk.get("score"),
                "memory_id": memory_metadata.get("memory_id"),
            }
        )
    for chunk in erp_chunks:
        erp_metadata = chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {}
        citations.append(
            {
                "index": len(citations) + 1,
                "source": "ERP 领域本体",
                "text": str(chunk.get("text") or ""),
                "score": chunk.get("score"),
                "erp_ontology_id": erp_metadata.get("erp_ontology_id"),
                "symbolic_expression": erp_metadata.get("symbolic_expression"),
            }
        )
    result["citations"] = citations

    if (memory_chunks or erp_chunks) and params.get("include_answer", True):
        memory_summary = "；".join(
            str(chunk.get("text") or "").strip()[:180]
            for chunk in memory_chunks[:3]
            if str(chunk.get("text") or "").strip()
        )
        erp_summary = summarize_erp_ontology_chunks(erp_chunks)
        knowledge_answer = str(payload.get("answer") or "").strip()
        memory_answer = f"已确认的长期记忆：{memory_summary}。" if memory_summary else ""
        erp_answer = f"ERP 领域规则：{erp_summary}。" if erp_summary else ""
        result["answer"] = "\n\n".join(
            part for part in (erp_answer, memory_answer, knowledge_answer) if part
        )
    return result
