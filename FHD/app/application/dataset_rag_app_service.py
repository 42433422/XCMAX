"""Public dataset application API and dependency composition root."""

from __future__ import annotations

import multiprocessing
import os
import threading
from collections.abc import Callable
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
from app.application.dataset_rag.document_lifecycle import (
    _DATASET_DOWNLOAD_ERRORS as _DATASET_DOWNLOAD_ERRORS,
)
from app.application.dataset_rag.document_lifecycle import DocumentLifecycle
from app.application.dataset_rag.document_parser import DocumentParser
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
from app.application.dataset_rag.models import _stable_document_id as _stable_document_id
from app.application.dataset_rag.models import _utc_now_iso as _utc_now_iso
from app.application.dataset_rag.rebuild_coordinator import (
    REBUILD_TERMINAL_STATUSES as REBUILD_TERMINAL_STATUSES,
)
from app.application.dataset_rag.rebuild_coordinator import (
    RebuildCoordinator,
    _rebuild_job_queue_position_locked,
    _recover_rebuild_jobs_locked,
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
from app.application.dataset_rag.status import DatasetStatus
from app.application.dataset_rag.vector_index import VectorIndexService
from app.application.dataset_rag.vector_index import _embedding_metadata as _embedding_metadata
from app.application.dataset_rag.vector_index import (
    _semantic_embedding_available as _semantic_embedding_available,
)
from app.domain.app_pure.dataset_rag_queue import DatasetStateLock
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
from app.utils.path_io.path_utils import get_app_data_dir, get_upload_dir


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
        _recover_rebuild_jobs_locked(state)
        self._renumber_chunks(state)
        self._vector._sync_vector_index_locked(state)
        self._vector._refresh_index_metadata(state)

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
    ) -> dict[str, Any]:
        return self._status._status_for_state(
            dataset_id,
            state,
            tenant_id_filter=tenant_id_filter,
            include_documents=include_documents,
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
    ) -> dict[str, Any]:
        return self._retrieval.query(
            dataset_id=dataset_id,
            query=query,
            top_k=top_k,
            tenant_id=tenant_id,
            version=version,
            metadata_filter=metadata_filter,
            rerank=rerank,
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
        )
        if not result.get("success") or not result.get("chunks"):
            result.setdefault("answer", "")
            result.setdefault("citations", [])
            result.setdefault("raw", "")
            return result
        retrieved = [_dict_to_retrieved_chunk(row) for row in result["chunks"]]
        tracker = CitationTracker(retrieved_chunks=retrieved)
        prompt = tracker.format_for_prompt()
        raw_answer = (
            llm_call(str(result.get("query") or ""), prompt)
            if llm_call is not None
            else _deterministic_answer(str(result.get("query") or ""), retrieved)
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
