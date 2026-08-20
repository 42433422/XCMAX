# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.dataset_rag_app_service")


@_facade().dataclass
class DatasetDocument:
    document_id: str
    source: str
    parser: str
    text_length: int
    chunk_count: int
    tenant_id: str = "default"
    version: int = 1
    version_label: str = "v1"
    metadata: dict[str, _facade().Any] = _facade().field(default_factory=dict)

    def to_dict(self) -> dict[str, _facade().Any]:
        return {
            "document_id": self.document_id,
            "source": self.source,
            "parser": self.parser,
            "text_length": self.text_length,
            "chunk_count": self.chunk_count,
            "tenant_id": self.tenant_id,
            "version": self.version,
            "version_label": self.version_label,
            "metadata": self.metadata,
        }


@_facade().dataclass
class DatasetRebuildJob:
    job_id: str
    dataset_id: str
    status: str = "queued"
    tenant_id: str = ""
    metadata_filter: dict[str, _facade().Any] = _facade().field(default_factory=dict)
    document_count: int = 0
    chunk_count: int = 0
    error: str = ""
    attempt_count: int = 0
    max_attempts: int = 1
    worker_id: str = ""
    created_at: str = _facade().field(default_factory=lambda: _facade()._utc_now_iso())
    queued_at: str = _facade().field(default_factory=lambda: _facade()._utc_now_iso())
    started_at: str = ""
    completed_at: str = ""
    cancelled_at: str = ""
    updated_at: str = _facade().field(default_factory=lambda: _facade()._utc_now_iso())

    def to_dict(self) -> dict[str, _facade().Any]:
        return {
            "job_id": self.job_id,
            "dataset_id": self.dataset_id,
            "status": self.status,
            "tenant_id": self.tenant_id,
            "metadata_filter": self.metadata_filter,
            "document_count": self.document_count,
            "chunk_count": self.chunk_count,
            "error": self.error,
            "attempt_count": self.attempt_count,
            "max_attempts": self.max_attempts,
            "worker_id": self.worker_id,
            "created_at": self.created_at,
            "queued_at": self.queued_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "cancelled_at": self.cancelled_at,
            "updated_at": self.updated_at,
        }
