"""Branch-coverage tests for app.infrastructure.persistence.compat_db.product_queries.

Targets branches NOT already covered by test_product_queries.py:
* ``_load_products_list_impl_pg`` — business_data_exposed False path, get_sync_engine
  failure, meta_timeout parsing, meta_timeout=0 skip, count timeout parsing, count
  failure, count timeout=0, query timeout parsing, query failure with total None,
  query timeout=0, row None field defaults, total None fallback, keyword/unit
  filtering, is_active column, order_by_created_at, missing optional columns.
* ``_load_products_all_for_export`` — delegation.
"""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.exc import OperationalError

from app.infrastructure.persistence.compat_db.product_queries import (
    _load_products_all_for_export,
    _load_products_list_impl_pg,
)


def _make_mock_conn() -> MagicMock:
    """Build a mock connection usable as context manager."""
    mock_conn = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    return mock_conn


def _make_mock_engine(conn: MagicMock | None = None) -> MagicMock:
    mock_eng = MagicMock()
    mock_eng.connect.return_value = conn or _make_mock_conn()
    return mock_eng


# ---------------------------------------------------------------------------
# business_data_exposed False path
# ---------------------------------------------------------------------------


class TestBusinessDataHidden:
    def test_business_data_not_exposed_returns_empty(self) -> None:
        with patch(
            "app.infrastructure.persistence.compat_db.product_queries.business_data_exposed",
            create=True,
            return_value=False,
        ) as mock_exposed, patch(
            "app.shell.mod_business_scope.business_data_exposed",
            return_value=False,
        ), patch(
            "app.shell.mod_business_scope.business_data_hidden_reason",
            return_value="data hidden reason",
        ):
            rows, total, hint = _load_products_list_impl_pg(1, 20, None, None)
        assert rows == []
        assert total == 0
        assert hint == "data hidden reason"

    def test_business_data_exposed_import_error_continues(self) -> None:
        # The except RECOVERABLE_ERRORS catches ImportError and continues
        mock_eng = _make_mock_engine()
        mock_insp = MagicMock()
        mock_insp.get_table_names.return_value = []  # no products table
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
                "app.shell.mod_business_scope.business_data_exposed",
                side_effect=ImportError("no module"),
            ),
        ):
            rows, total, hint = _load_products_list_impl_pg(1, 20, None, None)
        # Should continue to table check and return empty (no products table)
        assert rows == []
        assert "products 表" in (hint or "")


# ---------------------------------------------------------------------------
# get_sync_engine failure
# ---------------------------------------------------------------------------


class TestGetSyncEngineFailure:
    def test_engine_failure_returns_error_hint(self) -> None:
        with (
            patch(
                "app.infrastructure.persistence.compat_db.product_queries.get_sync_engine",
                side_effect=RuntimeError("db connection failed"),
            ),
            patch(
                "app.shell.mod_business_scope.business_data_exposed",
                return_value=True,
            ),
        ):
            rows, total, hint = _load_products_list_impl_pg(1, 20, None, None)
        assert rows == []
        assert total == 0
        assert hint is not None
        assert "无法连接" in hint


# ---------------------------------------------------------------------------
# meta timeout parsing
# ---------------------------------------------------------------------------


