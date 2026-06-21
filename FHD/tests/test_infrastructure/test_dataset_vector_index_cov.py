from __future__ import annotations

"""Branch-coverage tests for app.infrastructure.rag.dataset_vector_index."""

import json
import math
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.infrastructure.rag.dataset_vector_index import (
    DatasetVectorSQLiteIndex,
    _chunk_row_id,
    _cosine,
    _embedding_from_metadata,
    _filter_chunks,
    _index_id,
    _lexical_score,
    _load_json_object,
    _metadata_matches,
    _pg_row_to_chunk,
    _row_to_chunk,
    _sha256,
    _tokenize_for_lexical,
    default_dataset_vector_index_path,
)
from app.infrastructure.rag.hybrid_retriever import RetrievedChunk

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_chunk(
    text="hello",
    metadata=None,
    chunk_index=0,
    char_start=0,
    char_end=5,
    source="test",
    source_url="",
    page=None,
    score=0.0,
) -> RetrievedChunk:
    return RetrievedChunk(
        text=text,
        score=score,
        source=source,
        chunk_index=chunk_index,
        char_start=char_start,
        char_end=char_end,
        metadata=metadata or {},
        source_url=source_url,
        page=page,
    )


@pytest.fixture
def sqlite_index(tmp_path):
    db_path = tmp_path / "test_vectors.sqlite"
    return DatasetVectorSQLiteIndex(db_path)


# ---------------------------------------------------------------------------
# _load_json_object
# ---------------------------------------------------------------------------

class TestLoadJsonObject:
    def test_dict_passthrough(self):
        assert _load_json_object({"a": 1}) == {"a": 1}

    def test_json_string(self):
        assert _load_json_object('{"x": 2}') == {"x": 2}

    def test_invalid_json_returns_empty(self):
        assert _load_json_object("not-json{{") == {}

    def test_none_returns_empty(self):
        assert _load_json_object(None) == {}

    def test_list_json_returns_empty(self):
        # parsed is a list, not dict
        assert _load_json_object("[1, 2]") == {}

    def test_empty_string(self):
        assert _load_json_object("") == {}


# ---------------------------------------------------------------------------
# _embedding_from_metadata
# ---------------------------------------------------------------------------

class TestEmbeddingFromMetadata:
    def test_no_embedding_key(self):
        assert _embedding_from_metadata({}) == []

    def test_non_list_embedding(self):
        assert _embedding_from_metadata({"_embedding": "not-a-list"}) == []

    def test_list_embedding(self):
        result = _embedding_from_metadata({"_embedding": [1.0, 2.0]})
        assert result == [1.0, 2.0]

    def test_list_with_bad_item(self):
        assert _embedding_from_metadata({"_embedding": ["bad", "vals"]}) == []


# ---------------------------------------------------------------------------
# _cosine
# ---------------------------------------------------------------------------

class TestCosine:
    def test_empty_vectors(self):
        assert _cosine([], []) == 0.0

    def test_different_lengths(self):
        assert _cosine([1.0], [1.0, 2.0]) == 0.0

    def test_zero_norm_a(self):
        assert _cosine([0.0, 0.0], [1.0, 0.0]) == 0.0

    def test_zero_norm_b(self):
        assert _cosine([1.0, 0.0], [0.0, 0.0]) == 0.0

    def test_identical_vectors(self):
        v = [1.0, 0.0]
        assert abs(_cosine(v, v) - 1.0) < 1e-9

    def test_orthogonal(self):
        assert abs(_cosine([1.0, 0.0], [0.0, 1.0])) < 1e-9


# ---------------------------------------------------------------------------
# _lexical_score and _tokenize_for_lexical
# ---------------------------------------------------------------------------

class TestLexicalScore:
    def test_empty_terms(self):
        assert _lexical_score("hello world", set()) == 0.0

    def test_full_match(self):
        score = _lexical_score("hello world", {"hello", "world"})
        assert score == 1.0

    def test_partial_match(self):
        score = _lexical_score("hello", {"hello", "world"})
        assert score == 0.5

    def test_no_match(self):
        score = _lexical_score("foo bar", {"baz"})
        assert score == 0.0


class TestTokenize:
    def test_basic(self):
        tokens = _tokenize_for_lexical("Hello World 123")
        assert "hello" in tokens
        assert "world" in tokens
        assert "123" in tokens

    def test_punctuation_stripped(self):
        tokens = _tokenize_for_lexical("hello!world")
        assert "hello" in tokens
        assert "world" in tokens


