"""Tests for app.infrastructure.persistence.user_memory_vector_store — coverage ramp."""

from __future__ import annotations

import json
import os
import tempfile
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from app.infrastructure.persistence.user_memory_vector_store import (
    SQLiteUserMemoryVectorStore,
)


# ---------------------------------------------------------------------------
# SQLiteUserMemoryVectorStore
# ---------------------------------------------------------------------------


class TestSQLiteUserMemoryVectorStore:
    @pytest.fixture
    def store(self, tmp_path):
        db_path = str(tmp_path / "test_vectors.db")
        return SQLiteUserMemoryVectorStore(db_path)

    def test_create_and_list_index(self, store):
        store.create_or_update_index("idx-1", "user-1")
        indexes = store.list_indexes()
        assert len(indexes) == 1
        assert indexes[0]["index_id"] == "idx-1"
        assert indexes[0]["user_id"] == "user-1"

    def test_update_index(self, store):
        store.create_or_update_index("idx-1", "user-1")
        store.create_or_update_index("idx-1", "user-2")
        indexes = store.list_indexes()
        assert len(indexes) == 1
        assert indexes[0]["user_id"] == "user-2"

    def test_upsert_chunks_empty(self, store):
        result = store.upsert_chunks("idx-1", [])
        assert result == 0

    def test_upsert_chunks_and_query(self, store):
        store.create_or_update_index("idx-1", "user-1")
        embedding = [1.0, 0.0, 0.0]
        chunks = [
            {
                "chunk_id": "c1",
                "content": "hello world",
                "embedding": embedding,
                "metadata": {"source": "test"},
            }
        ]
        count = store.upsert_chunks("idx-1", chunks)
        assert count == 1

        results = store.query("idx-1", [1.0, 0.0, 0.0], top_k=5)
        assert len(results) == 1
        assert results[0]["chunk_id"] == "c1"
        assert results[0]["content"] == "hello world"
        assert results[0]["score"] > 0.9

    def test_query_empty_index(self, store):
        store.create_or_update_index("idx-1", "user-1")
        results = store.query("idx-1", [1.0, 0.0, 0.0])
        assert results == []

    def test_query_nonexistent_index(self, store):
        results = store.query("nonexistent", [1.0, 0.0, 0.0])
        assert results == []

    def test_upsert_chunks_updates_existing(self, store):
        store.create_or_update_index("idx-1", "user-1")
        chunks = [
            {"chunk_id": "c1", "content": "v1", "embedding": [1.0, 0.0], "metadata": {}}
        ]
        store.upsert_chunks("idx-1", chunks)
        chunks[0]["content"] = "v2"
        store.upsert_chunks("idx-1", chunks)
        results = store.query("idx-1", [1.0, 0.0])
        assert results[0]["content"] == "v2"

    def test_delete_index(self, store):
        store.create_or_update_index("idx-1", "user-1")
        result = store.delete_index("idx-1")
        assert result is True
        assert store.list_indexes() == []

    def test_delete_nonexistent_index(self, store):
        result = store.delete_index("nonexistent")
        assert result is False

    def test_cosine_similarity(self, store_cls=SQLiteUserMemoryVectorStore):
        a = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        b = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        assert store_cls._cosine_similarity(a, b) == pytest.approx(1.0)

    def test_cosine_similarity_orthogonal(self, store_cls=SQLiteUserMemoryVectorStore):
        a = np.array([1.0, 0.0], dtype=np.float32)
        b = np.array([0.0, 1.0], dtype=np.float32)
        assert store_cls._cosine_similarity(a, b) == pytest.approx(0.0)

    def test_cosine_similarity_zero_vector(self, store_cls=SQLiteUserMemoryVectorStore):
        a = np.array([0.0, 0.0], dtype=np.float32)
        b = np.array([1.0, 0.0], dtype=np.float32)
        assert store_cls._cosine_similarity(a, b) == 0.0

    def test_query_top_k_limit(self, store):
        store.create_or_update_index("idx-1", "user-1")
        for i in range(5):
            store.upsert_chunks("idx-1", [
                {"chunk_id": f"c{i}", "content": f"text{i}", "embedding": [float(i), 0.0], "metadata": {}}
            ])
        results = store.query("idx-1", [0.0, 0.0], top_k=2)
        assert len(results) == 2

    def test_query_with_bad_embedding_skipped(self, store):
        store.create_or_update_index("idx-1", "user-1")
        # Insert a chunk with bad embedding directly via SQL
        with store._get_conn() as conn:
            conn.execute(
                "INSERT INTO user_memory_vector_chunks(chunk_id, index_id, content, embedding, metadata, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                ("bad-c", "idx-1", "bad", "not-json", "{}", 0.0),
            )
            conn.commit()
        results = store.query("idx-1", [1.0, 0.0])
        assert len(results) == 0  # bad embedding skipped

    def test_list_indexes_empty(self, store):
        assert store.list_indexes() == []

    def test_chunk_count_updated(self, store):
        store.create_or_update_index("idx-1", "user-1")
        store.upsert_chunks("idx-1", [
            {"chunk_id": "c1", "content": "a", "embedding": [1.0], "metadata": {}},
            {"chunk_id": "c2", "content": "b", "embedding": [2.0], "metadata": {}},
        ])
        indexes = store.list_indexes()
        assert indexes[0]["chunk_count"] == 2


# ---------------------------------------------------------------------------
# Module-level functions
# ---------------------------------------------------------------------------


class TestModuleFunctions:
    def test_get_user_memory_sqlite_vector_store(self):
        from app.infrastructure.persistence.user_memory_vector_store import (
            get_user_memory_sqlite_vector_store,
        )
        # Reset singleton
        import app.infrastructure.persistence.user_memory_vector_store as mod
        mod._user_memory_sqlite_vector_store_instance = None
        with patch("app.infrastructure.persistence.user_memory_vector_store._default_user_memory_vector_db_path",
                   return_value=os.path.join(tempfile.mkdtemp(), "test.db")):
            store = get_user_memory_sqlite_vector_store()
            assert store is not None
        mod._user_memory_sqlite_vector_store_instance = None

    def test_get_user_memory_pg_vector_store_raises_without_url(self):
        from app.infrastructure.persistence.user_memory_vector_store import (
            get_user_memory_pg_vector_store,
        )
        import app.infrastructure.persistence.user_memory_vector_store as mod
        mod._user_memory_pg_vector_store_instance = None
        with patch.dict(os.environ, {"VECTOR_DB_URL": "", "DATABASE_URL": ""}, clear=False):
            with pytest.raises(ValueError, match="缺少"):
                get_user_memory_pg_vector_store()

    def test_default_db_path_from_env(self):
        from app.infrastructure.persistence.user_memory_vector_store import (
            _default_user_memory_vector_db_path,
        )
        with patch.dict(os.environ, {"USER_MEMORY_VECTOR_DB_PATH": "/tmp/test_vec.db"}):
            path = _default_user_memory_vector_db_path()
            assert path == "/tmp/test_vec.db"

    def test_default_db_path_from_app_data(self):
        from app.infrastructure.persistence.user_memory_vector_store import (
            _default_user_memory_vector_db_path,
        )
        with patch.dict(os.environ, {"USER_MEMORY_VECTOR_DB_PATH": ""}, clear=False):
            path = _default_user_memory_vector_db_path()
            assert "user_memory_vectors.db" in path
