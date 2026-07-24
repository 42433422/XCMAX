"""Production intent path should invoke ConsciousProcessor when handlers exist."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.domain.neuro.processors.coordinator import ProcessorType
from app.neuro_bus.integrations.intent_integration import NeuroIntentRecognizer


def test_conscious_processor_path_used_when_handler_registered():
    recognizer = NeuroIntentRecognizer(base_recognizer=MagicMock())
    fake_processor = MagicMock()
    fake_processor._handlers = {"intent.process": MagicMock()}
    fake_processor.process = MagicMock()

    report = SimpleNamespace(
        success=True,
        data={"intent": "query_order", "confidence": 0.91, "entities": {"k": "v"}},
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
            "查一下订单",
            "u1",
            None,
            {},
            0.0,
            ProcessorType.CONSCIOUS,
        )

    assert result.source == "conscious_processor"
    assert result.intent == "query_order"
    recognizer._base.recognize.assert_not_called()


def test_conscious_processor_fallback_to_unified():
    from app.services.unified_intent_recognizer import RecognizerResult

    base = MagicMock()
    base.recognize.return_value = RecognizerResult(
        primary_intent="fallback_intent",
        tool_key="",
        intent_hints=[],
        is_negated=False,
        is_greeting=False,
        is_goodbye=False,
        is_help=False,
        is_confirmation=False,
        is_negation_intent=False,
        is_likely_unclear=False,
        all_matched_tools=[],
        slots={},
        confidence=0.7,
        sources_used=["rule"],
        raw_results={},
    )
    recognizer = NeuroIntentRecognizer(base_recognizer=base)

    with (
        patch(
            "app.domain.neuro.processors.conscious.get_conscious_processor",
            side_effect=RuntimeError("no processor"),
        ),
        patch(
            "app.neuro_bus.integrations.intent_integration.get_intent_domain",
        ) as mock_domain,
    ):
        mock_domain.return_value.emit_intent_recognized = MagicMock()
        result = recognizer._build_conscious_result(
            "你好",
            "u1",
            None,
            {},
            0.0,
            ProcessorType.CONSCIOUS,
        )

    assert result.source == "unified"
    assert result.intent == "fallback_intent"
    base.recognize.assert_called_once()