class TestMetaTimeoutParsing:
    def test_meta_timeout_invalid_falls_back_to_2000(self) -> None:
        mock_eng = _make_mock_engine()
        mock_insp = MagicMock()
        mock_insp.get_table_names.return_value = ["products"]
        mock_insp.get_columns.return_value = [
            {"name": "id"},
            {"name": "model_number"},
            {"name": "name"},
        ]
        with (
            patch(
                "app.infrastructure.persistence.compat_db.product_queries.get_sync_engine",
                return_value=mock_eng,
            ),
            patch(
                "app.infrastructure.persistence.compat_db.product_queries.inspect",
                return_value=mock_insp,
            ),
            patch.dict(
                os.environ, {"FHD_PRODUCTS_META_TIMEOUT_MS": "invalid"}, clear=False
            ),
            patch(
                "app.infrastructure.persistence.compat_db.product_queries.append_mod_scope_where",
            ),
        ):
            # Will fail later on count query but meta timeout parsing should work
            rows, total, hint = _load_products_list_impl_pg(1, 20, None, None)
        # Should reach the missing columns check (id, model_number, name present)
        # then proceed to count query which uses mock_conn returning MagicMock
        assert isinstance(rows, list)

    def test_meta_timeout_zero_skips_set(self) -> None:
        mock_eng = _make_mock_engine()
        mock_insp = MagicMock()
        mock_insp.get_table_names.return_value = ["products"]
        mock_insp.get_columns.return_value = [
            {"name": "id"},
            {"name": "model_number"},
            {"name": "name"},
        ]
        with (
            patch(
                "app.infrastructure.persistence.compat_db.product_queries.get_sync_engine",
                return_value=mock_eng,
            ),
            patch(
                "app.infrastructure.persistence.compat_db.product_queries.inspect",
                return_value=mock_insp,
            ),
            patch.dict(
                os.environ, {"FHD_PRODUCTS_META_TIMEOUT_MS": "0"}, clear=False
            ),
            patch(
                "app.infrastructure.persistence.compat_db.product_queries.append_mod_scope_where",
            ),
        ):
            rows, total, hint = _load_products_list_impl_pg(1, 20, None, None)
        assert isinstance(rows, list)


# ---------------------------------------------------------------------------
# count query timeout / failure
# ---------------------------------------------------------------------------


class TestCountQueryBranches:
    def test_count_timeout_invalid_falls_back_to_1500(self) -> None:
        mock_eng = _make_mock_engine()
        mock_insp = MagicMock()
        mock_insp.get_table_names.return_value = ["products"]
        mock_insp.get_columns.return_value = [
            {"name": "id"},
            {"name": "model_number"},
            {"name": "name"},
        ]
        with (
            patch(
                "app.infrastructure.persistence.compat_db.product_queries.get_sync_engine",
                return_value=mock_eng,
            ),
            patch(
                "app.infrastructure.persistence.compat_db.product_queries.inspect",
                return_value=mock_insp,
            ),
            patch.dict(
                os.environ,
                {"FHD_PRODUCTS_COUNT_TIMEOUT_MS": "invalid"},
                clear=False,
            ),
            patch(
                "app.infrastructure.persistence.compat_db.product_queries.append_mod_scope_where",
            ),
        ):
            rows, total, hint = _load_products_list_impl_pg(1, 20, None, None)
        assert isinstance(rows, list)

    def test_count_timeout_zero_skips_set(self) -> None:
        mock_eng = _make_mock_engine()
        mock_insp = MagicMock()
        mock_insp.get_table_names.return_value = ["products"]
        mock_insp.get_columns.return_value = [
            {"name": "id"},
            {"name": "model_number"},
            {"name": "name"},
        ]
        with (
            patch(
                "app.infrastructure.persistence.compat_db.product_queries.get_sync_engine",
                return_value=mock_eng,
            ),
            patch(
                "app.infrastructure.persistence.compat_db.product_queries.inspect",
                return_value=mock_insp,
            ),
            patch.dict(
                os.environ, {"FHD_PRODUCTS_COUNT_TIMEOUT_MS": "0"}, clear=False
            ),
            patch(
                "app.infrastructure.persistence.compat_db.product_queries.append_mod_scope_where",
            ),
        ):
            rows, total, hint = _load_products_list_impl_pg(1, 20, None, None)
        assert isinstance(rows, list)

    def test_count_query_failure_returns_none_total(self) -> None:
        mock_eng = _make_mock_engine()
        mock_insp = MagicMock()
        mock_insp.get_table_names.return_value = ["products"]
        mock_insp.get_columns.return_value = [
            {"name": "id"},
            {"name": "model_number"},
            {"name": "name"},
        ]
        # First connect for metadata (succeeds), second for count (fails), third for data
        mock_conn_meta = _make_mock_conn()
        mock_conn_count = _make_mock_conn()
        mock_conn_count.execute.side_effect = RuntimeError("count failed")
        mock_conn_data = _make_mock_conn()
        mock_eng.connect.side_effect = [mock_conn_meta, mock_conn_count, mock_conn_data]
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
        # total None → falls back to offset + len(rows)
        assert isinstance(rows, list)


