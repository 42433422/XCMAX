# mypy: disable-error-code="attr-defined, no-any-return, valid-type"
"""Behavior mixin extracted from the public facade class."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.dataset_rag_app_service")


class __DatasetRagApplicationServicePart02MixinPart02Mixin:
    def _vector_index_status(self, dataset_id: str) -> dict[str, _facade().Any]:
        if self._vector_index_backend is None:
            return {
                "backend": "none",
                "persistent": False,
                "dataset_id": dataset_id,
                "chunk_count": 0,
                "index_exists": False,
            }
        try:
            return dict(self._vector_index_backend.status(dataset_id))
        except _facade().RECOVERABLE_ERRORS as exc:
            return {
                "backend": self._vector_index_backend_name(),
                "persistent": True,
                "dataset_id": dataset_id,
                "chunk_count": 0,
                "index_exists": False,
                "status": "failed",
                "error": str(exc),
            }

    def _refresh_index_metadata(self, state: _facade()._DatasetState) -> None:
        embedding_count = sum(
            1
            for chunk in state.chunks
            if isinstance(chunk.metadata, dict)
            and isinstance(chunk.metadata.get("_embedding"), list)
        )
        vector_status = self._vector_index_status(state.dataset_id)
        previous = dict(state.index or {})
        state.index = {
            "schema_version": 2,
            "retriever": "hybrid_bm25_vector",
            "reranker": "lexical_overlap_v1",
            "document_count": len(state.documents),
            "chunk_count": len(state.chunks),
            "embedding_count": embedding_count,
            "embedding_persisted": embedding_count > 0,
            "vector_backend": vector_status,
            "vector_backend_name": vector_status.get("backend", self._vector_index_backend_name()),
            "vector_backend_chunk_count": int(vector_status.get("chunk_count") or 0),
            "vector_backend_persistent": bool(vector_status.get("persistent")),
            "vector_backend_sync_status": previous.get("vector_backend_sync_status", ""),
            "vector_backend_synced_chunks": int(previous.get("vector_backend_synced_chunks") or 0),
            "vector_backend_synced_at": str(previous.get("vector_backend_synced_at") or ""),
            "vector_backend_error": str(previous.get("vector_backend_error") or ""),
            "updated_at": _facade()._utc_now_iso(),
        }

    def _status_for_state(
        self,
        dataset_id: str,
        state: _facade()._DatasetState | None,
        *,
        tenant_id_filter: str = "",
        include_documents: bool = True,
    ) -> dict[str, _facade().Any]:
        if state is None:
            empty_index = {
                "semantic_embedding_available": _facade()._semantic_embedding_available(0),
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
                "rebuild_queue": _facade()._empty_rebuild_queue_summary(
                    self._max_concurrent_rebuild_jobs, worker_enabled=self._rebuild_workers_enabled
                ),
                "storage_path": str(self._storage_path),
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
        index["semantic_embedding_available"] = _facade()._semantic_embedding_available(
            int(index.get("embedding_count") or 0)
        )
        rebuild_jobs = [
            self._rebuild_job_to_dict_locked(state, job)
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
            "rebuild_queue": self._rebuild_queue_summary_locked(
                state, tenant_id_filter=tenant_id_filter
            ),
            "storage_path": str(self._storage_path),
            "persistent": True,
        }

    def _rebuild_job_to_dict_locked(
        self, state: _facade()._DatasetState, job: _facade().DatasetRebuildJob
    ) -> dict[str, _facade().Any]:
        payload = job.to_dict()
        payload["queue_position"] = self._rebuild_job_queue_position_locked(state, job)
        payload["max_concurrent_jobs"] = self._max_concurrent_rebuild_jobs
        return payload

    @staticmethod
    def _rebuild_job_queue_position_locked(
        state: _facade()._DatasetState, job: _facade().DatasetRebuildJob
    ) -> int:
        if job.status != "queued":
            return 0
        queued = [item for item in state.rebuild_jobs.values() if item.status == "queued"]
        queued.sort(key=lambda item: (item.queued_at or item.created_at, item.job_id))
        for index, item in enumerate(queued, start=1):
            if item.job_id == job.job_id:
                return index
        return 0

    def _rebuild_queue_summary_locked(
        self, state: _facade()._DatasetState, *, tenant_id_filter: str = ""
    ) -> dict[str, _facade().Any]:
        jobs = [
            job
            for job in state.rebuild_jobs.values()
            if not tenant_id_filter or job.tenant_id == tenant_id_filter
        ]
        counts = {"queued": 0, "running": 0, "completed": 0, "failed": 0, "cancelled": 0}
        for job in jobs:
            if job.status in counts:
                counts[job.status] += 1
        queued = sorted(
            (job for job in jobs if job.status == "queued"),
            key=lambda item: (item.queued_at or item.created_at, item.job_id),
        )
        running = sorted(
            (job for job in jobs if job.status == "running"),
            key=lambda item: (item.started_at or item.updated_at, item.job_id),
        )
        return {
            "max_concurrent_jobs": self._max_concurrent_rebuild_jobs,
            "worker_enabled": self._rebuild_workers_enabled,
            "queued": counts["queued"],
            "running": counts["running"],
            "completed": counts["completed"],
            "failed": counts["failed"],
            "cancelled": counts["cancelled"],
            "next_job_id": queued[0].job_id if queued else "",
            "running_job_ids": [job.job_id for job in running],
        }

    @staticmethod
    def _recover_rebuild_jobs_locked(state: _facade()._DatasetState) -> None:
        for job in state.rebuild_jobs.values():
            if job.status == "running":
                now = _facade()._utc_now_iso()
                job.status = "queued"
                job.error = "requeued after service restart"
                job.worker_id = ""
                job.queued_at = now
                job.updated_at = now
