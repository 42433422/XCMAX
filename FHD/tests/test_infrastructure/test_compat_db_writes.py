"""Tests for app.infrastructure.persistence.compat_db.writes."""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.infrastructure.persistence.compat_db.writes import (
    _customer_pg_insert,
    _customer_pg_update,
    _customer_pg_delete_anywhere,
    _customer_delete_unified,
    _products_delete_by_unit_pg,
    _purchase_units_delete_by_norm_unit_pg,
    _customers_delete_by_norm_name_pg,
    _purchase_units_delete_by_id_pg,
    _customers_delete_by_id_pg,
    _products_unit_replace_pg,
    _customer_pg_row_select_sql,
    _customer_pg_fetch_by_id,
    _customer_pg_select_customers_name_by_id,
    products_pg_update_row,
    products_pg_insert_row,
    products_pg_delete_row,
    products_pg_batch_delete_rows,
)


# ---------------------------------------------------------------------------
# Helper: patch _norm_model which is a "lost legacy symbol" that raises
# ImportError via __getattr__, so normal patch(..., create=True) fails.
# ---------------------------------------------------------------------------

@contextmanager
def _patch_norm_model(return_value="M1"):
    """Temporarily inject _norm_model into app.application.excel_imports."""
    import app.application.excel_imports as _ei
    mock_fn = MagicMock(return_value=return_value)
    setattr(_ei, "_norm_model", mock_fn)
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
        eng = MagicMock()
        assert _products_delete_by_unit_pg(eng, "") == 0
        assert _products_delete_by_unit_pg(eng, "  ") == 0
        assert _products_delete_by_unit_pg(eng, None) == 0

    @patch("app.infrastructure.persistence.compat_db.writes._customer_pg_products_has_unit")
    @patch("app.infrastructure.persistence.compat_db.writes.inspect")
    def test_no_unit_column_returns_zero(self, mock_insp, mock_has_unit):
        eng = MagicMock()
        mock_has_unit.return_value = False
        result = _products_delete_by_unit_pg(eng, "客户A")
        assert result == 0

    @patch("app.infrastructure.persistence.compat_db.writes.append_mod_scope_where")
    @patch("app.infrastructure.persistence.compat_db.writes._customer_pg_products_has_unit")
    @patch("app.infrastructure.persistence.compat_db.writes.inspect")
    def test_delete_success(self, mock_insp, mock_has_unit, mock_mod_scope):
        eng = MagicMock()
        mock_has_unit.return_value = True
        mock_insp_obj = MagicMock()
        mock_insp_obj.get_columns.return_value = [
            {"name": "id"}, {"name": "unit"}, {"name": "name"}
        ]
        mock_insp.return_value = mock_insp_obj

        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.rowcount = 3
        mock_conn.execute.return_value = mock_result
        eng.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        eng.begin.return_value.__exit__ = MagicMock(return_value=False)

        mock_mod_scope.return_value = None
        result = _products_delete_by_unit_pg(eng, "客户A")
        assert result == 3


# ---------------------------------------------------------------------------
# _purchase_units_delete_by_norm_unit_pg
# ---------------------------------------------------------------------------

class TestPurchaseUnitsDeleteByNormUnitPg:
    def test_empty_name_returns_zero(self):
        eng = MagicMock()
        assert _purchase_units_delete_by_norm_unit_pg(eng, "") == 0

    @patch("app.infrastructure.persistence.compat_db.writes.inspect")
    def test_no_purchase_units_table(self, mock_insp):
        eng = MagicMock()
        mock_insp_obj = MagicMock()
        mock_insp_obj.get_table_names.return_value = ["products"]
        mock_insp.return_value = mock_insp_obj
        result = _purchase_units_delete_by_norm_unit_pg(eng, "客户A")
        assert result == 0

    @patch("app.infrastructure.persistence.compat_db.writes.inspect")
    def test_no_unit_name_column(self, mock_insp):
        eng = MagicMock()
        mock_insp_obj = MagicMock()
        mock_insp_obj.get_table_names.return_value = ["purchase_units"]
        mock_insp_obj.get_columns.return_value = [{"name": "id"}]
        mock_insp.return_value = mock_insp_obj
        result = _purchase_units_delete_by_norm_unit_pg(eng, "客户A")
        assert result == 0