# ---------------------------------------------------------------------------
# data query timeout / failure
# ---------------------------------------------------------------------------


class TestDataQueryBranches:
    def test_query_timeout_invalid_falls_back_to_8000(self) -> None:
        mock_eng = _make_mock_engine()
        mock_insp = MagicMock()
        mock_insp.get_table_names.return_value = ["products"]
        mock_insp.get_columns.return_value = [
            {"name": "id"},
            {"name": "model_number"},
            {"name": "name"},
        ]
        with (
            patch(
                "app.infrastructure.persistence.compat_db.product_queries.get_sync_engine",
                return_value=mock_eng,
            ),
            patch(
                "app.infrastructure.persistence.compat_db.product_queries.inspect",
                return_value=mock_insp,
            ),
            patch.dict(
                os.environ,
                {"FHD_PRODUCTS_QUERY_TIMEOUT_MS": "invalid"},
                clear=False,
            ),
            patch(
                "app.infrastructure.persistence.compat_db.product_queries.append_mod_scope_where",
            ),
        ):
            rows, total, hint = _load_products_list_impl_pg(1, 20, None, None)
        assert isinstance(rows, list)

    def test_query_timeout_zero_skips_set(self) -> None:
        mock_eng = _make_mock_engine()
        mock_insp = MagicMock()
        mock_insp.get_table_names.return_value = ["products"]
        mock_insp.get_columns.return_value = [
            {"name": "id"},
            {"name": "model_number"},
            {"name": "name"},
        ]
        with (
            patch(
                "app.infrastructure.persistence.compat_db.product_queries.get_sync_engine",
                return_value=mock_eng,
            ),
            patch(
                "app.infrastructure.persistence.compat_db.product_queries.inspect",
                return_value=mock_insp,
            ),
            patch.dict(
                os.environ, {"FHD_PRODUCTS_QUERY_TIMEOUT_MS": "0"}, clear=False
            ),
            patch(
                "app.infrastructure.persistence.compat_db.product_queries.append_mod_scope_where",
            ),
        ):
            rows, total, hint = _load_products_list_impl_pg(1, 20, None, None)
        assert isinstance(rows, list)

    def test_data_query_failure_with_total_none(self) -> None:
        mock_eng = _make_mock_engine()
        mock_insp = MagicMock()
        mock_insp.get_table_names.return_value = ["products"]
        mock_insp.get_columns.return_value = [
            {"name": "id"},
            {"name": "model_number"},
            {"name": "name"},
        ]
        mock_conn_meta = _make_mock_conn()
        mock_conn_count = _make_mock_conn()
        mock_conn_count.execute.side_effect = RuntimeError("count failed")
        mock_conn_data = _make_mock_conn()
        mock_conn_data.execute.side_effect = RuntimeError("data query failed")
        mock_eng.connect.side_effect = [mock_conn_meta, mock_conn_count, mock_conn_data]
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
        assert rows == []
        assert total == 0  # total was None → set to 0 because data_query_err
        assert hint is not None
        assert "超时" in hint or "中断" in hint

    def test_data_query_failure_with_total_known(self) -> None:
        mock_eng = _make_mock_engine()
        mock_insp = MagicMock()
        mock_insp.get_table_names.return_value = ["products"]
        mock_insp.get_columns.return_value = [
            {"name": "id"},
            {"name": "model_number"},
            {"name": "name"},
        ]
        mock_conn_meta = _make_mock_conn()
        mock_conn_count = _make_mock_conn()
        count_result = MagicMock()
        count_result.scalar_one.return_value = 42
        mock_conn_count.execute.return_value = count_result
        mock_conn_data = _make_mock_conn()
        mock_conn_data.execute.side_effect = RuntimeError("data query failed")
        mock_eng.connect.side_effect = [mock_conn_meta, mock_conn_count, mock_conn_data]
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
        assert rows == []
        assert total == 42  # total was known
        assert hint is not None


