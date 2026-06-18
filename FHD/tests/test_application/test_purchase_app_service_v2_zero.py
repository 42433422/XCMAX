"""Tests for app.application.purchase_app_service_v2."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from app.application.purchase_app_service_v2 import PurchaseAppServiceV2


@pytest.fixture
def mock_purchase_svc() -> MagicMock:
    svc = MagicMock()
    svc.get_suppliers.return_value = {"success": True, "data": []}
    svc.get_supplier.return_value = {"success": True, "data": {"id": 1}}
    svc.get_supplier_summary.return_value = {"total": 5}
    svc.create_supplier.return_value = {"success": True, "data": {"id": 1, "name": "S1"}}
    svc.update_supplier.return_value = {"success": True, "data": {"id": 1}}
    svc.delete_supplier.return_value = {"success": True}
    svc.get_purchase_orders.return_value = {"success": True, "data": []}
    svc.get_purchase_order.return_value = {"success": True, "data": {"id": 10}}
    svc.create_purchase_order.return_value = {"success": True, "data": {"id": 10}}
    svc.update_purchase_order.return_value = {"success": True, "data": {"id": 10}}
    svc.approve_purchase_order.return_value = {"success": True, "data": {"id": 10}}
    svc.cancel_purchase_order.return_value = {"success": True, "data": {"id": 10}}
    svc.get_purchase_inbounds.return_value = {"success": True, "data": []}
    svc.create_purchase_inbound.return_value = {"success": True, "data": {"id": 20}}
    svc.get_purchase_summary.return_value = {"total_orders": 100}
    return svc


@pytest.fixture
def service(mock_purchase_svc: MagicMock) -> PurchaseAppServiceV2:
    svc = PurchaseAppServiceV2()
    svc._svc = mock_purchase_svc
    return svc


class TestPurchaseAppServiceV2Suppliers:
    """Tests for supplier-related methods."""

    def test_get_suppliers(self, service: PurchaseAppServiceV2) -> None:
        result = service.get_suppliers()
        assert result["success"] is True

    def test_get_suppliers_with_filters(self, service: PurchaseAppServiceV2) -> None:
        result = service.get_suppliers(status="active", keyword="test")
        assert result["success"] is True

    def test_get_supplier(self, service: PurchaseAppServiceV2) -> None:
        result = service.get_supplier(1)
        assert result["success"] is True

    def test_get_supplier_summary(self, service: PurchaseAppServiceV2) -> None:
        result = service.get_supplier_summary()
        assert result["total"] == 5

    @patch("app.application.purchase_app_service_v2.PurchaseAppServiceV2._try_publish")
    def test_create_supplier_publishes_event(
        self, mock_publish: MagicMock, service: PurchaseAppServiceV2
    ) -> None:
        result = service.create_supplier({"name": "S1"})
        assert result["success"] is True
        mock_publish.assert_called_once_with(
            "purchase.supplier.created", {"supplier": {"id": 1, "name": "S1"}}
        )

    @patch("app.application.purchase_app_service_v2.PurchaseAppServiceV2._try_publish")
    def test_create_supplier_no_event_on_failure(
        self, mock_publish: MagicMock, service: PurchaseAppServiceV2, mock_purchase_svc: MagicMock
    ) -> None:
        mock_purchase_svc.create_supplier.return_value = {"success": False}
        result = service.create_supplier({"name": "S1"})
        assert result["success"] is False
        mock_publish.assert_not_called()

    @patch("app.application.purchase_app_service_v2.PurchaseAppServiceV2._try_publish")
    def test_update_supplier_publishes_event(
        self, mock_publish: MagicMock, service: PurchaseAppServiceV2
    ) -> None:
        result = service.update_supplier(1, {"name": "Updated"})
        assert result["success"] is True
        mock_publish.assert_called_once()

    @patch("app.application.purchase_app_service_v2.PurchaseAppServiceV2._try_publish")
    def test_delete_supplier_publishes_event(
        self, mock_publish: MagicMock, service: PurchaseAppServiceV2
    ) -> None:
        result = service.delete_supplier(1)
        assert result["success"] is True
        mock_publish.assert_called_once_with("purchase.supplier.deleted", {"supplier_id": 1})


class TestPurchaseAppServiceV2Orders:
    """Tests for purchase order methods."""

    def test_get_purchase_orders(self, service: PurchaseAppServiceV2) -> None:
        result = service.get_purchase_orders()
        assert result["success"] is True

    def test_get_purchase_orders_with_filters(self, service: PurchaseAppServiceV2) -> None:
        result = service.get_purchase_orders(supplier_id=1, status="pending", page=2, per_page=50)
        assert result["success"] is True

    def test_get_purchase_order(self, service: PurchaseAppServiceV2) -> None:
        result = service.get_purchase_order(10)
        assert result["success"] is True

    @patch("app.application.purchase_app_service_v2.PurchaseAppServiceV2._try_publish")
    def test_create_purchase_order_publishes_event(
        self, mock_publish: MagicMock, service: PurchaseAppServiceV2
    ) -> None:
        result = service.create_purchase_order({"supplier_id": 1})
        assert result["success"] is True
        mock_publish.assert_called_once()

    @patch("app.application.purchase_app_service_v2.PurchaseAppServiceV2._try_publish")
    def test_approve_purchase_order_publishes_event(
        self, mock_publish: MagicMock, service: PurchaseAppServiceV2
    ) -> None:
        result = service.approve_purchase_order(10, approver="admin")
        assert result["success"] is True
        mock_publish.assert_called_once_with(
            "purchase.order.approved", {"order_id": 10, "approver": "admin"}
        )

    @patch("app.application.purchase_app_service_v2.PurchaseAppServiceV2._try_publish")
    def test_cancel_purchase_order_publishes_event(
        self, mock_publish: MagicMock, service: PurchaseAppServiceV2
    ) -> None:
        result = service.cancel_purchase_order(10)
        assert result["success"] is True
        mock_publish.assert_called_once_with("purchase.order.cancelled", {"order_id": 10})


class TestPurchaseAppServiceV2Inbounds:
    """Tests for purchase inbound methods."""

    def test_get_purchase_inbounds(self, service: PurchaseAppServiceV2) -> None:
        result = service.get_purchase_inbounds()
        assert result["success"] is True

    @patch("app.application.purchase_app_service_v2.PurchaseAppServiceV2._try_publish")
    def test_create_purchase_inbound_publishes_event(
        self, mock_publish: MagicMock, service: PurchaseAppServiceV2
    ) -> None:
        result = service.create_purchase_inbound({"order_id": 10})
        assert result["success"] is True
        mock_publish.assert_called_once()


class TestPurchaseAppServiceV2Summary:
    """Tests for summary method."""

    def test_get_purchase_summary(self, service: PurchaseAppServiceV2) -> None:
        result = service.get_purchase_summary()
        assert result["total_orders"] == 100


class TestPurchaseAppServiceV2TryPublish:
    """Tests for _try_publish error handling."""

    def test_try_publish_does_not_raise_on_error(self, service: PurchaseAppServiceV2) -> None:
        # get_neuro_bus is lazily imported inside _try_publish, patch at source
        with patch("app.neuro_bus.bus.get_neuro_bus", side_effect=ImportError("no bus")):
            service._try_publish("test.event", {"key": "val"})
            # Should not raise

    def test_lazy_load_purchase_svc(self) -> None:
        svc = PurchaseAppServiceV2()
        assert svc._svc is None
        # PurchaseService is lazily imported inside _purchase_svc, patch at source
        with patch("app.services.purchase_service.PurchaseService") as mock_cls:
            mock_cls.return_value = MagicMock()
            result = svc._purchase_svc()
            assert result is not None
            assert svc._svc is not None
