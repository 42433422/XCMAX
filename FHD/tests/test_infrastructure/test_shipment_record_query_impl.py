"""Tests for app.infrastructure.persistence.shipment_record_query_impl — coverage ramp."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from app.infrastructure.persistence.shipment_record_query_impl import (
    SQLAlchemyShipmentRecordQuery,
)


def _mock_db_ctx(mock_db):
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=mock_db)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx


def _make_record(**overrides):
    m = MagicMock()
    defaults = {
        "id": 1,
        "purchase_unit": "测试客户",
        "product_name": "产品A",
        "model_number": "M-001",
        "quantity": 10,
        "created_at": datetime(2026, 1, 15),
    }
    defaults.update(overrides)
    for k, v in defaults.items():
        setattr(m, k, v)
    return m


def _make_column_mocks(field_names):
    """Create column mocks for sa_inspect(ShipmentRecord).columns iteration."""
    cols = []
    for name in field_names:
        col = MagicMock()
        col.name = name
        cols.append(col)
    return cols


_SHIPMENT_FIELDS = ["id", "purchase_unit", "product_name", "model_number", "quantity", "created_at"]


@pytest.fixture
def query():
    return SQLAlchemyShipmentRecordQuery()


class TestQueryShipments:
    def test_returns_success_empty(self, query):
        mock_db = MagicMock()
        mock_inspector = MagicMock()
        mock_inspector.get_table_names.return_value = ["shipment_records"]
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.count.return_value = 0
        mock_query.order_by.return_value.limit.return_value.offset.return_value.all.return_value = []
        with (
            patch(
                "app.infrastructure.persistence.shipment_record_query_impl.get_db",
                return_value=_mock_db_ctx(mock_db),
            ),
            patch(
                "app.infrastructure.persistence.shipment_record_query_impl.sa_inspect",
                return_value=mock_inspector,
            ),
            patch(
                "app.infrastructure.persistence.shipment_record_query_impl.resolve_purchase_unit",
                return_value=None,
            ),
        ):
            result = query.query_shipments()
        assert result["success"] is True
        assert result["total"] == 0

    def test_table_not_found(self, query):
        mock_db = MagicMock()
        mock_inspector = MagicMock()
        mock_inspector.get_table_names.return_value = ["other_table"]
        with (
            patch(
                "app.infrastructure.persistence.shipment_record_query_impl.get_db",
                return_value=_mock_db_ctx(mock_db),
            ),
            patch(
                "app.infrastructure.persistence.shipment_record_query_impl.sa_inspect",
                return_value=mock_inspector,
            ),
        ):
            result = query.query_shipments()
        assert result["success"] is True
        assert result["data"] == []

    def test_with_unit_name(self, query):
        mock_db = MagicMock()
        mock_inspector = MagicMock()
        mock_inspector.get_table_names.return_value = ["shipment_records"]
        mock_inspector.columns = _make_column_mocks(_SHIPMENT_FIELDS)
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.count.return_value = 1
        mock_query.order_by.return_value.limit.return_value.offset.return_value.all.return_value = [
            _make_record()
        ]
        mock_resolved = MagicMock()
        mock_resolved.unit_name = "测试客户"
        with (
            patch(
                "app.infrastructure.persistence.shipment_record_query_impl.get_db",
                return_value=_mock_db_ctx(mock_db),
            ),
            patch(
                "app.infrastructure.persistence.shipment_record_query_impl.sa_inspect",
                return_value=mock_inspector,
            ),
            patch(
                "app.infrastructure.persistence.shipment_record_query_impl.resolve_purchase_unit",
                return_value=mock_resolved,
            ),
        ):
            result = query.query_shipments(unit_name="测试")
        assert result["success"] is True

    def test_db_error(self, query):
        with (
            patch(
                "app.infrastructure.persistence.shipment_record_query_impl.get_db",
                side_effect=RuntimeError("DB fail"),
            ),
            patch(
                "app.infrastructure.persistence.shipment_record_query_impl.resolve_purchase_unit",
                return_value=None,
            ),
        ):
            result = query.query_shipments()
        assert result["success"] is False
        assert "DB fail" in result["message"]


class TestSearchShipments:
    def test_empty_query(self, query):
        result = query.search_shipments("")
        assert result == []

    def test_none_query(self, query):
        result = query.search_shipments(None)
        assert result == []

    def test_search_returns_results(self, query):
        mock_db = MagicMock()
        mock_inspector = MagicMock()
        mock_inspector.get_table_names.return_value = ["shipment_records"]
        mock_inspector.columns = _make_column_mocks(_SHIPMENT_FIELDS)
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value.limit.return_value.all.return_value = [_make_record()]
        with (
            patch(
                "app.infrastructure.persistence.shipment_record_query_impl.get_db",
                return_value=_mock_db_ctx(mock_db),
            ),
            patch(
                "app.infrastructure.persistence.shipment_record_query_impl.sa_inspect",
                return_value=mock_inspector,
            ),
        ):
            result = query.search_shipments("测试")
        assert len(result) == 1

    def test_search_db_error(self, query):
        with patch(
            "app.infrastructure.persistence.shipment_record_query_impl.get_db",
            side_effect=RuntimeError("err"),
        ):
            result = query.search_shipments("test")
        assert result == []


class TestGetShipmentById:
    def test_none_id(self, query):
        result = query.get_shipment_by_id(None)
        assert result is None

    def test_empty_id(self, query):
        result = query.get_shipment_by_id("")
        assert result is None

    def test_found(self, query):
        mock_db = MagicMock()
        mock_inspector = MagicMock()
        mock_inspector.get_table_names.return_value = ["shipment_records"]
        mock_inspector.columns = _make_column_mocks(_SHIPMENT_FIELDS)
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = _make_record()
        with (
            patch(
                "app.infrastructure.persistence.shipment_record_query_impl.get_db",
                return_value=_mock_db_ctx(mock_db),
            ),
            patch(
                "app.infrastructure.persistence.shipment_record_query_impl.sa_inspect",
                return_value=mock_inspector,
            ),
        ):
            result = query.get_shipment_by_id("1")
        assert result is not None
        assert result["id"] == 1

    def test_not_found(self, query):
        mock_db = MagicMock()
        mock_inspector = MagicMock()
        mock_inspector.get_table_names.return_value = ["shipment_records"]
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = None
        with (
            patch(
                "app.infrastructure.persistence.shipment_record_query_impl.get_db",
                return_value=_mock_db_ctx(mock_db),
            ),
            patch(
                "app.infrastructure.persistence.shipment_record_query_impl.sa_inspect",
                return_value=mock_inspector,
            ),
        ):
            result = query.get_shipment_by_id("999")
        assert result is None

    def test_db_error(self, query):
        with patch(
            "app.infrastructure.persistence.shipment_record_query_impl.get_db",
            side_effect=RuntimeError("err"),
        ):
            result = query.get_shipment_by_id("1")
        assert result is None


class TestGetLatestShipments:
    def test_zero_limit(self, query):
        result = query.get_latest_shipments(0)
        assert result == []

    def test_negative_limit(self, query):
        result = query.get_latest_shipments(-1)
        assert result == []

    def test_returns_results(self, query):
        mock_db = MagicMock()
        mock_inspector = MagicMock()
        mock_inspector.get_table_names.return_value = ["shipment_records"]
        mock_inspector.columns = _make_column_mocks(_SHIPMENT_FIELDS)
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.order_by.return_value.limit.return_value.all.return_value = [_make_record()]
        with (
            patch(
                "app.infrastructure.persistence.shipment_record_query_impl.get_db",
                return_value=_mock_db_ctx(mock_db),
            ),
            patch(
                "app.infrastructure.persistence.shipment_record_query_impl.sa_inspect",
                return_value=mock_inspector,
            ),
        ):
            result = query.get_latest_shipments(5)
        assert len(result) == 1

    def test_db_error(self, query):
        with patch(
            "app.infrastructure.persistence.shipment_record_query_impl.get_db",
            side_effect=RuntimeError("err"),
        ):
            result = query.get_latest_shipments(5)
        assert result == []