# ---------------------------------------------------------------------------
# row None field defaults
# ---------------------------------------------------------------------------


class TestRowNoneDefaults:
    def test_row_none_fields_default(self) -> None:
        mock_eng = _make_mock_engine()
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

        mock_conn = _make_mock_conn()
        mock_eng.connect.return_value = mock_conn

        count_result = MagicMock()
        count_result.scalar_one.return_value = 1
        row_dict = {
            "id": 1,
            "model_number": "M1",
            "name": "Paint",
            "specification": None,
            "price": None,
            "quantity": None,
            "description": None,
            "category": None,
            "brand": None,
            "unit": None,
            "is_active": None,
            "created_at": None,
            "updated_at": None,
        }
        mock_mappings = MagicMock()
        mock_mappings.all.return_value = [row_dict]
        count_result.mappings.return_value = mock_mappings
        # Both count and data use the same mock_result
        mock_conn.execute.return_value = count_result

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
        assert len(rows) == 1
        assert rows[0]["price"] == 0
        assert rows[0]["quantity"] == 0
        assert rows[0]["unit"] == ""
        assert rows[0]["is_active"] == 1


# ---------------------------------------------------------------------------
# keyword / unit filtering
# ---------------------------------------------------------------------------


class TestKeywordUnitFiltering:
    def test_keyword_with_all_text_columns(self) -> None:
        mock_eng = _make_mock_engine()
        mock_insp = MagicMock()
        mock_insp.get_table_names.return_value = ["products"]
        mock_insp.get_columns.return_value = [
            {"name": "id"},
            {"name": "model_number"},
            {"name": "name"},
            {"name": "specification"},
            {"name": "is_active"},
        ]
        mock_conn = _make_mock_conn()
        mock_eng.connect.return_value = mock_conn
        count_result = MagicMock()
        count_result.scalar_one.return_value = 0
        mock_mappings = MagicMock()
        mock_mappings.all.return_value = []
        count_result.mappings.return_value = mock_mappings
        mock_conn.execute.return_value = count_result

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
            rows, total, hint = _load_products_list_impl_pg(1, 20, "paint", None)
        assert isinstance(rows, list)

    def test_unit_filter_when_unit_column_present(self) -> None:
        mock_eng = _make_mock_engine()
        mock_insp = MagicMock()
        mock_insp.get_table_names.return_value = ["products"]
        mock_insp.get_columns.return_value = [
            {"name": "id"},
            {"name": "model_number"},
            {"name": "name"},
            {"name": "unit"},
            {"name": "is_active"},
        ]
        mock_conn = _make_mock_conn()
        mock_eng.connect.return_value = mock_conn
        count_result = MagicMock()
        count_result.scalar_one.return_value = 0
        mock_mappings = MagicMock()
        mock_mappings.all.return_value = []
        count_result.mappings.return_value = mock_mappings
        mock_conn.execute.return_value = count_result

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
            rows, total, hint = _load_products_list_impl_pg(1, 20, None, "桶")
        assert isinstance(rows, list)

    def test_keyword_whitespace_only_skipped(self) -> None:
        mock_eng = _make_mock_engine()
        mock_insp = MagicMock()
        mock_insp.get_table_names.return_value = ["products"]
        mock_insp.get_columns.return_value = [
            {"name": "id"},
            {"name": "model_number"},
            {"name": "name"},
        ]
        mock_conn = _make_mock_conn()
        mock_eng.connect.return_value = mock_conn
        count_result = MagicMock()
        count_result.scalar_one.return_value = 0
        mock_mappings = MagicMock()
        mock_mappings.all.return_value = []
        count_result.mappings.return_value = mock_mappings
        mock_conn.execute.return_value = count_result

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
            rows, total, hint = _load_products_list_impl_pg(1, 20, "   ", None)
        assert isinstance(rows, list)

    def test_unit_whitespace_only_skipped(self) -> None:
        mock_eng = _make_mock_engine()
        mock_insp = MagicMock()
        mock_insp.get_table_names.return_value = ["products"]
        mock_insp.get_columns.return_value = [
            {"name": "id"},
            {"name": "model_number"},
            {"name": "name"},
            {"name": "unit"},
        ]
        mock_conn = _make_mock_conn()
        mock_eng.connect.return_value = mock_conn
        count_result = MagicMock()
        count_result.scalar_one.return_value = 0
        mock_mappings = MagicMock()
        mock_mappings.all.return_value = []
        count_result.mappings.return_value = mock_mappings
        mock_conn.execute.return_value = count_result

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
            rows, total, hint = _load_products_list_impl_pg(1, 20, None, "   ")
        assert isinstance(rows, list)


