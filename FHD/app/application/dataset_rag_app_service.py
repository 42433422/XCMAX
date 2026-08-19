# ruff: noqa: E402, F401
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import uuid
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from difflib import unified_diff
from pathlib import Path
from typing import Any

from app.infrastructure.rag import (
    HybridRetriever,
    RetrievedChunk,
    SemanticChunker,
    get_default_embedder,
)
from app.infrastructure.rag.citation_tracker import Citation, CitationTracker
from app.infrastructure.rag.dataset_vector_index import (
    DatasetVectorIndexBackend,
    DatasetVectorPgIndex,
    DatasetVectorSQLiteIndex,
    default_dataset_vector_index_path,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS
from app.utils.path_io.path_utils import get_app_data_dir, get_upload_dir
from app.utils.security.safe_download_path import (
    UnsafeDownloadPathError,
    resolve_under_allowed_dirs,
)

_DATASET_DOWNLOAD_ERRORS: tuple[type[Exception], ...] = RECOVERABLE_ERRORS + (
    UnsafeDownloadPathError,
)


from app.application.dataset_rag_app_service_part01 import (
    DatasetDocument as DatasetDocument,
)
from app.application.dataset_rag_app_service_part01 import (
    DatasetRebuildJob as DatasetRebuildJob,
)

DATASET_READ_PERMISSION = "dataset.read"
DATASET_WRITE_PERMISSION = "dataset.write"
DATASET_ADMIN_PERMISSION = "dataset.admin"
REBUILD_TERMINAL_STATUSES = {"completed", "failed", "cancelled"}


from app.application.dataset_rag_app_service_datasetragapplicationservice_mixin01 import (
    _DatasetRagApplicationServicePart01Mixin,
)
from app.application.dataset_rag_app_service_datasetragapplicationservice_mixin02 import (
    _DatasetRagApplicationServicePart02Mixin,
)


@dataclass(frozen=True)
class DatasetAccessContext:
    """Trusted caller identity and permissions for tenant-scoped dataset access."""

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
from app.application.dataset_rag_app_service_part02 import (
    _DatasetState as _DatasetState,
)
from app.application.dataset_rag_app_service_part02 import (
    _semantic_embedding_available as _semantic_embedding_available,
)
from app.application.dataset_rag_app_service_part03 import (
    DatasetRagApplicationService as DatasetRagApplicationService,
)
from app.application.dataset_rag_app_service_part03 import (
    _build_dataset_vector_index_backend as _build_dataset_vector_index_backend,
)
from app.application.dataset_rag_app_service_part03 import (
    _chunk_to_dict as _chunk_to_dict,
)
from app.application.dataset_rag_app_service_part03 import (
    _citation_to_dict as _citation_to_dict,
)
from app.application.dataset_rag_app_service_part03 import (
    _clean_key as _clean_key,
)
from app.application.dataset_rag_app_service_part03 import (
    _coerce_access_context as _coerce_access_context,
)
from app.application.dataset_rag_app_service_part03 import (
    _dataset_permission_denied as _dataset_permission_denied,
)
from app.application.dataset_rag_app_service_part03 import (
    _default_storage_path as _default_storage_path,
)
from app.application.dataset_rag_app_service_part03 import (
    _deterministic_answer as _deterministic_answer,
)
from app.application.dataset_rag_app_service_part03 import (
    _dict_to_retrieved_chunk as _dict_to_retrieved_chunk,
)
from app.application.dataset_rag_app_service_part03 import (
    _document_from_dict as _document_from_dict,
)
from app.application.dataset_rag_app_service_part03 import (
    _empty_rebuild_queue_summary as _empty_rebuild_queue_summary,
)
from app.application.dataset_rag_app_service_part03 import (
    _ensure_dataset_permission as _ensure_dataset_permission,
)
from app.application.dataset_rag_app_service_part03 import (
    _ensure_tenant_allowed as _ensure_tenant_allowed,
)
from app.application.dataset_rag_app_service_part03 import (
    _has_dataset_permission as _has_dataset_permission,
)
from app.application.dataset_rag_app_service_part03 import (
    _rebuild_job_from_dict as _rebuild_job_from_dict,
)
from app.application.dataset_rag_app_service_part03 import (
    _resolve_max_concurrent_rebuild_jobs as _resolve_max_concurrent_rebuild_jobs,
)
from app.application.dataset_rag_app_service_part03 import (
    _resolve_tenant_for_access as _resolve_tenant_for_access,
)
from app.application.dataset_rag_app_service_part03 import (
    _stable_document_id as _stable_document_id,
)

_GRAPH_TOPIC_METADATA_KEYS = frozenset(
    {"topic", "topics", "tag", "tags", "entity", "entities", "keywords", "category", "doc_type"}
)
_GRAPH_TOPIC_STOPWORDS = frozenset(
    {
        "about",
        "after",
        "before",
        "default",
        "document",
        "from",
        "into",
        "persy",
        "that",
        "their",
        "this",
        "with",
        "以及",
        "他们",
        "内容",
        "可以",
        "如何",
        "我们",
        "文件",
        "是否",
        "知识",
        "系统",
        "资料",
        "这个",
        "这些",
        "进行",
        "需要",
    }
)


from app.application.dataset_rag_app_service_part04 import (
    _build_knowledge_graph_payload as _build_knowledge_graph_payload,
)
from app.application.dataset_rag_app_service_part04 import (
    _clean_graph_label as _clean_graph_label,
)
from app.application.dataset_rag_app_service_part04 import (
    _embedding_metadata as _embedding_metadata,
)
from app.application.dataset_rag_app_service_part04 import (
    _extract_graph_topics as _extract_graph_topics,
)
from app.application.dataset_rag_app_service_part04 import (
    _filter_chunks as _filter_chunks,
)
from app.application.dataset_rag_app_service_part04 import (
    _graph_chunk_node_id as _graph_chunk_node_id,
)
from app.application.dataset_rag_app_service_part04 import (
    _graph_excerpt as _graph_excerpt,
)
from app.application.dataset_rag_app_service_part04 import (
    _graph_knowledge_label as _graph_knowledge_label,
)
from app.application.dataset_rag_app_service_part04 import (
    _graph_source_label as _graph_source_label,
)
from app.application.dataset_rag_app_service_part04 import (
    _graph_topic_candidates as _graph_topic_candidates,
)
from app.application.dataset_rag_app_service_part04 import (
    _metadata_matches as _metadata_matches,
)
from app.application.dataset_rag_app_service_part04 import (
    _public_graph_metadata as _public_graph_metadata,
)
from app.application.dataset_rag_app_service_part04 import (
    _rerank_chunks as _rerank_chunks,
)
from app.application.dataset_rag_app_service_part04 import (
    _select_graph_chunks as _select_graph_chunks,
)
from app.application.dataset_rag_app_service_part04 import (
    _tokenize_for_rerank as _tokenize_for_rerank,
)
from app.application.dataset_rag_app_service_part04 import (
    _utc_now_iso as _utc_now_iso,
)

_dataset_rag_app_service: DatasetRagApplicationService | None = None
_dataset_rag_lock = threading.Lock()


from app.application.dataset_rag_app_service_part05 import (
    get_dataset_rag_app_service as get_dataset_rag_app_service,
)
from app.application.dataset_rag_app_service_part05 import (
    reset_dataset_rag_app_service_for_tests as reset_dataset_rag_app_service_for_tests,
)
