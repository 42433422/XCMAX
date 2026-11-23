from __future__ import annotations

import hashlib
import os
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from app.application.excel_vector_app_service import HashEmbedder
from app.domain.excel.ports import VectorStorePort
from app.infrastructure.persistence.user_memory_vector_store import get_user_memory_vector_store
from app.utils.deployment import env_float as _env_float
from app.utils.operational_errors import RECOVERABLE_ERRORS


@dataclass
class UserMemoryVectorChunk:
    chunk_id: str
    content: str
    metadata: dict[str, Any]


class UserMemoryVectorIngestApplicationService:
    """把用户记忆事件（action/feedback 等）写入用户向量库。"""

    def __init__(
        self,
        vector_store: VectorStorePort | None = None,
        embedder: HashEmbedder | None = None,
    ) -> None:
        self._vector_store = vector_store or get_user_memory_vector_store()
        self._embedder = embedder or HashEmbedder()

    def _ensure_user_index(self, user_id: str) -> None:
        if hasattr(self._vector_store, "create_or_update_index"):
            # index_id 直接映射为 user_id，便于 RAG 查询只传 user_id。
            self._vector_store.create_or_update_index(index_id=user_id, user_id=user_id)

    def upsert_governed(
        self,
        *,
        user_id: str,
        source_memory_id: str,
        revision: int,
        text: str,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        if (
            not user_id
            or not source_memory_id
            or type(revision) is not int
            or revision < 1
            or not text.strip()
        ):
            return False
        chunk_id = (
            "memory-v2:" + hashlib.sha256(f"{user_id}\0{source_memory_id}".encode()).hexdigest()
        )
        result = self.ingest_chunks(
            user_id,
            [
                UserMemoryVectorChunk(
                    chunk_id=chunk_id,
                    content=text,
                    metadata={
                        **(metadata or {}),
                        "source_memory_id": source_memory_id,
                        "source_revision": revision,
                        "source_owner_id": user_id,
                    },
                )
            ],
        )
        return bool(result.get("success") and result.get("written"))

    def forget_source(self, *, user_id: str, source_memory_id: str) -> int:
        delete = getattr(self._vector_store, "delete_source", None)
        if not callable(delete):
            return -1
        return int(delete(index_id=user_id, source_memory_id=source_memory_id))

    def ingest_chunks(
        self,
        user_id: str,
        chunks: list[UserMemoryVectorChunk],
    ) -> dict[str, Any]:
        if not user_id:
            return {"success": False, "message": "缺少 user_id"}
        if not chunks:
            return {"success": True, "message": "无可写入内容", "written": 0}

        ttl_days, max_chunks = _memory_vector_limits()
        self._ensure_user_index(user_id)

        expires_at = (datetime.now().astimezone() + timedelta(days=ttl_days)).isoformat()
        safe_chunks: list[UserMemoryVectorChunk] = []
        for chunk in chunks[:max_chunks]:
            safe_content, safe_metadata = _memory_safe(chunk.content, chunk.metadata)
            safe_metadata["expires_at"] = expires_at
            safe_chunks.append(
                UserMemoryVectorChunk(
                    chunk_id=str(chunk.chunk_id or uuid.uuid4().hex)[:160],
                    content=safe_content,
                    metadata=safe_metadata,
                )
            )
        texts = [c.content for c in safe_chunks]
        embeddings = self._embedder.embed_texts(texts)
        store_payload: list[dict[str, Any]] = []
        for c, emb in zip(safe_chunks, embeddings):
            store_payload.append(
                {
                    "chunk_id": c.chunk_id,
                    "content": c.content,
                    "embedding": emb,
                    "metadata": c.metadata,
                }
            )

        written = self._vector_store.upsert_chunks(index_id=user_id, chunks=store_payload)
        prune = getattr(self._vector_store, "prune_index", None)
        if callable(prune):
            prune(
                index_id=user_id,
                older_than=time.time() - ttl_days * 24 * 60 * 60,
                max_chunks=max_chunks,
            )
        return {"success": True, "index_id": user_id, "written": written, "chunk_count": written}


def _memory_vector_limits() -> tuple[int, int]:
    try:
        ttl_days = max(1, min(3650, int(os.environ.get("XCAGI_USER_MEMORY_VECTOR_TTL_DAYS", "90"))))
    except ValueError:
        ttl_days = 90
    try:
        max_chunks = max(
            1, min(10000, int(os.environ.get("XCAGI_USER_MEMORY_VECTOR_MAX_CHUNKS", "400")))
        )
    except ValueError:
        max_chunks = 400
    return ttl_days, max_chunks


def _memory_safe(content: Any, metadata: Any) -> tuple[str, dict[str, Any]]:
    from app.application.ai_chat.conversation_history import _storage_safe

    safe_content = str(_storage_safe(str(content or "")))[:8000]
    safe_metadata = _storage_safe(metadata if isinstance(metadata, dict) else {})
    if not isinstance(safe_metadata, dict):
        safe_metadata = {}
    return safe_content, safe_metadata


class UserMemoryRagApplicationService:
    """用户记忆 RAG：基于用户向量库做语义检索。"""

    def __init__(
        self,
        vector_store: VectorStorePort | None = None,
        embedder: HashEmbedder | None = None,
        recall_validator: Callable[[list[dict[str, Any]]], list[dict[str, Any]]] | None = None,
    ) -> None:
        self._vector_store = vector_store or get_user_memory_vector_store()
        self._embedder = embedder or HashEmbedder()
        self._recall_validator = recall_validator

    def _validated_hits(self, user_id: str, hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
        from app.application.user_memory.retrieve import filter_recalled_memories

        if self._recall_validator is not None:
            return self._recall_validator(hits)
        return filter_recalled_memories(user_id, hits)

    def query(
        self, user_id: str, query_text: str, top_k: int = 5, min_score: float | None = None
    ) -> dict[str, Any]:
        if not user_id:
            return {"success": False, "message": "缺少 user_id"}
        query_text = str(query_text or "").strip()
        if not query_text:
            return {"success": False, "message": "缺少 query_text"}

        ttl_days, max_chunks = _memory_vector_limits()
        prune = getattr(self._vector_store, "prune_index", None)
        if callable(prune):
            prune(
                index_id=user_id,
                older_than=time.time() - ttl_days * 24 * 60 * 60,
                max_chunks=max_chunks,
            )
        query_vector = self._embedder.embed_query(query_text)
        hits = self._vector_store.query(
            index_id=user_id,
            query_vector=query_vector,
            top_k=max(1, min(20, int(top_k))),
            filters={
                "created_after": time.time() - ttl_days * 24 * 60 * 60,
                "governed_only": self._recall_validator is None,
            },
        )
        from app.application.ai_feature_isolation import allows_channel, current_ai_feature_channel

        channel = current_ai_feature_channel()
        if channel:
            hits = [
                hit
                for hit in hits
                if allows_channel(hit.get("metadata") if isinstance(hit, dict) else None, channel)
            ]
        safe_hits: list[dict[str, Any]] = []
        hits = self._validated_hits(user_id, hits)
        if self._recall_validator is None:
            from app.application.user_memory.retrieve import (
                merge_relation_hits,
                recall_authoritative_memories,
                relation_recall_hits,
            )

            bounded = max(1, min(20, int(top_k)))
            if not hits:
                hits = recall_authoritative_memories(user_id, query_text, bounded)
            else:
                related = relation_recall_hits(user_id, query_text)
                if channel:
                    related = [
                        hit for hit in related if allows_channel(hit.get("metadata"), channel)
                    ]
                hits = merge_relation_hits(hits, related, limit=bounded)
        for hit in hits:
            if not isinstance(hit, dict):
                continue
            safe_content, safe_metadata = _memory_safe(hit.get("content"), hit.get("metadata"))
            safe_hits.append({**hit, "content": safe_content, "metadata": safe_metadata})
        hits = safe_hits[: max(1, min(20, int(top_k)))]
        floor = (
            _env_float("XCAGI_MEMORY_RAG_MIN_SCORE", 0.0) if min_score is None else float(min_score)
        )
        if floor > 0:
            hits = [hit for hit in hits if float(hit.get("score") or 0.0) >= floor]
        return {
            "success": True,
            "user_id": user_id,
            "query": query_text,
            "top_k": top_k,
            "min_score": floor,
            "hits": hits,
        }

    def format_for_prompt(
        self,
        user_id: str,
        query_text: str,
        hits: list[dict[str, Any]],
        max_hits: int = 6,
        max_chars: int | None = None,
    ) -> str:
        budget = (
            int(_env_float("XCAGI_MEMORY_RAG_PROMPT_CHARS", 1800))
            if max_chars is None
            else int(max_chars)
        )
        hits = self._validated_hits(user_id, hits)
        if not hits:
            message = "【UserMemoryRAG】未召回用户记忆片段。"
            return message if len(message) <= budget else ""
        from app.application.user_memory.retrieve import format_relation_evidence

        footer = "优先参考以上片段的意图/习惯（不要编造片段中不存在的信息）。"
        lines: list[str] = ["【UserMemoryRAG】召回到以下用户记忆片段（用于辅助决策）:"]
        for idx, hit in enumerate(hits[:max_hits], start=1):
            score = float(hit.get("score") or 0.0)
            md = hit.get("metadata") if isinstance(hit.get("metadata"), dict) else {}
            if not isinstance(md, dict):
                md = {}
            preview, safe_md = _memory_safe(hit.get("content"), md)
            md = safe_md
            source = str(md.get("source") or "-")
            intent = md.get("intent") or md.get("recognized_intent") or ""
            user_feedback = md.get("user_feedback") or ""
            corrected_intent = md.get("corrected_intent") or ""
            last_used = md.get("last_used") or ""
            raw_slots = md.get("slots")
            slots: dict[str, Any] = dict(raw_slots) if isinstance(raw_slots, dict) else {}

            # slots 可能含较多键，做轻量展示。
            slot_str = ", ".join([f"{k}={slots[k]}" for k in list((slots or {}).keys())[:6]])
            preview = str(preview or "").strip()
            if len(preview) > 240:
                preview = preview[:240] + "…"

            preview += format_relation_evidence({**hit, "metadata": md})
            line = (
                f"{idx}. source={source}; intent={intent}; feedback={user_feedback or '-'}; corrected_intent={corrected_intent or '-'}; "
                f"last_used={last_used or '-'}; slots({slot_str or '-'}) ; score={score:.4f}\n"
                f"   content={preview}"
            )
            if len("\n".join([*lines, line, footer])) > budget:
                break
            lines.append(line)
        if len("\n".join([*lines, footer])) > budget:
            return ""
        lines.append(footer)
        return "\n".join(lines)


from app.neuro_bus.neuro_application_instrumentation import instrument_application_service_class

instrument_application_service_class(UserMemoryVectorIngestApplicationService)
instrument_application_service_class(UserMemoryRagApplicationService)

_user_memory_vector_ingest_service: UserMemoryVectorIngestApplicationService | None = None
_user_memory_rag_service: UserMemoryRagApplicationService | None = None


def get_user_memory_vector_ingest_app_service() -> UserMemoryVectorIngestApplicationService:
    global _user_memory_vector_ingest_service
    if _user_memory_vector_ingest_service is None:
        _user_memory_vector_ingest_service = UserMemoryVectorIngestApplicationService()
    return _user_memory_vector_ingest_service


def get_user_memory_rag_app_service() -> UserMemoryRagApplicationService:
    global _user_memory_rag_service
    if _user_memory_rag_service is None:
        _user_memory_rag_service = UserMemoryRagApplicationService()
    return _user_memory_rag_service


def _register_working_memory_long_term_provider() -> None:
    """把本服务组装进 domain 层 ``WorkingMemory`` 长期召回（application→domain 合法方向）。

    callable 经 ``sys.modules`` 晚绑定本模块属性，保证测试对
    ``get_user_memory_rag_app_service`` 的 patch 仍然生效。
    """
    import sys

    try:
        from app.domain.neuro.cognition.working_memory import set_long_term_recall_provider

        _self = sys.modules[__name__]
        set_long_term_recall_provider(lambda: _self.get_user_memory_rag_app_service())
    except RECOVERABLE_ERRORS:
        pass


_register_working_memory_long_term_provider()
