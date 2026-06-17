"""Extended tests for app.infrastructure.persistence.compat_db.writes — additional coverage."""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.infrastructure.persistence.compat_db.writes import (
    _customer_pg_delete_anywhere,
    _customer_pg_fetch_by_id,
    _customer_pg_insert,
    _customer_pg_row_select_sql,
    _customer_pg_select_customers_name_by_id,
    _customer_pg_update,
    _customers_delete_by_id_pg,
    _customers_delete_by_norm_name_pg,
    _products_delete_by_unit_pg,
    _products_pg_col_names,
    _products_unit_replace_pg,
    _purchase_units_delete_by_id_pg,
    _purchase_units_delete_by_norm_unit_pg,
    products_pg_batch_delete_rows,
    products_pg_delete_row,
    products_pg_insert_row,
    products_pg_update_row,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@contextmanager
def _patch_norm_model(return_value="M1"):
    """Temporarily inject _norm_model into app.application.excel_imports.

    The real module raises ImportError via __getattr__ (lost legacy symbol),
    so we must inject a mock before products_pg_insert_row can run.
    """
    import app.application.excel_imports as _ei

    mock_fn = MagicMock(return_value=return_value)
    _ei._norm_model = mock_fn
    try:
        yield mock_fn
    finally:
        if hasattr(_ei, "_norm_model"):
            delattr(_ei, "_norm_model")


# ---------------------------------------------------------------------------
# _products_delete_by_unit_pg
# ---------------------------------------------------------------------------


class TestProductsDeleteByUnitPg:
    def test_empty_unit_name_returns_zero(self):
        mock_eng = MagicMock()
        assert _products_delete_by_unit_pg(mock_eng, "") == 0
        assert _products_delete_by_unit_pg(mock_eng, "  ") == 0

    def test_no_unit_column_returns_zero(self):
        mock_eng = MagicMock()
        mock_insp = MagicMock()
        mock_insp.get_columns.return_value = [{"name": "id"}, {"name": "name"}]
        with (
            patch(
                "app.infrastructure.persistence.compat_db.writes.inspect", return_value=mock_insp
            ),
            patch(
                "app.infrastructure.persistence.compat_db.writes._customer_pg_products_has_unit",
                return_value=False,
            ),
        ):
            assert _products_delete_by_unit_pg(mock_eng, "TestCo") == 0


# ---------------------------------------------------------------------------
# _purchase_units_delete_by_norm_unit_pg
# ---------------------------------------------------------------------------


class TestPurchaseUnitsDeleteByNormUnitPg:
    def test_empty_name_returns_zero(self):
        mock_eng = MagicMock()
        assert _purchase_units_delete_by_norm_unit_pg(mock_eng, "") == 0

    def test_no_purchase_units_table(self):
        mock_eng = MagicMock()
        mock_insp = MagicMock()
        mock_insp.get_table_names.return_value = ["products"]
        with patch(
            "app.infrastructure.persistence.compat_db.writes.inspect", return_value=mock_insp
        ):
            assert _purchase_units_delete_by_norm_unit_pg(mock_eng, "TestCo") == 0

    def test_no_unit_name_column(self):
        mock_eng = MagicMock()
        mock_insp = MagicMock()
        mock_insp.get_table_names.return_value = ["purchase_units"]
        mock_insp.get_columns.return_value = [{"name": "id"}]
        with patch(
            "app.infrastructure.persistence.compat_db.writes.inspect", return_value=mock_insp
        ):
            assert _purchase_units_delete_by_norm_unit_pg(mock_eng, "TestCo") == 0


# ---------------------------------------------------------------------------
# _customers_delete_by_norm_name_pg
# ---------------------------------------------------------------------------


class TestCustomersDeleteByNormNamePg:
    def test_empty_name_returns_zero(self):
        mock_eng = MagicMock()
        mock_insp = MagicMock()
        assert _customers_delete_by_norm_name_pg(mock_eng, mock_insp, "") == 0

    def test_no_customers_table(self):
        mock_eng = MagicMock()
        mock_insp = MagicMock()
        mock_insp.get_table_names.return_value = ["products"]
        assert _customers_delete_by_norm_name_pg(mock_eng, mock_insp, "TestCo") == 0

    def test_no_name_column(self):
        mock_eng = MagicMock()
        mock_insp = MagicMock()
        mock_insp.get_table_names.return_value = ["customers"]
        mock_insp.get_columns.return_value = [{"name": "id"}]
        assert _customers_delete_by_norm_name_pg(mock_eng, mock_insp, "TestCo") == 0


# ---------------------------------------------------------------------------
# _purchase_units_delete_by_id_pg
# ---------------------------------------------------------------------------


class TestPurchaseUnitsDeleteByIdPg:
    def test_no_purchase_units_table(self):
        mock_eng = MagicMock()
        mock_insp = MagicMock()
        mock_insp.get_table_names.return_value = ["products"]
        with patch(
            "app.infrastructure.persistence.compat_db.writes.inspect", return_value=mock_insp
        ):
            assert _purchase_units_delete_by_id_pg(mock_eng, 1) == 0

    def test_no_id_column(self):
        mock_eng = MagicMock()
        mock_insp = MagicMock()
        mock_insp.get_table_names.return_value = ["purchase_units"]
        mock_insp.get_columns.return_value = [{"name": "unit_name"}]
        with patch(
            "app.infrastructure.persistence.compat_db.writes.inspect", return_value=mock_insp
        ):
            assert _purchase_units_delete_by_id_pg(mock_eng, 1) == 0


# ---------------------------------------------------------------------------
# _customers_delete_by_id_pg
# ---------------------------------------------------------------------------


class TestCustomersDeleteByIdPg:
    def test_no_customers_table(self):
        mock_eng = MagicMock()
        mock_insp = MagicMock()
        mock_insp.get_table_names.return_value = ["products"]
        assert _customers_delete_by_id_pg(mock_eng, mock_insp, 1) == 0

    def test_no_id_or_customer_id_column(self):
        mock_eng = MagicMock()
        mock_insp = MagicMock()
        mock_insp.get_table_names.return_value = ["customers"]
        mock_insp.get_columns.return_value = [{"name": "name"}]
        assert _customers_delete_by_id_pg(mock_eng, mock_insp, 1) == 0

    def test_uses_customer_id_column(self):
        mock_eng = MagicMock()
        mock_insp = MagicMock()
        mock_insp.get_table_names.return_value = ["customers"]
        mock_insp.get_columns.return_value = [{"name": "customer_id"}, {"name": "name"}]
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.rowcount = 1
        mock_conn.execute.return_value = mock_result
        mock_eng.begin.return_value.__enter__ = lambda s: mock_conn
        mock_eng.begin.return_value.__exit__ = MagicMock(return_value=False)
        with patch("app.infrastructure.persistence.compat_db.writes.append_mod_scope_where"):
            result = _customers_delete_by_id_pg(mock_eng, mock_insp, 1)
            assert result == 1


# ---------------------------------------------------------------------------
# _products_unit_replace_pg
# ---------------------------------------------------------------------------


class TestProductsUnitReplacePg:
    def test_empty_names_noop(self):
        mock_eng = MagicMock()
        _products_unit_replace_pg(mock_eng, "", "new")
        _products_unit_replace_pg(mock_eng, "old", "")
        _products_unit_replace_pg(mock_eng, "same", "same")
        mock_eng.assert_not_called()

    def test_no_unit_column_noop(self):
        mock_eng = MagicMock()
        mock_insp = MagicMock()
        mock_insp.get_columns.return_value = [{"name": "id"}]
        with (
            patch(
                "app.infrastructure.persistence.compat_db.writes.inspect", return_value=mock_insp
            ),
            patch(
                "app.infrastructure.persistence.compat_db.writes._customer_pg_products_has_unit",
                return_value=False,
            ),
        ):
            _products_unit_replace_pg(mock_eng, "old", "new")
            mock_eng.connect.assert_not_called()


# ---------------------------------------------------------------------------
# _customer_pg_row_select_sql
# ---------------------------------------------------------------------------


class TestCustomerPgRowSelectSql:
    def test_missing_id_raises_503(self):
        mock_insp = MagicMock()
        mock_insp.get_columns.return_value = [{"name": "unit_name"}]
        with pytest.raises(HTTPException) as exc_info:
            _customer_pg_row_select_sql(mock_insp)
        assert exc_info.value.status_code == 503

    def test_full_columns(self):
        mock_insp = MagicMock()
        mock_insp.get_columns.return_value = [
            {"name": "id"},
            {"name": "unit_name"},
            {"name": "contact_person"},
            {"name": "contact_phone"},
            {"name": "address"},
            {"name": "is_active"},
            {"name": "created_at"},
            {"name": "updated_at"},
        ]
        sql, sel = _customer_pg_row_select_sql(mock_insp)
        assert "id" in sql
        assert "unit_name" in sql
        assert len(sel) == 8


# ---------------------------------------------------------------------------
# _customer_pg_select_customers_name_by_id
# ---------------------------------------------------------------------------


class TestCustomerPgSelectCustomersNameById:
    def test_no_customers_table(self):
        mock_eng = MagicMock()
        mock_insp = MagicMock()
        mock_insp.get_table_names.return_value = ["products"]
        result = _customer_pg_select_customers_name_by_id(mock_eng, mock_insp, 1)
        assert result is None

    def test_no_id_or_name_column(self):
        mock_eng = MagicMock()
        mock_insp = MagicMock()
        mock_insp.get_table_names.return_value = ["customers"]
        mock_insp.get_columns.return_value = [{"name": "other"}]
        result = _customer_pg_select_customers_name_by_id(mock_eng, mock_insp, 1)
        assert result is None


# ---------------------------------------------------------------------------
# _customer_pg_delete_anywhere
# ---------------------------------------------------------------------------


class TestCustomerPgDeleteAnywhere:
    def test_not_found_raises_404(self):
        with patch(
            "app.infrastructure.persistence.compat_db.writes._customer_pg_engine_insp",
            return_value=(MagicMock(), MagicMock()),
        ) as mock_insp_fn:
            mock_eng, mock_insp = mock_insp_fn.return_value
            mock_insp.get_table_names.return_value = []
            mock_insp.get_columns.return_value = []
            with (
                patch(
                    "app.infrastructure.persistence.compat_db.writes._products_delete_by_unit_pg",
                    return_value=0,
                ),
                patch(
                    "app.infrastructure.persistence.compat_db.writes._purchase_units_delete_by_norm_unit_pg",
                    return_value=0,
                ),
                patch(
                    "app.infrastructure.persistence.compat_db.writes._customers_delete_by_norm_name_pg",
                    return_value=0,
                ),
                patch(
                    "app.infrastructure.persistence.compat_db.writes._purchase_units_delete_by_id_pg",
                    return_value=0,
                ),
                patch(
                    "app.infrastructure.persistence.compat_db.writes._customers_delete_by_id_pg",
                    return_value=0,
                ),
                patch(
                    "app.infrastructure.persistence.compat_db.writes._customer_pg_select_customers_name_by_id",
                    return_value=None,
                ),
                patch(
                    "app.infrastructure.persistence.compat_db.queries._customer_find_by_id",
                    return_value=None,
                    create=True,
                ),
            ):
                with pytest.raises(HTTPException) as exc_info:
                    _customer_pg_delete_anywhere(999)
                assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# products_pg_update_row
# ---------------------------------------------------------------------------


class TestProductsPgUpdateRow:
    def test_missing_required_columns_raises_503(self):
        mock_eng = MagicMock()
        with (
            patch(
                "app.infrastructure.persistence.compat_db.writes.get_sync_engine",
                return_value=mock_eng,
            ),
            patch(
                "app.infrastructure.persistence.compat_db.writes._products_pg_col_names",
                return_value={"id"},
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                products_pg_update_row(
                    1,
                    {"name": "P1"},
                    parse_price=lambda x: float(x or 0),
                    parse_quantity=lambda x: int(x or 0),
                    parse_is_active=lambda x: x,
                )
            assert exc_info.value.status_code == 503

    def test_empty_name_raises_400(self):
        mock_eng = MagicMock()
        with (
            patch(
                "app.infrastructure.persistence.compat_db.writes.get_sync_engine",
                return_value=mock_eng,
            ),
            patch(
                "app.infrastructure.persistence.compat_db.writes._products_pg_col_names",
                return_value={"id", "model_number", "name"},
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                products_pg_update_row(
                    1,
                    {"name": ""},
                    parse_price=lambda x: float(x or 0),
                    parse_quantity=lambda x: int(x or 0),
                    parse_is_active=lambda x: x,
                )
            assert exc_info.value.status_code == 400

    def test_rowcount_zero_raises_404(self):
        mock_eng = MagicMock()
        mock_result = MagicMock()
        mock_result.rowcount = 0
        mock_conn = MagicMock()
        mock_conn.execute.return_value = mock_result
        mock_eng.begin.return_value.__enter__ = lambda s: mock_conn
        mock_eng.begin.return_value.__exit__ = MagicMock(return_value=False)
        with (
            patch(
                "app.infrastructure.persistence.compat_db.writes.get_sync_engine",
                return_value=mock_eng,
            ),
            patch(
                "app.infrastructure.persistence.compat_db.writes._products_pg_col_names",
                return_value={"id", "model_number", "name", "updated_at"},
            ),
            patch(
                "app.infrastructure.persistence.compat_db.writes.products_update_or_delete_mod_and",
                return_value="",
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                products_pg_update_row(
                    999,
                    {"name": "P1"},
                    parse_price=lambda x: float(x or 0),
                    parse_quantity=lambda x: int(x or 0),
                    parse_is_active=lambda x: x,
                )
            assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# products_pg_insert_row
# ---------------------------------------------------------------------------


class TestProductsPgInsertRow:
    def test_missing_required_columns_raises_503(self):
        mock_eng = MagicMock()
        with (
            patch(
                "app.infrastructure.persistence.compat_db.writes.get_sync_engine",
                return_value=mock_eng,
            ),
            patch(
                "app.infrastructure.persistence.compat_db.writes._products_pg_col_names",
                return_value={"id"},
            ),
        ):
            with _patch_norm_model():
                with pytest.raises(HTTPException) as exc_info:
                    products_pg_insert_row(
                        {"name": "P1"},
                        parse_price=lambda x: float(x or 0),
                        parse_quantity=lambda x: int(x or 0),
                        parse_is_active=lambda x: x,
                    )
                assert exc_info.value.status_code == 503

    def test_empty_name_raises_400(self):
        mock_eng = MagicMock()
        with (
            patch(
                "app.infrastructure.persistence.compat_db.writes.get_sync_engine",
                return_value=mock_eng,
            ),
            patch(
                "app.infrastructure.persistence.compat_db.writes._products_pg_col_names",
                return_value={"model_number", "name"},
            ),
        ):
            with _patch_norm_model():
                with pytest.raises(HTTPException) as exc_info:
                    products_pg_insert_row(
                        {"name": ""},
                        parse_price=lambda x: float(x or 0),
                        parse_quantity=lambda x: int(x or 0),
                        parse_is_active=lambda x: x,
                    )
                assert exc_info.value.status_code == 400

    def test_insert_success(self):
        mock_eng = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = 42
        mock_conn = MagicMock()
        mock_conn.execute.return_value = mock_result
        mock_eng.begin.return_value.__enter__ = lambda s: mock_conn
        mock_eng.begin.return_value.__exit__ = MagicMock(return_value=False)
        with (
            patch(
                "app.infrastructure.persistence.compat_db.writes.get_sync_engine",
                return_value=mock_eng,
            ),
            patch(
                "app.infrastructure.persistence.compat_db.writes._products_pg_col_names",
                return_value={
                    "model_number",
                    "name",
                    "specification",
                    "price",
                    "quantity",
                    "unit",
                    "is_active",
                },
            ),
            patch(
                "app.infrastructure.persistence.compat_db.writes.scoped_mod_id", return_value=None
            ),
            patch(
                "app.infrastructure.persistence.compat_db.writes.products_update_or_delete_mod_and",
                return_value="",
            ),
        ):
            with _patch_norm_model():
                result = products_pg_insert_row(
                    {"name": "新产品", "model_number": "M1"},
                    parse_price=lambda x: 0,
                    parse_quantity=lambda x: 0,
                    parse_is_active=lambda x: 1,
                )
            assert result == 42


# ---------------------------------------------------------------------------
# products_pg_delete_row
# ---------------------------------------------------------------------------


class TestProductsPgDeleteRow:
    def test_not_found_raises_404(self):
        mock_eng = MagicMock()
        mock_result = MagicMock()
        mock_result.rowcount = 0
        mock_conn = MagicMock()
        mock_conn.execute.return_value = mock_result
        mock_eng.begin.return_value.__enter__ = lambda s: mock_conn
        mock_eng.begin.return_value.__exit__ = MagicMock(return_value=False)
        with (
            patch(
                "app.infrastructure.persistence.compat_db.writes.get_sync_engine",
                return_value=mock_eng,
            ),
            patch(
                "app.infrastructure.persistence.compat_db.writes._products_pg_col_names",
                return_value={"id"},
            ),
            patch(
                "app.infrastructure.persistence.compat_db.writes.products_update_or_delete_mod_and",
                return_value="",
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                products_pg_delete_row(999)
            assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# products_pg_batch_delete_rows
# ---------------------------------------------------------------------------


class TestProductsPgBatchDeleteRows:
    def test_mixed_results(self):
        mock_eng = MagicMock()
        mock_result_ok = MagicMock()
        mock_result_ok.rowcount = 1
        mock_conn = MagicMock()
        mock_conn.execute.return_value = mock_result_ok
        mock_eng.begin.return_value.__enter__ = lambda s: mock_conn
        mock_eng.begin.return_value.__exit__ = MagicMock(return_value=False)
        with (
            patch(
                "app.infrastructure.persistence.compat_db.writes.get_sync_engine",
                return_value=mock_eng,
            ),
            patch(
                "app.infrastructure.persistence.compat_db.writes._products_pg_col_names",
                return_value={"id"},
            ),
            patch(
                "app.infrastructure.persistence.compat_db.writes.products_update_or_delete_mod_and",
                return_value="",
            ),
            patch(
                "app.infrastructure.persistence.compat_db.writes._product_parse_id",
                side_effect=[1, None],
            ),
        ):
            deleted, skipped = products_pg_batch_delete_rows([1, "bad"])
            assert deleted == 1
            assert len(skipped) == 1
