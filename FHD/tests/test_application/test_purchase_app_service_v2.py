"""Tests for app.application.purchase_app_service_v2."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.application.purchase_app_service_v2 import PurchaseAppServiceV2


@pytest.fixture
def mock_purchase_svc():
    svc = MagicMock()
    svc.get_suppliers.return_value = {"success": True, "data": []}
    svc.get_supplier.return_value = {"success": True, "data": {"id": 1}}
    svc.get_supplier_summary.return_value = {"success": True, "data": {}}
    svc.create_supplier.return_value = {"success": True, "data": {"id": 1}}
    svc.update_supplier.return_value = {"success": True, "data": {"id": 1}}
    svc.delete_supplier.return_value = {"success": True}
    svc.get_purchase_orders.return_value = {"success": True, "data": []}
    svc.get_purchase_order.return_value = {"success": True, "data": {"id": 1}}
    svc.create_purchase_order.return_value = {"success": True, "data": {"id": 1}}
    svc.update_purchase_order.return_value = {"success": True, "data": {"id": 1}}
    svc.approve_purchase_order.return_value = {"success": True}
    svc.cancel_purchase_order.return_value = {"success": True}
    svc.get_purchase_inbounds.return_value = {"success": True, "data": []}
    svc.create_purchase_inbound.return_value = {"success": True, "data": {"id": 1}}
    svc.get_purchase_summary.return_value = {"success": True, "data": {}}
    return svc


@pytest.fixture
def service(mock_purchase_svc):
    svc = PurchaseAppServiceV2()
    svc._svc = mock_purchase_svc
    return svc


class TestPurchaseAppServiceV2:
    def test_get_suppliers(self, service, mock_purchase_svc):
        result = service.get_suppliers()
        assert result["success"] is True
        mock_purchase_svc.get_suppliers.assert_called_once()

    def test_get_suppliers_with_filters(self, service, mock_purchase_svc):
        result = service.get_suppliers(status="active", keyword="test")
        mock_purchase_svc.get_suppliers.assert_called_once_with(status="active", keyword="test")

    def test_get_supplier(self, service, mock_purchase_svc):
        result = service.get_supplier(1)
        assert result["success"] is True
        mock_purchase_svc.get_supplier.assert_called_once_with(1)

    def test_get_supplier_summary(self, service, mock_purchase_svc):
        result = service.get_supplier_summary()
        assert result["success"] is True

    def test_create_supplier_publishes_event(self, service, mock_purchase_svc):
        with patch.object(service, "_try_publish") as mock_pub:
            result = service.create_supplier({"name": "Test"})
            mock_pub.assert_called_once()
            call_args = mock_pub.call_args
            assert call_args[0][0] == "purchase.supplier.created"

    def test_create_supplier_no_event_on_failure(self, service, mock_purchase_svc):
        mock_purchase_svc.create_supplier.return_value = {"success": False}
        with patch.object(service, "_try_publish") as mock_pub:
            result = service.create_supplier({"name": "Test"})
            mock_pub.assert_not_called()

    def test_update_supplier_publishes_event(self, service, mock_purchase_svc):
        with patch.object(service, "_try_publish") as mock_pub:
            result = service.update_supplier(1, {"name": "Updated"})
            mock_pub.assert_called_once()
            assert mock_pub.call_args[0][0] == "purchase.supplier.updated"

    def test_delete_supplier_publishes_event(self, service, mock_purchase_svc):
        with patch.object(service, "_try_publish") as mock_pub:
            result = service.delete_supplier(1)
            mock_pub.assert_called_once()
            assert mock_pub.call_args[0][0] == "purchase.supplier.deleted"

    def test_get_purchase_orders(self, service, mock_purchase_svc):
        result = service.get_purchase_orders()
        assert result["success"] is True

    def test_create_purchase_order_publishes_event(self, service, mock_purchase_svc):
        with patch.object(service, "_try_publish") as mock_pub:
            result = service.create_purchase_order({"supplier_id": 1})
            mock_pub.assert_called_once()
            assert mock_pub.call_args[0][0] == "purchase.order.created"

    def test_approve_purchase_order_publishes_event(self, service, mock_purchase_svc):
        with patch.object(service, "_try_publish") as mock_pub:
            result = service.approve_purchase_order(1, approver="admin")
            mock_pub.assert_called_once()
            assert mock_pub.call_args[0][0] == "purchase.order.approved"

    def test_cancel_purchase_order_publishes_event(self, service, mock_purchase_svc):
        with patch.object(service, "_try_publish") as mock_pub:
            result = service.cancel_purchase_order(1)
            mock_pub.assert_called_once()
            assert mock_pub.call_args[0][0] == "purchase.order.cancelled"

    def test_get_purchase_inbounds(self, service, mock_purchase_svc):
        result = service.get_purchase_inbounds()
        assert result["success"] is True

    def test_create_purchase_inbound_publishes_event(self, service, mock_purchase_svc):
        with patch.object(service, "_try_publish") as mock_pub:
            result = service.create_purchase_inbound({"order_id": 1})
            mock_pub.assert_called_once()
            assert mock_pub.call_args[0][0] == "purchase.inbound.created"

    def test_get_purchase_summary(self, service, mock_purchase_svc):
        result = service.get_purchase_summary()
        assert result["success"] is True

    def test_try_publish_handles_errors(self, service):
        with patch("app.neuro_bus.bus.get_neuro_bus", side_effect=RuntimeError("no bus")):
            service._try_publish("test.event", {"key": "val"})
            # Should not raise
