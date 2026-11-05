"""Persistent dataset snapshots and atomic store serialization."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from app.application.dataset_rag.models import (
    _chunk_to_dict,
    _DatasetState,
    _dict_to_retrieved_chunk,
    _document_from_dict,
    _rebuild_job_from_dict,
)
from app.domain.app_pure.dataset_rag_queue import DatasetStateLock
from app.utils.operational_errors import RECOVERABLE_ERRORS


class DatasetRepository:
    """Serialize the dataset store and refresh snapshots under a process-safe lock."""

    def __init__(
        self, storage_path: Path, *, prepare_loaded_state: Callable[[_DatasetState], None]
    ) -> None:
        self.storage_path = storage_path
        self.datasets: dict[str, _DatasetState] = {}
        self._prepare_loaded_state = prepare_loaded_state
        self.lock = DatasetStateLock(self)

    def read_rebuild_state(self, dataset_id: str) -> _DatasetState | None:
        # _persist_locked publishes with atomic replace: one read sees one committed
        # JSON generation, not a transaction spanning the vector index or ledger.
        # Never acquire the writer lock or run projection/recovery initialization.
        raw = json.loads(self.storage_path.read_text(encoding="utf-8"))
        if (
            not isinstance(raw, dict)
            or type(raw.get("version")) is not int
            or raw["version"] != 1
            or not isinstance(raw.get("datasets"), dict)
        ):
            raise ValueError("invalid dataset snapshot")
        if dataset_id not in raw["datasets"]:
            return None
        payload = raw["datasets"][dataset_id]
        if (
            not isinstance(payload, dict)
            or payload.get("dataset_id") != dataset_id
            or not isinstance(payload.get("rebuild_jobs"), dict)
        ):
            raise ValueError("invalid rebuild snapshot")
        state = _DatasetState(dataset_id)
        for job_id, row in payload["rebuild_jobs"].items():
            if (
                not isinstance(row, dict)
                or not job_id
                or row.get("job_id") != job_id
                or row.get("dataset_id") != dataset_id
                or not isinstance(row.get("status"), str)
                or row.get("status")
                not in {"queued", "running", "completed", "failed", "cancelled"}
                or not isinstance(row.get("tenant_id"), str)
                or not isinstance(row.get("metadata_filter"), dict)
            ):
                raise ValueError("invalid rebuild identity")
            for name in ("document_count", "chunk_count", "attempt_count", "max_attempts"):
                value = row.get(name)
                if type(value) is not int or value < (1 if name == "max_attempts" else 0):
                    raise ValueError("invalid rebuild count")
            for name in (
                "error",
                "worker_id",
                "created_at",
                "queued_at",
                "started_at",
                "completed_at",
                "cancelled_at",
                "updated_at",
            ):
                if not isinstance(row.get(name), str):
                    raise ValueError("invalid rebuild timestamp or owner")
            if not all(row[name] for name in ("created_at", "queued_at", "updated_at")):
                raise ValueError("missing rebuild timestamp")
            state.rebuild_jobs[job_id] = _rebuild_job_from_dict(row)
        return state

    def _load_persisted_state(self) -> None:
        try:
            if not self.storage_path.exists():
                return
            raw = json.loads(self.storage_path.read_text(encoding="utf-8"))
            datasets = raw.get("datasets") if isinstance(raw, dict) else {}
            if not isinstance(datasets, dict):
                return
            loaded: dict[str, _DatasetState] = {}
            for dataset_id, payload in datasets.items():
                if not isinstance(payload, dict):
                    continue
                documents_payload = payload.get("documents")
                chunks_payload = payload.get("chunks")
                jobs_payload = payload.get("rebuild_jobs")
                documents = (
                    {
                        str(doc_id): _document_from_dict(row)
                        for doc_id, row in (documents_payload or {}).items()
                        if isinstance(row, dict)
                    }
                    if isinstance(documents_payload, dict)
                    else {}
                )
                chunks = (
                    [
                        _dict_to_retrieved_chunk(row)
                        for row in chunks_payload or []
                        if isinstance(row, dict)
                    ]
                    if isinstance(chunks_payload, list)
                    else []
                )
                index_payload = payload.get("index")
                state = _DatasetState(
                    str(dataset_id),
                    documents=documents,
                    chunks=chunks,
                    index=dict(index_payload or {}) if isinstance(index_payload, dict) else {},
                    rebuild_jobs={
                        str(job_id): _rebuild_job_from_dict(row)
                        for job_id, row in (jobs_payload or {}).items()
                        if isinstance(row, dict)
                    }
                    if isinstance(jobs_payload, dict)
                    else {},
                )
                self._prepare_loaded_state(state)
                loaded[str(dataset_id)] = state
            self.datasets = loaded
        except RECOVERABLE_ERRORS:
            self.datasets = {}

    def _persist_locked(self) -> None:
        payload = {
            "version": 1,
            "datasets": {
                dataset_id: {
                    "dataset_id": state.dataset_id,
                    "documents": {
                        doc_id: doc.to_dict() for doc_id, doc in sorted(state.documents.items())
                    },
                    "chunks": [_chunk_to_dict(chunk) for chunk in state.chunks],
                    "index": dict(state.index or {}),
                    "rebuild_jobs": {
                        job_id: job.to_dict() for job_id, job in sorted(state.rebuild_jobs.items())
                    },
                }
                for dataset_id, state in sorted(self.datasets.items())
            },
        }
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.storage_path.with_suffix(self.storage_path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(self.storage_path)
        self.lock.revision = self.lock.revision_now()
