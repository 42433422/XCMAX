"""Knowledge v1 runtime helpers (extracted for source-governance)."""
from __future__ import annotations

import json
from typing import Any

from fastapi import Request

def _ensure_bounded_metadata(value: Any, *, max_bytes: int = _DATASET_METADATA_MAX_BYTES) -> None:
    def walk(item: Any, depth: int = 0) -> None:
        if depth > 8:
            raise ValueError("metadata nesting exceeds 8 levels")
        if isinstance(item, dict):
            if len(item) > 200:
                raise ValueError("metadata has too many fields")
            for key, child in item.items():
                if len(str(key)) > 200:
                    raise ValueError("metadata key is too long")
                walk(child, depth + 1)
        elif isinstance(item, (list, tuple)):
            if len(item) > 1000:
                raise ValueError("metadata list is too long")
            for child in item:
                walk(child, depth + 1)

    walk(value)
    try:
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str).encode(
            "utf-8"
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("metadata must be JSON serializable") from exc
    if len(encoded) > max_bytes:
        raise ValueError(f"metadata cannot exceed {max_bytes} bytes")


def _knowledge_runtime_snapshot(request: Request | None = None) -> dict[str, Any]:
    legacy = _index.status()
    dataset_count = 0
    dataset_docs = 0
    dataset_chunks = 0
    recommended = _PERSY_DATASET_ID
    try:
        from app.application.dataset_rag_app_service import get_dataset_rag_app_service

        access = _dataset_access_context_from_request(request) if request is not None else None
        overview = get_dataset_rag_app_service().status(access_context=access)
        datasets = overview.get("datasets") if isinstance(overview, dict) else {}
        if isinstance(datasets, dict):
            dataset_count = len(datasets)
            dataset_docs = int(overview.get("document_count") or 0)
            dataset_chunks = int(overview.get("chunk_count") or 0)
            nonempty = [
                (key, int((val or {}).get("document_count") or 0))
                for key, val in datasets.items()
                if isinstance(val, dict)
            ]
            nonempty.sort(key=lambda item: item[1], reverse=True)
            persy_docs = next((n for key, n in nonempty if key == _PERSY_DATASET_ID), 0)
            if persy_docs <= 0 and nonempty and nonempty[0][1] > 0:
                recommended = nonempty[0][0]
    except Exception as exc:  # noqa: BLE001
        logger.debug("dataset overview for health failed: %s", exc)
    embedder_ok = get_default_embedder() is not None
    return {
        "rag_enabled": is_rag_enabled(),
        "embedder_available": embedder_ok,
        "semantic_embedding_available": embedder_ok,
        "indexed_sources": int(legacy.get("sources") or 0) + dataset_docs,
        "indexed_chunks": int(legacy.get("chunks") or 0) + dataset_chunks,
        "legacy_indexed_sources": int(legacy.get("sources") or 0),
        "legacy_indexed_chunks": int(legacy.get("chunks") or 0),
        "dataset_count": dataset_count,
        "dataset_document_count": dataset_docs,
        "dataset_chunk_count": dataset_chunks,
        "recommended_dataset_id": recommended,
    }

