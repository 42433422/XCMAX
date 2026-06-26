"""Branch coverage for app.infrastructure.persistence.purchase_unit_query_impl.

Covers list_purchase_units dedup + get_shipment_records_by_unit filter (0/6 branches).
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest


def _mock_db_ctx(mock_db):
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=mock_db)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx


def _make_record(**overrides):
    m = MagicMock()
    defaults = {
        "id": 1,
        "purchase_unit": "Acme",
        "product_name": "P",
        "model_number": "M1",
        "quantity_kg": 10.0,
        "quantity_tins": 5,
        "tin_spec": 2.0,
        "unit_price": 3.0,
        "amount": 30.0,
        "status": "pending",
        "created_at": datetime(2026, 1, 1),
        "updated_at": datetime(2026, 1, 2),
        "printed_at": None,
        "printer_name": "",
    }
    defaults.update(overrides)
    for k, v in defaults.items():
        setattr(m, k, v)
    return m


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


class TestGetShipmentRecordsByUnit:
    def test_with_unit_name_filter(self):
        mock_db = MagicMock()
        mock_q = MagicMock()
        mock_db.query.return_value = mock_q
        mock_q.filter.return_value = mock_q
        mock_q.order_by.return_value = mock_q
        mock_q.limit.return_value = mock_q
        mock_q.all.return_value = [_make_record()]
        with patch(
            "app.infrastructure.persistence.purchase_unit_query_impl.get_db",
            return_value=_mock_db_ctx(mock_db),
        ):
            from app.infrastructure.persistence.purchase_unit_query_impl import (
                SQLAlchemyPurchaseUnitQuery,
            )

            result = SQLAlchemyPurchaseUnitQuery().get_shipment_records_by_unit("Acme")
        assert len(result) == 1
        assert result[0]["purchase_unit"] == "Acme"
        mock_q.filter.assert_called_once()

    def test_without_unit_name_no_filter(self):
        mock_db = MagicMock()
        mock_q = MagicMock()
        mock_db.query.return_value = mock_q
        mock_q.order_by.return_value = mock_q
        mock_q.limit.return_value = mock_q
        mock_q.all.return_value = [_make_record(), _make_record(id=2)]
        with patch(
            "app.infrastructure.persistence.purchase_unit_query_impl.get_db",
            return_value=_mock_db_ctx(mock_db),
        ):
            from app.infrastructure.persistence.purchase_unit_query_impl import (
                SQLAlchemyPurchaseUnitQuery,
            )

            result = SQLAlchemyPurchaseUnitQuery().get_shipment_records_by_unit(None)
        assert len(result) == 2
        mock_q.filter.assert_not_called()

    def test_none_dates_become_none(self):
        mock_db = MagicMock()
        mock_q = MagicMock()
        mock_db.query.return_value = mock_q
        mock_q.order_by.return_value = mock_q
        mock_q.limit.return_value = mock_q
        mock_q.all.return_value = [_make_record(created_at=None, updated_at=None, printed_at=None)]
        with patch(
            "app.infrastructure.persistence.purchase_unit_query_impl.get_db",
            return_value=_mock_db_ctx(mock_db),
        ):
            from app.infrastructure.persistence.purchase_unit_query_impl import (
                SQLAlchemyPurchaseUnitQuery,
            )

            result = SQLAlchemyPurchaseUnitQuery().get_shipment_records_by_unit(None)
        assert result[0]["created_at"] is None
        assert result[0]["updated_at"] is None
        assert result[0]["printed_at"] is None

    def test_with_dates_iso_format(self):
        mock_db = MagicMock()
        mock_q = MagicMock()
        mock_db.query.return_value = mock_q
        mock_q.order_by.return_value = mock_q
        mock_q.limit.return_value = mock_q
        mock_q.all.return_value = [
            _make_record(
                created_at=datetime(2026, 1, 1),
                updated_at=datetime(2026, 1, 2),
                printed_at=datetime(2026, 1, 3),
            )
        ]
        with patch(
            "app.infrastructure.persistence.purchase_unit_query_impl.get_db",
            return_value=_mock_db_ctx(mock_db),
        ):
            from app.infrastructure.persistence.purchase_unit_query_impl import (
                SQLAlchemyPurchaseUnitQuery,
            )

            result = SQLAlchemyPurchaseUnitQuery().get_shipment_records_by_unit(None)
        assert "2026" in result[0]["created_at"]
        assert "2026" in result[0]["updated_at"]
        assert "2026" in result[0]["printed_at"]
