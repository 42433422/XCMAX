# mypy: disable-error-code="func-returns-value"
"""Tests for app.neuro_bus.domains.report_domain_handlers.

Covers:
* ``handle_monthly_summary_requested``:
  - happy path: gen_fn returns success → publishes generated event
  - business failure: gen_fn returns success=False → publishes failed event
  - generate exception: gen_fn raises → publishes failed event
  - import failure: _resolve_generator raises RECOVERABLE_ERRORS → publishes failed event
* ``_publish_event``:
  - normal: returns event_id
  - recoverable error: returns ""
* ``_resolve_generator``:
  - returns module-level patch when set
  - lazy imports when module-level is None
* ``ReportServiceDomainHandlers.register``
* ``get_report_handlers`` singleton
* ``register_report_domain_handlers``
"""

from __future__ import annotations

import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.neuro_bus.domains import report_domain_handlers as rdh
from app.neuro_bus.domains.report_domain_handlers import (
    ReportServiceDomainHandlers,
    _publish_event,
    _resolve_generator,
    get_report_handlers,
    handle_monthly_summary_requested,
    register_report_domain_handlers,
)
from app.neuro_bus.events.base import NeuroEvent


@pytest.fixture(autouse=True)
def _reset_handlers_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reset module-level singleton between tests."""
    monkeypatch.setattr(rdh, "_handlers", None)
    # Also reset module-level generate_monthly_finance_summary placeholder so
    # each test can patch it explicitly.
    monkeypatch.setattr(rdh, "generate_monthly_finance_summary", None)


def _make_event(payload: dict | None = None) -> NeuroEvent:
    """Build a NeuroEvent with the given payload."""
    return NeuroEvent(
        event_type="report.monthly_summary_requested",
        payload=payload or {"tenant_id": "t1", "year": 2026, "month": 7},
        source="test",
    )


# ---------------------------------------------------------------------------
# _publish_event
# ---------------------------------------------------------------------------


class TestPublishEvent:
    def test_returns_event_id_on_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        bus = MagicMock()
        captured_event: list[NeuroEvent] = []
        bus.publish = lambda evt: captured_event.append(evt)
        monkeypatch.setattr("app.neuro_bus.bus.get_neuro_bus", lambda: bus)

        event_id = _publish_event("report.test", {"k": "v"}, source="UnitTest")

        assert event_id  # non-empty string
        assert captured_event[0].event_type == "report.test"
        assert captured_event[0].payload.get("k") == "v"
        assert captured_event[0].payload.get("source") == "UnitTest"

    def test_returns_empty_string_on_recoverable_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _raise() -> MagicMock:
            raise OSError("bus down")

        monkeypatch.setattr("app.neuro_bus.bus.get_neuro_bus", _raise)

        event_id = _publish_event("report.test", {"k": "v"})

        assert event_id == ""


# ---------------------------------------------------------------------------
# _resolve_generator
# ---------------------------------------------------------------------------


class TestResolveGenerator:
    def test_returns_module_level_when_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        sentinel = MagicMock()
        monkeypatch.setattr(rdh, "generate_monthly_finance_summary", sentinel)

        result = _resolve_generator()

        assert result is sentinel

    def test_lazy_imports_when_module_level_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(rdh, "generate_monthly_finance_summary", None)
        lazy_fn = MagicMock()
        # Patch the lazy import path used inside _resolve_generator
        fake_module = MagicMock()
        fake_module.generate_monthly_finance_summary = lazy_fn
        monkeypatch.setitem(
            sys.modules,
            "app.application.monthly_report_scheduler",
            fake_module,
        )

        result = _resolve_generator()

        assert result is lazy_fn


# ---------------------------------------------------------------------------
# handle_monthly_summary_requested
# ---------------------------------------------------------------------------


class TestHandleMonthlySummaryRequested:
    @pytest.mark.asyncio
    async def test_happy_path_publishes_generated_event(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        gen_fn = MagicMock(
            return_value={
                "success": True,
                "summary": {"total": 100},
                "period": {"year": 2026, "month": 7},
                "generated_at": "2026-07-22T00:00:00Z",
            }
        )
        monkeypatch.setattr(rdh, "generate_monthly_finance_summary", gen_fn)

        published: list[tuple[str, dict]] = []
        monkeypatch.setattr(
            rdh,
            "_publish_event",
            lambda event_type, payload, **kw: published.append((event_type, payload)) or "evt-id",
        )

        event = _make_event()
        result = await handle_monthly_summary_requested(event)

        assert result["success"] is True
        assert result["tenant_id"] == "t1"
        assert result["year"] == 2026
        assert result["month"] == 7
        assert result["summary"] == {"total": 100}
        assert result["generated_event_id"] == "evt-id"
        # Verify the generated event was published
        assert published[0][0] == "report.monthly_summary_generated"
        assert published[0][1]["summary"] == {"total": 100}

    @pytest.mark.asyncio
    async def test_business_failure_publishes_failed_event(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        gen_fn = MagicMock(return_value={"success": False, "error": "no data"})
        monkeypatch.setattr(rdh, "generate_monthly_finance_summary", gen_fn)

        published: list[tuple[str, dict]] = []
        monkeypatch.setattr(
            rdh,
            "_publish_event",
            lambda event_type, payload, **kw: published.append((event_type, payload)) or "evt-id",
        )

        event = _make_event()
        result = await handle_monthly_summary_requested(event)

        assert result["success"] is False
        assert result["error"] == "no data"
        assert result["stage"] == "business"
        assert published[0][0] == "report.monthly_summary_failed"
        assert published[0][1]["error"] == "no data"
        assert published[0][1]["stage"] == "business"

    @pytest.mark.asyncio
    async def test_business_failure_with_missing_error_uses_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        gen_fn = MagicMock(return_value={"success": False})  # no "error" key
        monkeypatch.setattr(rdh, "generate_monthly_finance_summary", gen_fn)

        published: list[tuple[str, dict]] = []
        monkeypatch.setattr(
            rdh,
            "_publish_event",
            lambda event_type, payload, **kw: published.append((event_type, payload)) or "evt-id",
        )

        event = _make_event()
        result = await handle_monthly_summary_requested(event)

        assert result["success"] is False
        assert "generate_monthly_finance_summary returned failure" in result["error"]

    @pytest.mark.asyncio
    async def test_generate_exception_publishes_failed_event(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        gen_fn = MagicMock(side_effect=ValueError("bad input"))
        monkeypatch.setattr(rdh, "generate_monthly_finance_summary", gen_fn)

        published: list[tuple[str, dict]] = []
        monkeypatch.setattr(
            rdh,
            "_publish_event",
            lambda event_type, payload, **kw: published.append((event_type, payload)) or "evt-id",
        )

        event = _make_event()
        result = await handle_monthly_summary_requested(event)

        assert result["success"] is False
        assert result["error"] == "bad input"
        assert result["stage"] == "generate"
        assert published[0][0] == "report.monthly_summary_failed"
        assert published[0][1]["stage"] == "generate"

    @pytest.mark.asyncio
    async def test_import_failure_publishes_failed_event(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Force _resolve_generator to raise a RECOVERABLE_ERROR (ImportError)
        monkeypatch.setattr(
            rdh,
            "_resolve_generator",
            MagicMock(side_effect=ImportError("missing module")),
        )

        published: list[tuple[str, dict]] = []
        monkeypatch.setattr(
            rdh,
            "_publish_event",
            lambda event_type, payload, **kw: published.append((event_type, payload)) or "evt-id",
        )

        event = _make_event()
        result = await handle_monthly_summary_requested(event)

        assert result["success"] is False
        assert result["stage"] == "import"
        assert "missing module" in result["error"]
        assert published[0][0] == "report.monthly_summary_failed"
        assert published[0][1]["stage"] == "import"

    @pytest.mark.asyncio
    async def test_handles_none_payload(self, monkeypatch: pytest.MonkeyPatch) -> None:
        gen_fn = MagicMock(return_value={"success": True, "summary": {}})
        monkeypatch.setattr(rdh, "generate_monthly_finance_summary", gen_fn)

        monkeypatch.setattr(
            rdh,
            "_publish_event",
            lambda event_type, payload, **kw: "evt-id",
        )

        event = MagicMock()
        event.event_type = "report.monthly_summary_requested"
        event.payload = None
        result = await handle_monthly_summary_requested(event)

        assert result["success"] is True
        # Verify gen_fn was called with None tenant/year/month
        gen_fn.assert_called_once_with(None, None, None)


# ---------------------------------------------------------------------------
# ReportServiceDomainHandlers
# ---------------------------------------------------------------------------


class TestReportServiceDomainHandlers:
    def test_register_subscribes_handler(self, monkeypatch: pytest.MonkeyPatch) -> None:
        bus = MagicMock()
        # Pre-populate _handlers to verify the count log line works
        bus._handlers = {"report.monthly_summary_requested": [handle_monthly_summary_requested]}
        monkeypatch.setattr(
            "app.neuro_bus.domains.report_domain_handlers.get_neuro_bus", lambda: bus
        )

        handlers = ReportServiceDomainHandlers()
        handlers.register()

        bus.subscribe.assert_called_once_with(
            "report.monthly_summary_requested", handle_monthly_summary_requested
        )


class TestGetReportHandlers:
    def test_singleton_returns_same_instance(self, monkeypatch: pytest.MonkeyPatch) -> None:
        bus = MagicMock()
        monkeypatch.setattr(
            "app.neuro_bus.domains.report_domain_handlers.get_neuro_bus", lambda: bus
        )

        h1 = get_report_handlers()
        h2 = get_report_handlers()

        assert h1 is h2


class TestRegisterReportDomainHandlers:
    def test_registers_via_singleton(self, monkeypatch: pytest.MonkeyPatch) -> None:
        bus = MagicMock()
        bus._handlers = {}
        monkeypatch.setattr(
            "app.neuro_bus.domains.report_domain_handlers.get_neuro_bus", lambda: bus
        )

        register_report_domain_handlers(bus)

        # Verify the subscribe was called (via singleton's register)
        assert bus.subscribe.call_count == 1
