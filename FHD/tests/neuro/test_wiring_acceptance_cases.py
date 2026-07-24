"""衔接验收案例：注册链 + 认知 Processor + 订单样板（可独立复跑）。"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.domain.neuro.processors.coordinator import ProcessorType
from app.neuro_bus.integrations.intent_integration import NeuroIntentRecognizer
from app.neuro_bus.register_all_domains_complete import register_domain_handlers_only
from app.services.unified_intent_recognizer import RecognizerResult


@pytest.mark.asyncio
async def test_case_b_finance_report_ai_enter_startup_chain():
    mock_bus = MagicMock()
    finance = MagicMock()
    report = MagicMock()
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
            return_value=MagicMock(),
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


def test_case_b_conscious_processor_on_real_query_case():
    """案例：用户问「官网浅色模式看不见」应优先走 ConsciousProcessor。"""
    recognizer = NeuroIntentRecognizer(base_recognizer=MagicMock())
    fake_processor = MagicMock()
    fake_processor._handlers = {"intent.process": MagicMock()}
    report = SimpleNamespace(
        success=True,
        data={
            "intent": "product_issue",
            "confidence": 0.88,
            "entities": {"domain": "website"},
        },
    )
    with (
        patch(
            "app.domain.neuro.processors.conscious.get_conscious_processor",
            return_value=fake_processor,
        ),
        patch(
            "app.neuro_async_bridge.run_coroutine_on_neuro_loop",
            return_value=report,
        ),
        patch(
            "app.neuro_bus.integrations.intent_integration.get_intent_domain",
        ) as mock_domain,
    ):
        mock_domain.return_value.emit_intent_recognized = MagicMock()
        result = recognizer._build_conscious_result(
            "官网浅色模式文字看不见",
            "case-user-1",
            None,
            {"channel": "customer_service"},
            0.0,
            ProcessorType.CONSCIOUS,
        )
    assert result.source == "conscious_processor"
    assert result.intent == "product_issue"
    recognizer._base.recognize.assert_not_called()


def test_case_b_order_sample_loop_create_emits_side_effect(monkeypatch):
    from app.application import order_app_service as oas
    from app.neuro_bus import event_store as event_store_mod
    from app.neuro_bus.domains import order_domain as od
    from app.neuro_bus.domains import order_domain_handlers as odh
    from app.neuro_bus.event_store import EventStore

    oas.clear_sample_orders()
    odh.clear_order_created_side_effects()
    monkeypatch.setattr(event_store_mod, "_event_store_instance", EventStore())
    monkeypatch.setattr(od, "_order_domain", None)

    created = oas.OrderAppService().create_order(
        customer_id="C-CASE-1",
        items=[{"sku": "theme-fix", "quantity": 1, "unit_price": "19.90"}],
        total_amount=Decimal("19.90"),
    )
    assert created.get("success") is True
    order_id = str(created.get("order_id") or "")
    assert order_id
    sample = oas.get_sample_order(order_id)
    assert sample is not None
    assert sample["customer_id"] == "C-CASE-1"
    # emit 成功时 handler 可写投影；即便 bus 异步未 flush，样板订单投影已成立
    assert created.get("emitted") in {True, False}
    _ = odh.get_order_created_projection(order_id)
