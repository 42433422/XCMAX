"""Branch coverage for app.application.facades.shipment_event_primary.

Covers event-primary enabled/disabled branches, dispatch timeout, run_cmd error (0/10 branches).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_facade():
    from app.application.facades.shipment_event_primary import (
        ShipmentApplicationServiceEventPrimary,
    )

    core = MagicMock()
    return ShipmentApplicationServiceEventPrimary(core), core


class TestGetattrDelegation:
    def test_unknown_method_delegates_to_core(self):
        facade, core = _make_facade()
        core.some_method = MagicMock(return_value="ok")
        # __getattr__ delegates to core
        assert facade.some_method() == "ok"


class TestCreateShipment:
    def test_event_primary_disabled_delegates_to_core(self):
        facade, core = _make_facade()
        core.create_shipment.return_value = {"success": True}
        with patch(
            "app.application.facades.shipment_event_primary.is_event_primary_enabled",
            return_value=False,
        ):
            result = facade.create_shipment("Acme", [{"name": "P"}], "c", "p")
        core.create_shipment.assert_called_once_with("Acme", [{"name": "P"}], "c", "p")
        assert result == {"success": True}

    def test_event_primary_enabled_dispatches_command(self):
        facade, core = _make_facade()
        with (
            patch(
                "app.application.facades.shipment_event_primary.is_event_primary_enabled",
                return_value=True,
            ),
            patch(
                "app.application.facades.shipment_event_primary._neuro_runtime_ready",
                return_value=True,
            ),
            patch.object(facade, "_dispatch_command", new=MagicMock(return_value=object())),
            patch.object(facade, "_run_cmd", return_value={"success": True}) as mock_run,
        ):
            result = facade.create_shipment("Acme", [{"name": "P"}], "c", "p")
        assert result == {"success": True}
        mock_run.assert_called_once()


class TestCancelShipment:
    def test_event_primary_disabled_delegates_to_core(self):
        facade, core = _make_facade()
        core.cancel_shipment.return_value = {"success": True}
        with patch(
            "app.application.facades.shipment_event_primary.is_event_primary_enabled",
            return_value=False,
        ):
            result = facade.cancel_shipment(5)
        core.cancel_shipment.assert_called_once_with(5)
        assert result == {"success": True}

    def test_event_primary_enabled_dispatches_command(self):
        facade, core = _make_facade()
        with (
            patch(
                "app.application.facades.shipment_event_primary.is_event_primary_enabled",
                return_value=True,
            ),
            patch(
                "app.application.facades.shipment_event_primary._neuro_runtime_ready",
                return_value=True,
            ),
            patch.object(facade, "_dispatch_command", new=MagicMock(return_value=object())),
            patch.object(facade, "_run_cmd", return_value={"success": True}) as mock_run,
        ):
            result = facade.cancel_shipment(5)
        assert result == {"success": True}
        mock_run.assert_called_once()


class TestDeleteShipment:
    def test_event_primary_disabled_delegates_to_core(self):
        facade, core = _make_facade()
        core.delete_shipment.return_value = {"success": True}
        with patch(
            "app.application.facades.shipment_event_primary.is_event_primary_enabled",
            return_value=False,
        ):
            result = facade.delete_shipment(5)
        core.delete_shipment.assert_called_once_with(5)
        assert result == {"success": True}

    def test_event_primary_enabled_dispatches_command(self):
        facade, core = _make_facade()
        with (
            patch(
                "app.application.facades.shipment_event_primary.is_event_primary_enabled",
                return_value=True,
            ),
            patch(
                "app.application.facades.shipment_event_primary._neuro_runtime_ready",
                return_value=True,
            ),
            patch.object(facade, "_dispatch_command", new=MagicMock(return_value=object())),
            patch.object(facade, "_run_cmd", return_value={"success": True}) as mock_run,
        ):
            result = facade.delete_shipment(5)
        assert result == {"success": True}
        mock_run.assert_called_once()


class TestMarkAsPrinted:
    def test_event_primary_disabled_delegates_to_core(self):
        facade, core = _make_facade()
        core.mark_as_printed.return_value = {"success": True}
        with patch(
            "app.application.facades.shipment_event_primary.is_event_primary_enabled",
            return_value=False,
        ):
            result = facade.mark_as_printed(5, "printer1")
        core.mark_as_printed.assert_called_once_with(5, "printer1")
        assert result == {"success": True}

    def test_event_primary_enabled_dispatches_command(self):
        facade, core = _make_facade()
        with (
            patch(
                "app.application.facades.shipment_event_primary.is_event_primary_enabled",
                return_value=True,
            ),
            patch(
                "app.application.facades.shipment_event_primary._neuro_runtime_ready",
                return_value=True,
            ),
            patch.object(facade, "_dispatch_command", new=MagicMock(return_value=object())),
            patch.object(facade, "_run_cmd", return_value={"success": True}) as mock_run,
        ):
            result = facade.mark_as_printed(5, "printer1")
        assert result == {"success": True}
        mock_run.assert_called_once()


class TestDispatchCommand:
    @pytest.mark.asyncio
    async def test_dispatch_bus_not_publishing_returns_failure(self):
        facade, _ = _make_facade()
        mock_gw = MagicMock()
        mock_bus = MagicMock()
        mock_bus.publish.return_value = False
        with (
            patch(
                "app.application.facades.shipment_event_primary.get_command_gateway",
                return_value=mock_gw,
            ),
            patch(
                "app.application.facades.shipment_event_primary.get_neuro_bus",
                return_value=mock_bus,
            ),
        ):
            result = await facade._dispatch_command("shipment.created", {"x": 1})
        assert result["success"] is False
        assert "NeuroBus" in result["message"]
        mock_gw.cancel_pending.assert_called_once()

    @pytest.mark.asyncio
    async def test_dispatch_success(self):
        facade, _ = _make_facade()
        mock_gw = MagicMock()
        mock_gw.wait_for_result = AsyncMock(return_value={"success": True})
        mock_bus = MagicMock()
        mock_bus.publish.return_value = True
        with (
            patch(
                "app.application.facades.shipment_event_primary.get_command_gateway",
                return_value=mock_gw,
            ),
            patch(
                "app.application.facades.shipment_event_primary.get_neuro_bus",
                return_value=mock_bus,
            ),
        ):
            result = await facade._dispatch_command("shipment.created", {"x": 1})
        assert result == {"success": True}

    @pytest.mark.asyncio
    async def test_dispatch_timeout(self):
        facade, _ = _make_facade()
        mock_gw = MagicMock()
        mock_gw.wait_for_result = AsyncMock(side_effect=TimeoutError())
        mock_bus = MagicMock()
        mock_bus.publish.return_value = True
        with (
            patch(
                "app.application.facades.shipment_event_primary.get_command_gateway",
                return_value=mock_gw,
            ),
            patch(
                "app.application.facades.shipment_event_primary.get_neuro_bus",
                return_value=mock_bus,
            ),
        ):
            result = await facade._dispatch_command("shipment.created", {"x": 1})
        assert result["success"] is False
        assert "超时" in result["message"]


class TestRunCmd:
    def test_run_cmd_success(self):
        facade, _ = _make_facade()
        with patch(
            "app.application.facades.shipment_event_primary.run_coroutine_on_neuro_loop",
            return_value={"success": True},
        ):
            result = facade._run_cmd(MagicMock())
        assert result == {"success": True}

    def test_run_cmd_recoverable_error_returns_failure(self):
        facade, _ = _make_facade()
        with patch(
            "app.application.facades.shipment_event_primary.run_coroutine_on_neuro_loop",
            side_effect=RuntimeError("loop down"),
        ):
            result = facade._run_cmd(MagicMock())
        assert result["success"] is False
        assert "loop down" in result["message"]
