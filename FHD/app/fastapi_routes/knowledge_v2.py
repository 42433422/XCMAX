"""Persy Knowledge API v2 - Unified Memory Graph.

与 v1 共存，路由前缀 /api/knowledge/v2。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.application.memory_graph_app_service import MemoryGraphAppService
from app.db.models.memory_graph import MemoryNodeType


def _parse_node_type(value: str | None) -> MemoryNodeType | None:
    if not value:
        return None
    try:
        return MemoryNodeType(value)
    except ValueError:
        return None


class IngestNodeRequest(BaseModel):
    type: str = Field(
        ..., description="constraint|convention|lesson|episodic|preference|entity|doc|artifact"
    )
    title: str = Field(..., min_length=1, max_length=160)
    content: str = Field("", max_length=5_000_000)
    scope: str = Field("tenant", max_length=20)
    scope_id: str = Field("", max_length=160)
    tags: list[str] = Field(default_factory=list)
    source_policy: str = Field("auto_active", description="auto_active|needs_confirm")


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    scope: str = Field("tenant")
    scope_id: str = Field("")
    type: str | None = Field(None, description="可选节点类型过滤")
    top_k: int = Field(10, ge=1, le=50)


def create_v2_router(app_service: MemoryGraphAppService) -> APIRouter:
    router = APIRouter(prefix="/api/knowledge/v2", tags=["knowledge-v2"])

    @router.get("/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "version": "v2", "memory_graph_enabled": True}

    @router.post("/nodes")
    def ingest_node(req: IngestNodeRequest) -> dict[str, Any]:
        node_type = _parse_node_type(req.type)
        if node_type is None:
            return {
                "success": False,
                "error_code": "invalid_node_type",
                "message": f"unknown type: {req.type}",
            }
        result = app_service.ingest_engineering(
            type=node_type,
            title=req.title,
            content=req.content,
            scope=req.scope,
            scope_id=req.scope_id,
            tags=req.tags,
        )
        return result

    @router.get("/nodes/active")
    def list_active(
        scope: str = Query(...),
        scope_id: str = Query(...),
        type: str | None = Query(None),
    ) -> dict[str, Any]:
        node_type = _parse_node_type(type)
        if node_type == MemoryNodeType.CONSTRAINT:
            nodes = app_service.get_active_constraints(scope=scope, scope_id=scope_id)
        elif node_type == MemoryNodeType.CONVENTION:
            nodes = app_service.get_active_conventions(scope=scope, scope_id=scope_id)
        else:
            # Phase 1: 只支持 constraint/convention，其他类型后续扩展
            nodes = []
            if node_type is None:
                nodes = app_service.get_active_constraints(scope=scope, scope_id=scope_id)
                nodes += app_service.get_active_conventions(scope=scope, scope_id=scope_id)
        return {"count": len(nodes), "nodes": nodes}

    @router.post("/search")
    def search(req: SearchRequest) -> dict[str, Any]:
        node_type = _parse_node_type(req.type)
        results = app_service.search_memory(
            query=req.query,
            scope=req.scope,
            scope_id=req.scope_id,
            node_type=node_type,
            top_k=req.top_k,
        )
        return {"count": len(results), "results": results}

    return router
