# ruff: noqa
"""SQLite implementation of the dataset vector index backend."""
from __future__ import annotations
import json
import logging
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, cast
from app.infrastructure.rag.hybrid_retriever import RetrievedChunk
from app.utils.operational_errors import RECOVERABLE_ERRORS
from app.utils.path_io.external_sqlite import connect_sqlite
logger = logging.getLogger(__name__)

def _facade() -> Any:
    return sys.modules['app.infrastructure.rag.dataset_vector_index']

class DatasetVectorSQLiteIndex:
    """Dataset vector index backed by SQLite plus in-process cosine ranking."""
    backend_name = 'sqlite_vector'

    def __init__(self, db_path: str | Path) -> None:
        path = Path(db_path).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = str(path)
        try:
            self._ensure_tables()
        except sqlite3.DatabaseError as exc:
            if not path.is_file() or not _facade()._is_rebuildable_index_error(exc):
                raise
            backup_path = path.with_name(f'{path.name}.incompatible-{_facade().time.time_ns()}.bak')
            path.replace(backup_path)
            _facade().logger.warning('Archived incompatible dataset vector index %s to %s; rebuilding from source data', path, backup_path)
            self._ensure_tables()

    @property
    def db_path(self) -> str:
        return self._db_path

    def _get_conn(self) -> sqlite3.Connection:
        conn = connect_sqlite(self._db_path)
        try:
            conn.execute('PRAGMA foreign_keys = ON')
        except RECOVERABLE_ERRORS:
            pass
        conn.row_factory = sqlite3.Row
        return cast(sqlite3.Connection, conn)

    def _ensure_tables(self) -> None:
        with self._get_conn() as conn:
            conn.execute('\n                CREATE TABLE IF NOT EXISTS dataset_vector_indexes (\n                    index_id TEXT PRIMARY KEY,\n                    dataset_id TEXT NOT NULL,\n                    backend TEXT NOT NULL,\n                    created_at REAL NOT NULL,\n                    updated_at REAL NOT NULL,\n                    chunk_count INTEGER NOT NULL DEFAULT 0\n                )\n                ')
            conn.execute('\n                CREATE TABLE IF NOT EXISTS dataset_vector_chunks (\n                    chunk_id TEXT PRIMARY KEY,\n                    index_id TEXT NOT NULL REFERENCES dataset_vector_indexes(index_id) ON DELETE CASCADE,\n                    dataset_id TEXT NOT NULL,\n                    document_id TEXT NOT NULL,\n                    tenant_id TEXT NOT NULL,\n                    source TEXT NOT NULL,\n                    document_version INTEGER NOT NULL,\n                    version_label TEXT NOT NULL,\n                    content TEXT NOT NULL,\n                    embedding TEXT NOT NULL,\n                    metadata TEXT NOT NULL,\n                    source_url TEXT NOT NULL,\n                    chunk_index INTEGER NOT NULL,\n                    char_start INTEGER NOT NULL,\n                    char_end INTEGER NOT NULL,\n                    page INTEGER,\n                    created_at REAL NOT NULL\n                )\n                ')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_dataset_vector_chunks_index_id ON dataset_vector_chunks(index_id)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_dataset_vector_chunks_tenant ON dataset_vector_chunks(index_id, tenant_id)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_dataset_vector_chunks_doc ON dataset_vector_chunks(index_id, document_id)')
            conn.commit()

    def replace_dataset(self, dataset_id: str, chunks: list[RetrievedChunk]) -> int:
        index_id = _facade()._index_id(dataset_id)
        now = _facade().time.time()
        with self._get_conn() as conn:
            conn.execute('\n                INSERT INTO dataset_vector_indexes(index_id, dataset_id, backend, created_at, updated_at, chunk_count)\n                VALUES(?, ?, ?, ?, ?, 0)\n                ON CONFLICT(index_id) DO UPDATE SET\n                    dataset_id = excluded.dataset_id,\n                    backend = excluded.backend,\n                    updated_at = excluded.updated_at\n                ', (index_id, dataset_id, self.backend_name, now, now))
            conn.execute('DELETE FROM dataset_vector_chunks WHERE index_id = ?', (index_id,))
            for chunk in chunks:
                metadata = dict(chunk.metadata or {})
                document_id = str(metadata.get('document_id') or '')
                row_id = _facade()._chunk_row_id(dataset_id, chunk)
                conn.execute('\n                    INSERT INTO dataset_vector_chunks(\n                        chunk_id,\n                        index_id,\n                        dataset_id,\n                        document_id,\n                        tenant_id,\n                        source,\n                        document_version,\n                        version_label,\n                        content,\n                        embedding,\n                        metadata,\n                        source_url,\n                        chunk_index,\n                        char_start,\n                        char_end,\n                        page,\n                        created_at\n                    )\n                    VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)\n                    ', (row_id, index_id, dataset_id, document_id, str(metadata.get('tenant_id') or ''), str(metadata.get('source') or chunk.source or ''), int(metadata.get('document_version') or 1), str(metadata.get('version_label') or ''), chunk.text, _facade().json.dumps(_facade()._embedding_from_metadata(metadata), ensure_ascii=False), _facade().json.dumps(metadata, ensure_ascii=False), chunk.source_url or '', int(chunk.chunk_index or 0), int(chunk.char_start or 0), int(chunk.char_end or 0), chunk.page, now))
            conn.execute('\n                UPDATE dataset_vector_indexes\n                SET chunk_count = ?, updated_at = ?\n                WHERE index_id = ?\n                ', (len(chunks), now, index_id))
            conn.commit()
        return len(chunks)

    def delete_dataset(self, dataset_id: str) -> bool:
        index_id = _facade()._index_id(dataset_id)
        with self._get_conn() as conn:
            result = conn.execute('DELETE FROM dataset_vector_indexes WHERE index_id = ?', (index_id,))
            conn.commit()
        return bool(getattr(result, 'rowcount', 0) > 0)

    def query(self, dataset_id: str, query_vector: list[float], *, top_k: int=50, tenant_id: str='', version: str | int='', metadata_filter: dict[str, Any] | None=None) -> list[RetrievedChunk]:
        rows = self._select_rows(dataset_id, tenant_id=tenant_id)
        chunks = [_facade()._row_to_chunk(row) for row in rows]
        chunks = _facade()._filter_chunks(chunks, tenant_id=tenant_id, version=version, metadata_filter=metadata_filter or {})
        query_terms = set(_facade()._tokenize_for_lexical(' '.join((str(v) for v in query_vector))))
        scored: list[RetrievedChunk] = []
        for chunk in chunks:
            metadata = dict(chunk.metadata or {})
            embedding = _facade()._embedding_from_metadata(metadata)
            vector_score = _facade()._cosine(query_vector, embedding) if embedding else 0.0
            lexical_score = _facade()._lexical_score(chunk.text, query_terms)
            scored.append(_facade().RetrievedChunk(text=chunk.text, score=float(vector_score + lexical_score), source=self.backend_name, chunk_index=chunk.chunk_index, char_start=chunk.char_start, char_end=chunk.char_end, metadata=metadata, source_url=chunk.source_url, page=chunk.page))
        scored.sort(key=lambda item: item.score, reverse=True)
        return scored[:max(1, int(top_k or 1))]

    def status(self, dataset_id: str='') -> dict[str, Any]:
        with self._get_conn() as conn:
            if dataset_id:
                row = conn.execute('\n                    SELECT index_id, dataset_id, backend, created_at, updated_at, chunk_count\n                    FROM dataset_vector_indexes\n                    WHERE index_id = ?\n                    ', (_facade()._index_id(dataset_id),)).fetchone()
                if row is None:
                    return {'backend': self.backend_name, 'path': self._db_path, 'persistent': True, 'dataset_id': dataset_id, 'chunk_count': 0, 'index_exists': False}
                payload = dict(row)
                payload.update({'path': self._db_path, 'persistent': True, 'index_exists': True})
                return payload
            rows = conn.execute('\n                SELECT index_id, dataset_id, backend, created_at, updated_at, chunk_count\n                FROM dataset_vector_indexes\n                ORDER BY updated_at DESC\n                ').fetchall()
        return {'backend': self.backend_name, 'path': self._db_path, 'persistent': True, 'index_count': len(rows), 'indexes': [dict(row) for row in rows]}

    def _select_rows(self, dataset_id: str, *, tenant_id: str) -> list[sqlite3.Row]:
        index_id = _facade()._index_id(dataset_id)
        with self._get_conn() as conn:
            if tenant_id:
                rows = conn.execute('\n                    SELECT *\n                    FROM dataset_vector_chunks\n                    WHERE index_id = ? AND tenant_id = ?\n                    ORDER BY chunk_index ASC\n                    ', (index_id, tenant_id)).fetchall()
            else:
                rows = conn.execute('\n                    SELECT *\n                    FROM dataset_vector_chunks\n                    WHERE index_id = ?\n                    ORDER BY chunk_index ASC\n                    ', (index_id,)).fetchall()
        return list(rows)