# ---------------------------------------------------------------------------
# _metadata_matches
# ---------------------------------------------------------------------------

class TestMetadataMatches:
    def test_simple_match(self):
        assert _metadata_matches({"k": "v"}, {"k": "v"}) is True

    def test_simple_no_match(self):
        assert _metadata_matches({"k": "v"}, {"k": "x"}) is False

    def test_list_expected_match(self):
        assert _metadata_matches({"k": "a"}, {"k": ["a", "b"]}) is True

    def test_list_expected_no_match(self):
        assert _metadata_matches({"k": "c"}, {"k": ["a", "b"]}) is False

    def test_dict_expected_actual_not_dict(self):
        assert _metadata_matches({"k": "v"}, {"k": {"nested": "x"}}) is False

    def test_dict_expected_match(self):
        assert _metadata_matches({"k": {"n": "x"}}, {"k": {"n": "x"}}) is True

    def test_dict_expected_nested_no_match(self):
        assert _metadata_matches({"k": {"n": "y"}}, {"k": {"n": "x"}}) is False


# ---------------------------------------------------------------------------
# _filter_chunks
# ---------------------------------------------------------------------------

class TestFilterChunks:
    def _chunk_with_meta(self, meta):
        return _make_chunk(metadata=meta)

    def test_no_filter(self):
        chunks = [self._chunk_with_meta({})]
        result = _filter_chunks(chunks, tenant_id="", version="", metadata_filter={})
        assert len(result) == 1

    def test_tenant_filter(self):
        c1 = _make_chunk(metadata={"tenant_id": "t1"})
        c2 = _make_chunk(metadata={"tenant_id": "t2"})
        result = _filter_chunks([c1, c2], tenant_id="t1", version="", metadata_filter={})
        assert len(result) == 1
        assert result[0].metadata["tenant_id"] == "t1"

    def test_metadata_filter_applied(self):
        c1 = _make_chunk(metadata={"status": "active"})
        c2 = _make_chunk(metadata={"status": "inactive"})
        result = _filter_chunks([c1, c2], tenant_id="", version="", metadata_filter={"status": "active"})
        assert len(result) == 1

    def test_version_latest_keeps_highest(self):
        c1 = _make_chunk(source="src", metadata={"tenant_id": "", "source": "src", "document_version": 1})
        c2 = _make_chunk(source="src", metadata={"tenant_id": "", "source": "src", "document_version": 2})
        result = _filter_chunks([c1, c2], tenant_id="", version="latest", metadata_filter={})
        assert len(result) == 1
        assert result[0].metadata["document_version"] == 2

    def test_version_numeric_exact(self):
        c1 = _make_chunk(metadata={"document_version": 3, "version_label": ""})
        c2 = _make_chunk(metadata={"document_version": 5, "version_label": ""})
        result = _filter_chunks([c1, c2], tenant_id="", version="3", metadata_filter={})
        assert len(result) == 1

    def test_version_with_v_prefix(self):
        c1 = _make_chunk(metadata={"document_version": 2, "version_label": "v2"})
        result = _filter_chunks([c1], tenant_id="", version="v2", metadata_filter={})
        assert len(result) == 1

    def test_version_label_match(self):
        c1 = _make_chunk(metadata={"document_version": 0, "version_label": "release-1.0"})
        result = _filter_chunks([c1], tenant_id="", version="release-1.0", metadata_filter={})
        assert len(result) == 1

    def test_version_empty_returns_all(self):
        chunks = [_make_chunk(), _make_chunk()]
        result = _filter_chunks(chunks, tenant_id="", version="", metadata_filter={})
        assert len(result) == 2


# ---------------------------------------------------------------------------
# DatasetVectorSQLiteIndex
# ---------------------------------------------------------------------------

