"""Additional tests for compat_db.queries covering uncovered PG paths.

Focuses on:
- _load_purchase_units_rows_pg: business_data_exposed branches, engine/inspect errors,
  table missing, query execution, is_active filtering
- _distinct_units_from_products_db_pg: business_data_exposed, engine errors, table/column
  checks, query execution, OperationalError handling
- _load_customers_pg_from_customers_table: column detection (id/name/contact/phone/address),
  is_active filtering, query errors
- _load_customers_pg_from_purchase_units: query errors, is_active filtering, name remapping
- _load_customers_rows_pg: engine/inspect errors, customers table path, purchase_units fallback
- _load_customers_rows: business_data_exposed branches
- _customer_row_for_api: additional field combinations
- _customer_row_matches_keyword: additional field combinations
- _customer_find_by_id: type coercion
- _customers_schema_hint_if_empty: additional table combinations
- _units_select_data_unified: id type coercion, max_id calculation
- _products_units_for_select: data presence branches
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.infrastructure.persistence.compat_db.queries import (
    _customer_find_by_id,
    _customer_row_for_api,
    _customer_row_matches_keyword,
    _customer_rows_from_merged_unit_entries,
    _customers_schema_hint_if_empty,
    _distinct_units_from_products_db,
    _distinct_units_from_products_db_pg,
    _load_customers_pg_from_customers_table,
    _load_customers_pg_from_purchase_units,
    _load_customers_rows,
    _load_customers_rows_pg,
    _load_purchase_units_rows,
    _load_purchase_units_rows_pg,
    _merged_purchase_unit_entries,
    _products_units_for_select,
    _units_select_data_unified,
)


# ---------------------------------------------------------------------------
# _load_purchase_units_rows_pg — uncovered branches
# ---------------------------------------------------------------------------


class TestLoadPurchaseUnitsRowsPg:
    """Cover _load_purchase_units_rows_pg directly."""

    def test_business_not_exposed_returns_empty(self):
        """When business_data_exposed() returns False, should return []."""
        with patch(
            "app.shell.mod_business_scope.business_data_exposed",
            return_value=False,
        ):
            result = _load_purchase_units_rows_pg()
        assert result == []

    def test_business_scope_import_error_returns_empty(self):
        """When business_data_exposed import raises RECOVERABLE_ERRORS, should return []."""
        with patch(
            "app.shell.mod_business_scope.business_data_exposed",
            side_effect=OSError("import failed"),
        ):
            result = _load_purchase_units_rows_pg()
        assert result == []

    def test_engine_error_returns_empty(self):
        """When get_sync_engine raises RECOVERABLE_ERRORS, should return []."""
        mock_eng = MagicMock()
        with (
            patch(
                "app.shell.mod_business_scope.business_data_exposed",
                return_value=True,
            ),
            patch(
                "app.infrastructure.persistence.compat_db.queries.get_sync_engine",
                side_effect=OSError("no engine"),
            ),
        ):
            result = _load_purchase_units_rows_pg()
        assert result == []

    def test_table_missing_returns_empty(self):
        """When purchase_units table doesn't exist, should return []."""
        mock_eng = MagicMock()
        mock_insp = MagicMock()
        mock_insp.has_table.return_value = False

        with (
            patch(
                "app.shell.mod_business_scope.business_data_exposed",
                return_value=True,
            ),
            patch(
                "app.infrastructure.persistence.compat_db.queries.get_sync_engine",
                return_value=mock_eng,
            ),
            patch(
                "app.infrastructure.persistence.compat_db.queries.inspect",
                return_value=mock_insp,
            ),
            patch(
                "app.infrastructure.persistence.compat_db.queries._insp_table_exists",
                return_value=False,
            ),
        ):
            result = _load_purchase_units_rows_pg()
        assert result == []

    def test_query_returns_rows(self):
        """Should return rows when query succeeds."""
        mock_eng = MagicMock()
        mock_insp = MagicMock()
        mock_insp.get_columns.return_value = [
            {"name": "id"},
            {"name": "unit_name"},
            {"name": "contact_person"},
            {"name": "contact_phone"},
            {"name": "address"},
            {"name": "is_active"},
        ]

        mock_conn = MagicMock()
        mock_mapping = MagicMock()
        mock_mapping.all.return_value = [
            {"id": 1, "unit_name": "CoA", "contact_person": "Z", "contact_phone": "1",
             "address": "A", "is_active": 1},
            {"id": 2, "unit_name": "CoB", "contact_person": "", "contact_phone": "",
             "address": "", "is_active": 0},  # should be filtered out
        ]
        mock_conn.execute.return_value.mappings.return_value = mock_mapping
        mock_eng.connect.return_value.__enter__.return_value = mock_conn

        with (
            patch(
                "app.shell.mod_business_scope.business_data_exposed",
                return_value=True,
            ),
            patch(
                "app.infrastructure.persistence.compat_db.queries.get_sync_engine",
                return_value=mock_eng,
            ),
            patch(
                "app.infrastructure.persistence.compat_db.queries.inspect",
                return_value=mock_insp,
            ),
            patch(
                "app.infrastructure.persistence.compat_db.queries._insp_table_exists",
                return_value=True,
            ),
            patch(
                "app.infrastructure.persistence.compat_db.queries.append_mod_scope_where",
                return_value=None,
            ),
        ):
            result = _load_purchase_units_rows_pg()

        assert len(result) == 1
        assert result[0]["unit_name"] == "CoA"

    def test_query_undefined_table_returns_empty(self):
        """When query raises undefined table error, should return []."""
        mock_eng = MagicMock()
        mock_insp = MagicMock()
        mock_insp.get_columns.return_value = [{"name": "id"}]

        mock_conn = MagicMock()
        mock_conn.execute.side_effect = OperationalError("statement", {}, None)

        mock_eng.connect.return_value.__enter__.return_value = mock_conn

        with (
            patch(
                "app.shell.mod_business_scope.business_data_exposed",
                return_value=True,
            ),
            patch(
                "app.infrastructure.persistence.compat_db.queries.get_sync_engine",
                return_value=mock_eng,
            ),
            patch(
                "app.infrastructure.persistence.compat_db.queries.inspect",
                return_value=mock_insp,
            ),
            patch(
                "app.infrastructure.persistence.compat_db.queries._insp_table_exists",
                return_value=True,
            ),
            patch(
                "app.infrastructure.persistence.compat_db.queries._exc_chain_has_undefined_table",
                return_value=True,
            ),
            patch(
                "app.infrastructure.persistence.compat_db.queries.append_mod_scope_where",
                return_value=None,
            ),
        ):
            result = _load_purchase_units_rows_pg()
        assert result == []

    def test_query_other_error_returns_empty(self):
        """When query raises other RECOVERABLE_ERRORS, should return []."""
        mock_eng = MagicMock()
        mock_insp = MagicMock()
        mock_insp.get_columns.return_value = [{"name": "id"}]

        mock_conn = MagicMock()
        mock_conn.execute.side_effect = OSError("query failed")

        mock_eng.connect.return_value.__enter__.return_value = mock_conn

        with (
            patch(
                "app.shell.mod_business_scope.business_data_exposed",
                return_value=True,
            ),
            patch(
                "app.infrastructure.persistence.compat_db.queries.get_sync_engine",
                return_value=mock_eng,
            ),
            patch(
                "app.infrastructure.persistence.compat_db.queries.inspect",
                return_value=mock_insp,
            ),
            patch(
                "app.infrastructure.persistence.compat_db.queries._insp_table_exists",
                return_value=True,
            ),
            patch(
                "app.infrastructure.persistence.compat_db.queries._exc_chain_has_undefined_table",
                return_value=False,
            ),
            patch(
                "app.infrastructure.persistence.compat_db.queries.append_mod_scope_where",
                return_value=None,
            ),
        ):
            result = _load_purchase_units_rows_pg()
        assert result == []

    def test_is_active_false_string_filtered(self):
        """Rows with is_active='false' string should be filtered out."""
        mock_eng = MagicMock()
        mock_insp = MagicMock()
        mock_insp.get_columns.return_value = [{"name": "id"}]

        mock_conn = MagicMock()
        mock_mapping = MagicMock()
        mock_mapping.all.return_value = [
            {"id": 1, "unit_name": "CoA", "is_active": "false"},
            {"id": 2, "unit_name": "CoB", "is_active": "0"},
            {"id": 3, "unit_name": "CoC", "is_active": False},
            {"id": 4, "unit_name": "CoD", "is_active": 1},
        ]
        mock_conn.execute.return_value.mappings.return_value = mock_mapping
        mock_eng.connect.return_value.__enter__.return_value = mock_conn

        with (
            patch(
                "app.shell.mod_business_scope.business_data_exposed",
                return_value=True,
            ),
            patch(
                "app.infrastructure.persistence.compat_db.queries.get_sync_engine",
                return_value=mock_eng,
            ),
            patch(
                "app.infrastructure.persistence.compat_db.queries.inspect",
                return_value=mock_insp,
            ),
            patch(
                "app.infrastructure.persistence.compat_db.queries._insp_table_exists",
                return_value=True,
            ),
            patch(
                "app.infrastructure.persistence.compat_db.queries.append_mod_scope_where",
                return_value=None,
            ),
        ):
            result = _load_purchase_units_rows_pg()

        # Only CoD should remain (is_active=1)
        assert len(result) == 1
        assert result[0]["unit_name"] == "CoD"


