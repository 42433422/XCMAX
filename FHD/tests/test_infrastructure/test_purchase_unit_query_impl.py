"""Branch coverage for app.infrastructure.persistence.purchase_unit_query_impl.

Covers list_purchase_units deduplication and empty names.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch


def _mock_db_ctx(mock_db):
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=mock_db)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx


class TestListPurchaseUnits:
    def test_dedup_preserves_order(self):
        mock_db = MagicMock()
        mock_q = MagicMock()
        mock_db.query.return_value = mock_q
        mock_q.filter.return_value = mock_q
        mock_q.all.return_value = [("Acme",), ("Beta",), ("Acme",), ("Gamma",), ("Beta",)]
        with patch(
            "app.infrastructure.persistence.purchase_unit_query_impl.get_db",
            return_value=_mock_db_ctx(mock_db),
        ):
            from app.infrastructure.persistence.purchase_unit_query_impl import (
                SQLAlchemyPurchaseUnitQuery,
            )

            result = SQLAlchemyPurchaseUnitQuery().list_purchase_units()
        assert result == ["Acme", "Beta", "Gamma"]

    def test_filters_none_and_empty_names(self):
        mock_db = MagicMock()
        mock_q = MagicMock()
        mock_db.query.return_value = mock_q
        mock_q.filter.return_value = mock_q
        mock_q.all.return_value = [(None,), ("",), ("Acme",), ("",)]
        with patch(
            "app.infrastructure.persistence.purchase_unit_query_impl.get_db",
            return_value=_mock_db_ctx(mock_db),
        ):
            from app.infrastructure.persistence.purchase_unit_query_impl import (
                SQLAlchemyPurchaseUnitQuery,
            )

            result = SQLAlchemyPurchaseUnitQuery().list_purchase_units()
        assert result == ["Acme"]

    def test_empty_result(self):
        mock_db = MagicMock()
        mock_q = MagicMock()
        mock_db.query.return_value = mock_q
        mock_q.filter.return_value = mock_q
        mock_q.all.return_value = []
        with patch(
            "app.infrastructure.persistence.purchase_unit_query_impl.get_db",
            return_value=_mock_db_ctx(mock_db),
        ):
            from app.infrastructure.persistence.purchase_unit_query_impl import (
                SQLAlchemyPurchaseUnitQuery,
            )

            result = SQLAlchemyPurchaseUnitQuery().list_purchase_units()
        assert result == []
