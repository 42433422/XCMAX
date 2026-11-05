"""Versioned document ingestion, removal, comparison, and rollback."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from difflib import unified_diff
from typing import Any

from app.application.dataset_rag.access_policy import (
    DATASET_READ_PERMISSION,
    DATASET_WRITE_PERMISSION,
    _coerce_access_context,
    _ensure_dataset_permission,
    _ensure_tenant_allowed,
    _resolve_tenant_for_access,
)
from app.application.dataset_rag.document_parser import DocumentParser
from app.application.dataset_rag.models import (
    DatasetAccessContext,
    DatasetDocument,
    _clean_key,
    _DatasetState,
    _document_text_locked,
    _resolve_document_for_version,
    _resolve_document_version,
    _stable_document_id,
    _utc_now_iso,
)
from app.application.dataset_rag.repository import DatasetRepository
from app.application.dataset_rag.vector_index import VectorIndexService, _embedding_metadata
from app.infrastructure.rag import RetrievedChunk
from app.utils.operational_errors import RECOVERABLE_ERRORS
from app.utils.security.safe_download_path import UnsafeDownloadPathError

_DATASET_DOWNLOAD_ERRORS = RECOVERABLE_ERRORS + (UnsafeDownloadPathError,)


class DocumentLifecycle:
    """Apply document writes and version changes to the current repository snapshot."""

    def __init__(
        self,
        *,
        repository: DatasetRepository,
        parser: DocumentParser,
        vector: VectorIndexService,
        renumber: Callable[[_DatasetState], None],
    ) -> None:
        self._repository = repository
        self._parser = parser
        self._vector = vector
        self._renumber_chunks = renumber

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
        dataset_key = _clean_key(dataset_id, default="default")
        source_label = source.strip() or file_path.strip() or "inline"
        base_metadata = dict(metadata or {})
        requested_tenant = str(
            tenant_id or base_metadata.get("tenant_id") or base_metadata.get("user_id") or ""
        )
        tenant_key, denied = _resolve_tenant_for_access(
            access_context,
            requested_tenant,
            required_permission=DATASET_WRITE_PERMISSION,
            default_without_context="default",
            dataset_id=dataset_key,
        )
        if denied is not None:
            return denied
        try:
            if text.strip():
                extracted_text = text.strip()
                parser = "inline_text"
                extract_metadata: dict[str, Any] = {}
            elif file_path.strip():
                path = self._parser._resolve_file_path(file_path)
                extracted_text, parser, extract_metadata = self._parser._extract_file_text(path)
                source_label = source.strip() or path.name
                base_metadata.setdefault("file_path", str(path))
            else:
                raise ValueError("text or file_path is required")
            if not extracted_text.strip():
                raise ValueError("document text is empty")
            chunks = self._parser._split_text(
                extracted_text,
                strategy=chunk_strategy,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
            )
            if not chunks:
                raise ValueError("document produced no chunks")
            base_metadata.update(extract_metadata)
            base_metadata["tenant_id"] = tenant_key
            if idempotency_key:
                fingerprint = hashlib.sha256(
                    json.dumps(
                        [
                            tenant_key,
                            source_label,
                            extracted_text,
                            base_metadata,
                            chunk_strategy,
                            chunk_size,
                            chunk_overlap,
                        ],
                        sort_keys=True,
                        ensure_ascii=False,
                        default=str,
                    ).encode("utf-8")
                ).hexdigest()
                base_metadata["ingest_idempotency_key"] = idempotency_key
                base_metadata["ingest_fingerprint"] = fingerprint
            with self._repository.lock:
                state = self._repository.datasets.setdefault(
                    dataset_key, _DatasetState(dataset_key)
                )
                document_version = _resolve_document_version(
                    state, source=source_label, tenant_id=tenant_key, requested=version
                )
            version_text = version_label.strip() or f"v{document_version}"
            base_metadata["document_version"] = document_version
            base_metadata["version_label"] = version_text
            doc_id = document_id.strip() or _stable_document_id(
                dataset_key, tenant_key, source_label, document_version, extracted_text
            )
            document = DatasetDocument(
                document_id=doc_id,
                source=source_label,
                parser=parser,
                text_length=len(extracted_text),
                chunk_count=len(chunks),
                tenant_id=tenant_key,
                version=document_version,
                version_label=version_text,
                metadata=base_metadata,
            )
            retrieved_chunks = [
                RetrievedChunk(
                    text=chunk.text,
                    score=0.0,
                    source=source_label,
                    chunk_index=chunk.chunk_index,
                    char_start=chunk.char_start,
                    char_end=chunk.char_end,
                    metadata={
                        "dataset_id": dataset_key,
                        "document_id": doc_id,
                        "source": source_label,
                        "parser": parser,
                        "strategy": chunk.strategy,
                        "tenant_id": tenant_key,
                        "document_version": document_version,
                        "version_label": version_text,
                        **_embedding_metadata(self._vector.embedder, chunk.text),
                        **base_metadata,
                    },
                    source_url=source_label,
                )
                for chunk in chunks
            ]
            with self._repository.lock:
                # The lock may have loaded another writer's commit while embedding
                # ran. Its new snapshot is authoritative for conflicts and versions.
                state = self._repository.datasets.setdefault(
                    dataset_key, _DatasetState(dataset_key)
                )
                if not document_id.strip() and (version is None or str(version).strip() == ""):
                    committed_version = _resolve_document_version(
                        state, source=source_label, tenant_id=tenant_key, requested=None
                    )
                    doc_id = _stable_document_id(
                        dataset_key, tenant_key, source_label, committed_version, extracted_text
                    )
                    document.document_id = doc_id
                # Caller metadata cannot change the ownership used for deletion,
                # version reconstruction, or vector index replacement.
                for chunk in retrieved_chunks:
                    chunk.metadata = {**(chunk.metadata or {}), "document_id": doc_id}
                previous = state.documents.get(doc_id)
                if previous is not None:
                    # Explicit IDs are dataset-wide; admin permission does not
                    # authorize overwriting another tenant's document identity.
                    if previous.tenant_id != tenant_key:
                        return {"success": False, "error_code": "dataset_document_conflict"}
                    if idempotency_key:
                        if (
                            previous.metadata.get("ingest_idempotency_key") == idempotency_key
                            and previous.metadata.get("ingest_fingerprint") == fingerprint
                        ):
                            return {
                                "success": True,
                                "dataset_id": dataset_key,
                                "document": previous.to_dict(),
                                "chunk_count": previous.chunk_count,
                            }
                        return {"success": False, "error_code": "dataset_document_conflict"}
                latest_version = (
                    _resolve_document_version(
                        state, source=source_label, tenant_id=tenant_key, requested=None
                    )
                    - 1
                )
                if (
                    expected_source_version is not None
                    and latest_version != expected_source_version
                ):
                    return {"success": False, "error_code": "dataset_source_version_conflict"}
                if version is None or str(version).strip() == "":
                    document.version = latest_version + 1
                    document.version_label = version_label.strip() or f"v{document.version}"
                    document.metadata["document_version"] = document.version
                    document.metadata["version_label"] = document.version_label
                    for chunk in retrieved_chunks:
                        chunk.metadata = {
                            **(chunk.metadata or {}),
                            "document_version": document.version,
                            "version_label": document.version_label,
                        }
                state.documents[doc_id] = document
                state.chunks = [
                    c
                    for c in state.chunks
                    if not isinstance(c.metadata, dict) or c.metadata.get("document_id") != doc_id
                ]
                state.chunks.extend(retrieved_chunks)
                self._renumber_chunks(state)
                self._vector._sync_vector_index_locked(state)
                self._vector._refresh_index_metadata(state)
                self._repository._persist_locked()
            return {
                "success": True,
                "dataset_id": dataset_key,
                "document": document.to_dict(),
                "chunk_count": len(chunks),
            }
        except _DATASET_DOWNLOAD_ERRORS as exc:
            return {
                "success": False,
                "dataset_id": dataset_key,
                "message": str(exc),
                "error_code": "dataset_ingest_failed",
            }

    def delete_document(
        self,
        dataset_id: str,
        document_id: str,
        *,
        expected_version: int | None = None,
        expected_metadata: dict[str, Any] | None = None,
        access_context: DatasetAccessContext | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        dataset_key = _clean_key(dataset_id, default="default")
        doc_key = document_id.strip()
        context = _coerce_access_context(access_context)
        denied = _ensure_dataset_permission(
            context, DATASET_WRITE_PERMISSION, dataset_id=dataset_key
        )
        if denied is not None:
            return denied
        with self._repository.lock:
            state = self._repository.datasets.get(dataset_key)
            if state is None or doc_key not in state.documents:
                return {
                    "success": False,
                    "dataset_id": dataset_key,
                    "document_id": doc_key,
                    "message": "document not found",
                }
            document = state.documents[doc_key]
            denied = _ensure_tenant_allowed(
                context, document.tenant_id, dataset_id=dataset_key, operation="delete_document"
            )
            if denied is not None:
                denied["document_id"] = doc_key
                return denied
            if (
                expected_version is not None
                and document.version != expected_version
                or (
                    expected_metadata is not None
                    and any(
                        (
                            document.metadata.get(key) != value
                            for key, value in expected_metadata.items()
                        )
                    )
                )
            ):
                return {"success": False, "error_code": "dataset_document_conflict"}
            state.documents.pop(doc_key, None)
            before = len(state.chunks)
            state.chunks = [
                c
                for c in state.chunks
                if not isinstance(c.metadata, dict) or c.metadata.get("document_id") != doc_key
            ]
            self._renumber_chunks(state)
            self._vector._sync_vector_index_locked(state)
            self._vector._refresh_index_metadata(state)
            self._repository._persist_locked()
        return {
            "success": True,
            "dataset_id": dataset_key,
            "document_id": doc_key,
            "deleted_chunks": before - len(state.chunks),
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
        dataset_key = _clean_key(dataset_id, default="default")
        source_label = source.strip()
        tenant_key, denied = _resolve_tenant_for_access(
            access_context,
            tenant_id,
            required_permission=DATASET_READ_PERMISSION,
            default_without_context="default",
            dataset_id=dataset_key,
        )
        if denied is not None:
            return denied
        with self._repository.lock:
            state = self._repository.datasets.get(dataset_key)
            if state is None:
                return {"success": False, "dataset_id": dataset_key, "message": "dataset not found"}
            from_doc = _resolve_document_for_version(
                state, source=source_label, tenant_id=tenant_key, version=from_version
            )
            to_doc = _resolve_document_for_version(
                state, source=source_label, tenant_id=tenant_key, version=to_version
            )
            if from_doc is None or to_doc is None:
                return {
                    "success": False,
                    "dataset_id": dataset_key,
                    "source": source_label,
                    "tenant_id": tenant_key,
                    "message": "document version not found",
                    "from_version": str(from_version),
                    "to_version": str(to_version),
                }
            from_text = _document_text_locked(state, from_doc.document_id)
            to_text = _document_text_locked(state, to_doc.document_id)
        from_lines = from_text.splitlines() or ([from_text] if from_text else [])
        to_lines = to_text.splitlines() or ([to_text] if to_text else [])
        diff_lines = list(
            unified_diff(
                from_lines,
                to_lines,
                fromfile=f"{source_label}@{from_doc.version_label}",
                tofile=f"{source_label}@{to_doc.version_label}",
                lineterm="",
            )
        )
        added = [
            line[1:] for line in diff_lines if line.startswith("+") and (not line.startswith("+++"))
        ]
        removed = [
            line[1:] for line in diff_lines if line.startswith("-") and (not line.startswith("---"))
        ]
        return {
            "success": True,
            "dataset_id": dataset_key,
            "source": source_label,
            "tenant_id": tenant_key,
            "from_document": from_doc.to_dict(),
            "to_document": to_doc.to_dict(),
            "from_version": from_doc.version,
            "to_version": to_doc.version,
            "changed": from_text != to_text,
            "added_lines": added,
            "removed_lines": removed,
            "diff": diff_lines,
        }

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
        dataset_key = _clean_key(dataset_id, default="default")
        source_label = source.strip()
        tenant_key, denied = _resolve_tenant_for_access(
            access_context,
            tenant_id,
            required_permission=DATASET_WRITE_PERMISSION,
            default_without_context="default",
            dataset_id=dataset_key,
        )
        if denied is not None:
            return denied
        with self._repository.lock:
            state = self._repository.datasets.get(dataset_key)
            if state is None:
                return {"success": False, "dataset_id": dataset_key, "message": "dataset not found"}
            target_doc = _resolve_document_for_version(
                state, source=source_label, tenant_id=tenant_key, version=target_version
            )
            if target_doc is None:
                return {
                    "success": False,
                    "dataset_id": dataset_key,
                    "source": source_label,
                    "tenant_id": tenant_key,
                    "message": "document version not found",
                    "target_version": str(target_version),
                }
            rollback_text = _document_text_locked(state, target_doc.document_id)
            rollback_metadata = dict(target_doc.metadata or {})
            rollback_metadata.update(dict(metadata or {}))
            rollback_metadata.update(
                {
                    "rollback": True,
                    "rollback_from_version": target_doc.version,
                    "rollback_from_document_id": target_doc.document_id,
                    "rollback_at": _utc_now_iso(),
                }
            )
        result = self.ingest_document(
            dataset_id=dataset_key,
            source=source_label,
            text=rollback_text,
            tenant_id=tenant_key,
            metadata=rollback_metadata,
            chunk_strategy="fixed",
            access_context=access_context,
        )
        result["rolled_back_from"] = target_doc.to_dict()
        return result
