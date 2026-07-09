from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.infrastructure.rag import (
    RetrievedChunk,
)


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


@dataclass
class DatasetDocument:
    document_id: str
    source: str
    parser: str
    text_length: int
    chunk_count: int
    tenant_id: str = "default"
    version: int = 1
    version_label: str = "v1"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
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


@dataclass
class DatasetRebuildJob:
    job_id: str
    dataset_id: str
    status: str = "queued"
    tenant_id: str = ""
    metadata_filter: dict[str, Any] = field(default_factory=dict)
    document_count: int = 0
    chunk_count: int = 0
    error: str = ""
    attempt_count: int = 0
    max_attempts: int = 1
    worker_id: str = ""
    created_at: str = field(default_factory=lambda: _utc_now_iso())
    queued_at: str = field(default_factory=lambda: _utc_now_iso())
    started_at: str = ""
    completed_at: str = ""
    cancelled_at: str = ""
    updated_at: str = field(default_factory=lambda: _utc_now_iso())

    def to_dict(self) -> dict[str, Any]:
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


DATASET_READ_PERMISSION = "dataset.read"
DATASET_WRITE_PERMISSION = "dataset.write"
DATASET_ADMIN_PERMISSION = "dataset.admin"
REBUILD_TERMINAL_STATUSES = {"completed", "failed", "cancelled"}


@dataclass(frozen=True)
class DatasetAccessContext:
    actor_id: str = ""
    tenant_id: str = ""
    permissions: frozenset[str] = field(default_factory=frozenset)
    is_admin: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "actor_id": self.actor_id,
            "tenant_id": self.tenant_id,
            "permissions": sorted(self.permissions),
            "is_admin": self.is_admin,
        }


@dataclass
class _DatasetState:
    dataset_id: str
    documents: dict[str, DatasetDocument] = field(default_factory=dict)
    chunks: list[RetrievedChunk] = field(default_factory=list)
    index: dict[str, Any] = field(default_factory=dict)
    rebuild_jobs: dict[str, DatasetRebuildJob] = field(default_factory=dict)

