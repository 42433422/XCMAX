# mypy: disable-error-code="attr-defined, no-any-return, valid-type"
"""Behavior mixin extracted from the public facade class."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.dataset_rag_app_service")


class __DatasetRagApplicationServicePart01MixinPart02Mixin:
    def start_rebuild_index(
        self,
        *,
        dataset_id: str,
        tenant_id: str = "",
        metadata_filter: dict[str, _facade().Any] | None = None,
        background: bool = True,
        max_attempts: int = 1,
        access_context: _facade().DatasetAccessContext | dict[str, _facade().Any] | None = None,
    ) -> dict[str, _facade().Any]:
        dataset_key = _facade()._clean_key(dataset_id, default="default")
        (tenant_key, denied) = _facade()._resolve_tenant_for_access(
            access_context,
            tenant_id,
            required_permission=_facade().DATASET_WRITE_PERMISSION,
            default_without_context="",
            dataset_id=dataset_key,
        )
        if denied is not None:
            return denied
        job = _facade().DatasetRebuildJob(
            job_id=f"rag_rebuild_{_facade().uuid.uuid4().hex[:12]}",
            dataset_id=dataset_key,
            tenant_id=tenant_key,
            metadata_filter=dict(metadata_filter or {}),
            max_attempts=max(1, min(int(max_attempts or 1), 5)),
        )
        starts: list[tuple[str, str]] = []
        with self._lock:
            state = self._datasets.get(dataset_key)
            if state is None:
                return {"success": False, "dataset_id": dataset_key, "message": "dataset not found"}
            state.rebuild_jobs[job.job_id] = job
            if background and self._rebuild_workers_enabled:
                starts = self._claim_next_rebuild_jobs_locked()
            self._persist_locked()
            job_payload = self._rebuild_job_to_dict_locked(state, job)
        if background:
            self._start_rebuild_threads(starts)
            return {"success": True, "job": job_payload, "background": True}
        self._run_rebuild_job(dataset_key, job.job_id)
        return {
            "success": True,
            "job": self.get_rebuild_job(dataset_key, job.job_id).get("job", job.to_dict()),
            "background": False,
        }

    def cancel_rebuild_job(
        self,
        dataset_id: str,
        job_id: str,
        *,
        access_context: _facade().DatasetAccessContext | dict[str, _facade().Any] | None = None,
    ) -> dict[str, _facade().Any]:
        dataset_key = _facade()._clean_key(dataset_id, default="default")
        context = _facade()._coerce_access_context(access_context)
        denied = _facade()._ensure_dataset_permission(
            context, _facade().DATASET_WRITE_PERMISSION, dataset_id=dataset_key
        )
        if denied is not None:
            return denied
        with self._lock:
            state = self._datasets.get(dataset_key)
            job = state.rebuild_jobs.get(job_id) if state is not None else None
            if job is None:
                return {
                    "success": False,
                    "dataset_id": dataset_key,
                    "job_id": job_id,
                    "message": "rebuild job not found",
                }
            if state is None:
                return {"success": False, "dataset_id": dataset_key, "message": "dataset not found"}
            denied = _facade()._ensure_tenant_allowed(
                context, job.tenant_id, dataset_id=dataset_key, operation="cancel_rebuild_job"
            )
            if denied is not None:
                denied["job_id"] = job_id
                return denied
            if job.status in _facade().REBUILD_TERMINAL_STATUSES:
                return {
                    "success": True,
                    "dataset_id": dataset_key,
                    "job": self._rebuild_job_to_dict_locked(state, job),
                    "message": f"rebuild job already {job.status}",
                }
            if job.status != "queued":
                return {
                    "success": False,
                    "dataset_id": dataset_key,
                    "job_id": job_id,
                    "error_code": "dataset_rebuild_cancel_failed",
                    "message": "only queued rebuild jobs can be cancelled",
                    "job": self._rebuild_job_to_dict_locked(state, job),
                }
            now = _facade()._utc_now_iso()
            job.status = "cancelled"
            job.cancelled_at = now
            job.completed_at = now
            job.updated_at = now
            self._persist_locked()
            return {
                "success": True,
                "dataset_id": dataset_key,
                "job": self._rebuild_job_to_dict_locked(state, job),
            }

    def drain_rebuild_queue(self, *, max_jobs: int | None = None) -> dict[str, _facade().Any]:
        drained: list[dict[str, _facade().Any]] = []
        limit = max_jobs if max_jobs is not None else 1000
        while len(drained) < max(0, int(limit)):
            with self._lock:
                next_job = self._claim_next_rebuild_jobs_locked(limit=1)
                self._persist_locked()
            if not next_job:
                break
            (dataset_id, job_id) = next_job[0]
            self._run_rebuild_job(dataset_id, job_id, claimed=True, schedule_next=False)
            job_status = self.get_rebuild_job(dataset_id, job_id)
            if isinstance(job_status.get("job"), dict):
                drained.append(job_status["job"])
        return {"success": True, "drained_count": len(drained), "jobs": drained}

    def get_rebuild_job(
        self,
        dataset_id: str,
        job_id: str,
        *,
        access_context: _facade().DatasetAccessContext | dict[str, _facade().Any] | None = None,
    ) -> dict[str, _facade().Any]:
        dataset_key = _facade()._clean_key(dataset_id, default="default")
        context = _facade()._coerce_access_context(access_context)
        denied = _facade()._ensure_dataset_permission(
            context, _facade().DATASET_READ_PERMISSION, dataset_id=dataset_key
        )
        if denied is not None:
            return denied
        with self._lock:
            state = self._datasets.get(dataset_key)
            job = state.rebuild_jobs.get(job_id) if state is not None else None
            if job is None:
                return {
                    "success": False,
                    "dataset_id": dataset_key,
                    "job_id": job_id,
                    "message": "rebuild job not found",
                }
            if state is None:
                return {"success": False, "dataset_id": dataset_key, "message": "dataset not found"}
            denied = _facade()._ensure_tenant_allowed(
                context, job.tenant_id, dataset_id=dataset_key, operation="get_rebuild_job"
            )
            if denied is not None:
                denied["job_id"] = job_id
                return denied
            return {
                "success": True,
                "dataset_id": dataset_key,
                "job": self._rebuild_job_to_dict_locked(state, job),
            }

    def status(
        self,
        dataset_id: str = "",
        *,
        tenant_id: str = "",
        access_context: _facade().DatasetAccessContext | dict[str, _facade().Any] | None = None,
        include_documents: bool = True,
    ) -> dict[str, _facade().Any]:
        (tenant_filter, denied) = _facade()._resolve_tenant_for_access(
            access_context,
            tenant_id,
            required_permission=_facade().DATASET_READ_PERMISSION,
            default_without_context="",
            dataset_id=_facade()._clean_key(dataset_id, default="default")
            if dataset_id.strip()
            else "",
        )
        if denied is not None:
            return denied
        with self._lock:
            if dataset_id.strip():
                dataset_key = _facade()._clean_key(dataset_id, default="default")
                state = self._datasets.get(dataset_key)
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
                for (key, state) in sorted(self._datasets.items())
            }
        return {
            "success": True,
            "datasets": datasets,
            "dataset_count": len(datasets),
            "document_count": sum(item["document_count"] for item in datasets.values()),
            "chunk_count": sum(item["chunk_count"] for item in datasets.values()),
            "storage_path": str(self._storage_path),
            "persistent": True,
        }

    def query(
        self,
        *,
        dataset_id: str,
        query: str,
        top_k: int = 5,
        tenant_id: str = "",
        version: str | int = "",
        metadata_filter: dict[str, _facade().Any] | None = None,
        rerank: bool = False,
        access_context: _facade().DatasetAccessContext | dict[str, _facade().Any] | None = None,
    ) -> dict[str, _facade().Any]:
        dataset_key = _facade()._clean_key(dataset_id, default="default")
        (tenant_key, denied) = _facade()._resolve_tenant_for_access(
            access_context,
            tenant_id,
            required_permission=_facade().DATASET_READ_PERMISSION,
            default_without_context="",
            dataset_id=dataset_key,
        )
        if denied is not None:
            denied.update({"chunks": [], "citations": [], "answer": ""})
            return denied
        query_text = query.strip()
        if not query_text:
            return {
                "success": False,
                "dataset_id": dataset_key,
                "message": "query is required",
                "chunks": [],
            }
        with self._lock:
            state = self._datasets.get(dataset_key)
            chunks = list(state.chunks) if state is not None else []
            index_snapshot = dict(state.index or {}) if state is not None else {}
        vector_candidates = self._query_vector_index_candidates(
            dataset_id=dataset_key,
            query=query_text,
            top_k=max(50, max(1, min(int(top_k), 50)) * 4),
            tenant_id=tenant_key,
            version=version,
            metadata_filter=metadata_filter or {},
        )
        used_vector_backend = vector_candidates is not None
        if vector_candidates is not None:
            chunks = vector_candidates
            index_snapshot["query_backend"] = self._vector_index_backend_name()
        else:
            chunks = _facade()._filter_chunks(
                chunks, tenant_id=tenant_key, version=version, metadata_filter=metadata_filter or {}
            )
            index_snapshot["query_backend"] = "in_memory_hybrid"
        if not chunks:
            return {
                "success": True,
                "dataset_id": dataset_key,
                "query": query_text,
                "chunks": [],
                "citations": [],
                "answer": "",
                "tenant_id": tenant_key,
                "version": str(version or ""),
                "vector_backend_used": used_vector_backend,
                "index": index_snapshot,
            }
        retriever = _facade().HybridRetriever(
            embedder=self._embedder, top_k=max(1, min(int(top_k), 50))
        )
        retriever.index(chunks)
        top = retriever.retrieve(query_text)
        if rerank:
            top = _facade()._rerank_chunks(query_text, top, top_k=max(1, min(int(top_k), 50)))
        return {
            "success": True,
            "dataset_id": dataset_key,
            "query": query_text,
            "chunks": [_facade()._chunk_to_dict(c, public=True) for c in top],
            "tenant_id": tenant_key,
            "version": str(version or ""),
            "metadata_filter": metadata_filter or {},
            "rerank": bool(rerank),
            "vector_backend_used": used_vector_backend,
            "index": index_snapshot,
        }

    def knowledge_graph(
        self,
        dataset_id: str,
        *,
        tenant_id: str = "",
        limit: int = 120,
        access_context: _facade().DatasetAccessContext | dict[str, _facade().Any] | None = None,
    ) -> dict[str, _facade().Any]:
        """Build a bounded, explainable graph from persisted documents and chunks."""
        dataset_key = _facade()._clean_key(dataset_id, default="default")
        (tenant_key, denied) = _facade()._resolve_tenant_for_access(
            access_context,
            tenant_id,
            required_permission=_facade().DATASET_READ_PERMISSION,
            default_without_context="",
            dataset_id=dataset_key,
        )
        if denied is not None:
            denied.update({"nodes": [], "edges": [], "stats": {}})
            return denied
        with self._lock:
            state = self._datasets.get(dataset_key)
            if state is None:
                documents: list[_facade().DatasetDocument] = []
                chunks: list[_facade().RetrievedChunk] = []
            else:
                documents = [
                    doc
                    for doc in state.documents.values()
                    if not tenant_key or doc.tenant_id == tenant_key
                ]
                chunks = _facade()._filter_chunks(
                    list(state.chunks), tenant_id=tenant_key, version="", metadata_filter={}
                )
        return _facade()._build_knowledge_graph_payload(
            dataset_id=dataset_key,
            tenant_id=tenant_key,
            documents=documents,
            chunks=chunks,
            limit=max(20, min(int(limit), 240)),
        )
