"""Branch coverage for app.infrastructure.persistence.pg_vector_store.

Covers upsert_chunks empty check, delete_index rowcount, query filters (0/4 branches).
Existing test_pg_vector_store.py only does DDL/source assertions.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def _make_store():
    """Create a PgVectorStore with mocked engine (no real DB)."""
    with (
        patch("app.infrastructure.persistence.pg_vector_store.create_engine") as mock_create,
        patch(
            "app.infrastructure.persistence.pg_vector_store.PgVectorStore._ensure_tables",
            return_value=None,
        ),
    ):
        mock_engine = MagicMock()
        mock_create.return_value = mock_engine
        from app.infrastructure.persistence.pg_vector_store import PgVectorStore

        store = PgVectorStore("postgresql://u:p@localhost/db")
    return store, mock_engine


class TestUpsertChunks:
    def test_empty_chunks_returns_zero(self):
        store, _ = _make_store()
        result = store.upsert_chunks("idx-1", [])
        assert result == 0

    def test_non_empty_chunks_inserts_and_returns_count(self):
        store, mock_engine = _make_store()
        mock_conn = MagicMock()
        mock_engine.begin.return_value.__enter__.return_value = mock_conn
        chunks = [
            {"chunk_id": "c1", "content": "hello", "embedding": [0.1, 0.2], "metadata": {"x": 1}},
            {"chunk_id": "c2", "content": "world", "embedding": [0.3, 0.4]},
        ]
        result = store.upsert_chunks("idx-1", chunks)
        assert result == 2
        # DELETE + 2 INSERTs + 1 UPDATE = 4 executes
        assert mock_conn.execute.call_count == 4

    def test_chunks_without_metadata_uses_empty_dict(self):
        store, mock_engine = _make_store()
        mock_conn = MagicMock()
        mock_engine.begin.return_value.__enter__.return_value = mock_conn
        chunks = [{"chunk_id": "c1", "content": "hello", "embedding": [0.1]}]
        result = store.upsert_chunks("idx-1", chunks)
        assert result == 1


class TestQuery:
    def test_query_returns_results(self):
        store, mock_engine = _make_store()
        mock_conn = MagicMock()
        mock_engine.begin.return_value.__enter__.return_value = mock_conn
        mock_row = MagicMock()
        mock_row.__getitem__.side_effect = lambda k: {
            "chunk_id": "c1",
            "content": "hello",
            "metadata": {"x": 1},
            "score": 0.95,
        }[k]
        mock_result = MagicMock()
        mock_result.mappings.return_value.all.return_value = [mock_row]
        mock_conn.execute.return_value = mock_result
        result = store.query("idx-1", [0.1, 0.2], top_k=5, filters={"a": "b"})
        assert len(result) == 1
        assert result[0]["chunk_id"] == "c1"
        assert result[0]["score"] == 0.95

    def test_query_with_none_metadata(self):
        store, mock_engine = _make_store()
        mock_conn = MagicMock()
        mock_engine.begin.return_value.__enter__.return_value = mock_conn
        mock_row = MagicMock()
        mock_row.__getitem__.side_effect = lambda k: {
            "chunk_id": "c1",
            "content": "hello",
            "metadata": None,
            "score": None,
        }[k]
        mock_result = MagicMock()
        mock_result.mappings.return_value.all.return_value = [mock_row]
        mock_conn.execute.return_value = mock_result
        result = store.query("idx-1", [0.1], top_k=3)
        assert result[0]["metadata"] == {}
        assert result[0]["score"] == 0.0

    def test_query_top_k_clamped_to_min_1(self):
        store, mock_engine = _make_store()
        mock_conn = MagicMock()
        mock_engine.begin.return_value.__enter__.return_value = mock_conn
        mock_result = MagicMock()
        mock_result.mappings.return_value.all.return_value = []
        mock_conn.execute.return_value = mock_result
        result = store.query("idx-1", [0.1], top_k=0)
        assert result == []
        # Verify top_k was clamped to 1
        call_kwargs = mock_conn.execute.call_args[0][1]
        assert call_kwargs["top_k"] == 1


class TestDeleteIndex:
    def test_delete_returns_true_when_rowcount_positive(self):
        store, mock_engine = _make_store()
        mock_conn = MagicMock()
        mock_engine.begin.return_value.__enter__.return_value = mock_conn
        # Second execute (DELETE indexes) returns rowcount > 0
        delete_chunks_result = MagicMock()
        delete_indexes_result = MagicMock()
        delete_indexes_result.rowcount = 1
        mock_conn.execute.side_effect = [delete_chunks_result, delete_indexes_result]
        result = store.delete_index("idx-1")
        assert result is True

    def test_delete_returns_false_when_rowcount_zero(self):
        store, mock_engine = _make_store()
        mock_conn = MagicMock()
        mock_engine.begin.return_value.__enter__.return_value = mock_conn
        delete_chunks_result = MagicMock()
        delete_indexes_result = MagicMock()
        delete_indexes_result.rowcount = 0
        mock_conn.execute.side_effect = [delete_chunks_result, delete_indexes_result]
        result = store.delete_index("nonexistent")
        assert result is False


class TestCreateOrUpdateIndex:
    def test_create_or_update_executes_upsert(self):
        store, mock_engine = _make_store()
        mock_conn = MagicMock()
        mock_engine.begin.return_value.__enter__.return_value = mock_conn
        store.create_or_update_index("idx-1", "My Index", "file.xlsx")
        mock_conn.execute.assert_called_once()


class TestListIndexes:
    def test_list_returns_rows(self):
        store, mock_engine = _make_store()
        mock_conn = MagicMock()
        mock_engine.begin.return_value.__enter__.return_value = mock_conn
        mock_row = {
            "index_id": "idx-1",
            "name": "test",
            "source_file": "f.xlsx",
            "created_at": 1.0,
            "updated_at": 2.0,
            "chunk_count": 5,
        }
        mock_result = MagicMock()
        mock_result.mappings.return_value.all.return_value = [mock_row]
        mock_conn.execute.return_value = mock_result
        result = store.list_indexes()
        assert len(result) == 1
        assert result[0]["index_id"] == "idx-1"

    def test_list_empty(self):
        store, mock_engine = _make_store()
        mock_conn = MagicMock()
        mock_engine.begin.return_value.__enter__.return_value = mock_conn
        mock_result = MagicMock()
        mock_result.mappings.return_value.all.return_value = []
        mock_conn.execute.return_value = mock_result
        result = store.list_indexes()
        assert result == []
