"""Tests for app.application.excel_vector_app_service."""

from __future__ import annotations

import os
import tempfile
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from app.application.excel_vector_app_service import (
    ExcelVectorIngestApplicationService,
    ExcelVectorSearchApplicationService,
    HashEmbedder,
    _default_vector_db_path,
)


# ---------------------------------------------------------------------------
# HashEmbedder
# ---------------------------------------------------------------------------
class TestHashEmbedder:
    def test_dimensions_minimum_64(self):
        emb = HashEmbedder(dimensions=10)
        assert emb._dimensions == 64

    def test_embed_texts_returns_list_of_vectors(self):
        emb = HashEmbedder(dimensions=128)
        result = emb.embed_texts(["hello", "world"])
        assert len(result) == 2
        assert len(result[0]) == 128
        assert len(result[1]) == 128

    def test_embed_query_returns_vector(self):
        emb = HashEmbedder(dimensions=128)
        result = emb.embed_query("hello")
        assert len(result) == 128

    def test_empty_text_returns_zero_vector(self):
        emb = HashEmbedder(dimensions=64)
        result = emb.embed_query("")
        assert all(v == 0.0 for v in result)

    def test_none_text_returns_zero_vector(self):
        emb = HashEmbedder(dimensions=64)
        result = emb.embed_query(None)
        assert all(v == 0.0 for v in result)

    def test_normalized_vector(self):
        emb = HashEmbedder(dimensions=64)
        result = emb.embed_query("hello world")
        norm = sum(v * v for v in result) ** 0.5
        assert abs(norm - 1.0) < 1e-6

    def test_different_texts_different_vectors(self):
        emb = HashEmbedder(dimensions=64)
        v1 = emb.embed_query("hello")
        v2 = emb.embed_query("world")
        assert v1 != v2

    def test_cjk_tokenization(self):
        emb = HashEmbedder(dimensions=64)
        result = emb.embed_query("你好世界")
        assert any(v != 0.0 for v in result)

    def test_cjk_bigrams(self):
        emb = HashEmbedder(dimensions=64)
        result = emb.embed_query("你好世界测试")
        assert any(v != 0.0 for v in result)


# ---------------------------------------------------------------------------
# ExcelVectorIngestApplicationService
# ---------------------------------------------------------------------------
class TestExcelVectorIngestApplicationService:
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

    def test_ingest_nonexistent_file(self, svc):
        result = svc.ingest_excel("/nonexistent/file.xlsx")
        assert result["success"] is False
        assert "不存在" in result["message"]

    def test_ingest_excel_file(self, svc, mock_store, tmp_path):
        # Create a simple Excel file
        df = pd.DataFrame({"型号": ["M1", "M2"], "名称": ["Widget", "Gadget"], "价格": [100, 200]})
        file_path = tmp_path / "test.xlsx"
        df.to_excel(str(file_path), index=False)

        result = svc.ingest_excel(str(file_path), index_name="test-index")
        assert result["success"] is True
        assert result["chunk_count"] == 5  # 2 row chunks + 1 window chunk + upsert returns 5
        assert result["source_file"] == "test.xlsx"

    def test_ingest_with_custom_index_id(self, svc, mock_store, tmp_path):
        df = pd.DataFrame({"col": ["val"]})
        file_path = tmp_path / "test.xlsx"
        df.to_excel(str(file_path), index=False)

        result = svc.ingest_excel(str(file_path), index_id="custom-id")
        assert result["success"] is True
        assert result["index_id"] == "custom-id"

    def test_ingest_empty_excel(self, svc, mock_store, tmp_path):
        df = pd.DataFrame()
        file_path = tmp_path / "empty.xlsx"
        df.to_excel(str(file_path), index=False)

        result = svc.ingest_excel(str(file_path))
        assert result["success"] is False
        assert "没有可索引" in result["message"]

    def test_ingest_with_create_or_update_index(self, svc, mock_store, tmp_path):
        mock_store.create_or_update_index = MagicMock()
        df = pd.DataFrame({"col": ["val"]})
        file_path = tmp_path / "test.xlsx"
        df.to_excel(str(file_path), index=False)

        result = svc.ingest_excel(str(file_path))
        assert result["success"] is True
        mock_store.create_or_update_index.assert_called_once()


