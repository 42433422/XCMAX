"""Finance/report/AI handlers must enter the startup registration chain."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.neuro_bus.register_all_domains_complete import register_domain_handlers_only


@pytest.mark.asyncio
async def test_register_domain_handlers_calls_finance_report_and_ai():
    mock_bus = MagicMock()
    finance = MagicMock()
    report = MagicMock()
    ai_domain = MagicMock()

    with (
        patch(
            "app.neuro_bus.domains.finance_domain_handlers.register_finance_domain_handlers",
            finance,
        ),
        patch(
            "app.neuro_bus.domains.report_domain_handlers.register_report_domain_handlers",
            report,
        ),
        patch(
            "app.neuro_bus.domains.ai_service_domain.get_ai_service_domain",
            return_value=ai_domain,
        ) as get_ai,
        patch(
            "app.neuro_bus.domains.product_domain_handlers.register_product_domain_handlers",
            MagicMock(),
        ),
        patch(
            "app.neuro_bus.domains.shipment_domain_handlers.register_shipment_domain_handlers",
            MagicMock(),
        ),
        patch(
            "app.neuro_bus.domains.application_event_consumers.register_application_event_consumers",
            MagicMock(),
        ),
    ):
        await register_domain_handlers_only(mock_bus)

    finance.assert_called_once_with(mock_bus)
    report.assert_called_once_with(mock_bus)
    get_ai.assert_called_once()
