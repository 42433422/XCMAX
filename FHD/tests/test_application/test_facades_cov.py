from __future__ import annotations

"""Branch coverage for app/application/facades/shipment_event_primary.py."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_facade(event_primary_enabled: bool = False):
    """Build a ShipmentApplicationServiceEventPrimary with a mocked core service."""
    core = MagicMock()
    core.create_shipment.return_value = {"success": True, "id": 1}
    core.cancel_shipment.return_value = {"success": True}
    core.delete_shipment.return_value = {"success": True}
    core.mark_as_printed.return_value = {"success": True}

    from app.application.facades.shipment_event_primary import (
        ShipmentApplicationServiceEventPrimary,
    )

    facade = ShipmentApplicationServiceEventPrimary(core)

    # Patch the flag so we can choose mode
    patch_target = "app.application.facades.shipment_event_primary.is_event_primary_enabled"
    return facade, core, patch(patch_target, return_value=event_primary_enabled)


class TestShipmentEventPrimaryFallback:
    """When event-primary flag is OFF, all methods delegate to core."""

    def test_create_shipment_delegates(self):
        facade, core, flag = _make_facade(event_primary_enabled=False)
        with flag:
            result = facade.create_shipment("公司A", [{"product_id": 1, "qty": 2}])
        core.create_shipment.assert_called_once()
        assert result["success"] is True

    def test_cancel_shipment_delegates(self):
        facade, core, flag = _make_facade(event_primary_enabled=False)
        with flag:
            result = facade.cancel_shipment(42)
        core.cancel_shipment.assert_called_once_with(42)
        assert result["success"] is True

    def test_delete_shipment_delegates(self):
        facade, core, flag = _make_facade(event_primary_enabled=False)
        with flag:
            result = facade.delete_shipment(99)
        core.delete_shipment.assert_called_once_with(99)
        assert result["success"] is True

    def test_mark_as_printed_delegates(self):
        facade, core, flag = _make_facade(event_primary_enabled=False)
        with flag:
            result = facade.mark_as_printed(7, "Printer1")
        core.mark_as_printed.assert_called_once_with(7, "Printer1")
        assert result["success"] is True

    def test_getattr_delegates_read_method(self):
        facade, core, flag = _make_facade(event_primary_enabled=False)
        core.get_shipment = MagicMock(return_value={"id": 1})
        with flag:
            result = facade.get_shipment(1)
        core.get_shipment.assert_called_once_with(1)


class TestShipmentEventPrimaryEnabled:
    """When event-primary is ON, methods go through NeuroBus command pipeline."""

    def _patch_bus_success(self, result=None):
        if result is None:
            result = {"success": True, "id": 42}

        mock_gw = MagicMock()
        mock_gw.prepare_command_event.return_value = "rid-123"
        mock_gw.wait_for_result = AsyncMock(return_value=result)

        mock_bus = MagicMock()
        mock_bus.publish.return_value = True

        return mock_gw, mock_bus

    def test_create_shipment_event_primary_success(self):
        facade, core, flag = _make_facade(event_primary_enabled=True)
        gw, bus = self._patch_bus_success()

        with (
            flag,
            patch(
                "app.application.facades.shipment_event_primary.get_command_gateway",
                return_value=gw,
            ),
            patch(
                "app.application.facades.shipment_event_primary.get_neuro_bus",
                return_value=bus,
            ),
            patch(
                "app.application.facades.shipment_event_primary.run_coroutine_on_neuro_loop",
                return_value={"success": True, "id": 42},
            ),
        ):
            result = facade.create_shipment("公司A", [])
        assert result["success"] is True

    def test_create_shipment_event_primary_bus_not_running(self):
        facade, core, flag = _make_facade(event_primary_enabled=True)
        gw = MagicMock()
        gw.prepare_command_event.return_value = "rid-1"
        bus = MagicMock()
        bus.publish.return_value = False  # bus rejected

        with (
            flag,
            patch(
                "app.application.facades.shipment_event_primary.get_command_gateway",
                return_value=gw,
            ),
            patch(
                "app.application.facades.shipment_event_primary.get_neuro_bus",
                return_value=bus,
            ),
            patch(
                "app.application.facades.shipment_event_primary.run_coroutine_on_neuro_loop",
                return_value={"success": False, "message": "NeuroBus 未运行或无法入队"},
            ),
        ):
            result = facade.create_shipment("公司A", [])
        assert result["success"] is False

    def test_cancel_shipment_event_primary(self):
        facade, core, flag = _make_facade(event_primary_enabled=True)
        gw, bus = self._patch_bus_success()

        with (
            flag,
            patch(
                "app.application.facades.shipment_event_primary.get_command_gateway",
                return_value=gw,
            ),
            patch(
                "app.application.facades.shipment_event_primary.get_neuro_bus",
                return_value=bus,
            ),
            patch(
                "app.application.facades.shipment_event_primary.run_coroutine_on_neuro_loop",
                return_value={"success": True},
            ),
        ):
            result = facade.cancel_shipment(5)
        assert result["success"] is True

    def test_delete_shipment_event_primary(self):
        facade, core, flag = _make_facade(event_primary_enabled=True)
        gw, bus = self._patch_bus_success()

        with (
            flag,
            patch(
                "app.application.facades.shipment_event_primary.get_command_gateway",
                return_value=gw,
            ),
            patch(
                "app.application.facades.shipment_event_primary.get_neuro_bus",
                return_value=bus,
            ),
            patch(
                "app.application.facades.shipment_event_primary.run_coroutine_on_neuro_loop",
                return_value={"success": True},
            ),
        ):
            result = facade.delete_shipment(5)
        assert result["success"] is True

    def test_mark_as_printed_event_primary(self):
        facade, core, flag = _make_facade(event_primary_enabled=True)
        gw, bus = self._patch_bus_success()

        with (
            flag,
            patch(
                "app.application.facades.shipment_event_primary.get_command_gateway",
                return_value=gw,
            ),
            patch(
                "app.application.facades.shipment_event_primary.get_neuro_bus",
                return_value=bus,
            ),
            patch(
                "app.application.facades.shipment_event_primary.run_coroutine_on_neuro_loop",
                return_value={"success": True},
            ),
        ):
            result = facade.mark_as_printed(5, "PrinterA")
        assert result["success"] is True

    def test_run_cmd_handles_recoverable_error(self):
        facade, core, flag = _make_facade(event_primary_enabled=True)
        gw, bus = self._patch_bus_success()

        with (
            flag,
            patch(
                "app.application.facades.shipment_event_primary.get_command_gateway",
                return_value=gw,
            ),
            patch(
                "app.application.facades.shipment_event_primary.get_neuro_bus",
                return_value=bus,
            ),
            patch(
                "app.application.facades.shipment_event_primary.run_coroutine_on_neuro_loop",
                side_effect=RuntimeError("loop error"),
            ),
        ):
            result = facade.create_shipment("公司A", [])
        assert result["success"] is False
        assert "loop error" in result["message"]
