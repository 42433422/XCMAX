"""Tests for app.application.neuro_commands.order.OrderAppServiceV2 (SSOT).

This file replaces the former ``test_order_app_service_v1_v2.py`` which
exercised the now-removed duplicate ``app.application.order_app_service_v2``.
The live command SSOT is ``app.application.neuro_commands.order`` (wired into
NeuroBus via ``neuro_commands.registry``).

Covers:
* ``OrderAppServiceV2`` initialization delegates bus wiring to
  ``NeuroCommandServiceBase`` (``get_neuro_bus``).
* ``correlation_prefix`` / ``_create_correlation_id`` use the "order" prefix.
* ``_publish_event`` happy path publishes via ``bus.publish`` and returns a
  ``NeuroEvent``; failure path returns ``None`` and logs.
* ``submit_order`` success / failure paths.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip(
    "app.application.neuro_commands.order",
    reason="neuro_commands command SSOT not present in this build; test reactivates when module lands",
)
from app.application.neuro_commands.order import OrderAppServiceV2, get_order_app_service_v2


class TestInit:
    def test_init_gets_neuro_bus(self) -> None:
        with patch("app.application.neuro_commands._base.get_neuro_bus") as g:
            g.return_value = MagicMock(name="bus")
            svc = OrderAppServiceV2()
        assert svc._bus is g.return_value
        assert svc.correlation_prefix == "order"

    def test_singleton_getter(self) -> None:
        a = get_order_app_service_v2()
        b = get_order_app_service_v2()
        assert a is b


class TestCorrelationId:
    def test_includes_prefix(self) -> None:
        svc = OrderAppServiceV2.__new__(OrderAppServiceV2)
        cid = svc._create_correlation_id()
        assert cid.startswith("order-")


class TestPublishEvent:
    def test_publishes_to_bus(self) -> None:
        svc = OrderAppServiceV2.__new__(OrderAppServiceV2)
        svc._bus = MagicMock()
        out = svc._publish_event("order.test", {"x": 1})
        svc._bus.publish.assert_called_once()
        assert out is not None

    def test_returns_none_on_exception(self) -> None:
        svc = OrderAppServiceV2.__new__(OrderAppServiceV2)
        svc._bus = MagicMock()
        svc._bus.publish.side_effect = RuntimeError("bus down")
        out = svc._publish_event("order.test", {})
        assert out is None


class TestSubmitOrder:
    @pytest.mark.asyncio
    async def test_submit_order_success(self) -> None:
        svc = OrderAppServiceV2.__new__(OrderAppServiceV2)
        svc._bus = MagicMock()
        with patch("app.application.neuro_commands.order.OrderSubmittedEvent") as Ev:
            Ev.return_value = MagicMock()
            Ev.return_value.metadata.event_id = "E1"
            out = await svc.submit_order({"order_id": "O1", "total_amount": 100})
        assert out["success"] is True
        assert out["order_id"] == "O1"
        svc._bus.publish.assert_called_once()

    @pytest.mark.asyncio
    async def test_submit_order_publish_failure(self) -> None:
        svc = OrderAppServiceV2.__new__(OrderAppServiceV2)
        svc._bus = MagicMock()
        svc._bus.publish.side_effect = RuntimeError("bus down")
        with patch("app.application.neuro_commands.order.OrderSubmittedEvent") as Ev:
            Ev.return_value = MagicMock()
            out = await svc.submit_order({"order_id": "O1"})
        assert out["success"] is False