class TestSQLiteIndex:
    def test_init_creates_tables(self, sqlite_index):
        with sqlite3.connect(sqlite_index.db_path) as conn:
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "dataset_vector_indexes" in tables
        assert "dataset_vector_chunks" in tables

    def test_replace_and_delete(self, sqlite_index):
        chunk = _make_chunk(
            metadata={"_embedding": [1.0, 0.0], "document_id": "doc1", "tenant_id": "t1",
                       "source": "src", "document_version": 1, "version_label": "v1"}
        )
        count = sqlite_index.replace_dataset("ds1", [chunk])
        assert count == 1
        deleted = sqlite_index.delete_dataset("ds1")
        assert deleted is True

    def test_delete_nonexistent(self, sqlite_index):
        assert sqlite_index.delete_dataset("nope") is False

    def test_status_no_dataset_id(self, sqlite_index):
        status = sqlite_index.status()
        assert "indexes" in status
        assert status["backend"] == "sqlite_vector"

    def test_status_with_dataset_id_not_found(self, sqlite_index):
        status = sqlite_index.status("missing-ds")
        assert status["index_exists"] is False
        assert status["chunk_count"] == 0

    def test_status_with_dataset_id_found(self, sqlite_index):
        chunk = _make_chunk(metadata={"_embedding": [0.5, 0.5]})
        sqlite_index.replace_dataset("ds2", [chunk])
        status = sqlite_index.status("ds2")
        assert status["index_exists"] is True

    def test_query_with_tenant_filter(self, sqlite_index):
        c1 = _make_chunk(text="text1", metadata={
            "_embedding": [1.0, 0.0], "tenant_id": "t1",
            "document_id": "d1", "source": "s", "document_version": 1, "version_label": ""
        })
        c2 = _make_chunk(text="text2", metadata={
            "_embedding": [0.0, 1.0], "tenant_id": "t2",
            "document_id": "d2", "source": "s", "document_version": 1, "version_label": ""
        })
        sqlite_index.replace_dataset("ds3", [c1, c2])
        results = sqlite_index.query("ds3", [1.0, 0.0], tenant_id="t1", top_k=10)
        assert all(r.metadata.get("tenant_id") == "t1" for r in results)

    def test_query_empty_dataset(self, sqlite_index):
        results = sqlite_index.query("nonexistent", [1.0, 0.0])
        assert results == []

    def test_select_rows_no_tenant(self, sqlite_index):
        chunk = _make_chunk(metadata={"_embedding": [0.3, 0.7], "tenant_id": "x"})
        sqlite_index.replace_dataset("ds4", [chunk])
        rows = sqlite_index._select_rows("ds4", tenant_id="")
        assert len(rows) == 1

    def test_select_rows_with_tenant(self, sqlite_index):
        chunk = _make_chunk(metadata={"_embedding": [0.3, 0.7], "tenant_id": "x"})
        sqlite_index.replace_dataset("ds5", [chunk])
        rows = sqlite_index._select_rows("ds5", tenant_id="x")
        assert len(rows) == 1

    def test_query_with_metadata_filter(self, sqlite_index):
        c = _make_chunk(text="doc", metadata={
            "_embedding": [1.0, 0.0], "tenant_id": "", "doc_type": "invoice",
            "document_id": "d3", "source": "s", "document_version": 1, "version_label": ""
        })
        sqlite_index.replace_dataset("ds6", [c])
        results = sqlite_index.query("ds6", [1.0, 0.0], metadata_filter={"doc_type": "invoice"})
        assert len(results) == 1


# ---------------------------------------------------------------------------
# default_dataset_vector_index_path
# ---------------------------------------------------------------------------

class TestDefaultPath:
    def test_with_env_var(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DATASET_RAG_VECTOR_INDEX_PATH", str(tmp_path / "custom.sqlite"))
        monkeypatch.delenv("XCAGI_DATASET_RAG_VECTOR_INDEX_PATH", raising=False)
        result = default_dataset_vector_index_path()
        assert str(result).endswith("custom.sqlite")

    def test_with_storage_path(self, tmp_path, monkeypatch):
        monkeypatch.delenv("DATASET_RAG_VECTOR_INDEX_PATH", raising=False)
        monkeypatch.delenv("XCAGI_DATASET_RAG_VECTOR_INDEX_PATH", raising=False)
        result = default_dataset_vector_index_path(storage_path=tmp_path / "store.db")
        assert "vectors.sqlite" in str(result)

    def test_default_fallback(self, monkeypatch):
        monkeypatch.delenv("DATASET_RAG_VECTOR_INDEX_PATH", raising=False)
        monkeypatch.delenv("XCAGI_DATASET_RAG_VECTOR_INDEX_PATH", raising=False)
        result = default_dataset_vector_index_path()
        assert "dataset_vectors.sqlite" in str(result)

    def test_xcagi_env_var(self, tmp_path, monkeypatch):
        monkeypatch.delenv("DATASET_RAG_VECTOR_INDEX_PATH", raising=False)
        monkeypatch.setenv("XCAGI_DATASET_RAG_VECTOR_INDEX_PATH", str(tmp_path / "xcagi.sqlite"))
        result = default_dataset_vector_index_path()
        assert str(result).endswith("xcagi.sqlite")