# ---------------------------------------------------------------------------
# _distinct_units_from_products_db_pg — uncovered branches
# ---------------------------------------------------------------------------


class TestDistinctUnitsFromProductsDbPg:
    """Cover _distinct_units_from_products_db_pg directly."""

    def test_business_not_exposed_returns_empty(self):
        """When business_data_exposed() returns False, should return []."""
        with patch(
            "app.shell.mod_business_scope.business_data_exposed",
            return_value=False,
        ):
            result = _distinct_units_from_products_db_pg()
        assert result == []

    def test_business_scope_import_error_returns_empty(self):
        """When business_data_exposed raises RECOVERABLE_ERRORS, should return []."""
        with patch(
            "app.shell.mod_business_scope.business_data_exposed",
            side_effect=OSError("import failed"),
        ):
            result = _distinct_units_from_products_db_pg()
        assert result == []

    def test_engine_error_returns_empty(self):
        """When get_sync_engine raises RECOVERABLE_ERRORS, should return []."""
        with (
            patch(
                "app.shell.mod_business_scope.business_data_exposed",
                return_value=True,
            ),
            patch(
                "app.infrastructure.persistence.compat_db.queries.get_sync_engine",
                side_effect=OSError("no engine"),
            ),
        ):
            result = _distinct_units_from_products_db_pg()
        assert result == []

    def test_products_table_missing_returns_empty(self):
        """When products table doesn't exist, should return []."""
        mock_eng = MagicMock()
        mock_insp = MagicMock()
        mock_insp.get_table_names.return_value = ["customers"]

        with (
            patch(
                "app.shell.mod_business_scope.business_data_exposed",
                return_value=True,
            ),
            patch(
                "app.infrastructure.persistence.compat_db.queries.get_sync_engine",
                return_value=mock_eng,
            ),
            patch(
                "app.infrastructure.persistence.compat_db.queries.inspect",
                return_value=mock_insp,
            ),
        ):
            result = _distinct_units_from_products_db_pg()
        assert result == []

    def test_unit_column_missing_returns_empty(self):
        """When products table has no 'unit' column, should return []."""
        mock_eng = MagicMock()
        mock_insp = MagicMock()
        mock_insp.get_table_names.return_value = ["products"]
        mock_insp.get_columns.return_value = [{"name": "id"}, {"name": "name"}]

        with (
            patch(
                "app.shell.mod_business_scope.business_data_exposed",
                return_value=True,
            ),
            patch(
                "app.infrastructure.persistence.compat_db.queries.get_sync_engine",
                return_value=mock_eng,
            ),
            patch(
                "app.infrastructure.persistence.compat_db.queries.inspect",
                return_value=mock_insp,
            ),
        ):
            result = _distinct_units_from_products_db_pg()
        assert result == []

    def test_query_returns_distinct_units(self):
        """Should return distinct units from products table."""
        mock_eng = MagicMock()
        mock_insp = MagicMock()
        mock_insp.get_table_names.return_value = ["products"]
        mock_insp.get_columns.return_value = [
            {"name": "id"}, {"name": "name"}, {"name": "unit"}, {"name": "is_active"}
        ]

        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [("CoA",), ("CoB",), ("CoA",)]  # CoA duplicated
        mock_conn.execute.return_value = mock_result
        mock_eng.connect.return_value.__enter__.return_value = mock_conn

        with (
            patch(
                "app.shell.mod_business_scope.business_data_exposed",
                return_value=True,
            ),
            patch(
                "app.infrastructure.persistence.compat_db.queries.get_sync_engine",
                return_value=mock_eng,
            ),
            patch(
                "app.infrastructure.persistence.compat_db.queries.inspect",
                return_value=mock_insp,
            ),
            patch(
                "app.infrastructure.persistence.compat_db.queries.append_mod_scope_where",
                return_value=None,
            ),
        ):
            result = _distinct_units_from_products_db_pg()

        assert len(result) == 3  # SQL DISTINCT happens at DB level, mock returns all
        assert all("name" in r and "symbol" in r and "id" in r for r in result)

    def test_operational_error_returns_empty(self):
        """OperationalError should be caught and return []."""
        from sqlalchemy.exc import OperationalError

        mock_eng = MagicMock()
        mock_insp = MagicMock()
        mock_insp.get_table_names.return_value = ["products"]
        mock_insp.get_columns.return_value = [{"name": "id"}, {"name": "unit"}]

        mock_conn = MagicMock()
        mock_conn.execute.side_effect = OperationalError("stmt", {}, None)
        mock_eng.connect.return_value.__enter__.return_value = mock_conn

        with (
            patch(
                "app.shell.mod_business_scope.business_data_exposed",
                return_value=True,
            ),
            patch(
                "app.infrastructure.persistence.compat_db.queries.get_sync_engine",
                return_value=mock_eng,
            ),
            patch(
                "app.infrastructure.persistence.compat_db.queries.inspect",
                return_value=mock_insp,
            ),
            patch(
                "app.infrastructure.persistence.compat_db.queries.append_mod_scope_where",
                return_value=None,
            ),
        ):
            result = _distinct_units_from_products_db_pg()
        assert result == []

    def test_recoverable_error_returns_empty(self):
        """RECOVERABLE_ERRORS (non-OperationalError) should be caught."""
        mock_eng = MagicMock()
        mock_insp = MagicMock()
        mock_insp.get_table_names.return_value = ["products"]
        mock_insp.get_columns.return_value = [{"name": "id"}, {"name": "unit"}]

        mock_conn = MagicMock()
        mock_conn.execute.side_effect = OSError("db error")
        mock_eng.connect.return_value.__enter__.return_value = mock_conn

        with (
            patch(
                "app.shell.mod_business_scope.business_data_exposed",
                return_value=True,
            ),
            patch(
                "app.infrastructure.persistence.compat_db.queries.get_sync_engine",
                return_value=mock_eng,
            ),
            patch(
                "app.infrastructure.persistence.compat_db.queries.inspect",
                return_value=mock_insp,
            ),
            patch(
                "app.infrastructure.persistence.compat_db.queries.append_mod_scope_where",
                return_value=None,
            ),
        ):
            result = _distinct_units_from_products_db_pg()
        assert result == []

    def test_none_unit_values_skipped(self):
        """None values in unit column should be skipped."""
        mock_eng = MagicMock()
        mock_insp = MagicMock()
        mock_insp.get_table_names.return_value = ["products"]
        mock_insp.get_columns.return_value = [{"name": "id"}, {"name": "unit"}]

        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [(None,), ("CoA",), ("",)]
        mock_conn.execute.return_value = mock_result
        mock_eng.connect.return_value.__enter__.return_value = mock_conn

        with (
            patch(
                "app.shell.mod_business_scope.business_data_exposed",
                return_value=True,
            ),
            patch(
                "app.infrastructure.persistence.compat_db.queries.get_sync_engine",
                return_value=mock_eng,
            ),
            patch(
                "app.infrastructure.persistence.compat_db.queries.inspect",
                return_value=mock_insp,
            ),
            patch(
                "app.infrastructure.persistence.compat_db.queries.append_mod_scope_where",
                return_value=None,
            ),
        ):
            result = _distinct_units_from_products_db_pg()

        # None is skipped, "" becomes "" (stripped), "CoA" is included
        # The function does: [str(row[0]).strip() for row in rows if row[0] is not None]
        # So None is skipped, but "" is kept (it's not None)
        assert len(result) == 2  # "" and "CoA"


