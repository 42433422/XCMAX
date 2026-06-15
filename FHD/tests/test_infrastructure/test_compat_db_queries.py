"""Tests for app.infrastructure.persistence.compat_db.queries."""

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
    _load_customers_rows,
    _load_customers_rows_pg,
    _load_purchase_units_rows,
    _merged_purchase_unit_entries,
    _products_units_for_select,
    _units_select_data_unified,
)


# ---------------------------------------------------------------------------
# _customer_row_for_api
# ---------------------------------------------------------------------------

class TestCustomerRowForApi:
    def test_basic_conversion(self):
        row = {
            "id": 1,
            "customer_name": "客户A",
            "contact_person": "张三",
            "contact_phone": "13800000000",
            "address": "北京市",
            "is_active": 1,
            "created_at": "2026-01-01",
            "updated_at": "2026-01-02",
        }
        result = _customer_row_for_api(row)
        assert result["id"] == 1
        assert result["name"] == "客户A"
        assert result["customer_name"] == "客户A"
        assert result["contact_person"] == "张三"
        assert result["contact_phone"] == "13800000000"
        assert result["contact_address"] == "北京市"
        assert result["is_active"] == 1

    def test_unit_name_fallback_for_customer_name(self):
        row = {
            "id": 2,
            "unit_name": "单位B",
            "contact_person": "",
            "contact_phone": "",
            "address": "",
            "is_active": 1,
        }
        result = _customer_row_for_api(row)
        assert result["customer_name"] == "单位B"
        assert result["name"] == "单位B"

    def test_name_fallback_for_customer_name(self):
        row = {
            "id": 3,
            "name": "名称C",
            "contact_person": "",
            "contact_phone": "",
            "address": "",
            "is_active": 1,
        }
        result = _customer_row_for_api(row)
        assert result["customer_name"] == "名称C"

    def test_missing_fields_default_to_empty(self):
        row = {"id": 4}
        result = _customer_row_for_api(row)
        assert result["contact_person"] == ""
        assert result["contact_phone"] == ""
        assert result["contact_address"] == ""
        assert result["address"] == ""
        assert result["is_active"] == 1

    def test_is_active_defaults_to_1(self):
        row = {"id": 5}
        result = _customer_row_for_api(row)
        assert result["is_active"] == 1

    def test_contact_address_prefers_address(self):
        row = {
            "id": 6,
            "customer_name": "X",
            "address": "地址A",
            "contact_address": "地址B",
        }
        result = _customer_row_for_api(row)
        assert result["contact_address"] == "地址A"

    def test_contact_address_fallback_to_contact_address(self):
        row = {
            "id": 7,
            "customer_name": "X",
            "contact_address": "地址B",
        }
        result = _customer_row_for_api(row)
        assert result["contact_address"] == "地址B"


# ---------------------------------------------------------------------------
# _customer_row_matches_keyword
# ---------------------------------------------------------------------------

class TestCustomerRowMatchesKeyword:
    def test_empty_keyword_matches(self):
        row = {"customer_name": "客户A"}
        assert _customer_row_matches_keyword(row, "") is True

    def test_none_keyword_matches(self):
        row = {"customer_name": "客户A"}
        assert _customer_row_matches_keyword(row, None) is True

    def test_match_customer_name(self):
        row = {"customer_name": "客户A"}
        assert _customer_row_matches_keyword(row, "客户") is True

    def test_match_case_insensitive(self):
        row = {"customer_name": "ClientABC"}
        assert _customer_row_matches_keyword(row, "clientabc") is True

    def test_match_contact_person(self):
        row = {"contact_person": "张三"}
        assert _customer_row_matches_keyword(row, "张") is True

    def test_match_contact_phone(self):
        row = {"contact_phone": "13800000000"}
        assert _customer_row_matches_keyword(row, "138") is True

    def test_match_address(self):
        row = {"address": "北京市朝阳区"}
        assert _customer_row_matches_keyword(row, "朝阳") is True

    def test_no_match(self):
        row = {"customer_name": "客户A"}
        assert _customer_row_matches_keyword(row, "不存在") is False

    def test_match_unit_name(self):
        row = {"unit_name": "单位X"}
        assert _customer_row_matches_keyword(row, "单位X") is True

    def test_match_name_key(self):
        row = {"name": "名称Y"}
        assert _customer_row_matches_keyword(row, "名称Y") is True

    def test_none_value_skipped(self):
        row = {"customer_name": None, "address": "北京"}
        assert _customer_row_matches_keyword(row, "北京") is True


