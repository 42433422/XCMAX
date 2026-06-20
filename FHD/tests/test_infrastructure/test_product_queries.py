"""Tests for app.infrastructure.persistence.compat_db.product_queries — PG product list loading."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.exc import OperationalError

from app.infrastructure.persistence.compat_db.product_queries import (
    _load_products_all_for_export,
    _load_products_list_impl_pg,
)

# ---------------------------------------------------------------------------
# _load_products_list_impl_pg — tested via mocking the DB engine
# ---------------------------------------------------------------------------


class TestLoadProductsListImplPg:
    def test_operational_error_returns_connection_error(self):
        mock_eng = MagicMock()
        mock_eng.connect.side_effect = OperationalError("stmt", {}, RuntimeError("conn refused"))
        with patch(
            "app.infrastructure.persistence.compat_db.product_queries.get_sync_engine",
            return_value=mock_eng,
        ):
            rows, total, hint = _load_products_list_impl_pg(1, 20, None, None)
        assert rows == []
        assert total == 0
        assert hint is not None
        assert "无法连接" in hint

    def test_returns_empty_when_table_missing(self):
        mock_eng = MagicMock()
        mock_insp = MagicMock()
        mock_insp.get_table_names.return_value = []
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_eng.connect.return_value = mock_conn
        with (
            patch(
                "app.infrastructure.persistence.compat_db.product_queries.get_sync_engine",
                return_value=mock_eng,
            ),
            patch(
                "app.infrastructure.persistence.compat_db.product_queries.inspect",
                return_value=mock_insp,
            ),
        ):
            rows, total, hint = _load_products_list_impl_pg(1, 20, None, None)
        assert rows == []
        assert total == 0
        assert hint is not None

    def test_returns_error_when_missing_required_columns(self):
        mock_eng = MagicMock()
        mock_insp = MagicMock()
        mock_insp.get_table_names.return_value = ["products"]
        mock_insp.get_columns.return_value = [{"name": "id"}, {"name": "name"}]
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_eng.connect.return_value = mock_conn
        with (
            patch(
                "app.infrastructure.persistence.compat_db.product_queries.get_sync_engine",
                return_value=mock_eng,
            ),
            patch(
                "app.infrastructure.persistence.compat_db.product_queries.inspect",
                return_value=mock_insp,
            ),
        ):
            rows, total, hint = _load_products_list_impl_pg(1, 20, None, None)
        assert rows == []
        assert "缺少必要列" in hint

    def test_meta_query_timeout(self):
        mock_eng = MagicMock()
        mock_insp = MagicMock()
        mock_insp.get_table_names.return_value = ["products"]
        mock_insp.get_columns.side_effect = RuntimeError("timeout")
        mock_conn = MagicMock()
        mock_conn.execute.return_value.scalar_one.return_value = 0
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_eng.connect.return_value = mock_conn

        with (
            patch(
                "app.infrastructure.persistence.compat_db.product_queries.get_sync_engine",
                return_value=mock_eng,
            ),
            patch(
                "app.infrastructure.persistence.compat_db.product_queries.inspect",
                return_value=mock_insp,
            ),
        ):
            rows, total, hint = _load_products_list_impl_pg(1, 20, None, None)
        assert rows == []
        assert "元数据查询超时" in hint or "失败" in hint

    def test_successful_query_with_all_columns(self):
        mock_eng = MagicMock()
        mock_insp = MagicMock()
        mock_insp.get_table_names.return_value = ["products"]
        all_cols = [
            {"name": "id"},
            {"name": "model_number"},
            {"name": "name"},
            {"name": "specification"},
            {"name": "price"},
            {"name": "quantity"},
            {"name": "description"},
            {"name": "category"},
            {"name": "brand"},
            {"name": "unit"},
            {"name": "is_active"},
            {"name": "created_at"},
            {"name": "updated_at"},
        ]
        mock_insp.get_columns.return_value = all_cols

        # First connect() for metadata, second for count, third for data
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_eng.connect.return_value = mock_conn

        # count query returns 1
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = 1
        # data query returns rows
        row_dict = {
            "id": 1,
            "model_number": "M1",
            "name": "Paint",
            "specification": "20L",
            "price": 100,
            "quantity": 10,
            "description": "desc",
            "category": "cat",
            "brand": "brand",
            "unit": "桶",
            "is_active": 1,
            "created_at": None,
            "updated_at": None,
        }
        mock_mappings = MagicMock()
        mock_mappings.all.return_value = [row_dict]
        mock_result.mappings.return_value = mock_mappings

        # First call: metadata get_columns, then count, then data
        mock_conn.execute.return_value = mock_result

        with (
            patch(
                "app.infrastructure.persistence.compat_db.product_queries.get_sync_engine",
                return_value=mock_eng,
            ),
            patch(
                "app.infrastructure.persistence.compat_db.product_queries.inspect",
                return_value=mock_insp,
            ),
            patch(
                "app.infrastructure.persistence.compat_db.product_queries.append_mod_scope_where",
            ),
        ):
            rows, total, hint = _load_products_list_impl_pg(1, 20, None, None)
        assert isinstance(rows, list)
        assert hint is None  # No error


class TestLoadProductsAllForExport:
    def test_delegates_to_impl(self):
        with patch(
            "app.infrastructure.persistence.compat_db.product_queries._load_products_list_impl_pg",
            return_value=([{"id": 1}], 1, None),
        ) as mock_impl:
            result = _load_products_all_for_export("paint", "桶")
        assert result == [{"id": 1}]
        mock_impl.assert_called_once()