# ---------------------------------------------------------------------------
# _load_customers_pg_from_customers_table — uncovered branches
# ---------------------------------------------------------------------------


class TestLoadCustomersPgFromCustomersTable:
    """Cover _load_customers_pg_from_customers_table directly."""

    def test_no_id_column_returns_empty(self):
        """When no id/customer_id column exists, should return []."""
        mock_eng = MagicMock()
        mock_insp = MagicMock()
        mock_insp.get_columns.return_value = [{"name": "name"}]

        result = _load_customers_pg_from_customers_table(mock_eng, mock_insp)
        assert result == []

    def test_no_name_column_returns_empty(self):
        """When no name column exists, should return []."""
        mock_eng = MagicMock()
        mock_insp = MagicMock()
        mock_insp.get_columns.return_value = [{"name": "id"}]

        result = _load_customers_pg_from_customers_table(mock_eng, mock_insp)
        assert result == []

    def test_customer_id_column_used(self):
        """Should use customer_id column when id is missing."""
        mock_eng = MagicMock()
        mock_insp = MagicMock()
        mock_insp.get_columns.return_value = [
            {"name": "customer_id"}, {"name": "customer_name"}
        ]

        mock_conn = MagicMock()
        mock_mapping = MagicMock()
        mock_mapping.all.return_value = [
            {"id": 1, "customer_name": "CoA"},
        ]
        mock_conn.execute.return_value.mappings.return_value = mock_mapping
        mock_eng.connect.return_value.__enter__.return_value = mock_conn

        with patch(
            "app.infrastructure.persistence.compat_db.queries.append_mod_scope_where",
            return_value=None,
        ):
            result = _load_customers_pg_from_customers_table(mock_eng, mock_insp)

        assert len(result) == 1
        assert result[0]["customer_name"] == "CoA"

    def test_chinese_column_names_used(self):
        """Should use Chinese column names (客户名称, 联系人, 电话, 地址)."""
        mock_eng = MagicMock()
        mock_insp = MagicMock()
        mock_insp.get_columns.return_value = [
            {"name": "id"}, {"name": "客户名称"}, {"name": "联系人"},
            {"name": "电话"}, {"name": "地址"},
        ]

        mock_conn = MagicMock()
        mock_mapping = MagicMock()
        mock_mapping.all.return_value = [
            {"id": 1, "customer_name": "中文名", "contact_person": "张",
             "contact_phone": "138", "address": "北京"},
        ]
        mock_conn.execute.return_value.mappings.return_value = mock_mapping
        mock_eng.connect.return_value.__enter__.return_value = mock_conn

        with patch(
            "app.infrastructure.persistence.compat_db.queries.append_mod_scope_where",
            return_value=None,
        ):
            result = _load_customers_pg_from_customers_table(mock_eng, mock_insp)

        assert len(result) == 1
        assert result[0]["customer_name"] == "中文名"

    def test_query_error_returns_empty(self):
        """When query raises RECOVERABLE_ERRORS, should return []."""
        mock_eng = MagicMock()
        mock_insp = MagicMock()
        mock_insp.get_columns.return_value = [
            {"name": "id"}, {"name": "customer_name"}
        ]

        mock_conn = MagicMock()
        mock_conn.execute.side_effect = OSError("query failed")
        mock_eng.connect.return_value.__enter__.return_value = mock_conn

        with patch(
            "app.infrastructure.persistence.compat_db.queries.append_mod_scope_where",
            return_value=None,
        ):
            result = _load_customers_pg_from_customers_table(mock_eng, mock_insp)
        assert result == []

    def test_is_active_missing_defaults_to_1(self):
        """When is_active column is missing, should default to 1."""
        mock_eng = MagicMock()
        mock_insp = MagicMock()
        mock_insp.get_columns.return_value = [
            {"name": "id"}, {"name": "customer_name"}
        ]

        mock_conn = MagicMock()
        mock_mapping = MagicMock()
        mock_mapping.all.return_value = [
            {"id": 1, "customer_name": "CoA"},  # no is_active
        ]
        mock_conn.execute.return_value.mappings.return_value = mock_mapping
        mock_eng.connect.return_value.__enter__.return_value = mock_conn

        with patch(
            "app.infrastructure.persistence.compat_db.queries.append_mod_scope_where",
            return_value=None,
        ):
            result = _load_customers_pg_from_customers_table(mock_eng, mock_insp)

        assert len(result) == 1
        assert result[0]["is_active"] == 1

    def test_is_active_present_used(self):
        """When is_active column exists, should include it in query."""
        mock_eng = MagicMock()
        mock_insp = MagicMock()
        mock_insp.get_columns.return_value = [
            {"name": "id"}, {"name": "customer_name"}, {"name": "is_active"}
        ]

        mock_conn = MagicMock()
        mock_mapping = MagicMock()
        mock_mapping.all.return_value = [
            {"id": 1, "customer_name": "CoA", "is_active": 1},
        ]
        mock_conn.execute.return_value.mappings.return_value = mock_mapping
        mock_eng.connect.return_value.__enter__.return_value = mock_conn

        with patch(
            "app.infrastructure.persistence.compat_db.queries.append_mod_scope_where",
            return_value=None,
        ):
            result = _load_customers_pg_from_customers_table(mock_eng, mock_insp)

        assert len(result) == 1
        assert result[0]["is_active"] == 1


