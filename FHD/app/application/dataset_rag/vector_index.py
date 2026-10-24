"""Embedding and vector index adapters for dataset records."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.application.dataset_rag.models import _DatasetState, _utc_now_iso
from app.infrastructure.rag import RetrievedChunk
from app.infrastructure.rag.dataset_vector_index import DatasetVectorIndexBackend
from app.utils.operational_errors import RECOVERABLE_ERRORS


def _embedding_metadata(embedder: Callable[[str], list[float]] | None, text: str) -> dict[str, Any]:
    if embedder is None:
        return {}
    try:
        embedding = embedder(text)
    except RECOVERABLE_ERRORS:
        return {}
    if not isinstance(embedding, list) or not embedding:
        return {}
    try:
        return {"_embedding": [float(value) for value in embedding]}
    except (TypeError, ValueError):
        return {}


def _semantic_embedding_available(embedding_count: int = 0) -> bool:
    """UI contract: true when a live embedder exists or chunks already carry vectors."""
    if int(embedding_count or 0) > 0:
        return True
    try:
        from app.infrastructure.rag import get_default_embedder

        return get_default_embedder() is not None
    except RECOVERABLE_ERRORS:
        return False


class VectorIndexService:
    """Own the embedding adapter and persistent vector index projection."""

    def __init__(
        self,
        *,
        backend: DatasetVectorIndexBackend | None,
        embedder: Callable[[str], list[float]] | None,
    ) -> None:
        self.backend = backend
        self.embedder = embedder

    def _query_vector_index_candidates(
        self,
        *,
        dataset_id: str,
        query: str,
        top_k: int,
        tenant_id: str,
        version: str | int,
        metadata_filter: dict[str, Any],
    ) -> list[RetrievedChunk] | None:
        if self.backend is None or self.embedder is None:
            return None
        try:
            query_vector = self.embedder(query)
            if not isinstance(query_vector, list) or not query_vector:
                return None
            return self.backend.query(
                dataset_id,
                [float(value) for value in query_vector],
                top_k=top_k,
                tenant_id=tenant_id,
                version=version,
                metadata_filter=metadata_filter,
            )
        except RECOVERABLE_ERRORS:
            return None

    def _sync_vector_index_locked(self, state: _DatasetState) -> None:
        if self.backend is None:
            state.index["vector_backend_sync_status"] = "disabled"
            return
        try:
            count = self.backend.replace_dataset(state.dataset_id, state.chunks)
            state.index["vector_backend_sync_status"] = "synced"
            state.index["vector_backend_synced_chunks"] = count
            state.index["vector_backend_synced_at"] = _utc_now_iso()
        except RECOVERABLE_ERRORS as exc:
            state.index["vector_backend_sync_status"] = "failed"
            state.index["vector_backend_error"] = str(exc)

    def _vector_index_backend_name(self) -> str:
        if self.backend is None:
            return "none"
        return str(getattr(self.backend, "backend_name", "vector_index"))

    def _vector_index_status(self, dataset_id: str) -> dict[str, Any]:
        if self.backend is None:
            return {
                "backend": "none",
                "persistent": False,
                "dataset_id": dataset_id,
                "chunk_count": 0,
                "index_exists": False,
            }
        try:
            return dict(self.backend.status(dataset_id))
        except RECOVERABLE_ERRORS as exc:
            return {
                "backend": self._vector_index_backend_name(),
                "persistent": True,
                "dataset_id": dataset_id,
                "chunk_count": 0,
                "index_exists": False,
                "status": "failed",
                "error": str(exc),
            }

    def _refresh_index_metadata(self, state: _DatasetState) -> None:
        embedding_count = sum(
            1
            for chunk in state.chunks
            if isinstance(chunk.metadata, dict)
            and isinstance(chunk.metadata.get("_embedding"), list)
        )
        vector_status = self._vector_index_status(state.dataset_id)
        previous = dict(state.index or {})
        state.index = {
            "schema_version": 2,
            "retriever": "hybrid_bm25_vector",
            "reranker": "lexical_overlap_v1",
            "document_count": len(state.documents),
            "chunk_count": len(state.chunks),
            "embedding_count": embedding_count,
            "embedding_persisted": embedding_count > 0,
            "vector_backend": vector_status,
            "vector_backend_name": vector_status.get("backend", self._vector_index_backend_name()),
            "vector_backend_chunk_count": int(vector_status.get("chunk_count") or 0),
            "vector_backend_persistent": bool(vector_status.get("persistent")),
            "vector_backend_sync_status": previous.get("vector_backend_sync_status", ""),
            "vector_backend_synced_chunks": int(previous.get("vector_backend_synced_chunks") or 0),
            "vector_backend_synced_at": str(previous.get("vector_backend_synced_at") or ""),
            "vector_backend_error": str(previous.get("vector_backend_error") or ""),
            "updated_at": _utc_now_iso(),
        }
