"""Redis/RediSearch vector storage（兼容路径）

仅在 ``MODSTORE_VECTOR_BACKEND=redis`` 时被
``modstore_server/knowledge_vector_store.py`` 委托使用，或被
``scripts/migrate_kb_redis_to_chroma.py`` 用于读出存量数据。

新实现请走 ``modstore_server/vector_engine.py`` 的 Chroma 引擎。
"""

from __future__ import annotations

import hashlib
import os
import time
from array import array
from typing import Any, Dict, Iterable, List, Optional

INDEX_NAME = "idx:modstore:kb:chunks"
CHUNK_PREFIX = "modstore:kb:chunk:"
DOC_PREFIX = "modstore:kb:doc:"
USER_DOCS_PREFIX = "modstore:kb:user:"

_redis = None


class KnowledgeVectorError(RuntimeError):
    pass


def vector_dim() -> int:
    return int((os.environ.get("MODSTORE_EMBEDDING_DIM") or "1536").strip() or "1536")


def redis_url() -> str:
    return (
        os.environ.get("MODSTORE_VECTOR_REDIS_URL") or os.environ.get("REDIS_URL") or ""
    ).strip()


def get_redis():
    global _redis
    if _redis is not None:
        return _redis
    url = redis_url()
    if not url:
        raise KnowledgeVectorError("未配置 MODSTORE_VECTOR_REDIS_URL 或 REDIS_URL")
    try:
        import redis
    except ImportError as e:
        raise KnowledgeVectorError("服务器未安装 redis Python 包") from e
    _redis = redis.from_url(
        url,
        decode_responses=False,
        socket_connect_timeout=2.0,
        socket_timeout=8.0,
        retry_on_timeout=True,
        health_check_interval=30,
    )
    return _redis


def _tag_value(value: Any) -> str:
    s = str(value)
    return "".join(("\\" + ch) if ch in r" ,.<>{}[]\"':;!@#$%^&*()-+=~" else ch for ch in s)


def _vec_bytes(values: Iterable[float]) -> bytes:
    arr = array("f", [float(v) for v in values])
    return arr.tobytes()


def doc_key(user_id: int, doc_id: str) -> str:
    return f"{DOC_PREFIX}{user_id}:{doc_id}"


def chunk_key(user_id: int, doc_id: str, idx: int) -> str:
    return f"{CHUNK_PREFIX}{user_id}:{doc_id}:{idx}"


def user_docs_key(user_id: int) -> str:
    return f"{USER_DOCS_PREFIX}{user_id}:docs"


def make_doc_id(user_id: int, filename: str, raw: bytes) -> str:
    h = hashlib.sha256()
    h.update(str(user_id).encode())
    h.update(b"\0")
    h.update((filename or "").encode("utf-8", errors="ignore"))
    h.update(b"\0")
    h.update(raw)
    return h.hexdigest()[:24]


def ensure_index() -> None:
    r = get_redis()
    try:
        r.ft(INDEX_NAME).info()
        return
    except Exception:
        pass

    try:
        from redis.commands.search.field import NumericField, TagField, TextField, VectorField

        try:
            from redis.commands.search.indexDefinition import IndexDefinition, IndexType
        except ImportError:
            from redis.commands.search.index_definition import IndexDefinition, IndexType
    except ImportError as e:
        raise KnowledgeVectorError("redis-py Search 模块不可用") from e

    schema = [
        TagField("user_id"),
        TagField("doc_id"),
        TagField("chunk_id"),
        TextField("filename"),
        TextField("content"),
        NumericField("page_no"),
        NumericField("created_at"),
        VectorField(
            "embedding",
            "HNSW",
            {
                "TYPE": "FLOAT32",
                "DIM": vector_dim(),
                "DISTANCE_METRIC": "COSINE",
                "M": 16,
                "EF_CONSTRUCTION": 200,
            },
        ),
    ]
    definition = IndexDefinition(prefix=[CHUNK_PREFIX], index_type=IndexType.HASH)
    try:
        r.ft(INDEX_NAME).create_index(schema, definition=definition)
    except Exception as e:
        msg = str(e).lower()
        if "unknown command" in msg or "no such index" in msg:
            raise KnowledgeVectorError(
                "Redis 未启用 RediSearch/Vector（需要 Redis Stack 或 Redis Cloud Search）"
            ) from e
        if "already exists" not in msg:
            raise


