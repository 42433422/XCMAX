"""Dataset evidence retrieval and knowledge graph query service."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any, Protocol

from app.application.dataset_rag.access_policy import (
    DATASET_READ_PERMISSION,
    _resolve_tenant_for_access,
)
from app.application.dataset_rag.knowledge_graph import _build_knowledge_graph_payload
from app.application.dataset_rag.models import (
    DatasetAccessContext,
    DatasetDocument,
    _chunk_to_dict,
    _clean_key,
)
from app.application.dataset_rag.repository import DatasetRepository
from app.application.dataset_rag.retrieval_policy import _filter_chunks, _rerank_chunks
from app.application.dataset_rag.vector_index import VectorIndexService
from app.infrastructure.rag import RetrievedChunk


class EvidenceRetriever(Protocol):
    def index(self, chunks: list[RetrievedChunk]) -> None: ...

    def retrieve(self, query: str) -> list[RetrievedChunk]: ...


class RetrieverFactory(Protocol):
    def __call__(
        self, *, embedder: Callable[[str], list[float]] | None, top_k: int
    ) -> EvidenceRetriever: ...


def _named_sheet_context(
    query: str, top: list[RetrievedChunk], scoped_chunks: list[RetrievedChunk]
) -> list[dict[str, Any]]:
    """Expand matching worksheet text without crossing document or tenant boundaries."""
    selected = {
        ((c.metadata or {}).get("document_id"), (c.metadata or {}).get("document_version"))
        for c in top
        if (c.metadata or {}).get("document_id")
    }
    contexts: list[dict[str, Any]] = []
    for document_id, version in sorted(selected, key=lambda item: (str(item[0]), str(item[1]))):
        document = sorted(
            (
                c
                for c in scoped_chunks
                if (c.metadata or {}).get("document_id") == document_id
                and (c.metadata or {}).get("document_version") == version
            ),
            key=lambda c: c.char_start,
        )
        headers = sorted(
            {
                (c.char_start + match.start(), match.group(1).strip())
                for c in document
                for match in re.finditer(r"(?m)^# sheet:([^\n\r]+)", c.text)
            }
        )
        for index, (start, sheet) in enumerate(headers):
            if len(sheet) < 2 or sheet not in query:
                continue
            end = headers[index + 1][0] if index + 1 < len(headers) else float("inf")
            parts: list[str] = []
            cursor = start
            total = 0
            truncated = False
            for chunk in document:
                chunk_end = chunk.char_start + len(chunk.text)
                left = max(start, cursor, chunk.char_start)
                right = min(end, chunk_end)
                if left >= right:
                    continue
                part = chunk.text[int(left - chunk.char_start) : int(right - chunk.char_start)]
                remaining = 12000 - total
                if len(part) > remaining:
                    part, truncated = part[:remaining], True
                parts.append(part)
                total += len(part)
                cursor = int(right)
                if truncated or total >= 12000:
                    truncated = True
                    break
            if parts:
                contexts.append(
                    {
                        "sheet": sheet,
                        "source": str((document[0].metadata or {}).get("source") or ""),
                        "text": "\n".join(parts),
                        "truncated": truncated,
                    }
                )
            if len(contexts) >= 4:
                return contexts
    return contexts


class DatasetRetrieval:
    """Read tenant-filtered evidence and derive citations or a bounded knowledge graph."""

    def __init__(
        self,
        *,
        repository: DatasetRepository,
        vector: VectorIndexService,
        retriever_factory: RetrieverFactory,
    ) -> None:
        self._repository = repository
        self._vector = vector
        self._retriever_factory = retriever_factory

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
    ) -> dict[str, Any]:
        dataset_key = _clean_key(dataset_id, default="default")
        tenant_key, denied = _resolve_tenant_for_access(
            access_context,
            tenant_id,
            required_permission=DATASET_READ_PERMISSION,
            default_without_context="",
            dataset_id=dataset_key,
        )
        if denied is not None:
            denied.update({"chunks": [], "citations": [], "answer": ""})
            return denied
        query_text = query.strip()
        if not query_text:
            return {
                "success": False,
                "dataset_id": dataset_key,
                "message": "query is required",
                "chunks": [],
            }
        with self._repository.lock:
            state = self._repository.datasets.get(dataset_key)
            chunks = list(state.chunks) if state is not None else []
            index_snapshot = dict(state.index or {}) if state is not None else {}
        scope_chunks = _filter_chunks(
            chunks, tenant_id=tenant_key, version=version, metadata_filter=metadata_filter or {}
        )
        vector_candidates = self._vector._query_vector_index_candidates(
            dataset_id=dataset_key,
            query=query_text,
            top_k=max(50, max(1, min(int(top_k), 50)) * 4),
            tenant_id=tenant_key,
            version=version,
            metadata_filter=metadata_filter or {},
        )
        used_vector_backend = vector_candidates is not None
        if vector_candidates is not None:
            chunks = vector_candidates
            index_snapshot["query_backend"] = self._vector._vector_index_backend_name()
        else:
            chunks = _filter_chunks(
                chunks, tenant_id=tenant_key, version=version, metadata_filter=metadata_filter or {}
            )
            index_snapshot["query_backend"] = "in_memory_hybrid"
        if not chunks:
            return {
                "success": True,
                "dataset_id": dataset_key,
                "query": query_text,
                "chunks": [],
                "citations": [],
                "answer": "",
                "tenant_id": tenant_key,
                "version": str(version or ""),
                "vector_backend_used": used_vector_backend,
                "index": index_snapshot,
            }
        retriever = self._retriever_factory(
            embedder=self._vector.embedder, top_k=max(1, min(int(top_k), 50))
        )
        retriever.index(chunks)
        top = retriever.retrieve(query_text)
        if rerank:
            top = _rerank_chunks(query_text, top, top_k=max(1, min(int(top_k), 50)))
        rows = [_chunk_to_dict(c, public=True) for c in top]
        # Excel text embeds sheet boundaries. Recover them for older indexed chunks
        # so rows from another worksheet cannot inherit a customer's identity.
        for row in rows:
            metadata = row.get("metadata") or {}
            document_id = metadata.get("document_id")
            previous: tuple[int, str] | None = None
            if document_id:
                for candidate in scope_chunks:
                    candidate_metadata = candidate.metadata or {}
                    if candidate_metadata.get(
                        "document_id"
                    ) != document_id or candidate_metadata.get("document_version") != metadata.get(
                        "document_version"
                    ):
                        continue
                    for match in re.finditer(r"(?m)^# sheet:([^\n\r]+)", candidate.text):
                        position = candidate.char_start + match.start()
                        if position <= row["char_start"] and (
                            previous is None or position > previous[0]
                        ):
                            previous = (position, match.group(1).strip())
                markers = re.findall(r"(?m)^# sheet:([^\n\r]+)", row.get("text") or "")
                if markers:
                    metadata["sheet_context"] = "片段含工作表边界：" + "、".join(markers)
                elif previous:
                    metadata["sheet_context"] = previous[1]
        result = {
            "success": True,
            "dataset_id": dataset_key,
            "query": query_text,
            "chunks": rows,
            "tenant_id": tenant_key,
            "version": str(version or ""),
            "metadata_filter": metadata_filter or {},
            "rerank": bool(rerank),
            "vector_backend_used": used_vector_backend,
            "index": index_snapshot,
        }
        if include_sheet_context:
            result["sheet_contexts"] = _named_sheet_context(query_text, top, scope_chunks)
        return result

    def knowledge_graph(
        self,
        dataset_id: str,
        *,
        tenant_id: str = "",
        limit: int = 120,
        access_context: DatasetAccessContext | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build a bounded, explainable graph from persisted documents and chunks."""
        dataset_key = _clean_key(dataset_id, default="default")
        tenant_key, denied = _resolve_tenant_for_access(
            access_context,
            tenant_id,
            required_permission=DATASET_READ_PERMISSION,
            default_without_context="",
            dataset_id=dataset_key,
        )
        if denied is not None:
            denied.update({"nodes": [], "edges": [], "stats": {}})
            return denied
        with self._repository.lock:
            state = self._repository.datasets.get(dataset_key)
            if state is None:
                documents: list[DatasetDocument] = []
                chunks: list[RetrievedChunk] = []
            else:
                documents = [
                    doc
                    for doc in state.documents.values()
                    if not tenant_key or doc.tenant_id == tenant_key
                ]
                chunks = _filter_chunks(
                    list(state.chunks), tenant_id=tenant_key, version="", metadata_filter={}
                )
        return _build_knowledge_graph_payload(
            dataset_id=dataset_key,
            tenant_id=tenant_key,
            documents=documents,
            chunks=chunks,
            limit=max(20, min(int(limit), 240)),
        )
