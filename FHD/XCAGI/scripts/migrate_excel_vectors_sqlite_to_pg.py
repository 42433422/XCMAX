#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
将本地 SQLite excel_vectors.db 中的索引与向量块复制到 PostgreSQL（pgvector）。

用法（在 XCAGI 仓库根目录）:
  python scripts/migrate_excel_vectors_sqlite_to_pg.py --sqlite path/to/excel_vectors.db

环境变量:
  DATABASE_URL 或 VECTOR_DB_URL — 目标 PostgreSQL（须已安装 vector 扩展且存在 excel_vector_* 表，
  通常由 alembic f3b2c1d9e4a7 或 PgVectorStore 首次连接创建）。

说明:
  - 默认按 chunk_id 覆盖写入（先删目标 index_id 下已有块再插入，与 PgVectorStore.upsert_chunks 行为类似）。
  - 大库请分批或改用 COPY。
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from typing import Any, Dict, List

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(_ROOT, ".env"))
except ImportError:
    pass


def _fetch_sqlite_indexes(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    cur = conn.execute(
        "SELECT index_id, name, source_file, created_at, updated_at, chunk_count FROM excel_vector_indexes"
    )
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def _fetch_chunks(conn: sqlite3.Connection, index_id: str) -> List[Dict[str, Any]]:
    cur = conn.execute(
        "SELECT chunk_id, index_id, content, embedding, metadata, created_at "
        "FROM excel_vector_chunks WHERE index_id = ?",
        (index_id,),
    )
    cols = [d[0] for d in cur.description]
    out: List[Dict[str, Any]] = []
    for row in cur.fetchall():
        out.append(dict(zip(cols, row)))
    return out


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--sqlite", required=True, help="Path to excel_vectors.db (SQLite)")
    args = p.parse_args()
    sqlite_path = os.path.abspath(args.sqlite)
    if not os.path.isfile(sqlite_path):
        print(f"ERROR: file not found: {sqlite_path}", file=sys.stderr)
        return 1

    dest = (os.environ.get("VECTOR_DB_URL") or os.environ.get("DATABASE_URL") or "").strip()
    if not dest or not (dest.startswith("postgresql") or dest.startswith("postgres")):
        print("ERROR: set VECTOR_DB_URL or DATABASE_URL to PostgreSQL.", file=sys.stderr)
        return 1

    from sqlalchemy import create_engine, text

    pg = create_engine(dest, pool_pre_ping=True)
    with pg.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS excel_vector_indexes (
                    index_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    source_file TEXT NOT NULL,
                    created_at DOUBLE PRECISION NOT NULL,
                    updated_at DOUBLE PRECISION NOT NULL,
                    chunk_count INTEGER NOT NULL DEFAULT 0
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS excel_vector_chunks (
                    chunk_id TEXT PRIMARY KEY,
                    index_id TEXT NOT NULL REFERENCES excel_vector_indexes(index_id) ON DELETE CASCADE,
                    content TEXT NOT NULL,
                    embedding vector(256) NOT NULL,
                    metadata JSONB NOT NULL,
                    created_at DOUBLE PRECISION NOT NULL
                )
                """
            )
        )

    with sqlite3.connect(sqlite_path) as sl:
        sl.row_factory = sqlite3.Row
        indexes = _fetch_sqlite_indexes(sl)
        if not indexes:
            print("No indexes in SQLite; nothing to do.")
            return 0

        for idx in indexes:
            index_id = str(idx["index_id"])
            chunks = _fetch_chunks(sl, index_id)
            now = time.time()
            with pg.begin() as conn:
                conn.execute(
                    text(
                        """
                        INSERT INTO excel_vector_indexes(index_id, name, source_file, created_at, updated_at, chunk_count)
                        VALUES(:index_id, :name, :source_file, :created_at, :updated_at, :chunk_count)
                        ON CONFLICT(index_id) DO UPDATE
                        SET name = EXCLUDED.name,
                            source_file = EXCLUDED.source_file,
                            updated_at = EXCLUDED.updated_at,
                            chunk_count = EXCLUDED.chunk_count
                        """
                    ),
                    {
                        "index_id": index_id,
                        "name": idx.get("name") or index_id,
                        "source_file": idx.get("source_file") or "",
                        "created_at": float(idx.get("created_at") or now),
                        "updated_at": float(idx.get("updated_at") or now),
                        "chunk_count": int(idx.get("chunk_count") or len(chunks)),
                    },
                )
                conn.execute(text("DELETE FROM excel_vector_chunks WHERE index_id = :i"), {"i": index_id})
                for ch in chunks:
                    emb_raw = ch.get("embedding")
                    if isinstance(emb_raw, (bytes, memoryview)):
                        emb_raw = emb_raw.decode("utf-8", errors="replace")
                    if isinstance(emb_raw, str):
                        vec = json.loads(emb_raw)
                    else:
                        vec = list(emb_raw)
                    meta = ch.get("metadata")
                    if isinstance(meta, str):
                        meta_obj: Any = json.loads(meta)
                    else:
                        meta_obj = meta or {}
                    conn.execute(
                        text(
                            """
                            INSERT INTO excel_vector_chunks(chunk_id, index_id, content, embedding, metadata, created_at)
                            VALUES(:chunk_id, :index_id, :content, CAST(:embedding AS vector), CAST(:metadata AS jsonb), :created_at)
                            """
                        ),
                        {
                            "chunk_id": str(ch["chunk_id"]),
                            "index_id": index_id,
                            "content": str(ch.get("content") or ""),
                            "embedding": json.dumps(vec, ensure_ascii=False),
                            "metadata": json.dumps(meta_obj, ensure_ascii=False),
                            "created_at": float(ch.get("created_at") or now),
                        },
                    )
            print(f"Migrated index {index_id}: {len(chunks)} chunks")

    pg.dispose()
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
