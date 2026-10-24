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
from app.application.dataset_rag_queue import DatasetStateLock
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