# ---------------------------------------------------------------------------
# _customers_delete_by_norm_name_pg
# ---------------------------------------------------------------------------

class TestCustomersDeleteByNormNamePg:
    def test_empty_name_returns_zero(self):
        eng = MagicMock()
        insp = MagicMock()
        assert _customers_delete_by_norm_name_pg(eng, insp, "") == 0

    def test_no_customers_table(self):
        eng = MagicMock()
        insp = MagicMock()
        insp.get_table_names.return_value = ["products"]
        result = _customers_delete_by_norm_name_pg(eng, insp, "客户A")
        assert result == 0

    def test_no_name_column(self):
        eng = MagicMock()
        insp = MagicMock()
        insp.get_table_names.return_value = ["customers"]
        insp.get_columns.return_value = [{"name": "id"}]
        result = _customers_delete_by_norm_name_pg(eng, insp, "客户A")
        assert result == 0


# ---------------------------------------------------------------------------
# _purchase_units_delete_by_id_pg
# ---------------------------------------------------------------------------

class TestPurchaseUnitsDeleteByIdPg:
    @patch("app.infrastructure.persistence.compat_db.writes.inspect")
    def test_no_purchase_units_table(self, mock_insp):
        eng = MagicMock()
        mock_insp_obj = MagicMock()
        mock_insp_obj.get_table_names.return_value = []
        mock_insp.return_value = mock_insp_obj
        result = _purchase_units_delete_by_id_pg(eng, 1)
        assert result == 0

    @patch("app.infrastructure.persistence.compat_db.writes.inspect")
    def test_no_id_column(self, mock_insp):
        eng = MagicMock()
        mock_insp_obj = MagicMock()
        mock_insp_obj.get_table_names.return_value = ["purchase_units"]
        mock_insp_obj.get_columns.return_value = [{"name": "unit_name"}]
        mock_insp.return_value = mock_insp_obj
        result = _purchase_units_delete_by_id_pg(eng, 1)
        assert result == 0


# ---------------------------------------------------------------------------
# _customers_delete_by_id_pg
# ---------------------------------------------------------------------------

class TestCustomersDeleteByIdPg:
    def test_no_customers_table(self):
        eng = MagicMock()
        insp = MagicMock()
        insp.get_table_names.return_value = []
        result = _customers_delete_by_id_pg(eng, insp, 1)
        assert result == 0

    def test_no_id_column(self):
        eng = MagicMock()
        insp = MagicMock()
        insp.get_table_names.return_value = ["customers"]
        insp.get_columns.return_value = [{"name": "customer_name"}]
        result = _customers_delete_by_id_pg(eng, insp, 1)
        assert result == 0


# ---------------------------------------------------------------------------
# _products_unit_replace_pg
# ---------------------------------------------------------------------------

class TestProductsUnitReplacePg:
    def test_empty_old_name_returns(self):
        eng = MagicMock()
        _products_unit_replace_pg(eng, "", "new")  # should not raise

    def test_empty_new_name_returns(self):
        eng = MagicMock()
        _products_unit_replace_pg(eng, "old", "")  # should not raise

    def test_same_name_returns(self):
        eng = MagicMock()
        _products_unit_replace_pg(eng, "same", "same")  # should not raise

    @patch("app.infrastructure.persistence.compat_db.writes._customer_pg_products_has_unit")
    @patch("app.infrastructure.persistence.compat_db.writes.inspect")
    def test_no_unit_column_returns(self, mock_insp, mock_has_unit):
        eng = MagicMock()
        mock_has_unit.return_value = False
        _products_unit_replace_pg(eng, "old", "new")  # should not raise


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
        insp.get_columns.return_value = [
            {"name": "id"}, {"name": "unit_name"}
        ]
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

