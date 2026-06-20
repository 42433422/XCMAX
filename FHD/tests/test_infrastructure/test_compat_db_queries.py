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
    _load_purchase_units_rows,
    _merged_purchase_unit_entries,
    _products_units_for_select,
    _units_select_data_unified,
)


# ---------------------------------------------------------------------------
# _customer_row_for_api
# ---------------------------------------------------------------------------
class TestCustomerRowForApi:
    def test_maps_customer_name(self):
        row = {
            "id": 1,
            "customer_name": "TestCo",
            "contact_person": "Zhang",
            "contact_phone": "138",
            "address": "Addr",
            "is_active": 1,
        }
        result = _customer_row_for_api(row)
        assert result["name"] == "TestCo"
        assert result["customer_name"] == "TestCo"
        assert result["contact_person"] == "Zhang"

    def test_falls_back_to_unit_name(self):
        row = {
            "id": 2,
            "unit_name": "UnitCo",
            "contact_person": "",
            "contact_phone": "",
            "address": "",
            "is_active": 1,
        }
        result = _customer_row_for_api(row)
        assert result["name"] == "UnitCo"

    def test_falls_back_to_name(self):
        row = {
            "id": 3,
            "name": "NameCo",
            "contact_person": "",
            "contact_phone": "",
            "address": "",
            "is_active": 1,
        }
        result = _customer_row_for_api(row)
        assert result["name"] == "NameCo"

    def test_empty_name_fields(self):
        row = {"id": 4, "is_active": 1}
        result = _customer_row_for_api(row)
        assert result["name"] == ""
        assert result["is_active"] == 1

    def test_preserves_created_at(self):
        row = {"id": 5, "customer_name": "Co", "is_active": 1, "created_at": "2026-01-01"}
        result = _customer_row_for_api(row)
        assert result["created_at"] == "2026-01-01"

    def test_contact_address_fallback(self):
        row = {
            "id": 6,
            "customer_name": "Co",
            "contact_address": "Contact Addr",
            "address": "Addr",
            "is_active": 1,
        }
        result = _customer_row_for_api(row)
        # contact_address in output comes from row.get("contact_address") first
        # but the function maps address -> contact_address if contact_address missing
        # Since both exist, contact_address = row.get("contact_address") = "Contact Addr"
        # and address = row.get("address") = "Addr"
        # Actually looking at the code: contact_address = row.get("address") or row.get("contact_address")
        # Since "address" is truthy, it takes "Addr"
        assert result["contact_address"] == "Addr"
        assert result["address"] == "Addr"


# ---------------------------------------------------------------------------
# _customer_row_matches_keyword
# ---------------------------------------------------------------------------
class TestCustomerRowMatchesKeyword:
    def test_matches_customer_name(self):
        row = {"customer_name": "TestCo"}
        assert _customer_row_matches_keyword(row, "test") is True

    def test_matches_contact_person(self):
        row = {"contact_person": "Zhang San"}
        assert _customer_row_matches_keyword(row, "zhang") is True

    def test_matches_phone(self):
        row = {"contact_phone": "13800138000"}
        assert _customer_row_matches_keyword(row, "138") is True

    def test_no_match(self):
        row = {"customer_name": "TestCo"}
        assert _customer_row_matches_keyword(row, "xyz") is False

    def test_empty_keyword_always_matches(self):
        row = {"customer_name": "TestCo"}
        assert _customer_row_matches_keyword(row, "") is True
        assert _customer_row_matches_keyword(row, None) is True

    def test_case_insensitive(self):
        row = {"customer_name": "TestCo"}
        assert _customer_row_matches_keyword(row, "TESTCO") is True

    def test_matches_address(self):
        row = {"address": "北京市朝阳区"}
        assert _customer_row_matches_keyword(row, "朝阳") is True

    def test_none_field_skipped(self):
        row = {"customer_name": None, "phone": None}
        assert _customer_row_matches_keyword(row, "test") is False