def status() -> Dict[str, Any]:
    url = redis_url()
    out: Dict[str, Any] = {
        "configured": bool(url),
        "redis_url_configured": bool(url),
        "index_name": INDEX_NAME,
        "dim": vector_dim(),
        "ready": False,
        "error": "",
        "chunks": 0,
    }
    if not url:
        out["error"] = "未配置 Redis URL"
        return out
    try:
        ensure_index()
        r = get_redis()
        info = r.ft(INDEX_NAME).info()
        out["ready"] = True
        out["chunks"] = int(info.get(b"num_docs") or info.get("num_docs") or 0)
    except Exception as e:
        out["error"] = str(e)
    return out


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
    if len(chunks) != len(embeddings):
        raise KnowledgeVectorError("chunks 与 embeddings 数量不一致")
    ensure_index()
    r = get_redis()
    created_at = int(time.time())
    delete_document(user_id, doc_id, missing_ok=True)
    pipe = r.pipeline(transaction=False)
    pipe.hset(
        doc_key(user_id, doc_id),
        mapping={
            "user_id": str(user_id),
            "doc_id": doc_id,
            "filename": filename,
            "size_bytes": str(size_bytes),
            "chunk_count": str(len(chunks)),
            "created_at": str(created_at),
        },
    )
    pipe.zadd(user_docs_key(user_id), {doc_id: created_at})
    metas = chunk_metas or [{} for _ in chunks]
    for i, (chunk, emb) in enumerate(zip(chunks, embeddings)):
        cid = f"{doc_id}:{i}"
        meta = metas[i] if i < len(metas) and isinstance(metas[i], dict) else {}
        page_no = meta.get("page_no")
        mapping = {
            "user_id": str(user_id),
            "doc_id": doc_id,
            "chunk_id": cid,
            "filename": filename,
            "content": chunk,
            "chunk_index": str(i),
            "created_at": str(created_at),
            "embedding": _vec_bytes(emb),
        }
        if page_no is not None:
            mapping["page_no"] = str(int(page_no))
        pipe.hset(
            chunk_key(user_id, doc_id, i),
            mapping=mapping,
        )
    pipe.execute()
    return {
        "doc_id": doc_id,
        "filename": filename,
        "size_bytes": size_bytes,
        "chunk_count": len(chunks),
        "created_at": created_at,
    }


def _decode_hash(row: Dict[Any, Any]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for k, v in (row or {}).items():
        ks = k.decode("utf-8", errors="ignore") if isinstance(k, bytes) else str(k)
        if isinstance(v, bytes):
            out[ks] = v.decode("utf-8", errors="ignore")
        else:
            out[ks] = str(v)
    return out


def list_documents(user_id: int) -> List[Dict[str, Any]]:
    r = get_redis()
    ids = r.zrevrange(user_docs_key(user_id), 0, 199)
    out = []
    for raw in ids:
        doc_id = raw.decode() if isinstance(raw, bytes) else str(raw)
        data = _decode_hash(r.hgetall(doc_key(user_id, doc_id)))
        if not data:
            continue
        out.append(
            {
                "doc_id": data.get("doc_id", doc_id),
                "filename": data.get("filename", ""),
                "size_bytes": int(data.get("size_bytes") or 0),
                "chunk_count": int(data.get("chunk_count") or 0),
                "created_at": int(data.get("created_at") or 0),
            }
        )
    return out


def delete_document(user_id: int, doc_id: str, *, missing_ok: bool = False) -> bool:
    r = get_redis()
    pattern = f"{CHUNK_PREFIX}{user_id}:{doc_id}:*"
    keys = list(r.scan_iter(match=pattern, count=200))
    dk = doc_key(user_id, doc_id)
    exists = bool(keys or r.exists(dk))
    if not exists and not missing_ok:
        return False
    if keys:
        r.delete(*keys)
    r.delete(dk)
    r.zrem(user_docs_key(user_id), doc_id)
    return exists


def search(user_id: int, query_embedding: List[float], limit: int = 6) -> List[Dict[str, Any]]:
    ensure_index()
    try:
        from redis.commands.search.query import Query
    except ImportError as e:
        raise KnowledgeVectorError("redis-py Search Query 模块不可用") from e

    r = get_redis()
    n = max(1, min(int(limit or 6), 20))
    q = (
        Query(f"(@user_id:{{{_tag_value(user_id)}}})=>[KNN {n} @embedding $vec AS distance]")
        .return_fields("doc_id", "chunk_id", "filename", "content", "page_no", "distance")
        .sort_by("distance")
        .paging(0, n)
        .dialect(2)
    )
    res = r.ft(INDEX_NAME).search(q, query_params={"vec": _vec_bytes(query_embedding)})
    items = []
    for doc in getattr(res, "docs", []) or []:
        items.append(
            {
                "doc_id": getattr(doc, "doc_id", ""),
                "chunk_id": getattr(doc, "chunk_id", ""),
                "filename": getattr(doc, "filename", ""),
                "content": getattr(doc, "content", ""),
                "page_no": int(getattr(doc, "page_no", 0) or 0) or None,
                "distance": float(getattr(doc, "distance", 1.0)),
            }
        )
    return items
