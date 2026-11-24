"""Tests for app.infrastructure.persistence.compat_db.writes."""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.infrastructure.persistence.compat_db.writes import (
    _customer_pg_fetch_by_id,
    _customer_pg_insert,
    _customer_pg_row_select_sql,
)

# ---------------------------------------------------------------------------
# _products_delete_by_unit_pg
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# _purchase_units_delete_by_norm_unit_pg
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# _customers_delete_by_norm_name_pg
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# _purchase_units_delete_by_id_pg
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# _customers_delete_by_id_pg
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# _products_unit_replace_pg
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# _customer_pg_row_select_sql
# ---------------------------------------------------------------------------


class TestCustomerPgRowSelectSql:
    def test_full_columns(self):
        insp = MagicMock()
        insp.get_columns.return_value = [
            {"name": "id"},
            {"name": "unit_name"},
            {"name": "contact_person"},
            {"name": "contact_phone"},
            {"name": "address"},
            {"name": "is_active"},
            {"name": "created_at"},
            {"name": "updated_at"},
        ]
        sql, sel = _customer_pg_row_select_sql(insp)
        assert "id" in sql
        assert len(sel) == 8

    def test_missing_id_raises_503(self):
        insp = MagicMock()
        insp.get_columns.return_value = [
            {"name": "unit_name"},
        ]
        with pytest.raises(HTTPException) as exc_info:
            _customer_pg_row_select_sql(insp)
        assert exc_info.value.status_code == 503

    def test_minimal_columns(self):
        insp = MagicMock()
        insp.get_columns.return_value = [
            {"name": "id"},
            {"name": "unit_name"},
        ]
        sql, sel = _customer_pg_row_select_sql(insp)
        assert "id" in sql
        assert "unit_name" in sql


# ---------------------------------------------------------------------------
# _customer_pg_fetch_by_id
# ---------------------------------------------------------------------------


class TestCustomerPgFetchById:
    def test_not_found_raises_404(self):
        eng = MagicMock()
        insp = MagicMock()
        insp.get_columns.return_value = [{"name": "id"}, {"name": "unit_name"}]
        mock_conn = MagicMock()
        mock_conn.execute.return_value.mappings.return_value.first.return_value = None
        eng.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        eng.connect.return_value.__exit__ = MagicMock(return_value=False)

        with pytest.raises(HTTPException) as exc_info:
            _customer_pg_fetch_by_id(eng, insp, 999)
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# _customer_pg_select_customers_name_by_id
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# _customer_pg_delete_anywhere
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# _customer_delete_unified
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# products_pg_update_row
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# products_pg_insert_row
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# products_pg_delete_row
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# products_pg_batch_delete_rows
# ---------------------------------------------------------------------------
