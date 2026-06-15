"""知识库 API（V1 简化版）。

Phase 3.3 交付：
  - POST /api/knowledge/v1/ingest   — 文本入库（语义分块 + 内存索引）
  - POST /api/knowledge/v1/query    — 检索（混合 + 引用）
  - GET  /api/knowledge/v1/status   — 健康检查
  - GET  /api/knowledge/v1/health   — 详细状态

生产应代理到 MODstore `/api/knowledge/v2/*`；本地开发可用此简化版。
"""

from __future__ import annotations

import logging
import threading
from typing import Any, cast

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.infrastructure.rag import (
    HybridRetriever,
    RetrievedChunk,
    SemanticChunker,
    get_default_embedder,
    is_rag_enabled,
)

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/api/knowledge/v1", tags=["knowledge-v1"])


class IngestRequest(BaseModel):
    text: str = Field(..., description="待入库文本")
    source: str = Field("default", description="来源标识")
    chunk_strategy: str = Field("semantic", description="semantic | fixed")
    chunk_size: int = Field(500, ge=50, le=5000)
    chunk_overlap: int = Field(50, ge=0, le=500)


class QueryRequest(BaseModel):
    query: str = Field(..., description="查询文本")
    top_k: int = Field(5, ge=1, le=50)
    include_citations: bool = Field(True, description="是否返回 [1][2] 引用")


class IngestResponse(BaseModel):
    success: bool
    chunk_count: int
    source: str
    strategy: str
    message: str = ""


class QueryResponse(BaseModel):
    success: bool
    query: str
    chunks: list[dict[str, Any]]
    citations: list[dict[str, Any]] = []
    rag_enabled: bool


class StatusResponse(BaseModel):
    rag_enabled: bool
    embedder_available: bool
    indexed_sources: int
    indexed_chunks: int


class _KnowledgeIndex:
    """进程内单例：保存所有 chunk + 检索器。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._chunker = SemanticChunker(embedder=get_default_embedder())
        self._retriever = HybridRetriever(embedder=get_default_embedder())
        self._chunks: list[RetrievedChunk] = []
        self._sources: set[str] = set()
        self._rebuild_needed: bool = True

    def ingest(
        self, text: str, source: str, strategy: str, chunk_size: int, chunk_overlap: int
    ) -> int:
        with self._lock:
            if strategy == "semantic":
                chunks = self._chunker.split_by_semantic(text)
            else:
                chunks = self._chunker.split_by_fixed(
                    text, chunk_size=chunk_size, chunk_overlap=chunk_overlap
                )
            base = len(self._chunks)
            for i, c in enumerate(chunks):
                self._chunks.append(
                    RetrievedChunk(
                        text=c.text,
                        score=0.0,
                        source=source,
                        chunk_index=base + i,
                        char_start=c.char_start,
                        char_end=c.char_end,
                        metadata={"source": source, "strategy": c.strategy},
                    )
                )
            self._sources.add(source)
            self._rebuild_needed = True
            return len(chunks)

    def query(self, q: str, top_k: int) -> list[RetrievedChunk]:
        with self._lock:
            if self._rebuild_needed:
                self._retriever.index(self._chunks)
                self._rebuild_needed = False
            return cast("list[Any]", self._retriever.retrieve(q))

    def status(self) -> dict[str, int]:
        with self._lock:
            return {
                "sources": len(self._sources),
                "chunks": len(self._chunks),
            }


_index = _KnowledgeIndex()


@router.post("/ingest", response_model=IngestResponse)
def ingest(req: IngestRequest) -> IngestResponse:
    try:
        count = _index.ingest(
            req.text, req.source, req.chunk_strategy, req.chunk_size, req.chunk_overlap
        )
        return IngestResponse(
            success=True,
            chunk_count=count,
            source=req.source,
            strategy=req.chunk_strategy,
            message=f"已入库 {count} 个 chunk",
        )
    except (ValueError, TypeError) as e:
        return IngestResponse(
            success=False,
            chunk_count=0,
            source=req.source,
            strategy=req.chunk_strategy,
            message=str(e),
        )


@router.post("/query", response_model=QueryResponse)
def query(req: QueryRequest) -> QueryResponse:
    chunks = _index.query(req.query, req.top_k)
    return QueryResponse(
        success=True,
        query=req.query,
        chunks=[
            {"chunk_index": c.chunk_index, "text": c.text, "score": c.score, "source": c.source}
            for c in chunks
        ],
        citations=[],
        rag_enabled=is_rag_enabled(),
    )


@router.get("/status", response_model=StatusResponse)
def status() -> StatusResponse:
    s = _index.status()
    return StatusResponse(
        rag_enabled=is_rag_enabled(),
        embedder_available=get_default_embedder() is not None,
        indexed_sources=s["sources"],
        indexed_chunks=s["chunks"],
    )


@router.get("/health")
def health() -> dict[str, Any]:
    s = _index.status()
    return {
        "success": True,
        "rag_enabled": is_rag_enabled(),
        "embedder_available": get_default_embedder() is not None,
        "indexed_sources": s["sources"],
        "indexed_chunks": s["chunks"],
    }