# ---------------------------------------------------------------------------
# _load_customers_pg_from_purchase_units — uncovered branches
# ---------------------------------------------------------------------------


class TestLoadCustomersPgFromPurchaseUnits:
    """Cover _load_customers_pg_from_purchase_units directly."""

    def test_query_returns_rows(self):
        """Should return rows with unit_name remapped to customer_name."""
        mock_eng = MagicMock()
        mock_insp = MagicMock()
        mock_insp.get_columns.return_value = [{"name": "id"}]

        mock_conn = MagicMock()
        mock_mapping = MagicMock()
        mock_mapping.all.return_value = [
            {"id": 1, "unit_name": "CoA", "contact_person": "Z",
             "contact_phone": "1", "address": "A", "is_active": 1},
        ]
        mock_conn.execute.return_value.mappings.return_value = mock_mapping
        mock_eng.connect.return_value.__enter__.return_value = mock_conn

        with patch(
            "app.infrastructure.persistence.compat_db.queries.append_mod_scope_where",
            return_value=None,
        ):
            result = _load_customers_pg_from_purchase_units(mock_eng)

        assert len(result) == 1
        assert result[0]["customer_name"] == "CoA"
        assert "unit_name" not in result[0]

    def test_query_error_returns_empty(self):
        """When query raises RECOVERABLE_ERRORS, should return []."""
        mock_eng = MagicMock()
        mock_insp = MagicMock()
        mock_insp.get_columns.return_value = [{"name": "id"}]

        mock_conn = MagicMock()
        mock_conn.execute.side_effect = OSError("query failed")
        mock_eng.connect.return_value.__enter__.return_value = mock_conn

        with patch(
            "app.infrastructure.persistence.compat_db.queries.append_mod_scope_where",
            return_value=None,
        ):
            result = _load_customers_pg_from_purchase_units(mock_eng)
        assert result == []

    def test_is_active_false_filtered(self):
        """Rows with is_active=False should be filtered out."""
        mock_eng = MagicMock()
        mock_insp = MagicMock()
        mock_insp.get_columns.return_value = [{"name": "id"}]

        mock_conn = MagicMock()
        mock_mapping = MagicMock()
        mock_mapping.all.return_value = [
            {"id": 1, "unit_name": "CoA", "is_active": 1},
            {"id": 2, "unit_name": "CoB", "is_active": 0},
            {"id": 3, "unit_name": "CoC", "is_active": False},
            {"id": 4, "unit_name": "CoD", "is_active": "false"},
        ]
        mock_conn.execute.return_value.mappings.return_value = mock_mapping
        mock_eng.connect.return_value.__enter__.return_value = mock_conn

        with patch(
            "app.infrastructure.persistence.compat_db.queries.append_mod_scope_where",
            return_value=None,
        ):
            result = _load_customers_pg_from_purchase_units(mock_eng)

        assert len(result) == 1
        assert result[0]["customer_name"] == "CoA"

    def test_unit_name_none_handled(self):
        """None unit_name should be converted to empty string."""
        mock_eng = MagicMock()
        mock_insp = MagicMock()
        mock_insp.get_columns.return_value = [{"name": "id"}]

        mock_conn = MagicMock()
        mock_mapping = MagicMock()
        mock_mapping.all.return_value = [
            {"id": 1, "unit_name": None, "is_active": 1},
        ]
        mock_conn.execute.return_value.mappings.return_value = mock_mapping
        mock_eng.connect.return_value.__enter__.return_value = mock_conn

        with patch(
            "app.infrastructure.persistence.compat_db.queries.append_mod_scope_where",
            return_value=None,
        ):
            result = _load_customers_pg_from_purchase_units(mock_eng)

        assert len(result) == 1
        assert result[0]["customer_name"] == ""


# ---------------------------------------------------------------------------
# _load_customers_rows_pg — uncovered branches
# ---------------------------------------------------------------------------


class TestLoadCustomersRowsPg:
    """Cover _load_customers_rows_pg directly."""

    def test_engine_error_returns_empty(self):
        """When get_sync_engine raises RECOVERABLE_ERRORS, should return []."""
        with (
            patch(
                "app.infrastructure.persistence.compat_db.queries.get_sync_engine",
                side_effect=OSError("no engine"),
            ),
            patch(
                "app.infrastructure.persistence.compat_db.queries.inspect",
            ),
        ):
            result = _load_customers_rows_pg()
        assert result == []

    def test_customers_table_present_returns_rows(self):
        """When customers table exists and returns rows, should return them."""
        mock_eng = MagicMock()
        mock_insp = MagicMock()
        mock_insp.get_table_names.return_value = ["customers"]

        mock_rows = [{"id": 1, "customer_name": "CoA", "is_active": 1}]

        with (
            patch(
                "app.infrastructure.persistence.compat_db.queries.get_sync_engine",
                return_value=mock_eng,
            ),
            patch(
                "app.infrastructure.persistence.compat_db.queries.inspect",
                return_value=mock_insp,
            ),
            patch(
                "app.infrastructure.persistence.compat_db.queries._load_customers_pg_from_customers_table",
                return_value=mock_rows,
            ),
        ):
            result = _load_customers_rows_pg()

        assert result == mock_rows

    def test_customers_empty_falls_back_to_purchase_units(self):
        """When customers table returns empty, should fall back to purchase_units."""
        mock_eng = MagicMock()
        mock_insp = MagicMock()
        mock_insp.get_table_names.return_value = ["customers", "purchase_units"]

        pu_rows = [{"id": 1, "customer_name": "CoB", "is_active": 1}]

        with (
            patch(
                "app.infrastructure.persistence.compat_db.queries.get_sync_engine",
                return_value=mock_eng,
            ),
            patch(
                "app.infrastructure.persistence.compat_db.queries.inspect",
                return_value=mock_insp,
            ),
            patch(
                "app.infrastructure.persistence.compat_db.queries._load_customers_pg_from_customers_table",
                return_value=[],
            ),
            patch(
                "app.infrastructure.persistence.compat_db.queries._load_customers_pg_from_purchase_units",
                return_value=pu_rows,
            ),
        ):
            result = _load_customers_rows_pg()

        assert result == pu_rows

    def test_no_tables_returns_empty(self):
        """When neither customers nor purchase_units tables exist, should return []."""
        mock_eng = MagicMock()
        mock_insp = MagicMock()
        mock_insp.get_table_names.return_value = ["products"]

        with (
            patch(
                "app.infrastructure.persistence.compat_db.queries.get_sync_engine",
                return_value=mock_eng,
            ),
            patch(
                "app.infrastructure.persistence.compat_db.queries.inspect",
                return_value=mock_insp,
            ),
        ):
            result = _load_customers_rows_pg()
        assert result == []

    def test_only_purchase_units_table(self):
        """When only purchase_units table exists, should use it."""
        mock_eng = MagicMock()
        mock_insp = MagicMock()
        mock_insp.get_table_names.return_value = ["purchase_units"]

        pu_rows = [{"id": 1, "customer_name": "CoA", "is_active": 1}]

        with (
            patch(
                "app.infrastructure.persistence.compat_db.queries.get_sync_engine",
                return_value=mock_eng,
            ),
            patch(
                "app.infrastructure.persistence.compat_db.queries.inspect",
                return_value=mock_insp,
            ),
            patch(
                "app.infrastructure.persistence.compat_db.queries._load_customers_pg_from_purchase_units",
                return_value=pu_rows,
            ),
        ):
            result = _load_customers_rows_pg()

        assert result == pu_rows