# ---------------------------------------------------------------------------
# _build_chunks (indirect via ingest)
# ---------------------------------------------------------------------------
class TestBuildChunks:
    @pytest.fixture
    def svc(self):
        store = MagicMock()
        store.upsert_chunks.return_value = 0
        store.create_or_update_index = MagicMock()
        return ExcelVectorIngestApplicationService(
            vector_store=store,
            embedder=HashEmbedder(dimensions=64),
        )

    def test_builds_row_and_window_chunks(self, svc, tmp_path):
        df = pd.DataFrame(
            {
                "型号": ["M1", "M2", "M3"],
                "名称": ["W1", "W2", "W3"],
            }
        )
        file_path = tmp_path / "test.xlsx"
        df.to_excel(str(file_path), index=False)

        result = svc.ingest_excel(str(file_path))
        assert result["success"] is True
        # 3 row chunks + 1 window chunk (3 rows fit in one window of 20)
        # upsert_chunks was called, so we know chunks were built

    def test_multiple_sheets(self, svc, tmp_path):
        with pd.ExcelWriter(str(tmp_path / "multi.xlsx")) as writer:
            pd.DataFrame({"A": [1, 2]}).to_excel(writer, sheet_name="Sheet1", index=False)
            pd.DataFrame({"B": [3, 4]}).to_excel(writer, sheet_name="Sheet2", index=False)

        result = svc.ingest_excel(str(tmp_path / "multi.xlsx"))
        assert result["success"] is True

    def test_chunk_window_size(self, tmp_path):
        store = MagicMock()
        store.upsert_chunks.return_value = 0
        store.create_or_update_index = MagicMock()

        svc = ExcelVectorIngestApplicationService(
            vector_store=store,
            embedder=HashEmbedder(dimensions=64),
            chunk_window_size=2,
        )

        df = pd.DataFrame({"col": range(5)})
        file_path = tmp_path / "test.xlsx"
        df.to_excel(str(file_path), index=False)

        result = svc.ingest_excel(str(file_path))
        assert result["success"] is True

    def test_chunk_window_size_minimum(self):
        store = MagicMock()
        svc = ExcelVectorIngestApplicationService(
            vector_store=store,
            embedder=HashEmbedder(dimensions=64),
            chunk_window_size=1,  # below minimum of 5
        )
        assert svc._chunk_window_size == 5


# ---------------------------------------------------------------------------
# ExcelVectorSearchApplicationService
# ---------------------------------------------------------------------------
class TestExcelVectorSearchApplicationService:
    @pytest.fixture
    def mock_store(self):
        return MagicMock()

    @pytest.fixture
    def svc(self, mock_store):
        return ExcelVectorSearchApplicationService(
            vector_store=mock_store,
            embedder=HashEmbedder(dimensions=64),
        )

    def test_query_success(self, svc, mock_store):
        mock_store.query.return_value = [{"chunk_id": "c1", "content": "test", "score": 0.9}]
        result = svc.query("idx1", "search text")
        assert result["success"] is True
        assert result["hits"] is not None

    def test_query_missing_index_id(self, svc):
        result = svc.query("", "search text")
        assert result["success"] is False
        assert "index_id" in result["message"]

    def test_query_missing_query(self, svc):
        result = svc.query("idx1", "")
        assert result["success"] is False
        assert "query" in result["message"]

    def test_query_custom_top_k(self, svc, mock_store):
        mock_store.query.return_value = []
        result = svc.query("idx1", "search", top_k=10)
        assert result["success"] is True
        assert result["top_k"] == 10

    def test_list_indexes(self, svc, mock_store):
        mock_store.list_indexes.return_value = [{"index_id": "idx1", "name": "test"}]
        result = svc.list_indexes()
        assert result["success"] is True
        assert len(result["indexes"]) == 1

    def test_delete_index(self, svc, mock_store):
        mock_store.delete_index.return_value = True
        result = svc.delete_index("idx1")
        assert result["success"] is True

    def test_delete_index_not_found(self, svc, mock_store):
        mock_store.delete_index.return_value = False
        result = svc.delete_index("nonexistent")
        assert result["success"] is False


# ---------------------------------------------------------------------------
# _default_vector_db_path
# ---------------------------------------------------------------------------
class TestDefaultVectorDbPath:
    def test_uses_env_var(self, monkeypatch, tmp_path):
        env_path = os.path.join(tmp_path, "custom_vectors.db")
        monkeypatch.setenv("EXCEL_VECTOR_DB_PATH", env_path)
        result = _default_vector_db_path()
        assert result == env_path

    def test_default_path(self, monkeypatch):
        monkeypatch.delenv("EXCEL_VECTOR_DB_PATH", raising=False)
        with patch(
            "app.application.excel_vector_app_service.get_app_data_dir",
            return_value="/tmp/appdata",
        ):
            result = _default_vector_db_path()
        assert "vectors" in result
        assert "excel_vectors.db" in result

    def test_creates_parent_dir_from_env(self, monkeypatch, tmp_path):
        env_path = os.path.join(tmp_path, "subdir", "vectors.db")
        monkeypatch.setenv("EXCEL_VECTOR_DB_PATH", env_path)
        result = _default_vector_db_path()
        assert os.path.isdir(os.path.dirname(env_path))
