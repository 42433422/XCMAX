"""Tests for app.infrastructure.skills.db_query.db_query."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.infrastructure.skills.db_query.db_query import get_db_query_skill


class TestGetDbQuerySkill:
    def test_returns_dict(self):
        result = get_db_query_skill()
        assert result["name"] == "db-query"
        assert "functions" in result

    def test_has_all_functions(self):
        result = get_db_query_skill()
        expected_fns = [
            "query_all_products",
            "search_products",
            "search_products_by_model",
            "query_all_customers",
            "search_customers",
            "query_recent_shipments",
            "query_product_price",
            "query_all_materials",
            "search_materials",
        ]
        for fn_name in expected_fns:
            assert fn_name in result["functions"]
            assert callable(result["functions"][fn_name])


class TestDbQueryFunctions:
    """Test the DB query functions with mocked database."""

    @patch("app.infrastructure.skills.db_query.db_query.get_db")
    def test_query_all_products(self, mock_get_db):
        mock_db = MagicMock()
        mock_db.query.return_value.limit.return_value.all.return_value = []
        mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

        skill = get_db_query_skill()
        result = skill["functions"]["query_all_products"](limit=10)
        assert result == []

    @patch("app.infrastructure.skills.db_query.db_query.get_db")
    def test_search_products(self, mock_get_db):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.limit.return_value.all.return_value = []
        mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

        skill = get_db_query_skill()
        result = skill["functions"]["search_products"]("test")
        assert result == []

    @patch("app.infrastructure.skills.db_query.db_query.get_db")
    def test_query_product_price_not_found(self, mock_get_db):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

        skill = get_db_query_skill()
        result = skill["functions"]["query_product_price"]("nonexistent")
        assert result is None

    @patch("app.infrastructure.skills.db_query.db_query.get_db")
    def test_query_product_price_found(self, mock_get_db):
        mock_product = MagicMock()
        mock_product.price = 99.9
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_product
        mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

        skill = get_db_query_skill()
        result = skill["functions"]["query_product_price"]("test")
        assert result == 99.9
