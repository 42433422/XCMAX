"""Public dataset application API and dependency composition root."""

from __future__ import annotations

import hashlib
import multiprocessing
import os
import threading
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Thread
from typing import Any

from app.application.dataset_rag.access_policy import (
    DATASET_ADMIN_PERMISSION as DATASET_ADMIN_PERMISSION,
)
from app.application.dataset_rag.access_policy import (
    DATASET_READ_PERMISSION as DATASET_READ_PERMISSION,
)
from app.application.dataset_rag.access_policy import (
    DATASET_WRITE_PERMISSION as DATASET_WRITE_PERMISSION,
)
from app.application.dataset_rag.access_policy import (
    _coerce_access_context as _coerce_access_context,
)
from app.application.dataset_rag.access_policy import (
    _dataset_permission_denied as _dataset_permission_denied,
)
from app.application.dataset_rag.access_policy import (
    _ensure_dataset_permission as _ensure_dataset_permission,
)
from app.application.dataset_rag.access_policy import (
    _ensure_tenant_allowed as _ensure_tenant_allowed,
)
from app.application.dataset_rag.access_policy import (
    _has_dataset_permission as _has_dataset_permission,
)
from app.application.dataset_rag.access_policy import (
    _resolve_tenant_for_access as _resolve_tenant_for_access,
)
from app.application.dataset_rag.api_keys import DatasetApiKeyStore
from app.application.dataset_rag.document_lifecycle import (
    _DATASET_DOWNLOAD_ERRORS as _DATASET_DOWNLOAD_ERRORS,
)
from app.application.dataset_rag.document_lifecycle import DocumentLifecycle
from app.application.dataset_rag.document_parser import DocumentParser
from app.application.dataset_rag.feedback import DatasetFeedbackStore
from app.application.dataset_rag.knowledge_graph import (
    _GRAPH_TOPIC_METADATA_KEYS as _GRAPH_TOPIC_METADATA_KEYS,
)
from app.application.dataset_rag.knowledge_graph import (
    _GRAPH_TOPIC_STOPWORDS as _GRAPH_TOPIC_STOPWORDS,
)
from app.application.dataset_rag.knowledge_graph import (
    _build_knowledge_graph_payload as _build_knowledge_graph_payload,
)
from app.application.dataset_rag.knowledge_graph import _clean_graph_label as _clean_graph_label
from app.application.dataset_rag.knowledge_graph import (
    _extract_graph_topics as _extract_graph_topics,
)
from app.application.dataset_rag.knowledge_graph import _graph_chunk_node_id as _graph_chunk_node_id
from app.application.dataset_rag.knowledge_graph import _graph_excerpt as _graph_excerpt
from app.application.dataset_rag.knowledge_graph import (
    _graph_knowledge_label as _graph_knowledge_label,
)
from app.application.dataset_rag.knowledge_graph import _graph_source_label as _graph_source_label
from app.application.dataset_rag.knowledge_graph import (
    _graph_topic_candidates as _graph_topic_candidates,
)
from app.application.dataset_rag.knowledge_graph import (
    _public_graph_metadata as _public_graph_metadata,
)
from app.application.dataset_rag.knowledge_graph import _select_graph_chunks as _select_graph_chunks
from app.application.dataset_rag.models import DatasetAccessContext as DatasetAccessContext
from app.application.dataset_rag.models import DatasetDocument as DatasetDocument
from app.application.dataset_rag.models import DatasetRebuildJob as DatasetRebuildJob
from app.application.dataset_rag.models import _chunk_to_dict as _chunk_to_dict
from app.application.dataset_rag.models import _citation_to_dict as _citation_to_dict
from app.application.dataset_rag.models import _clean_key as _clean_key
from app.application.dataset_rag.models import _DatasetState as _DatasetState
from app.application.dataset_rag.models import _dict_to_retrieved_chunk as _dict_to_retrieved_chunk
from app.application.dataset_rag.models import _document_from_dict as _document_from_dict
from app.application.dataset_rag.models import (
    _document_text_locked,
    _renumber_chunks,
    _resolve_document_for_version,
    _resolve_document_version,
)
from app.application.dataset_rag.models import _rebuild_job_from_dict as _rebuild_job_from_dict
from app.application.dataset_rag.models import _source_synced_at as _source_synced_at
from app.application.dataset_rag.models import _stable_document_id as _stable_document_id
from app.application.dataset_rag.models import _utc_now_iso as _utc_now_iso
from app.application.dataset_rag.qa_pairs import normalize_qa_pairs, scoped_qa_pairs
from app.application.dataset_rag.query_gaps import DatasetQueryGapStore
from app.application.dataset_rag.rebuild_coordinator import (
    REBUILD_TERMINAL_STATUSES as REBUILD_TERMINAL_STATUSES,
)
from app.application.dataset_rag.rebuild_coordinator import (
    RebuildCoordinator,
    _rebuild_job_queue_position_locked,
    _recover_rebuild_jobs_locked,
    read_rebuild_job,
)
from app.application.dataset_rag.rebuild_coordinator import (
    _empty_rebuild_queue_summary as _empty_rebuild_queue_summary,
)
from app.application.dataset_rag.repository import DatasetRepository
from app.application.dataset_rag.retrieval import DatasetRetrieval
from app.application.dataset_rag.retrieval_policy import (
    _deterministic_answer as _deterministic_answer,
)
from app.application.dataset_rag.retrieval_policy import _filter_chunks as _filter_chunks
from app.application.dataset_rag.retrieval_policy import _metadata_matches as _metadata_matches
from app.application.dataset_rag.retrieval_policy import _rerank_chunks as _rerank_chunks
from app.application.dataset_rag.retrieval_policy import (
    _tokenize_for_rerank as _tokenize_for_rerank,
)
from app.application.dataset_rag.retrieval_policy import (
    evidence_grounding as evidence_grounding,
)
from app.application.dataset_rag.retrieval_policy import (
    resolve_min_relevance as resolve_min_relevance,
)
from app.application.dataset_rag.status import DatasetStatus
from app.application.dataset_rag.vector_index import VectorIndexService
from app.application.dataset_rag.vector_index import _embedding_metadata as _embedding_metadata
from app.application.dataset_rag.vector_index import (
    _semantic_embedding_available as _semantic_embedding_available,
)
from app.application.document_parsing.source_refresh import (
    fetch_source_text,
    source_coordinates,
)
from app.domain.app_pure.dataset_rag_queue import DatasetStateLock
from app.domain.app_pure.dataset_synonyms import normalize_synonyms
from app.infrastructure.rag import (
    HybridRetriever,
    RetrievedChunk,
    SemanticChunker,
    get_default_embedder,
)
from app.infrastructure.rag.citation_tracker import CitationTracker
from app.infrastructure.rag.dataset_vector_index import (
    DatasetVectorIndexBackend,
    DatasetVectorPgIndex,
    DatasetVectorSQLiteIndex,
    default_dataset_vector_index_path,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS
from app.utils.path_io.path_utils import get_app_data_dir, get_upload_dir


def _default_storage_path() -> Path:
    configured = (
        os.environ.get("DATASET_RAG_STORE_PATH")
        or os.environ.get("XCAGI_DATASET_RAG_STORE_PATH")
        or ""
    ).strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(get_app_data_dir(create=False)).resolve() / "dataset_rag" / "datasets.json"


def _build_dataset_vector_index_backend(
    *, backend_name: str | None, storage_path: Path, vector_index_path: str | Path | None
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
        path = (
            Path(vector_index_path).expanduser().resolve()
            if vector_index_path is not None
            else default_dataset_vector_index_path(storage_path)
        )
        return DatasetVectorSQLiteIndex(path)
    if name in {"pgvector", "postgres", "postgresql"}:
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
        return DatasetVectorPgIndex(database_url, dimension=dimension)
    raise ValueError(f"unsupported dataset vector backend: {configured}")


_DEFAULT_MAX_CONTEXT_CHARS = 6000
_MIN_CONTEXT_CHARS = 500
_MAX_CONTEXT_CHARS = 200_000


def _resolve_max_context_chars(requested: int | None) -> int:
    def _clamp(value: int) -> int:
        return max(_MIN_CONTEXT_CHARS, min(value, _MAX_CONTEXT_CHARS))

    try:
        if requested is not None and int(requested) > 0:
            return _clamp(int(requested))
    except (TypeError, ValueError):
        pass
    raw = os.environ.get("XCAGI_KB_MAX_CONTEXT_CHARS", "").strip()
    if not raw.isdigit():
        return _DEFAULT_MAX_CONTEXT_CHARS
    return _clamp(int(raw))


def _resolve_max_concurrent_rebuild_jobs(configured: int | None) -> int:
    if configured is not None:
        return max(1, min(int(configured), 8))
    raw = os.environ.get("DATASET_RAG_REBUILD_MAX_CONCURRENT", "").strip()
    if not raw:
        raw = os.environ.get("XCAGI_DATASET_RAG_REBUILD_MAX_CONCURRENT", "").strip()
    if raw.isdigit():
        return max(1, min(int(raw), 8))
    return 1


class DatasetRagApplicationService:
    """Compose dataset persistence, document lifecycle, retrieval, and rebuild workers."""

    def __init__(
        self,
        *,
        embedder: Callable[[str], list[float]] | None = None,
        allowed_roots: list[Path] | None = None,
        storage_path: str | Path | None = None,
        max_concurrent_rebuild_jobs: int | None = None,
        rebuild_workers_enabled: bool = True,
        vector_index_backend: DatasetVectorIndexBackend | None = None,
        vector_index_backend_name: str | None = None,
        vector_index_path: str | Path | None = None,
    ) -> None:
        chosen_embedder = embedder if embedder is not None else get_default_embedder()
        chosen_path = Path(storage_path).resolve() if storage_path else _default_storage_path()
        backend = (
            vector_index_backend
            if vector_index_backend is not None
            else _build_dataset_vector_index_backend(
                backend_name=vector_index_backend_name,
                storage_path=chosen_path,
                vector_index_path=vector_index_path,
            )
        )
        self._vector = VectorIndexService(backend=backend, embedder=chosen_embedder)
        self._parser = DocumentParser(
            chunker=SemanticChunker(embedder=chosen_embedder),
            allowed_roots=allowed_roots,
            default_roots=lambda: [
                Path(get_upload_dir()).resolve(),
                Path(get_app_data_dir()).resolve(),
                Path.cwd().resolve(),
            ],
        )
        self._repository = DatasetRepository(
            chosen_path, prepare_loaded_state=self._prepare_loaded_state
        )
        self._feedback = DatasetFeedbackStore(chosen_path.with_name("dataset_feedback.json"))
        self._query_gaps = DatasetQueryGapStore(chosen_path.with_name("dataset_query_gaps.json"))
        self._api_keys = DatasetApiKeyStore(chosen_path.with_name("dataset_api_keys.json"))
        self._documents = DocumentLifecycle(
            repository=self._repository,
            parser=self._parser,
            vector=self._vector,
            renumber=lambda state: self._renumber_chunks(state),
        )
        self._rebuild = RebuildCoordinator(
            repository=self._repository,
            vector=self._vector,
            renumber=lambda state: self._renumber_chunks(state),
            max_concurrent_jobs=_resolve_max_concurrent_rebuild_jobs(max_concurrent_rebuild_jobs),
            workers_enabled=bool(rebuild_workers_enabled),
        )
        self._status = DatasetStatus(repository=self._repository, rebuild=self._rebuild)
        self._retrieval = DatasetRetrieval(
            repository=self._repository,
            vector=self._vector,
            retriever_factory=lambda **kwargs: HybridRetriever(**kwargs),
        )
        with self._repository.lock:
            pass
        if self._rebuild.workers_enabled:
            self._schedule_rebuild_jobs()

    def _prepare_loaded_state(self, state: _DatasetState) -> None:
        from app.application.dataset_rag.vector_index import backfill_missing_embeddings

        _recover_rebuild_jobs_locked(state)
        dirty = backfill_missing_embeddings(self._vector.embedder, state)
        self._renumber_chunks(state)
        self._vector._sync_vector_index_locked(state)
        self._vector._refresh_index_metadata(state)
        if dirty:
            state.index["_persist_after_load"] = True

    def ingest_document(
        self,
        *,
        dataset_id: str,
        source: str = "",
        text: str = "",
        file_path: str = "",
        document_id: str = "",
        chunk_strategy: str = "semantic",
        chunk_size: int = 500,
        chunk_overlap: int = 50,
        metadata: dict[str, Any] | None = None,
        tenant_id: str = "",
        version: int | str | None = None,
        version_label: str = "",
        idempotency_key: str = "",
        expected_source_version: int | None = None,
        allow_duplicate: bool = False,
        access_context: DatasetAccessContext | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._documents.ingest_document(
            dataset_id=dataset_id,
            source=source,
            text=text,
            file_path=file_path,
            document_id=document_id,
            chunk_strategy=chunk_strategy,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            metadata=metadata,
            tenant_id=tenant_id,
            version=version,
            version_label=version_label,
            idempotency_key=idempotency_key,
            expected_source_version=expected_source_version,
            allow_duplicate=allow_duplicate,
            access_context=access_context,
        )

    def delete_document(
        self,
        dataset_id: str,
        document_id: str,
        *,
        expected_version: int | None = None,
        expected_metadata: dict[str, Any] | None = None,
        access_context: DatasetAccessContext | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._documents.delete_document(
            dataset_id,
            document_id,
            expected_version=expected_version,
            expected_metadata=expected_metadata,
            access_context=access_context,
        )

    def update_document_acl(
        self,
        dataset_id: str,
        document_id: str,
        *,
        acl: dict[str, Any] | None = None,
        access_context: DatasetAccessContext | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._documents.update_document_acl(
            dataset_id,
            document_id,
            acl=acl,
            access_context=access_context,
        )

    def refresh_document(
        self,
        dataset_id: str,
        document_id: str,
        *,
        tenant_id: str = "",
        access_context: DatasetAccessContext | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Re-fetch one document from its recorded external source and version it.

        Knowledge bases that sync Confluence / Notion / web pages keep the source
        coordinates so a re-sync produces a new version instead of a duplicate
        document. Unchanged content returns ``changed=false`` without a new version.
        """
        from app.application.dataset_rag.document_acl import document_visible_to

        dataset_key = _clean_key(dataset_id, default="default")
        doc_key = str(document_id or "").strip()
        context = _coerce_access_context(access_context)
        denied = _ensure_dataset_permission(
            context, DATASET_WRITE_PERMISSION, dataset_id=dataset_key
        )
        if denied is not None:
            return denied
        tenant_key, denied = _resolve_tenant_for_access(
            context,
            tenant_id,
            required_permission=DATASET_WRITE_PERMISSION,
            default_without_context="",
            dataset_id=dataset_key,
        )
        if denied is not None:
            return denied
        with self._repository.lock:
            state = self._repository.datasets.get(dataset_key)
            document = state.documents.get(doc_key) if state is not None else None
            snapshot = document.to_dict() if document is not None else None
        if snapshot is None or not document_visible_to(snapshot.get("metadata"), context):
            return {
                "success": False,
                "dataset_id": dataset_key,
                "document_id": doc_key,
                "error_code": "dataset_document_not_found",
                "message": "document not found",
            }
        denied = _ensure_tenant_allowed(
            context,
            str(snapshot.get("tenant_id") or ""),
            dataset_id=dataset_key,
            operation="refresh_document",
        )
        if denied is not None:
            denied["document_id"] = doc_key
            return denied
        metadata = dict(snapshot.get("metadata") or {})
        coordinates = source_coordinates(metadata)
        if coordinates is None:
            return {
                "success": False,
                "dataset_id": dataset_key,
                "document_id": doc_key,
                "error_code": "dataset_refresh_unsupported",
                "message": "该文档没有可刷新的外部来源（支持 url / confluence / feishu / notion）",
            }
        kind, ref = coordinates
        try:
            text, source_label, extra_metadata = fetch_source_text(kind, ref)
        except ValueError as exc:
            return {
                "success": False,
                "dataset_id": dataset_key,
                "document_id": doc_key,
                "error_code": "dataset_refresh_failed",
                "message": str(exc),
            }
        if not str(text or "").strip():
            return {
                "success": False,
                "dataset_id": dataset_key,
                "document_id": doc_key,
                "error_code": "dataset_refresh_failed",
                "message": "来源返回空正文",
            }
        fresh_hash = hashlib.sha256(str(text).strip().encode("utf-8")).hexdigest()
        synced_at = _utc_now_iso()
        if fresh_hash == str(metadata.get("document_content_hash") or ""):
            self._mark_source_synced(dataset_key, doc_key, synced_at)
            return {
                "success": True,
                "dataset_id": dataset_key,
                "document_id": doc_key,
                "changed": False,
                "version": int(snapshot.get("version") or 1),
                "document": snapshot,
                "last_source_sync_at": synced_at,
            }
        chunk_strategy = str(metadata.pop("chunk_strategy", "") or "semantic")
        chunk_size = int(metadata.pop("chunk_size", 500) or 500)
        chunk_overlap = int(metadata.pop("chunk_overlap", 50) or 50)
        for key in (
            "document_content_hash",
            "document_version",
            "version_label",
            "ingest_idempotency_key",
            "ingest_fingerprint",
        ):
            metadata.pop(key, None)
        metadata.update(extra_metadata)
        metadata["last_source_sync_at"] = synced_at
        result = self._documents.ingest_document(
            dataset_id=dataset_key,
            # 版本按 source 归属，刷新必须沿用原 source，否则会被当成新文档从 v1 开始。
            source=str(snapshot.get("source") or source_label or ""),
            text=str(text),
            document_id=doc_key,
            chunk_strategy=chunk_strategy,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            metadata=metadata,
            tenant_id=tenant_key,
            access_context=access_context,
        )
        response = dict(result)
        response.update(
            {
                "changed": bool(result.get("success")),
                "previous_version": int(snapshot.get("version") or 1),
                "source_kind": kind,
            }
        )
        return response

    def _mark_source_synced(self, dataset_id: str, document_id: str, synced_at: str) -> None:
        """内容未变时也记录同步时间，避免批量同步反复抓同一来源。"""
        with self._repository.lock:
            state = self._repository.datasets.get(dataset_id)
            document = state.documents.get(document_id) if state is not None else None
            if document is None:
                return
            document.metadata = {**(document.metadata or {}), "last_source_sync_at": synced_at}
            self._repository._persist_locked()

    def refresh_documents(
        self,
        dataset_id: str,
        *,
        tenant_id: str = "",
        access_context: DatasetAccessContext | dict[str, Any] | None = None,
        limit: int = 50,
        max_age_hours: float | None = None,
    ) -> dict[str, Any]:
        """Re-sync every document in the dataset that records external coordinates.

        Mature knowledge bases offer a scheduled / bulk source sync; per-document
        refresh alone cannot catch a whole Confluence space. Documents without a
        recorded source are counted as skipped instead of failing the batch.
        """
        from app.application.dataset_rag.document_acl import document_visible_to

        dataset_key = _clean_key(dataset_id, default="default")
        context = _coerce_access_context(access_context)
        denied = _ensure_dataset_permission(
            context, DATASET_WRITE_PERMISSION, dataset_id=dataset_key
        )
        if denied is not None:
            return denied
        tenant_key, denied = _resolve_tenant_for_access(
            context,
            tenant_id,
            required_permission=DATASET_WRITE_PERMISSION,
            default_without_context="",
            dataset_id=dataset_key,
        )
        if denied is not None:
            return denied
        with self._repository.lock:
            state = self._repository.datasets.get(dataset_key)
            snapshots = (
                [document.to_dict() for document in state.documents.values()]
                if state is not None
                else []
            )
        candidates: list[dict[str, Any]] = []
        skipped = 0
        fresh = 0
        cutoff = (
            datetime.now(UTC) - timedelta(hours=float(max_age_hours))
            if max_age_hours is not None and float(max_age_hours) > 0
            else None
        )
        for snapshot in sorted(snapshots, key=lambda item: str(item.get("document_id") or "")):
            if tenant_key and str(snapshot.get("tenant_id") or "") != tenant_key:
                continue
            if not document_visible_to(snapshot.get("metadata"), context):
                continue
            if source_coordinates(snapshot.get("metadata")) is None:
                skipped += 1
                continue
            if cutoff is not None:
                synced_at = _source_synced_at(snapshot.get("metadata"))
                if synced_at is not None and synced_at >= cutoff:
                    fresh += 1
                    continue
            candidates.append(snapshot)
        bounded = max(1, min(int(limit), 200))
        results: list[dict[str, Any]] = []
        changed = unchanged = failed = 0
        for snapshot in candidates[:bounded]:
            doc_id = str(snapshot.get("document_id") or "")
            outcome = self.refresh_document(
                dataset_key,
                doc_id,
                tenant_id=tenant_key,
                access_context=access_context,
            )
            if not outcome.get("success"):
                failed += 1
                results.append(
                    {
                        "document_id": doc_id,
                        "source": str(snapshot.get("source") or ""),
                        "status": "failed",
                        "error_code": str(outcome.get("error_code") or "dataset_refresh_failed"),
                        "message": str(outcome.get("message") or ""),
                    }
                )
                continue
            is_changed = bool(outcome.get("changed"))
            changed += int(is_changed)
            unchanged += int(not is_changed)
            document = outcome.get("document") if isinstance(outcome.get("document"), dict) else {}
            results.append(
                {
                    "document_id": doc_id,
                    "source": str(snapshot.get("source") or ""),
                    "status": "changed" if is_changed else "unchanged",
                    "version": int(document.get("version") or outcome.get("version") or 0),
                }
            )
        return {
            "success": True,
            "dataset_id": dataset_key,
            "tenant_id": tenant_key,
            "total": len(candidates),
            "processed": len(results),
            "changed": changed,
            "unchanged": unchanged,
            "failed": failed,
            "skipped": skipped,
            "fresh": fresh,
            "max_age_hours": float(max_age_hours) if max_age_hours is not None else 0.0,
            "truncated": len(candidates) > bounded,
            "documents": results,
        }

    def refresh_all_due_sources(
        self,
        *,
        max_age_hours: float = 24.0,
        limit_per_dataset: int = 50,
    ) -> dict[str, Any]:
        """后台定时任务入口：刷新所有知识库中超过新鲜度阈值的来源。"""
        with self._repository.lock:
            dataset_ids = sorted(
                key
                for key, state in self._repository.datasets.items()
                if state.documents
                and any(source_coordinates(doc.metadata) for doc in state.documents.values())
            )
        totals = {
            "datasets": 0,
            "processed": 0,
            "changed": 0,
            "unchanged": 0,
            "failed": 0,
            "fresh": 0,
        }
        results: list[dict[str, Any]] = []
        for dataset_id in dataset_ids:
            outcome = self.refresh_documents(
                dataset_id,
                max_age_hours=max_age_hours,
                limit=limit_per_dataset,
                access_context=None,
            )
            if not outcome.get("success"):
                results.append({"dataset_id": dataset_id, "error": outcome.get("message", "")})
                continue
            totals["datasets"] += 1
            for key in ("processed", "changed", "unchanged", "failed", "fresh"):
                totals[key] += int(outcome.get(key) or 0)
            results.append(
                {
                    "dataset_id": dataset_id,
                    "processed": int(outcome.get("processed") or 0),
                    "changed": int(outcome.get("changed") or 0),
                    "failed": int(outcome.get("failed") or 0),
                    "fresh": int(outcome.get("fresh") or 0),
                }
            )
        return {**totals, "max_age_hours": float(max_age_hours), "results": results}

    def clear_dataset(
        self,
        dataset_id: str,
        *,
        tenant_id: str = "",
        access_context: DatasetAccessContext | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Remove every document in one dataset for the caller's tenant."""
        access = access_context if isinstance(access_context, DatasetAccessContext) else None
        list_context = access_context
        if access is not None and DATASET_READ_PERMISSION not in access.permissions:
            # 列举待删文档需要读权限，真正的删除仍由 delete_document 校验写权限。
            list_context = DatasetAccessContext(
                actor_id=access.actor_id,
                tenant_id=access.tenant_id,
                permissions=frozenset(set(access.permissions) | {DATASET_READ_PERMISSION}),
                is_admin=access.is_admin,
            )
        status = self.status(
            dataset_id,
            tenant_id=tenant_id,
            access_context=list_context,
            include_documents=True,
        )
        if not status.get("success"):
            return status
        deleted_documents = 0
        deleted_chunks = 0
        for document in status.get("documents") or []:
            document_id = str((document or {}).get("document_id") or "").strip()
            if not document_id:
                continue
            result = self.delete_document(dataset_id, document_id, access_context=access_context)
            if not result.get("success"):
                return result
            deleted_documents += 1
            deleted_chunks += int(result.get("deleted_chunks") or 0)
        return {
            "success": True,
            "dataset_id": dataset_id,
            "deleted_documents": deleted_documents,
            "deleted_chunks": deleted_chunks,
        }

    def diff_versions(
        self,
        *,
        dataset_id: str,
        source: str,
        from_version: str | int,
        to_version: str | int = "latest",
        tenant_id: str = "",
        access_context: DatasetAccessContext | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._documents.diff_versions(
            dataset_id=dataset_id,
            source=source,
            from_version=from_version,
            to_version=to_version,
            tenant_id=tenant_id,
            access_context=access_context,
        )

    def rollback_document_version(
        self,
        *,
        dataset_id: str,
        source: str,
        target_version: str | int,
        tenant_id: str = "",
        metadata: dict[str, Any] | None = None,
        access_context: DatasetAccessContext | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._documents.rollback_document_version(
            dataset_id=dataset_id,
            source=source,
            target_version=target_version,
            tenant_id=tenant_id,
            metadata=metadata,
            access_context=access_context,
        )

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
        return self._rebuild.start_rebuild_index(
            dataset_id=dataset_id,
            tenant_id=tenant_id,
            metadata_filter=metadata_filter,
            background=background,
            max_attempts=max_attempts,
            access_context=access_context,
        )

    def cancel_rebuild_job(
        self,
        dataset_id: str,
        job_id: str,
        *,
        access_context: DatasetAccessContext | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._rebuild.cancel_rebuild_job(dataset_id, job_id, access_context=access_context)

    def drain_rebuild_queue(self, *, max_jobs: int | None = None) -> dict[str, Any]:
        return self._rebuild.drain_rebuild_queue(max_jobs=max_jobs)

    def get_rebuild_job(
        self,
        dataset_id: str,
        job_id: str,
        *,
        access_context: DatasetAccessContext | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._rebuild.get_rebuild_job(dataset_id, job_id, access_context=access_context)

    def _schedule_rebuild_jobs(self) -> None:
        self._rebuild._schedule_rebuild_jobs()

    def _claim_next_rebuild_jobs_locked(self, *, limit: int | None = None) -> list[tuple[str, str]]:
        return self._rebuild._claim_next_rebuild_jobs_locked(limit=limit)

    def _start_rebuild_threads(self, starts: list[tuple[str, str]]) -> None:
        self._rebuild._start_rebuild_threads(starts)

    def _run_rebuild_job(
        self, dataset_id: str, job_id: str, *, claimed: bool = False, schedule_next: bool = True
    ) -> None:
        self._rebuild._run_rebuild_job(
            dataset_id, job_id, claimed=claimed, schedule_next=schedule_next
        )

    def _rebuild_job_to_dict_locked(
        self, state: _DatasetState, job: DatasetRebuildJob
    ) -> dict[str, Any]:
        return self._rebuild._rebuild_job_to_dict_locked(state, job)

    def _rebuild_queue_summary_locked(
        self, state: _DatasetState, *, tenant_id_filter: str = ""
    ) -> dict[str, Any]:
        return self._rebuild._rebuild_queue_summary_locked(state, tenant_id_filter=tenant_id_filter)

    def status(
        self,
        dataset_id: str = "",
        *,
        tenant_id: str = "",
        access_context: DatasetAccessContext | dict[str, Any] | None = None,
        include_documents: bool = True,
    ) -> dict[str, Any]:
        return self._status.status(
            dataset_id,
            tenant_id=tenant_id,
            access_context=access_context,
            include_documents=include_documents,
        )

    def _status_for_state(
        self,
        dataset_id: str,
        state: _DatasetState | None,
        *,
        tenant_id_filter: str = "",
        include_documents: bool = True,
        access_context: DatasetAccessContext | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._status._status_for_state(
            dataset_id,
            state,
            tenant_id_filter=tenant_id_filter,
            include_documents=include_documents,
            access_context=access_context,
        )

    def query(
        self,
        *,
        dataset_id: str,
        query: str,
        top_k: int = 5,
        tenant_id: str = "",
        version: str | int = "",
        metadata_filter: dict[str, Any] | None = None,
        rerank: bool = False,
        access_context: DatasetAccessContext | dict[str, Any] | None = None,
        include_sheet_context: bool = False,
        context_window: int = 0,
        history: list[dict[str, Any]] | None = None,
        min_relevance: float | None = None,
        mmr_lambda: float | None = None,
        retrieval_mode: str = "hybrid",
        vector_weight: float = 1.0,
        keyword_weight: float = 1.0,
        expand_section: bool = False,
    ) -> dict[str, Any]:
        original_query = query
        rewritten = ""
        if history:
            from app.infrastructure.llm.query_rewrite import rewrite_query

            rewritten = rewrite_query(query, history)
            if rewritten:
                query = rewritten
        result = self._retrieval.query(
            dataset_id=dataset_id,
            query=query,
            top_k=top_k,
            tenant_id=tenant_id,
            version=version,
            metadata_filter=metadata_filter,
            rerank=rerank,
            access_context=access_context,
            include_sheet_context=include_sheet_context,
            context_window=context_window,
            min_relevance=min_relevance,
            mmr_lambda=mmr_lambda,
            retrieval_mode=retrieval_mode,
            vector_weight=vector_weight,
            keyword_weight=keyword_weight,
            expand_section=expand_section,
        )
        if rewritten:
            result["original_query"] = original_query
            result["query_rewritten"] = True
            result["query"] = query
        if result.get("success") and not result.get("chunks"):
            self._record_query_gap(
                dataset_id,
                original_query if rewritten else query,
                str(result.get("tenant_id") or tenant_id),
            )
        return result

    def document_chunks(
        self,
        dataset_id: str,
        document_id: str,
        *,
        tenant_id: str = "",
        offset: int = 0,
        limit: int = 50,
        access_context: DatasetAccessContext | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._retrieval.document_chunks(
            dataset_id,
            document_id,
            tenant_id=tenant_id,
            offset=offset,
            limit=limit,
            access_context=access_context,
        )

    def knowledge_graph(
        self,
        dataset_id: str,
        *,
        tenant_id: str = "",
        limit: int = 120,
        access_context: DatasetAccessContext | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._retrieval.knowledge_graph(
            dataset_id, tenant_id=tenant_id, limit=limit, access_context=access_context
        )

    def record_feedback(
        self,
        *,
        dataset_id: str,
        rating: str,
        query: str = "",
        answer: str = "",
        comment: str = "",
        citations: list[dict[str, Any]] | None = None,
        tenant_id: str = "",
        access_context: DatasetAccessContext | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Record whether an answer was useful (thumb up/down) for quality review."""
        dataset_key = _clean_key(dataset_id, default="default")
        context = _coerce_access_context(access_context)
        tenant_key, denied = _resolve_tenant_for_access(
            context,
            tenant_id,
            required_permission=DATASET_READ_PERMISSION,
            default_without_context="",
            dataset_id=dataset_key,
        )
        if denied is not None:
            return denied
        try:
            record = self._feedback.record(
                dataset_id=dataset_key,
                tenant_id=tenant_key,
                rating=str(rating or "").strip().lower(),
                query=query,
                answer=answer,
                comment=comment,
                citations=citations,
                actor_id=str(getattr(context, "actor_id", "") or ""),
            )
        except ValueError as exc:
            return {"success": False, "dataset_id": dataset_key, "message": str(exc)}
        return {"success": True, "dataset_id": dataset_key, "feedback": record}

    def feedback_summary(
        self,
        dataset_id: str,
        *,
        tenant_id: str = "",
        limit: int = 20,
        access_context: DatasetAccessContext | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        dataset_key = _clean_key(dataset_id, default="default")
        context = _coerce_access_context(access_context)
        tenant_key, denied = _resolve_tenant_for_access(
            context,
            tenant_id,
            required_permission=DATASET_READ_PERMISSION,
            default_without_context="",
            dataset_id=dataset_key,
        )
        if denied is not None:
            return denied
        summary = self._feedback.summary(dataset_id=dataset_key, tenant_id=tenant_key, limit=limit)
        return {"success": True, "dataset_id": dataset_key, **summary}

    def query_gaps(
        self,
        dataset_id: str,
        *,
        tenant_id: str = "",
        limit: int = 20,
        access_context: DatasetAccessContext | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Questions that retrieved no usable evidence, most frequent first."""
        dataset_key = _clean_key(dataset_id, default="default")
        context = _coerce_access_context(access_context)
        tenant_key, denied = _resolve_tenant_for_access(
            context,
            tenant_id,
            required_permission=DATASET_READ_PERMISSION,
            default_without_context="",
            dataset_id=dataset_key,
        )
        if denied is not None:
            return denied
        rows = self._query_gaps.list(dataset_id=dataset_key, tenant_id=tenant_key, limit=limit)
        return {
            "success": True,
            "dataset_id": dataset_key,
            "gaps": rows,
            "total": len(rows),
        }

    def clear_query_gaps(
        self,
        dataset_id: str,
        *,
        tenant_id: str = "",
        access_context: DatasetAccessContext | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        dataset_key = _clean_key(dataset_id, default="default")
        context = _coerce_access_context(access_context)
        tenant_key, denied = _resolve_tenant_for_access(
            context,
            tenant_id,
            required_permission=DATASET_WRITE_PERMISSION,
            default_without_context="",
            dataset_id=dataset_key,
        )
        if denied is not None:
            return denied
        removed = self._query_gaps.clear(dataset_id=dataset_key, tenant_id=tenant_key)
        return {"success": True, "dataset_id": dataset_key, "removed": removed}

    def _record_query_gap(self, dataset_id: str, query: str, tenant_id: str) -> None:
        try:
            self._query_gaps.record(
                dataset_id=_clean_key(dataset_id, default="default"),
                tenant_id=_clean_key(tenant_id, default="") if tenant_id else "",
                query=query,
            )
        except RECOVERABLE_ERRORS:
            pass

    def synonyms(
        self,
        dataset_id: str,
        *,
        access_context: DatasetAccessContext | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._retrieval.synonyms(dataset_id, access_context=access_context)

    def set_synonyms(
        self,
        dataset_id: str,
        synonyms: Any,
        *,
        access_context: DatasetAccessContext | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._retrieval.set_synonyms(dataset_id, synonyms, access_context=access_context)

    def qa_pairs(
        self,
        dataset_id: str,
        *,
        tenant_id: str = "",
        access_context: DatasetAccessContext | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._retrieval.qa_pairs(
            dataset_id, tenant_id=tenant_id, access_context=access_context
        )

    def set_qa_pairs(
        self,
        dataset_id: str,
        payload: Any,
        *,
        tenant_id: str = "",
        replace: bool = True,
        access_context: DatasetAccessContext | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._retrieval.set_qa_pairs(
            dataset_id,
            payload,
            tenant_id=tenant_id,
            replace=replace,
            access_context=access_context,
        )

    def delete_qa_pairs(
        self,
        dataset_id: str,
        *,
        tenant_id: str = "",
        access_context: DatasetAccessContext | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._retrieval.delete_qa_pairs(
            dataset_id, tenant_id=tenant_id, access_context=access_context
        )

    def export_dataset(
        self,
        dataset_id: str,
        *,
        tenant_id: str = "",
        access_context: DatasetAccessContext | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Export a portable dataset snapshot (documents, chunks, synonyms)."""
        from app.application.dataset_rag.document_acl import document_visible_to

        dataset_key = _clean_key(dataset_id, default="default")
        context = _coerce_access_context(access_context)
        tenant_key, denied = _resolve_tenant_for_access(
            context,
            tenant_id,
            required_permission=DATASET_READ_PERMISSION,
            default_without_context="",
            dataset_id=dataset_key,
        )
        if denied is not None:
            return denied
        with self._repository.lock:
            state = self._repository.datasets.get(dataset_key)
            if state is None:
                return {
                    "success": False,
                    "dataset_id": dataset_key,
                    "message": "dataset not found",
                    "error_code": "dataset_not_found",
                }
            documents = [
                doc
                for doc in state.documents.values()
                if (not tenant_key or doc.tenant_id == tenant_key)
                and document_visible_to(doc.metadata, context)
            ]
            visible_ids = {doc.document_id for doc in documents}
            chunks = []
            for chunk in state.chunks:
                metadata = dict(chunk.metadata or {})
                document_id = str(metadata.get("document_id") or "")
                if document_id:
                    if document_id not in visible_ids:
                        continue
                elif tenant_key and str(metadata.get("tenant_id") or "") != tenant_key:
                    continue
                chunks.append(
                    {
                        "text": chunk.text,
                        "score": chunk.score,
                        "source": chunk.source,
                        "chunk_index": chunk.chunk_index,
                        "char_start": chunk.char_start,
                        "char_end": chunk.char_end,
                        "metadata": {
                            key: value for key, value in metadata.items() if not key.startswith("_")
                        },
                        "source_url": chunk.source_url,
                        "page": chunk.page,
                    }
                )
            synonyms = normalize_synonyms((state.index or {}).get("synonyms"))
            qa_pairs = scoped_qa_pairs(state.index, tenant_key)
        return {
            "success": True,
            "version": 1,
            "dataset_id": dataset_key,
            "exported_at": _utc_now_iso(),
            "tenant_id": tenant_key,
            "documents": [doc.to_dict() for doc in documents],
            "chunks": chunks,
            "synonyms": synonyms,
            "qa_pairs": qa_pairs,
            "document_count": len(documents),
            "chunk_count": len(chunks),
            "qa_pair_count": len(qa_pairs),
        }

    def import_dataset(
        self,
        dataset_id: str,
        payload: Any,
        *,
        overwrite: bool = False,
        access_context: DatasetAccessContext | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Restore an exported snapshot into a dataset, forcing actor tenant."""
        dataset_key = _clean_key(dataset_id, default="default")
        context = _coerce_access_context(access_context)
        denied = _ensure_dataset_permission(
            context, DATASET_WRITE_PERMISSION, dataset_id=dataset_key
        )
        if denied is not None:
            return denied
        data = payload if isinstance(payload, dict) else {}
        documents_payload = data.get("documents")
        chunks_payload = data.get("chunks")
        if not isinstance(documents_payload, list) or not isinstance(chunks_payload, list):
            return {
                "success": False,
                "dataset_id": dataset_key,
                "message": "payload must contain documents and chunks lists",
            }
        if len(documents_payload) > 5000 or len(chunks_payload) > 50000:
            return {
                "success": False,
                "dataset_id": dataset_key,
                "message": "export is too large (max 5000 documents / 50000 chunks)",
            }
        actor_tenant = _clean_key(str(getattr(context, "tenant_id", "") or ""), default="")
        if not actor_tenant and context is not None and not context.is_admin:
            return {
                "success": False,
                "dataset_id": dataset_key,
                "message": "actor tenant context is required",
                "error_code": "dataset_permission_denied",
            }
        try:
            synonyms = normalize_synonyms(data.get("synonyms"))
        except ValueError as exc:
            return {"success": False, "dataset_id": dataset_key, "message": str(exc)}
        try:
            qa_pairs = normalize_qa_pairs(data.get("qa_pairs"))
        except ValueError as exc:
            return {"success": False, "dataset_id": dataset_key, "message": str(exc)}
        documents: dict[str, DatasetDocument] = {}
        for row in documents_payload:
            if not isinstance(row, dict):
                continue
            document = _document_from_dict(row)
            if not document.document_id:
                continue
            document.tenant_id = actor_tenant
            document.metadata = {
                key: value
                for key, value in dict(document.metadata or {}).items()
                if not key.startswith("_")
            }
            if actor_tenant:
                document.metadata["tenant_id"] = actor_tenant
            documents[document.document_id] = document
        chunks = []
        for row in chunks_payload:
            if not isinstance(row, dict):
                continue
            document_id = str((row.get("metadata") or {}).get("document_id") or "")
            if document_id and document_id not in documents:
                continue
            chunk = _dict_to_retrieved_chunk(row)
            chunk.metadata = {
                key: value
                for key, value in dict(chunk.metadata or {}).items()
                if not key.startswith("_")
            }
            if actor_tenant:
                chunk.metadata["tenant_id"] = actor_tenant
            chunks.append(chunk)
        with self._repository.lock:
            existing = self._repository.datasets.get(dataset_key)
            if existing is not None and existing.documents and not overwrite:
                return {
                    "success": False,
                    "dataset_id": dataset_key,
                    "message": "dataset already has documents; pass overwrite=true",
                    "error_code": "dataset_not_empty",
                }
            index: dict[str, Any] = {}
            if synonyms:
                index["synonyms"] = synonyms
            if qa_pairs:
                index["qa_pairs"] = [{**pair, "tenant_id": actor_tenant} for pair in qa_pairs]
            state = _DatasetState(
                dataset_key,
                documents=documents,
                chunks=chunks,
                index=index,
            )
            self._prepare_loaded_state(state)
            state.index.pop("_persist_after_load", None)
            self._repository.datasets[dataset_key] = state
            self._repository._persist_locked()
        return {
            "success": True,
            "dataset_id": dataset_key,
            "document_count": len(documents),
            "chunk_count": len(chunks),
            "synonym_count": len(synonyms),
            "qa_pair_count": len(qa_pairs),
        }

    def create_api_key(
        self,
        dataset_id: str,
        *,
        label: str = "",
        access_context: DatasetAccessContext | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Issue a read-only external key; the raw key is returned exactly once."""
        dataset_key = _clean_key(dataset_id, default="default")
        context = _coerce_access_context(access_context)
        denied = _ensure_dataset_permission(
            context, DATASET_ADMIN_PERMISSION, dataset_id=dataset_key
        )
        if denied is not None:
            return denied
        tenant = _clean_key(str(getattr(context, "tenant_id", "") or ""), default="")
        if not tenant:
            return {
                "success": False,
                "dataset_id": dataset_key,
                "message": "actor tenant context is required for API keys",
                "error_code": "dataset_permission_denied",
            }
        row = self._api_keys.create(dataset_id=dataset_key, tenant_id=tenant, label=label)
        return {"success": True, "dataset_id": dataset_key, **row}

    def list_api_keys(
        self,
        dataset_id: str,
        *,
        access_context: DatasetAccessContext | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        dataset_key = _clean_key(dataset_id, default="default")
        context = _coerce_access_context(access_context)
        denied = _ensure_dataset_permission(
            context, DATASET_ADMIN_PERMISSION, dataset_id=dataset_key
        )
        if denied is not None:
            return denied
        rows = self._api_keys.list(dataset_id=dataset_key)
        return {
            "success": True,
            "dataset_id": dataset_key,
            "keys": rows,
            "total": len(rows),
        }

    def revoke_api_key(
        self,
        dataset_id: str,
        token_id: str,
        *,
        access_context: DatasetAccessContext | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        dataset_key = _clean_key(dataset_id, default="default")
        context = _coerce_access_context(access_context)
        denied = _ensure_dataset_permission(
            context, DATASET_ADMIN_PERMISSION, dataset_id=dataset_key
        )
        if denied is not None:
            return denied
        removed = self._api_keys.revoke(dataset_id=dataset_key, token_id=str(token_id or ""))
        return {"success": True, "dataset_id": dataset_key, "revoked": removed}

    def public_query(
        self,
        *,
        api_key: str,
        query: str,
        top_k: int = 5,
        metadata_filter: dict[str, Any] | None = None,
        retrieval_mode: str = "hybrid",
        mmr_lambda: float = 0.0,
        expand_section: bool = False,
    ) -> dict[str, Any]:
        """External read-only query authenticated by a dataset API key."""
        resolved = self._api_keys.resolve(api_key)
        if resolved is None:
            return {
                "success": False,
                "error_code": "knowledge_api_key_invalid",
                "message": "invalid or revoked API key",
                "chunks": [],
            }
        context = DatasetAccessContext(
            actor_id=f"api:{resolved['token_id']}",
            tenant_id=resolved["tenant_id"],
            permissions=frozenset({DATASET_READ_PERMISSION}),
            is_admin=False,
        )
        result = self.query(
            dataset_id=resolved["dataset_id"],
            query=query,
            top_k=max(1, min(int(top_k or 5), 20)),
            tenant_id=resolved["tenant_id"],
            metadata_filter=metadata_filter or {},
            rerank=False,
            access_context=context,
            retrieval_mode=retrieval_mode,
            mmr_lambda=mmr_lambda,
            expand_section=expand_section,
        )
        for chunk in result.get("chunks") or []:
            metadata = chunk.get("metadata")
            if isinstance(metadata, dict):
                metadata.pop("acl", None)
                metadata.pop("tenant_id", None)
        result.pop("citations", None)
        result["answer"] = ""
        result["dataset_id"] = resolved["dataset_id"]
        return result

    def _resolve_file_path(self, file_path: str) -> Path:
        return self._parser._resolve_file_path(file_path)

    def _allowed_file_roots(self) -> list[Path]:
        return self._parser._allowed_file_roots()

    def _extract_file_text(self, path: Path) -> tuple[str, str, dict[str, Any]]:
        return self._parser._extract_file_text(path)

    def _extract_pdf_text(self, path: Path) -> tuple[str, str, dict[str, Any]]:
        return self._parser._extract_pdf_text(path)

    def _extract_docx_text(self, path: Path) -> tuple[str, str, dict[str, Any]]:
        return self._parser._extract_docx_text(path)

    def _extract_pptx_text(self, path: Path) -> tuple[str, str, dict[str, Any]]:
        return self._parser._extract_pptx_text(path)

    def _extract_excel_text(self, path: Path) -> tuple[str, str, dict[str, Any]]:
        return self._parser._extract_excel_text(path)

    def _extract_xlsx_text(self, path: Path) -> tuple[str, str, dict[str, Any]]:
        return self._parser._extract_xlsx_text(path)

    def _extract_xls_text(self, path: Path) -> tuple[str, str, dict[str, Any]]:
        return self._parser._extract_xls_text(path)

    def _split_text(self, text: str, *, strategy: str, chunk_size: int, chunk_overlap: int):
        return self._parser._split_text(
            text, strategy=strategy, chunk_size=chunk_size, chunk_overlap=chunk_overlap
        )

    def _query_vector_index_candidates(
        self,
        *,
        dataset_id: str,
        query: str,
        top_k: int,
        tenant_id: str,
        version: str | int,
        metadata_filter: dict[str, Any],
    ) -> list[RetrievedChunk] | None:
        return self._vector._query_vector_index_candidates(
            dataset_id=dataset_id,
            query=query,
            top_k=top_k,
            tenant_id=tenant_id,
            version=version,
            metadata_filter=metadata_filter,
        )

    def _sync_vector_index_locked(self, state: _DatasetState) -> None:
        self._vector._sync_vector_index_locked(state)

    def _vector_index_backend_name(self) -> str:
        return self._vector._vector_index_backend_name()

    def _vector_index_status(self, dataset_id: str) -> dict[str, Any]:
        return self._vector._vector_index_status(dataset_id)

    def _refresh_index_metadata(self, state: _DatasetState) -> None:
        self._vector._refresh_index_metadata(state)

    def _load_persisted_state(self) -> None:
        self._repository._load_persisted_state()

    def _persist_locked(self) -> None:
        self._repository._persist_locked()

    def answer(
        self,
        *,
        dataset_id: str,
        query: str,
        top_k: int = 5,
        llm_call: Callable[[str, str], str] | None = None,
        tenant_id: str = "",
        version: str | int = "",
        metadata_filter: dict[str, Any] | None = None,
        rerank: bool = False,
        access_context: DatasetAccessContext | dict[str, Any] | None = None,
        history: list[dict[str, Any]] | None = None,
        min_relevance: float | None = None,
        max_context_chars: int | None = None,
        mmr_lambda: float | None = None,
        retrieval_mode: str = "hybrid",
        vector_weight: float = 1.0,
        keyword_weight: float = 1.0,
        expand_section: bool = False,
    ) -> dict[str, Any]:
        result = self.query(
            dataset_id=dataset_id,
            query=query,
            top_k=top_k,
            tenant_id=tenant_id,
            version=version,
            metadata_filter=metadata_filter,
            rerank=rerank,
            access_context=access_context,
            context_window=1,
            history=history,
            min_relevance=min_relevance,
            mmr_lambda=mmr_lambda,
            retrieval_mode=retrieval_mode,
            vector_weight=vector_weight,
            keyword_weight=keyword_weight,
            expand_section=expand_section,
        )
        synthesized = self._synthesize_answer(
            result, llm_call=llm_call, max_context_chars=max_context_chars
        )
        if synthesized.get("no_answer") and result.get("chunks"):
            self._record_query_gap(dataset_id, query, str(result.get("tenant_id") or tenant_id))
        return synthesized

    def multi_query(
        self,
        *,
        dataset_ids: list[str],
        query: str,
        top_k: int = 5,
        tenant_id: str = "",
        version: str | int = "",
        metadata_filter: dict[str, Any] | None = None,
        rerank: bool = False,
        access_context: DatasetAccessContext | dict[str, Any] | None = None,
        context_window: int = 0,
        history: list[dict[str, Any]] | None = None,
        min_relevance: float | None = None,
        mmr_lambda: float | None = None,
        retrieval_mode: str = "hybrid",
        vector_weight: float = 1.0,
        keyword_weight: float = 1.0,
        expand_section: bool = False,
    ) -> dict[str, Any]:
        """Query several datasets and rank their pooled candidates on one scale.

        Mature knowledge bases (Dify / FastGPT / RAGFlow) let one question span a
        whole knowledge-base group; per-dataset query alone cannot answer that.
        Per-dataset scores are rank-based and saturate at the same value, so fusion
        pools each dataset's candidates and re-runs hybrid retrieval over the union
        instead of comparing incomparable per-dataset scores. Each dataset keeps
        its own tenant and ACL checks - pooling never widens visibility.
        """
        keys: list[str] = []
        for raw in dataset_ids or []:
            key = str(raw or "").strip()
            if key and key not in keys:
                keys.append(key)
        if not keys:
            return {
                "success": False,
                "message": "dataset_ids is required",
                "dataset_ids": [],
                "query": query,
                "chunks": [],
                "citations": [],
                "answer": "",
            }
        original_query = query
        rewritten = ""
        if history:
            from app.infrastructure.llm.query_rewrite import rewrite_query

            rewritten = rewrite_query(query, history)
            if rewritten:
                query = rewritten
        finals = max(1, min(int(top_k), 50))
        candidate_k = max(finals * 4, 20)
        results: list[tuple[str, dict[str, Any]]] = []
        failures: list[dict[str, Any]] = []
        pooled: list[dict[str, Any]] = []
        for key in keys:
            result = self.query(
                dataset_id=key,
                query=query,
                top_k=candidate_k,
                tenant_id=tenant_id,
                version=version,
                metadata_filter=metadata_filter,
                rerank=False,
                access_context=access_context,
                context_window=context_window,
                retrieval_mode=retrieval_mode,
                vector_weight=vector_weight,
                keyword_weight=keyword_weight,
                expand_section=expand_section,
            )
            if not result.get("success"):
                failures.append(
                    {"dataset_id": key, "message": str(result.get("message") or "query failed")}
                )
                continue
            results.append((key, result))
            for row in result.get("chunks") or []:
                if not isinstance(row, dict):
                    continue
                metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
                pooled.append(
                    {
                        **row,
                        "dataset_id": key,
                        "metadata": {**metadata, "_dataset_id": key},
                    }
                )
        fused = self._pool_retrieve(
            pooled,
            query,
            finals,
            rerank=rerank,
            mmr_lambda=mmr_lambda,
            retrieval_mode=retrieval_mode,
            vector_weight=vector_weight,
            keyword_weight=keyword_weight,
        )
        grounding = evidence_grounding(query, [_dict_to_retrieved_chunk(row) for row in fused])
        threshold = resolve_min_relevance(min_relevance)
        payload: dict[str, Any] = {
            "success": bool(results),
            "dataset_ids": keys,
            "query": query,
            "chunks": fused,
            "citations": [],
            "answer": "",
            "grounding": round(grounding, 4),
            "min_relevance": round(threshold, 4),
            "answer_grounded": grounding >= threshold,
            "tenant_id": str(results[0][1].get("tenant_id") if results else ""),
            "version": str(version or ""),
            "datasets": [
                {
                    "dataset_id": key,
                    "vector_backend_used": bool(result.get("vector_backend_used")),
                    "index": result.get("index") or {},
                }
                for key, result in results
            ],
        }
        if rewritten:
            payload["original_query"] = original_query
            payload["query_rewritten"] = True
        if failures:
            payload["failed_datasets"] = failures
        return payload

    def _pool_retrieve(
        self,
        pooled: list[dict[str, Any]],
        query: str,
        top_k: int,
        *,
        rerank: bool,
        mmr_lambda: float | None = None,
        retrieval_mode: str = "hybrid",
        vector_weight: float = 1.0,
        keyword_weight: float = 1.0,
    ) -> list[dict[str, Any]]:
        """Rank pooled candidates from several datasets on a single scoring scale."""
        if not pooled:
            return []
        rows: dict[tuple[str, str, int], dict[str, Any]] = {}
        for row in pooled:
            metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
            key = (
                str(metadata.get("_dataset_id") or ""),
                str(metadata.get("document_id") or row.get("source") or ""),
                int(row.get("chunk_index") or 0),
            )
            rows.setdefault(key, row)
        chunks = [_dict_to_retrieved_chunk(row) for row in rows.values()]
        # 向量/BM25 两条通道各自默认只取 10 条；候选池要做 MMR 时必须全量排序，
        # 否则长尾里的独立文档根本进不了池子。
        retriever = HybridRetriever(
            embedder=self._vector.embedder,
            top_k=len(chunks),
            top_k_vector=len(chunks),
            top_k_bm25=len(chunks),
            mode=retrieval_mode,
            vector_weight=vector_weight,
            keyword_weight=keyword_weight,
        )
        retriever.index(chunks)
        top = retriever.retrieve(query)
        from app.application.dataset_rag.retrieval import (
            _auto_rerank_available,
            _rerank_chunks,
            _semantic_rerank_chunks,
        )
        from app.application.dataset_rag.retrieval_policy import (
            mmr_rerank,
            resolve_mmr_lambda,
        )

        auto = False if rerank else _auto_rerank_available()
        lambda_value = resolve_mmr_lambda(mmr_lambda)
        # MMR 需要完整候选池才能在长尾里挑出「不同文档」；池子本身已按
        # 每个库的候选上限收敛，不会无限膨胀。
        retrieve_k = len(top) if lambda_value > 0 else top_k
        if rerank or auto:
            top = _semantic_rerank_chunks(
                query, top, top_k=retrieve_k, auto=auto
            ) or _rerank_chunks(query, top, top_k=retrieve_k)
        else:
            top = top[:retrieve_k]
        if lambda_value > 0:
            top = mmr_rerank(
                query,
                top,
                lambda_=lambda_value,
                top_k=top_k,
                embedder=self._vector.embedder,
            )
        output: list[dict[str, Any]] = []
        for chunk in top:
            metadata = chunk.metadata or {}
            key = (
                str(metadata.get("_dataset_id") or ""),
                str(metadata.get("document_id") or chunk.source or ""),
                int(chunk.chunk_index or 0),
            )
            row = rows.get(key) or {}
            output.append(
                {
                    **_chunk_to_dict(chunk, public=True),
                    "dataset_id": str(row.get("dataset_id") or metadata.get("_dataset_id") or ""),
                }
            )
        return output

    def multi_answer(
        self,
        *,
        dataset_ids: list[str],
        query: str,
        top_k: int = 5,
        llm_call: Callable[[str, str], str] | None = None,
        tenant_id: str = "",
        version: str | int = "",
        metadata_filter: dict[str, Any] | None = None,
        rerank: bool = False,
        access_context: DatasetAccessContext | dict[str, Any] | None = None,
        history: list[dict[str, Any]] | None = None,
        min_relevance: float | None = None,
        max_context_chars: int | None = None,
        mmr_lambda: float | None = None,
        retrieval_mode: str = "hybrid",
        vector_weight: float = 1.0,
        keyword_weight: float = 1.0,
        expand_section: bool = False,
    ) -> dict[str, Any]:
        result = self.multi_query(
            dataset_ids=dataset_ids,
            query=query,
            top_k=top_k,
            tenant_id=tenant_id,
            version=version,
            metadata_filter=metadata_filter,
            rerank=rerank,
            access_context=access_context,
            context_window=1,
            history=history,
            min_relevance=min_relevance,
            mmr_lambda=mmr_lambda,
            retrieval_mode=retrieval_mode,
            vector_weight=vector_weight,
            keyword_weight=keyword_weight,
            expand_section=expand_section,
        )
        return self._synthesize_answer(
            result, llm_call=llm_call, max_context_chars=max_context_chars
        )

    def _prepare_answer_prompt(
        self,
        result: dict[str, Any],
        *,
        max_context_chars: int | None = None,
    ) -> tuple[str, CitationTracker, list[RetrievedChunk]] | None:
        """构造带引用编号与预算的证据提示词；拒答场景返回 None。"""
        if not result.get("chunks") or result.get("answer_grounded") is False:
            return None
        retrieved = [_dict_to_retrieved_chunk(row) for row in result["chunks"]]
        prompt_chunks: list[RetrievedChunk] = []
        for row, chunk in zip(result["chunks"], retrieved, strict=True):
            context = str((row.get("metadata") or {}).get("context") or "")
            if not context or context == chunk.text:
                prompt_chunks.append(chunk)
                continue
            prompt_chunks.append(
                RetrievedChunk(
                    text=context,
                    score=chunk.score,
                    source=chunk.source,
                    chunk_index=chunk.chunk_index,
                    char_start=chunk.char_start,
                    char_end=chunk.char_end,
                    metadata=chunk.metadata,
                    source_url=chunk.source_url,
                    page=chunk.page,
                )
            )
        tracker = CitationTracker(retrieved_chunks=retrieved)
        budget = _resolve_max_context_chars(max_context_chars)
        budgeted: list[RetrievedChunk] = []
        used = 0
        truncated = False
        for chunk in prompt_chunks:
            remaining = budget - used
            if remaining <= 0:
                truncated = True
                break
            text = chunk.text
            if len(text) > remaining:
                text = text[: max(0, remaining - 1)] + "…"
                truncated = True
            budgeted.append(
                RetrievedChunk(
                    text=text,
                    score=chunk.score,
                    source=chunk.source,
                    chunk_index=chunk.chunk_index,
                    char_start=chunk.char_start,
                    char_end=chunk.char_end,
                    metadata=chunk.metadata,
                    source_url=chunk.source_url,
                    page=chunk.page,
                )
            )
            used += len(text)
        result["context_chars"] = used
        result["context_truncated"] = truncated
        prompt = CitationTracker(retrieved_chunks=budgeted).format_for_prompt()
        return prompt, tracker, retrieved

    async def stream_answer(
        self,
        *,
        dataset_id: str,
        query: str,
        top_k: int = 5,
        tenant_id: str = "",
        version: str | int = "",
        metadata_filter: dict[str, Any] | None = None,
        rerank: bool = False,
        access_context: DatasetAccessContext | dict[str, Any] | None = None,
        history: list[dict[str, Any]] | None = None,
        min_relevance: float | None = None,
        max_context_chars: int | None = None,
        mmr_lambda: float | None = None,
        retrieval_mode: str = "hybrid",
        vector_weight: float = 1.0,
        keyword_weight: float = 1.0,
        expand_section: bool = False,
        llm_stream: Callable[[str, str], Any] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """SSE 事件流：meta → 若干 delta → done（拒答时直接 delta+done）。"""
        result = self.query(
            dataset_id=dataset_id,
            query=query,
            top_k=top_k,
            tenant_id=tenant_id,
            version=version,
            metadata_filter=metadata_filter,
            rerank=rerank,
            access_context=access_context,
            context_window=1,
            history=history,
            min_relevance=min_relevance,
            mmr_lambda=mmr_lambda,
            retrieval_mode=retrieval_mode,
            vector_weight=vector_weight,
            keyword_weight=keyword_weight,
            expand_section=expand_section,
        )
        yield {
            "event": "meta",
            "data": {
                "success": bool(result.get("success")),
                "dataset_id": result.get("dataset_id", dataset_id),
                "query": result.get("query", query),
                "grounding": result.get("grounding", 0.0),
                "answer_grounded": result.get("answer_grounded", False),
                "chunk_count": len(result.get("chunks") or []),
                "chunks": result.get("chunks") or [],
            },
        }
        prepared = self._prepare_answer_prompt(result, max_context_chars=max_context_chars)
        query_text = str(result.get("query") or query)
        if prepared is None:
            refusal = (
                "知识库中没有找到与该问题足够相关的内容，请补充资料或换个问法。"
                if result.get("success")
                else str(result.get("message") or "知识库检索失败")
            )
            yield {"event": "delta", "data": {"text": refusal}}
            yield {
                "event": "done",
                "data": {"answer": refusal, "citations": [], "no_answer": True},
            }
            return
        prompt, tracker, retrieved = prepared
        if llm_stream is None:
            from app.infrastructure.llm.knowledge_answer import get_kb_answer_stream

            llm_stream = get_kb_answer_stream()
        pieces: list[str] = []
        if llm_stream is not None:
            async for piece in llm_stream(query_text, prompt):
                if not piece:
                    continue
                pieces.append(str(piece))
                yield {"event": "delta", "data": {"text": str(piece)}}
        if not pieces:
            fallback = _deterministic_answer(query_text, retrieved)
            pieces.append(fallback)
            yield {"event": "delta", "data": {"text": fallback}}
        clean_answer, citations = tracker.attach_citations("".join(pieces))
        yield {
            "event": "done",
            "data": {
                "answer": clean_answer,
                "citations": [_citation_to_dict(citation) for citation in citations],
                "context_chars": result.get("context_chars", 0),
                "context_truncated": bool(result.get("context_truncated")),
            },
        }

    def _synthesize_answer(
        self,
        result: dict[str, Any],
        *,
        llm_call: Callable[[str, str], str] | None = None,
        max_context_chars: int | None = None,
    ) -> dict[str, Any]:
        if not result.get("success"):
            result.setdefault("answer", "")
            result.setdefault("citations", [])
            result.setdefault("raw", "")
            return result
        prepared = self._prepare_answer_prompt(result, max_context_chars=max_context_chars)
        if prepared is None:
            # 没有候选或证据覆盖率低于门槛时明确拒答，避免模型用无关片段编造答案。
            result["answer"] = "知识库中没有找到与该问题足够相关的内容，请补充资料或换个问法。"
            result["citations"] = []
            result["raw"] = ""
            result["no_answer"] = True
            result.setdefault("answer_grounded", False)
            return result
        prompt, tracker, retrieved = prepared
        if llm_call is None:
            from app.infrastructure.llm.knowledge_answer import get_kb_answer_llm_call

            llm_call = get_kb_answer_llm_call()
        raw_answer = (llm_call(str(result.get("query") or ""), prompt) if llm_call else "") or (
            _deterministic_answer(str(result.get("query") or ""), retrieved)
        )
        clean_answer, citations = tracker.attach_citations(raw_answer)
        result["answer"] = clean_answer
        result["raw"] = raw_answer
        result["citations"] = [_citation_to_dict(c) for c in citations]
        return result

    _renumber_chunks = staticmethod(_renumber_chunks)
    _resolve_document_version = staticmethod(_resolve_document_version)
    _resolve_document_for_version = staticmethod(_resolve_document_for_version)
    _document_text_locked = staticmethod(_document_text_locked)
    _rebuild_job_queue_position_locked = staticmethod(_rebuild_job_queue_position_locked)
    _recover_rebuild_jobs_locked = staticmethod(_recover_rebuild_jobs_locked)

    @property
    def _datasets(self) -> dict[str, _DatasetState]:
        return self._repository.datasets

    @_datasets.setter
    def _datasets(self, value: dict[str, _DatasetState]) -> None:
        self._repository.datasets = value

    @property
    def _lock(self) -> DatasetStateLock:
        return self._repository.lock

    @property
    def _storage_path(self) -> Path:
        return self._repository.storage_path

    @property
    def _allowed_roots(self) -> list[Path] | None:
        return self._parser._allowed_roots

    @_allowed_roots.setter
    def _allowed_roots(self, value: list[Path] | None) -> None:
        self._parser._allowed_roots = value

    @property
    def _chunker(self) -> SemanticChunker:
        return self._parser._chunker

    @_chunker.setter
    def _chunker(self, value: SemanticChunker) -> None:
        self._parser._chunker = value

    @property
    def _embedder(self) -> Callable[[str], list[float]] | None:
        return self._vector.embedder

    @_embedder.setter
    def _embedder(self, value: Callable[[str], list[float]] | None) -> None:
        self._vector.embedder = value

    @property
    def _vector_index_backend(self) -> DatasetVectorIndexBackend | None:
        return self._vector.backend

    @_vector_index_backend.setter
    def _vector_index_backend(self, value: DatasetVectorIndexBackend | None) -> None:
        self._vector.backend = value

    @property
    def _rebuild_owner(self) -> str:
        return self._rebuild.owner

    @_rebuild_owner.setter
    def _rebuild_owner(self, value: str) -> None:
        self._rebuild.owner = value

    @property
    def _rebuild_shutdown(self) -> bool:
        return self._rebuild.shutdown

    @_rebuild_shutdown.setter
    def _rebuild_shutdown(self, value: bool) -> None:
        self._rebuild.shutdown = value

    @property
    def _rebuild_threads(self) -> set[Thread]:
        return self._rebuild.threads

    @_rebuild_threads.setter
    def _rebuild_threads(self, value: set[Thread]) -> None:
        self._rebuild.threads = value

    @property
    def _max_concurrent_rebuild_jobs(self) -> int:
        return self._rebuild.max_concurrent_jobs

    @_max_concurrent_rebuild_jobs.setter
    def _max_concurrent_rebuild_jobs(self, value: int) -> None:
        self._rebuild.max_concurrent_jobs = value

    @property
    def _rebuild_workers_enabled(self) -> bool:
        return self._rebuild.workers_enabled

    @_rebuild_workers_enabled.setter
    def _rebuild_workers_enabled(self, value: bool) -> None:
        self._rebuild.workers_enabled = value


_dataset_rag_app_service: DatasetRagApplicationService | None = None
_dataset_rag_lock = threading.Lock()


def read_dataset_rebuild_job(
    dataset_id: str,
    job_id: str,
    *,
    access_context: DatasetAccessContext | dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Keep the first status GET independent of write-side service initialization."""
    service = _dataset_rag_app_service
    if service is not None:
        return service.get_rebuild_job(dataset_id, job_id, access_context=access_context)
    return read_rebuild_job(
        DatasetRepository(_default_storage_path(), prepare_loaded_state=lambda state: None),
        dataset_id,
        job_id,
        max_concurrent_jobs=_resolve_max_concurrent_rebuild_jobs(None),
        access_context=access_context,
    )


def get_dataset_rag_app_service() -> DatasetRagApplicationService:
    global _dataset_rag_app_service
    if _dataset_rag_app_service is None:
        with _dataset_rag_lock:
            if _dataset_rag_app_service is None:
                _dataset_rag_app_service = DatasetRagApplicationService(
                    rebuild_workers_enabled=multiprocessing.parent_process() is None
                )
    return _dataset_rag_app_service


def reset_dataset_rag_app_service_for_tests() -> None:
    from app.domain.app_pure.dataset_rag_queue import stop_host_workers

    global _dataset_rag_app_service
    if not stop_host_workers():
        raise RuntimeError("dataset host work is still running; retain its storage")
    with _dataset_rag_lock:
        _dataset_rag_app_service = None
