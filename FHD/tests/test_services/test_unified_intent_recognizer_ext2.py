"""Extended tests for ``app.services.unified_intent_recognizer`` covering low-coverage branches."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.services.unified_intent_recognizer import (
    RecognizerResult,
    RecognizerType,
    UnifiedIntentRecognizer,
    get_unified_intent_recognizer,
    reload_unified_recognizer,
)


@pytest.fixture()
def fresh_recognizer(monkeypatch: pytest.MonkeyPatch) -> UnifiedIntentRecognizer:
    """Build a recognizer with all sub-engines mocked (no real model loading)."""
    # Reset singleton
    import app.services.unified_intent_recognizer as mod

    monkeypatch.setattr(mod, "_unified_recognizer", None)
    # Patch _init_recognizers to avoid loading real engines
    monkeypatch.setattr(UnifiedIntentRecognizer, "_init_recognizers", lambda self: None)
    r = UnifiedIntentRecognizer()
    r._rule_engine = MagicMock()
    r._distilled_recognizer = None
    r._bert_recognizer = None
    r._deepseek_recognizer = None
    r._rasa_service = None
    r._hybrid_service = None
    return r


class TestRecognizerType:
    def test_recognizer_type_values(self) -> None:
        assert RecognizerType.RULE.value == "rule"
        assert RecognizerType.DISTILLED.value == "distilled"
        assert RecognizerType.BERT.value == "bert"
        assert RecognizerType.DEEPSEEK.value == "deepseek"
        assert RecognizerType.RASA.value == "rasa"
        assert RecognizerType.HYBRID.value == "hybrid"


class TestRecognizeQuickPath:
    def test_quick_recognize_hit_returns_early(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
        quick_result = {
            "primary_intent": "order",
            "tool_key": "order",
            "elapsed_ms": 10,
            "source": "quick_command",
            "slots": {"key": "value"},
            "context_inherited": True,
        }
        with patch(
            "app.services.intent_service.quick_recognize",
            return_value=quick_result,
        ):
            result = fresh_recognizer.recognize("msg", context_data={"k": "v"})
        assert isinstance(result, RecognizerResult)
        assert result.primary_intent == "order"
        assert result.confidence == 0.95
        assert "quick" in result.sources_used

    def test_quick_recognize_high_elapsed_skipped(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
        quick_result = {
            "primary_intent": "order",
            "tool_key": "order",
            "elapsed_ms": 100,
            "source": "quick_command",
        }
        with (
            patch(
                "app.services.intent_service.quick_recognize",
                return_value=quick_result,
            ),
            patch.object(
                UnifiedIntentRecognizer, "_recognize_rule", return_value=None
            ) as mock_rule,
        ):
            fresh_recognizer.recognize("msg", context_data={"k": "v"})
        mock_rule.assert_called_once()

    def test_quick_recognize_no_primary_intent_skipped(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
        quick_result = {"primary_intent": None, "elapsed_ms": 10}
        with (
            patch(
                "app.services.intent_service.quick_recognize",
                return_value=quick_result,
            ),
            patch.object(
                UnifiedIntentRecognizer, "_recognize_rule", return_value=None
            ) as mock_rule,
        ):
            fresh_recognizer.recognize("msg", context_data={"k": "v"})
        mock_rule.assert_called_once()

    def test_quick_recognize_recoverable_error(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
        with (
            patch(
                "app.services.intent_service.quick_recognize",
                side_effect=RuntimeError("quick fail"),
            ),
            patch.object(
                UnifiedIntentRecognizer, "_recognize_rule", return_value=None
            ) as mock_rule,
        ):
            fresh_recognizer.recognize("msg", context_data={"k": "v"})
        mock_rule.assert_called_once()


class TestRecognizeRulePath:
    def test_recognize_rule_success(self, fresh_recognizer: UnifiedIntentRecognizer) -> None:
        with patch(
            "app.services.intent_service.recognize_intents",
            return_value={"primary_intent": "order", "tool_key": "order"},
        ):
            result = fresh_recognizer._recognize_rule("msg")
        assert result is not None
        assert result["primary_intent"] == "order"

    def test_recognize_rule_recoverable_error(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
        with patch(
            "app.services.intent_service.recognize_intents",
            side_effect=RuntimeError("rule fail"),
        ):
            result = fresh_recognizer._recognize_rule("msg")
        assert result is None


class TestRecognizeFromContext:
    def test_pending_confirmation_with_intent(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
        ctx = {
            "pending_confirmation": {
                "intent": "confirm",
                "slots": {"k": "v"},
            }
        }
        result = fresh_recognizer._recognize_from_context("msg", ctx)
        assert result is not None
        assert result["primary_intent"] == "confirm"
        assert result["confidence"] == 0.9
        assert result["source"] == "context_pending"

    def test_pending_confirmation_with_tool_key(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
        ctx = {
            "pending_confirmation": {
                "tool_key": "tk",
                "slots": {},
            }
        }
        result = fresh_recognizer._recognize_from_context("msg", ctx)
        assert result is not None
        assert result["primary_intent"] == "tk"

    def test_pending_confirmation_no_intent(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
        ctx = {"pending_confirmation": {}}
        result = fresh_recognizer._recognize_from_context("msg", ctx)
        assert result is None

    def test_last_intent_with_slots(self, fresh_recognizer: UnifiedIntentRecognizer) -> None:
        ctx = {
            "last_intent": "order",
            "last_slots": {"k": "v"},
        }
        result = fresh_recognizer._recognize_from_context("msg", ctx)
        assert result is not None
        assert result["primary_intent"] == "order"
        assert result["confidence"] == 0.7
        assert result["source"] == "context_inherit"

    def test_current_intent_with_slots(self, fresh_recognizer: UnifiedIntentRecognizer) -> None:
        ctx = {
            "current_intent": "order",
            "last_slots": {"k": "v"},
        }
        result = fresh_recognizer._recognize_from_context("msg", ctx)
        assert result is not None
        assert result["primary_intent"] == "order"

    def test_recent_intents(self, fresh_recognizer: UnifiedIntentRecognizer) -> None:
        ctx = {"recent_intents": ["order", "chat"]}
        result = fresh_recognizer._recognize_from_context("msg", ctx)
        assert result is not None
        assert result["primary_intent"] == "order"
        assert result["confidence"] == 0.6
        assert result["source"] == "context_recent"

    def test_no_context_data_returns_none(self, fresh_recognizer: UnifiedIntentRecognizer) -> None:
        result = fresh_recognizer._recognize_from_context("msg", {})
        assert result is None

    def test_recoverable_error_returns_none(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
        # Force an attribute access error inside the try block
        ctx = MagicMock()
        ctx.get = MagicMock(side_effect=RuntimeError("ctx fail"))
        result = fresh_recognizer._recognize_from_context("msg", ctx)  # type: ignore[arg-type]
        assert result is None


class TestRecognizeDistilled:
    def test_distilled_success(self, fresh_recognizer: UnifiedIntentRecognizer) -> None:
        mock_distilled = MagicMock()
        mock_distilled.recognize.return_value = {
            "intent": "order",
            "confidence": 0.9,
        }
        fresh_recognizer._distilled_recognizer = mock_distilled
        result = fresh_recognizer._recognize_distilled("msg")
        assert result is not None
        assert result["primary_intent"] == "order"

    def test_distilled_no_recognizer(self, fresh_recognizer: UnifiedIntentRecognizer) -> None:
        fresh_recognizer._distilled_recognizer = None
        result = fresh_recognizer._recognize_distilled("msg")
        assert result is None

    def test_distilled_no_intent(self, fresh_recognizer: UnifiedIntentRecognizer) -> None:
        mock_distilled = MagicMock()
        mock_distilled.recognize.return_value = {"intent": None}
        fresh_recognizer._distilled_recognizer = mock_distilled
        result = fresh_recognizer._recognize_distilled("msg")
        assert result is None

    def test_distilled_recoverable_error(self, fresh_recognizer: UnifiedIntentRecognizer) -> None:
        mock_distilled = MagicMock()
        mock_distilled.recognize.side_effect = RuntimeError("distilled fail")
        fresh_recognizer._distilled_recognizer = mock_distilled
        result = fresh_recognizer._recognize_distilled("msg")
        assert result is None


class TestRecognizeBert:
    def test_bert_success(self, fresh_recognizer: UnifiedIntentRecognizer) -> None:
        mock_bert = MagicMock()
        mock_bert.predict.return_value = {
            "intent": "order",
            "confidence": 0.85,
        }
        fresh_recognizer._bert_recognizer = mock_bert
        result = fresh_recognizer._recognize_bert("msg")
        assert result is not None
        assert result["primary_intent"] == "order"

    def test_bert_no_recognizer(self, fresh_recognizer: UnifiedIntentRecognizer) -> None:
        fresh_recognizer._bert_recognizer = None
        result = fresh_recognizer._recognize_bert("msg")
        assert result is None

    def test_bert_no_intent(self, fresh_recognizer: UnifiedIntentRecognizer) -> None:
        mock_bert = MagicMock()
        mock_bert.predict.return_value = {"intent": None}
        fresh_recognizer._bert_recognizer = mock_bert
        result = fresh_recognizer._recognize_bert("msg")
        assert result is None

    def test_bert_recoverable_error(self, fresh_recognizer: UnifiedIntentRecognizer) -> None:
        mock_bert = MagicMock()
        mock_bert.predict.side_effect = RuntimeError("bert fail")
        fresh_recognizer._bert_recognizer = mock_bert
        result = fresh_recognizer._recognize_bert("msg")
        assert result is None


class TestRecognizeDeepseek:
    def test_deepseek_no_recognizer(self, fresh_recognizer: UnifiedIntentRecognizer) -> None:
        fresh_recognizer._deepseek_recognizer = None
        result = fresh_recognizer._recognize_deepseek("msg")
        assert result is None

    def test_deepseek_recoverable_error(self, fresh_recognizer: UnifiedIntentRecognizer) -> None:
        mock_ds = MagicMock()
        mock_ds.recognize.side_effect = RuntimeError("ds fail")
        fresh_recognizer._deepseek_recognizer = mock_ds
        result = fresh_recognizer._recognize_deepseek("msg")
        assert result is None

    def test_deepseek_no_intent(self, fresh_recognizer: UnifiedIntentRecognizer) -> None:
        mock_ds = MagicMock()

        async def fake_recognize(msg, ctx):
            return {"intent": None}

        mock_ds.recognize = fake_recognize
        fresh_recognizer._deepseek_recognizer = mock_ds
        result = fresh_recognizer._recognize_deepseek("msg")
        assert result is None


class TestMergeResults:
    def test_merge_empty_results_short_message(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
        result = fresh_recognizer._merge_results({}, "ab", None)
        assert result["primary_intent"] is None
        assert result["is_likely_unclear"] is True

    def test_merge_empty_results_long_message(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
        result = fresh_recognizer._merge_results({}, "long message", None)
        assert result["primary_intent"] is None
        assert result["is_likely_unclear"] is False

    def test_merge_rule_with_tool_key(self, fresh_recognizer: UnifiedIntentRecognizer) -> None:
        results = {"rule": {"tool_key": "order", "primary_intent": "order", "is_negated": False}}
        result = fresh_recognizer._merge_results(results, "msg", None)
        assert result["tool_key"] == "order"

    def test_merge_rule_negated_skipped(self, fresh_recognizer: UnifiedIntentRecognizer) -> None:
        results = {
            "rule": {"tool_key": "order", "is_negated": True},
            "distilled": {"primary_intent": "chat", "confidence": 0.9},
        }
        result = fresh_recognizer._merge_results(results, "msg", None)
        assert result["primary_intent"] == "chat"

    def test_merge_context_pending_high_confidence(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
        results = {"context": {"primary_intent": "order", "confidence": 0.9}}
        ctx = {"pending_confirmation": {"intent": "order"}}
        result = fresh_recognizer._merge_results(results, "msg", ctx)
        assert result["primary_intent"] == "order"

    def test_merge_context_user_preferences(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
        results = {
            "context": {
                "primary_intent": "order",
                "confidence": 0.8,
                "slots": {},
            }
        }
        ctx = {"user_preferences": {"favorite_customer": "客户A"}}
        result = fresh_recognizer._merge_results(results, "msg", ctx)
        assert result["slots"]["unit_name"] == "客户A"

    def test_merge_context_user_preferences_with_existing_unit(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
        results = {
            "context": {
                "primary_intent": "order",
                "confidence": 0.8,
                "slots": {"unit_name": "existing"},
            }
        }
        ctx = {"user_preferences": {"favorite_customer": "客户A"}}
        result = fresh_recognizer._merge_results(results, "msg", ctx)
        assert result["slots"]["unit_name"] == "existing"

    def test_merge_distilled_high_confidence(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
        results = {"distilled": {"primary_intent": "order", "confidence": 0.9}}
        result = fresh_recognizer._merge_results(results, "msg", None)
        assert result["primary_intent"] == "order"

    def test_merge_distilled_low_confidence_falls_through(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
        results = {
            "distilled": {"primary_intent": "order", "confidence": 0.3},
            "context": {"primary_intent": "ctx", "confidence": 0.5},
        }
        result = fresh_recognizer._merge_results(results, "msg", None)
        assert result["primary_intent"] == "ctx"

    def test_merge_falls_to_rule(self, fresh_recognizer: UnifiedIntentRecognizer) -> None:
        results = {"rule": {"primary_intent": "order", "confidence": 0.5}}
        result = fresh_recognizer._merge_results(results, "msg", None)
        assert result["primary_intent"] == "order"


class TestRecognizeSkipDeepseek:
    def test_skip_unified_deepseek_normal_profile(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
        ctx = {
            "tool_execution_profile": "normal",
            "ui_surface": "normal",
        }
        with (
            patch.object(UnifiedIntentRecognizer, "_recognize_rule", return_value=None),
            patch.object(UnifiedIntentRecognizer, "_recognize_deepseek") as mock_ds,
        ):
            fresh_recognizer.recognize("msg", context_data=ctx)
        mock_ds.assert_not_called()


class TestReload:
    def test_reload_calls_init(
        self,
        fresh_recognizer: UnifiedIntentRecognizer,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        called = {"init": False}

        def fake_init(self):
            called["init"] = True

        monkeypatch.setattr(UnifiedIntentRecognizer, "_init_recognizers", fake_init)
        monkeypatch.setattr(
            "app.services.unified_intent_recognizer.reload_intent_config",
            lambda: None,
        )
        monkeypatch.setattr(
            "app.services.rule_engine.reload_rule_engine",
            lambda: None,
        )
        fresh_recognizer.reload()
        assert called["init"] is True


class TestSingletonAccessors:
    def test_get_unified_intent_recognizer_returns_singleton(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import app.services.unified_intent_recognizer as mod

        monkeypatch.setattr(mod, "_unified_recognizer", None)
        monkeypatch.setattr(UnifiedIntentRecognizer, "_init_recognizers", lambda self: None)
        r1 = get_unified_intent_recognizer()
        r2 = get_unified_intent_recognizer()
        assert r1 is r2

    def test_reload_unified_recognizer(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import app.services.unified_intent_recognizer as mod

        monkeypatch.setattr(mod, "_unified_recognizer", None)
        monkeypatch.setattr(UnifiedIntentRecognizer, "_init_recognizers", lambda self: None)
        r1 = get_unified_intent_recognizer()
        # Set up reload mock
        reloaded = {"called": False}

        def fake_reload(self):
            reloaded["called"] = True

        monkeypatch.setattr(UnifiedIntentRecognizer, "reload", fake_reload)
        r2 = reload_unified_recognizer()
        assert reloaded["called"] is True
        assert r2 is r1