# ---------------------------------------------------------------------------
# _load_customers_rows — uncovered branches
# ---------------------------------------------------------------------------


class TestLoadCustomersRowsAdditional:
    """Cover _load_customers_rows business_data_exposed branches."""

    def test_business_not_exposed_returns_empty(self):
        """When business_data_exposed() returns False, should return []."""
        with patch(
            "app.shell.mod_business_scope.business_data_exposed",
            return_value=False,
        ):
            result = _load_customers_rows()
        assert result == []

    def test_business_scope_import_error_returns_merged(self):
        """When business_data_exposed raises, should fall back to merged entries."""
        merged = [{"id": 1, "customer_name": "CoA", "is_active": 1}]
        with (
            patch(
                "app.shell.mod_business_scope.business_data_exposed",
                side_effect=OSError("import failed"),
            ),
            patch(
                "app.infrastructure.persistence.compat_db.queries._load_customers_rows_pg",
                return_value=[],
            ),
            patch(
                "app.infrastructure.persistence.compat_db.queries._customer_rows_from_merged_unit_entries",
                return_value=merged,
            ),
        ):
            result = _load_customers_rows()
        assert result == merged

    def test_pg_rows_returned_when_available(self):
        """When PG rows are available, should return them."""
        pg_rows = [{"id": 1, "customer_name": "CoA", "is_active": 1}]
        with (
            patch(
                "app.shell.mod_business_scope.business_data_exposed",
                return_value=True,
            ),
            patch(
                "app.infrastructure.persistence.compat_db.queries._load_customers_rows_pg",
                return_value=pg_rows,
            ),
        ):
            result = _load_customers_rows()
        assert result == pg_rows


# ---------------------------------------------------------------------------
# _customer_row_for_api — additional branches
# ---------------------------------------------------------------------------


class TestCustomerRowForApiAdditional:
    """Additional coverage for _customer_row_for_api."""

    def test_all_fields_present(self):
        """All fields should be mapped correctly."""
        row = {
            "id": 1,
            "customer_name": "CoA",
            "contact_person": "Zhang",
            "contact_phone": "138",
            "address": "Addr",
            "is_active": 1,
            "created_at": "2026-01-01",
            "updated_at": "2026-01-02",
        }
        result = _customer_row_for_api(row)
        assert result["id"] == 1
        assert result["name"] == "CoA"
        assert result["customer_name"] == "CoA"
        assert result["contact_person"] == "Zhang"
        assert result["contact_phone"] == "138"
        assert result["contact_address"] == "Addr"
        assert result["address"] == "Addr"
        assert result["is_active"] == 1
        assert result["created_at"] == "2026-01-01"
        assert result["updated_at"] == "2026-01-02"

    def test_contact_address_falls_back_to_contact_address(self):
        """When address is empty, contact_address should fall back to contact_address."""
        row = {
            "id": 1,
            "customer_name": "CoA",
            "contact_address": "Contact Addr",
            "address": "",
            "is_active": 1,
        }
        result = _customer_row_for_api(row)
        assert result["contact_address"] == "Contact Addr"
        assert result["address"] == ""

    def test_is_active_none_defaults_to_1(self):
        """When is_active is None, should default to 1."""
        row = {"id": 1, "customer_name": "CoA", "is_active": None}
        result = _customer_row_for_api(row)
        assert result["is_active"] == 1

    def test_is_active_zero_becomes_one(self):
        """When is_active is 0 (falsy), should default to 1 due to `or 1` logic."""
        row = {"id": 1, "customer_name": "CoA", "is_active": 0}
        result = _customer_row_for_api(row)
        # int(0 or 1) = int(1) = 1
        assert result["is_active"] == 1

    def test_name_with_whitespace_stripped(self):
        """Name with whitespace should be stripped."""
        row = {"id": 1, "customer_name": "  CoA  ", "is_active": 1}
        result = _customer_row_for_api(row)
        assert result["name"] == "CoA"
        assert result["customer_name"] == "CoA"

    def test_contact_person_none_becomes_empty(self):
        """None contact_person should become empty string."""
        row = {"id": 1, "customer_name": "CoA", "contact_person": None, "is_active": 1}
        result = _customer_row_for_api(row)
        assert result["contact_person"] == ""


# ---------------------------------------------------------------------------
# _customer_row_matches_keyword — additional branches
# ---------------------------------------------------------------------------


class TestCustomerRowMatchesKeywordAdditional:
    """Additional coverage for _customer_row_matches_keyword."""

    def test_matches_unit_name(self):
        row = {"unit_name": "TestUnit"}
        assert _customer_row_matches_keyword(row, "test") is True

    def test_matches_phone(self):
        row = {"phone": "13800138000"}
        assert _customer_row_matches_keyword(row, "138") is True

    def test_matches_company(self):
        row = {"company": "TestCompany"}
        assert _customer_row_matches_keyword(row, "test") is True

    def test_matches_contact_address(self):
        row = {"contact_address": "北京市"}
        assert _customer_row_matches_keyword(row, "北京") is True

    def test_keyword_with_whitespace(self):
        """Keyword with whitespace should be stripped."""
        row = {"customer_name": "TestCo"}
        assert _customer_row_matches_keyword(row, "  test  ") is True

    def test_empty_string_field_skipped(self):
        """Empty string field should be skipped (not match)."""
        row = {"customer_name": ""}
        assert _customer_row_matches_keyword(row, "test") is False

    def test_numeric_field_matched(self):
        """Numeric field should be converted to string and matched."""
        row = {"contact_phone": 13800138000}
        assert _customer_row_matches_keyword(row, "138") is True


# ---------------------------------------------------------------------------
# _customer_find_by_id — additional branches
# ---------------------------------------------------------------------------


