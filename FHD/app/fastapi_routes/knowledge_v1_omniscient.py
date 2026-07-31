"""Omniscient knowledge routes (extracted from knowledge_v1 for source-governance)."""
from __future__ import annotations

from typing import Any, cast

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.fastapi_routes.knowledge_v1 import (
    QueryRequest,
    _dataset_access_context_from_request,
    _dataset_admin_access,
    _knowledge_runtime_snapshot,
    _public_dataset_payload,
)
from app.infrastructure.rag import is_rag_enabled

router = APIRouter(prefix="/api/knowledge/v1", tags=["knowledge-v1"])


@router.get("/omniscient")
def omniscient_overview(request: Request) -> dict[str, Any]:
    """Admin/full-knowledge overview across all governed datasets."""
    from app.application.dataset_rag_app_service import get_dataset_rag_app_service

    access = _dataset_access_context_from_request(request)
    if not _dataset_admin_access(access):
        return cast(
            "dict[str, Any]",
            JSONResponse(
                {
                    "success": False,
                    "error_code": "dataset_admin_required",
                    "message": "全知知识视图仅限管理员",
                },
                status_code=403,
            ),
        )
    overview = get_dataset_rag_app_service().status(access_context=access)
    snap = _knowledge_runtime_snapshot(request)
    datasets = overview.get("datasets") if isinstance(overview, dict) else {}
    return cast(
        "dict[str, Any]",
        _public_dataset_payload(
            {
                "success": True,
                "omniscient": True,
                "rag_enabled": snap["rag_enabled"],
                "embedder_available": snap["embedder_available"],
                "semantic_embedding_available": snap["semantic_embedding_available"],
                "recommended_dataset_id": snap["recommended_dataset_id"],
                "dataset_count": snap["dataset_count"],
                "document_count": snap["dataset_document_count"],
                "chunk_count": snap["dataset_chunk_count"],
                "datasets": datasets if isinstance(datasets, dict) else {},
                "is_admin": bool(getattr(access, "is_admin", False)) if access else False,
            }
        ),
    )


@router.post("/omniscient/query")
def omniscient_query(req: QueryRequest, request: Request) -> dict[str, Any]:
    """Query across all datasets visible to the caller (admin = full platform)."""
    from app.application.dataset_rag_app_service import get_dataset_rag_app_service

    access = _dataset_access_context_from_request(request)
    if not _dataset_admin_access(access):
        return cast(
            "dict[str, Any]",
            JSONResponse(
                {
                    "success": False,
                    "error_code": "dataset_admin_required",
                    "message": "全知知识检索仅限管理员",
                },
                status_code=403,
            ),
        )
    service = get_dataset_rag_app_service()
    overview = service.status(access_context=access)
    datasets = overview.get("datasets") if isinstance(overview, dict) else {}
    merged: list[dict[str, Any]] = []
    if isinstance(datasets, dict):
        per_ds = max(1, min(int(req.top_k), 20))
        for dataset_id in datasets:
            result = service.query(
                dataset_id=str(dataset_id),
                query=req.query,
                top_k=per_ds,
                access_context=access,
                rerank=True,
            )
            if not result.get("success"):
                continue
            for chunk in result.get("chunks") or []:
                if not isinstance(chunk, dict):
                    continue
                item = dict(chunk)
                item["dataset_id"] = str(dataset_id)
                merged.append(item)
    merged.sort(key=lambda item: float(item.get("score") or 0.0), reverse=True)
    top = merged[: max(1, min(int(req.top_k), 50))]
    return {
        "success": True,
        "query": req.query,
        "chunks": top,
        "citations": [],
        "rag_enabled": is_rag_enabled(),
        "omniscient": True,
        "dataset_hits": len({str(c.get("dataset_id") or "") for c in top if c.get("dataset_id")}),
    }