# ---------------------------------------------------------------------------
# _load_purchase_units_rows
# ---------------------------------------------------------------------------

class TestLoadPurchaseUnitsRows:
    @patch("app.infrastructure.persistence.compat_db.queries._load_purchase_units_rows_pg")
    def test_delegates_to_pg(self, mock_pg):
        mock_pg.return_value = [{"id": 1, "unit_name": "客户A"}]
        result = _load_purchase_units_rows()
        assert result == [{"id": 1, "unit_name": "客户A"}]

    @patch("app.infrastructure.persistence.compat_db.queries._load_purchase_units_rows_pg")
    def test_returns_empty_on_error(self, mock_pg):
        mock_pg.return_value = []
        result = _load_purchase_units_rows()
        assert result == []


# ---------------------------------------------------------------------------
# _distinct_units_from_products_db
# ---------------------------------------------------------------------------

class TestDistinctUnitsFromProductsDb:
    @patch("app.infrastructure.persistence.compat_db.queries.get_sync_engine")
    def test_returns_empty_when_business_data_not_exposed(self, mock_engine):
        with patch(
            "app.infrastructure.persistence.compat_db.queries.business_data_exposed",
            return_value=False,
            create=True,
        ):
            result = _distinct_units_from_products_db()
            assert result == []

    @patch("app.infrastructure.persistence.compat_db.queries.get_sync_engine")
    def test_returns_empty_on_engine_error(self, mock_engine):
        mock_engine.side_effect = OSError("no engine")
        with patch(
            "app.infrastructure.persistence.compat_db.queries.business_data_exposed",
            return_value=True,
            create=True,
        ):
            result = _distinct_units_from_products_db()
            assert result == []


# ---------------------------------------------------------------------------
# _merged_purchase_unit_entries
# ---------------------------------------------------------------------------

class TestMergedPurchaseUnitEntries:
    @patch("app.infrastructure.persistence.compat_db.queries._distinct_units_from_products_db")
    @patch("app.infrastructure.persistence.compat_db.queries._load_purchase_units_rows")
    def test_merges_purchase_units_and_products(self, mock_load_pu, mock_distinct):
        mock_load_pu.return_value = [
            {"id": 1, "unit_name": "客户A", "is_active": 1},
        ]
        mock_distinct.return_value = [
            {"id": 1, "name": "客户B", "symbol": "客户B"},
        ]
        result = _merged_purchase_unit_entries()
        names = [r.get("unit_name") for r in result]
        assert "客户A" in names
        assert "客户B" in names

    @patch("app.infrastructure.persistence.compat_db.queries._distinct_units_from_products_db")
    @patch("app.infrastructure.persistence.compat_db.queries._load_purchase_units_rows")
    def test_deduplicates_by_unit_name(self, mock_load_pu, mock_distinct):
        mock_load_pu.return_value = [
            {"id": 1, "unit_name": "客户A", "is_active": 1},
        ]
        mock_distinct.return_value = [
            {"id": 1, "name": "客户A", "symbol": "客户A"},  # duplicate
        ]
        result = _merged_purchase_unit_entries()
        names = [r.get("unit_name") for r in result]
        assert names.count("客户A") == 1

    @patch("app.infrastructure.persistence.compat_db.queries._distinct_units_from_products_db")
    @patch("app.infrastructure.persistence.compat_db.queries._load_purchase_units_rows")
    def test_filters_trivial_units_from_products(self, mock_load_pu, mock_distinct):
        mock_load_pu.return_value = []
        mock_distinct.return_value = [
            {"id": 1, "name": "件", "symbol": "件"},  # trivial
            {"id": 2, "name": "客户B", "symbol": "客户B"},
        ]
        result = _merged_purchase_unit_entries()
        names = [r.get("unit_name") for r in result]
        assert "件" not in names
        assert "客户B" in names

    @patch("app.infrastructure.persistence.compat_db.queries._distinct_units_from_products_db")
    @patch("app.infrastructure.persistence.compat_db.queries._load_purchase_units_rows")
    def test_empty_both_returns_empty(self, mock_load_pu, mock_distinct):
        mock_load_pu.return_value = []
        mock_distinct.return_value = []
        result = _merged_purchase_unit_entries()
        assert result == []


