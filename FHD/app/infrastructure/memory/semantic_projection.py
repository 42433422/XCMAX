"""Versioned, non-authoritative semantic projection of existing memory chunks."""

from __future__ import annotations

import hashlib
import json
import logging
import math
from typing import Any

from app.infrastructure.llm.embedding_service import get_default_embedding_service
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def _vector(value: Any, dimension: int) -> list[float] | None:
    if not isinstance(value, list) or len(value) != dimension:
        return None
    try:
        vector = [float(item) for item in value]
    except (ValueError, TypeError):
        return None
    if not all(math.isfinite(item) for item in vector):
        return None
    if not any(vector):
        return None
    return vector


def _cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b)) / (
        math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    )


def query_semantic_projection(
    store: Any,
    owner: str,
    query: str,
    *,
    cutoff: float,
    governed_only: bool,
    limit: int,
    top_k: int,
) -> list[dict[str, Any]] | None:
    """None means keep the old Hash space, never mix incomparable scores.

    Migration is lazy and reversible: retain the existing source records and
    cache only vectors scoped to their current content and model fingerprint.
    No data is sent to a remote embedding service by this migration.
    """
    snapshot = getattr(type(store), "semantic_snapshot", None)
    cache = getattr(type(store), "cache_semantic_vectors", None)
    if not callable(snapshot) or not callable(cache):
        return None
    try:
        embedder = get_default_embedding_service()
        if embedder is None or embedder.mode not in {"local", "fastembed"}:
            return None
        dimension = embedder.dim()
        if not 0 < dimension <= 8192:
            return None
        query_vector = _vector(embedder.embed_query(query), dimension)
        if query_vector is None:
            return None
        fingerprint = embedder.embedding_fingerprint
        rows = snapshot(store, owner, fingerprint, cutoff, governed_only, limit)
        vectors: dict[str, list[float]] = {}
        missing = []
        for row in rows:
            content_sha = hashlib.sha256(row["content"].encode("utf-8")).hexdigest()
            row["expected_sha"] = content_sha
            cached = None
            if row.get("content_sha") == content_sha and row.get("embedding"):
                try:
                    cached = _vector(json.loads(row["embedding"]), dimension)
                except (ValueError, TypeError):
                    pass
            if cached is None:
                missing.append(row)
            else:
                vectors[row["chunk_id"]] = cached
        updates = []
        for offset in range(0, len(missing), 32):
            batch = missing[offset : offset + 32]
            encoded = embedder.embed_texts([row["content"] for row in batch])
            if len(encoded) != len(batch):
                return None
            for row, raw in zip(batch, encoded):
                vector = _vector(raw, dimension)
                if vector is None:
                    return None
                vectors[row["chunk_id"]] = vector
                updates.append(
                    {
                        "chunk_id": row["chunk_id"],
                        "content": row["content"],
                        "content_sha": row["expected_sha"],
                        "embedding": json.dumps(vector, separators=(",", ":"), allow_nan=False),
                    }
                )
        if updates:
            cache(store, owner, fingerprint, updates)
        hits = [
            {
                "chunk_id": row["chunk_id"],
                "content": row["content"],
                "metadata": row["metadata"],
                "score": _cosine(query_vector, vectors[row["chunk_id"]]),
            }
            for row in rows
        ]
        hits.sort(key=lambda row: row["score"], reverse=True)
        return hits[:top_k]
    except RECOVERABLE_ERRORS:
        logger.warning("Semantic memory projection unavailable; using legacy hash", exc_info=True)
        return None
