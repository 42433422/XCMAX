from __future__ import annotations

import hashlib
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.infrastructure.rag import (
    RetrievedChunk,
)
from app.infrastructure.rag.citation_tracker import Citation
from app.infrastructure.rag.dataset_vector_index import (
    DatasetVectorIndexBackend,
    default_dataset_vector_index_path,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS
from app.utils.path_utils import get_app_data_dir

from .types import (
    DATASET_ADMIN_PERMISSION,
    DATASET_READ_PERMISSION,
    DatasetAccessContext,
    DatasetDocument,
    DatasetRebuildJob,
    _utc_now_iso,
)


def _default_storage_path() -> Path:
    configured = (
        os.environ.get("DATASET_RAG_STORE_PATH")
        or os.environ.get("XCAGI_DATASET_RAG_STORE_PATH")
        or ""
    ).strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(get_app_data_dir()).resolve() / "dataset_rag" / "datasets.json"


def _build_dataset_vector_index_backend(
    *,
    backend_name: str | None,
    storage_path: Path,
    vector_index_path: str | Path | None,
) -> DatasetVectorIndexBackend | None:
    configured = (
        backend_name
        if backend_name is not None
        else os.environ.get("DATASET_RAG_VECTOR_BACKEND")
        or os.environ.get("XCAGI_DATASET_RAG_VECTOR_BACKEND")
        or "sqlite"
    )
    name = str(configured or "").strip().lower()
    if name in {"", "none", "disabled", "off", "json", "memory"}:
        return None
    if name in {"sqlite", "sqlite_vector"}:
        from app.application import dataset_rag_app_service as dataset_rag_module

        path = (
            Path(vector_index_path).expanduser().resolve()
            if vector_index_path is not None
            else default_dataset_vector_index_path(storage_path)
        )
        return dataset_rag_module.DatasetVectorSQLiteIndex(path)
    if name in {"pgvector", "postgres", "postgresql"}:
        from app.application import dataset_rag_app_service as dataset_rag_module

        database_url = (
            os.environ.get("DATASET_RAG_PGVECTOR_DATABASE_URL")
            or os.environ.get("XCAGI_DATASET_RAG_PGVECTOR_DATABASE_URL")
            or os.environ.get("PGVECTOR_DATABASE_URL")
            or os.environ.get("DATABASE_URL")
            or ""
        ).strip()
        dimension_raw = (
            os.environ.get("DATASET_RAG_PGVECTOR_DIMENSION")
            or os.environ.get("XCAGI_DATASET_RAG_PGVECTOR_DIMENSION")
            or "256"
        )
        try:
            dimension = int(dimension_raw)
        except (TypeError, ValueError):
            dimension = 256
        return dataset_rag_module.DatasetVectorPgIndex(database_url, dimension=dimension)
    raise ValueError(f"unsupported dataset vector backend: {configured}")


def _resolve_max_concurrent_rebuild_jobs(configured: int | None) -> int:
    if configured is not None:
        return max(1, min(int(configured), 8))
    raw = os.environ.get("DATASET_RAG_REBUILD_MAX_CONCURRENT", "").strip()
    if not raw:
        raw = os.environ.get("XCAGI_DATASET_RAG_REBUILD_MAX_CONCURRENT", "").strip()
    if raw.isdigit():
        return max(1, min(int(raw), 8))
    return 1


def _empty_rebuild_queue_summary(
    max_concurrent_jobs: int,
    *,
    worker_enabled: bool,
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


def _clean_key(value: str, *, default: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in value.strip())
    return cleaned.strip("._-") or default


def _coerce_access_context(
    value: DatasetAccessContext | dict[str, Any] | None,
) -> DatasetAccessContext | None:
    if value is None:
        return None
    if isinstance(value, DatasetAccessContext):
        return value
    permissions_value = value.get("permissions") if isinstance(value, dict) else None
    if isinstance(permissions_value, str):
        permissions = frozenset(
            part.strip() for part in permissions_value.replace(";", ",").split(",") if part.strip()
        )
    elif isinstance(permissions_value, (list, tuple, set, frozenset)):
        permissions = frozenset(
            str(part).strip() for part in permissions_value if str(part).strip()
        )
    else:
        permissions = frozenset()
    return DatasetAccessContext(
        actor_id=str(value.get("actor_id") or value.get("user_id") or ""),
        tenant_id=_clean_key(str(value.get("tenant_id") or ""), default="")
        if value.get("tenant_id")
        else "",
        permissions=permissions,
        is_admin=bool(value.get("is_admin") or value.get("admin")),
    )


def _has_dataset_permission(context: DatasetAccessContext | None, permission: str) -> bool:
    if context is None:
        return True
    if context.is_admin or DATASET_ADMIN_PERMISSION in context.permissions:
        return True
    if permission in context.permissions:
        return True
    prefix = permission.split(".", 1)[0]
    return f"{prefix}.*" in context.permissions or "*" in context.permissions


def _dataset_permission_denied(
    *,
    dataset_id: str,
    permission: str,
    message: str,
    context: DatasetAccessContext | None,
) -> dict[str, Any]:
    return {
        "success": False,
        "dataset_id": dataset_id,
        "error_code": "dataset_permission_denied",
        "message": message,
        "required_permission": permission,
        "access": context.to_dict() if context is not None else {},
    }


def _ensure_dataset_permission(
    context: DatasetAccessContext | None,
    permission: str,
    *,
    dataset_id: str,
) -> dict[str, Any] | None:
    if _has_dataset_permission(context, permission):
        return None
    return _dataset_permission_denied(
        dataset_id=dataset_id,
        permission=permission,
        message=f"{permission} permission is required",
        context=context,
    )


def _ensure_tenant_allowed(
    context: DatasetAccessContext | None,
    tenant_id: str,
    *,
    dataset_id: str,
    operation: str,
) -> dict[str, Any] | None:
    if context is None or context.is_admin or DATASET_ADMIN_PERMISSION in context.permissions:
        return None
    actor_tenant = _clean_key(context.tenant_id, default="") if context.tenant_id else ""
    target_tenant = _clean_key(str(tenant_id or ""), default="") if tenant_id else ""
    if not actor_tenant:
        return _dataset_permission_denied(
            dataset_id=dataset_id,
            permission=DATASET_READ_PERMISSION,
            message=f"{operation} requires an actor tenant context",
            context=context,
        )
    if not target_tenant:
        return _dataset_permission_denied(
            dataset_id=dataset_id,
            permission=DATASET_ADMIN_PERMISSION,
            message=f"{operation} across all tenants requires dataset admin",
            context=context,
        )
    if actor_tenant != target_tenant:
        return _dataset_permission_denied(
            dataset_id=dataset_id,
            permission=DATASET_ADMIN_PERMISSION,
            message=f"{operation} cannot access tenant {target_tenant}",
            context=context,
        )
    return None


def _resolve_tenant_for_access(
    access_context: DatasetAccessContext | dict[str, Any] | None,
    requested_tenant_id: str,
    *,
    required_permission: str,
    default_without_context: str,
    dataset_id: str,
) -> tuple[str, dict[str, Any] | None]:
    context = _coerce_access_context(access_context)
    denied = _ensure_dataset_permission(context, required_permission, dataset_id=dataset_id)
    if denied is not None:
        return "", denied
    requested = (
        _clean_key(str(requested_tenant_id or ""), default="") if requested_tenant_id else ""
    )
    if context is None:
        if requested:
            return requested, None
        return (
            _clean_key(str(default_without_context), default=default_without_context)
            if default_without_context
            else ""
        ), None
    if context.is_admin or DATASET_ADMIN_PERMISSION in context.permissions:
        if requested:
            return requested, None
        return (
            _clean_key(str(default_without_context), default=default_without_context)
            if default_without_context
            else ""
        ), None
    actor_tenant = _clean_key(context.tenant_id, default="") if context.tenant_id else ""
    if not actor_tenant:
        return "", _dataset_permission_denied(
            dataset_id=dataset_id,
            permission=required_permission,
            message="dataset tenant context is required",
            context=context,
        )
    if requested and requested != actor_tenant:
        return "", _dataset_permission_denied(
            dataset_id=dataset_id,
            permission=DATASET_ADMIN_PERMISSION,
            message=f"tenant {requested} is outside requester scope",
            context=context,
        )
    return actor_tenant, None


def _stable_document_id(
    dataset_id: str,
    tenant_id: str,
    source: str,
    version: int,
    text: str,
) -> str:
    digest = hashlib.sha256(
        f"{dataset_id}\0{tenant_id}\0{source}\0{version}\0{text}".encode()
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
            str(data.get("tenant_id") or metadata.get("tenant_id") or "default"),
            default="default",
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


def _deterministic_answer(query: str, chunks: list[RetrievedChunk]) -> str:
    if not chunks:
        return ""
    excerpt = chunks[0].text.strip().replace("\n", " ")
    if len(excerpt) > 320:
        excerpt = excerpt[:317].rstrip() + "..."
    prefix = f"Based on the retrieved dataset evidence for {query!r}: " if query else ""
    return f"{prefix}{excerpt} [1]"


def _embedding_metadata(
    embedder: Callable[[str], list[float]] | None,
    text: str,
) -> dict[str, Any]:
    if embedder is None:
        return {}
    try:
        embedding = embedder(text)
    except RECOVERABLE_ERRORS:
        return {}
    if not isinstance(embedding, list) or not embedding:
        return {}
    try:
        return {"_embedding": [float(value) for value in embedding]}
    except (TypeError, ValueError):
        return {}


def _filter_chunks(
    chunks: list[RetrievedChunk],
    *,
    tenant_id: str,
    version: str | int,
    metadata_filter: dict[str, Any],
) -> list[RetrievedChunk]:
    selected = list(chunks)
    tenant_key = _clean_key(str(tenant_id or ""), default="") if tenant_id else ""
    if tenant_key:
        selected = [
            chunk
            for chunk in selected
            if str((chunk.metadata or {}).get("tenant_id") or "") == tenant_key
        ]
    if metadata_filter:
        selected = [chunk for chunk in selected if _metadata_matches(chunk, metadata_filter)]

    version_text = str(version or "").strip()
    if not version_text:
        return selected
    if version_text.lower() == "latest":
        latest_by_scope: dict[tuple[str, str], int] = {}
        for chunk in selected:
            metadata = chunk.metadata or {}
            scope = (
                str(metadata.get("tenant_id") or ""),
                str(metadata.get("source") or chunk.source or ""),
            )
            latest_by_scope[scope] = max(
                latest_by_scope.get(scope, 0),
                int(metadata.get("document_version") or 1),
            )
        return [
            chunk
            for chunk in selected
            if int((chunk.metadata or {}).get("document_version") or 1)
            == latest_by_scope.get(
                (
                    str((chunk.metadata or {}).get("tenant_id") or ""),
                    str((chunk.metadata or {}).get("source") or chunk.source or ""),
                ),
                1,
            )
        ]
    normalized = version_text[1:] if version_text.lower().startswith("v") else version_text
    return [
        chunk
        for chunk in selected
        if str((chunk.metadata or {}).get("document_version") or "") == normalized
        or str((chunk.metadata or {}).get("version_label") or "") == version_text
    ]


def _metadata_matches(chunk: RetrievedChunk, metadata_filter: dict[str, Any]) -> bool:
    metadata = dict(chunk.metadata or {})
    metadata.setdefault("source", chunk.source)
    for key, expected in metadata_filter.items():
        actual = metadata.get(str(key))
        if isinstance(expected, list):
            expected_values = {str(item) for item in expected}
            if str(actual) not in expected_values:
                return False
        elif isinstance(expected, dict):
            if not isinstance(actual, dict):
                return False
            for nested_key, nested_expected in expected.items():
                if str(actual.get(str(nested_key))) != str(nested_expected):
                    return False
        elif str(actual) != str(expected):
            return False
    return True


def _rerank_chunks(
    query: str,
    chunks: list[RetrievedChunk],
    *,
    top_k: int,
) -> list[RetrievedChunk]:
    query_terms = set(_tokenize_for_rerank(query))
    if not query_terms:
        return chunks[:top_k]
    reranked: list[RetrievedChunk] = []
    for chunk in chunks:
        chunk_terms = set(_tokenize_for_rerank(chunk.text))
        overlap = len(query_terms & chunk_terms)
        exact_bonus = (
            1.0 if query.strip().lower() and query.strip().lower() in chunk.text.lower() else 0.0
        )
        boost = overlap / max(1, len(query_terms)) + exact_bonus
        reranked.append(
            RetrievedChunk(
                text=chunk.text,
                score=float(chunk.score) + boost,
                source=f"{chunk.source}+rerank" if "rerank" not in chunk.source else chunk.source,
                chunk_index=chunk.chunk_index,
                char_start=chunk.char_start,
                char_end=chunk.char_end,
                metadata=chunk.metadata,
                source_url=chunk.source_url,
                page=chunk.page,
            )
        )
    return sorted(reranked, key=lambda item: item.score, reverse=True)[:top_k]


def _tokenize_for_rerank(text: str) -> list[str]:
    cleaned = "".join(ch.lower() if ch.isalnum() else " " for ch in text)
    return [part for part in cleaned.split() if part]