# ---------------------------------------------------------------------------
# _customer_rows_from_merged_unit_entries
# ---------------------------------------------------------------------------

class TestCustomerRowsFromMergedUnitEntries:
    @patch("app.infrastructure.persistence.compat_db.queries._merged_purchase_unit_entries")
    def test_converts_unit_entries_to_customer_rows(self, mock_merged):
        mock_merged.return_value = [
            {"id": 1, "unit_name": "客户A", "contact_person": "张三",
             "contact_phone": "138", "address": "北京", "is_active": 1},
        ]
        result = _customer_rows_from_merged_unit_entries()
        assert len(result) == 1
        assert result[0]["customer_name"] == "客户A"
        assert result[0]["contact_person"] == "张三"

    @patch("app.infrastructure.persistence.compat_db.queries._merged_purchase_unit_entries")
    def test_skips_empty_unit_name(self, mock_merged):
        mock_merged.return_value = [
            {"id": 1, "unit_name": "", "is_active": 1},
            {"id": 2, "unit_name": "客户B", "is_active": 1},
        ]
        result = _customer_rows_from_merged_unit_entries()
        assert len(result) == 1
        assert result[0]["customer_name"] == "客户B"

    @patch("app.infrastructure.persistence.compat_db.queries._merged_purchase_unit_entries")
    def test_empty_returns_empty(self, mock_merged):
        mock_merged.return_value = []
        result = _customer_rows_from_merged_unit_entries()
        assert result == []


# ---------------------------------------------------------------------------
# _customer_find_by_id
# ---------------------------------------------------------------------------

class TestCustomerFindById:
    @patch("app.infrastructure.persistence.compat_db.queries._load_customers_rows")
    def test_found(self, mock_load):
        mock_load.return_value = [
            {"id": 1, "customer_name": "客户A"},
            {"id": 2, "customer_name": "客户B"},
        ]
        result = _customer_find_by_id(1)
        assert result is not None
        assert result["customer_name"] == "客户A"

    @patch("app.infrastructure.persistence.compat_db.queries._load_customers_rows")
    def test_not_found(self, mock_load):
        mock_load.return_value = [
            {"id": 1, "customer_name": "客户A"},
        ]
        result = _customer_find_by_id(999)
        assert result is None

    @patch("app.infrastructure.persistence.compat_db.queries._load_customers_rows")
    def test_empty_rows(self, mock_load):
        mock_load.return_value = []
        result = _customer_find_by_id(1)
        assert result is None


# ---------------------------------------------------------------------------
# _customers_schema_hint_if_empty
# ---------------------------------------------------------------------------

