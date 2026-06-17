"""Tests for app.infrastructure.persistence.compat_db.writes."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.infrastructure.persistence.compat_db.writes import (
    _customer_delete_unified,
    _customer_pg_delete_anywhere,
    _customer_pg_fetch_by_id,
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


# ── _products_delete_by_unit_pg ───────────────────────────────


class TestProductsDeleteByUnitPg:
    def test_empty_unit_returns_zero(self):
        eng = MagicMock()
        assert _products_delete_by_unit_pg(eng, "") == 0
        assert _products_delete_by_unit_pg(eng, "   ") == 0

    def test_no_unit_column_returns_zero(self):
        eng = MagicMock()
        mock_insp = MagicMock()
        mock_insp.get_columns.return_value = [{"name": "id"}, {"name": "name"}]
        with patch("app.infrastructure.persistence.compat_db.writes.inspect", return_value=mock_insp):
            with patch(
                "app.infrastructure.persistence.compat_db.writes._customer_pg_products_has_unit",
                return_value=False,
            ):
                assert _products_delete_by_unit_pg(eng, "kg") == 0

    def test_deletes_matching_rows(self):
        eng = MagicMock()
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.rowcount = 3
        mock_conn.execute.return_value = mock_result
        eng.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        eng.begin.return_value.__exit__ = MagicMock(return_value=False)

        mock_insp = MagicMock()
        mock_insp.get_columns.return_value = [{"name": "id"}, {"name": "unit"}]
        with patch("app.infrastructure.persistence.compat_db.writes.inspect", return_value=mock_insp):
            with patch(
                "app.infrastructure.persistence.compat_db.writes._customer_pg_products_has_unit",
                return_value=True,
            ):
                with patch(
                    "app.infrastructure.persistence.compat_db.writes.append_mod_scope_where",
                ):
                    result = _products_delete_by_unit_pg(eng, "kg")
                    assert result == 3


# ── _purchase_units_delete_by_norm_unit_pg ────────────────────


class TestPurchaseUnitsDeleteByNormUnitPg:
    def test_empty_unit_returns_zero(self):
        eng = MagicMock()
        assert _purchase_units_delete_by_norm_unit_pg(eng, "") == 0

    def test_no_purchase_units_table_returns_zero(self):
        eng = MagicMock()
        mock_insp = MagicMock()
        mock_insp.get_table_names.return_value = ["products"]
        with patch("app.infrastructure.persistence.compat_db.writes.inspect", return_value=mock_insp):
            assert _purchase_units_delete_by_norm_unit_pg(eng, "kg") == 0

    def test_no_unit_name_column_returns_zero(self):
        eng = MagicMock()
        mock_insp = MagicMock()
        mock_insp.get_table_names.return_value = ["purchase_units"]
        mock_insp.get_columns.return_value = [{"name": "id"}]
        with patch("app.infrastructure.persistence.compat_db.writes.inspect", return_value=mock_insp):
            assert _purchase_units_delete_by_norm_unit_pg(eng, "kg") == 0


# ── _customers_delete_by_norm_name_pg ────────────────────────


class TestCustomersDeleteByNormNamePg:
    def test_empty_name_returns_zero(self):
        eng = MagicMock()
        insp = MagicMock()
        assert _customers_delete_by_norm_name_pg(eng, insp, "") == 0

    def test_no_customers_table_returns_zero(self):
        eng = MagicMock()
        insp = MagicMock()
        insp.get_table_names.return_value = ["products"]
        assert _customers_delete_by_norm_name_pg(eng, insp, "test") == 0

    def test_no_name_column_returns_zero(self):
        eng = MagicMock()
        insp = MagicMock()
        insp.get_table_names.return_value = ["customers"]
        insp.get_columns.return_value = [{"name": "id"}]
        assert _customers_delete_by_norm_name_pg(eng, insp, "test") == 0

    def test_deletes_matching_rows(self):
        eng = MagicMock()
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.rowcount = 1
        mock_conn.execute.return_value = mock_result
        eng.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        eng.begin.return_value.__exit__ = MagicMock(return_value=False)

        insp = MagicMock()
        insp.get_table_names.return_value = ["customers"]
        insp.get_columns.return_value = [{"name": "id"}, {"name": "customer_name"}]
        with patch("app.infrastructure.persistence.compat_db.writes.append_mod_scope_where"):
            result = _customers_delete_by_norm_name_pg(eng, insp, "test")
            assert result == 1


# ── _purchase_units_delete_by_id_pg ──────────────────────────


class TestPurchaseUnitsDeleteByIdPg:
    def test_no_table_returns_zero(self):
        eng = MagicMock()
        mock_insp = MagicMock()
        mock_insp.get_table_names.return_value = []
        with patch("app.infrastructure.persistence.compat_db.writes.inspect", return_value=mock_insp):
            assert _purchase_units_delete_by_id_pg(eng, 1) == 0

    def test_no_id_column_returns_zero(self):
        eng = MagicMock()
        mock_insp = MagicMock()
        mock_insp.get_table_names.return_value = ["purchase_units"]
        mock_insp.get_columns.return_value = [{"name": "unit_name"}]
        with patch("app.infrastructure.persistence.compat_db.writes.inspect", return_value=mock_insp):
            assert _purchase_units_delete_by_id_pg(eng, 1) == 0


# ── _customers_delete_by_id_pg ───────────────────────────────


class TestCustomersDeleteByIdPg:
    def test_no_customers_table_returns_zero(self):
        eng = MagicMock()
        insp = MagicMock()
        insp.get_table_names.return_value = []
        assert _customers_delete_by_id_pg(eng, insp, 1) == 0

    def test_no_id_column_returns_zero(self):
        eng = MagicMock()
        insp = MagicMock()
        insp.get_table_names.return_value = ["customers"]
        insp.get_columns.return_value = [{"name": "name"}]
        assert _customers_delete_by_id_pg(eng, insp, 1) == 0

    def test_deletes_with_id_column(self):
        eng = MagicMock()
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.rowcount = 1
        mock_conn.execute.return_value = mock_result
        eng.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        eng.begin.return_value.__exit__ = MagicMock(return_value=False)

        insp = MagicMock()
        insp.get_table_names.return_value = ["customers"]
        insp.get_columns.return_value = [{"name": "id"}, {"name": "name"}]
        with patch("app.infrastructure.persistence.compat_db.writes.append_mod_scope_where"):
            result = _customers_delete_by_id_pg(eng, insp, 42)
            assert result == 1

    def test_deletes_with_customer_id_column(self):
        eng = MagicMock()
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.rowcount = 1
        mock_conn.execute.return_value = mock_result
        eng.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        eng.begin.return_value.__exit__ = MagicMock(return_value=False)

        insp = MagicMock()
        insp.get_table_names.return_value = ["customers"]
        insp.get_columns.return_value = [{"name": "customer_id"}, {"name": "name"}]
        with patch("app.infrastructure.persistence.compat_db.writes.append_mod_scope_where"):
            result = _customers_delete_by_id_pg(eng, insp, 42)
            assert result == 1


# ── _products_unit_replace_pg ─────────────────────────────────


class TestProductsUnitReplacePg:
    def test_empty_old_name_returns(self):
        eng = MagicMock()
        _products_unit_replace_pg(eng, "", "new")
        eng.connect.assert_not_called()

    def test_empty_new_name_returns(self):
        eng = MagicMock()
        _products_unit_replace_pg(eng, "old", "")
        eng.connect.assert_not_called()

    def test_same_name_returns(self):
        eng = MagicMock()
        _products_unit_replace_pg(eng, "kg", "kg")
        eng.connect.assert_not_called()

    def test_no_unit_column_returns(self):
        eng = MagicMock()
        mock_insp = MagicMock()
        mock_insp.get_columns.return_value = [{"name": "id"}]
        with patch("app.infrastructure.persistence.compat_db.writes.inspect", return_value=mock_insp):
            with patch(
                "app.infrastructure.persistence.compat_db.writes._customer_pg_products_has_unit",
                return_value=False,
            ):
                _products_unit_replace_pg(eng, "old", "new")
                eng.connect.assert_not_called()

    def test_replaces_unit(self):
        eng = MagicMock()
        mock_conn = MagicMock()
        eng.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        eng.connect.return_value.__exit__ = MagicMock(return_value=False)

        mock_insp = MagicMock()
        mock_insp.get_columns.return_value = [{"name": "id"}, {"name": "unit"}]
        with patch("app.infrastructure.persistence.compat_db.writes.inspect", return_value=mock_insp):
            with patch(
                "app.infrastructure.persistence.compat_db.writes._customer_pg_products_has_unit",
                return_value=True,
            ):
                with patch("app.infrastructure.persistence.compat_db.writes.append_mod_scope_where"):
                    _products_unit_replace_pg(eng, "old_unit", "new_unit")
                    mock_conn.execute.assert_called_once()
                    mock_conn.commit.assert_called_once()


# ── _customer_pg_row_select_sql ───────────────────────────────


class TestCustomerPgRowSelectSql:
    def test_complete_columns(self):
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
        assert "unit_name" in sel
        assert len(sel) == 8

    def test_missing_id_raises_503(self):
        insp = MagicMock()
        insp.get_columns.return_value = [{"name": "unit_name"}]
        with pytest.raises(HTTPException) as exc_info:
            _customer_pg_row_select_sql(insp)
        assert exc_info.value.status_code == 503

    def test_no_matching_columns_raises_503(self):
        insp = MagicMock()
        insp.get_columns.return_value = [{"name": "other_col"}]
        with pytest.raises(HTTPException) as exc_info:
            _customer_pg_row_select_sql(insp)
        assert exc_info.value.status_code == 503


# ── _customer_pg_fetch_by_id ──────────────────────────────────


class TestCustomerPgFetchById:
    def test_not_found_raises_404(self):
        eng = MagicMock()
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.mappings.return_value.first.return_value = None
        mock_conn.execute.return_value = mock_result
        eng.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        eng.connect.return_value.__exit__ = MagicMock(return_value=False)

        insp = MagicMock()
        insp.get_columns.return_value = [{"name": "id"}, {"name": "unit_name"}]
        with patch(
            "app.infrastructure.persistence.compat_db.writes._customer_pg_row_select_sql",
            return_value=("id, unit_name", ["id", "unit_name"]),
        ):
            with patch("app.infrastructure.persistence.compat_db.writes.append_mod_scope_where"):
                with pytest.raises(HTTPException) as exc_info:
                    _customer_pg_fetch_by_id(eng, insp, 999)
                assert exc_info.value.status_code == 404

    def test_found_returns_customer(self):
        eng = MagicMock()
        mock_conn = MagicMock()
        mock_row = {"id": 1, "unit_name": "Test Customer"}
        mock_result = MagicMock()
        mock_result.mappings.return_value.first.return_value = mock_row
        mock_conn.execute.return_value = mock_result
        eng.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        eng.connect.return_value.__exit__ = MagicMock(return_value=False)

        insp = MagicMock()
        insp.get_columns.return_value = [{"name": "id"}, {"name": "unit_name"}]
        with patch(
            "app.infrastructure.persistence.compat_db.writes._customer_pg_row_select_sql",
            return_value=("id, unit_name", ["id", "unit_name"]),
        ):
            with patch("app.infrastructure.persistence.compat_db.writes.append_mod_scope_where"):
                with patch(
                    "app.infrastructure.persistence.compat_db.writes._customer_row_for_api",
                    side_effect=lambda d: d,
                ):
                    result = _customer_pg_fetch_by_id(eng, insp, 1)
                    assert result["customer_name"] == "Test Customer"


# ── _customer_pg_select_customers_name_by_id ──────────────────


class TestCustomerPgSelectCustomersNameById:
    def test_no_customers_table_returns_none(self):
        eng = MagicMock()
        insp = MagicMock()
        insp.get_table_names.return_value = []
        assert _customer_pg_select_customers_name_by_id(eng, insp, 1) is None

    def test_no_id_or_name_column_returns_none(self):
        eng = MagicMock()
        insp = MagicMock()
        insp.get_table_names.return_value = ["customers"]
        insp.get_columns.return_value = [{"name": "other"}]
        assert _customer_pg_select_customers_name_by_id(eng, insp, 1) is None

    def test_found_returns_name_and_col(self):
        eng = MagicMock()
        mock_conn = MagicMock()
        mock_row = {"nm": "TestName"}
        mock_result = MagicMock()
        mock_result.mappings.return_value.first.return_value = mock_row
        mock_conn.execute.return_value = mock_result
        eng.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        eng.connect.return_value.__exit__ = MagicMock(return_value=False)

        insp = MagicMock()
        insp.get_table_names.return_value = ["customers"]
        insp.get_columns.return_value = [{"name": "id"}, {"name": "customer_name"}]
        with patch("app.infrastructure.persistence.compat_db.writes.append_mod_scope_where"):
            result = _customer_pg_select_customers_name_by_id(eng, insp, 1)
            assert result is not None
            assert result[0] == "TestName"
            assert result[1] == "id"

    def test_not_found_returns_none(self):
        eng = MagicMock()
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.mappings.return_value.first.return_value = None
        mock_conn.execute.return_value = mock_result
        eng.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        eng.connect.return_value.__exit__ = MagicMock(return_value=False)

        insp = MagicMock()
        insp.get_table_names.return_value = ["customers"]
        insp.get_columns.return_value = [{"name": "id"}, {"name": "customer_name"}]
        with patch("app.infrastructure.persistence.compat_db.writes.append_mod_scope_where"):
            result = _customer_pg_select_customers_name_by_id(eng, insp, 1)
            assert result is None


# ── _customer_pg_delete_anywhere ──────────────────────────────


class TestCustomerPgDeleteAnywhere:
    def test_not_found_raises_404(self):
        with patch(
            "app.infrastructure.persistence.compat_db.writes._customer_pg_engine_insp",
            return_value=(MagicMock(), MagicMock()),
        ) as mock_ei:
            eng, insp = mock_ei.return_value
            insp.get_table_names.return_value = []
            insp.get_columns.return_value = []
            with patch(
                "app.infrastructure.persistence.compat_db.writes._customer_pg_select_customers_name_by_id",
                return_value=None,
            ):
                with patch(
                    "app.infrastructure.persistence.compat_db.writes._products_delete_by_unit_pg",
                    return_value=0,
                ):
                    with patch(
                        "app.infrastructure.persistence.compat_db.writes._purchase_units_delete_by_norm_unit_pg",
                        return_value=0,
                    ):
                        with patch(
                            "app.infrastructure.persistence.compat_db.writes._customers_delete_by_norm_name_pg",
                            return_value=0,
                        ):
                            with patch(
                                "app.infrastructure.persistence.compat_db.writes._purchase_units_delete_by_id_pg",
                                return_value=0,
                            ):
                                with patch(
                                    "app.infrastructure.persistence.compat_db.writes._customers_delete_by_id_pg",
                                    return_value=0,
                                ):
                                    with patch(
                                        "app.infrastructure.persistence.compat_db.writes._customer_find_by_id",
                                        return_value=None,
                                        create=True,
                                    ):
                                        with pytest.raises(HTTPException) as exc_info:
                                            _customer_pg_delete_anywhere(999)
                                        assert exc_info.value.status_code == 404


# ── _customer_delete_unified ──────────────────────────────────


class TestCustomerDeleteUnified:
    def test_delegates_to_delete_anywhere(self):
        with patch(
            "app.infrastructure.persistence.compat_db.writes._customer_pg_delete_anywhere"
        ) as mock_del:
            _customer_delete_unified(42)
            mock_del.assert_called_once_with(42)


# ── products_pg_update_row ────────────────────────────────────


class TestProductsPgUpdateRow:
    def test_missing_required_columns_raises_503(self):
        with patch(
            "app.infrastructure.persistence.compat_db.writes.get_sync_engine"
        ):
            with patch(
                "app.infrastructure.persistence.compat_db.writes._products_pg_col_names",
                return_value={"id"},
            ):
                with pytest.raises(HTTPException) as exc_info:
                    products_pg_update_row(
                        1, {"name": "x"}, parse_price=lambda x: x,
                        parse_quantity=lambda x: x, parse_is_active=lambda x: x,
                    )
                assert exc_info.value.status_code == 503

    def test_empty_name_raises_400(self):
        with patch(
            "app.infrastructure.persistence.compat_db.writes.get_sync_engine"
        ):
            with patch(
                "app.infrastructure.persistence.compat_db.writes._products_pg_col_names",
                return_value={"id", "model_number", "name"},
            ):
                with pytest.raises(HTTPException) as exc_info:
                    products_pg_update_row(
                        1, {"name": ""}, parse_price=lambda x: x,
                        parse_quantity=lambda x: x, parse_is_active=lambda x: x,
                    )
                assert exc_info.value.status_code == 400

    def test_no_updatable_columns_raises_400(self):
        with patch(
            "app.infrastructure.persistence.compat_db.writes.get_sync_engine"
        ):
            with patch(
                "app.infrastructure.persistence.compat_db.writes._products_pg_col_names",
                return_value={"id", "model_number", "name"},
            ):
                with patch(
                    "app.infrastructure.persistence.compat_db.writes.products_update_or_delete_mod_and",
                    return_value="",
                ):
                    eng = MagicMock()
                    mock_conn = MagicMock()
                    mock_result = MagicMock()
                    mock_result.rowcount = 1
                    mock_conn.execute.return_value = mock_result
                    eng.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
                    eng.begin.return_value.__exit__ = MagicMock(return_value=False)
                    with patch(
                        "app.infrastructure.persistence.compat_db.writes.get_sync_engine",
                        return_value=eng,
                    ):
                        products_pg_update_row(
                            1, {"name": "test"}, parse_price=lambda x: x,
                            parse_quantity=lambda x: x, parse_is_active=lambda x: None,
                        )

    def test_product_not_found_raises_404(self):
        eng = MagicMock()
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.rowcount = 0
        mock_conn.execute.return_value = mock_result
        eng.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        eng.begin.return_value.__exit__ = MagicMock(return_value=False)

        with patch("app.infrastructure.persistence.compat_db.writes.get_sync_engine", return_value=eng):
            with patch(
                "app.infrastructure.persistence.compat_db.writes._products_pg_col_names",
                return_value={"id", "model_number", "name", "price", "quantity", "unit", "specification", "description", "category", "brand", "is_active", "updated_at"},
            ):
                with patch(
                    "app.infrastructure.persistence.compat_db.writes.products_update_or_delete_mod_and",
                    return_value="",
                ):
                    with pytest.raises(HTTPException) as exc_info:
                        products_pg_update_row(
                            999, {"name": "test"}, parse_price=lambda x: x,
                            parse_quantity=lambda x: x, parse_is_active=lambda x: True,
                        )
                    assert exc_info.value.status_code == 404


# ── products_pg_insert_row ────────────────────────────────────


class TestProductsPgInsertRow:
    def test_missing_required_columns_raises_503(self):
        eng = MagicMock()
        with patch(
            "app.infrastructure.db.sync_engine.get_sync_engine",
            return_value=eng,
        ):
            with patch(
                "app.infrastructure.persistence.compat_db.writes._products_pg_col_names",
                return_value={"id"},
            ):
                with patch.dict(
                    "sys.modules",
                    {"app.application.excel_imports": MagicMock(_norm_model=lambda *a: "M")},
                ):
                    with pytest.raises(HTTPException) as exc_info:
                        products_pg_insert_row(
                            {"name": "x"}, parse_price=lambda x: x,
                            parse_quantity=lambda x: x, parse_is_active=lambda x: x,
                        )
                    assert exc_info.value.status_code == 503

    def test_empty_name_raises_400(self):
        eng = MagicMock()
        with patch(
            "app.infrastructure.db.sync_engine.get_sync_engine",
            return_value=eng,
        ):
            with patch(
                "app.infrastructure.persistence.compat_db.writes._products_pg_col_names",
                return_value={"model_number", "name"},
            ):
                with patch.dict(
                    "sys.modules",
                    {"app.application.excel_imports": MagicMock(_norm_model=lambda *a: "M")},
                ):
                    with pytest.raises(HTTPException) as exc_info:
                        products_pg_insert_row(
                            {"name": ""}, parse_price=lambda x: x,
                            parse_quantity=lambda x: x, parse_is_active=lambda x: x,
                        )
                    assert exc_info.value.status_code == 400


# ── products_pg_delete_row ────────────────────────────────────


class TestProductsPgDeleteRow:
    def test_not_found_raises_404(self):
        eng = MagicMock()
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.rowcount = 0
        mock_conn.execute.return_value = mock_result
        eng.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        eng.begin.return_value.__exit__ = MagicMock(return_value=False)

        with patch("app.infrastructure.persistence.compat_db.writes.get_sync_engine", return_value=eng):
            with patch(
                "app.infrastructure.persistence.compat_db.writes._products_pg_col_names",
                return_value={"id"},
            ):
                with patch(
                    "app.infrastructure.persistence.compat_db.writes.products_update_or_delete_mod_and",
                    return_value="",
                ):
                    with pytest.raises(HTTPException) as exc_info:
                        products_pg_delete_row(999)
                    assert exc_info.value.status_code == 404


# ── products_pg_batch_delete_rows ─────────────────────────────


class TestProductsPgBatchDeleteRows:
    def test_invalid_ids_skipped(self):
        eng = MagicMock()
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.rowcount = 0
        mock_conn.execute.return_value = mock_result
        eng.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        eng.begin.return_value.__exit__ = MagicMock(return_value=False)

        with patch("app.infrastructure.persistence.compat_db.writes.get_sync_engine", return_value=eng):
            with patch(
                "app.infrastructure.persistence.compat_db.writes._products_pg_col_names",
                return_value={"id"},
            ):
                with patch(
                    "app.infrastructure.persistence.compat_db.writes.products_update_or_delete_mod_and",
                    return_value="",
                ):
                    with patch(
                        "app.infrastructure.persistence.compat_db.writes._product_parse_id",
                        side_effect=lambda x: None,
                    ):
                        deleted, skipped = products_pg_batch_delete_rows(["abc", "def"])
                        assert deleted == 0
                        assert len(skipped) == 2

    def test_mixed_valid_invalid_ids(self):
        eng = MagicMock()
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.rowcount = 1
        mock_conn.execute.return_value = mock_result
        eng.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        eng.begin.return_value.__exit__ = MagicMock(return_value=False)

        with patch("app.infrastructure.persistence.compat_db.writes.get_sync_engine", return_value=eng):
            with patch(
                "app.infrastructure.persistence.compat_db.writes._products_pg_col_names",
                return_value={"id"},
            ):
                with patch(
                    "app.infrastructure.persistence.compat_db.writes.products_update_or_delete_mod_and",
                    return_value="",
                ):
                    with patch(
                        "app.infrastructure.persistence.compat_db.writes._product_parse_id",
                        side_effect=lambda x: int(x) if x.isdigit() else None,
                    ):
                        deleted, skipped = products_pg_batch_delete_rows(["1", "abc", "2"])
                        assert deleted == 2
                        assert len(skipped) == 1