class TestCustomerFindByIdAdditional:
    """Additional coverage for _customer_find_by_id."""

    def test_id_as_string_found(self):
        """Should find customer when id is passed as string."""
        with patch(
            "app.infrastructure.persistence.compat_db.queries._load_customers_rows",
            return_value=[{"id": 1, "customer_name": "CoA", "is_active": 1}],
        ):
            result = _customer_find_by_id("1")
        assert result is not None
        assert result["customer_name"] == "CoA"

    def test_id_none_raises_type_error(self):
        """Should raise TypeError when customer_id is None (int(None) fails)."""
        with patch(
            "app.infrastructure.persistence.compat_db.queries._load_customers_rows",
            return_value=[{"id": 0, "customer_name": "CoA", "is_active": 1}],
        ):
            # int(None) raises TypeError
            with pytest.raises(TypeError):
                _customer_find_by_id(None)

    def test_id_zero_not_found(self):
        """Should return None when no row has id=0."""
        with patch(
            "app.infrastructure.persistence.compat_db.queries._load_customers_rows",
            return_value=[{"id": 1, "customer_name": "CoA", "is_active": 1}],
        ):
            result = _customer_find_by_id(0)
        assert result is None

    def test_row_id_none_treated_as_zero(self):
        """Row with id=None should be treated as 0."""
        with patch(
            "app.infrastructure.persistence.compat_db.queries._load_customers_rows",
            return_value=[{"id": None, "customer_name": "CoA", "is_active": 1}],
        ):
            result = _customer_find_by_id(0)
        assert result is not None
        assert result["customer_name"] == "CoA"

    def test_returns_dict_copy(self):
        """Should return a dict copy, not the original."""
        original = {"id": 1, "customer_name": "CoA", "is_active": 1}
        with patch(
            "app.infrastructure.persistence.compat_db.queries._load_customers_rows",
            return_value=[original],
        ):
            result = _customer_find_by_id(1)
        assert result is not original
        assert result == original


# ---------------------------------------------------------------------------
# _customers_schema_hint_if_empty — additional branches
# ---------------------------------------------------------------------------


class TestCustomersSchemaHintIfEmptyAdditional:
    """Additional coverage for _customers_schema_hint_if_empty."""

    def test_only_customers_table(self):
        """When only customers table exists, should return None."""
        mock_eng = MagicMock()
        mock_insp = MagicMock()
        mock_insp.get_table_names.return_value = ["customers"]

        with (
            patch(
                "app.infrastructure.persistence.compat_db.queries.get_sync_engine",
                return_value=mock_eng,
            ),
            patch(
                "app.infrastructure.persistence.compat_db.queries.inspect",
                return_value=mock_insp,
            ),
        ):
            result = _customers_schema_hint_if_empty()
        assert result is None

    def test_only_purchase_units_table(self):
        """When only purchase_units table exists (no customers, no products), should return hint."""
        mock_eng = MagicMock()
        mock_insp = MagicMock()
        mock_insp.get_table_names.return_value = ["purchase_units"]

        with (
            patch(
                "app.infrastructure.persistence.compat_db.queries.get_sync_engine",
                return_value=mock_eng,
            ),
            patch(
                "app.infrastructure.persistence.compat_db.queries.inspect",
                return_value=mock_insp,
            ),
        ):
            result = _customers_schema_hint_if_empty()
        # has_c=False, has_pu=True, has_p=False
        # not has_p and not has_c = True → returns hint
        assert result is not None
        assert "customers" in result or "products" in result

    def test_customers_and_products_tables(self):
        """When customers and products tables exist (no purchase_units), should return hint about missing purchase_units."""
        mock_eng = MagicMock()
        mock_insp = MagicMock()
        mock_insp.get_table_names.return_value = ["customers", "products"]

        with (
            patch(
                "app.infrastructure.persistence.compat_db.queries.get_sync_engine",
                return_value=mock_eng,
            ),
            patch(
                "app.infrastructure.persistence.compat_db.queries.inspect",
                return_value=mock_insp,
            ),
        ):
            result = _customers_schema_hint_if_empty()
        # has_c=True, has_pu=False, has_p=True
        # not has_pu and has_p = True → returns hint about missing purchase_units
        assert result is not None
        assert "purchase_units" in result

    def test_purchase_units_and_products_tables(self):
        """When purchase_units and products tables exist, should return None."""
        mock_eng = MagicMock()
        mock_insp = MagicMock()
        mock_insp.get_table_names.return_value = ["purchase_units", "products"]

        with (
            patch(
                "app.infrastructure.persistence.compat_db.queries.get_sync_engine",
                return_value=mock_eng,
            ),
            patch(
                "app.infrastructure.persistence.compat_db.queries.inspect",
                return_value=mock_insp,
            ),
        ):
            result = _customers_schema_hint_if_empty()
        assert result is None

    def test_only_products_table(self):
        """When only products table exists, should return hint about missing customers/purchase_units."""
        mock_eng = MagicMock()
        mock_insp = MagicMock()
        mock_insp.get_table_names.return_value = ["products"]

        with (
            patch(
                "app.infrastructure.persistence.compat_db.queries.get_sync_engine",
                return_value=mock_eng,
            ),
            patch(
                "app.infrastructure.persistence.compat_db.queries.inspect",
                return_value=mock_insp,
            ),
        ):
            result = _customers_schema_hint_if_empty()
        assert result is not None
        assert "customers" in result or "purchase_units" in result

    def test_no_tables_returns_hint(self):
        """When no relevant tables exist, should return hint."""
        mock_eng = MagicMock()
        mock_insp = MagicMock()
        mock_insp.get_table_names.return_value = ["other_table"]

        with (
            patch(
                "app.infrastructure.persistence.compat_db.queries.get_sync_engine",
                return_value=mock_eng,
            ),
            patch(
                "app.infrastructure.persistence.compat_db.queries.inspect",
                return_value=mock_insp,
            ),
        ):
            result = _customers_schema_hint_if_empty()
        assert result is not None
        assert "customers" in result or "purchase_units" in result


# ---------------------------------------------------------------------------
# _units_select_data_unified — additional branches
# ---------------------------------------------------------------------------


