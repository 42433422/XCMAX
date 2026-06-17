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
    """Tests for ShipmentItem schema."""

    def test_valid_item(self) -> None:
        item = ShipmentItem(product_id=1, quantity=5)
        assert item.product_id == 1
        assert item.quantity == 5
        assert item.product_name is None
        assert item.unit_price is None
        assert item.amount is None

    def test_item_with_all_fields(self) -> None:
        item = ShipmentItem(
            product_id=1,
            quantity=10,
            product_name="测试产品",
            unit_price=99.9,
            amount=999.0,
        )
        assert item.product_name == "测试产品"
        assert item.unit_price == 99.9
        assert item.amount == 999.0

    def test_quantity_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            ShipmentItem(product_id=1, quantity=0)

    def test_quantity_must_be_positive_negative(self) -> None:
        with pytest.raises(ValidationError):
            ShipmentItem(product_id=1, quantity=-1)

    def test_missing_required_fields(self) -> None:
        with pytest.raises(ValidationError):
            ShipmentItem()


class TestShipmentGenerateRequest:
    """Tests for ShipmentGenerateRequest schema."""

    def test_default_values(self) -> None:
        req = ShipmentGenerateRequest()
        assert req.customer_name is None
        assert req.items == []
        assert req.notes is None

    def test_with_customer_name(self) -> None:
        req = ShipmentGenerateRequest(customer_name="测试客户")
        assert req.customer_name == "测试客户"

    def test_with_items(self) -> None:
        items = [ShipmentItem(product_id=1, quantity=5)]
        req = ShipmentGenerateRequest(items=items)
        assert len(req.items) == 1

    def test_with_notes(self) -> None:
        req = ShipmentGenerateRequest(notes="加急处理")
        assert req.notes == "加急处理"


class TestShipmentPrintRequest:
    """Tests for ShipmentPrintRequest schema."""

    def test_valid_request(self) -> None:
        req = ShipmentPrintRequest(shipment_id=1)
        assert req.shipment_id == 1
        assert req.printer_name is None
        assert req.copies == 1

    def test_custom_copies(self) -> None:
        req = ShipmentPrintRequest(shipment_id=1, copies=3)
        assert req.copies == 3

    def test_copies_minimum(self) -> None:
        with pytest.raises(ValidationError):
            ShipmentPrintRequest(shipment_id=1, copies=0)

    def test_copies_maximum(self) -> None:
        with pytest.raises(ValidationError):
            ShipmentPrintRequest(shipment_id=1, copies=11)

    def test_with_printer_name(self) -> None:
        req = ShipmentPrintRequest(shipment_id=1, printer_name="HP LaserJet")
        assert req.printer_name == "HP LaserJet"

    def test_missing_shipment_id(self) -> None:
        with pytest.raises(ValidationError):
            ShipmentPrintRequest()
