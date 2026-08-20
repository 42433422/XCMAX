# mypy: disable-error-code="no-any-return, valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.fastapi_routes.knowledge_v1")


def _knowledge_runtime_snapshot(
    request: _facade().Request | None = None,
) -> dict[str, _facade().Any]:
    legacy = _facade()._index.status()
    dataset_count = 0
    dataset_docs = 0
    dataset_chunks = 0
    recommended = _facade()._PERSY_DATASET_ID
    try:
        from app.application.dataset_rag_app_service import get_dataset_rag_app_service

        access = (
            _facade()._dataset_access_context_from_request(request) if request is not None else None
        )
        overview = get_dataset_rag_app_service().status(access_context=access)
        datasets = overview.get("datasets") if isinstance(overview, dict) else {}
        if isinstance(datasets, dict):
            dataset_count = len(datasets)
            dataset_docs = int(overview.get("document_count") or 0)
            dataset_chunks = int(overview.get("chunk_count") or 0)
            nonempty = [
                (key, int((val or {}).get("document_count") or 0))
                for key, val in datasets.items()
                if isinstance(val, dict)
            ]
            nonempty.sort(key=lambda item: item[1], reverse=True)
            persy_docs = next((n for key, n in nonempty if key == _facade()._PERSY_DATASET_ID), 0)
            if persy_docs <= 0 and nonempty and (nonempty[0][1] > 0):
                recommended = nonempty[0][0]
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.debug("dataset overview for health failed: %s", exc)
    embedder_ok = _facade().get_default_embedder() is not None
    return {
        "rag_enabled": _facade().is_rag_enabled(),
        "embedder_available": embedder_ok,
        "semantic_embedding_available": embedder_ok,
        "indexed_sources": int(legacy.get("sources") or 0) + dataset_docs,
        "indexed_chunks": int(legacy.get("chunks") or 0) + dataset_chunks,
        "legacy_indexed_sources": int(legacy.get("sources") or 0),
        "legacy_indexed_chunks": int(legacy.get("chunks") or 0),
        "dataset_count": dataset_count,
        "dataset_document_count": dataset_docs,
        "dataset_chunk_count": dataset_chunks,
        "recommended_dataset_id": recommended,
    }


