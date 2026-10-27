"""Durable rebuild admission, worker ownership, and completion fencing."""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from threading import Thread
from typing import Any

from app.application.dataset_rag.access_policy import (
    DATASET_READ_PERMISSION,
    DATASET_WRITE_PERMISSION,
    _coerce_access_context,
    _ensure_dataset_permission,
    _ensure_tenant_allowed,
    _resolve_tenant_for_access,
)
from app.application.dataset_rag.models import (
    DatasetAccessContext,
    DatasetRebuildJob,
    _clean_key,
    _DatasetState,
    _utc_now_iso,
)
from app.application.dataset_rag.repository import DatasetRepository
from app.application.dataset_rag.retrieval_policy import _metadata_matches
from app.application.dataset_rag.vector_index import VectorIndexService, _embedding_metadata
from app.domain.app_pure.dataset_rag_queue import owner_alive, owner_id
from app.utils.operational_errors import RECOVERABLE_ERRORS

REBUILD_TERMINAL_STATUSES = {"completed", "failed", "cancelled"}


def _empty_rebuild_queue_summary(
    max_concurrent_jobs: int, *, worker_enabled: bool
) -> dict[str, Any]:
    return {
        "max_concurrent_jobs": max_concurrent_jobs,
        "worker_enabled": worker_enabled,
        "queued": 0,
        "running": 0,
        "completed": 0,
        "failed": 0,
        "cancelled": 0,
        "next_job_id": "",
        "running_job_ids": [],
    }


def _recover_rebuild_jobs_locked(state: _DatasetState) -> None:
    for job in state.rebuild_jobs.values():
        if job.status == "running" and (not owner_alive(job.worker_id)):
            now = _utc_now_iso()
            job.status = "queued"
            job.error = "requeued after service restart"
            job.worker_id = ""
            job.queued_at = now
            job.updated_at = now


def _rebuild_job_queue_position_locked(state: _DatasetState, job: DatasetRebuildJob) -> int:
    if job.status != "queued":
        return 0
    queued = [item for item in state.rebuild_jobs.values() if item.status == "queued"]
    queued.sort(key=lambda item: (item.queued_at or item.created_at, item.job_id))
    for index, item in enumerate(queued, start=1):
        if item.job_id == job.job_id:
            return index
    return 0


