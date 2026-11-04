"""Knowledge health, runtime status and cross-dataset search."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Request

from .read_views import DatasetViews
from .schemas import QueryRequest, StatusResponse


class OverviewRoutes:
    """Knowledge health, runtime status and cross-dataset search."""

    def __init__(
        self,
        *,
        views: Callable[[], DatasetViews],
        snapshot: Callable[[], Callable[[Request | None], dict[str, Any]]],
        rag_enabled: Callable[[], Callable[[], bool]],
    ) -> None:
        router = self.router = APIRouter()

        @router.get("/status", response_model=StatusResponse)
        def status(request: Request) -> StatusResponse:
            snap = snapshot()(request)
            return StatusResponse(
                rag_enabled=bool(snap["rag_enabled"]),
                embedder_available=bool(snap["embedder_available"]),
                indexed_sources=int(snap["indexed_sources"]),
                indexed_chunks=int(snap["indexed_chunks"]),
                dataset_count=int(snap["dataset_count"]),
                dataset_document_count=int(snap["dataset_document_count"]),
                dataset_chunk_count=int(snap["dataset_chunk_count"]),
                semantic_embedding_available=bool(snap["semantic_embedding_available"]),
                recommended_dataset_id=str(snap["recommended_dataset_id"]),
            )

        self.status = status

        @router.get("/health")
        def health(request: Request) -> dict[str, Any]:
            snap = snapshot()(request)
            return {"success": True, **snap}

        self.health = health

        @router.get("/omniscient")
        def omniscient_overview(request: Request) -> dict[str, Any]:
            """Admin/full-knowledge overview across all governed datasets."""
            return views().overview(request, snapshot=snapshot())

        self.omniscient_overview = omniscient_overview

        @router.post("/omniscient/query")
        def omniscient_query(req: QueryRequest, request: Request) -> dict[str, Any]:
            """Query across all datasets visible to the caller (admin = full platform)."""
            return views().query_all(req, request, rag_enabled=rag_enabled())

        self.omniscient_query = omniscient_query
