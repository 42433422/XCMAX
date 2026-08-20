# mypy: disable-error-code="no-any-return, valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.fastapi_routes.knowledge_v1")


@_facade().router.post("/datasets/{dataset_id}/memories/query")
def query_persy_memories(
    dataset_id: str, req: _facade().PersyMemoryQueryRequest, request: _facade().Request
) -> _facade().JSONResponse:
    unsupported = _facade()._persy_dataset_error(dataset_id)
    if unsupported is not None:
        return unsupported
    payload = (
        _facade()
        ._persy_memory_service()
        .query(
            access_context=_facade()._dataset_access_context_from_request(request),
            query=req.query,
            top_k=req.top_k,
            reinforce=req.reinforce,
        )
    )
    code = str(payload.get("error_code") or "")
    status_code = 200 if payload.get("success") else 400
    if code in {"dataset_permission_denied", "persy_memory_scope_missing"}:
        status_code = 403
    return _facade().JSONResponse(payload, status_code=status_code)


@_facade().router.post("/datasets/{dataset_id}/memories/{memory_id}/confirm")
def confirm_persy_memory(
    dataset_id: str,
    memory_id: str,
    req: _facade().PersyMemoryMutationRequest,
    request: _facade().Request,
) -> _facade().JSONResponse:
    unsupported = _facade()._persy_dataset_error(dataset_id)
    if unsupported is not None:
        return unsupported
    correction = {
        key: getattr(req, key)
        for key in ("key", "value", "memory_type", "confidence")
        if key in req.model_fields_set
    }
    payload = (
        _facade()
        ._persy_memory_service()
        .mutate(
            access_context=_facade()._dataset_access_context_from_request(request),
            memory_id=memory_id,
            action="confirm",
            patch=correction,
            reason=req.reason,
        )
    )
    return _facade()._persy_memory_response(payload, request=request, action="confirm")


@_facade().router.post("/datasets/{dataset_id}/memories/{memory_id}/reject")
def reject_persy_memory(
    dataset_id: str,
    memory_id: str,
    req: _facade().PersyMemoryMutationRequest,
    request: _facade().Request,
) -> _facade().JSONResponse:
    unsupported = _facade()._persy_dataset_error(dataset_id)
    if unsupported is not None:
        return unsupported
    payload = (
        _facade()
        ._persy_memory_service()
        .mutate(
            access_context=_facade()._dataset_access_context_from_request(request),
            memory_id=memory_id,
            action="reject",
            reason=req.reason,
        )
    )
    return _facade()._persy_memory_response(payload, request=request, action="reject")


@_facade().router.patch("/datasets/{dataset_id}/memories/{memory_id}")
def correct_persy_memory(
    dataset_id: str,
    memory_id: str,
    req: _facade().PersyMemoryMutationRequest,
    request: _facade().Request,
) -> _facade().JSONResponse:
    unsupported = _facade()._persy_dataset_error(dataset_id)
    if unsupported is not None:
        return unsupported
    patch = {key: getattr(req, key) for key in ("key", "value") if key in req.model_fields_set}
    payload = (
        _facade()
        ._persy_memory_service()
        .mutate(
            access_context=_facade()._dataset_access_context_from_request(request),
            memory_id=memory_id,
            action="correct",
            patch=patch,
            reason=req.reason,
        )
    )
    return _facade()._persy_memory_response(payload, request=request, action="correct")


@_facade().router.delete("/datasets/{dataset_id}/memories/{memory_id}")
def delete_persy_memory(
    dataset_id: str,
    memory_id: str,
    request: _facade().Request,
    reason: str = _facade().FastAPIQuery("", max_length=500),
) -> _facade().JSONResponse:
    unsupported = _facade()._persy_dataset_error(dataset_id)
    if unsupported is not None:
        return unsupported
    payload = (
        _facade()
        ._persy_memory_service()
        .mutate(
            access_context=_facade()._dataset_access_context_from_request(request),
            memory_id=memory_id,
            action="delete",
            reason=reason,
        )
    )
    return _facade()._persy_memory_response(payload, request=request, action="delete")


@_facade().router.post("/datasets/{dataset_id}/versions/diff")
def diff_dataset_versions(
    dataset_id: str, req: _facade().DatasetVersionDiffRequest, request: _facade().Request
) -> _facade().JSONResponse:
    return _facade()._run_dataset_rag_agent(
        request=request,
        action="diff_versions",
        route_path="/api/knowledge/v1/datasets/{dataset_id}/versions/diff",
        params={
            "dataset_id": dataset_id,
            "source": req.source,
            "tenant_id": req.tenant_id,
            "from_version": req.from_version,
            "to_version": req.to_version,
        },
    )