class TestUnitsSelectDataUnifiedAdditional:
    """Additional coverage for _units_select_data_unified."""

    def test_id_string_coerced_to_none(self):
        """When id is a non-numeric string, should be coerced to None."""
        with (
            patch(
                "app.infrastructure.persistence.compat_db.queries._load_customers_rows",
                return_value=[
                    {"id": "abc", "customer_name": "CoA", "is_active": 1},
                ],
            ),
            patch(
                "app.infrastructure.persistence.compat_db.queries._distinct_units_from_products_db",
                return_value=[],
            ),
        ):
            result = _units_select_data_unified()
        assert len(result) == 1
        # When oid is None, next_id is incremented from max_id (0) + 1 = 1
        assert result[0]["id"] == 1
        assert result[0]["name"] == "CoA"

    def test_id_none_coerced_to_none(self):
        """When id is None, should be coerced to None."""
        with (
            patch(
                "app.infrastructure.persistence.compat_db.queries._load_customers_rows",
                return_value=[
                    {"id": None, "customer_name": "CoA", "is_active": 1},
                ],
            ),
            patch(
                "app.infrastructure.persistence.compat_db.queries._distinct_units_from_products_db",
                return_value=[],
            ),
        ):
            result = _units_select_data_unified()
        assert len(result) == 1
        assert result[0]["id"] == 1  # next_id = 0 + 1 = 1

    def test_mixed_valid_and_invalid_ids(self):
        """Mix of valid and invalid ids should be handled correctly."""
        with (
            patch(
                "app.infrastructure.persistence.compat_db.queries._load_customers_rows",
                return_value=[
                    {"id": 5, "customer_name": "CoA", "is_active": 1},
                    {"id": "invalid", "customer_name": "CoB", "is_active": 1},
                    {"id": 10, "customer_name": "CoC", "is_active": 1},
                ],
            ),
            patch(
                "app.infrastructure.persistence.compat_db.queries._distinct_units_from_products_db",
                return_value=[],
            ),
        ):
            result = _units_select_data_unified()
        assert len(result) == 3
        # CoA has id=5, CoC has id=10, CoB has None -> next_id = 10 + 1 = 11
        ids = {r["id"] for r in result}
        assert 5 in ids
        assert 10 in ids
        assert 11 in ids  # CoB's synthesized id

    def test_distinct_units_added_with_max_id_offset(self):
        """Distinct units should be added with id = max_id + syn."""
        with (
            patch(
                "app.infrastructure.persistence.compat_db.queries._load_customers_rows",
                return_value=[
                    {"id": 5, "customer_name": "CoA", "is_active": 1},
                ],
            ),
            patch(
                "app.infrastructure.persistence.compat_db.queries._distinct_units_from_products_db",
                return_value=[
                    {"id": 1, "name": "CoB", "symbol": "CoB"},
                    {"id": 2, "name": "CoC", "symbol": "CoC"},
                ],
            ),
        ):
            result = _units_select_data_unified()
        assert len(result) == 3
        # CoA: id=5, CoB: id=5+1=6, CoC: id=5+2=7
        names_to_ids = {r["name"]: r["id"] for r in result}
        assert names_to_ids["CoA"] == 5
        assert names_to_ids["CoB"] == 6
        assert names_to_ids["CoC"] == 7

    def test_empty_name_skipped(self):
        """Empty customer_name should be skipped."""
        with (
            patch(
                "app.infrastructure.persistence.compat_db.queries._load_customers_rows",
                return_value=[
                    {"id": 1, "customer_name": "", "is_active": 1},
                    {"id": 2, "customer_name": "   ", "is_active": 1},
                    {"id": 3, "customer_name": "CoA", "is_active": 1},
                ],
            ),
            patch(
                "app.infrastructure.persistence.compat_db.queries._distinct_units_from_products_db",
                return_value=[],
            ),
        ):
            result = _units_select_data_unified()
        assert len(result) == 1
        assert result[0]["name"] == "CoA"

    def test_distinct_unit_empty_name_skipped(self):
        """Empty name in distinct units should be skipped."""
        with (
            patch(
                "app.infrastructure.persistence.compat_db.queries._load_customers_rows",
                return_value=[],
            ),
            patch(
                "app.infrastructure.persistence.compat_db.queries._distinct_units_from_products_db",
                return_value=[
                    {"id": 1, "name": "", "symbol": ""},
                    {"id": 2, "name": "CoA", "symbol": "CoA"},
                ],
            ),
        ):
            result = _units_select_data_unified()
        assert len(result) == 1
        assert result[0]["name"] == "CoA"

    def test_distinct_unit_trivial_skipped(self):
        """Trivial measure units in distinct should be skipped."""
        with (
            patch(
                "app.infrastructure.persistence.compat_db.queries._load_customers_rows",
                return_value=[],
            ),
            patch(
                "app.infrastructure.persistence.compat_db.queries._distinct_units_from_products_db",
                return_value=[
                    {"id": 1, "name": "个", "symbol": "个"},
                    {"id": 2, "name": "CoA", "symbol": "CoA"},
                ],
            ),
            patch(
                "app.infrastructure.persistence.compat_db.queries.TRIVIAL_MEASURE_UNITS",
                {"个"},
            ),
        ):
            result = _units_select_data_unified()
        assert len(result) == 1
        assert result[0]["name"] == "CoA"

    def test_distinct_unit_duplicate_skipped(self):
        """Duplicate name in distinct units (already in customers) should be skipped."""
        with (
            patch(
                "app.infrastructure.persistence.compat_db.queries._load_customers_rows",
                return_value=[
                    {"id": 1, "customer_name": "CoA", "is_active": 1},
                ],
            ),
            patch(
                "app.infrastructure.persistence.compat_db.queries._distinct_units_from_products_db",
                return_value=[
                    {"id": 2, "name": "CoA", "symbol": "CoA"},  # duplicate
                    {"id": 3, "name": "CoB", "symbol": "CoB"},
                ],
            ),
        ):
            result = _units_select_data_unified()
        assert len(result) == 2
        names = {r["name"] for r in result}
        assert names == {"CoA", "CoB"}


# ---------------------------------------------------------------------------
# _products_units_for_select — additional branches
# ---------------------------------------------------------------------------


class TestProductsUnitsForSelectAdditional:
    """Additional coverage for _products_units_for_select."""

    def test_returns_unified_data_when_available(self):
        """When unified data is available, should return it."""
        with patch(
            "app.infrastructure.persistence.compat_db.queries._units_select_data_unified",
            return_value=[{"id": 1, "name": "CoA", "symbol": "CoA"}],
        ):
            result = _products_units_for_select()
        assert result["success"] is True
        assert len(result["data"]) == 1

    def test_falls_back_to_distinct_when_unified_empty(self):
        """When unified data is empty, should fall back to distinct units."""
        with (
            patch(
                "app.infrastructure.persistence.compat_db.queries._units_select_data_unified",
                return_value=[],
            ),
            patch(
                "app.infrastructure.persistence.compat_db.queries._distinct_units_from_products_db",
                return_value=[{"id": 1, "name": "CoB", "symbol": "CoB"}],
            ),
        ):
            result = _products_units_for_select()
        assert result["success"] is True
        assert len(result["data"]) == 1
        assert result["data"][0]["name"] == "CoB"

    def test_returns_empty_when_no_data(self):
        """When no data available, should return empty list."""
        with (
            patch(
                "app.infrastructure.persistence.compat_db.queries._units_select_data_unified",
                return_value=[],
            ),
            patch(
                "app.infrastructure.persistence.compat_db.queries._distinct_units_from_products_db",
                return_value=[],
            ),
        ):
            result = _products_units_for_select()
        assert result["success"] is True
        assert result["data"] == []

    def test_multiple_unified_items(self):
        """Multiple unified items should all be returned."""
        with patch(
            "app.infrastructure.persistence.compat_db.queries._units_select_data_unified",
            return_value=[
                {"id": 1, "name": "CoA", "symbol": "CoA"},
                {"id": 2, "name": "CoB", "symbol": "CoB"},
                {"id": 3, "name": "CoC", "symbol": "CoC"},
            ],
        ):
            result = _products_units_for_select()
        assert result["success"] is True
        assert len(result["data"]) == 3


# ---------------------------------------------------------------------------
# _merged_purchase_unit_entries — additional branches
# ---------------------------------------------------------------------------


