"""Dataset evidence retrieval and knowledge graph query service."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any, Protocol

from app.application.dataset_rag.access_policy import (
    DATASET_ADMIN_PERMISSION,
    DATASET_READ_PERMISSION,
    DATASET_WRITE_PERMISSION,
    _coerce_access_context,
    _ensure_dataset_permission,
    _resolve_tenant_for_access,
)
from app.application.dataset_rag.chunk_context import expanded_context, section_context
from app.application.dataset_rag.document_acl import (
    document_acl,
    document_visible_to,
    filter_chunks_by_acl,
)
from app.application.dataset_rag.knowledge_graph import _build_knowledge_graph_payload
from app.application.dataset_rag.models import (
    DatasetAccessContext,
    DatasetDocument,
    _chunk_to_dict,
    _clean_key,
    _DatasetState,
)
from app.application.dataset_rag.qa_pairs import (
    MAX_QA_PAIRS,
    normalize_qa_pairs,
    qa_chunks,
    scoped_qa_pairs,
)
from app.application.dataset_rag.repository import DatasetRepository
from app.application.dataset_rag.retrieval_policy import (
    _filter_chunks,
    _rerank_chunks,
    _semantic_rerank_chunks,
    evidence_grounding,
    highlight_spans,
    mmr_rerank,
    resolve_min_relevance,
    resolve_mmr_lambda,
)
from app.application.dataset_rag.synonyms import expand_query, normalize_synonyms
from app.application.dataset_rag.vector_index import VectorIndexService
from app.infrastructure.rag import RetrievedChunk
from app.utils.operational_errors import RECOVERABLE_ERRORS


class EvidenceRetriever(Protocol):
    def index(self, chunks: list[RetrievedChunk]) -> None: ...

    def retrieve(self, query: str) -> list[RetrievedChunk]: ...


class RetrieverFactory(Protocol):
    def __call__(
        self,
        *,
        embedder: Callable[[str], list[float]] | None,
        top_k: int,
        mode: str = "hybrid",
        vector_weight: float = 1.0,
        keyword_weight: float = 1.0,
    ) -> EvidenceRetriever: ...


_TABLE_MARKER = re.compile(r"(?m)^\[(table|page) \d+\]")


def _table_context(texts: list[str], *, max_chars: int = 4000) -> str:
    """命中片段附近有 ``[table N]`` 时返回完整 Markdown 表格（跨块拼接、有预算）。"""
    started = False
    parts: list[str] = []
    used = 0
    for raw in texts:
        text = str(raw or "")
        markers = list(_TABLE_MARKER.finditer(text))
        if not started:
            marker = next((match for match in markers if match.group(1) == "table"), None)
            if marker is None:
                continue
            started = True
            segment = text[marker.start() :]
        else:
            if markers and markers[0].start() == 0:
                break
            segment = text
        following = _TABLE_MARKER.search(segment, 1)
        if following is not None:
            segment = segment[: following.start()]
        remaining = max_chars - used
        if len(segment) > remaining:
            segment = segment[:remaining]
        parts.append(segment)
        used += len(segment)
        if used >= max_chars or following is not None:
            break
    return "\n".join(part for part in parts if part).strip()


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


def _auto_rerank_available() -> bool:
    """hash/disabled embedding 时，若本地精排依赖可用则自动精排。"""
    try:
        from app.infrastructure.llm.embedding_service import get_default_embedding_service
        from app.infrastructure.rag.reranker import auto_rerank_allowed, get_default_reranker

        if not auto_rerank_allowed():
            return False
        service = get_default_embedding_service()
        if service is not None and service.is_semantic():
            return False
        return get_default_reranker(auto=True) is not None
    except RECOVERABLE_ERRORS:
        return False


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
        context_window: int = 0,
        min_relevance: float | None = None,
        mmr_lambda: float | None = None,
        retrieval_mode: str = "hybrid",
        vector_weight: float = 1.0,
        keyword_weight: float = 1.0,
        expand_section: bool = False,
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
            documents_in_state = list(state.documents.values()) if state is not None else []
            index_snapshot = dict(state.index or {}) if state is not None else {}
        # 问答对与文档块共用同一召回/精排链路；index 快照里不带答案正文，避免响应过大。
        qa_pairs = (
            []
            if metadata_filter
            else scoped_qa_pairs({"qa_pairs": index_snapshot.pop("qa_pairs", None)}, tenant_key)
        )
        scope_chunks = _filter_chunks(
            chunks, tenant_id=tenant_key, version=version, metadata_filter=metadata_filter or {}
        )
        scope_chunks = filter_chunks_by_acl(scope_chunks, access_context)
        # 术语表（可选）：把用户口语词展开为语料里的写法，只影响召回通道，
        # 引用与证据覆盖率仍按原问题计算。
        retrieval_query = expand_query(query_text, index_snapshot.get("synonyms"))
        # 向量库只能先取候选再按 ACL 过滤；有受限文档时扩大候选池，避免
        # 受限结果占满名额导致本来可见的文档被挤出。
        context = _coerce_access_context(access_context)
        can_bypass_acl = context is None or context.is_admin
        if context is not None and DATASET_ADMIN_PERMISSION in context.permissions:
            can_bypass_acl = True
        candidate_k = max(50, max(1, min(int(top_k), 50)) * 4)
        if not can_bypass_acl and any(document_acl(doc.metadata) for doc in documents_in_state):
            candidate_k = min(500, candidate_k * 8)
        vector_candidates = self._vector._query_vector_index_candidates(
            dataset_id=dataset_key,
            query=retrieval_query,
            top_k=candidate_k,
            tenant_id=tenant_key,
            version=version,
            metadata_filter=metadata_filter or {},
        )
        used_vector_backend = vector_candidates is not None
        if vector_candidates is not None:
            chunks = filter_chunks_by_acl(vector_candidates, access_context)
            index_snapshot["query_backend"] = self._vector._vector_index_backend_name()
        else:
            chunks = filter_chunks_by_acl(
                _filter_chunks(
                    chunks,
                    tenant_id=tenant_key,
                    version=version,
                    metadata_filter=metadata_filter or {},
                ),
                access_context,
            )
            index_snapshot["query_backend"] = "in_memory_hybrid"
        if qa_pairs:
            chunks = [*chunks, *qa_chunks(qa_pairs, tenant_id=tenant_key)]
        if not chunks:
            return {
                "success": True,
                "dataset_id": dataset_key,
                "query": query_text,
                "chunks": [],
                "citations": [],
                "answer": "",
                "grounding": 0.0,
                "answer_grounded": False,
                "tenant_id": tenant_key,
                "version": str(version or ""),
                "vector_backend_used": used_vector_backend,
                "index": index_snapshot,
            }
        final_k = max(1, min(int(top_k), 50))
        auto_rerank = False if rerank else _auto_rerank_available()
        effective_rerank = rerank or auto_rerank
        lambda_value = resolve_mmr_lambda(mmr_lambda)
        # 精排与 MMR 都需要更大的候选池，否则没有可选空间
        retrieve_k = max(final_k * 4, 20) if effective_rerank else final_k
        if lambda_value > 0:
            retrieve_k = max(retrieve_k, final_k * 3, 15)
        mode = str(retrieval_mode or "hybrid").strip().lower()
        mode = mode if mode in {"hybrid", "vector", "keyword"} else "hybrid"
        factory_kwargs: dict[str, Any] = {"embedder": self._vector.embedder, "top_k": retrieve_k}
        if mode != "hybrid":
            factory_kwargs["mode"] = mode
        if float(vector_weight) != 1.0:
            factory_kwargs["vector_weight"] = float(vector_weight)
        if float(keyword_weight) != 1.0:
            factory_kwargs["keyword_weight"] = float(keyword_weight)
        retriever = self._retriever_factory(**factory_kwargs)
        retriever.index(chunks)
        top = retriever.retrieve(retrieval_query)
        if effective_rerank:
            top = _semantic_rerank_chunks(
                query_text, top, top_k=retrieve_k, auto=auto_rerank
            ) or _rerank_chunks(query_text, top, top_k=retrieve_k)
        if lambda_value > 0:
            top = mmr_rerank(
                query_text,
                top,
                lambda_=lambda_value,
                top_k=final_k,
                embedder=self._vector.embedder,
            )
        else:
            top = top[:final_k]
        rows = [_chunk_to_dict(c, public=True) for c in top]
        # 命中词高亮：只给前端标记区间，正文保持原样，避免 HTML 注入。
        for row in rows:
            spans = highlight_spans(str(row.get("text") or ""), query_text)
            if spans:
                row.setdefault("metadata", {})["highlights"] = spans
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
                # PDF 表格：命中块（或其前一块带 [table N] 标记）时补一份完整表格。
                start = int(row.get("char_start") or 0)
                ordered = sorted(
                    (
                        candidate
                        for candidate in scope_chunks
                        if (candidate.metadata or {}).get("document_id") == document_id
                        and (candidate.metadata or {}).get("document_version")
                        == metadata.get("document_version")
                    ),
                    key=lambda item: item.char_start,
                )
                position = next(
                    (index for index, item in enumerate(ordered) if item.char_start == start), 0
                )
                table = _table_context(
                    [item.text for item in ordered[max(0, position - 1) : position + 3]]
                )
                if table.startswith("[table"):
                    metadata["table_context"] = table
        if expand_section:
            for row, chunk in zip(rows, top, strict=True):
                expanded = section_context(chunk, scope_chunks)
                if expanded != chunk.text:
                    row.setdefault("metadata", {})["context"] = expanded
                    row["metadata"]["context_mode"] = "section"
        elif context_window > 0:
            for row, chunk in zip(rows, top, strict=True):
                expanded = expanded_context(chunk, scope_chunks)
                if expanded != chunk.text:
                    row.setdefault("metadata", {})["context"] = expanded
                    row["metadata"]["context_mode"] = "window"
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
        grounding = evidence_grounding(query_text, top)
        threshold = resolve_min_relevance(min_relevance)
        result["grounding"] = round(grounding, 4)
        result["min_relevance"] = round(threshold, 4)
        result["answer_grounded"] = grounding >= threshold
        if include_sheet_context:
            result["sheet_contexts"] = _named_sheet_context(query_text, top, scope_chunks)
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
        """Return one document's chunks (ACL filtered) for preview and hit testing."""
        dataset_key = _clean_key(dataset_id, default="default")
        doc_key = (document_id or "").strip()
        tenant_key, denied = _resolve_tenant_for_access(
            access_context,
            tenant_id,
            required_permission=DATASET_READ_PERMISSION,
            default_without_context="",
            dataset_id=dataset_key,
        )
        if denied is not None:
            denied.update({"document": None, "chunks": [], "total": 0})
            return denied
        with self._repository.lock:
            state = self._repository.datasets.get(dataset_key)
            document = state.documents.get(doc_key) if state is not None else None
            chunks = list(state.chunks) if state is not None else []
        if (
            document is None
            or (tenant_key and document.tenant_id != tenant_key)
            or not document_visible_to(document.metadata, access_context)
        ):
            return {
                "success": False,
                "dataset_id": dataset_key,
                "document_id": doc_key,
                "message": "document not found",
                "error_code": "dataset_document_not_found",
                "document": None,
                "chunks": [],
                "total": 0,
            }
        selected = sorted(
            (
                chunk
                for chunk in chunks
                if str((chunk.metadata or {}).get("document_id") or "") == doc_key
                and document_visible_to(chunk.metadata, access_context)
            ),
            key=lambda item: (item.char_start, item.chunk_index),
        )
        start = max(0, int(offset))
        size = max(1, min(int(limit), 200))
        return {
            "success": True,
            "dataset_id": dataset_key,
            "document": document.to_dict(),
            "chunks": [
                _chunk_to_dict(chunk, public=True) for chunk in selected[start : start + size]
            ],
            "total": len(selected),
            "offset": start,
            "limit": size,
        }

    def synonyms(
        self,
        dataset_id: str,
        *,
        access_context: DatasetAccessContext | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return the dataset synonym groups used for query expansion."""
        dataset_key = _clean_key(dataset_id, default="default")
        context = _coerce_access_context(access_context)
        denied = _ensure_dataset_permission(
            context, DATASET_READ_PERMISSION, dataset_id=dataset_key
        )
        if denied is not None:
            return denied
        with self._repository.lock:
            state = self._repository.datasets.get(dataset_key)
            groups = normalize_synonyms((state.index or {}).get("synonyms")) if state else {}
        return {
            "success": True,
            "dataset_id": dataset_key,
            "synonyms": groups,
            "count": len(groups),
        }

    def set_synonyms(
        self,
        dataset_id: str,
        synonyms: Any,
        *,
        access_context: DatasetAccessContext | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Replace the dataset synonym groups (empty mapping clears them)."""
        dataset_key = _clean_key(dataset_id, default="default")
        context = _coerce_access_context(access_context)
        denied = _ensure_dataset_permission(
            context, DATASET_WRITE_PERMISSION, dataset_id=dataset_key
        )
        if denied is not None:
            return denied
        try:
            cleaned = normalize_synonyms(synonyms)
        except ValueError as exc:
            return {"success": False, "dataset_id": dataset_key, "message": str(exc)}
        with self._repository.lock:
            state = self._repository.datasets.setdefault(dataset_key, _DatasetState(dataset_key))
            state.index["synonyms"] = cleaned
            self._repository._persist_locked()
        return {
            "success": True,
            "dataset_id": dataset_key,
            "synonyms": cleaned,
            "count": len(cleaned),
        }

    def qa_pairs(
        self,
        dataset_id: str,
        *,
        tenant_id: str = "",
        access_context: DatasetAccessContext | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """按租户读取问答对（问题参与召回，答案作为引用证据）。"""
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
            denied.update({"pairs": [], "total": 0})
            return denied
        with self._repository.lock:
            state = self._repository.datasets.get(dataset_key)
            rows = scoped_qa_pairs(state.index if state is not None else None, tenant_key)
        return {
            "success": True,
            "dataset_id": dataset_key,
            "pairs": rows,
            "total": len(rows),
        }

    def set_qa_pairs(
        self,
        dataset_id: str,
        payload: Any,
        *,
        tenant_id: str = "",
        replace: bool = True,
        access_context: DatasetAccessContext | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """写入问答对；默认整租户替换，``replace=False`` 时按问题+答案追加去重。"""
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
        try:
            normalized = normalize_qa_pairs(payload)
        except ValueError as exc:
            return {"success": False, "dataset_id": dataset_key, "message": str(exc)}
        incoming = [{**pair, "tenant_id": tenant_key} for pair in normalized]
        with self._repository.lock:
            state = self._repository.datasets.setdefault(dataset_key, _DatasetState(dataset_key))
            existing = state.index.get("qa_pairs")
            rows = (
                [row for row in existing if isinstance(row, dict)]
                if isinstance(existing, list)
                else []
            )
            others = [row for row in rows if str(row.get("tenant_id") or "") != tenant_key]
            kept = (
                []
                if replace
                else [row for row in rows if str(row.get("tenant_id") or "") == tenant_key]
            )
            merged: list[dict[str, Any]] = []
            seen: set[str] = set()
            for row in [*kept, *incoming]:
                key = str(row.get("qa_id") or "")
                if key and key in seen:
                    continue
                if key:
                    seen.add(key)
                merged.append(row)
            state.index["qa_pairs"] = [*others, *merged][:MAX_QA_PAIRS]
            self._repository._persist_locked()
        scoped = [row for row in merged if str(row.get("tenant_id") or "") == tenant_key]
        return {
            "success": True,
            "dataset_id": dataset_key,
            "pairs": scoped,
            "count": len(incoming),
            "total": len(scoped),
        }

    def delete_qa_pairs(
        self,
        dataset_id: str,
        *,
        tenant_id: str = "",
        access_context: DatasetAccessContext | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """清空当前租户的问答对，其它租户不受影响。"""
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
        removed = 0
        with self._repository.lock:
            state = self._repository.datasets.get(dataset_key)
            existing = state.index.get("qa_pairs") if state is not None else None
            if state is not None and isinstance(existing, list):
                keep = [
                    row
                    for row in existing
                    if isinstance(row, dict) and str(row.get("tenant_id") or "") != tenant_key
                ]
                removed = len(existing) - len(keep)
                state.index["qa_pairs"] = keep
                if removed:
                    self._repository._persist_locked()
        return {"success": True, "dataset_id": dataset_key, "removed": removed}

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
                    if (not tenant_key or doc.tenant_id == tenant_key)
                    and document_visible_to(doc.metadata, access_context)
                ]
                chunks = filter_chunks_by_acl(
                    _filter_chunks(
                        list(state.chunks), tenant_id=tenant_key, version="", metadata_filter={}
                    ),
                    access_context,
                )
        return _build_knowledge_graph_payload(
            dataset_id=dataset_key,
            tenant_id=tenant_key,
            documents=documents,
            chunks=chunks,
            limit=max(20, min(int(limit), 240)),
        )
