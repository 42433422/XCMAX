"""Phase 2: extract_log_store_impl 单元测试（mock DB）。"""

from __future__ import annotations

import json
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.infrastructure.persistence.extract_log_store_impl import SQLAlchemyExtractLogStore


def _row(**kwargs):
    defaults = {
        "id": 1,
        "file_name": "test.xlsx",
        "file_path": "/tmp/test.xlsx",
        "data_type": "product",
        "total_rows": 10,
        "valid_rows": 8,
        "imported_rows": 7,
        "skipped_rows": 1,
        "failed_rows": 0,
        "status": "done",
        "error_message": None,
        "field_mapping": json.dumps({"a": "b"}),
        "created_at": datetime(2026, 1, 1, 12, 0, 0),
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


@pytest.fixture
def store() -> SQLAlchemyExtractLogStore:
    return SQLAlchemyExtractLogStore()


class TestExtractLogStoreImpl:
    def test_row_to_dict(self, store: SQLAlchemyExtractLogStore):
        d = store._row_to_dict(_row())
        assert d["file_name"] == "test.xlsx"
        assert d["field_mapping"] == {"a": "b"}
        assert d["created_at"].startswith("2026")

    def test_row_to_dict_null_mapping(self, store: SQLAlchemyExtractLogStore):
        d = store._row_to_dict(_row(field_mapping=None))
        assert d["field_mapping"] is None

    @patch("app.infrastructure.persistence.extract_log_store_impl.get_db")
    def test_find_all_pagination(self, mock_get_db: MagicMock, store: SQLAlchemyExtractLogStore):
        db = MagicMock()
        result = MagicMock()
        result.fetchall.return_value = [_row(id=i, file_name=f"f{i}.xlsx") for i in range(1, 6)]
        db.execute.return_value = result
        mock_get_db.return_value.__enter__.return_value = db

        out = store.find_all(page=1, per_page=2)
        assert out["success"] is True
        assert out["total"] == 5
        assert len(out["data"]) == 2

    @patch("app.infrastructure.persistence.extract_log_store_impl.get_db")
    def test_find_all_unit_filter(self, mock_get_db: MagicMock, store: SQLAlchemyExtractLogStore):
        db = MagicMock()
        result = MagicMock()
        result.fetchall.return_value = [
            _row(id=1, file_name="Alpha.xlsx"),
            _row(id=2, file_name="Beta.xlsx"),
        ]
        db.execute.return_value = result
        mock_get_db.return_value.__enter__.return_value = db

        out = store.find_all(unit_name="alpha")
        assert out["total"] == 1
        assert out["data"][0]["file_name"] == "Alpha.xlsx"

    @patch("app.infrastructure.persistence.extract_log_store_impl.get_db")
    def test_find_by_id_found(self, mock_get_db: MagicMock, store: SQLAlchemyExtractLogStore):
        db = MagicMock()
        result = MagicMock()
        result.fetchone.return_value = _row(id=9)
        db.execute.return_value = result
        mock_get_db.return_value.__enter__.return_value = db

        out = store.find_by_id(9)
        assert out is not None
        assert out["id"] == 9

    @patch("app.infrastructure.persistence.extract_log_store_impl.get_db")
    def test_find_by_id_missing(self, mock_get_db: MagicMock, store: SQLAlchemyExtractLogStore):
        db = MagicMock()
        result = MagicMock()
        result.fetchone.return_value = None
        db.execute.return_value = result
        mock_get_db.return_value.__enter__.return_value = db
        assert store.find_by_id(99) is None

    @patch("app.infrastructure.persistence.extract_log_store_impl.get_db")
    def test_create_success(self, mock_get_db: MagicMock, store: SQLAlchemyExtractLogStore):
        db = MagicMock()
        result = MagicMock()
        result.lastrowid = 42
        db.execute.return_value = result
        mock_get_db.return_value.__enter__.return_value = db

        out = store.create(
            {
                "file_name": "a.xlsx",
                "file_path": "/a.xlsx",
                "data_type": "product",
                "total_rows": 3,
                "field_mapping": {"col": "name"},
            }
        )
        assert out["success"] is True
        assert out["log_id"] == 42
        db.commit.assert_called_once()

    @patch("app.infrastructure.persistence.extract_log_store_impl.get_db")
    def test_delete_success(self, mock_get_db: MagicMock, store: SQLAlchemyExtractLogStore):
        db = MagicMock()
        mock_get_db.return_value.__enter__.return_value = db
        out = store.delete(1)
        assert out["success"] is True
        db.commit.assert_called_once()

    @patch("app.infrastructure.persistence.extract_log_store_impl.get_db")
    def test_clear_old(self, mock_get_db: MagicMock, store: SQLAlchemyExtractLogStore):
        db = MagicMock()
        result = MagicMock()
        result.rowcount = 3
        db.execute.return_value = result
        mock_get_db.return_value.__enter__.return_value = db
        out = store.clear_old(days=7)
        assert out["success"] is True
        assert out["deleted_count"] == 3

    @patch("app.infrastructure.persistence.extract_log_store_impl.get_db")
    def test_find_all_db_error(self, mock_get_db: MagicMock, store: SQLAlchemyExtractLogStore):
        mock_get_db.return_value.__enter__.side_effect = RuntimeError("db down")
        out = store.find_all()
        assert out["success"] is False
        assert out["data"] == []