class TestCustomersSchemaHintIfEmpty:
    @patch("app.infrastructure.persistence.compat_db.queries.get_sync_engine")
    def test_all_tables_exist_returns_none(self, mock_engine):
        mock_eng = MagicMock()
        mock_engine.return_value = mock_eng
        with patch(
            "app.infrastructure.persistence.compat_db.queries.inspect"
        ) as mock_insp:
            mock_insp.return_value.get_table_names.return_value = [
                "customers", "purchase_units", "products"
            ]
            result = _customers_schema_hint_if_empty()

        assert result is None

    @patch("app.infrastructure.persistence.compat_db.queries.get_sync_engine")
    def test_missing_customers_and_purchase_units(self, mock_engine):
        mock_eng = MagicMock()
        mock_engine.return_value = mock_eng
        with patch(
            "app.infrastructure.persistence.compat_db.queries.inspect"
        ) as mock_insp:
            mock_insp.return_value.get_table_names.return_value = ["products"]
            result = _customers_schema_hint_if_empty()

        assert result is not None
        assert "customers" in result.lower() or "purchase_units" in result.lower()

    @patch("app.infrastructure.persistence.compat_db.queries.get_sync_engine")
    def test_engine_error(self, mock_engine):
        mock_engine.side_effect = OSError("no engine")
        result = _customers_schema_hint_if_empty()
        assert result is not None
        assert "PostgreSQL" in result or "无法连接" in result

    @patch("app.infrastructure.persistence.compat_db.queries.get_sync_engine")
    def test_missing_purchase_units_with_products(self, mock_engine):
        mock_eng = MagicMock()
        mock_engine.return_value = mock_eng
        with patch(
            "app.infrastructure.persistence.compat_db.queries.inspect"
        ) as mock_insp:
            mock_insp.return_value.get_table_names.return_value = ["customers", "products"]
            result = _customers_schema_hint_if_empty()

        # customers exists, so no hint about missing purchase_units
        # Actually, the function checks: if not has_c and not has_pu -> hint
        # Here has_c=True, so no hint about missing tables
        # But there's also: if not has_pu and has_p -> hint
        assert result is not None
        assert "purchase_units" in result.lower()


# ---------------------------------------------------------------------------
# _units_select_data_unified
# ---------------------------------------------------------------------------

class TestUnitsSelectDataUnified:
    @patch("app.infrastructure.persistence.compat_db.queries._distinct_units_from_products_db")
    @patch("app.infrastructure.persistence.compat_db.queries._load_customers_rows")
    def test_with_customer_rows(self, mock_load, mock_distinct):
        mock_load.return_value = [
            {"id": 1, "customer_name": "客户A"},
        ]
        mock_distinct.return_value = []
        result = _units_select_data_unified()
        assert len(result) == 1
        assert result[0]["name"] == "客户A"

    @patch("app.infrastructure.persistence.compat_db.queries._distinct_units_from_products_db")
    @patch("app.infrastructure.persistence.compat_db.queries._load_customers_rows")
    def test_deduplicates(self, mock_load, mock_distinct):
        mock_load.return_value = [
            {"id": 1, "customer_name": "客户A"},
            {"id": 2, "customer_name": "客户A"},  # duplicate
        ]
        mock_distinct.return_value = []
        result = _units_select_data_unified()
        names = [r["name"] for r in result]
        assert names.count("客户A") == 1

    @patch("app.infrastructure.persistence.compat_db.queries._distinct_units_from_products_db")
    @patch("app.infrastructure.persistence.compat_db.queries._load_customers_rows")
    def test_merges_with_products_units(self, mock_load, mock_distinct):
        mock_load.return_value = [
            {"id": 1, "customer_name": "客户A"},
        ]
        mock_distinct.return_value = [
            {"id": 1, "name": "客户B", "symbol": "客户B"},
        ]
        result = _units_select_data_unified()
        names = [r["name"] for r in result]
        assert "客户A" in names
        assert "客户B" in names

    @patch("app.infrastructure.persistence.compat_db.queries._distinct_units_from_products_db")
    @patch("app.infrastructure.persistence.compat_db.queries._load_customers_rows")
    def test_filters_trivial_units(self, mock_load, mock_distinct):
        mock_load.return_value = []
        mock_distinct.return_value = [
            {"id": 1, "name": "件", "symbol": "件"},
            {"id": 2, "name": "客户B", "symbol": "客户B"},
        ]
        result = _units_select_data_unified()
        names = [r["name"] for r in result]
        assert "件" not in names
        assert "客户B" in names


