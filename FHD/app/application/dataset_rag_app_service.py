"""Dataset RAG application service — re-export shim (split into dataset_rag/)."""

from __future__ import annotations

from app.infrastructure.rag.dataset_vector_index import (
    DatasetVectorPgIndex as DatasetVectorPgIndex,
)
from app.infrastructure.rag.dataset_vector_index import (
    DatasetVectorSQLiteIndex as DatasetVectorSQLiteIndex,
)

from .dataset_rag.helpers import (
    _build_dataset_vector_index_backend,
    _chunk_to_dict,
    _citation_to_dict,
    _clean_key,
    _coerce_access_context,
    _dataset_permission_denied,
    _default_storage_path,
    _deterministic_answer,
    _dict_to_retrieved_chunk,
    _document_from_dict,
    _embedding_metadata,
    _empty_rebuild_queue_summary,
    _ensure_dataset_permission,
    _ensure_tenant_allowed,
    _filter_chunks,
    _has_dataset_permission,
    _metadata_matches,
    _rebuild_job_from_dict,
    _rerank_chunks,
    _resolve_max_concurrent_rebuild_jobs,
    _resolve_tenant_for_access,
    _stable_document_id,
    _tokenize_for_rerank,
    _utc_now_iso,
)
from .dataset_rag.service import DatasetRagApplicationService as DatasetRagApplicationService
from .dataset_rag.singleton import (
    _dataset_rag_app_service,
    _dataset_rag_lock,
    get_dataset_rag_app_service,
    reset_dataset_rag_app_service_for_tests,
)
from .dataset_rag.types import (
    DATASET_ADMIN_PERMISSION,
    DATASET_READ_PERMISSION,
    DATASET_WRITE_PERMISSION,
    REBUILD_TERMINAL_STATUSES,
    DatasetAccessContext,
    DatasetDocument,
    DatasetRebuildJob,
    _DatasetState,
)

__all__ = [
    "DATASET_ADMIN_PERMISSION",
    "DATASET_READ_PERMISSION",
    "DATASET_WRITE_PERMISSION",
    "DatasetAccessContext",
    "DatasetDocument",
    "DatasetRagApplicationService",
    "DatasetRebuildJob",
    "DatasetVectorPgIndex",
    "DatasetVectorSQLiteIndex",
    "REBUILD_TERMINAL_STATUSES",
    "_DatasetState",
    "_build_dataset_vector_index_backend",
    "_chunk_to_dict",
    "_citation_to_dict",
    "_clean_key",
    "_coerce_access_context",
    "_dataset_permission_denied",
    "_dataset_rag_app_service",
    "_dataset_rag_lock",
    "_default_storage_path",
    "_deterministic_answer",
    "_dict_to_retrieved_chunk",
    "_document_from_dict",
    "_embedding_metadata",
    "_empty_rebuild_queue_summary",
    "_ensure_dataset_permission",
    "_ensure_tenant_allowed",
    "_filter_chunks",
    "_has_dataset_permission",
    "_metadata_matches",
    "_rebuild_job_from_dict",
    "_rerank_chunks",
    "_resolve_max_concurrent_rebuild_jobs",
    "_resolve_tenant_for_access",
    "_stable_document_id",
    "_tokenize_for_rerank",
    "_utc_now_iso",
    "get_dataset_rag_app_service",
    "reset_dataset_rag_app_service_for_tests",
]