class TestMergedPurchaseUnitEntriesAdditional:
    """Additional coverage for _merged_purchase_unit_entries."""

    def test_max_id_calculation_with_mixed_ids(self):
        """Should calculate max_id correctly with mixed id types."""
        with (
            patch(
                "app.infrastructure.persistence.compat_db.queries._load_purchase_units_rows",
                return_value=[
                    {"id": 5, "unit_name": "CoA", "is_active": 1,
                     "contact_person": "", "contact_phone": "", "address": ""},
                    {"id": "invalid", "unit_name": "CoB", "is_active": 1,
                     "contact_person": "", "contact_phone": "", "address": ""},
                    {"id": 10, "unit_name": "CoC", "is_active": 1,
                     "contact_person": "", "contact_phone": "", "address": ""},
                ],
            ),
            patch(
                "app.infrastructure.persistence.compat_db.queries._distinct_units_from_products_db",
                return_value=[
                    {"id": 1, "name": "CoD", "symbol": "CoD"},
                ],
            ),
        ):
            result = _merged_purchase_unit_entries()
        # max_id = 10 (from CoC), CoD gets id = 10 + 1 = 11
        co_d = [r for r in result if r["unit_name"] == "CoD"][0]
        assert co_d["id"] == 11

    def test_distinct_unit_empty_name_skipped(self):
        """Empty name in distinct units should be skipped."""
        with (
            patch(
                "app.infrastructure.persistence.compat_db.queries._load_purchase_units_rows",
                return_value=[],
            ),
            patch(
                "app.infrastructure.persistence.compat_db.queries._distinct_units_from_products_db",
                return_value=[
                    {"id": 1, "name": "", "symbol": ""},
                    {"id": 2, "name": "CoA", "symbol": "CoA"},
                ],
            ),
        ):
            result = _merged_purchase_unit_entries()
        assert len(result) == 1
        assert result[0]["unit_name"] == "CoA"

    def test_distinct_unit_trivial_skipped(self):
        """Trivial measure units should be skipped."""
        with (
            patch(
                "app.infrastructure.persistence.compat_db.queries._load_purchase_units_rows",
                return_value=[],
            ),
            patch(
                "app.infrastructure.persistence.compat_db.queries._distinct_units_from_products_db",
                return_value=[
                    {"id": 1, "name": "件", "symbol": "件"},
                    {"id": 2, "name": "CoA", "symbol": "CoA"},
                ],
            ),
            patch(
                "app.infrastructure.persistence.compat_db.queries.TRIVIAL_MEASURE_UNITS",
                {"件"},
            ),
        ):
            result = _merged_purchase_unit_entries()
        assert len(result) == 1
        assert result[0]["unit_name"] == "CoA"

    def test_distinct_unit_duplicate_skipped(self):
        """Duplicate name (already in purchase_units) should be skipped."""
        with (
            patch(
                "app.infrastructure.persistence.compat_db.queries._load_purchase_units_rows",
                return_value=[
                    {"id": 1, "unit_name": "CoA", "is_active": 1,
                     "contact_person": "", "contact_phone": "", "address": ""},
                ],
            ),
            patch(
                "app.infrastructure.persistence.compat_db.queries._distinct_units_from_products_db",
                return_value=[
                    {"id": 2, "name": "CoA", "symbol": "CoA"},  # duplicate
                    {"id": 3, "name": "CoB", "symbol": "CoB"},
                ],
            ),
        ):
            result = _merged_purchase_unit_entries()
        assert len(result) == 2
        names = [r["unit_name"] for r in result]
        assert names.count("CoA") == 1
        assert "CoB" in names

    def test_no_max_id_when_all_invalid(self):
        """When all ids are invalid, max_id should be 0."""
        with (
            patch(
                "app.infrastructure.persistence.compat_db.queries._load_purchase_units_rows",
                return_value=[
                    {"id": "invalid", "unit_name": "CoA", "is_active": 1,
                     "contact_person": "", "contact_phone": "", "address": ""},
                ],
            ),
            patch(
                "app.infrastructure.persistence.compat_db.queries._distinct_units_from_products_db",
                return_value=[
                    {"id": 1, "name": "CoB", "symbol": "CoB"},
                ],
            ),
        ):
            result = _merged_purchase_unit_entries()
        # max_id = 0, CoB gets id = 0 + 1 = 1
        co_b = [r for r in result if r["unit_name"] == "CoB"][0]
        assert co_b["id"] == 1


# ---------------------------------------------------------------------------
# _customer_rows_from_merged_unit_entries — additional branches
# ---------------------------------------------------------------------------


class TestCustomerRowsFromMergedUnitEntriesAdditional:
    """Additional coverage for _customer_rows_from_merged_unit_entries."""

    def test_non_int_id_uses_index(self):
        """When id is not an int, should use index (len(out) + 1)."""
        with patch(
            "app.infrastructure.persistence.compat_db.queries._merged_purchase_unit_entries",
            return_value=[
                {"id": "invalid", "unit_name": "CoA", "contact_person": "",
                 "contact_phone": "", "address": "", "is_active": 1},
                {"id": "also_invalid", "unit_name": "CoB", "contact_person": "",
                 "contact_phone": "", "address": "", "is_active": 1},
            ],
        ):
            result = _customer_rows_from_merged_unit_entries()
        assert len(result) == 2
        assert result[0]["id"] == 1  # len(out) + 1 = 0 + 1 = 1
        assert result[1]["id"] == 2  # len(out) + 1 = 1 + 1 = 2

    def test_is_active_none_defaults_to_1(self):
        """When is_active is None, should default to 1."""
        with patch(
            "app.infrastructure.persistence.compat_db.queries._merged_purchase_unit_entries",
            return_value=[
                {"id": 1, "unit_name": "CoA", "contact_person": "",
                 "contact_phone": "", "address": "", "is_active": None},
            ],
        ):
            result = _customer_rows_from_merged_unit_entries()
        assert len(result) == 1
        assert result[0]["is_active"] == 1

    def test_is_active_zero_becomes_one(self):
        """When is_active is 0 (falsy), should default to 1 due to `or 1` logic."""
        with patch(
            "app.infrastructure.persistence.compat_db.queries._merged_purchase_unit_entries",
            return_value=[
                {"id": 1, "unit_name": "CoA", "contact_person": "",
                 "contact_phone": "", "address": "", "is_active": 0},
            ],
        ):
            result = _customer_rows_from_merged_unit_entries()
        assert len(result) == 1
        # int(0 or 1) = int(1) = 1
        assert result[0]["is_active"] == 1

    def test_contact_fields_preserved(self):
        """Contact fields should be preserved (converted to string)."""
        with patch(
            "app.infrastructure.persistence.compat_db.queries._merged_purchase_unit_entries",
            return_value=[
                {"id": 1, "unit_name": "CoA", "contact_person": "Zhang",
                 "contact_phone": "138", "address": "Addr", "is_active": 1},
            ],
        ):
            result = _customer_rows_from_merged_unit_entries()
        assert len(result) == 1
        assert result[0]["contact_person"] == "Zhang"
        assert result[0]["contact_phone"] == "138"
        assert result[0]["address"] == "Addr"

    def test_none_contact_fields_become_empty(self):
        """None contact fields should become empty strings."""
        with patch(
            "app.infrastructure.persistence.compat_db.queries._merged_purchase_unit_entries",
            return_value=[
                {"id": 1, "unit_name": "CoA", "contact_person": None,
                 "contact_phone": None, "address": None, "is_active": 1},
            ],
        ):
            result = _customer_rows_from_merged_unit_entries()
        assert len(result) == 1
        assert result[0]["contact_person"] == ""
        assert result[0]["contact_phone"] == ""
        assert result[0]["address"] == ""


# Import OperationalError for use in test patches
from sqlalchemy.exc import OperationalError
