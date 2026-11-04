"""Dataset records, stable identity, serialization, and source version rules."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.infrastructure.rag import RetrievedChunk
from app.infrastructure.rag.citation_tracker import Citation


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


@dataclass
class _DatasetState:
    dataset_id: str
    documents: dict[str, DatasetDocument] = field(default_factory=dict)
    chunks: list[RetrievedChunk] = field(default_factory=list)
    index: dict[str, Any] = field(default_factory=dict)
    rebuild_jobs: dict[str, DatasetRebuildJob] = field(default_factory=dict)


def _clean_key(value: str, *, default: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in value.strip())
    return cleaned.strip("._-") or default


def _stable_document_id(
    dataset_id: str, tenant_id: str, source: str, version: int, text: str
) -> str:
    digest = hashlib.sha256(
        f"{dataset_id}\x00{tenant_id}\x00{source}\x00{version}\x00{text}".encode()
    ).hexdigest()
    return f"doc_{digest[:16]}"


def _document_from_dict(data: dict[str, Any]) -> DatasetDocument:
    metadata = dict(data.get("metadata") or {})
    version = int(data.get("version") or metadata.get("document_version") or 1)
    return DatasetDocument(
        document_id=str(data.get("document_id") or ""),
        source=str(data.get("source") or ""),
        parser=str(data.get("parser") or ""),
        text_length=int(data.get("text_length") or 0),
        chunk_count=int(data.get("chunk_count") or 0),
        tenant_id=_clean_key(
            str(data.get("tenant_id") or metadata.get("tenant_id") or "default"), default="default"
        ),
        version=version,
        version_label=str(
            data.get("version_label") or metadata.get("version_label") or f"v{version}"
        ),
        metadata=metadata,
    )


def _rebuild_job_from_dict(data: dict[str, Any]) -> DatasetRebuildJob:
    created_at = str(data.get("created_at") or _utc_now_iso())
    queued_at = str(data.get("queued_at") or created_at)
    return DatasetRebuildJob(
        job_id=str(data.get("job_id") or ""),
        dataset_id=str(data.get("dataset_id") or ""),
        status=str(data.get("status") or "queued"),
        tenant_id=str(data.get("tenant_id") or ""),
        metadata_filter=dict(data.get("metadata_filter") or {}),
        document_count=int(data.get("document_count") or 0),
        chunk_count=int(data.get("chunk_count") or 0),
        error=str(data.get("error") or ""),
        attempt_count=int(data.get("attempt_count") or 0),
        max_attempts=max(1, int(data.get("max_attempts") or 1)),
        worker_id=str(data.get("worker_id") or ""),
        created_at=created_at,
        queued_at=queued_at,
        started_at=str(data.get("started_at") or ""),
        completed_at=str(data.get("completed_at") or ""),
        cancelled_at=str(data.get("cancelled_at") or ""),
        updated_at=str(data.get("updated_at") or queued_at),
    )


def _chunk_to_dict(chunk: RetrievedChunk, *, public: bool = False) -> dict[str, Any]:
    metadata = dict(chunk.metadata or {})
    if public:
        metadata = {key: value for key, value in metadata.items() if not str(key).startswith("_")}
    return {
        "text": chunk.text,
        "score": chunk.score,
        "source": chunk.source,
        "chunk_index": chunk.chunk_index,
        "char_start": chunk.char_start,
        "char_end": chunk.char_end,
        "metadata": metadata,
        "source_url": chunk.source_url,
        "page": chunk.page,
    }


def _dict_to_retrieved_chunk(data: dict[str, Any]) -> RetrievedChunk:
    return RetrievedChunk(
        text=str(data.get("text") or ""),
        score=float(data.get("score") or 0.0),
        source=str(data.get("source") or ""),
        chunk_index=int(data.get("chunk_index") or 0),
        char_start=int(data.get("char_start") or 0),
        char_end=int(data.get("char_end") or 0),
        metadata=dict(data.get("metadata") or {}),
        source_url=str(data.get("source_url") or ""),
        page=data.get("page") if isinstance(data.get("page"), int) else None,
    )


def _citation_to_dict(citation: Citation) -> dict[str, Any]:
    return {
        "index": citation.index,
        "text": citation.text,
        "source": citation.source,
        "chunk_index": citation.chunk_index,
        "char_range": list(citation.char_range),
        "source_url": citation.source_url,
        "page": citation.page,
    }


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _renumber_chunks(state: _DatasetState) -> None:
    for index, chunk in enumerate(state.chunks):
        chunk.chunk_index = index


def _resolve_document_version(
    state: _DatasetState, *, source: str, tenant_id: str, requested: int | str | None
) -> int:
    text = str(requested or "").strip()
    if text:
        if text.lower().startswith("v") and text[1:].isdigit():
            return max(1, int(text[1:]))
        if text.isdigit():
            return max(1, int(text))
        raise ValueError("version must be an integer, vN, or empty")
    versions = [
        int(doc.version or 1)
        for doc in state.documents.values()
        if doc.source == source and doc.tenant_id == tenant_id
    ]
    return max(versions) + 1 if versions else 1


def _resolve_document_for_version(
    state: _DatasetState, *, source: str, tenant_id: str, version: str | int
) -> DatasetDocument | None:
    candidates = [
        doc
        for doc in state.documents.values()
        if doc.source == source and doc.tenant_id == tenant_id
    ]
    if not candidates:
        return None
    version_text = str(version or "").strip()
    if not version_text or version_text.lower() == "latest":
        return max(candidates, key=lambda doc: int(doc.version or 1))
    normalized = version_text[1:] if version_text.lower().startswith("v") else version_text
    for doc in candidates:
        if str(doc.version) == normalized or doc.version_label == version_text:
            return doc
    return None


def _document_text_locked(state: _DatasetState, document_id: str) -> str:
    chunks = [
        chunk
        for chunk in state.chunks
        if isinstance(chunk.metadata, dict)
        and str(chunk.metadata.get("document_id") or "") == document_id
    ]
    chunks.sort(key=lambda item: (item.char_start, item.chunk_index))
    return "\n".join(chunk.text for chunk in chunks if chunk.text)
