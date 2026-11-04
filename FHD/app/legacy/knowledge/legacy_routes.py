"""Tenant-scoped legacy text ingestion and retrieval."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from fastapi import APIRouter, Depends, Request

from app.fastapi_routes.knowledge.schemas import (
    IngestRequest,
    IngestResponse,
    QueryRequest,
    QueryResponse,
)
from app.legacy.knowledge.legacy_index import KnowledgeIndex


class LegacyMirror(Protocol):
    def __call__(
        self,
        *,
        text: str,
        source: str,
        chunk_strategy: str,
        chunk_size: int,
        chunk_overlap: int,
        request: Request | None = None,
    ) -> dict[str, Any]: ...


class LegacyRoutes:
    """Tenant-scoped legacy text ingestion and retrieval."""

    def __init__(
        self,
        *,
        index: Callable[[], KnowledgeIndex],
        mirror: Callable[[], LegacyMirror],
        tenant_key: Callable[[Request | None], str | None],
        rag_enabled: Callable[[], bool],
        require_tenant: Callable[[Request], None],
    ) -> None:
        router = self.router = APIRouter()

        @router.post(
            "/ingest", response_model=IngestResponse, dependencies=[Depends(require_tenant)]
        )
        def ingest(req: IngestRequest, request: Request) -> IngestResponse:
            try:
                count = index().ingest(
                    req.text,
                    req.source,
                    req.chunk_strategy,
                    req.chunk_size,
                    req.chunk_overlap,
                    tenant_id=tenant_key(request),
                )
                mirrored = mirror()(
                    text=req.text,
                    source=req.source,
                    chunk_strategy=req.chunk_strategy,
                    chunk_size=req.chunk_size,
                    chunk_overlap=req.chunk_overlap,
                    request=request,
                )
                mirror_note = ""
                if mirrored.get("success"):
                    mirror_note = f"；已同步 Persy +{int(mirrored.get('chunk_count') or 0)} chunk"
                return IngestResponse(
                    success=True,
                    chunk_count=count,
                    source=req.source,
                    strategy=req.chunk_strategy,
                    message=f"已入库 {count} 个 chunk{mirror_note}",
                )
            except (ValueError, TypeError) as e:
                return IngestResponse(
                    success=False,
                    chunk_count=0,
                    source=req.source,
                    strategy=req.chunk_strategy,
                    message=str(e),
                )

        self.ingest = ingest

        @router.post("/query", response_model=QueryResponse, dependencies=[Depends(require_tenant)])
        def query(req: QueryRequest, request: Request) -> QueryResponse:
            chunks = index().query(req.query, req.top_k, tenant_id=tenant_key(request))
            return QueryResponse(
                success=True,
                query=req.query,
                chunks=[
                    {
                        "chunk_index": c.chunk_index,
                        "text": c.text,
                        "score": c.score,
                        "source": c.source,
                    }
                    for c in chunks
                ],
                citations=[],
                rag_enabled=rag_enabled(),
            )

        self.query = query