@_facade().router.post("/datasets/{dataset_id}/versions/rollback")
def rollback_dataset_version(
    dataset_id: str, req: _facade().DatasetRollbackRequest, request: _facade().Request
) -> _facade().JSONResponse:
    return _facade()._run_dataset_rag_agent(
        request=request,
        action="rollback_version",
        route_path="/api/knowledge/v1/datasets/{dataset_id}/versions/rollback",
        params={
            "dataset_id": dataset_id,
            "source": req.source,
            "tenant_id": req.tenant_id,
            "target_version": req.target_version,
            "metadata": req.metadata,
        },
    )


@_facade().router.post("/datasets/{dataset_id}/index/rebuild")
def rebuild_dataset_index(
    dataset_id: str, req: _facade().DatasetRebuildRequest, request: _facade().Request
) -> _facade().JSONResponse:
    return _facade()._run_dataset_rag_agent(
        request=request,
        action="rebuild_index",
        route_path="/api/knowledge/v1/datasets/{dataset_id}/index/rebuild",
        params={
            "dataset_id": dataset_id,
            "tenant_id": req.tenant_id,
            "metadata_filter": req.metadata_filter,
            "background": req.background,
            "max_attempts": req.max_attempts,
        },
    )


@_facade().router.post("/datasets/{dataset_id}/index/rebuild/{job_id}/cancel")
def cancel_dataset_rebuild_job(
    dataset_id: str, job_id: str, request: _facade().Request
) -> _facade().JSONResponse:
    return _facade()._run_dataset_rag_agent(
        request=request,
        action="cancel_rebuild",
        route_path="/api/knowledge/v1/datasets/{dataset_id}/index/rebuild/{job_id}/cancel",
        params={"dataset_id": dataset_id, "job_id": job_id},
    )


@_facade().router.get("/datasets/{dataset_id}/index/rebuild/{job_id}")
def dataset_rebuild_job(
    dataset_id: str, job_id: str, request: _facade().Request
) -> dict[str, _facade().Any]:
    from app.application.dataset_rag_app_service import get_dataset_rag_app_service

    return _facade().cast(
        "dict[str, Any]",
        _facade()._public_dataset_payload(
            get_dataset_rag_app_service().get_rebuild_job(
                dataset_id,
                job_id,
                access_context=_facade()._dataset_access_context_from_request(request),
            )
        ),
    )


@_facade().router.delete("/datasets/{dataset_id}/documents/{document_id}")
def delete_dataset_document(
    dataset_id: str, document_id: str, request: _facade().Request
) -> _facade().JSONResponse:
    return _facade()._run_dataset_rag_agent(
        request=request,
        action="delete_document",
        route_path="/api/knowledge/v1/datasets/{dataset_id}/documents/{document_id}",
        params={"dataset_id": dataset_id, "document_id": document_id},
    )


@_facade().router.get("/status", response_model=_facade().StatusResponse)
def status(request: _facade().Request) -> _facade().StatusResponse:
    snap = _facade()._knowledge_runtime_snapshot(request)
    return _facade().StatusResponse(
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


@_facade().router.get("/health")
def health(request: _facade().Request) -> dict[str, _facade().Any]:
    snap = _facade()._knowledge_runtime_snapshot(request)
    return {"success": True, **snap}


@_facade().router.get("/omniscient")
def omniscient_overview(request: _facade().Request) -> dict[str, _facade().Any]:
    """Admin/full-knowledge overview across all governed datasets."""
    from app.application.dataset_rag_app_service import get_dataset_rag_app_service

    access = _facade()._dataset_access_context_from_request(request)
    overview = get_dataset_rag_app_service().status(access_context=access)
    snap = _facade()._knowledge_runtime_snapshot(request)
    datasets = overview.get("datasets") if isinstance(overview, dict) else {}
    return _facade().cast(
        "dict[str, Any]",
        _facade()._public_dataset_payload(
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


@_facade().router.post("/omniscient/query")
def omniscient_query(
    req: _facade().QueryRequest, request: _facade().Request
) -> dict[str, _facade().Any]:
    """Query across all datasets visible to the caller (admin = full platform)."""
    from app.application.dataset_rag_app_service import get_dataset_rag_app_service

    access = _facade()._dataset_access_context_from_request(request)
    service = get_dataset_rag_app_service()
    overview = service.status(access_context=access)
    datasets = overview.get("datasets") if isinstance(overview, dict) else {}
    merged: list[dict[str, _facade().Any]] = []
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
        "rag_enabled": _facade().is_rag_enabled(),
        "omniscient": True,
        "dataset_hits": len({str(c.get("dataset_id") or "") for c in top if c.get("dataset_id")}),
    }
