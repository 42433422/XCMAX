"""Tests for app.fastapi_routes.shipment.schemas."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.fastapi_routes.shipment.schemas import (
    ShipmentGenerateRequest,
    ShipmentItem,
    ShipmentPrintRequest,
)


class TestShipmentItem:
    def test_valid_item(self):
        item = ShipmentItem(product_id=1, quantity=5)
        assert item.product_id == 1
        assert item.quantity == 5

    def test_optional_fields(self):
        item = ShipmentItem(product_id=1, quantity=1)
        assert item.product_name is None
        assert item.unit_price is None
        assert item.amount is None

    def test_all_fields(self):
        item = ShipmentItem(
            product_id=1, quantity=10, product_name="Test", unit_price=99.9, amount=999.0
        )
        assert item.product_name == "Test"
        assert item.unit_price == 99.9
        assert item.amount == 999.0

    def test_quantity_must_be_positive(self):
        with pytest.raises(ValidationError):
            ShipmentItem(product_id=1, quantity=0)

    def test_negative_quantity_rejected(self):
        with pytest.raises(ValidationError):
            ShipmentItem(product_id=1, quantity=-1)


class TestShipmentGenerateRequest:
    def test_default_values(self):
        req = ShipmentGenerateRequest()
        assert req.customer_name is None
        assert req.items == []
        assert req.notes is None

    def test_with_items(self):
        req = ShipmentGenerateRequest(
            customer_name="Test Corp",
            items=[ShipmentItem(product_id=1, quantity=5)],
            notes="Urgent",
        )
        assert req.customer_name == "Test Corp"
        assert len(req.items) == 1
        assert req.notes == "Urgent"


class TestShipmentPrintRequest:
    def test_valid_request(self):
        req = ShipmentPrintRequest(shipment_id=1)
        assert req.shipment_id == 1
        assert req.printer_name is None
        assert req.copies == 1

    def test_custom_copies(self):
        req = ShipmentPrintRequest(shipment_id=1, copies=5)
        assert req.copies == 5

    def test_copies_minimum_one(self):
        with pytest.raises(ValidationError):
            ShipmentPrintRequest(shipment_id=1, copies=0)

    def test_copies_maximum_ten(self):
        with pytest.raises(ValidationError):
            ShipmentPrintRequest(shipment_id=1, copies=11)

    def test_with_printer_name(self):
        req = ShipmentPrintRequest(shipment_id=1, printer_name="HP LaserJet")
        assert req.printer_name == "HP LaserJet"
