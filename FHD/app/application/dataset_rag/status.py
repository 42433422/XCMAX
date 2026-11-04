"""Tenant-scoped dataset and rebuild status projections."""

from __future__ import annotations

from typing import Any

from app.application.dataset_rag.access_policy import (
    DATASET_READ_PERMISSION,
    _resolve_tenant_for_access,
)
from app.application.dataset_rag.models import DatasetAccessContext, _clean_key, _DatasetState
from app.application.dataset_rag.rebuild_coordinator import (
    RebuildCoordinator,
    _empty_rebuild_queue_summary,
)
from app.application.dataset_rag.repository import DatasetRepository
from app.application.dataset_rag.vector_index import _semantic_embedding_available


class DatasetStatus:
    """Project tenant-scoped document, index, and durable queue status."""

    def __init__(self, *, repository: DatasetRepository, rebuild: RebuildCoordinator) -> None:
        self._repository = repository
        self._rebuild = rebuild

    def status(
        self,
        dataset_id: str = "",
        *,
        tenant_id: str = "",
        access_context: DatasetAccessContext | dict[str, Any] | None = None,
        include_documents: bool = True,
    ) -> dict[str, Any]:
        tenant_filter, denied = _resolve_tenant_for_access(
            access_context,
            tenant_id,
            required_permission=DATASET_READ_PERMISSION,
            default_without_context="",
            dataset_id=_clean_key(dataset_id, default="default") if dataset_id.strip() else "",
        )
        if denied is not None:
            return denied
        with self._repository.lock:
            if dataset_id.strip():
                dataset_key = _clean_key(dataset_id, default="default")
                state = self._repository.datasets.get(dataset_key)
                return self._status_for_state(
                    dataset_key,
                    state,
                    tenant_id_filter=tenant_filter,
                    include_documents=include_documents,
                )
            datasets = {
                key: self._status_for_state(
                    key, state, tenant_id_filter=tenant_filter, include_documents=include_documents
                )
                for key, state in sorted(self._repository.datasets.items())
            }
        return {
            "success": True,
            "datasets": datasets,
            "dataset_count": len(datasets),
            "document_count": sum(item["document_count"] for item in datasets.values()),
            "chunk_count": sum(item["chunk_count"] for item in datasets.values()),
            "storage_path": str(self._repository.storage_path),
            "persistent": True,
        }

    def _status_for_state(
        self,
        dataset_id: str,
        state: _DatasetState | None,
        *,
        tenant_id_filter: str = "",
        include_documents: bool = True,
    ) -> dict[str, Any]:
        if state is None:
            empty_index = {
                "semantic_embedding_available": _semantic_embedding_available(0),
                "embedding_count": 0,
            }
            return {
                "success": True,
                "dataset_id": dataset_id,
                "document_count": 0,
                "chunk_count": 0,
                "documents": [],
                "tenant_ids": [],
                "versions": [],
                "index": empty_index,
                "rebuild_jobs": [],
                "rebuild_job_count": 0,
                "rebuild_queue": _empty_rebuild_queue_summary(
                    self._rebuild.max_concurrent_jobs, worker_enabled=self._rebuild.workers_enabled
                ),
                "storage_path": str(self._repository.storage_path),
                "persistent": True,
            }
        documents = [
            doc
            for doc in state.documents.values()
            if not tenant_id_filter or doc.tenant_id == tenant_id_filter
        ]
        chunks = [
            chunk
            for chunk in state.chunks
            if not tenant_id_filter
            or str((chunk.metadata or {}).get("tenant_id") or "") == tenant_id_filter
        ]
        rebuild_job_records = [
            job
            for job in state.rebuild_jobs.values()
            if not tenant_id_filter or job.tenant_id == tenant_id_filter
        ]
        embedding_count = sum(
            1
            for chunk in chunks
            if isinstance(chunk.metadata, dict)
            and isinstance(chunk.metadata.get("_embedding"), list)
        )
        index = dict(state.index or {})
        if tenant_id_filter:
            index.update(
                {
                    "document_count": len(documents),
                    "chunk_count": len(chunks),
                    "embedding_count": embedding_count,
                    "filtered_by_tenant": tenant_id_filter,
                }
            )
        index["embedding_count"] = int(index.get("embedding_count") or embedding_count or 0)
        index["semantic_embedding_available"] = _semantic_embedding_available(
            int(index.get("embedding_count") or 0)
        )
        rebuild_jobs = [
            self._rebuild._rebuild_job_to_dict_locked(state, job)
            for job in sorted(rebuild_job_records, key=lambda item: item.created_at, reverse=True)[
                :10
            ]
        ]
        return {
            "success": True,
            "dataset_id": dataset_id,
            "document_count": len(documents),
            "chunk_count": len(chunks),
            "documents": [doc.to_dict() for doc in documents] if include_documents else [],
            "tenant_ids": sorted({doc.tenant_id for doc in documents}),
            "versions": sorted({doc.version_label for doc in documents}),
            "index": index,
            "rebuild_jobs": rebuild_jobs,
            "rebuild_job_count": len(rebuild_jobs),
            "rebuild_queue": self._rebuild._rebuild_queue_summary_locked(
                state, tenant_id_filter=tenant_id_filter
            ),
            "storage_path": str(self._repository.storage_path),
            "persistent": True,
        }