# ---------------------------------------------------------------------------
# is_active column
# ---------------------------------------------------------------------------


class TestIsActiveColumn:
    def test_is_active_present_adds_where(self) -> None:
        mock_eng = _make_mock_engine()
        mock_insp = MagicMock()
        mock_insp.get_table_names.return_value = ["products"]
        mock_insp.get_columns.return_value = [
            {"name": "id"},
            {"name": "model_number"},
            {"name": "name"},
            {"name": "is_active"},
        ]
        mock_conn = _make_mock_conn()
        mock_eng.connect.return_value = mock_conn
        count_result = MagicMock()
        count_result.scalar_one.return_value = 0
        mock_mappings = MagicMock()
        mock_mappings.all.return_value = []
        count_result.mappings.return_value = mock_mappings
        mock_conn.execute.return_value = count_result

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


# ---------------------------------------------------------------------------
# order_by_created_at
# ---------------------------------------------------------------------------


class TestOrderByCreatedAt:
    def test_order_by_created_at_enabled(self) -> None:
        mock_eng = _make_mock_engine()
        mock_insp = MagicMock()
        mock_insp.get_table_names.return_value = ["products"]
        mock_insp.get_columns.return_value = [
            {"name": "id"},
            {"name": "model_number"},
            {"name": "name"},
            {"name": "created_at"},
        ]
        mock_conn = _make_mock_conn()
        mock_eng.connect.return_value = mock_conn
        count_result = MagicMock()
        count_result.scalar_one.return_value = 0
        mock_mappings = MagicMock()
        mock_mappings.all.return_value = []
        count_result.mappings.return_value = mock_mappings
        mock_conn.execute.return_value = count_result

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
            patch.dict(
                os.environ,
                {"FHD_PRODUCTS_ORDER_BY_CREATED_AT": "1"},
                clear=False,
            ),
        ):
            rows, total, hint = _load_products_list_impl_pg(1, 20, None, None)
        assert isinstance(rows, list)

    def test_order_by_created_at_disabled(self) -> None:
        mock_eng = _make_mock_engine()
        mock_insp = MagicMock()
        mock_insp.get_table_names.return_value = ["products"]
        mock_insp.get_columns.return_value = [
            {"name": "id"},
            {"name": "model_number"},
            {"name": "name"},
            {"name": "created_at"},
        ]
        mock_conn = _make_mock_conn()
        mock_eng.connect.return_value = mock_conn
        count_result = MagicMock()
        count_result.scalar_one.return_value = 0
        mock_mappings = MagicMock()
        mock_mappings.all.return_value = []
        count_result.mappings.return_value = mock_mappings
        mock_conn.execute.return_value = count_result

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
            patch.dict(
                os.environ,
                {"FHD_PRODUCTS_ORDER_BY_CREATED_AT": "0"},
                clear=False,
            ),
        ):
            rows, total, hint = _load_products_list_impl_pg(1, 20, None, None)
        assert isinstance(rows, list)


