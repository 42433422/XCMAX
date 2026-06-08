"""知识库向量存储（v1 兼容门面）

历史上这里是 Redis Stack 的 RediSearch HNSW 实现，现在统一接入
``modstore_server.vector_engine`` 的 Chroma 引擎。原 Redis 实现保留在
``knowledge_vector_store_redis.py``，可通过 ``MODSTORE_VECTOR_BACKEND=redis``
切回（用于灰度或回滚）。

对外公开 API 保持不变，让 ``knowledge_vector_api.py`` 与前端 v1 接口完全向后兼容：

- ``KnowledgeVectorError``
- ``vector_dim()``
- ``make_doc_id(user_id, filename, raw)``
- ``ensure_index()``
- ``status()``
- ``upsert_document(...)``
- ``list_documents(user_id)``
- ``delete_document(user_id, doc_id, missing_ok=False)``
- ``search(user_id, query_embedding, limit=6)``
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
from typing import Any, Dict, List, Optional

from modstore_server import vector_engine
from modstore_server.models import (
    KnowledgeCollection,
    KnowledgeDocument,
    get_session_factory,
)
from modstore_server.vector_engine import VectorEngineError

logger = logging.getLogger(__name__)


DEFAULT_USER_COLLECTION_NAME = "default"


class KnowledgeVectorError(RuntimeError):
    """知识库向量存储相关错误（保留旧类名以兼容外部 try/except）。"""


def vector_dim() -> int:
    return int((os.environ.get("MODSTORE_EMBEDDING_DIM") or "1536").strip() or "1536")


def _backend() -> str:
    return (os.environ.get("MODSTORE_VECTOR_BACKEND") or "chroma").strip().lower() or "chroma"


def make_doc_id(user_id: int, filename: str, raw: bytes) -> str:
    """与历史实现保持完全一致的 doc_id 计算（24 字节 sha256 前缀）。"""
    h = hashlib.sha256()
    h.update(str(user_id).encode())
    h.update(b"\0")
    h.update((filename or "").encode("utf-8", errors="ignore"))
    h.update(b"\0")
    h.update(raw)
    return h.hexdigest()[:24]


# ---------------------------------------------------------------------------
# Redis 后端委托（仅 backend=redis 时使用）
# ---------------------------------------------------------------------------


def _redis_module():
    from modstore_server import knowledge_vector_store_redis as redis_impl

    return redis_impl


# ---------------------------------------------------------------------------
# 默认 Chroma 后端
# ---------------------------------------------------------------------------


def _ensure_user_default_collection(session, user_id: int) -> KnowledgeCollection:
    row = (
        session.query(KnowledgeCollection)
        .filter(
            KnowledgeCollection.owner_kind == "user",
            KnowledgeCollection.owner_id == str(int(user_id)),
            KnowledgeCollection.name == DEFAULT_USER_COLLECTION_NAME,
        )
        .first()
    )
    if row is not None:
        return row
    row = KnowledgeCollection(
        owner_kind="user",
        owner_id=str(int(user_id)),
        name=DEFAULT_USER_COLLECTION_NAME,
        description="自动生成的用户默认知识库（v1 兼容）",
        visibility="private",
        embedding_model=(os.environ.get("MODSTORE_EMBEDDING_MODEL") or "").strip()
        or "text-embedding-3-small",
        embedding_dim=vector_dim(),
        chunk_count=0,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def ensure_index() -> None:
    """v1 旧名：在 Chroma 后端下其实就是确认 PersistentClient 可用。"""
    if _backend() == "redis":
        try:
            _redis_module().ensure_index()
        except Exception as e:  # noqa: BLE001
            raise KnowledgeVectorError(str(e)) from e
        return
    try:
        vector_engine.get_client()
    except VectorEngineError as e:
        raise KnowledgeVectorError(str(e)) from e


def status() -> Dict[str, Any]:
    """诊断信息。形态尽量与历史返回兼容：``configured/ready/chunks/error``。"""
    if _backend() == "redis":
        try:
            return _redis_module().status()
        except Exception as e:  # noqa: BLE001
            return {
                "configured": False,
                "ready": False,
                "chunks": 0,
                "error": str(e),
                "backend": "redis",
            }

    info = vector_engine.status()
    chunks = 0
    try:
        sf = get_session_factory()
        with sf() as session:
            for row in session.query(KnowledgeDocument).all():
                chunks += int(row.chunk_count or 0)
    except Exception:  # noqa: BLE001
        chunks = 0
    return {
        "configured": True,
        "ready": bool(info.get("ready")),
        "backend": "chroma",
        "persist_dir": info.get("persist_dir", ""),
        "collections": int(info.get("collections") or 0),
        "chunks": chunks,
        "dim": vector_dim(),
        "error": info.get("error", ""),
    }


def upsert_document(
    *,
    user_id: int,
    doc_id: str,
    filename: str,
    size_bytes: int,
    chunks: List[str],
    embeddings: List[List[float]],
    chunk_metas: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    if _backend() == "redis":
        try:
            return _redis_module().upsert_document(
                user_id=user_id,
                doc_id=doc_id,
                filename=filename,
                size_bytes=size_bytes,
                chunks=chunks,
                embeddings=embeddings,
                chunk_metas=chunk_metas,
            )
        except Exception as e:  # noqa: BLE001
            raise KnowledgeVectorError(str(e)) from e

    if len(chunks) != len(embeddings):
        raise KnowledgeVectorError("chunks 与 embeddings 数量不一致")

    metas = chunk_metas or [{} for _ in chunks]
    if len(metas) != len(chunks):
        metas = (metas + [{} for _ in chunks])[: len(chunks)]

    sf = get_session_factory()
    with sf() as session:
        coll = _ensure_user_default_collection(session, int(user_id))
        try:
            delete_document(int(user_id), doc_id, missing_ok=True)
        except Exception:  # noqa: BLE001
            pass
        created_at = int(time.time())
        ids: List[str] = []
        documents: List[str] = []
        out_metas: List[Dict[str, Any]] = []
        for i, chunk in enumerate(chunks):
            cid = f"{doc_id}:{i}"
            ids.append(cid)
            documents.append(chunk)
            meta_in = metas[i] if i < len(metas) and isinstance(metas[i], dict) else {}
            meta_out: Dict[str, Any] = {
                "user_id": str(int(user_id)),
                "doc_id": str(doc_id),
                "chunk_id": cid,
                "filename": str(filename or ""),
                "chunk_index": int(i),
                "created_at": created_at,
            }
            page_no = meta_in.get("page_no")
            if page_no is not None:
                try:
                    meta_out["page_no"] = int(page_no)
                except Exception:  # noqa: BLE001
                    pass
            out_metas.append(meta_out)

        try:
            vector_engine.upsert(
                vector_engine.kb_collection_name(coll.id),
                ids=ids,
                embeddings=embeddings,
                documents=documents,
                metadatas=out_metas,
            )
        except VectorEngineError as e:
            raise KnowledgeVectorError(str(e)) from e

        doc_row = (
            session.query(KnowledgeDocument)
            .filter(
                KnowledgeDocument.collection_id == coll.id,
                KnowledgeDocument.doc_id == str(doc_id),
            )
            .first()
        )
        if doc_row is None:
            doc_row = KnowledgeDocument(
                collection_id=coll.id,
                doc_id=str(doc_id),
                filename=str(filename or ""),
                size_bytes=int(size_bytes or 0),
                chunk_count=len(chunks),
            )
            session.add(doc_row)
        else:
            doc_row.filename = str(filename or "")
            doc_row.size_bytes = int(size_bytes or 0)
            doc_row.chunk_count = len(chunks)

        chunk_rows = (
            session.query(KnowledgeDocument.chunk_count)
            .filter(KnowledgeDocument.collection_id == coll.id)
            .all()
        )
        coll.chunk_count = sum(int(r[0] or 0) for r in chunk_rows)
        session.commit()
        return {
            "doc_id": doc_id,
            "filename": filename,
            "size_bytes": int(size_bytes or 0),
            "chunk_count": len(chunks),
            "created_at": created_at,
        }


def list_documents(user_id: int) -> List[Dict[str, Any]]:
    if _backend() == "redis":
        try:
            return _redis_module().list_documents(user_id)
        except Exception as e:  # noqa: BLE001
            raise KnowledgeVectorError(str(e)) from e

    sf = get_session_factory()
    with sf() as session:
        coll = (
            session.query(KnowledgeCollection)
            .filter(
                KnowledgeCollection.owner_kind == "user",
                KnowledgeCollection.owner_id == str(int(user_id)),
                KnowledgeCollection.name == DEFAULT_USER_COLLECTION_NAME,
            )
            .first()
        )
        if coll is None:
            return []
        rows = (
            session.query(KnowledgeDocument)
            .filter(KnowledgeDocument.collection_id == coll.id)
            .order_by(KnowledgeDocument.created_at.desc())
            .all()
        )
        out = []
        for r in rows:
            out.append(
                {
                    "doc_id": r.doc_id,
                    "filename": r.filename or "",
                    "size_bytes": int(r.size_bytes or 0),
                    "chunk_count": int(r.chunk_count or 0),
                    "created_at": int(r.created_at.timestamp()) if r.created_at else 0,
                }
            )
        return out


def delete_document(user_id: int, doc_id: str, *, missing_ok: bool = False) -> bool:
    if _backend() == "redis":
        try:
            return _redis_module().delete_document(user_id, doc_id, missing_ok=missing_ok)
        except Exception as e:  # noqa: BLE001
            raise KnowledgeVectorError(str(e)) from e

    sf = get_session_factory()
    with sf() as session:
        coll = (
            session.query(KnowledgeCollection)
            .filter(
                KnowledgeCollection.owner_kind == "user",
                KnowledgeCollection.owner_id == str(int(user_id)),
                KnowledgeCollection.name == DEFAULT_USER_COLLECTION_NAME,
            )
            .first()
        )
        if coll is None:
            if missing_ok:
                return False
            return False
        doc_row = (
            session.query(KnowledgeDocument)
            .filter(
                KnowledgeDocument.collection_id == coll.id,
                KnowledgeDocument.doc_id == str(doc_id),
            )
            .first()
        )
        existed = doc_row is not None
        try:
            vector_engine.delete(
                vector_engine.kb_collection_name(coll.id),
                where={"doc_id": str(doc_id)},
            )
        except VectorEngineError:
            pass
        if doc_row is not None:
            session.delete(doc_row)
            coll.chunk_count = max(0, int(coll.chunk_count or 0) - int(doc_row.chunk_count or 0))
            session.commit()
        if not existed and not missing_ok:
            return False
        return existed


def search(user_id: int, query_embedding: List[float], limit: int = 6) -> List[Dict[str, Any]]:
    if _backend() == "redis":
        try:
            return _redis_module().search(user_id, query_embedding, limit)
        except Exception as e:  # noqa: BLE001
            raise KnowledgeVectorError(str(e)) from e

    sf = get_session_factory()
    with sf() as session:
        coll = (
            session.query(KnowledgeCollection)
            .filter(
                KnowledgeCollection.owner_kind == "user",
                KnowledgeCollection.owner_id == str(int(user_id)),
                KnowledgeCollection.name == DEFAULT_USER_COLLECTION_NAME,
            )
            .first()
        )
        if coll is None:
            return []
        try:
            rows = vector_engine.query(
                vector_engine.kb_collection_name(coll.id),
                query_embedding=query_embedding,
                top_k=int(limit or 6),
            )
        except VectorEngineError as e:
            raise KnowledgeVectorError(str(e)) from e

    items: List[Dict[str, Any]] = []
    for r in rows:
        meta = r.get("metadata") or {}
        page_no_raw = meta.get("page_no")
        page_no = None
        if page_no_raw not in (None, "", 0):
            try:
                page_no = int(page_no_raw)
            except Exception:  # noqa: BLE001
                page_no = None
        items.append(
            {
                "doc_id": str(meta.get("doc_id") or ""),
                "chunk_id": str(meta.get("chunk_id") or r.get("id") or ""),
                "filename": str(meta.get("filename") or ""),
                "content": r.get("document") or "",
                "page_no": page_no,
                "distance": float(r.get("distance") or 1.0),
            }
        )
    return items


__all__ = [
    "KnowledgeVectorError",
    "vector_dim",
    "make_doc_id",
    "ensure_index",
    "status",
    "upsert_document",
    "list_documents",
    "delete_document",
    "search",
]
