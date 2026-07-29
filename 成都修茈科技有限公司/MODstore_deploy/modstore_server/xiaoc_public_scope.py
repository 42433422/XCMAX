"""Shared public-knowledge visibility scope for XiaoC customer-service retrieval."""

from __future__ import annotations

from typing import Any, Dict

PUBLIC_KNOWLEDGE_FILTER: Dict[str, str] = {
    "audience": "public",
    "publication_status": "published",
    "knowledge_owner": "chengdu-xiuci-technology",
}


def public_query_kwargs() -> Dict[str, Any]:
    return {"tenant_id": "public", "metadata_filter": dict(PUBLIC_KNOWLEDGE_FILTER)}


def is_published_public_chunk(chunk: Any) -> bool:
    metadata = chunk.get("metadata") if isinstance(chunk, dict) else None
    return isinstance(metadata, dict) and all(
        metadata.get(key) == value for key, value in PUBLIC_KNOWLEDGE_FILTER.items()
    )