# ---------------------------------------------------------------------------
# _products_units_for_select
# ---------------------------------------------------------------------------

class TestProductsUnitsForSelect:
    @patch("app.infrastructure.persistence.compat_db.queries._units_select_data_unified")
    @patch("app.infrastructure.persistence.compat_db.queries._distinct_units_from_products_db")
    def test_with_unified_data(self, mock_distinct, mock_unified):
        mock_unified.return_value = [
            {"id": 1, "name": "客户A", "symbol": "客户A"},
        ]
        result = _products_units_for_select()
        assert result["success"] is True
        assert len(result["data"]) == 1

    @patch("app.infrastructure.persistence.compat_db.queries._units_select_data_unified")
    @patch("app.infrastructure.persistence.compat_db.queries._distinct_units_from_products_db")
    def test_fallback_to_distinct(self, mock_distinct, mock_unified):
        mock_unified.return_value = []
        mock_distinct.return_value = [
            {"id": 1, "name": "客户B", "symbol": "客户B"},
        ]
        result = _products_units_for_select()
        assert result["success"] is True
        assert len(result["data"]) == 1

    @patch("app.infrastructure.persistence.compat_db.queries._units_select_data_unified")
    @patch("app.infrastructure.persistence.compat_db.queries._distinct_units_from_products_db")
    def test_empty_returns_empty_data(self, mock_distinct, mock_unified):
        mock_unified.return_value = []
        mock_distinct.return_value = []
        result = _products_units_for_select()
        assert result["success"] is True
        assert result["data"] == []


# ---------------------------------------------------------------------------
# _load_customers_rows_pg
# ---------------------------------------------------------------------------

class TestLoadCustomersRowsPg:
    @patch("app.infrastructure.persistence.compat_db.queries.get_sync_engine")
    def test_engine_error_returns_empty(self, mock_engine):
        mock_engine.side_effect = OSError("no engine")
        result = _load_customers_rows_pg()
        assert result == []

    @patch("app.infrastructure.persistence.compat_db.queries.get_sync_engine")
    def test_no_relevant_tables(self, mock_engine):
        mock_eng = MagicMock()
        mock_engine.return_value = mock_eng
        with patch(
            "app.infrastructure.persistence.compat_db.queries.inspect"
        ) as mock_insp:
            mock_insp.return_value.get_table_names.return_value = ["other_table"]
            result = _load_customers_rows_pg()

        assert result == []


# ---------------------------------------------------------------------------
# _load_customers_rows
# ---------------------------------------------------------------------------

class TestLoadCustomersRows:
    @patch("app.infrastructure.persistence.compat_db.queries._customer_rows_from_merged_unit_entries")
    @patch("app.infrastructure.persistence.compat_db.queries._load_customers_rows_pg")
    def test_prefers_pg_rows(self, mock_pg, mock_merged):
        mock_pg.return_value = [{"id": 1, "customer_name": "PG客户"}]
        mock_merged.return_value = [{"id": 2, "customer_name": "Merged客户"}]

        with patch(
            "app.infrastructure.persistence.compat_db.queries.business_data_exposed",
            return_value=True,
            create=True,
        ):
            result = _load_customers_rows()

        assert result == [{"id": 1, "customer_name": "PG客户"}]

    @patch("app.infrastructure.persistence.compat_db.queries._customer_rows_from_merged_unit_entries")
    @patch("app.infrastructure.persistence.compat_db.queries._load_customers_rows_pg")
    def test_fallback_to_merged(self, mock_pg, mock_merged):
        mock_pg.return_value = []
        mock_merged.return_value = [{"id": 2, "customer_name": "Merged客户"}]

        with patch(
            "app.infrastructure.persistence.compat_db.queries.business_data_exposed",
            return_value=True,
            create=True,
        ):
            result = _load_customers_rows()

        assert result == [{"id": 2, "customer_name": "Merged客户"}]
