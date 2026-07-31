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


# 模块级单例：lazy 初始化，避免在 import 时即创建 DB 连接。
_app_service_singleton: MemoryGraphAppService | None = None


def get_default_app_service() -> MemoryGraphAppService:
    """懒构造默认的 MemoryGraphAppService。

    供 ``create_v2_router(app_service=None)`` 在主应用装配时使用：
    复用应用全局 SessionLocal，确保与 v1 路由看到同一数据库。
    """
    global _app_service_singleton
    if _app_service_singleton is not None:
        return _app_service_singleton

    # 延迟导入，避免在模块加载阶段触发 DB 引擎构造。
    from app.application.memory_update_engine import MemoryUpdateEngine
    from app.db import SessionLocal
    from app.infrastructure.memory_graph_store import MemoryGraphStore

    store = MemoryGraphStore(SessionLocal())
    update_engine = MemoryUpdateEngine(store)
    _app_service_singleton = MemoryGraphAppService(store=store, update_engine=update_engine)
    return _app_service_singleton


def reset_default_app_service() -> None:
    """重置单例，仅用于测试。"""
    global _app_service_singleton
    _app_service_singleton = None


def create_v2_router(app_service: MemoryGraphAppService | None = None) -> APIRouter:
    """构造 v2 路由器。

    ``app_service`` 为 None 时使用 ``get_default_app_service()`` 懒初始化，
    使主应用可在不显式注入依赖的情况下挂载 v2 路由。
    """
    service = app_service if app_service is not None else get_default_app_service()
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
        result = service.ingest_engineering(
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
            nodes = service.get_active_constraints(scope=scope, scope_id=scope_id)
        elif node_type == MemoryNodeType.CONVENTION:
            nodes = service.get_active_conventions(scope=scope, scope_id=scope_id)
        else:
            # Phase 1: 只支持 constraint/convention，其他类型后续扩展
            nodes = []
            if node_type is None:
                nodes = service.get_active_constraints(scope=scope, scope_id=scope_id)
                nodes += service.get_active_conventions(scope=scope, scope_id=scope_id)
        return {"count": len(nodes), "nodes": nodes}

    @router.get("/nodes/{node_id}")
    def get_node(node_id: str) -> dict[str, Any]:
        node = service.get_node(node_id)
        if node is None:
            return {
                "success": False,
                "error_code": "node_not_found",
                "message": f"node {node_id} not found",
            }
        return {"success": True, "node": node}

    @router.get("/nodes/{node_id}/backlinks")
    def get_backlinks(node_id: str) -> dict[str, Any]:
        backlinks = service.list_backlinks(node_id)
        return {"count": len(backlinks), "backlinks": backlinks}

    @router.get("/export")
    def export(
        scope: str = Query(...),
        scope_id: str = Query(...),
        type: str | None = Query(None),
        format: str = Query("markdown"),
    ) -> dict[str, Any]:
        if format != "markdown":
            return {
                "success": False,
                "error_code": "unsupported_format",
                "message": f"format {format} not supported, only 'markdown'",
            }
        node_type = _parse_node_type(type)
        markdown = service.export_scope(scope=scope, scope_id=scope_id, node_type=node_type)
        return {
            "success": True,
            "format": "markdown",
            "scope": scope,
            "scope_id": scope_id,
            "markdown": markdown,
        }

    @router.post("/nodes/{node_id}/confirm")
    def confirm_node(node_id: str) -> dict[str, Any]:
        return service.confirm_node(node_id)

    @router.post("/nodes/{node_id}/reject")
    def reject_node(node_id: str, reason: str = Query("")) -> dict[str, Any]:
        return service.reject_node(node_id, reason=reason)

    @router.post("/search")
    def search(req: SearchRequest) -> dict[str, Any]:
        node_type = _parse_node_type(req.type)
        results = service.search_memory(
            query=req.query,
            scope=req.scope,
            scope_id=req.scope_id,
            node_type=node_type,
            top_k=req.top_k,
        )
        return {"count": len(results), "results": results}

    return router
