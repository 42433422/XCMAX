# mypy: disable-error-code="func-returns-value"
"""Tests for app.neuro_bus.domains.finance_domain_handlers.

Covers:
* ``_publish_event`` success + recoverable error paths
* ``_resolve_approval_service`` module-level + lazy import
* ``_resolve_purchase_service_cls`` module-level + lazy import
* ``handle_approval_requested``:
  - happy path → publishes approval_created
  - exception during create_approval_request → publishes approval_failed
  - amount > 1000 sets risk="medium", else risk="low"
* ``handle_approval_completed``:
  - approved decision → publishes approval_archived
  - rejected decision → publishes approval_archived
  - unknown decision → publishes approval_completion_failed
  - import failure → publishes approval_completion_failed
  - exception → publishes approval_completion_failed
  - business failure → publishes approval_completion_failed
* ``FinanceServiceDomainHandlers.register``
* ``get_finance_handlers`` singleton
* ``register_finance_domain_handlers``
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest

from app.neuro_bus.domains import finance_domain_handlers as fdh
from app.neuro_bus.domains.finance_domain_handlers import (
    FinanceServiceDomainHandlers,
    _publish_event,
    _resolve_approval_service,
    _resolve_purchase_service_cls,
    get_finance_handlers,
    handle_approval_completed,
    handle_approval_requested,
    register_finance_domain_handlers,
)
from app.neuro_bus.events.base import NeuroEvent


@pytest.fixture(autouse=True)
def _reset_handlers_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fdh, "_handlers", None)
    monkeypatch.setattr(fdh, "PurchaseService", None)
    monkeypatch.setattr(fdh, "get_approval_service", None)


def _make_approval_event(payload: dict | None = None) -> NeuroEvent:
    return NeuroEvent(
        event_type="finance.approval_requested",
        payload=payload
        or {
            "business_type": "purchase_inbound",
            "business_id": 100,
            "amount": 500.0,
            "applicant_id": 7,
            "inbound_no": "IN-100",
            "supplier_id": 10,
        },
        source="test",
    )


def _make_completion_event(payload: dict | None = None) -> NeuroEvent:
    return NeuroEvent(
        event_type="finance.approval_completed",
        payload=payload
        or {
            "approval_id": "appr-1",
            "business_type": "purchase_inbound",
            "business_id": 100,
            "decision": "approved",
            "approver_id": 5,
            "comment": "ok",
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
        monkeypatch.setattr("app.neuro_bus.bus.get_neuro_bus", lambda: bus)

        event_id = _publish_event("finance.test", {"k": "v"}, source="UnitTest")

        assert event_id
        assert captured[0].event_type == "finance.test"
        assert captured[0].payload.get("source") == "UnitTest"

    def test_returns_empty_string_on_recoverable_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _raise() -> MagicMock:
            raise OSError("bus down")

        monkeypatch.setattr("app.neuro_bus.bus.get_neuro_bus", _raise)

        assert _publish_event("finance.test", {"k": "v"}) == ""


# ---------------------------------------------------------------------------
# _resolve_approval_service
# ---------------------------------------------------------------------------


class TestResolveApprovalService:
    def test_returns_module_level_when_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        sentinel = MagicMock()
        monkeypatch.setattr(fdh, "get_approval_service", sentinel)

        assert _resolve_approval_service() is sentinel

    def test_lazy_imports_when_module_level_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(fdh, "get_approval_service", None)
        lazy_fn = MagicMock()
        fake_module = MagicMock()
        fake_module.get_approval_service = lazy_fn
        monkeypatch.setitem(
            sys.modules,
            "app.application.workflow.approval_service",
            fake_module,
        )

        result = _resolve_approval_service()

        assert result is lazy_fn


# ---------------------------------------------------------------------------
# _resolve_purchase_service_cls
# ---------------------------------------------------------------------------


class TestResolvePurchaseService:
    def test_returns_module_level_when_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        sentinel = MagicMock()
        monkeypatch.setattr(fdh, "PurchaseService", sentinel)

        assert _resolve_purchase_service_cls() is sentinel

    def test_lazy_imports_when_module_level_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(fdh, "PurchaseService", None)
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
# handle_approval_requested
# ---------------------------------------------------------------------------


class TestHandleApprovalRequested:
    @pytest.mark.asyncio
    async def test_happy_path_publishes_approval_created(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        request = MagicMock()
        request.request_id = "appr-1"
        request.status.value = "pending"

        svc = MagicMock()
        svc.create_approval_request.return_value = request
        factory = MagicMock(return_value=svc)
        monkeypatch.setattr(fdh, "get_approval_service", factory)

        published: list[tuple[str, dict]] = []
        monkeypatch.setattr(
            fdh,
            "_publish_event",
            lambda event_type, payload, **kw: published.append((event_type, payload)) or "evt-id",
        )

        result = await handle_approval_requested(_make_approval_event())

        assert result["success"] is True
        assert result["approval_id"] == "appr-1"
        assert result["approval_event_id"] == "evt-id"
        assert published[0][0] == "finance.approval_created"
        assert published[0][1]["approval_id"] == "appr-1"
        assert published[0][1]["business_type"] == "purchase_inbound"
        assert published[0][1]["amount"] == 500.0

    @pytest.mark.asyncio
    async def test_high_amount_sets_medium_risk(self, monkeypatch: pytest.MonkeyPatch) -> None:
        request = MagicMock()
        request.request_id = "appr-2"
        request.status.value = "pending"

        svc = MagicMock()
        svc.create_approval_request.return_value = request
        factory = MagicMock(return_value=svc)
        monkeypatch.setattr(fdh, "get_approval_service", factory)

        captured_nodes: list = []

        def _capture_create(plan_id, node):
            captured_nodes.append(node)
            return request

        svc.create_approval_request.side_effect = _capture_create

        monkeypatch.setattr(
            fdh,
            "_publish_event",
            lambda event_type, payload, **kw: "evt-id",
        )

        event = _make_approval_event({"amount": 5000.0, "business_id": 1})
        await handle_approval_requested(event)

        # Verify the node was created with risk="medium" for amount > 1000
        assert captured_nodes[0].risk == "medium"

    @pytest.mark.asyncio
    async def test_low_amount_sets_low_risk(self, monkeypatch: pytest.MonkeyPatch) -> None:
        request = MagicMock()
        request.request_id = "appr-3"
        request.status.value = "pending"

        svc = MagicMock()
        svc.create_approval_request.return_value = request
        factory = MagicMock(return_value=svc)
        monkeypatch.setattr(fdh, "get_approval_service", factory)

        captured_nodes: list = []
        svc.create_approval_request.side_effect = lambda pid, node: (
            captured_nodes.append(node) or request
        )

        monkeypatch.setattr(
            fdh,
            "_publish_event",
            lambda event_type, payload, **kw: "evt-id",
        )

        event = _make_approval_event({"amount": 100.0, "business_id": 2})
        await handle_approval_requested(event)

        assert captured_nodes[0].risk == "low"

    @pytest.mark.asyncio
    async def test_exception_publishes_approval_failed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        factory = MagicMock(side_effect=OSError("svc down"))
        monkeypatch.setattr(fdh, "get_approval_service", factory)

        published: list[tuple[str, dict]] = []
        monkeypatch.setattr(
            fdh,
            "_publish_event",
            lambda event_type, payload, **kw: published.append((event_type, payload)) or "evt-id",
        )

        result = await handle_approval_requested(_make_approval_event())

        assert result["success"] is False
        assert result["stage"] == "create_approval_request"
        assert "svc down" in result["error"]
        assert published[0][0] == "finance.approval_failed"

    @pytest.mark.asyncio
    async def test_handles_none_payload(self, monkeypatch: pytest.MonkeyPatch) -> None:
        request = MagicMock()
        request.request_id = "appr-x"
        request.status = None

        svc = MagicMock()
        svc.create_approval_request.return_value = request
        factory = MagicMock(return_value=svc)
        monkeypatch.setattr(fdh, "get_approval_service", factory)

        monkeypatch.setattr(
            fdh,
            "_publish_event",
            lambda event_type, payload, **kw: "evt-id",
        )

        event = MagicMock()
        event.event_type = "finance.approval_requested"
        event.payload = None
        result = await handle_approval_requested(event)

        assert result["success"] is True
        # Verify business_type defaults to "general"
        _args, kwargs = svc.create_approval_request.call_args
        node = _args[1]
        assert node.tool_id == "general"


# ---------------------------------------------------------------------------
# handle_approval_completed
# ---------------------------------------------------------------------------


class TestHandleApprovalCompleted:
    @pytest.mark.asyncio
    async def test_approved_decision_publishes_archived(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        svc_instance = MagicMock()
        svc_instance.update_inbound_approval_status.return_value = {
            "success": True,
            "status": "approved",
        }
        svc_cls = MagicMock(return_value=svc_instance)
        monkeypatch.setattr(fdh, "PurchaseService", svc_cls)

        published: list[tuple[str, dict]] = []
        monkeypatch.setattr(
            fdh,
            "_publish_event",
            lambda event_type, payload, **kw: published.append((event_type, payload)) or "evt-id",
        )

        result = await handle_approval_completed(_make_completion_event())

        assert result["success"] is True
        assert result["decision"] == "approved"
        assert result["archived_event_id"] == "evt-id"
        assert published[0][0] == "finance.approval_archived"
        assert published[0][1]["decision"] == "approved"

    @pytest.mark.asyncio
    async def test_rejected_decision_publishes_archived(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        svc_instance = MagicMock()
        svc_instance.update_inbound_approval_status.return_value = {
            "success": True,
            "status": "rejected",
        }
        svc_cls = MagicMock(return_value=svc_instance)
        monkeypatch.setattr(fdh, "PurchaseService", svc_cls)

        monkeypatch.setattr(
            fdh,
            "_publish_event",
            lambda event_type, payload, **kw: "evt-id",
        )

        event = _make_completion_event({"decision": "rejected"})
        result = await handle_approval_completed(event)

        assert result["success"] is True
        assert result["decision"] == "rejected"

    @pytest.mark.asyncio
    async def test_unknown_decision_publishes_failed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        published: list[tuple[str, dict]] = []
        monkeypatch.setattr(
            fdh,
            "_publish_event",
            lambda event_type, payload, **kw: published.append((event_type, payload)) or "evt-id",
        )

        event = _make_completion_event({"decision": "maybe"})
        result = await handle_approval_completed(event)

        assert result["success"] is False
        assert "unknown decision" in result["error"]
        assert published[0][0] == "finance.approval_completion_failed"
        assert published[0][1]["stage"] == "validate_decision"

    @pytest.mark.asyncio
    async def test_import_failure_publishes_failed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(fdh, "PurchaseService", None)
        monkeypatch.setattr(
            fdh,
            "_resolve_purchase_service_cls",
            MagicMock(side_effect=ImportError("missing module")),
        )

        published: list[tuple[str, dict]] = []
        monkeypatch.setattr(
            fdh,
            "_publish_event",
            lambda event_type, payload, **kw: published.append((event_type, payload)) or "evt-id",
        )

        result = await handle_approval_completed(_make_completion_event())

        assert result["success"] is False
        assert result["stage"] == "import"
        assert published[0][0] == "finance.approval_completion_failed"

    @pytest.mark.asyncio
    async def test_exception_during_update_publishes_failed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        svc_instance = MagicMock()
        svc_instance.update_inbound_approval_status.side_effect = RuntimeError("db down")
        svc_cls = MagicMock(return_value=svc_instance)
        monkeypatch.setattr(fdh, "PurchaseService", svc_cls)

        published: list[tuple[str, dict]] = []
        monkeypatch.setattr(
            fdh,
            "_publish_event",
            lambda event_type, payload, **kw: published.append((event_type, payload)) or "evt-id",
        )

        result = await handle_approval_completed(_make_completion_event())

        assert result["success"] is False
        assert result["stage"] == "update_inbound"
        assert result["error"] == "db down"

    @pytest.mark.asyncio
    async def test_business_failure_publishes_failed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        svc_instance = MagicMock()
        svc_instance.update_inbound_approval_status.return_value = {
            "success": False,
            "message": "inbound not found",
        }
        svc_cls = MagicMock(return_value=svc_instance)
        monkeypatch.setattr(fdh, "PurchaseService", svc_cls)

        published: list[tuple[str, dict]] = []
        monkeypatch.setattr(
            fdh,
            "_publish_event",
            lambda event_type, payload, **kw: published.append((event_type, payload)) or "evt-id",
        )

        result = await handle_approval_completed(_make_completion_event())

        assert result["success"] is False
        assert result["stage"] == "business"
        assert result["error"] == "inbound not found"

    @pytest.mark.asyncio
    async def test_business_failure_with_no_message_uses_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        svc_instance = MagicMock()
        svc_instance.update_inbound_approval_status.return_value = {"success": False}
        svc_cls = MagicMock(return_value=svc_instance)
        monkeypatch.setattr(fdh, "PurchaseService", svc_cls)

        monkeypatch.setattr(
            fdh,
            "_publish_event",
            lambda event_type, payload, **kw: "evt-id",
        )

        result = await handle_approval_completed(_make_completion_event())

        assert result["success"] is False
        assert "returned failure" in result["error"]

    @pytest.mark.asyncio
    async def test_handles_none_payload(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            fdh,
            "_publish_event",
            lambda event_type, payload, **kw: "evt-id",
        )

        event = MagicMock()
        event.event_type = "finance.approval_completed"
        event.payload = None
        result = await handle_approval_completed(event)

        # None payload → decision="" → unknown decision path
        assert result["success"] is False
        assert "unknown decision" in result["error"]


# ---------------------------------------------------------------------------
# FinanceServiceDomainHandlers
# ---------------------------------------------------------------------------


class TestFinanceServiceDomainHandlersRegister:
    def test_register_subscribes_handlers(self, monkeypatch: pytest.MonkeyPatch) -> None:
        bus = MagicMock()
        bus._handlers = {
            "finance.approval_requested": [handle_approval_requested],
            "finance.approval_completed": [handle_approval_completed],
        }
        monkeypatch.setattr(
            "app.neuro_bus.domains.finance_domain_handlers.get_neuro_bus", lambda: bus
        )

        handlers = FinanceServiceDomainHandlers()
        handlers.register()

        subscribed_types = [call.args[0] for call in bus.subscribe.call_args_list]
        assert "finance.approval_requested" in subscribed_types
        assert "finance.approval_completed" in subscribed_types


class TestGetFinanceHandlers:
    def test_singleton_returns_same_instance(self, monkeypatch: pytest.MonkeyPatch) -> None:
        bus = MagicMock()
        monkeypatch.setattr(
            "app.neuro_bus.domains.finance_domain_handlers.get_neuro_bus", lambda: bus
        )

        h1 = get_finance_handlers()
        h2 = get_finance_handlers()

        assert h1 is h2


class TestRegisterFinanceDomainHandlers:
    def test_registers_via_singleton(self, monkeypatch: pytest.MonkeyPatch) -> None:
        bus = MagicMock()
        monkeypatch.setattr(
            "app.neuro_bus.domains.finance_domain_handlers.get_neuro_bus", lambda: bus
        )

        register_finance_domain_handlers(bus)

        assert bus.subscribe.call_count == 2
