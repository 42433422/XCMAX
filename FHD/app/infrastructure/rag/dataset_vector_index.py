from __future__ import annotations

import heapq
import json
import logging
import math
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from typing import Any, Protocol, cast, runtime_checkable

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from app.infrastructure.rag.dataset_vector_index_utils import (
    _chunk_row_id as _chunk_row_id,
)
from app.infrastructure.rag.dataset_vector_index_utils import (
    _cosine as _cosine,
)
from app.infrastructure.rag.dataset_vector_index_utils import (
    _embedding_from_metadata as _embedding_from_metadata,
)
from app.infrastructure.rag.dataset_vector_index_utils import (
    _filter_chunks as _filter_chunks,
)
from app.infrastructure.rag.dataset_vector_index_utils import (
    _index_id as _index_id,
)
from app.infrastructure.rag.dataset_vector_index_utils import (
    _is_rebuildable_index_error as _is_rebuildable_index_error,
)
from app.infrastructure.rag.dataset_vector_index_utils import (
    _lexical_score as _lexical_score,
)
from app.infrastructure.rag.dataset_vector_index_utils import (
    _load_json_object as _load_json_object,
)
from app.infrastructure.rag.dataset_vector_index_utils import (
    _metadata_matches as _metadata_matches,
)
from app.infrastructure.rag.dataset_vector_index_utils import (
    _pg_row_to_chunk as _pg_row_to_chunk,
)
from app.infrastructure.rag.dataset_vector_index_utils import (
    _row_to_chunk as _row_to_chunk,
)
from app.infrastructure.rag.dataset_vector_index_utils import (
    _sha256 as _sha256,
)
from app.infrastructure.rag.dataset_vector_index_utils import (
    _tokenize_for_lexical as _tokenize_for_lexical,
)
from app.infrastructure.rag.dataset_vector_index_utils import (
    default_dataset_vector_index_path as default_dataset_vector_index_path,
)
from app.infrastructure.rag.hybrid_retriever import RetrievedChunk
from app.utils.operational_errors import RECOVERABLE_ERRORS
from app.utils.path_io.external_sqlite import connect_sqlite

logger = logging.getLogger(__name__)