class TestCustomerPgSelectCustomersNameById:
    def test_no_customers_table(self):
        eng = MagicMock()
        insp = MagicMock()
        insp.get_table_names.return_value = []
        result = _customer_pg_select_customers_name_by_id(eng, insp, 1)
        assert result is None

    def test_no_id_or_name_column(self):
        eng = MagicMock()
        insp = MagicMock()
        insp.get_table_names.return_value = ["customers"]
        insp.get_columns.return_value = [{"name": "other"}]
        result = _customer_pg_select_customers_name_by_id(eng, insp, 1)
        assert result is None


# ---------------------------------------------------------------------------
# _customer_pg_delete_anywhere
# ---------------------------------------------------------------------------

class TestCustomerPgDeleteAnywhere:
    @patch("app.infrastructure.persistence.compat_db.writes._customers_delete_by_id_pg")
    @patch("app.infrastructure.persistence.compat_db.writes._customers_delete_by_norm_name_pg")
    @patch("app.infrastructure.persistence.compat_db.writes._purchase_units_delete_by_norm_unit_pg")
    @patch("app.infrastructure.persistence.compat_db.writes._products_delete_by_unit_pg")
    @patch("app.infrastructure.persistence.compat_db.writes._purchase_units_delete_by_id_pg")
    @patch("app.infrastructure.persistence.compat_db.writes._customer_pg_select_customers_name_by_id")
    @patch("app.infrastructure.persistence.compat_db.writes.inspect")
    @patch("app.infrastructure.persistence.compat_db.writes._customer_pg_engine_insp")
    def test_not_found_raises_404(
        self, mock_eng_insp, mock_insp, mock_select_name,
        mock_pu_del_id, mock_prod_del, mock_pu_del_norm,
        mock_cu_del_norm, mock_cu_del_id
    ):
        mock_eng = MagicMock()
        mock_insp_obj = MagicMock()
        mock_insp_obj.get_table_names.return_value = []
        mock_insp_obj.get_columns.return_value = []
        mock_eng_insp.return_value = (mock_eng, mock_insp_obj)
        mock_insp.return_value = mock_insp_obj
        mock_select_name.return_value = None

        # All delete counts are 0
        mock_pu_del_id.return_value = 0
        mock_cu_del_id.return_value = 0
        mock_pu_del_norm.return_value = 0
        mock_cu_del_norm.return_value = 0
        mock_prod_del.return_value = 0

        with patch(
            "app.infrastructure.persistence.compat_db.queries._customer_find_by_id",
            return_value=None,
        ):
            with pytest.raises(HTTPException) as exc_info:
                _customer_pg_delete_anywhere(999)
            assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# _customer_delete_unified
# ---------------------------------------------------------------------------

class TestCustomerDeleteUnified:
    @patch("app.infrastructure.persistence.compat_db.writes._customer_pg_delete_anywhere")
    def test_delegates_to_pg_delete(self, mock_delete):
        _customer_delete_unified(1)
        mock_delete.assert_called_once_with(1)


# ---------------------------------------------------------------------------
# products_pg_update_row
# ---------------------------------------------------------------------------