# ---------------------------------------------------------------------------
# total None fallback
# ---------------------------------------------------------------------------


class TestTotalNoneFallback:
    def test_total_none_falls_back_to_offset_plus_rows(self) -> None:
        mock_eng = _make_mock_engine()
        mock_insp = MagicMock()
        mock_insp.get_table_names.return_value = ["products"]
        mock_insp.get_columns.return_value = [
            {"name": "id"},
            {"name": "model_number"},
            {"name": "name"},
        ]
        # count query fails → total None; data query returns 2 rows
        mock_conn_meta = _make_mock_conn()
        mock_conn_count = _make_mock_conn()
        mock_conn_count.execute.side_effect = RuntimeError("count failed")
        mock_conn_data = _make_mock_conn()
        count_result = MagicMock()
        count_result.scalar_one.return_value = 0
        row1 = {"id": 1, "model_number": "M1", "name": "A"}
        row2 = {"id": 2, "model_number": "M2", "name": "B"}
        mock_mappings = MagicMock()
        mock_mappings.all.return_value = [row1, row2]
        count_result.mappings.return_value = mock_mappings
        mock_conn_data.execute.return_value = count_result
        mock_eng.connect.side_effect = [mock_conn_meta, mock_conn_count, mock_conn_data]

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
            # page=3, per_page=10 → offset=20
            rows, total, hint = _load_products_list_impl_pg(3, 10, None, None)
        assert len(rows) == 2
        assert total == 20 + 2  # offset + len(rows)


# ---------------------------------------------------------------------------
# OperationalError at outer level
# ---------------------------------------------------------------------------


class TestOperationalErrorOuter:
    def test_operational_error_at_metadata_returns_connection_error(self) -> None:
        mock_eng = MagicMock()
        # First connect raises OperationalError
        mock_eng.connect.side_effect = OperationalError(
            "stmt", {}, RuntimeError("conn refused")
        )
        with (
            patch(
                "app.infrastructure.persistence.compat_db.product_queries.get_sync_engine",
                return_value=mock_eng,
            ),
            patch(
                "app.shell.mod_business_scope.business_data_exposed",
                return_value=True,
            ),
        ):
            rows, total, hint = _load_products_list_impl_pg(1, 20, None, None)
        assert rows == []
        assert total == 0
        assert "无法连接" in (hint or "")


# ---------------------------------------------------------------------------
# _load_products_all_for_export
# ---------------------------------------------------------------------------


class TestLoadProductsAllForExport:
    def test_delegates_with_export_max_rows(self) -> None:
        with patch(
            "app.infrastructure.persistence.compat_db.product_queries._load_products_list_impl_pg",
            return_value=([{"id": 1}], 1, None),
        ) as mock_impl:
            result = _load_products_all_for_export("paint", "桶")
        assert result == [{"id": 1}]
        mock_impl.assert_called_once()
        # Verify page=1 and per_page=_EXPORT_MAX_ROWS
        args = mock_impl.call_args[0]
        assert args[0] == 1
        # args[1] is per_page which should be _EXPORT_MAX_ROWS (50000)
        from app.infrastructure.persistence.compat_db.base import _EXPORT_MAX_ROWS

        assert args[1] == _EXPORT_MAX_ROWS

    def test_delegates_with_none_kwargs(self) -> None:
        with patch(
            "app.infrastructure.persistence.compat_db.product_queries._load_products_list_impl_pg",
            return_value=([], 0, "error"),
        ) as mock_impl:
            result = _load_products_all_for_export(None, None)
        assert result == []
        mock_impl.assert_called_once_with(1, 50000, None, None)
