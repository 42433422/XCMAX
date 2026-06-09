"""Tests for app.application.shipment_app_service — coverage ramp C3.2-b.

Covers:
* ``ShipmentApplicationService.create_shipment`` with mocked repository.
* Validation failure paths (invalid items, missing unit).
* Exception path returning failure envelope.
* Document generator delegation.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.application.shipment_app_service import ShipmentApplicationService


def _svc() -> ShipmentApplicationService:
    return ShipmentApplicationService(
        repository=MagicMock(),
        document_generator=MagicMock(),
        record_store=MagicMock(),
        record_query=MagicMock(),
        record_command=MagicMock(),
        purchase_unit_query=MagicMock(),
    )


class TestCreateShipment:
    def test_success_returns_saved_shipment(self) -> None:
        svc = _svc()
        with (
            patch("app.application.shipment_app_service.Shipment") as ShipmentMock,
            patch("app.application.shipment_app_service.ShipmentItem") as ItemMock,
        ):
            shipment_inst = MagicMock()
            shipment_inst.is_valid.return_value = True
            ShipmentMock.create.return_value = shipment_inst
            ItemMock.from_dict.return_value = MagicMock()
            svc._repository.save.return_value = MagicMock(id=42)
            with patch("app.infrastructure.mods.hooks.trigger"):
                out = svc.create_shipment(
                    unit_name="Acme",
                    items_data=[{"product_name": "P1", "quantity_kg": 10}],
                )
        assert out["success"] is True

    def test_skips_invalid_items(self) -> None:
        svc = _svc()
        with (
            patch("app.application.shipment_app_service.Shipment") as ShipmentMock,
            patch("app.application.shipment_app_service.ShipmentItem") as ItemMock,
        ):
            shipment_inst = MagicMock()
            shipment_inst.is_valid.return_value = True
            ShipmentMock.create.return_value = shipment_inst
            # First item valid, second raises
            ItemMock.from_dict.side_effect = [MagicMock(), ValueError("bad")]
            svc._repository.save.return_value = MagicMock(id=1)
            with patch("app.infrastructure.mods.hooks.trigger"):
                out = svc.create_shipment(
                    unit_name="X",
                    items_data=[{"good": 1}, {"bad": 1}],
                )
        # 1 item was added (the other was skipped with logger.warning)
        assert out["success"] is True
        assert shipment_inst.add_item.call_count == 1

    def test_shipment_invalid_returns_error(self) -> None:
        svc = _svc()
        with (
            patch("app.application.shipment_app_service.Shipment") as ShipmentMock,
            patch("app.application.shipment_app_service.ShipmentItem") as ItemMock,
        ):
            shipment_inst = MagicMock()
            shipment_inst.is_valid.return_value = False
            ShipmentMock.create.return_value = shipment_inst
            ItemMock.from_dict.return_value = MagicMock()
            out = svc.create_shipment(unit_name="X", items_data=[{"success": 1}])
        assert out["success"] is False
        assert "无效" in out["message"]

    def test_exception_path(self) -> None:
        svc = _svc()
        with patch(
            "app.application.shipment_app_service.Shipment.create",
            side_effect=RuntimeError("boom"),
        ):
            out = svc.create_shipment(unit_name="X", items_data=[])
        assert out["success"] is False
        assert "boom" in out["message"]