class TestProductsPgUpdateRow:
    @patch("app.infrastructure.persistence.compat_db.writes._products_pg_col_names")
    @patch("app.infrastructure.persistence.compat_db.writes.get_sync_engine")
    def test_missing_required_columns_raises_503(self, mock_engine, mock_col_names):
        mock_col_names.return_value = {"id"}  # missing model_number and name
        with pytest.raises(HTTPException) as exc_info:
            products_pg_update_row(
                1, {"name": "产品"},
                parse_price=lambda x: 0,
                parse_quantity=lambda x: 0,
                parse_is_active=lambda x: None,
            )
        assert exc_info.value.status_code == 503

    @patch("app.infrastructure.persistence.compat_db.writes._products_pg_col_names")
    @patch("app.infrastructure.persistence.compat_db.writes.get_sync_engine")
    def test_empty_name_raises_400(self, mock_engine, mock_col_names):
        mock_col_names.return_value = {"id", "model_number", "name"}
        with pytest.raises(HTTPException) as exc_info:
            products_pg_update_row(
                1, {"name": ""},
                parse_price=lambda x: 0,
                parse_quantity=lambda x: 0,
                parse_is_active=lambda x: None,
            )
        assert exc_info.value.status_code == 400

    @patch("app.infrastructure.persistence.compat_db.writes.products_update_or_delete_mod_and")
    @patch("app.infrastructure.persistence.compat_db.writes._products_pg_col_names")
    @patch("app.infrastructure.persistence.compat_db.writes.get_sync_engine")
    def test_product_not_found_raises_404(self, mock_engine, mock_col_names, mock_mod_and):
        mock_col_names.return_value = {"id", "model_number", "name", "price"}
        mock_mod_and.return_value = ""
        mock_eng = MagicMock()
        mock_engine.return_value = mock_eng
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.rowcount = 0
        mock_conn.execute.return_value = mock_result
        mock_eng.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_eng.begin.return_value.__exit__ = MagicMock(return_value=False)

        with pytest.raises(HTTPException) as exc_info:
            products_pg_update_row(
                999, {"name": "产品"},
                parse_price=lambda x: 0,
                parse_quantity=lambda x: 0,
                parse_is_active=lambda x: None,
            )
        assert exc_info.value.status_code == 404

    @patch("app.infrastructure.persistence.compat_db.writes.products_update_or_delete_mod_and")
    @patch("app.infrastructure.persistence.compat_db.writes._products_pg_col_names")
    @patch("app.infrastructure.persistence.compat_db.writes.get_sync_engine")
    def test_update_success(self, mock_engine, mock_col_names, mock_mod_and):
        mock_col_names.return_value = {
            "id", "model_number", "name", "price", "quantity",
            "unit", "description", "category", "brand", "is_active",
            "updated_at",
        }
        mock_mod_and.return_value = ""
        mock_eng = MagicMock()
        mock_engine.return_value = mock_eng
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.rowcount = 1
        mock_conn.execute.return_value = mock_result
        mock_eng.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_eng.begin.return_value.__exit__ = MagicMock(return_value=False)

        # Should not raise
        products_pg_update_row(
            1, {"name": "更新产品", "price": "99.9"},
            parse_price=lambda x: float(x or 0),
            parse_quantity=lambda x: int(x or 0),
            parse_is_active=lambda x: 1,
        )


# ---------------------------------------------------------------------------
# products_pg_insert_row
# ---------------------------------------------------------------------------

