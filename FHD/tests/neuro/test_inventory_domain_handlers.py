# mypy: disable-error-code="func-returns-value"
"""Tests for app.neuro_bus.domains.inventory_domain_handlers.

Covers:
* ``_publish_event`` success + recoverable error paths
* ``_resolve_purchase_service_cls`` lazy import + module-level override
* ``_coerce_float`` edge cases (None / str / invalid)
* ``handle_auto_inbound_requested``:
  - happy path: success → publishes inbound_created + finance.approval_requested
  - business failure: success=False → publishes inbound_failed
  - exception during create → publishes inbound_failed
  - total_amount fallback to inbound_data when result has no total_amount
* ``InventoryServiceDomainHandlers.register`` subscribes all handlers
* ``handle_stock_in`` / ``handle_stock_out`` / ``handle_transfer`` / ``handle_check_completed``
* ``get_inventory_handlers`` singleton
* ``register_inventory_domain_handlers``
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest

from app.neuro_bus.domains import inventory_domain_handlers as idh
from app.neuro_bus.domains.inventory_domain_handlers import (
    InventoryServiceDomainHandlers,
    _coerce_float,
    _publish_event,
    _resolve_purchase_service_cls,
    get_inventory_handlers,
    handle_auto_inbound_requested,
    register_inventory_domain_handlers,
)
from app.neuro_bus.events.base import NeuroEvent


@pytest.fixture(autouse=True)
def _reset_handlers_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(idh, "_handlers", None)
    monkeypatch.setattr(idh, "PurchaseService", None)
    # Reset env var that triggers UoW path in handle_stock_in
    monkeypatch.delenv("XCAGI_NEURO_UOW_ON_INVENTORY", raising=False)


def _make_event(payload: dict | None = None) -> NeuroEvent:
    return NeuroEvent(
        event_type="inventory.auto_inbound_requested",
        payload=payload
        or {
            "ocr_request_id": "ocr-1",
            "supplier_id": 10,
            "warehouse_id": 5,
            "items": [{"sku": "A", "qty": 2}],
            "total_amount": 100.0,
            "invoice_no": "INV-001",
            "order_id": 99,
            "applicant_id": 7,
        },
        source="test",
    )


# ---------------------------------------------------------------------------
# _publish_event
# ---------------------------------------------------------------------------


class TestPublishEvent:
    def test_returns_event_id_on_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        bus = MagicMock()
        captured: list[NeuroEvent] = []
        bus.publish = lambda evt: captured.append(evt)
        monkeypatch.setattr(idh.neuro_bus, "get_neuro_bus", lambda: bus)

        event_id = _publish_event("inventory.test", {"k": "v"}, source="UnitTest")

        assert event_id
        assert captured[0].event_type == "inventory.test"
        assert captured[0].payload.get("source") == "UnitTest"

    def test_returns_empty_string_on_recoverable_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _raise() -> MagicMock:
            raise OSError("bus down")

        monkeypatch.setattr(idh.neuro_bus, "get_neuro_bus", _raise)

        event_id = _publish_event("inventory.test", {"k": "v"})

        assert event_id == ""


# ---------------------------------------------------------------------------
# _resolve_purchase_service_cls
# ---------------------------------------------------------------------------


class TestResolvePurchaseService:
    def test_returns_module_level_when_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        sentinel = MagicMock()
        monkeypatch.setattr(idh, "PurchaseService", sentinel)

        assert _resolve_purchase_service_cls() is sentinel

    def test_lazy_imports_when_module_level_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(idh, "PurchaseService", None)
        lazy_cls = MagicMock()
        fake_module = MagicMock()
        fake_module.PurchaseService = lazy_cls
        monkeypatch.setitem(
            sys.modules,
            "app.services.purchase_service",
            fake_module,
        )

        assert _resolve_purchase_service_cls() is lazy_cls


# ---------------------------------------------------------------------------
# _coerce_float
# ---------------------------------------------------------------------------


class TestCoerceFloat:
    def test_int_value(self) -> None:
        assert _coerce_float(42) == 42.0

    def test_string_value(self) -> None:
        assert _coerce_float("3.14") == 3.14

    def test_none_returns_zero(self) -> None:
        assert _coerce_float(None) == 0.0

    def test_empty_string_returns_zero(self) -> None:
        assert _coerce_float("") == 0.0

    def test_invalid_string_returns_zero(self) -> None:
        assert _coerce_float("not-a-number") == 0.0

    def test_list_returns_zero(self) -> None:
        # list is not convertible to float → TypeError → 0.0
        assert _coerce_float([1, 2, 3]) == 0.0


# ---------------------------------------------------------------------------
# handle_auto_inbound_requested
# ---------------------------------------------------------------------------


class TestHandleAutoInboundRequested:
    @pytest.mark.asyncio
    async def test_happy_path_publishes_creation_and_finance_approval(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        svc_instance = MagicMock()
        svc_instance.create_purchase_inbound.return_value = {
            "success": True,
            "data": {
                "id": 100,
                "inbound_no": "IN-100",
                "total_amount": 200.0,
            },
        }
        svc_cls = MagicMock(return_value=svc_instance)
        monkeypatch.setattr(idh, "PurchaseService", svc_cls)

        published: list[tuple[str, dict]] = []
        monkeypatch.setattr(
            idh,
            "_publish_event",
            lambda event_type, payload, **kw: published.append((event_type, payload)) or "evt-id",
        )

        result = await handle_auto_inbound_requested(_make_event())

        assert result["success"] is True
        assert result["inbound_id"] == 100
        assert result["inbound_no"] == "IN-100"
        # Verify both events were published
        event_types = [e[0] for e in published]
        assert "finance.approval_requested" in event_types
        assert "inventory.inbound_created" in event_types
        # Check finance payload
        fin_payload = next(p for et, p in published if et == "finance.approval_requested")
        assert fin_payload["business_type"] == "purchase_inbound"
        assert fin_payload["business_id"] == 100
        assert fin_payload["amount"] == 200.0
        # Check inbound_created payload
        inb_payload = next(p for et, p in published if et == "inventory.inbound_created")
        assert inb_payload["inbound_id"] == 100
        assert inb_payload["inbound_no"] == "IN-100"

    @pytest.mark.asyncio
    async def test_business_failure_publishes_inbound_failed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        svc_instance = MagicMock()
        svc_instance.create_purchase_inbound.return_value = {
            "success": False,
            "message": "supplier not found",
        }
        svc_cls = MagicMock(return_value=svc_instance)
        monkeypatch.setattr(idh, "PurchaseService", svc_cls)

        published: list[tuple[str, dict]] = []
        monkeypatch.setattr(
            idh,
            "_publish_event",
            lambda event_type, payload, **kw: published.append((event_type, payload)) or "evt-id",
        )

        result = await handle_auto_inbound_requested(_make_event())

        assert result["success"] is False
        assert result["error"] == "supplier not found"
        assert result["stage"] == "create_purchase_inbound"
        assert published[0][0] == "inventory.inbound_failed"
        assert published[0][1]["error"] == "supplier not found"

    @pytest.mark.asyncio
    async def test_business_failure_with_no_message_uses_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        svc_instance = MagicMock()
        svc_instance.create_purchase_inbound.return_value = {"success": False}
        svc_cls = MagicMock(return_value=svc_instance)
        monkeypatch.setattr(idh, "PurchaseService", svc_cls)

        published: list[tuple[str, dict]] = []
        monkeypatch.setattr(
            idh,
            "_publish_event",
            lambda event_type, payload, **kw: published.append((event_type, payload)) or "evt-id",
        )

        result = await handle_auto_inbound_requested(_make_event())

        assert result["success"] is False
        assert result["error"] == "create_purchase_inbound failed"

    @pytest.mark.asyncio
    async def test_exception_during_create_publishes_failed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        svc_instance = MagicMock()
        svc_instance.create_purchase_inbound.side_effect = RuntimeError("db down")
        svc_cls = MagicMock(return_value=svc_instance)
        monkeypatch.setattr(idh, "PurchaseService", svc_cls)

        published: list[tuple[str, dict]] = []
        monkeypatch.setattr(
            idh,
            "_publish_event",
            lambda event_type, payload, **kw: published.append((event_type, payload)) or "evt-id",
        )

        result = await handle_auto_inbound_requested(_make_event())

        assert result["success"] is False
        assert result["error"] == "db down"
        assert result["stage"] == "create_purchase_inbound"
        assert published[0][0] == "inventory.inbound_failed"

    @pytest.mark.asyncio
    async def test_total_amount_falls_back_to_inbound_data(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        svc_instance = MagicMock()
        svc_instance.create_purchase_inbound.return_value = {
            "success": True,
            "data": {"id": 5, "inbound_no": "IN-5"},  # no total_amount in result
        }
        svc_cls = MagicMock(return_value=svc_instance)
        monkeypatch.setattr(idh, "PurchaseService", svc_cls)

        published: list[tuple[str, dict]] = []
        monkeypatch.setattr(
            idh,
            "_publish_event",
            lambda event_type, payload, **kw: published.append((event_type, payload)) or "evt-id",
        )

        event = _make_event({"total_amount": 99.5, "items": [], "applicant_id": 1})
        result = await handle_auto_inbound_requested(event)

        assert result["success"] is True
        # Verify the fallback total_amount was used in finance event
        fin_payload = next(p for et, p in published if et == "finance.approval_requested")
        assert fin_payload["amount"] == 99.5

    @pytest.mark.asyncio
    async def test_handles_none_payload(self, monkeypatch: pytest.MonkeyPatch) -> None:
        svc_instance = MagicMock()
        svc_instance.create_purchase_inbound.return_value = {"success": True, "data": {}}
        svc_cls = MagicMock(return_value=svc_instance)
        monkeypatch.setattr(idh, "PurchaseService", svc_cls)

        monkeypatch.setattr(
            idh,
            "_publish_event",
            lambda event_type, payload, **kw: "evt-id",
        )

        event = MagicMock()
        event.event_type = "inventory.auto_inbound_requested"
        event.payload = None
        result = await handle_auto_inbound_requested(event)

        assert result["success"] is True


# ---------------------------------------------------------------------------
# InventoryServiceDomainHandlers.register + handle_* methods
# ---------------------------------------------------------------------------


class TestInventoryServiceDomainHandlersRegister:
    def test_register_subscribes_all_handlers(self, monkeypatch: pytest.MonkeyPatch) -> None:
        bus = MagicMock()
        monkeypatch.setattr(idh.neuro_bus, "get_neuro_bus", lambda: bus)

        handlers = InventoryServiceDomainHandlers()
        handlers.register()

        # Verify all 5 subscriptions
        subscribed_types = [call.args[0] for call in bus.subscribe.call_args_list]
        assert "inventory.stock_in" in subscribed_types
        assert "inventory.stock_out" in subscribed_types
        assert "inventory.transfer" in subscribed_types
        assert "inventory.auto_inbound_requested" in subscribed_types
        assert "inventory.check_completed" in subscribed_types


class TestInventoryHandlers:
    @pytest.mark.asyncio
    async def test_handle_stock_in_returns_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        bus = MagicMock()
        monkeypatch.setattr(idh.neuro_bus, "get_neuro_bus", lambda: bus)
        handlers = InventoryServiceDomainHandlers()
        event = NeuroEvent(
            event_type="inventory.stock_in",
            payload={"product_id": "P1"},
            source="test",
        )
        result = await handlers.handle_stock_in(event)
        assert result["success"] is True
        assert result["event_type"] == "inventory.stock_in"

    @pytest.mark.asyncio
    async def test_handle_stock_out_returns_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        bus = MagicMock()
        monkeypatch.setattr(idh.neuro_bus, "get_neuro_bus", lambda: bus)
        handlers = InventoryServiceDomainHandlers()
        event = NeuroEvent(
            event_type="inventory.stock_out",
            payload={"quantity": 5},
            source="test",
        )
        result = await handlers.handle_stock_out(event)
        assert result["success"] is True
        assert result["event_type"] == "inventory.stock_out"

    @pytest.mark.asyncio
    async def test_handle_transfer_returns_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        bus = MagicMock()
        monkeypatch.setattr(idh.neuro_bus, "get_neuro_bus", lambda: bus)
        handlers = InventoryServiceDomainHandlers()
        event = NeuroEvent(
            event_type="inventory.transfer",
            payload={"from_location": "W1", "to_location": "W2"},
            source="test",
        )
        result = await handlers.handle_transfer(event)
        assert result["success"] is True
        assert result["event_type"] == "inventory.transfer"

    @pytest.mark.asyncio
    async def test_handle_check_completed_returns_success(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bus = MagicMock()
        monkeypatch.setattr(idh.neuro_bus, "get_neuro_bus", lambda: bus)
        handlers = InventoryServiceDomainHandlers()
        event = NeuroEvent(
            event_type="inventory.check_completed",
            payload={"check_id": "C1"},
            source="test",
        )
        result = await handlers.handle_check_completed(event)
        assert result["success"] is True
        assert result["event_type"] == "inventory.check_completed"


class TestGetInventoryHandlers:
    def test_singleton_returns_same_instance(self, monkeypatch: pytest.MonkeyPatch) -> None:
        bus = MagicMock()
        monkeypatch.setattr(idh.neuro_bus, "get_neuro_bus", lambda: bus)

        h1 = get_inventory_handlers()
        h2 = get_inventory_handlers()

        assert h1 is h2


class TestRegisterInventoryDomainHandlers:
    def test_registers_via_singleton(self, monkeypatch: pytest.MonkeyPatch) -> None:
        bus = MagicMock()
        monkeypatch.setattr(idh.neuro_bus, "get_neuro_bus", lambda: bus)

        register_inventory_domain_handlers(bus)

        assert bus.subscribe.call_count == 5
