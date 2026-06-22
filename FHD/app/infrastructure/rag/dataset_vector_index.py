from __future__ import annotations

import json
import math
import os
import sqlite3
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from app.infrastructure.rag.hybrid_retriever import RetrievedChunk
from app.utils.external_sqlite import connect_sqlite
from app.utils.operational_errors import RECOVERABLE_ERRORS
from app.utils.path_utils import get_app_data_dir


@runtime_checkable
class DatasetVectorIndexBackend(Protocol):
    backend_name: str

    def replace_dataset(self, dataset_id: str, chunks: list[RetrievedChunk]) -> int:
        raise NotImplementedError

    def delete_dataset(self, dataset_id: str) -> bool:
        raise NotImplementedError

    def query(
        self,
        dataset_id: str,
        query_vector: list[float],
        *,
        top_k: int = 50,
        tenant_id: str = "",
        version: str | int = "",
        metadata_filter: dict[str, Any] | None = None,
    ) -> list[RetrievedChunk]:
        raise NotImplementedError

    def status(self, dataset_id: str = "") -> dict[str, Any]:
        raise NotImplementedError


class DatasetVectorSQLiteIndex:
    """Dataset vector index backed by SQLite plus in-process cosine ranking."""

    backend_name = "sqlite_vector"

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(Path(db_path).expanduser().resolve())
        self._ensure_tables()

    @property
    def db_path(self) -> str:
        return self._db_path

    def _get_conn(self) -> sqlite3.Connection:
        conn = connect_sqlite(self._db_path)
        try:
            conn.execute("PRAGMA foreign_keys = ON")
        except RECOVERABLE_ERRORS:
            pass
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_tables(self) -> None:
        with self._get_conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS dataset_vector_indexes (
                    index_id TEXT PRIMARY KEY,
                    dataset_id TEXT NOT NULL,
                    backend TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    chunk_count INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS dataset_vector_chunks (
                    chunk_id TEXT PRIMARY KEY,
                    index_id TEXT NOT NULL REFERENCES dataset_vector_indexes(index_id) ON DELETE CASCADE,
                    dataset_id TEXT NOT NULL,
                    document_id TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    source TEXT NOT NULL,
                    document_version INTEGER NOT NULL,
                    version_label TEXT NOT NULL,
                    content TEXT NOT NULL,
                    embedding TEXT NOT NULL,
                    metadata TEXT NOT NULL,
                    source_url TEXT NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    char_start INTEGER NOT NULL,
                    char_end INTEGER NOT NULL,
                    page INTEGER,
                    created_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_dataset_vector_chunks_index_id ON dataset_vector_chunks(index_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_dataset_vector_chunks_tenant ON dataset_vector_chunks(index_id, tenant_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_dataset_vector_chunks_doc ON dataset_vector_chunks(index_id, document_id)"
            )
            conn.commit()

    def replace_dataset(self, dataset_id: str, chunks: list[RetrievedChunk]) -> int:
        index_id = _index_id(dataset_id)
        now = time.time()
        with self._get_conn() as conn:
            conn.execute(
                """
                INSERT INTO dataset_vector_indexes(index_id, dataset_id, backend, created_at, updated_at, chunk_count)
                VALUES(?, ?, ?, ?, ?, 0)
                ON CONFLICT(index_id) DO UPDATE SET
                    dataset_id = excluded.dataset_id,
                    backend = excluded.backend,
                    updated_at = excluded.updated_at
                """,
                (index_id, dataset_id, self.backend_name, now, now),
            )
            conn.execute("DELETE FROM dataset_vector_chunks WHERE index_id = ?", (index_id,))
            for chunk in chunks:
                metadata = dict(chunk.metadata or {})
                document_id = str(metadata.get("document_id") or "")
                row_id = _chunk_row_id(dataset_id, chunk)
                conn.execute(
                    """
                    INSERT INTO dataset_vector_chunks(
                        chunk_id,
                        index_id,
                        dataset_id,
                        document_id,
                        tenant_id,
                        source,
                        document_version,
                        version_label,
                        content,
                        embedding,
                        metadata,
                        source_url,
                        chunk_index,
                        char_start,
                        char_end,
                        page,
                        created_at
                    )
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row_id,
                        index_id,
                        dataset_id,
                        document_id,
                        str(metadata.get("tenant_id") or ""),
                        str(metadata.get("source") or chunk.source or ""),
                        int(metadata.get("document_version") or 1),
                        str(metadata.get("version_label") or ""),
                        chunk.text,
                        json.dumps(_embedding_from_metadata(metadata), ensure_ascii=False),
                        json.dumps(metadata, ensure_ascii=False),
                        chunk.source_url or "",
                        int(chunk.chunk_index or 0),
                        int(chunk.char_start or 0),
                        int(chunk.char_end or 0),
                        chunk.page,
                        now,
                    ),
                )
            conn.execute(
                """
                UPDATE dataset_vector_indexes
                SET chunk_count = ?, updated_at = ?
                WHERE index_id = ?
                """,
                (len(chunks), now, index_id),
            )
            conn.commit()
        return len(chunks)

    def delete_dataset(self, dataset_id: str) -> bool:
        index_id = _index_id(dataset_id)
        with self._get_conn() as conn:
            result = conn.execute(
                "DELETE FROM dataset_vector_indexes WHERE index_id = ?",
                (index_id,),
            )
            conn.commit()
        return bool(getattr(result, "rowcount", 0) > 0)

    def query(
        self,
        dataset_id: str,
        query_vector: list[float],
        *,
        top_k: int = 50,
        tenant_id: str = "",
        version: str | int = "",
        metadata_filter: dict[str, Any] | None = None,
    ) -> list[RetrievedChunk]:
        rows = self._select_rows(dataset_id, tenant_id=tenant_id)
        chunks = [_row_to_chunk(row) for row in rows]
        chunks = _filter_chunks(
            chunks,
            tenant_id=tenant_id,
            version=version,
            metadata_filter=metadata_filter or {},
        )
        query_terms = set(_tokenize_for_lexical(" ".join(str(v) for v in query_vector)))
        scored: list[RetrievedChunk] = []
        for chunk in chunks:
            metadata = dict(chunk.metadata or {})
            embedding = _embedding_from_metadata(metadata)
            vector_score = _cosine(query_vector, embedding) if embedding else 0.0
            lexical_score = _lexical_score(chunk.text, query_terms)
            scored.append(
                RetrievedChunk(
                    text=chunk.text,
                    score=float(vector_score + lexical_score),
                    source=self.backend_name,
                    chunk_index=chunk.chunk_index,
                    char_start=chunk.char_start,
                    char_end=chunk.char_end,
                    metadata=metadata,
                    source_url=chunk.source_url,
                    page=chunk.page,
                )
            )
        scored.sort(key=lambda item: item.score, reverse=True)
        return scored[: max(1, int(top_k or 1))]

    def status(self, dataset_id: str = "") -> dict[str, Any]:
        with self._get_conn() as conn:
            if dataset_id:
                row = conn.execute(
                    """
                    SELECT index_id, dataset_id, backend, created_at, updated_at, chunk_count
                    FROM dataset_vector_indexes
                    WHERE index_id = ?
                    """,
                    (_index_id(dataset_id),),
                ).fetchone()
                if row is None:
                    return {
                        "backend": self.backend_name,
                        "path": self._db_path,
                        "persistent": True,
                        "dataset_id": dataset_id,
                        "chunk_count": 0,
                        "index_exists": False,
                    }
                payload = dict(row)
                payload.update({"path": self._db_path, "persistent": True, "index_exists": True})
                return payload
            rows = conn.execute(
                """
                SELECT index_id, dataset_id, backend, created_at, updated_at, chunk_count
                FROM dataset_vector_indexes
                ORDER BY updated_at DESC
                """
            ).fetchall()
        return {
            "backend": self.backend_name,
            "path": self._db_path,
            "persistent": True,
            "index_count": len(rows),
            "indexes": [dict(row) for row in rows],
        }

    def _select_rows(self, dataset_id: str, *, tenant_id: str) -> list[sqlite3.Row]:
        index_id = _index_id(dataset_id)
        with self._get_conn() as conn:
            if tenant_id:
                rows = conn.execute(
                    """
                    SELECT *
                    FROM dataset_vector_chunks
                    WHERE index_id = ? AND tenant_id = ?
                    ORDER BY chunk_index ASC
                    """,
                    (index_id, tenant_id),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT *
                    FROM dataset_vector_chunks
                    WHERE index_id = ?
                    ORDER BY chunk_index ASC
                    """,
                    (index_id,),
                ).fetchall()
        return list(rows)


class DatasetVectorPgIndex:
    """Dataset vector index backed by PostgreSQL + pgvector."""

    backend_name = "pgvector"

    def __init__(self, database_url: str, *, dimension: int = 256) -> None:
        configured_url = str(database_url or "").strip()
        if not configured_url:
            raise ValueError("DATASET_RAG_PGVECTOR_DATABASE_URL is required")
        self._database_url = configured_url
        self._dimension = max(1, int(dimension or 256))
        self._engine: Engine = create_engine(configured_url, pool_pre_ping=True, echo=False)
        self._ensure_tables()

    @property
    def database_url(self) -> str:
        return self._database_url

    @property
    def dimension(self) -> int:
        return self._dimension

    def _ensure_tables(self) -> None:
        with self._engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS dataset_vector_indexes (
                        index_id TEXT PRIMARY KEY,
                        dataset_id TEXT NOT NULL,
                        backend TEXT NOT NULL,
                        created_at DOUBLE PRECISION NOT NULL,
                        updated_at DOUBLE PRECISION NOT NULL,
                        chunk_count INTEGER NOT NULL DEFAULT 0
                    )
                    """
                )
            )
            dimension = int(self._dimension)
            conn.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS dataset_vector_chunks ("
                    "chunk_id TEXT PRIMARY KEY, "
                    "index_id TEXT NOT NULL REFERENCES dataset_vector_indexes(index_id) ON DELETE CASCADE, "
                    "dataset_id TEXT NOT NULL, "
                    "document_id TEXT NOT NULL, "
                    "tenant_id TEXT NOT NULL, "
                    "source TEXT NOT NULL, "
                    "document_version INTEGER NOT NULL, "
                    "version_label TEXT NOT NULL, "
                    "content TEXT NOT NULL, "
                    "embedding vector(" + str(dimension) + ") NOT NULL, "
                    "metadata JSONB NOT NULL, "
                    "source_url TEXT NOT NULL, "
                    "chunk_index INTEGER NOT NULL, "
                    "char_start INTEGER NOT NULL, "
                    "char_end INTEGER NOT NULL, "
                    "page INTEGER, "
                    "created_at DOUBLE PRECISION NOT NULL"
                    ")"
                )
            )
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_dataset_vector_chunks_index_id "
                    "ON dataset_vector_chunks(index_id)"
                )
            )
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_dataset_vector_chunks_tenant "
                    "ON dataset_vector_chunks(index_id, tenant_id)"
                )
            )
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_dataset_vector_chunks_embedding "
                    "ON dataset_vector_chunks USING ivfflat (embedding vector_cosine_ops)"
                )
            )

    def replace_dataset(self, dataset_id: str, chunks: list[RetrievedChunk]) -> int:
        index_id = _index_id(dataset_id)
        now = time.time()
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO dataset_vector_indexes(index_id, dataset_id, backend, created_at, updated_at, chunk_count)
                    VALUES(:index_id, :dataset_id, :backend, :created_at, :updated_at, 0)
                    ON CONFLICT(index_id) DO UPDATE
                    SET dataset_id = EXCLUDED.dataset_id,
                        backend = EXCLUDED.backend,
                        updated_at = EXCLUDED.updated_at
                    """
                ),
                {
                    "index_id": index_id,
                    "dataset_id": dataset_id,
                    "backend": self.backend_name,
                    "created_at": now,
                    "updated_at": now,
                },
            )
            conn.execute(
                text("DELETE FROM dataset_vector_chunks WHERE index_id = :index_id"),
                {"index_id": index_id},
            )
            for chunk in chunks:
                metadata = dict(chunk.metadata or {})
                embedding = _embedding_from_metadata(metadata)
                if not embedding:
                    continue
                conn.execute(
                    text(
                        """
                        INSERT INTO dataset_vector_chunks(
                            chunk_id,
                            index_id,
                            dataset_id,
                            document_id,
                            tenant_id,
                            source,
                            document_version,
                            version_label,
                            content,
                            embedding,
                            metadata,
                            source_url,
                            chunk_index,
                            char_start,
                            char_end,
                            page,
                            created_at
                        )
                        VALUES(
                            :chunk_id,
                            :index_id,
                            :dataset_id,
                            :document_id,
                            :tenant_id,
                            :source,
                            :document_version,
                            :version_label,
                            :content,
                            CAST(:embedding AS vector),
                            CAST(:metadata AS jsonb),
                            :source_url,
                            :chunk_index,
                            :char_start,
                            :char_end,
                            :page,
                            :created_at
                        )
                        """
                    ),
                    {
                        "chunk_id": _chunk_row_id(dataset_id, chunk),
                        "index_id": index_id,
                        "dataset_id": dataset_id,
                        "document_id": str(metadata.get("document_id") or ""),
                        "tenant_id": str(metadata.get("tenant_id") or ""),
                        "source": str(metadata.get("source") or chunk.source or ""),
                        "document_version": int(metadata.get("document_version") or 1),
                        "version_label": str(metadata.get("version_label") or ""),
                        "content": chunk.text,
                        "embedding": json.dumps(embedding, ensure_ascii=False),
                        "metadata": json.dumps(metadata, ensure_ascii=False),
                        "source_url": chunk.source_url or "",
                        "chunk_index": int(chunk.chunk_index or 0),
                        "char_start": int(chunk.char_start or 0),
                        "char_end": int(chunk.char_end or 0),
                        "page": chunk.page,
                        "created_at": now,
                    },
                )
            conn.execute(
                text(
                    """
                    UPDATE dataset_vector_indexes
                    SET chunk_count = (
                        SELECT COUNT(*) FROM dataset_vector_chunks WHERE index_id = :index_id
                    ),
                    updated_at = :updated_at
                    WHERE index_id = :index_id
                    """
                ),
                {"index_id": index_id, "updated_at": now},
            )
            row = (
                conn.execute(
                    text(
                        "SELECT chunk_count FROM dataset_vector_indexes WHERE index_id = :index_id"
                    ),
                    {"index_id": index_id},
                )
                .mappings()
                .first()
            )
        return int((row or {}).get("chunk_count") or 0)

    def delete_dataset(self, dataset_id: str) -> bool:
        index_id = _index_id(dataset_id)
        with self._engine.begin() as conn:
            result = conn.execute(
                text("DELETE FROM dataset_vector_indexes WHERE index_id = :index_id"),
                {"index_id": index_id},
            )
        return bool(getattr(result, "rowcount", 0) > 0)

    def query(
        self,
        dataset_id: str,
        query_vector: list[float],
        *,
        top_k: int = 50,
        tenant_id: str = "",
        version: str | int = "",
        metadata_filter: dict[str, Any] | None = None,
    ) -> list[RetrievedChunk]:
        index_id = _index_id(dataset_id)
        clauses = ["index_id = :index_id"]
        params: dict[str, Any] = {
            "index_id": index_id,
            "query_vector": json.dumps([float(item) for item in query_vector], ensure_ascii=False),
            "top_k": max(1, int(top_k or 1)),
        }
        if tenant_id:
            clauses.append("tenant_id = :tenant_id")
            params["tenant_id"] = tenant_id
        version_text = str(version or "").strip()
        if version_text and version_text.lower() != "latest":
            normalized = version_text[1:] if version_text.lower().startswith("v") else version_text
            clauses.append(
                "(document_version = :document_version OR version_label = :version_label)"
            )
            params["document_version"] = int(normalized) if normalized.isdigit() else -1
            params["version_label"] = version_text
        post_filter: dict[str, Any] = {}
        for idx, (key, expected) in enumerate((metadata_filter or {}).items()):
            if isinstance(expected, (dict, list)):
                post_filter[str(key)] = expected
                continue
            param = f"metadata_filter_{idx}"
            clauses.append(f"metadata ->> :metadata_key_{idx} = :{param}")
            params[f"metadata_key_{idx}"] = str(key)
            params[param] = str(expected)
        with self._engine.begin() as conn:
            where_clause = " AND ".join(clauses)
            rows = (
                conn.execute(
                    text(
                        "SELECT content, source, source_url, chunk_index, char_start, char_end, "
                        "page, metadata, "
                        "1 - (embedding <=> CAST(:query_vector AS vector)) AS score "
                        "FROM dataset_vector_chunks "
                        "WHERE " + where_clause + " "
                        "ORDER BY embedding <=> CAST(:query_vector AS vector) "
                        "LIMIT :top_k"
                    ),
                    params,
                )
                .mappings()
                .all()
            )
        chunks = [_pg_row_to_chunk(row) for row in rows]
        if version_text.lower() == "latest" or post_filter:
            chunks = _filter_chunks(
                chunks,
                tenant_id=tenant_id,
                version=version,
                metadata_filter=post_filter,
            )
        return chunks

    def status(self, dataset_id: str = "") -> dict[str, Any]:
        with self._engine.begin() as conn:
            if dataset_id:
                row = (
                    conn.execute(
                        text(
                            """
                            SELECT index_id, dataset_id, backend, created_at, updated_at, chunk_count
                            FROM dataset_vector_indexes
                            WHERE index_id = :index_id
                            """
                        ),
                        {"index_id": _index_id(dataset_id)},
                    )
                    .mappings()
                    .first()
                )
                if row is None:
                    return {
                        "backend": self.backend_name,
                        "persistent": True,
                        "dataset_id": dataset_id,
                        "chunk_count": 0,
                        "index_exists": False,
                        "dimension": self._dimension,
                    }
                payload = dict(row)
                payload.update(
                    {"persistent": True, "index_exists": True, "dimension": self._dimension}
                )
                return payload
            rows = (
                conn.execute(
                    text(
                        """
                        SELECT index_id, dataset_id, backend, created_at, updated_at, chunk_count
                        FROM dataset_vector_indexes
                        ORDER BY updated_at DESC
                        """
                    )
                )
                .mappings()
                .all()
            )
        return {
            "backend": self.backend_name,
            "persistent": True,
            "dimension": self._dimension,
            "index_count": len(rows),
            "indexes": [dict(row) for row in rows],
        }


def default_dataset_vector_index_path(storage_path: str | Path | None = None) -> Path:
    configured = (
        os.environ.get("DATASET_RAG_VECTOR_INDEX_PATH")
        or os.environ.get("XCAGI_DATASET_RAG_VECTOR_INDEX_PATH")
        or ""
    ).strip()
    if configured:
        return Path(configured).expanduser().resolve()
    if storage_path:
        path = Path(storage_path).expanduser().resolve()
        return path.with_suffix(path.suffix + ".vectors.sqlite")
    return Path(get_app_data_dir()).resolve() / "dataset_rag" / "dataset_vectors.sqlite"


def _index_id(dataset_id: str) -> str:
    return f"dataset:{dataset_id}"


def _chunk_row_id(dataset_id: str, chunk: RetrievedChunk) -> str:
    metadata = dict(chunk.metadata or {})
    raw = "\0".join(
        [
            dataset_id,
            str(metadata.get("document_id") or ""),
            str(metadata.get("tenant_id") or ""),
            str(metadata.get("document_version") or ""),
            str(chunk.chunk_index),
            str(chunk.char_start),
            str(chunk.char_end),
        ]
    )
    digest = _sha256(raw)
    return f"dvc_{digest[:24]}"


def _sha256(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _row_to_chunk(row: sqlite3.Row) -> RetrievedChunk:
    metadata = _load_json_object(row["metadata"])
    return RetrievedChunk(
        text=str(row["content"] or ""),
        score=0.0,
        source=str(row["source"] or ""),
        chunk_index=int(row["chunk_index"] or 0),
        char_start=int(row["char_start"] or 0),
        char_end=int(row["char_end"] or 0),
        metadata=metadata,
        source_url=str(row["source_url"] or ""),
        page=row["page"] if isinstance(row["page"], int) else None,
    )


def _pg_row_to_chunk(row: Any) -> RetrievedChunk:
    metadata = _load_json_object(row.get("metadata", {}))
    return RetrievedChunk(
        text=str(row["content"] or ""),
        score=float(row["score"] or 0.0),
        source=str(row["source"] or "pgvector"),
        chunk_index=int(row["chunk_index"] or 0),
        char_start=int(row["char_start"] or 0),
        char_end=int(row["char_end"] or 0),
        metadata=metadata,
        source_url=str(row["source_url"] or ""),
        page=row["page"] if isinstance(row["page"], int) else None,
    )


def _load_json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    try:
        parsed = json.loads(str(value or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def _embedding_from_metadata(metadata: dict[str, Any]) -> list[float]:
    embedding = metadata.get("_embedding")
    if not isinstance(embedding, list):
        return []
    try:
        return [float(item) for item in embedding]
    except (TypeError, ValueError):
        return []


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def _filter_chunks(
    chunks: list[RetrievedChunk],
    *,
    tenant_id: str,
    version: str | int,
    metadata_filter: dict[str, Any],
) -> list[RetrievedChunk]:
    selected = list(chunks)
    if tenant_id:
        selected = [
            chunk
            for chunk in selected
            if str((chunk.metadata or {}).get("tenant_id") or "") == tenant_id
        ]
    if metadata_filter:
        selected = [
            chunk for chunk in selected if _metadata_matches(chunk.metadata or {}, metadata_filter)
        ]
    version_text = str(version or "").strip()
    if not version_text:
        return selected
    if version_text.lower() == "latest":
        latest_by_scope: dict[tuple[str, str], int] = {}
        for chunk in selected:
            metadata = chunk.metadata or {}
            scope = (
                str(metadata.get("tenant_id") or ""),
                str(metadata.get("source") or chunk.source or ""),
            )
            latest_by_scope[scope] = max(
                latest_by_scope.get(scope, 0),
                int(metadata.get("document_version") or 1),
            )
        return [
            chunk
            for chunk in selected
            if int((chunk.metadata or {}).get("document_version") or 1)
            == latest_by_scope.get(
                (
                    str((chunk.metadata or {}).get("tenant_id") or ""),
                    str((chunk.metadata or {}).get("source") or chunk.source or ""),
                ),
                1,
            )
        ]
    normalized = version_text[1:] if version_text.lower().startswith("v") else version_text
    return [
        chunk
        for chunk in selected
        if str((chunk.metadata or {}).get("document_version") or "") == normalized
        or str((chunk.metadata or {}).get("version_label") or "") == version_text
    ]


def _metadata_matches(metadata: dict[str, Any], metadata_filter: dict[str, Any]) -> bool:
    for key, expected in metadata_filter.items():
        actual = metadata.get(str(key))
        if isinstance(expected, list):
            if str(actual) not in {str(item) for item in expected}:
                return False
        elif isinstance(expected, dict):
            if not isinstance(actual, dict):
                return False
            for nested_key, nested_expected in expected.items():
                if str(actual.get(str(nested_key))) != str(nested_expected):
                    return False
        elif str(actual) != str(expected):
            return False
    return True


def _lexical_score(text: str, query_terms: Iterable[str]) -> float:
    terms = set(query_terms)
    if not terms:
        return 0.0
    text_terms = set(_tokenize_for_lexical(text))
    return len(terms & text_terms) / max(1, len(terms))


def _tokenize_for_lexical(text: str) -> list[str]:
    cleaned = "".join(ch.lower() if ch.isalnum() else " " for ch in text)
    return [part for part in cleaned.split() if part]