class TestProductsPgInsertRow:
    @patch("app.infrastructure.persistence.compat_db.writes._products_pg_col_names")
    @patch("app.infrastructure.persistence.compat_db.writes.get_sync_engine")
    def test_missing_required_columns_raises_503(self, mock_engine, mock_col_names):
        mock_col_names.return_value = {"id"}
        with _patch_norm_model():
            with pytest.raises(HTTPException) as exc_info:
                products_pg_insert_row(
                    {"name": "产品"},
                    parse_price=lambda x: 0,
                    parse_quantity=lambda x: 0,
                    parse_is_active=lambda x: None,
                )
        assert exc_info.value.status_code == 503

    @patch("app.infrastructure.persistence.compat_db.writes._products_pg_col_names")
    @patch("app.infrastructure.persistence.compat_db.writes.get_sync_engine")
    def test_empty_name_raises_400(self, mock_engine, mock_col_names):
        mock_col_names.return_value = {"model_number", "name"}
        with _patch_norm_model():
            with pytest.raises(HTTPException) as exc_info:
                products_pg_insert_row(
                    {"name": ""},
                    parse_price=lambda x: 0,
                    parse_quantity=lambda x: 0,
                    parse_is_active=lambda x: None,
                )
        assert exc_info.value.status_code == 400

    @patch("app.infrastructure.persistence.compat_db.writes.scoped_mod_id")
    @patch("app.infrastructure.persistence.compat_db.writes._products_pg_col_names")
    @patch("app.infrastructure.persistence.compat_db.writes.get_sync_engine")
    def test_insert_success(self, mock_engine, mock_col_names, mock_mod_id):
        mock_col_names.return_value = {
            "model_number", "name", "specification", "price",
            "quantity", "unit", "description", "is_active",
        }
        mock_mod_id.return_value = None
        mock_eng = MagicMock()
        mock_engine.return_value = mock_eng
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = 42
        mock_conn.execute.return_value = mock_result
        mock_eng.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_eng.begin.return_value.__exit__ = MagicMock(return_value=False)

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
    @patch("app.infrastructure.persistence.compat_db.writes.products_update_or_delete_mod_and")
    @patch("app.infrastructure.persistence.compat_db.writes._products_pg_col_names")
    @patch("app.infrastructure.persistence.compat_db.writes.get_sync_engine")
    def test_delete_not_found_raises_404(self, mock_engine, mock_col_names, mock_mod_and):
        mock_col_names.return_value = {"id"}
        mock_mod_and.return_value = ""
        mock_eng = MagicMock()
        mock_engine.return_value = mock_eng
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.rowcount = 0
        mock_conn.execute.return_value = mock_result
        mock_eng.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_eng.begin.return_value.__exit__ = MagicMock(return_value=False)

        with pytest.raises(HTTPException) as exc_info:
            products_pg_delete_row(999)
        assert exc_info.value.status_code == 404

    @patch("app.infrastructure.persistence.compat_db.writes.products_update_or_delete_mod_and")
    @patch("app.infrastructure.persistence.compat_db.writes._products_pg_col_names")
    @patch("app.infrastructure.persistence.compat_db.writes.get_sync_engine")
    def test_delete_success(self, mock_engine, mock_col_names, mock_mod_and):
        mock_col_names.return_value = {"id"}
        mock_mod_and.return_value = ""
        mock_eng = MagicMock()
        mock_engine.return_value = mock_eng
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.rowcount = 1
        mock_conn.execute.return_value = mock_result
        mock_eng.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_eng.begin.return_value.__exit__ = MagicMock(return_value=False)

        # Should not raise
        products_pg_delete_row(1)


# ---------------------------------------------------------------------------
# products_pg_batch_delete_rows
# ---------------------------------------------------------------------------

class TestProductsPgBatchDeleteRows:
    @patch("app.infrastructure.persistence.compat_db.writes.products_update_or_delete_mod_and")
    @patch("app.infrastructure.persistence.compat_db.writes._products_pg_col_names")
    @patch("app.infrastructure.persistence.compat_db.writes.get_sync_engine")
    def test_batch_delete_mixed(self, mock_engine, mock_col_names, mock_mod_and):
        mock_col_names.return_value = {"id"}
        mock_mod_and.return_value = ""
        mock_eng = MagicMock()
        mock_engine.return_value = mock_eng
        mock_conn = MagicMock()

        # First id=1 deletes, second id=999 not found
        results = [MagicMock(rowcount=1), MagicMock(rowcount=0)]
        mock_conn.execute.side_effect = results
        mock_eng.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_eng.begin.return_value.__exit__ = MagicMock(return_value=False)

        deleted, skipped = products_pg_batch_delete_rows([1, 999])
        assert deleted == 1
        assert len(skipped) == 1

    @patch("app.infrastructure.persistence.compat_db.writes.products_update_or_delete_mod_and")
    @patch("app.infrastructure.persistence.compat_db.writes._products_pg_col_names")
    @patch("app.infrastructure.persistence.compat_db.writes.get_sync_engine")
    def test_batch_delete_invalid_id(self, mock_engine, mock_col_names, mock_mod_and):
        mock_col_names.return_value = {"id"}
        mock_mod_and.return_value = ""
        mock_eng = MagicMock()
        mock_engine.return_value = mock_eng
        mock_conn = MagicMock()
        mock_eng.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_eng.begin.return_value.__exit__ = MagicMock(return_value=False)

        deleted, skipped = products_pg_batch_delete_rows(["invalid", None])
        assert deleted == 0
        assert len(skipped) == 2
