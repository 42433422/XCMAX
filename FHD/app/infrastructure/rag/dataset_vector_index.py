from __future__ import annotations

import json
import logging
import time
from typing import Any, Protocol, runtime_checkable

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
from app.infrastructure.rag.dataset_vector_sqlite import (
    DatasetVectorSQLiteIndex as DatasetVectorSQLiteIndex,
)
from app.infrastructure.rag.hybrid_retriever import RetrievedChunk

logger = logging.getLogger(__name__)


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

