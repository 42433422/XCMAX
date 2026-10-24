"""Dataset status, graphs and retrieval views with explicit access providers."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, cast

from fastapi import Request

from app.application.dataset_rag_app_service import DatasetRagApplicationService
from app.application.persy_memory_app_service import PersyMemoryApplicationService
from app.fastapi_routes.knowledge.ports import AccessResolver
from app.fastapi_routes.knowledge.schemas import QueryRequest
from app.fastapi_routes.knowledge.serialization import _public_dataset_payload
from app.utils.operational_errors import RECOVERABLE_ERRORS


class DatasetViews:
    def __init__(
        self,
        *,
        service: Callable[[], DatasetRagApplicationService],
        access: AccessResolver,
        tenant_scope: Callable[[Any], str],
        memories: Callable[[], PersyMemoryApplicationService],
        dataset_id: str,
        logger: logging.Logger,
    ) -> None:
        self._service = service
        self._access = access
        self._tenant_scope = tenant_scope
        self._memories = memories
        self._dataset_id = dataset_id
        self._logger = logger

    def status_all(self, request: Request) -> dict[str, Any]:
        return cast(
            "dict[str, Any]",
            _public_dataset_payload(self._service().status(access_context=self._access(request))),
        )

    def status(
        self, dataset_id: str, request: Request, include_documents: bool = True
    ) -> dict[str, Any]:
        access = self._access(request)
        return cast(
            "dict[str, Any]",
            _public_dataset_payload(
                self._service().status(
                    dataset_id,
                    tenant_id=self._tenant_scope(access),
                    access_context=access,
                    include_documents=bool(include_documents),
                )
            ),
        )

    def graph(self, dataset_id: str, request: Request, limit: int = 80) -> dict[str, Any]:
        from app.application.persy_memory_app_service import merge_memory_graph

        access = self._access(request)
        tenant_id = self._tenant_scope(access)
        memory_graph: dict[str, Any] = {"success": True, "nodes": [], "edges": [], "stats": {}}
        graph_limit = limit
        if dataset_id == self._dataset_id:
            memory_graph = self._memories().graph(
                access_context=access, limit=max(8, min(40, int(limit * 0.28)))
            )
            if memory_graph.get("nodes"):
                graph_limit = max(20, int(limit * 0.62))
        base_graph = self._service().knowledge_graph(
            dataset_id, tenant_id=tenant_id, limit=graph_limit, access_context=access
        )
        if not base_graph.get("success") or not memory_graph.get("success"):
            return cast("dict[str, Any]", _public_dataset_payload(base_graph))
        return cast(
            "dict[str, Any]",
            _public_dataset_payload(merge_memory_graph(base_graph, memory_graph, limit=limit)),
        )

    def job(self, dataset_id: str, job_id: str, request: Request) -> dict[str, Any]:
        return cast(
            "dict[str, Any]",
            _public_dataset_payload(
                self._service().get_rebuild_job(
                    dataset_id, job_id, access_context=self._access(request)
                )
            ),
        )

    def overview(
        self, request: Request, *, snapshot: Callable[[Request | None], dict[str, Any]]
    ) -> dict[str, Any]:
        """Admin/full-knowledge overview across all governed datasets."""
        access = self._access(request)
        overview = self._service().status(access_context=access)
        snap = snapshot(request)
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

    def query_all(
        self, req: QueryRequest, request: Request, *, rag_enabled: Callable[[], bool]
    ) -> dict[str, Any]:
        """Query across all datasets visible to the caller (admin = full platform)."""
        access = self._access(request)
        service = self._service()
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
            "rag_enabled": rag_enabled(),
            "omniscient": True,
            "dataset_hits": len(
                {str(c.get("dataset_id") or "") for c in top if c.get("dataset_id")}
            ),
        }

    def snapshot(
        self,
        request: Request | None = None,
        *,
        legacy: dict[str, int],
        embedder_available: Callable[[], bool],
        rag_enabled: Callable[[], bool],
    ) -> dict[str, Any]:
        dataset_count = 0
        dataset_docs = 0
        dataset_chunks = 0
        recommended = self._dataset_id
        try:
            access = self._access(request) if request is not None else None
            overview = self._service().status(access_context=access)
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
                persy_docs = next((n for key, n in nonempty if key == self._dataset_id), 0)
                if persy_docs <= 0 and nonempty and (nonempty[0][1] > 0):
                    recommended = nonempty[0][0]
        except RECOVERABLE_ERRORS as exc:
            self._logger.debug("dataset overview for health failed: %s", exc)
        embedder_ok = embedder_available()
        return {
            "rag_enabled": rag_enabled(),
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