class RebuildCoordinator:
    """Admit durable rebuild jobs, claim capacity, and fence worker completion."""

    def __init__(
        self,
        *,
        repository: DatasetRepository,
        vector: VectorIndexService,
        renumber: Callable[[_DatasetState], None],
        max_concurrent_jobs: int,
        workers_enabled: bool,
    ) -> None:
        self._repository = repository
        self._vector = vector
        self._renumber_chunks = renumber
        self.owner = owner_id()
        self.shutdown = False
        self.threads: set[Thread] = set()
        self.max_concurrent_jobs = max_concurrent_jobs
        self.workers_enabled = workers_enabled

    def start_rebuild_index(
        self,
        *,
        dataset_id: str,
        tenant_id: str = "",
        metadata_filter: dict[str, Any] | None = None,
        background: bool = True,
        max_attempts: int = 1,
        access_context: DatasetAccessContext | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        dataset_key = _clean_key(dataset_id, default="default")
        tenant_key, denied = _resolve_tenant_for_access(
            access_context,
            tenant_id,
            required_permission=DATASET_WRITE_PERMISSION,
            default_without_context="",
            dataset_id=dataset_key,
        )
        if denied is not None:
            return denied
        job = DatasetRebuildJob(
            job_id=f"rag_rebuild_{uuid.uuid4().hex[:12]}",
            dataset_id=dataset_key,
            tenant_id=tenant_key,
            metadata_filter=dict(metadata_filter or {}),
            max_attempts=max(1, min(int(max_attempts or 1), 5)),
        )
        starts: list[tuple[str, str]] = []
        with self._repository.lock:
            state = self._repository.datasets.get(dataset_key)
            if state is None:
                return {"success": False, "dataset_id": dataset_key, "message": "dataset not found"}
            state.rebuild_jobs[job.job_id] = job
            if background and self.workers_enabled:
                starts = self._claim_next_rebuild_jobs_locked()
            self._repository._persist_locked()
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
        access_context: DatasetAccessContext | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        dataset_key = _clean_key(dataset_id, default="default")
        context = _coerce_access_context(access_context)
        denied = _ensure_dataset_permission(
            context, DATASET_WRITE_PERMISSION, dataset_id=dataset_key
        )
        if denied is not None:
            return denied
        with self._repository.lock:
            state = self._repository.datasets.get(dataset_key)
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
            denied = _ensure_tenant_allowed(
                context, job.tenant_id, dataset_id=dataset_key, operation="cancel_rebuild_job"
            )
            if denied is not None:
                denied["job_id"] = job_id
                return denied
            if job.status in REBUILD_TERMINAL_STATUSES:
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
            now = _utc_now_iso()
            job.status = "cancelled"
            job.cancelled_at = now
            job.completed_at = now
            job.updated_at = now
            self._repository._persist_locked()
            return {
                "success": True,
                "dataset_id": dataset_key,
                "job": self._rebuild_job_to_dict_locked(state, job),
            }

    def drain_rebuild_queue(self, *, max_jobs: int | None = None) -> dict[str, Any]:
        drained: list[dict[str, Any]] = []
        limit = max_jobs if max_jobs is not None else 1000
        while len(drained) < max(0, int(limit)):
            with self._repository.lock:
                next_job = self._claim_next_rebuild_jobs_locked(limit=1)
                self._repository._persist_locked()
            if not next_job:
                break
            dataset_id, job_id = next_job[0]
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
        access_context: DatasetAccessContext | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        dataset_key = _clean_key(dataset_id, default="default")
        context = _coerce_access_context(access_context)
        denied = _ensure_dataset_permission(
            context, DATASET_READ_PERMISSION, dataset_id=dataset_key
        )
        if denied is not None:
            return denied
        with self._repository.lock:
            state = self._repository.datasets.get(dataset_key)
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
            denied = _ensure_tenant_allowed(
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

    def _schedule_rebuild_jobs(self) -> None:
        if not self.workers_enabled or self.shutdown:
            return
        with self._repository.lock:
            starts = self._claim_next_rebuild_jobs_locked()
            if starts:
                self._repository._persist_locked()
        self._start_rebuild_threads(starts)

    def _claim_next_rebuild_jobs_locked(self, *, limit: int | None = None) -> list[tuple[str, str]]:
        running = sum(
            1
            for state in self._repository.datasets.values()
            for job in state.rebuild_jobs.values()
            if job.status == "running"
        )
        capacity = max(0, self.max_concurrent_jobs - running)
        if limit is not None:
            capacity = min(capacity, max(0, int(limit)))
        if capacity <= 0:
            return []
        queued: list[tuple[str, DatasetRebuildJob]] = []
        for dataset_id, state in sorted(self._repository.datasets.items()):
            for job in state.rebuild_jobs.values():
                if job.status == "queued":
                    queued.append((dataset_id, job))
        queued.sort(key=lambda item: (item[1].queued_at or item[1].created_at, item[1].job_id))
        starts: list[tuple[str, str]] = []
        for dataset_id, job in queued[:capacity]:
            now = _utc_now_iso()
            job.status = "running"
            job.started_at = now if not job.started_at else job.started_at
            job.updated_at = now
            job.attempt_count += 1
            job.worker_id = self.owner
            starts.append((dataset_id, job.job_id))
        return starts

    def _start_rebuild_threads(self, starts: list[tuple[str, str]]) -> None:
        for dataset_id, job_id in starts:
            thread = threading.Thread(
                target=self._run_rebuild_job,
                kwargs={"dataset_id": dataset_id, "job_id": job_id, "claimed": True},
                daemon=True,
            )
            self.threads.add(thread)
            thread.start()

    def _run_rebuild_job(
        self, dataset_id: str, job_id: str, *, claimed: bool = False, schedule_next: bool = True
    ) -> None:
        with self._repository.lock:
            state = self._repository.datasets.get(dataset_id)
            job = state.rebuild_jobs.get(job_id) if state is not None else None
            if state is None or job is None:
                return
            if job.status in REBUILD_TERMINAL_STATUSES:
                return
            if not claimed:
                now = _utc_now_iso()
                job.status = "running"
                job.started_at = now if not job.started_at else job.started_at
                job.updated_at = now
                job.attempt_count += 1
                job.worker_id = self.owner
                self._repository._persist_locked()
        try:
            with self._repository.lock:
                state = self._repository.datasets.get(dataset_id)
                job = state.rebuild_jobs.get(job_id) if state is not None else None
                if state is None or job is None:
                    return
                work = [
                    (
                        (chunk.metadata or {}).get("document_id"),
                        (chunk.metadata or {}).get("tenant_id"),
                        chunk.chunk_index,
                        chunk.text,
                    )
                    for chunk in state.chunks
                    if (
                        not job.tenant_id
                        or str((chunk.metadata or {}).get("tenant_id") or "") == job.tenant_id
                    )
                    and (not job.metadata_filter or _metadata_matches(chunk, job.metadata_filter))
                ]
            vectors = {key: _embedding_metadata(self._vector.embedder, key[3]) for key in work}
            with self._repository.lock:
                state = self._repository.datasets[dataset_id]
                job = state.rebuild_jobs[job_id]
                if job.status != "running" or job.worker_id != self.owner or self.shutdown:
                    return
                matched_document_ids: set[str] = set()
                rebuilt_chunks = 0
                for chunk in state.chunks:
                    key = (
                        (chunk.metadata or {}).get("document_id"),
                        (chunk.metadata or {}).get("tenant_id"),
                        chunk.chunk_index,
                        chunk.text,
                    )
                    if key not in vectors:
                        continue
                    metadata = dict(chunk.metadata or {})
                    metadata.pop("_embedding", None)
                    metadata.update(vectors[key])
                    chunk.metadata = metadata
                    rebuilt_chunks += 1
                    document_id = str(metadata.get("document_id") or "")
                    if document_id:
                        matched_document_ids.add(document_id)
                self._renumber_chunks(state)
                self._vector._sync_vector_index_locked(state)
                self._vector._refresh_index_metadata(state)
                job.status = "completed"
                job.document_count = len(matched_document_ids)
                job.chunk_count = rebuilt_chunks
                now = _utc_now_iso()
                job.completed_at = now
                job.updated_at = now
                self._repository._persist_locked()
        except RECOVERABLE_ERRORS as exc:
            with self._repository.lock:
                state = self._repository.datasets.get(dataset_id)
                job = state.rebuild_jobs.get(job_id) if state is not None else None
                if (
                    job is not None
                    and job.status == "running"
                    and (job.worker_id == self.owner)
                    and (not self.shutdown)
                ):
                    now = _utc_now_iso()
                    if job.attempt_count < max(1, int(job.max_attempts or 1)):
                        job.status = "queued"
                        job.queued_at = now
                    else:
                        job.status = "failed"
                        job.completed_at = now
                    job.error = str(exc)
                    job.updated_at = now
                    self._repository._persist_locked()
        finally:
            self.threads.discard(threading.current_thread())
            if schedule_next:
                self._schedule_rebuild_jobs()

    def _rebuild_job_to_dict_locked(
        self, state: _DatasetState, job: DatasetRebuildJob
    ) -> dict[str, Any]:
        payload = job.to_dict()
        payload["queue_position"] = _rebuild_job_queue_position_locked(state, job)
        payload["max_concurrent_jobs"] = self.max_concurrent_jobs
        return payload

    def _rebuild_queue_summary_locked(
        self, state: _DatasetState, *, tenant_id_filter: str = ""
    ) -> dict[str, Any]:
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
            "max_concurrent_jobs": self.max_concurrent_jobs,
            "worker_enabled": self.workers_enabled,
            "queued": counts["queued"],
            "running": counts["running"],
            "completed": counts["completed"],
            "failed": counts["failed"],
            "cancelled": counts["cancelled"],
            "next_job_id": queued[0].job_id if queued else "",
            "running_job_ids": [job.job_id for job in running],
        }