@_facade().router.post("/ingest", response_model=_facade().IngestResponse)
def ingest(req: _facade().IngestRequest, request: _facade().Request) -> _facade().IngestResponse:
    try:
        count = _facade()._index.ingest(
            req.text, req.source, req.chunk_strategy, req.chunk_size, req.chunk_overlap
        )
        mirrored = _facade()._mirror_ingest_to_persy(
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
        return _facade().IngestResponse(
            success=True,
            chunk_count=count,
            source=req.source,
            strategy=req.chunk_strategy,
            message=f"已入库 {count} 个 chunk{mirror_note}",
        )
    except (ValueError, TypeError) as e:
        return _facade().IngestResponse(
            success=False,
            chunk_count=0,
            source=req.source,
            strategy=req.chunk_strategy,
            message=str(e),
        )


@_facade().router.post("/query", response_model=_facade().QueryResponse)
def query(req: _facade().QueryRequest) -> _facade().QueryResponse:
    chunks = _facade()._index.query(req.query, req.top_k)
    return _facade().QueryResponse(
        success=True,
        query=req.query,
        chunks=[
            {"chunk_index": c.chunk_index, "text": c.text, "score": c.score, "source": c.source}
            for c in chunks
        ],
        citations=[],
        rag_enabled=_facade().is_rag_enabled(),
    )


@_facade().router.post("/datasets/{dataset_id}/documents")
def ingest_dataset_document(
    dataset_id: str, req: _facade().DatasetDocumentIngestRequest, request: _facade().Request
) -> _facade().JSONResponse:
    return _facade()._run_dataset_rag_agent(
        request=request,
        action="ingest_document",
        route_path="/api/knowledge/v1/datasets/{dataset_id}/documents",
        params={
            "dataset_id": dataset_id,
            "source": req.source,
            "text": req.text,
            "file_path": req.file_path,
            "document_id": req.document_id,
            "chunk_strategy": req.chunk_strategy,
            "chunk_size": req.chunk_size,
            "chunk_overlap": req.chunk_overlap,
            "metadata": req.metadata,
            "tenant_id": req.tenant_id,
            "version": req.version,
            "version_label": req.version_label,
        },
    )


@_facade().router.post("/datasets/{dataset_id}/documents/upload")
async def upload_dataset_document(
    dataset_id: str,
    request: _facade().Request,
    file: _facade().UploadFile = _facade().File(...),
    source: str = _facade().Form(""),
    tenant_id: str = _facade().Form(""),
    version: str = _facade().Form(""),
    version_label: str = _facade().Form(""),
    chunk_strategy: str = _facade().Form("semantic"),
) -> _facade().JSONResponse:
    raw_name = _facade().Path(str(file.filename or "document")).name
    suffix = _facade().Path(raw_name).suffix.lower()
    stem_limit = max(1, 240 - len(suffix))
    original_name = f"{_facade().Path(raw_name).stem[:stem_limit]}{suffix}"
    if suffix not in _facade()._DATASET_UPLOAD_EXTENSIONS:
        return _facade().JSONResponse(
            {
                "success": False,
                "message": f"不支持的资料类型: {suffix or '无扩展名'}",
                "allowed_extensions": sorted(_facade()._DATASET_UPLOAD_EXTENSIONS),
            },
            status_code=400,
        )
    source_label = str(source or original_name).strip() or original_name
    if len(source_label) > 300:
        return _facade().JSONResponse(
            {"success": False, "message": "资料名称不能超过 300 个字符"}, status_code=400
        )
    if any(
        (
            len(str(value or "")) > limit
            for value, limit in ((tenant_id, 160), (version, 80), (version_label, 120))
        )
    ):
        return _facade().JSONResponse(
            {"success": False, "message": "上传参数过长"}, status_code=400
        )
    from app.utils.path_io.path_utils import get_upload_dir

    safe_dataset = _facade().re.sub("[^A-Za-z0-9._-]+", "_", str(dataset_id or "default"))[:100]
    upload_dir = (
        _facade().Path(get_upload_dir()).resolve() / "knowledge" / (safe_dataset or "default")
    )
    upload_dir.mkdir(parents=True, exist_ok=True)
    saved_path = upload_dir / f"{_facade().uuid.uuid4().hex}{suffix}"
    size = 0
    try:
        with saved_path.open("wb") as target:
            while chunk := (await file.read(1024 * 1024)):
                size += len(chunk)
                if size > _facade()._DATASET_UPLOAD_MAX_BYTES:
                    raise ValueError("资料文件不能超过 25 MB")
                target.write(chunk)
    except (OSError, ValueError) as exc:
        saved_path.unlink(missing_ok=True)
        return _facade().JSONResponse({"success": False, "message": str(exc)}, status_code=400)
    finally:
        await file.close()
    response = _facade()._run_dataset_rag_agent(
        request=request,
        action="ingest_document",
        route_path="/api/knowledge/v1/datasets/{dataset_id}/documents/upload",
        params={
            "dataset_id": dataset_id,
            "source": source_label,
            "file_path": str(saved_path),
            "text": "",
            "document_id": "",
            "chunk_strategy": chunk_strategy
            if chunk_strategy in {"semantic", "fixed"}
            else "semantic",
            "chunk_size": 500,
            "chunk_overlap": 50,
            "metadata": {
                "original_file_name": original_name,
                "upload_size_bytes": size,
                "entrypoint": "persy_knowledge_upload",
            },
            "tenant_id": tenant_id,
            "version": version,
            "version_label": version_label,
        },
    )
    if response.status_code >= 400:
        try:
            saved_path.unlink(missing_ok=True)
        except OSError:
            _facade().logger.warning("Failed to clean rejected Persy upload: %s", saved_path)
    return response


@_facade().router.post("/datasets/{dataset_id}/query")
def query_dataset(
    dataset_id: str, req: _facade().DatasetQueryRequest, request: _facade().Request
) -> _facade().JSONResponse:
    return _facade()._run_dataset_rag_agent(
        request=request,
        action="query",
        route_path="/api/knowledge/v1/datasets/{dataset_id}/query",
        params={
            "dataset_id": dataset_id,
            "query": req.query,
            "top_k": req.top_k,
            "include_answer": req.include_answer,
            "tenant_id": req.tenant_id,
            "version": req.version,
            "metadata_filter": req.metadata_filter,
            "rerank": req.rerank,
        },
    )


@_facade().router.get("/datasets")
def dataset_status_all(request: _facade().Request) -> dict[str, _facade().Any]:
    from app.application.dataset_rag_app_service import get_dataset_rag_app_service

    return _facade().cast(
        "dict[str, Any]",
        _facade()._public_dataset_payload(
            get_dataset_rag_app_service().status(
                access_context=_facade()._dataset_access_context_from_request(request)
            )
        ),
    )


@_facade().router.get("/datasets/{dataset_id}/status")
def dataset_status(
    dataset_id: str,
    request: _facade().Request,
    include_documents: bool = _facade().FastAPIQuery(
        True,
        description="When false, omit document rows (counts/index only) for lighter graph HUD loads",
    ),
) -> dict[str, _facade().Any]:
    from app.application.dataset_rag_app_service import get_dataset_rag_app_service

    access = _facade()._dataset_access_context_from_request(request)
    return _facade().cast(
        "dict[str, Any]",
        _facade()._public_dataset_payload(
            get_dataset_rag_app_service().status(
                dataset_id,
                tenant_id=_facade()._dataset_read_tenant_scope(access),
                access_context=access,
                include_documents=bool(include_documents),
            )
        ),
    )


@_facade().router.get("/datasets/{dataset_id}/graph")
def dataset_graph(
    dataset_id: str,
    request: _facade().Request,
    limit: int = _facade().FastAPIQuery(80, ge=20, le=240),
) -> dict[str, _facade().Any]:
    from app.application.dataset_rag_app_service import get_dataset_rag_app_service
    from app.application.persy_memory_app_service import merge_memory_graph

    access = _facade()._dataset_access_context_from_request(request)
    tenant_id = _facade()._dataset_read_tenant_scope(access)
    memory_graph: dict[str, _facade().Any] = {
        "success": True,
        "nodes": [],
        "edges": [],
        "stats": {},
    }
    graph_limit = limit
    if dataset_id == _facade()._PERSY_DATASET_ID:
        memory_graph = (
            _facade()
            ._persy_memory_service()
            .graph(access_context=access, limit=max(8, min(40, int(limit * 0.28))))
        )
        if memory_graph.get("nodes"):
            graph_limit = max(20, int(limit * 0.62))
    base_graph = get_dataset_rag_app_service().knowledge_graph(
        dataset_id, tenant_id=tenant_id, limit=graph_limit, access_context=access
    )
    if not base_graph.get("success") or not memory_graph.get("success"):
        return _facade().cast("dict[str, Any]", _facade()._public_dataset_payload(base_graph))
    return _facade().cast(
        "dict[str, Any]",
        _facade()._public_dataset_payload(
            merge_memory_graph(base_graph, memory_graph, limit=limit)
        ),
    )


@_facade().router.get("/datasets/{dataset_id}/memories")
def list_persy_memories(
    dataset_id: str,
    request: _facade().Request,
    status: str = _facade().FastAPIQuery(""),
    memory_type: str = _facade().FastAPIQuery(""),
    limit: int = _facade().FastAPIQuery(200, ge=1, le=1000),
) -> _facade().JSONResponse:
    unsupported = _facade()._persy_dataset_error(dataset_id)
    if unsupported is not None:
        return unsupported
    payload = (
        _facade()
        ._persy_memory_service()
        .list_memories(
            access_context=_facade()._dataset_access_context_from_request(request),
            status=status,
            memory_type=memory_type,
            limit=limit,
        )
    )
    code = str(payload.get("error_code") or "")
    status_code = 200 if payload.get("success") else 400
    if code in {"dataset_permission_denied", "persy_memory_scope_missing"}:
        status_code = 403
    return _facade().JSONResponse(payload, status_code=status_code)
