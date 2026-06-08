"""把存量 Redis Stack 知识库迁移到统一 Chroma 引擎。

用法（在 modstore_server 根目录下执行）::

    # 只读，先看会迁移哪些用户/文档
    python scripts/migrate_kb_redis_to_chroma.py --dry-run

    # 真实迁移（幂等：可重复跑）
    python scripts/migrate_kb_redis_to_chroma.py

    # 指定 redis URL（不依赖环境变量）
    python scripts/migrate_kb_redis_to_chroma.py \
        --redis-url redis://:password@host:6379

环境变量：
    MODSTORE_VECTOR_REDIS_URL / REDIS_URL    存量 Redis Stack 地址
    MODSTORE_VECTOR_DB_DIR                   Chroma 持久化目录（默认 modstore_server/data/chroma）
    MODSTORE_DB_PATH                         SQLite/Postgres 元数据库
"""

from __future__ import annotations

import argparse
import logging
import os
import struct
import sys
from typing import Any, Dict, Iterable, List, Tuple

logger = logging.getLogger("migrate_kb")


def _decode_hash(row: Dict[Any, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k, v in (row or {}).items():
        ks = k.decode("utf-8", errors="ignore") if isinstance(k, bytes) else str(k)
        if ks == "embedding" and isinstance(v, (bytes, bytearray)):
            try:
                n = len(v) // 4
                out[ks] = list(struct.unpack(f"{n}f", bytes(v)))
            except Exception:  # noqa: BLE001
                out[ks] = []
        elif isinstance(v, bytes):
            out[ks] = v.decode("utf-8", errors="ignore")
        else:
            out[ks] = v
    return out


def _scan_user_chunks(redis_client) -> Iterable[Tuple[int, str, List[Dict[str, Any]]]]:
    """逐用户、逐 doc_id 聚合 chunks。yield (user_id, doc_id, [chunk_hash, ...])。"""
    grouped: Dict[Tuple[int, str], List[Dict[str, Any]]] = {}
    chunk_prefix = b"modstore:kb:chunk:"
    for key in redis_client.scan_iter(match=b"modstore:kb:chunk:*", count=200):
        if not key.startswith(chunk_prefix):
            continue
        suffix = key[len(chunk_prefix):].decode("utf-8", errors="ignore")
        parts = suffix.split(":")
        if len(parts) < 3:
            continue
        try:
            user_id = int(parts[0])
        except ValueError:
            continue
        doc_id = parts[1]
        try:
            chunk_idx = int(parts[2])
        except ValueError:
            chunk_idx = 0
        try:
            data = _decode_hash(redis_client.hgetall(key))
        except Exception as e:  # noqa: BLE001
            logger.warning("读取 %s 失败: %s", key, e)
            continue
        data["__chunk_index__"] = chunk_idx
        grouped.setdefault((user_id, doc_id), []).append(data)
    for (uid, doc_id), rows in grouped.items():
        rows.sort(key=lambda r: int(r.get("__chunk_index__") or r.get("chunk_index") or 0))
        yield uid, doc_id, rows


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Redis Stack KB → Chroma 迁移")
    parser.add_argument("--redis-url", default="", help="覆盖 REDIS_URL")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只统计/打印不写入",
    )
    parser.add_argument(
        "--limit-docs",
        type=int,
        default=0,
        help="仅迁移前 N 个文档（调试用）",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.redis_url:
        os.environ["MODSTORE_VECTOR_REDIS_URL"] = args.redis_url

    try:
        from modstore_server import vector_engine
        from modstore_server.knowledge_vector_store_redis import (
            CHUNK_PREFIX,
            DOC_PREFIX,
            USER_DOCS_PREFIX,
            INDEX_NAME,
            get_redis,
            redis_url,
            vector_dim,
        )
        from modstore_server.knowledge_vector_store import (
            DEFAULT_USER_COLLECTION_NAME,
            _ensure_user_default_collection,
        )
        from modstore_server.models import (
            KnowledgeDocument,
            get_session_factory,
            init_db,
        )
    except ImportError as e:
        logger.error("无法导入 modstore_server（确认在仓库根目录运行）: %s", e)
        return 2

    if not redis_url():
        logger.error("未配置 MODSTORE_VECTOR_REDIS_URL / REDIS_URL；无法读取存量数据")
        return 2

    logger.info("Redis 源: %s", redis_url())
    logger.info("Chroma 目标: %s", vector_engine.vector_db_dir())
    if args.dry_run:
        logger.info("DRY-RUN 模式：只统计、不写入")

    init_db()
    redis_client = get_redis()

    sf = get_session_factory()
    total_docs = 0
    total_chunks = 0
    seen_doc_ids: set[Tuple[int, str]] = set()

    for user_id, doc_id, chunks in _scan_user_chunks(redis_client):
        if args.limit_docs and total_docs >= args.limit_docs:
            break
        if not chunks:
            continue
        seen_doc_ids.add((user_id, doc_id))
        total_docs += 1
        total_chunks += len(chunks)

        if args.dry_run:
            logger.info(
                "[dry-run] user=%s doc=%s chunks=%d filename=%s",
                user_id,
                doc_id,
                len(chunks),
                str(chunks[0].get("filename") or ""),
            )
            continue

        with sf() as session:
            coll = _ensure_user_default_collection(session, int(user_id))
            ids: List[str] = []
            embeddings: List[List[float]] = []
            documents: List[str] = []
            metadatas: List[Dict[str, Any]] = []
            for c in chunks:
                emb = c.get("embedding") or []
                if not emb:
                    continue
                cid = str(c.get("chunk_id") or f"{doc_id}:{c.get('__chunk_index__', 0)}")
                ids.append(cid)
                embeddings.append([float(x) for x in emb])
                documents.append(str(c.get("content") or ""))
                meta: Dict[str, Any] = {
                    "user_id": str(int(user_id)),
                    "doc_id": str(doc_id),
                    "chunk_id": cid,
                    "filename": str(c.get("filename") or ""),
                    "chunk_index": int(c.get("__chunk_index__") or 0),
                }
                page_no = c.get("page_no")
                try:
                    if page_no not in (None, "", 0):
                        meta["page_no"] = int(page_no)
                except Exception:  # noqa: BLE001
                    pass
                created_at_v = c.get("created_at")
                try:
                    if created_at_v not in (None, "", 0):
                        meta["created_at"] = int(created_at_v)
                except Exception:  # noqa: BLE001
                    pass
                metadatas.append(meta)

            if not ids:
                logger.warning("user=%s doc=%s 没有可迁移的 chunk（embedding 缺失）", user_id, doc_id)
                continue

            try:
                vector_engine.delete(
                    vector_engine.kb_collection_name(int(coll.id)),
                    where={"doc_id": str(doc_id)},
                )
            except Exception:  # noqa: BLE001
                pass
            vector_engine.upsert(
                vector_engine.kb_collection_name(int(coll.id)),
                ids=ids,
                embeddings=embeddings,
                documents=documents,
                metadatas=metadatas,
            )

            doc_row = (
                session.query(KnowledgeDocument)
                .filter(
                    KnowledgeDocument.collection_id == coll.id,
                    KnowledgeDocument.doc_id == str(doc_id),
                )
                .first()
            )
            filename = str(chunks[0].get("filename") or "")
            if doc_row is None:
                doc_row = KnowledgeDocument(
                    collection_id=coll.id,
                    doc_id=str(doc_id),
                    filename=filename,
                    size_bytes=0,
                    chunk_count=len(ids),
                )
                session.add(doc_row)
            else:
                doc_row.filename = filename
                doc_row.chunk_count = len(ids)

            chunk_rows = (
                session.query(KnowledgeDocument.chunk_count)
                .filter(KnowledgeDocument.collection_id == coll.id)
                .all()
            )
            coll.chunk_count = sum(int(r[0] or 0) for r in chunk_rows)
            session.commit()
            logger.info(
                "[migrated] user=%s doc=%s chunks=%d collection_id=%s",
                user_id,
                doc_id,
                len(ids),
                coll.id,
            )

    logger.info(
        "完成: docs=%d chunks=%d unique_docs=%d %s",
        total_docs,
        total_chunks,
        len(seen_doc_ids),
        "(dry-run)" if args.dry_run else "",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
