"""RedisVL vector index for self-evolution KB.

This module is deliberately isolated from the generic user knowledge-base
store. It indexes the file-backed fix/pattern KB under ``FHD/XCAGI/kb`` and is
used by the self-maintenance loop before falling back to lexical/RagService
ranking.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

INDEX_PREFIX = "xcmax:self_evolution_kb:"
SIGNATURE_PREFIX = "xcmax:self_evolution_kb:signature:"
DEFAULT_DIM = 1536
MAX_DOC_TEXT = 12000


class SelfEvolutionRedisVLError(RuntimeError):
    pass


def enabled() -> bool:
    raw = (os.environ.get("MODSTORE_SELF_EVOLUTION_REDISVL_ENABLED") or "1").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def redis_url() -> str:
    return (
        os.environ.get("MODSTORE_SELF_EVOLUTION_REDIS_URL")
        or os.environ.get("MODSTORE_VECTOR_REDIS_URL")
        or os.environ.get("REDIS_URL")
        or ""
    ).strip()


def _embedding_dim() -> int:
    raw = (os.environ.get("MODSTORE_SELF_EVOLUTION_EMBEDDING_DIM") or "").strip()
    if raw:
        return int(raw)
    try:
        from modstore_server.embedding_service import embedding_config_snapshot

        return int(embedding_config_snapshot().get("dim") or DEFAULT_DIM)
    except Exception:
        return int(
            (os.environ.get("MODSTORE_EMBEDDING_DIM") or str(DEFAULT_DIM)).strip() or DEFAULT_DIM
        )


def _index_name(kind: str) -> str:
    safe = "".join(ch if ch.isalnum() else "_" for ch in str(kind or "kb").lower())
    return f"idx:xcmax:self_evolution:{safe}"


def _key_prefix(kind: str) -> str:
    safe = "".join(ch if ch.isalnum() else "_" for ch in str(kind or "kb").lower())
    return f"{INDEX_PREFIX}{safe}:"


def _doc_id(kind: str, doc: Dict[str, Any]) -> str:
    raw = str(
        doc.get("_path")
        or doc.get("id")
        or doc.get("created_at")
        or json.dumps(doc, sort_keys=True)
    )
    return hashlib.sha256(f"{kind}\0{raw}".encode("utf-8")).hexdigest()[:32]


def _doc_text(doc: Dict[str, Any], fields: Sequence[str]) -> str:
    parts: List[str] = []
    for field in fields:
        value = doc.get(field)
        if value:
            parts.append(f"{field}: {value}")
    template = doc.get("executable_template")
    if isinstance(template, dict):
        parts.append(
            "executable_template: " + json.dumps(template, ensure_ascii=False, sort_keys=True)
        )
    if not parts:
        parts.append(json.dumps(doc, ensure_ascii=False, sort_keys=True, default=str))
    return "\n".join(parts)[:MAX_DOC_TEXT]


def _signature(kind: str, docs: Sequence[Dict[str, Any]], fields: Sequence[str]) -> str:
    h = hashlib.sha256()
    h.update(str(kind).encode("utf-8"))
    for doc in docs:
        h.update(b"\0")
        h.update(str(doc.get("_path") or "").encode("utf-8", errors="ignore"))
        h.update(b"\0")
        h.update(_doc_text(doc, fields).encode("utf-8", errors="ignore"))
    h.update(b"\0")
    h.update(str(_embedding_dim()).encode("ascii"))
    return h.hexdigest()


def _redis_client():
    url = redis_url()
    if not url:
        raise SelfEvolutionRedisVLError("Redis URL not configured")
    try:
        import redis
    except ImportError as exc:
        raise SelfEvolutionRedisVLError("redis package is not installed") from exc
    return redis.from_url(
        url,
        decode_responses=True,
        socket_connect_timeout=2.0,
        socket_timeout=10.0,
        retry_on_timeout=True,
        health_check_interval=30,
    )


def _search_index(kind: str):
    url = redis_url()
    if not url:
        raise SelfEvolutionRedisVLError("Redis URL not configured")
    try:
        from redisvl.index import SearchIndex
        from redisvl.schema import IndexSchema
    except ImportError as exc:
        raise SelfEvolutionRedisVLError("redisvl package is not installed") from exc

    dim = _embedding_dim()
    schema = IndexSchema.from_dict(
        {
            "index": {
                "name": _index_name(kind),
                "prefix": _key_prefix(kind),
                "storage_type": "hash",
            },
            "fields": [
                {"name": "doc_id", "type": "tag"},
                {"name": "kind", "type": "tag"},
                {"name": "path", "type": "text"},
                {"name": "title", "type": "text"},
                {"name": "text", "type": "text"},
                {
                    "name": "embedding",
                    "type": "vector",
                    "attrs": {
                        "algorithm": "hnsw",
                        "datatype": "float32",
                        "dims": dim,
                        "distance_metric": "cosine",
                    },
                },
            ],
        }
    )
    return SearchIndex(schema, redis_url=url)


def _ensure_index(kind: str):
    index = _search_index(kind)
    try:
        index.create(overwrite=False)
    except TypeError:
        index.create()
    except Exception as exc:
        text = str(exc).lower()
        if "already exists" not in text and "index already exists" not in text:
            raise
    return index


def _embed(texts: List[str]) -> List[List[float]]:
    if not texts:
        return []
    try:
        from modstore_server.embedding_service import embed_texts
        from modstore_server.runtime_async import run_coro_sync
    except Exception as exc:
        raise SelfEvolutionRedisVLError("embedding service unavailable") from exc
    try:
        vectors = run_coro_sync(embed_texts(texts))
    except Exception as exc:
        raise SelfEvolutionRedisVLError(f"embedding failed: {exc}") from exc
    if len(vectors) != len(texts):
        raise SelfEvolutionRedisVLError("embedding count mismatch")
    return vectors


def ensure_indexed(
    kind: str, docs: Sequence[Dict[str, Any]], fields: Sequence[str]
) -> Dict[str, Any]:
    if not enabled():
        return {"enabled": False, "ready": False, "reason": "disabled"}
    docs = [doc for doc in docs if isinstance(doc, dict)]
    sig = _signature(kind, docs, fields)
    client = _redis_client()
    sig_key = f"{SIGNATURE_PREFIX}{kind}"
    if client.get(sig_key) == sig:
        return {
            "chunk_count": len(docs),
            "enabled": True,
            "index_name": _index_name(kind),
            "ready": True,
            "rebuilt": False,
        }

    index = _ensure_index(kind)
    stale_keys = list(client.scan_iter(f"{_key_prefix(kind)}*"))
    if stale_keys:
        client.delete(*stale_keys)
    records: List[Dict[str, Any]] = []
    texts = [_doc_text(doc, fields) for doc in docs]
    vectors = _embed(texts) if texts else []
    now = int(time.time())
    for doc, text, vector in zip(docs, texts, vectors):
        doc_id = _doc_id(kind, doc)
        title = doc.get("symptom") or doc.get("pattern") or doc.get("summary") or doc_id
        records.append(
            {
                "doc_id": doc_id,
                "embedding": vector,
                "kind": kind,
                "path": str(doc.get("_path") or ""),
                "redis_key": f"{_key_prefix(kind)}{doc_id}",
                "text": text,
                "title": str(title)[:1000],
                "updated_at": now,
            }
        )
    try:
        if records:
            try:
                index.load(records, id_field="redis_key")
            except TypeError:
                index.load(records)
    except Exception as exc:
        raise SelfEvolutionRedisVLError(f"redisvl load failed: {exc}") from exc
    client.set(sig_key, sig)
    return {
        "chunk_count": len(records),
        "enabled": True,
        "index_name": _index_name(kind),
        "ready": True,
        "rebuilt": True,
    }


def query(
    *,
    kind: str,
    docs: Sequence[Dict[str, Any]],
    fields: Sequence[str],
    limit: int,
    query_text: str,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    if not enabled():
        return [], {"enabled": False, "ready": False, "reason": "disabled"}
    if not str(query_text or "").strip():
        return [], {"enabled": True, "ready": False, "reason": "empty_query"}
    index_status = ensure_indexed(kind, docs, fields)
    index = _ensure_index(kind)
    query_vector = _embed([query_text[:MAX_DOC_TEXT]])[0]
    try:
        from redisvl.query import VectorQuery
    except ImportError as exc:
        raise SelfEvolutionRedisVLError("redisvl VectorQuery is not available") from exc

    q = VectorQuery(
        vector=query_vector,
        vector_field_name="embedding",
        return_fields=["doc_id", "kind", "path", "title", "text", "vector_distance"],
        num_results=max(1, int(limit or 1)),
    )
    try:
        rows = index.query(q)
    except Exception as exc:
        raise SelfEvolutionRedisVLError(f"redisvl query failed: {exc}") from exc

    by_path = {str(doc.get("_path") or ""): doc for doc in docs if isinstance(doc, dict)}
    by_id = {_doc_id(kind, doc): doc for doc in docs if isinstance(doc, dict)}
    out: List[Dict[str, Any]] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        path = str(row.get("path") or "")
        doc_id = str(row.get("doc_id") or "")
        doc = by_path.get(path) or by_id.get(doc_id)
        if not isinstance(doc, dict):
            continue
        distance_raw = row.get("vector_distance")
        try:
            distance = float(distance_raw)
        except (TypeError, ValueError):
            distance = 1.0
        out.append(
            {
                **doc,
                "score": round(max(0.0, 1.0 - distance), 4),
                "search_backend": "redisvl",
                "vector_distance": distance,
            }
        )
    return out[: max(1, int(limit or 1))], {**index_status, "backend": "redisvl"}


def status() -> Dict[str, Any]:
    if not enabled():
        return {"enabled": False, "ready": False, "reason": "disabled"}
    if not redis_url():
        return {"enabled": True, "ready": False, "reason": "redis_url_missing"}
    try:
        client = _redis_client()
        client.ping()
        return {"enabled": True, "ready": True, "backend": "redisvl", "dim": _embedding_dim()}
    except Exception as exc:
        return {"enabled": True, "ready": False, "backend": "redisvl", "error": str(exc)}


__all__ = [
    "SelfEvolutionRedisVLError",
    "enabled",
    "ensure_indexed",
    "query",
    "redis_url",
    "status",
]
