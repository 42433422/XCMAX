"""Branch coverage for app.infrastructure.products.db_read.

Covers _read_engine branching, find_matching_customer_unified, table-missing path (0/6 branches).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.infrastructure.products import db_read


class TestReadEngineSelection:
    def test_read_engine_uses_read_engine_when_url_set(self, monkeypatch):
        monkeypatch.setenv("DATABASE_READ_URL", "postgresql://u:p@replica:5432/db")
        with (
            patch("app.infrastructure.products.db_read.get_read_sync_engine") as mock_read,
            patch("app.infrastructure.products.db_read.get_sync_engine") as mock_primary,
        ):
            mock_read.return_value = MagicMock(name="read_engine")
            eng = db_read._read_engine()
            assert eng is mock_read.return_value
            mock_primary.assert_not_called()

    def test_read_engine_falls_back_to_primary_when_url_empty(self, monkeypatch):
        monkeypatch.delenv("DATABASE_READ_URL", raising=False)
        with (
            patch("app.infrastructure.products.db_read.get_read_sync_engine") as mock_read,
            patch("app.infrastructure.products.db_read.get_sync_engine") as mock_primary,
        ):
            mock_primary.return_value = MagicMock(name="primary_engine")
            eng = db_read._read_engine()
            assert eng is mock_primary.return_value
            mock_read.assert_not_called()

    def test_read_engine_falls_back_when_url_whitespace(self, monkeypatch):
        monkeypatch.setenv("DATABASE_READ_URL", "   ")
        with (
            patch("app.infrastructure.products.db_read.get_read_sync_engine") as mock_read,
            patch("app.infrastructure.products.db_read.get_sync_engine") as mock_primary,
        ):
            mock_primary.return_value = MagicMock(name="primary_engine")
            eng = db_read._read_engine()
            assert eng is mock_primary.return_value
            mock_read.assert_not_called()


class TestFindMatchingCustomerUnified:
    def test_returns_stripped_name(self):
        assert db_read.find_matching_customer_unified("  Acme  ") == "Acme"

    def test_returns_none_for_empty(self):
        assert db_read.find_matching_customer_unified("") is None

    def test_returns_none_for_whitespace_only(self):
        assert db_read.find_matching_customer_unified("   ") is None

    def test_returns_none_for_none(self):
        assert db_read.find_matching_customer_unified(None) is None


class TestLoadProductsForPriceListByCustomer:
    def test_table_missing_returns_empty(self):
        mock_engine = MagicMock()
        mock_insp = MagicMock()
        mock_insp.get_table_names.return_value = ["other_table"]
        with (
            patch("app.infrastructure.products.db_read._read_engine", return_value=mock_engine),
            patch("app.infrastructure.products.db_read.inspect", return_value=mock_insp),
        ):
            result = db_read.load_products_for_price_list_by_customer("Acme", None)
        assert result == []

    def test_table_present_returns_rows(self):
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        mock_row = {"model_number": "M1", "name": "P", "specification": "S", "unit": "Acme", "price": 10}
        mock_result = MagicMock()
        mock_result.mappings.return_value.all.return_value = [mock_row]
        mock_conn.execute.return_value = mock_result
        mock_insp = MagicMock()
        mock_insp.get_table_names.return_value = ["products"]
        with (
            patch("app.infrastructure.products.db_read._read_engine", return_value=mock_engine),
            patch("app.infrastructure.products.db_read.inspect", return_value=mock_insp),
        ):
            result = db_read.load_products_for_price_list_by_customer("Acme", None)
        assert len(result) == 1
        assert result[0]["model_number"] == "M1"

    def test_load_products_price_table_rows_delegates(self):
        with patch(
            "app.infrastructure.products.db_read.load_products_for_price_list_by_customer"
        ) as mock_load:
            mock_load.return_value = [{"x": 1}]
            result = db_read.load_products_price_table_rows("Acme")
            assert result == [{"x": 1}]
            mock_load.assert_called_once_with("Acme", None)
