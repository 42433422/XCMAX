# mypy: disable-error-code="func-returns-value"
"""Tests for app.neuro_bus.domains.ocr_domain_handlers.

Covers:
* ``_publish_event`` success + recoverable error paths
* ``archive_financial_receipt`` returns success
* ``handle_ocr_completed``:
  - invoice doc_type → publishes inventory.auto_inbound_requested
  - receipt doc_type → archives financial receipt
  - unsupported doc_type → returns success=False
* ``OCRServiceDomainHandlers.register`` subscribes all handlers
* ``handle_task_submitted`` / ``handle_task_completed`` / ``handle_batch_started``
* ``get_ocr_handlers`` singleton
* ``register_ocr_domain_handlers``
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.neuro_bus.domains import ocr_domain_handlers as odh
from app.neuro_bus.domains.ocr_domain_handlers import (
    OCRServiceDomainHandlers,
    _publish_event,
    archive_financial_receipt,
    get_ocr_handlers,
    handle_ocr_completed,
    register_ocr_domain_handlers,
)
from app.neuro_bus.events.base import NeuroEvent


@pytest.fixture(autouse=True)
def _reset_handlers_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(odh, "_handlers", None)


def _make_event(payload: dict | None = None) -> NeuroEvent:
    return NeuroEvent(
        event_type="ocr.completed",
        payload=payload or {},
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
        monkeypatch.setattr(odh.neuro_bus, "get_neuro_bus", lambda: bus)

        event_id = _publish_event("ocr.test", {"k": "v"}, source="UnitTest")

        assert event_id
        assert captured[0].event_type == "ocr.test"
        assert captured[0].payload.get("source") == "UnitTest"

    def test_returns_empty_string_on_recoverable_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _raise() -> MagicMock:
            raise OSError("bus down")

        monkeypatch.setattr(odh.neuro_bus, "get_neuro_bus", _raise)

        assert _publish_event("ocr.test", {"k": "v"}) == ""


# ---------------------------------------------------------------------------
# archive_financial_receipt
# ---------------------------------------------------------------------------


class TestArchiveFinancialReceipt:
    def test_returns_success_with_none_transaction_id(self) -> None:
        result = archive_financial_receipt({"amount": 100, "counterparty": "X"})
        assert result["success"] is True
        assert result["transaction_id"] is None


# ---------------------------------------------------------------------------
# handle_ocr_completed
# ---------------------------------------------------------------------------


class TestHandleOcrCompleted:
    @pytest.mark.asyncio
    async def test_invoice_doc_type_publishes_inbound_request(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        published: list[tuple[str, dict]] = []
        monkeypatch.setattr(
            odh,
            "_publish_event",
            lambda event_type, payload, **kw: published.append((event_type, payload)) or "evt-id",
        )

        event = _make_event(
            {
                "request_id": "ocr-1",
                "doc_type": "invoice",
                "fields": {
                    "supplier_id": 10,
                    "warehouse_id": 5,
                    "items": [{"sku": "A"}],
                    "total_amount": 200.0,
                    "invoice_no": "INV-001",
                },
                "applicant_id": 7,
                "text": "raw ocr text",
            }
        )
        result = await handle_ocr_completed(event)

        assert result["success"] is True
        assert result["event_type"] == "inventory.auto_inbound_requested"
        assert published[0][0] == "inventory.auto_inbound_requested"
        assert published[0][1]["ocr_request_id"] == "ocr-1"
        assert published[0][1]["supplier_id"] == 10
        assert published[0][1]["total_amount"] == 200.0

    @pytest.mark.asyncio
    async def test_receipt_doc_type_archives(self, monkeypatch: pytest.MonkeyPatch) -> None:
        archive_calls: list[dict] = []

        def _fake_archive(payload: dict) -> dict:
            archive_calls.append(payload)
            return {"success": True, "transaction_id": "tx-1"}

        monkeypatch.setattr(odh, "archive_financial_receipt", _fake_archive)

        event = _make_event(
            {
                "request_id": "ocr-2",
                "doc_type": "receipt",
                "fields": {
                    "amount": 99.5,
                    "counterparty": "Vendor X",
                    "transaction_date": "2026-07-22",
                    "receipt_no": "R-001",
                },
                "text": "receipt text",
            }
        )
        result = await handle_ocr_completed(event)

        assert result["success"] is True
        assert result["event_type"] == "financial_receipt.archived"
        assert len(archive_calls) == 1
        assert archive_calls[0]["amount"] == 99.5
        assert archive_calls[0]["counterparty"] == "Vendor X"

    @pytest.mark.asyncio
    async def test_unsupported_doc_type_returns_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            odh,
            "_publish_event",
            lambda event_type, payload, **kw: "evt-id",
        )

        event = _make_event({"doc_type": "unknown_type"})
        result = await handle_ocr_completed(event)

        assert result["success"] is False
        assert result["event_type"] == "ocr.completed"
        assert result["doc_type"] == "unknown_type"

    @pytest.mark.asyncio
    async def test_invoice_uses_payload_total_amount_when_fields_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        published: list[tuple[str, dict]] = []
        monkeypatch.setattr(
            odh,
            "_publish_event",
            lambda event_type, payload, **kw: published.append((event_type, payload)) or "evt-id",
        )

        event = _make_event(
            {
                "doc_type": "invoice",
                "total_amount": 50.0,
                "fields": {},  # no total_amount in fields
            }
        )
        result = await handle_ocr_completed(event)

        assert result["success"] is True
        # Should fall back to payload total_amount
        assert published[0][1]["total_amount"] == 50.0

    @pytest.mark.asyncio
    async def test_invoice_uses_ocr_request_id_when_request_id_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        published: list[tuple[str, dict]] = []
        monkeypatch.setattr(
            odh,
            "_publish_event",
            lambda event_type, payload, **kw: published.append((event_type, payload)) or "evt-id",
        )

        event = _make_event(
            {
                "ocr_request_id": "ocr-alt-id",
                "doc_type": "invoice",
                "fields": {},
            }
        )
        result = await handle_ocr_completed(event)

        assert result["success"] is True
        assert published[0][1]["ocr_request_id"] == "ocr-alt-id"

    @pytest.mark.asyncio
    async def test_handles_none_payload(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            odh,
            "_publish_event",
            lambda event_type, payload, **kw: "evt-id",
        )

        event = MagicMock()
        event.event_type = "ocr.completed"
        event.payload = None
        result = await handle_ocr_completed(event)

        assert result["success"] is False  # empty doc_type → unsupported


# ---------------------------------------------------------------------------
# OCRServiceDomainHandlers
# ---------------------------------------------------------------------------


class TestOCRServiceDomainHandlersRegister:
    def test_register_subscribes_all_handlers(self, monkeypatch: pytest.MonkeyPatch) -> None:
        bus = MagicMock()
        monkeypatch.setattr(odh.neuro_bus, "get_neuro_bus", lambda: bus)

        handlers = OCRServiceDomainHandlers()
        handlers.register()

        subscribed_types = [call.args[0] for call in bus.subscribe.call_args_list]
        assert "ocr.task_submitted" in subscribed_types
        assert "ocr.task_completed" in subscribed_types
        assert "ocr.completed" in subscribed_types
        assert "ocr.batch_started" in subscribed_types


class TestOCRHandlers:
    @pytest.mark.asyncio
    async def test_handle_task_submitted_returns_success(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bus = MagicMock()
        monkeypatch.setattr(odh.neuro_bus, "get_neuro_bus", lambda: bus)
        handlers = OCRServiceDomainHandlers()
        event = NeuroEvent(
            event_type="ocr.task_submitted",
            payload={"task_id": "T1"},
            source="test",
        )
        result = await handlers.handle_task_submitted(event)
        assert result["success"] is True
        assert result["event_type"] == "ocr.task_submitted"

    @pytest.mark.asyncio
    async def test_handle_task_completed_returns_success(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bus = MagicMock()
        monkeypatch.setattr(odh.neuro_bus, "get_neuro_bus", lambda: bus)
        handlers = OCRServiceDomainHandlers()
        event = NeuroEvent(
            event_type="ocr.task_completed",
            payload={"result": "ok"},
            source="test",
        )
        result = await handlers.handle_task_completed(event)
        assert result["success"] is True
        assert result["event_type"] == "ocr.task_completed"

    @pytest.mark.asyncio
    async def test_handle_batch_started_returns_success(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bus = MagicMock()
        monkeypatch.setattr(odh.neuro_bus, "get_neuro_bus", lambda: bus)
        handlers = OCRServiceDomainHandlers()
        event = NeuroEvent(
            event_type="ocr.batch_started",
            payload={"batch_id": "B1"},
            source="test",
        )
        result = await handlers.handle_batch_started(event)
        assert result["success"] is True
        assert result["event_type"] == "ocr.batch_started"


class TestGetOCRHandlers:
    def test_singleton_returns_same_instance(self, monkeypatch: pytest.MonkeyPatch) -> None:
        bus = MagicMock()
        monkeypatch.setattr(odh.neuro_bus, "get_neuro_bus", lambda: bus)

        h1 = get_ocr_handlers()
        h2 = get_ocr_handlers()

        assert h1 is h2


class TestRegisterOCRDomainHandlers:
    def test_registers_via_singleton(self, monkeypatch: pytest.MonkeyPatch) -> None:
        bus = MagicMock()
        monkeypatch.setattr(odh.neuro_bus, "get_neuro_bus", lambda: bus)

        register_ocr_domain_handlers(bus)

        assert bus.subscribe.call_count == 4