# ---------------------------------------------------------------------------
# _merged_purchase_unit_entries
# ---------------------------------------------------------------------------
class TestMergedPurchaseUnitEntries:
    def test_merges_purchase_units_and_distinct(self):
        with (
            patch(
                "app.infrastructure.persistence.compat_db.queries._load_purchase_units_rows",
                return_value=[
                    {
                        "id": 1,
                        "unit_name": "CoA",
                        "is_active": 1,
                        "contact_person": "",
                        "contact_phone": "",
                        "address": "",
                    },
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
        assert len(result) == 2
        assert result[0]["unit_name"] == "CoA"
        assert result[1]["unit_name"] == "CoB"

    def test_deduplicates_by_name(self):
        with (
            patch(
                "app.infrastructure.persistence.compat_db.queries._load_purchase_units_rows",
                return_value=[
                    {
                        "id": 1,
                        "unit_name": "CoA",
                        "is_active": 1,
                        "contact_person": "",
                        "contact_phone": "",
                        "address": "",
                    },
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
        names = [r["unit_name"] for r in result]
        assert names.count("CoA") == 1
        assert "CoB" in names

    def test_skips_trivial_measure_units(self):
        with (
            patch(
                "app.infrastructure.persistence.compat_db.queries._load_purchase_units_rows",
                return_value=[],
            ),
            patch(
                "app.infrastructure.persistence.compat_db.queries._distinct_units_from_products_db",
                return_value=[
                    {"id": 1, "name": "个", "symbol": "个"},
                    {"id": 2, "name": "RealCo", "symbol": "RealCo"},
                ],
            ),
            patch(
                "app.infrastructure.persistence.compat_db.queries.TRIVIAL_MEASURE_UNITS",
                {"个"},
            ),
        ):
            result = _merged_purchase_unit_entries()
        assert all(r["unit_name"] != "个" for r in result)

    def test_empty_inputs(self):
        with (
            patch(
                "app.infrastructure.persistence.compat_db.queries._load_purchase_units_rows",
                return_value=[],
            ),
            patch(
                "app.infrastructure.persistence.compat_db.queries._distinct_units_from_products_db",
                return_value=[],
            ),
        ):
            result = _merged_purchase_unit_entries()
        assert result == []


# ---------------------------------------------------------------------------
# _customer_rows_from_merged_unit_entries
# ---------------------------------------------------------------------------
class TestCustomerRowsFromMergedUnitEntries:
    def test_converts_to_customer_format(self):
        with patch(
            "app.infrastructure.persistence.compat_db.queries._merged_purchase_unit_entries",
            return_value=[
                {
                    "id": 1,
                    "unit_name": "CoA",
                    "contact_person": "Z",
                    "contact_phone": "1",
                    "address": "A",
                    "is_active": 1,
                },
            ],
        ):
            result = _customer_rows_from_merged_unit_entries()
        assert len(result) == 1
        assert result[0]["customer_name"] == "CoA"

    def test_skips_empty_names(self):
        with patch(
            "app.infrastructure.persistence.compat_db.queries._merged_purchase_unit_entries",
            return_value=[
                {
                    "id": 1,
                    "unit_name": "",
                    "contact_person": "",
                    "contact_phone": "",
                    "address": "",
                    "is_active": 1,
                },
                {
                    "id": 2,
                    "unit_name": "  ",
                    "contact_person": "",
                    "contact_phone": "",
                    "address": "",
                    "is_active": 1,
                },
                {
                    "id": 3,
                    "unit_name": "CoA",
                    "contact_person": "",
                    "contact_phone": "",
                    "address": "",
                    "is_active": 1,
                },
            ],
        ):
            result = _customer_rows_from_merged_unit_entries()
        assert len(result) == 1
        assert result[0]["customer_name"] == "CoA"


# ---------------------------------------------------------------------------
# _load_purchase_units_rows
# ---------------------------------------------------------------------------
class TestLoadPurchaseUnitsRows:
    def test_returns_empty_when_business_not_exposed(self):
        with patch(
            "app.infrastructure.persistence.compat_db.queries._load_purchase_units_rows_pg",
            return_value=[],
        ):
            result = _load_purchase_units_rows()
        assert result == []


# ---------------------------------------------------------------------------
# _distinct_units_from_products_db
# ---------------------------------------------------------------------------
class TestDistinctUnitsFromProductsDb:
    def test_returns_empty_when_no_engine(self):
        with patch(
            "app.infrastructure.persistence.compat_db.queries._distinct_units_from_products_db_pg",
            return_value=[],
        ):
            result = _distinct_units_from_products_db()
        assert result == []


# ---------------------------------------------------------------------------
# _load_customers_rows
# ---------------------------------------------------------------------------
class TestLoadCustomersRows:
    def test_returns_empty_when_business_not_exposed(self):
        with (
            patch(
                "app.infrastructure.persistence.compat_db.queries._load_customers_rows_pg",
                return_value=[],
            ),
            patch(
                "app.infrastructure.persistence.compat_db.queries._customer_rows_from_merged_unit_entries",
                return_value=[],
            ),
        ):
            result = _load_customers_rows()
        assert result == []

    def test_returns_pg_rows_when_available(self):
        pg_rows = [{"id": 1, "customer_name": "CoA", "is_active": 1}]
        with (
            patch(
                "app.infrastructure.persistence.compat_db.queries._load_customers_rows_pg",
                return_value=pg_rows,
            ),
        ):
            result = _load_customers_rows()
        assert len(result) == 1

    def test_falls_back_to_merged_entries(self):
        merged = [{"id": 2, "customer_name": "CoB", "is_active": 1}]
        with (
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
        assert len(result) == 1
        assert result[0]["customer_name"] == "CoB"


# ---------------------------------------------------------------------------
# _customer_find_by_id
# ---------------------------------------------------------------------------
class TestCustomerFindById:
    def test_finds_customer(self):
        with patch(
            "app.infrastructure.persistence.compat_db.queries._load_customers_rows",
            return_value=[
                {"id": 1, "customer_name": "CoA", "is_active": 1},
                {"id": 2, "customer_name": "CoB", "is_active": 1},
            ],
        ):
            result = _customer_find_by_id(2)
        assert result is not None
        assert result["customer_name"] == "CoB"

    def test_returns_none_when_not_found(self):
        with patch(
            "app.infrastructure.persistence.compat_db.queries._load_customers_rows",
            return_value=[{"id": 1, "customer_name": "CoA", "is_active": 1}],
        ):
            result = _customer_find_by_id(999)
        assert result is None


# ---------------------------------------------------------------------------
# _customers_schema_hint_if_empty
# ---------------------------------------------------------------------------
class TestCustomersSchemaHintIfEmpty:
    def test_returns_none_when_all_tables_exist(self):
        mock_eng = MagicMock()
        mock_insp = MagicMock()
        mock_insp.get_table_names.return_value = ["customers", "purchase_units", "products"]
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

    def test_returns_hint_when_missing_tables(self):
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
        assert "purchase_units" in result

    def test_returns_hint_on_engine_error(self):
        with patch(
            "app.infrastructure.persistence.compat_db.queries.get_sync_engine",
            side_effect=OSError("no engine"),
        ):
            result = _customers_schema_hint_if_empty()
        assert result is not None
        assert "无法连接" in result


# ---------------------------------------------------------------------------
# _units_select_data_unified
# ---------------------------------------------------------------------------
class TestUnitsSelectDataUnified:
    def test_deduplicates_by_name(self):
        with (
            patch(
                "app.infrastructure.persistence.compat_db.queries._load_customers_rows",
                return_value=[
                    {"id": 1, "customer_name": "CoA", "is_active": 1},
                    {"id": 2, "customer_name": "CoA", "is_active": 1},
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

    def test_includes_distinct_product_units(self):
        with (
            patch(
                "app.infrastructure.persistence.compat_db.queries._load_customers_rows",
                return_value=[],
            ),
            patch(
                "app.infrastructure.persistence.compat_db.queries._distinct_units_from_products_db",
                return_value=[{"id": 1, "name": "CoB", "symbol": "CoB"}],
            ),
        ):
            result = _units_select_data_unified()
        assert any(r["name"] == "CoB" for r in result)

    def test_skips_trivial_units(self):
        with (
            patch(
                "app.infrastructure.persistence.compat_db.queries._load_customers_rows",
                return_value=[],
            ),
            patch(
                "app.infrastructure.persistence.compat_db.queries._distinct_units_from_products_db",
                return_value=[{"id": 1, "name": "个", "symbol": "个"}],
            ),
            patch(
                "app.infrastructure.persistence.compat_db.queries.TRIVIAL_MEASURE_UNITS",
                {"个"},
            ),
        ):
            result = _units_select_data_unified()
        assert all(r["name"] != "个" for r in result)


# ---------------------------------------------------------------------------
# _products_units_for_select
# ---------------------------------------------------------------------------
class TestProductsUnitsForSelect:
    def test_returns_unified_data(self):
        with (
            patch(
                "app.infrastructure.persistence.compat_db.queries._units_select_data_unified",
                return_value=[{"id": 1, "name": "CoA", "symbol": "CoA"}],
            ),
        ):
            result = _products_units_for_select()
        assert result["success"] is True
        assert len(result["data"]) == 1

    def test_falls_back_to_distinct(self):
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

    def test_returns_empty_when_no_data(self):
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