class DatasetVectorSQLiteIndex:
    """Dataset vector index backed by SQLite plus in-process cosine ranking."""

    backend_name = "sqlite_vector"

    def __init__(self, db_path: str | Path) -> None:
        path = Path(db_path).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = str(path)
        try:
            self._ensure_tables()
        except sqlite3.DatabaseError as exc:
            if not path.is_file() or not _is_rebuildable_index_error(exc):
                raise
            backup_path = path.with_name(f"{path.name}.incompatible-{time.time_ns()}.bak")
            path.replace(backup_path)
            logger.warning(
                "Archived incompatible dataset vector index %s to %s; rebuilding from source data",
                path,
                backup_path,
            )
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
        return cast(sqlite3.Connection, conn)

    def _ensure_tables(self) -> None:
        with closing(self._get_conn()) as conn:
            conn.execute(
                "\n                CREATE TABLE IF NOT EXISTS dataset_vector_indexes (\n                    index_id TEXT PRIMARY KEY,\n                    dataset_id TEXT NOT NULL,\n                    backend TEXT NOT NULL,\n                    created_at REAL NOT NULL,\n                    updated_at REAL NOT NULL,\n                    chunk_count INTEGER NOT NULL DEFAULT 0\n                )\n                "
            )
            conn.execute(
                "\n                CREATE TABLE IF NOT EXISTS dataset_vector_chunks (\n                    chunk_id TEXT PRIMARY KEY,\n                    index_id TEXT NOT NULL REFERENCES dataset_vector_indexes(index_id) ON DELETE CASCADE,\n                    dataset_id TEXT NOT NULL,\n                    document_id TEXT NOT NULL,\n                    tenant_id TEXT NOT NULL,\n                    source TEXT NOT NULL,\n                    document_version INTEGER NOT NULL,\n                    version_label TEXT NOT NULL,\n                    content TEXT NOT NULL,\n                    embedding TEXT NOT NULL,\n                    metadata TEXT NOT NULL,\n                    source_url TEXT NOT NULL,\n                    chunk_index INTEGER NOT NULL,\n                    char_start INTEGER NOT NULL,\n                    char_end INTEGER NOT NULL,\n                    page INTEGER,\n                    created_at REAL NOT NULL\n                )\n                "
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
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_dataset_vector_chunks_tenant_order "
                "ON dataset_vector_chunks(index_id, tenant_id, chunk_index)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_dataset_vector_chunks_order "
                "ON dataset_vector_chunks(index_id, chunk_index)"
            )
            conn.commit()

    def replace_dataset(self, dataset_id: str, chunks: list[RetrievedChunk]) -> int:
        index_id = _index_id(dataset_id)
        now = time.time()
        with closing(self._get_conn()) as conn:
            conn.execute(
                "\n                INSERT INTO dataset_vector_indexes(index_id, dataset_id, backend, created_at, updated_at, chunk_count)\n                VALUES(?, ?, ?, ?, ?, 0)\n                ON CONFLICT(index_id) DO UPDATE SET\n                    dataset_id = excluded.dataset_id,\n                    backend = excluded.backend,\n                    updated_at = excluded.updated_at\n                ",
                (index_id, dataset_id, self.backend_name, now, now),
            )
            conn.execute("DELETE FROM dataset_vector_chunks WHERE index_id = ?", (index_id,))
            for chunk in chunks:
                metadata = dict(chunk.metadata or {})
                embedding = _embedding_from_metadata(metadata)
                if not all(math.isfinite(value) for value in embedding):
                    raise ValueError("Vector embeddings must contain finite numbers")
                document_id = str(metadata.get("document_id") or "")
                row_id = _chunk_row_id(dataset_id, chunk)
                conn.execute(
                    "\n                    INSERT INTO dataset_vector_chunks(\n                        chunk_id,\n                        index_id,\n                        dataset_id,\n                        document_id,\n                        tenant_id,\n                        source,\n                        document_version,\n                        version_label,\n                        content,\n                        embedding,\n                        metadata,\n                        source_url,\n                        chunk_index,\n                        char_start,\n                        char_end,\n                        page,\n                        created_at\n                    )\n                    VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)\n                    ",
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
                        json.dumps(embedding, ensure_ascii=False),
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
                "\n                UPDATE dataset_vector_indexes\n                SET chunk_count = ?, updated_at = ?\n                WHERE index_id = ?\n                ",
                (len(chunks), now, index_id),
            )
            conn.commit()
        return len(chunks)

    def delete_dataset(self, dataset_id: str) -> bool:
        index_id = _index_id(dataset_id)
        with closing(self._get_conn()) as conn:
            result = conn.execute(
                "DELETE FROM dataset_vector_indexes WHERE index_id = ?", (index_id,)
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
        if not all(math.isfinite(value) for value in query_vector):
            raise ValueError("Query vectors must contain finite numbers")
        limit = max(1, int(top_k or 1))
        query_terms = set(_tokenize_for_lexical(" ".join(str(v) for v in query_vector)))
        selected: list[tuple[float, int, RetrievedChunk]] = []
        latest = str(version or "").strip().lower() == "latest"
        with closing(self._get_conn()) as conn:
            # One read snapshot covers both version selection and ranking. Temporary
            # candidates are disk-backed even when every row has a distinct source.
            conn.execute("PRAGMA temp_store = FILE")
            conn.execute("PRAGMA temp.cache_size = -2048")
            conn.execute("BEGIN")
            if latest:
                conn.execute(
                    "CREATE TEMP TABLE candidates (chunk_id TEXT PRIMARY KEY, scope TEXT, version INTEGER) WITHOUT ROWID"
                )
                for row in self._query_rows(conn, dataset_id, tenant_id=tenant_id):
                    chunk = _row_to_chunk(row)
                    if not _filter_chunks(
                        [chunk],
                        tenant_id=tenant_id,
                        version="",
                        metadata_filter=metadata_filter or {},
                    ):
                        continue
                    metadata = chunk.metadata or {}
                    scope = json.dumps(
                        [
                            str(metadata.get("tenant_id") or ""),
                            str(metadata.get("source") or chunk.source or ""),
                        ]
                    )
                    conn.execute(
                        "INSERT INTO candidates VALUES (?, ?, ?)",
                        (row["chunk_id"], scope, int(metadata.get("document_version") or 1)),
                    )
                conn.execute("CREATE INDEX temp.candidate_versions ON candidates(scope, version)")
            for sequence, row in enumerate(
                self._query_rows(conn, dataset_id, tenant_id=tenant_id, latest=latest)
            ):
                chunk = _row_to_chunk(row)
                if not latest and not _filter_chunks(
                    [chunk],
                    tenant_id=tenant_id,
                    version=version,
                    metadata_filter=metadata_filter or {},
                ):
                    continue
                metadata = chunk.metadata or {}
                embedding = _embedding_from_metadata(metadata)
                vector_score = _cosine(query_vector, embedding) if embedding else 0.0
                chunk.score = float(vector_score + _lexical_score(chunk.text, query_terms))
                if not math.isfinite(chunk.score):
                    raise ValueError("Vector index contains a non-finite score; rebuild it")
                chunk.source = self.backend_name
                candidate = (chunk.score, -sequence, chunk)
                if len(selected) < limit:
                    heapq.heappush(selected, candidate)
                elif candidate[:2] > selected[0][:2]:
                    heapq.heapreplace(selected, candidate)
        return [entry[2] for entry in sorted(selected, key=lambda item: item[:2], reverse=True)]

    @staticmethod
    def _query_rows(
        conn: sqlite3.Connection, dataset_id: str, *, tenant_id: str, latest: bool = False
    ):
        # embedding is also present in metadata; selecting its duplicate JSON
        # column doubles transfer/allocation without contributing to the result.
        columns = ", ".join(
            "c." + name
            for name in (
                "chunk_id",
                "content",
                "source",
                "chunk_index",
                "char_start",
                "char_end",
                "metadata",
                "source_url",
                "page",
            )
        )
        sql = "SELECT " + columns + " FROM dataset_vector_chunks c "
        if latest:
            sql += (
                "JOIN candidates selected ON selected.chunk_id = c.chunk_id "
                "JOIN (SELECT scope, MAX(0, MAX(version)) version FROM candidates GROUP BY scope) versions "
                "ON versions.scope = selected.scope AND versions.version = selected.version "
            )
        sql += "WHERE c.index_id = ? "
        args: tuple[str, ...] = (_index_id(dataset_id),)
        if tenant_id:
            sql += "AND c.tenant_id = ? "
            args += (tenant_id,)
        with closing(conn.execute(sql + "ORDER BY c.chunk_index ASC, c.rowid ASC", args)) as cursor:
            yield from cursor

    def status(self, dataset_id: str = "") -> dict[str, Any]:
        with closing(self._get_conn()) as conn:
            if dataset_id:
                row = conn.execute(
                    "\n                    SELECT index_id, dataset_id, backend, created_at, updated_at, chunk_count\n                    FROM dataset_vector_indexes\n                    WHERE index_id = ?\n                    ",
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
                "\n                SELECT index_id, dataset_id, backend, created_at, updated_at, chunk_count\n                FROM dataset_vector_indexes\n                ORDER BY updated_at DESC\n                "
            ).fetchall()
        return {
            "backend": self.backend_name,
            "path": self._db_path,
            "persistent": True,
            "index_count": len(rows),
            "indexes": [dict(row) for row in rows],
        }

    def _select_rows(self, dataset_id: str, *, tenant_id: str) -> list[sqlite3.Row]:
        """Compatibility inspection helper; production ranking streams the cursor."""
        with closing(self._get_conn()) as conn:
            return list(self._query_rows(conn, dataset_id, tenant_id=tenant_id))


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
        return int(row["chunk_count"] if row and row.get("chunk_count") is not None else 0)

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
