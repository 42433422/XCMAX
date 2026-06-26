"""Branch-coverage tests for app.application.excel_vector_app_service.

Targets branches NOT already covered by test_excel_vector_app_service.py.

Focus:
* ``HashEmbedder.__init__`` — dimensions below 64 (clamped), exactly 64,
  negative dimensions, zero.
* ``HashEmbedder._tokenize`` — empty/None text, ascii-only, cjk-only,
  cjk with exactly 2 chars (bigram boundary), cjk with 1 char (no bigram),
  mixed ascii+cjk, whitespace-only.
* ``HashEmbedder._embed`` — no tokens (zero vector), norm > 0 normalization,
  single token, multiple tokens same index (accumulation).
* ``HashEmbedder.embed_texts`` — empty list, single text, multiple texts.
* ``ExcelVectorIngestApplicationService.__init__`` — chunk_window_size below
  minimum (clamped to 5), exactly 5, large value, None vector_store (uses
  get_vector_store), None embedder (uses HashEmbedder).
* ``ingest_excel`` — file not exists, empty excel (no chunks), successful
  ingest with create_or_update_index absent, successful ingest with
  create_or_update_index present, index_name fallback to path.stem, index_id
  fallback to uuid.
* ``_build_chunks`` — df None, df empty, single row, multiple rows, row with
  all empty values (skipped), window with all empty rows (skipped), multiple
  sheets, columns with non-string names.
* ``ExcelVectorSearchApplicationService.__init__`` — None store/embedder.
* ``ExcelVectorSearchApplicationService.query`` — empty index_id, empty query,
  custom top_k, default top_k.
* ``_default_vector_db_path`` — env var with folder, env var without folder
  (just filename), env var empty, no env var (default path).
* ``get_vector_store`` — sqlite fallback enabled, sqlite fallback disabled,
  existing instance returned.
* ``get_pg_vector_store`` — no DB url raises ValueError.
* ``get_sqlite_vector_store`` — singleton creation.
* ``get_excel_vector_ingest_app_service`` / ``get_excel_vector_search_app_service``
  — singleton creation and reuse.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from app.application import excel_vector_app_service as evas_mod
from app.application.excel_vector_app_service import (
    ExcelVectorChunk,
    ExcelVectorIngestApplicationService,
    ExcelVectorSearchApplicationService,
    HashEmbedder,
    _default_vector_db_path,
    get_excel_vector_ingest_app_service,
    get_excel_vector_search_app_service,
    get_pg_vector_store,
    get_sqlite_vector_store,
    get_vector_store,
)


# ---------------------------------------------------------------------------
# HashEmbedder.__init__ — branch coverage
# ---------------------------------------------------------------------------


class TestHashEmbedderInitBranches:
    def test_dimensions_below_minimum_clamped_to_64(self):
        emb = HashEmbedder(dimensions=10)
        assert emb._dimensions == 64

    def test_dimensions_zero_clamped_to_64(self):
        emb = HashEmbedder(dimensions=0)
        assert emb._dimensions == 64

    def test_dimensions_negative_clamped_to_64(self):
        emb = HashEmbedder(dimensions=-100)
        assert emb._dimensions == 64

    def test_dimensions_exactly_64_kept(self):
        emb = HashEmbedder(dimensions=64)
        assert emb._dimensions == 64

    def test_dimensions_above_minimum_kept(self):
        emb = HashEmbedder(dimensions=128)
        assert emb._dimensions == 128

    def test_default_dimensions(self):
        emb = HashEmbedder()
        assert emb._dimensions == 256


# ---------------------------------------------------------------------------
# HashEmbedder._tokenize — branch coverage
# ---------------------------------------------------------------------------


class TestHashEmbedderTokenizeBranches:
    def test_none_text_returns_empty(self):
        emb = HashEmbedder(dimensions=64)
        assert emb._tokenize(None) == []

    def test_empty_string_returns_empty(self):
        emb = HashEmbedder(dimensions=64)
        assert emb._tokenize("") == []

    def test_whitespace_only_returns_empty(self):
        emb = HashEmbedder(dimensions=64)
        assert emb._tokenize("   \t\n  ") == []

    def test_ascii_only(self):
        emb = HashEmbedder(dimensions=64)
        tokens = emb._tokenize("hello world")
        assert "hello" in tokens
        assert "world" in tokens

    def test_cjk_single_char_no_bigram(self):
        emb = HashEmbedder(dimensions=64)
        tokens = emb._tokenize("你")
        # Single CJK char -> just the char, no bigram (len < 2)
        assert "你" in tokens

    def test_cjk_two_chars_produces_bigram(self):
        emb = HashEmbedder(dimensions=64)
        tokens = emb._tokenize("你好")
        # 2 CJK chars -> 2 chars + 1 bigram
        assert "你" in tokens
        assert "好" in tokens
        assert "你好" in tokens

    def test_cjk_three_chars_produces_two_bigrams(self):
        emb = HashEmbedder(dimensions=64)
        tokens = emb._tokenize("你好世")
        assert "你" in tokens
        assert "好" in tokens
        assert "世" in tokens
        assert "你好" in tokens
        assert "好世" in tokens

    def test_mixed_ascii_and_cjk(self):
        emb = HashEmbedder(dimensions=64)
        tokens = emb._tokenize("hello 你好")
        assert "hello" in tokens
        assert "你" in tokens
        assert "好" in tokens
        assert "你好" in tokens

    def test_numbers_tokenized(self):
        emb = HashEmbedder(dimensions=64)
        tokens = emb._tokenize("abc123 def456")
        assert "abc123" in tokens
        assert "def456" in tokens

    def test_uppercase_lowercased(self):
        emb = HashEmbedder(dimensions=64)
        tokens = emb._tokenize("HELLO")
        assert "hello" in tokens


# ---------------------------------------------------------------------------
# HashEmbedder._embed — branch coverage
# ---------------------------------------------------------------------------


class TestHashEmbedderEmbedBranches:
    def test_empty_text_returns_zero_vector(self):
        emb = HashEmbedder(dimensions=64)
        vec = emb._embed("")
        assert all(v == 0.0 for v in vec)
        assert len(vec) == 64

    def test_none_text_returns_zero_vector(self):
        emb = HashEmbedder(dimensions=64)
        vec = emb._embed(None)
        assert all(v == 0.0 for v in vec)

    def test_single_token_normalized(self):
        emb = HashEmbedder(dimensions=64)
        vec = emb._embed("hello")
        # Non-zero vector, normalized
        norm = sum(v * v for v in vec) ** 0.5
        assert abs(norm - 1.0) < 1e-6
        assert any(v != 0.0 for v in vec)

    def test_multiple_tokens_accumulate_at_indices(self):
        emb = HashEmbedder(dimensions=64)
        vec = emb._embed("hello world foo bar")
        norm = sum(v * v for v in vec) ** 0.5
        assert abs(norm - 1.0) < 1e-6

    def test_same_text_produces_same_vector(self):
        emb = HashEmbedder(dimensions=64)
        v1 = emb._embed("test text")
        v2 = emb._embed("test text")
        assert v1 == v2


# ---------------------------------------------------------------------------
# HashEmbedder.embed_texts / embed_query
# ---------------------------------------------------------------------------


class TestHashEmbedderEmbedTextsBranches:
    def test_empty_list_returns_empty(self):
        emb = HashEmbedder(dimensions=64)
        assert emb.embed_texts([]) == []

    def test_single_text(self):
        emb = HashEmbedder(dimensions=64)
        result = emb.embed_texts(["hello"])
        assert len(result) == 1
        assert len(result[0]) == 64

    def test_multiple_texts(self):
        emb = HashEmbedder(dimensions=64)
        result = emb.embed_texts(["hello", "world", "foo"])
        assert len(result) == 3
        for vec in result:
            assert len(vec) == 64

    def test_embed_query_returns_vector(self):
        emb = HashEmbedder(dimensions=64)
        vec = emb.embed_query("test query")
        assert len(vec) == 64

    def test_embed_query_empty_returns_zero_vector(self):
        emb = HashEmbedder(dimensions=64)
        vec = emb.embed_query("")
        assert all(v == 0.0 for v in vec)


# ---------------------------------------------------------------------------
# ExcelVectorIngestApplicationService.__init__ — branch coverage
# ---------------------------------------------------------------------------


class TestIngestServiceInitBranches:
    def test_chunk_window_size_below_minimum_clamped(self):
        svc = ExcelVectorIngestApplicationService(
            vector_store=MagicMock(),
            chunk_window_size=1,
        )
        assert svc._chunk_window_size == 5

    def test_chunk_window_size_zero_clamped(self):
        svc = ExcelVectorIngestApplicationService(
            vector_store=MagicMock(),
            chunk_window_size=0,
        )
        assert svc._chunk_window_size == 5

    def test_chunk_window_size_negative_clamped(self):
        svc = ExcelVectorIngestApplicationService(
            vector_store=MagicMock(),
            chunk_window_size=-10,
        )
        assert svc._chunk_window_size == 5

    def test_chunk_window_size_exactly_minimum(self):
        svc = ExcelVectorIngestApplicationService(
            vector_store=MagicMock(),
            chunk_window_size=5,
        )
        assert svc._chunk_window_size == 5

    def test_chunk_window_size_large_value(self):
        svc = ExcelVectorIngestApplicationService(
            vector_store=MagicMock(),
            chunk_window_size=1000,
        )
        assert svc._chunk_window_size == 1000

    def test_default_embedder_is_hash_embedder(self):
        svc = ExcelVectorIngestApplicationService(vector_store=MagicMock())
        assert isinstance(svc._embedder, HashEmbedder)

    def test_custom_embedder_used(self):
        custom = MagicMock()
        svc = ExcelVectorIngestApplicationService(
            vector_store=MagicMock(),
            embedder=custom,
        )
        assert svc._embedder is custom


# ---------------------------------------------------------------------------
# ingest_excel — branch coverage
# ---------------------------------------------------------------------------


class TestIngestExcelBranches:
    @pytest.fixture
    def mock_store(self):
        store = MagicMock()
        store.upsert_chunks.return_value = 5
        return store

    @pytest.fixture
    def svc(self, mock_store):
        return ExcelVectorIngestApplicationService(
            vector_store=mock_store,
            embedder=HashEmbedder(dimensions=64),
        )

    def test_nonexistent_file_returns_failure(self, svc):
        result = svc.ingest_excel("/nonexistent/path/file.xlsx")
        assert result["success"] is False
        assert "不存在" in result["message"]

    def test_empty_excel_returns_failure(self, svc, mock_store, tmp_path):
        df = pd.DataFrame()
        file_path = tmp_path / "empty.xlsx"
        df.to_excel(str(file_path), index=False)
        result = svc.ingest_excel(str(file_path))
        assert result["success"] is False
        assert "没有可索引" in result["message"]

    def test_successful_ingest_without_create_or_update_index(self, svc, mock_store, tmp_path):
        # Ensure create_or_update_index is NOT present
        if hasattr(mock_store, "create_or_update_index"):
            delattr(mock_store, "create_or_update_index")
        df = pd.DataFrame({"col": ["val1", "val2"]})
        file_path = tmp_path / "test.xlsx"
        df.to_excel(str(file_path), index=False)
        result = svc.ingest_excel(str(file_path))
        assert result["success"] is True
        assert result["chunk_count"] == 5

    def test_successful_ingest_with_create_or_update_index(self, svc, mock_store, tmp_path):
        mock_store.create_or_update_index = MagicMock()
        df = pd.DataFrame({"col": ["val1"]})
        file_path = tmp_path / "test.xlsx"
        df.to_excel(str(file_path), index=False)
        result = svc.ingest_excel(str(file_path))
        assert result["success"] is True
        mock_store.create_or_update_index.assert_called_once()

    def test_index_name_defaults_to_path_stem(self, svc, mock_store, tmp_path):
        df = pd.DataFrame({"col": ["val"]})
        file_path = tmp_path / "my_index_name.xlsx"
        df.to_excel(str(file_path), index=False)
        result = svc.ingest_excel(str(file_path))
        assert result["success"] is True
        assert result["index_name"] == "my_index_name"

    def test_index_id_generated_when_not_provided(self, svc, mock_store, tmp_path):
        df = pd.DataFrame({"col": ["val"]})
        file_path = tmp_path / "test.xlsx"
        df.to_excel(str(file_path), index=False)
        result = svc.ingest_excel(str(file_path))
        assert result["success"] is True
        assert "index_id" in result
        assert len(result["index_id"]) > 0

    def test_index_name_explicit_overrides_stem(self, svc, mock_store, tmp_path):
        df = pd.DataFrame({"col": ["val"]})
        file_path = tmp_path / "test.xlsx"
        df.to_excel(str(file_path), index=False)
        result = svc.ingest_excel(str(file_path), index_name="custom name")
        assert result["success"] is True
        assert result["index_name"] == "custom name"

    def test_index_name_strips_whitespace(self, svc, mock_store, tmp_path):
        df = pd.DataFrame({"col": ["val"]})
        file_path = tmp_path / "test.xlsx"
        df.to_excel(str(file_path), index=False)
        result = svc.ingest_excel(str(file_path), index_name="  spaced  ")
        assert result["success"] is True
        assert result["index_name"] == "spaced"

    def test_source_file_in_result(self, svc, mock_store, tmp_path):
        df = pd.DataFrame({"col": ["val"]})
        file_path = tmp_path / "source_test.xlsx"
        df.to_excel(str(file_path), index=False)
        result = svc.ingest_excel(str(file_path))
        assert result["success"] is True
        assert result["source_file"] == "source_test.xlsx"


# ---------------------------------------------------------------------------
# _build_chunks — branch coverage (via ingest_excel)
# ---------------------------------------------------------------------------


class TestBuildChunksBranches:
    @pytest.fixture
    def svc(self):
        store = MagicMock()
        store.upsert_chunks.return_value = 0
        store.create_or_update_index = MagicMock()
        return ExcelVectorIngestApplicationService(
            vector_store=store,
            embedder=HashEmbedder(dimensions=64),
        )

    def test_df_with_none_values_filled(self, svc, tmp_path):
        df = pd.DataFrame({"col": ["val", None, "val3"]})
        file_path = tmp_path / "none_vals.xlsx"
        df.to_excel(str(file_path), index=False)
        result = svc.ingest_excel(str(file_path))
        assert result["success"] is True

    def test_row_with_all_empty_values_skipped(self, svc, tmp_path):
        # Row where all values are empty/NaN after fillna
        df = pd.DataFrame({"col": ["val1", "", "val3"]})
        file_path = tmp_path / "empty_row.xlsx"
        df.to_excel(str(file_path), index=False)
        result = svc.ingest_excel(str(file_path))
        assert result["success"] is True

    def test_multiple_sheets_one_empty(self, svc, tmp_path):
        with pd.ExcelWriter(str(tmp_path / "multi.xlsx")) as writer:
            pd.DataFrame({"A": [1, 2]}).to_excel(writer, sheet_name="Sheet1", index=False)
            # Empty sheet
            pd.DataFrame().to_excel(writer, sheet_name="Empty", index=False)
        result = svc.ingest_excel(str(tmp_path / "multi.xlsx"))
        assert result["success"] is True

    def test_columns_with_non_string_names(self, svc, tmp_path):
        # Use column names that are numeric strings to exercise str() conversion
        df = pd.DataFrame({"1": ["a"], "2": ["b"]})
        file_path = tmp_path / "numeric_cols.xlsx"
        df.to_excel(str(file_path), index=False)
        result = svc.ingest_excel(str(file_path))
        assert result["success"] is True

    def test_large_number_of_rows_multiple_windows(self, tmp_path):
        store = MagicMock()
        store.upsert_chunks.return_value = 0
        store.create_or_update_index = MagicMock()
        svc = ExcelVectorIngestApplicationService(
            vector_store=store,
            embedder=HashEmbedder(dimensions=64),
            chunk_window_size=5,
        )
        df = pd.DataFrame({"col": range(12)})  # 12 rows, window=5 -> 3 windows
        file_path = tmp_path / "large.xlsx"
        df.to_excel(str(file_path), index=False)
        result = svc.ingest_excel(str(file_path))
        assert result["success"] is True

    def test_window_with_all_empty_rows_skipped(self, svc, tmp_path):
        # All rows in a window are empty -> window chunk skipped
        df = pd.DataFrame({"col": ["", "", ""]})
        file_path = tmp_path / "all_empty.xlsx"
        df.to_excel(str(file_path), index=False)
        result = svc.ingest_excel(str(file_path))
        # All rows empty -> no chunks -> failure
        assert result["success"] is False

    def test_single_row_excel(self, svc, tmp_path):
        df = pd.DataFrame({"col": ["single"]})
        file_path = tmp_path / "single.xlsx"
        df.to_excel(str(file_path), index=False)
        result = svc.ingest_excel(str(file_path))
        assert result["success"] is True


# ---------------------------------------------------------------------------
# ExcelVectorSearchApplicationService — branch coverage
# ---------------------------------------------------------------------------


class TestSearchServiceBranches:
    def test_init_default_embedder(self):
        svc = ExcelVectorSearchApplicationService(vector_store=MagicMock())
        assert isinstance(svc._embedder, HashEmbedder)

    def test_init_custom_embedder(self):
        custom = MagicMock()
        svc = ExcelVectorSearchApplicationService(
            vector_store=MagicMock(),
            embedder=custom,
        )
        assert svc._embedder is custom

    def test_query_empty_index_id_returns_failure(self):
        svc = ExcelVectorSearchApplicationService(vector_store=MagicMock())
        result = svc.query("", "search text")
        assert result["success"] is False
        assert "index_id" in result["message"]

    def test_query_empty_query_returns_failure(self):
        svc = ExcelVectorSearchApplicationService(vector_store=MagicMock())
        result = svc.query("idx1", "")
        assert result["success"] is False
        assert "query" in result["message"]

    def test_query_none_index_id_returns_failure(self):
        svc = ExcelVectorSearchApplicationService(vector_store=MagicMock())
        result = svc.query(None, "search text")
        assert result["success"] is False

    def test_query_none_query_returns_failure(self):
        svc = ExcelVectorSearchApplicationService(vector_store=MagicMock())
        result = svc.query("idx1", None)
        assert result["success"] is False

    def test_query_default_top_k(self):
        store = MagicMock()
        store.query.return_value = []
        svc = ExcelVectorSearchApplicationService(vector_store=store)
        result = svc.query("idx1", "search")
        assert result["success"] is True
        assert result["top_k"] == 5

    def test_query_custom_top_k(self):
        store = MagicMock()
        store.query.return_value = []
        svc = ExcelVectorSearchApplicationService(vector_store=store)
        result = svc.query("idx1", "search", top_k=20)
        assert result["success"] is True
        assert result["top_k"] == 20

    def test_query_returns_hits(self):
        store = MagicMock()
        store.query.return_value = [{"chunk_id": "c1", "score": 0.9}]
        svc = ExcelVectorSearchApplicationService(vector_store=store)
        result = svc.query("idx1", "search")
        assert result["success"] is True
        assert len(result["hits"]) == 1

    def test_list_indexes_returns_indexes(self):
        store = MagicMock()
        store.list_indexes.return_value = [{"id": "1"}, {"id": "2"}]
        svc = ExcelVectorSearchApplicationService(vector_store=store)
        result = svc.list_indexes()
        assert result["success"] is True
        assert len(result["indexes"]) == 2

    def test_list_indexes_empty(self):
        store = MagicMock()
        store.list_indexes.return_value = []
        svc = ExcelVectorSearchApplicationService(vector_store=store)
        result = svc.list_indexes()
        assert result["success"] is True
        assert result["indexes"] == []

    def test_delete_index_success(self):
        store = MagicMock()
        store.delete_index.return_value = True
        svc = ExcelVectorSearchApplicationService(vector_store=store)
        result = svc.delete_index("idx1")
        assert result["success"] is True
        assert result["index_id"] == "idx1"

    def test_delete_index_failure(self):
        store = MagicMock()
        store.delete_index.return_value = False
        svc = ExcelVectorSearchApplicationService(vector_store=store)
        result = svc.delete_index("idx1")
        assert result["success"] is False

    def test_query_includes_query_text_in_result(self):
        store = MagicMock()
        store.query.return_value = []
        svc = ExcelVectorSearchApplicationService(vector_store=store)
        result = svc.query("idx1", "my query")
        assert result["query"] == "my query"

    def test_query_includes_index_id_in_result(self):
        store = MagicMock()
        store.query.return_value = []
        svc = ExcelVectorSearchApplicationService(vector_store=store)
        result = svc.query("my_idx", "query")
        assert result["index_id"] == "my_idx"


# ---------------------------------------------------------------------------
# _default_vector_db_path — branch coverage
# ---------------------------------------------------------------------------


class TestDefaultVectorDbPathBranches:
    def test_env_var_with_folder(self, monkeypatch, tmp_path):
        env_path = os.path.join(str(tmp_path), "subdir", "vectors.db")
        monkeypatch.setenv("EXCEL_VECTOR_DB_PATH", env_path)
        result = _default_vector_db_path()
        assert result == env_path
        assert os.path.isdir(os.path.dirname(env_path))

    def test_env_var_without_folder(self, monkeypatch, tmp_path):
        # Just a filename, no directory part
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("EXCEL_VECTOR_DB_PATH", "just_filename.db")
        result = _default_vector_db_path()
        assert result == "just_filename.db"

    def test_env_var_empty_string_uses_default(self, monkeypatch):
        monkeypatch.setenv("EXCEL_VECTOR_DB_PATH", "")
        with patch(
            "app.application.excel_vector_app_service.get_app_data_dir",
            return_value="/tmp/appdata",
        ):
            result = _default_vector_db_path()
        assert "vectors" in result
        assert "excel_vectors.db" in result

    def test_env_var_whitespace_uses_default(self, monkeypatch):
        monkeypatch.setenv("EXCEL_VECTOR_DB_PATH", "   ")
        with patch(
            "app.application.excel_vector_app_service.get_app_data_dir",
            return_value="/tmp/appdata",
        ):
            result = _default_vector_db_path()
        assert "vectors" in result

    def test_no_env_var_uses_default(self, monkeypatch):
        monkeypatch.delenv("EXCEL_VECTOR_DB_PATH", raising=False)
        with patch(
            "app.application.excel_vector_app_service.get_app_data_dir",
            return_value="/tmp/appdata",
        ):
            result = _default_vector_db_path()
        assert result == os.path.join("/tmp/appdata", "vectors", "excel_vectors.db")

    def test_default_path_creates_vectors_folder(self, monkeypatch, tmp_path):
        monkeypatch.delenv("EXCEL_VECTOR_DB_PATH", raising=False)
        with patch(
            "app.application.excel_vector_app_service.get_app_data_dir",
            return_value=str(tmp_path),
        ):
            result = _default_vector_db_path()
        assert os.path.isdir(os.path.join(str(tmp_path), "vectors"))


# ---------------------------------------------------------------------------
# get_vector_store / get_pg_vector_store / get_sqlite_vector_store — branches
# ---------------------------------------------------------------------------


class TestVectorStoreFactoryBranches:
    def test_get_vector_store_returns_existing_instance(self):
        mock_store = MagicMock()
        with patch.object(evas_mod, "_vector_store_instance", mock_store):
            result = get_vector_store()
        assert result is mock_store

    def test_get_vector_store_sqlite_fallback_enabled(self, monkeypatch):
        monkeypatch.setenv("ENABLE_SQLITE_VECTOR_FALLBACK", "1")
        mock_sqlite = MagicMock()
        with (
            patch.object(evas_mod, "_vector_store_instance", None),
            patch.object(evas_mod, "get_sqlite_vector_store", return_value=mock_sqlite),
        ):
            result = get_vector_store()
        assert result is mock_sqlite

    def test_get_vector_store_sqlite_fallback_disabled(self, monkeypatch):
        monkeypatch.setenv("ENABLE_SQLITE_VECTOR_FALLBACK", "0")
        mock_pg = MagicMock()
        with (
            patch.object(evas_mod, "_vector_store_instance", None),
            patch.object(evas_mod, "get_pg_vector_store", return_value=mock_pg),
        ):
            result = get_vector_store()
        assert result is mock_pg

    def test_get_vector_store_sqlite_fallback_empty_string(self, monkeypatch):
        # Empty string -> treated as "0" -> pg path
        monkeypatch.setenv("ENABLE_SQLITE_VECTOR_FALLBACK", "")
        mock_pg = MagicMock()
        with (
            patch.object(evas_mod, "_vector_store_instance", None),
            patch.object(evas_mod, "get_pg_vector_store", return_value=mock_pg),
        ):
            result = get_vector_store()
        assert result is mock_pg

    def test_get_pg_vector_store_no_url_raises(self, monkeypatch):
        monkeypatch.delenv("VECTOR_DB_URL", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)
        with (
            patch.object(evas_mod, "_pg_vector_store_instance", None),
            pytest.raises(ValueError, match="VECTOR_DB_URL"),
        ):
            get_pg_vector_store()

    def test_get_pg_vector_store_with_url(self, monkeypatch):
        monkeypatch.setenv("VECTOR_DB_URL", "postgresql://localhost/db")
        mock_pg = MagicMock()
        with (
            patch.object(evas_mod, "_pg_vector_store_instance", None),
            patch.object(evas_mod, "PgVectorStore", return_value=mock_pg),
        ):
            result = get_pg_vector_store()
        assert result is mock_pg

    def test_get_pg_vector_store_returns_existing(self):
        mock_pg = MagicMock()
        with patch.object(evas_mod, "_pg_vector_store_instance", mock_pg):
            result = get_pg_vector_store()
        assert result is mock_pg

    def test_get_sqlite_vector_store_creates_instance(self):
        mock_sqlite = MagicMock()
        with (
            patch.object(evas_mod, "_sqlite_vector_store_instance", None),
            patch.object(evas_mod, "SQLiteVectorStore", return_value=mock_sqlite),
            patch("app.application.excel_vector_app_service._default_vector_db_path", return_value="/tmp/test.db"),
        ):
            result = get_sqlite_vector_store()
        assert result is mock_sqlite

    def test_get_sqlite_vector_store_returns_existing(self):
        mock_sqlite = MagicMock()
        with patch.object(evas_mod, "_sqlite_vector_store_instance", mock_sqlite):
            result = get_sqlite_vector_store()
        assert result is mock_sqlite


# ---------------------------------------------------------------------------
# get_excel_vector_ingest_app_service / get_excel_vector_search_app_service
# ---------------------------------------------------------------------------


class TestAppServiceSingletonBranches:
    def test_get_ingest_service_creates_instance(self):
        with patch.object(evas_mod, "_excel_vector_ingest_service_instance", None):
            with patch.object(evas_mod, "get_vector_store", return_value=MagicMock()):
                svc = get_excel_vector_ingest_app_service()
                assert svc is not None
                assert isinstance(svc, ExcelVectorIngestApplicationService)

    def test_get_ingest_service_returns_existing(self):
        mock_svc = MagicMock()
        with patch.object(evas_mod, "_excel_vector_ingest_service_instance", mock_svc):
            result = get_excel_vector_ingest_app_service()
            assert result is mock_svc

    def test_get_search_service_creates_instance(self):
        with patch.object(evas_mod, "_excel_vector_search_service_instance", None):
            with patch.object(evas_mod, "get_vector_store", return_value=MagicMock()):
                svc = get_excel_vector_search_app_service()
                assert svc is not None
                assert isinstance(svc, ExcelVectorSearchApplicationService)

    def test_get_search_service_returns_existing(self):
        mock_svc = MagicMock()
        with patch.object(evas_mod, "_excel_vector_search_service_instance", mock_svc):
            result = get_excel_vector_search_app_service()
            assert result is mock_svc


# ---------------------------------------------------------------------------
# ExcelVectorChunk dataclass
# ---------------------------------------------------------------------------


class TestExcelVectorChunkBranches:
    def test_creation_with_defaults(self):
        chunk = ExcelVectorChunk(
            chunk_id="c1",
            content="test content",
            metadata={"key": "value"},
        )
        assert chunk.chunk_id == "c1"
        assert chunk.content == "test content"
        assert chunk.metadata == {"key": "value"}

    def test_creation_with_empty_metadata(self):
        chunk = ExcelVectorChunk(
            chunk_id="c2",
            content="",
            metadata={},
        )
        assert chunk.metadata == {}

    def test_creation_with_complex_metadata(self):
        chunk = ExcelVectorChunk(
            chunk_id="c3",
            content="complex",
            metadata={
                "source_file": "test.xlsx",
                "sheet": "Sheet1",
                "chunk_type": "row",
                "row_index": 1,
                "columns": ["a", "b"],
            },
        )
        assert chunk.metadata["chunk_type"] == "row"
        assert chunk.metadata["row_index"] == 1
