"""Deep tests for ``app.services.unified_intent_recognizer`` covering remaining uncovered branches."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

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
    import app.services.unified_intent_recognizer as mod

    monkeypatch.setattr(mod, "_unified_recognizer", None)
    monkeypatch.setattr(UnifiedIntentRecognizer, "_init_recognizers", lambda self: None)
    r = UnifiedIntentRecognizer()
    r._rule_engine = MagicMock()
    r._distilled_recognizer = None
    r._bert_recognizer = None
    r._deepseek_recognizer = None
    r._rasa_service = None
    r._hybrid_service = None
    return r


# ── RecognizerType enum deep ─────────────────────────────────────────────────


class TestRecognizerTypeDeep:
    def test_all_values_distinct(self) -> None:
        values = [t.value for t in RecognizerType]
        assert len(values) == len(set(values))

    def test_lookup_by_value(self) -> None:
        for t in RecognizerType:
            assert RecognizerType(t.value) is t


# ── recognize() main entry deep ──────────────────────────────────────────────


class TestRecognizeMainDeep:
    def test_quick_recognize_non_quick_source_confidence(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
        # source != "quick_command" → confidence 0.85
        quick_result = {
            "primary_intent": "order",
            "tool_key": "order",
            "elapsed_ms": 10,
            "source": "context_inherit",
            "context_inherited": False,
        }
        with patch(
            "app.services.intent_service.quick_recognize",
            return_value=quick_result,
        ):
            result = fresh_recognizer.recognize("msg", context_data={"k": "v"})
        assert result.confidence == 0.85
        assert result.sources_used == ["quick"]

    def test_quick_recognize_no_tool_key(self, fresh_recognizer: UnifiedIntentRecognizer) -> None:
        quick_result = {
            "primary_intent": "order",
            "tool_key": None,
            "elapsed_ms": 10,
            "source": "quick_command",
        }
        with patch(
            "app.services.intent_service.quick_recognize",
            return_value=quick_result,
        ):
            result = fresh_recognizer.recognize("msg", context_data={"k": "v"})
        assert result.tool_key is None
        # intent_hints should be [primary_intent] since primary_intent is truthy
        assert result.intent_hints == ["order"]

    def test_quick_recognize_no_primary_intent_hints_empty(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
        quick_result = {
            "primary_intent": None,
            "tool_key": None,
            "elapsed_ms": 10,
            "source": "quick_command",
        }
        with (
            patch(
                "app.services.intent_service.quick_recognize",
                return_value=quick_result,
            ),
            patch.object(UnifiedIntentRecognizer, "_recognize_rule", return_value=None),
        ):
            result = fresh_recognizer.recognize("msg", context_data={"k": "v"})
        assert result.intent_hints == []

    def test_no_context_data_skips_context_recognition(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
        with (
            patch.object(UnifiedIntentRecognizer, "_recognize_rule", return_value=None),
            patch.object(UnifiedIntentRecognizer, "_recognize_from_context") as mock_ctx,
        ):
            fresh_recognizer.recognize("msg")
        mock_ctx.assert_not_called()

    def test_distilled_available_runs_recognition(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
        mock_distilled = MagicMock()
        mock_distilled.is_available.return_value = True
        fresh_recognizer._distilled_recognizer = mock_distilled
        with (
            patch.object(
                UnifiedIntentRecognizer, "_recognize_distilled", return_value=None
            ) as mock_dist,
            patch.object(UnifiedIntentRecognizer, "_recognize_rule", return_value=None),
        ):
            fresh_recognizer.recognize("msg")
        mock_dist.assert_called_once()

    def test_distilled_not_available_skipped(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
        mock_distilled = MagicMock()
        mock_distilled.is_available.return_value = False
        fresh_recognizer._distilled_recognizer = mock_distilled
        with (
            patch.object(UnifiedIntentRecognizer, "_recognize_distilled") as mock_dist,
            patch.object(UnifiedIntentRecognizer, "_recognize_rule", return_value=None),
        ):
            fresh_recognizer.recognize("msg")
        mock_dist.assert_not_called()

    def test_bert_recognizer_present_runs(self, fresh_recognizer: UnifiedIntentRecognizer) -> None:
        fresh_recognizer._bert_recognizer = MagicMock()
        with (
            patch.object(
                UnifiedIntentRecognizer, "_recognize_bert", return_value=None
            ) as mock_bert,
            patch.object(UnifiedIntentRecognizer, "_recognize_rule", return_value=None),
        ):
            fresh_recognizer.recognize("msg")
        mock_bert.assert_called_once()

    def test_bert_recognizer_none_skipped(self, fresh_recognizer: UnifiedIntentRecognizer) -> None:
        fresh_recognizer._bert_recognizer = None
        with (
            patch.object(UnifiedIntentRecognizer, "_recognize_bert") as mock_bert,
            patch.object(UnifiedIntentRecognizer, "_recognize_rule", return_value=None),
        ):
            fresh_recognizer.recognize("msg")
        mock_bert.assert_not_called()

    def test_deepseek_normal_profile_normal_surface_skipped(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
        fresh_recognizer._deepseek_recognizer = MagicMock()
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

    def test_deepseek_normal_profile_other_surface_runs(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
        fresh_recognizer._deepseek_recognizer = MagicMock()
        ctx = {
            "tool_execution_profile": "normal",
            "ui_surface": "advanced",
        }
        with (
            patch.object(UnifiedIntentRecognizer, "_recognize_rule", return_value=None),
            patch.object(
                UnifiedIntentRecognizer, "_recognize_deepseek", return_value=None
            ) as mock_ds,
        ):
            fresh_recognizer.recognize("msg", context_data=ctx)
        mock_ds.assert_called_once()

    def test_deepseek_advanced_profile_normal_surface_runs(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
        fresh_recognizer._deepseek_recognizer = MagicMock()
        ctx = {
            "tool_execution_profile": "advanced",
            "ui_surface": "normal",
        }
        with (
            patch.object(UnifiedIntentRecognizer, "_recognize_rule", return_value=None),
            patch.object(
                UnifiedIntentRecognizer, "_recognize_deepseek", return_value=None
            ) as mock_ds,
        ):
            fresh_recognizer.recognize("msg", context_data=ctx)
        mock_ds.assert_called_once()

    def test_deepseek_empty_profile_strings_treated_as_normal(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
        # Empty strings strip to "" which .lower() == "" != "normal"
        # So skip_unified_deepseek stays False
        fresh_recognizer._deepseek_recognizer = MagicMock()
        ctx = {
            "tool_execution_profile": "",
            "ui_surface": "",
        }
        with (
            patch.object(UnifiedIntentRecognizer, "_recognize_rule", return_value=None),
            patch.object(
                UnifiedIntentRecognizer, "_recognize_deepseek", return_value=None
            ) as mock_ds,
        ):
            fresh_recognizer.recognize("msg", context_data=ctx)
        mock_ds.assert_called_once()

    def test_context_data_not_dict_skips_deepseek_skip_logic(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
        # When context_data is not a dict, quick_recognize would raise AttributeError
        # (NOT in RECOVERABLE_ERRORS). To test the recoverable path, we make
        # quick_recognize raise a RuntimeError (which IS in RECOVERABLE_ERRORS),
        # and patch _recognize_from_context to handle the non-dict gracefully.
        fresh_recognizer._deepseek_recognizer = MagicMock()
        with (
            patch(
                "app.services.intent_service.quick_recognize",
                side_effect=RuntimeError("simulated infra failure"),
            ),
            patch.object(UnifiedIntentRecognizer, "_recognize_rule", return_value=None),
            patch.object(UnifiedIntentRecognizer, "_recognize_from_context", return_value=None),
            patch.object(
                UnifiedIntentRecognizer, "_recognize_deepseek", return_value=None
            ) as mock_ds,
        ):
            fresh_recognizer.recognize("msg", context_data={"pending_confirmation": False})
        mock_ds.assert_called_once()

    def test_recognize_returns_recognizer_result(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
        with patch.object(UnifiedIntentRecognizer, "_recognize_rule", return_value=None):
            result = fresh_recognizer.recognize("msg")
        assert isinstance(result, RecognizerResult)
        assert result.raw_results == {}

    def test_recognize_with_context_data_and_rule_result(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
        rule_result = {"primary_intent": "order", "tool_key": "order"}
        ctx_result = {"primary_intent": "ctx_intent", "confidence": 0.6}
        with (
            patch.object(UnifiedIntentRecognizer, "_recognize_rule", return_value=rule_result),
            patch.object(
                UnifiedIntentRecognizer, "_recognize_from_context", return_value=ctx_result
            ),
        ):
            result = fresh_recognizer.recognize("msg", context_data={"k": "v"})
        assert isinstance(result, RecognizerResult)
        assert "rule" in result.sources_used
        assert "context" in result.sources_used


# ── _recognize_deepseek deep ─────────────────────────────────────────────────


class TestRecognizeDeepseekDeep:
    def test_deepseek_success_with_intent(self, fresh_recognizer: UnifiedIntentRecognizer) -> None:
        mock_ds = MagicMock()

        async def fake_recognize(msg, ctx):
            return {"intent": "order", "confidence": 0.9, "slots": {"k": "v"}}

        mock_ds.recognize = fake_recognize
        fresh_recognizer._deepseek_recognizer = mock_ds
        result = fresh_recognizer._recognize_deepseek("msg", [{"role": "user", "content": "hi"}])
        assert result is not None
        assert result["primary_intent"] == "order"
        assert result["confidence"] == 0.9
        assert result["slots"] == {"k": "v"}

    def test_deepseek_success_no_slots_key(self, fresh_recognizer: UnifiedIntentRecognizer) -> None:
        mock_ds = MagicMock()

        async def fake_recognize(msg, ctx):
            return {"intent": "order", "confidence": 0.9}

        mock_ds.recognize = fake_recognize
        fresh_recognizer._deepseek_recognizer = mock_ds
        result = fresh_recognizer._recognize_deepseek("msg")
        assert result is not None
        assert result["slots"] == {}

    def test_deepseek_with_context_passed(self, fresh_recognizer: UnifiedIntentRecognizer) -> None:
        mock_ds = MagicMock()
        captured_ctx = {}

        async def fake_recognize(msg, ctx):
            captured_ctx["ctx"] = ctx
            return {"intent": "order", "confidence": 0.9}

        mock_ds.recognize = fake_recognize
        fresh_recognizer._deepseek_recognizer = mock_ds
        ctx = [{"role": "user", "content": "hi"}]
        fresh_recognizer._recognize_deepseek("msg", ctx)
        assert captured_ctx["ctx"] == ctx


# ── _merge_results deep ──────────────────────────────────────────────────────


class TestMergeResultsDeep:
    def test_rule_with_tool_key_negated_skipped_to_distilled(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
        results = {
            "rule": {"tool_key": "order", "is_negated": True, "primary_intent": "order"},
            "distilled": {"primary_intent": "chat", "confidence": 0.9},
        }
        result = fresh_recognizer._merge_results(results, "msg", None)
        assert result["primary_intent"] == "chat"

    def test_rule_no_tool_key_skipped(self, fresh_recognizer: UnifiedIntentRecognizer) -> None:
        results = {
            "rule": {"tool_key": None, "primary_intent": "order"},
            "distilled": {"primary_intent": "chat", "confidence": 0.9},
        }
        result = fresh_recognizer._merge_results(results, "msg", None)
        assert result["primary_intent"] == "chat"

    def test_context_pending_low_confidence_skipped(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
        results = {"context": {"primary_intent": "order", "confidence": 0.5}}
        ctx = {"pending_confirmation": {"intent": "order"}}
        result = fresh_recognizer._merge_results(results, "msg", ctx)
        # confidence < 0.85, falls through to distilled/bert/deepseek/hybrid
        # none present, falls to context
        assert result["primary_intent"] == "order"

    def test_context_user_prefs_low_confidence_skipped(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
        results = {"context": {"primary_intent": "order", "confidence": 0.5}}
        ctx = {"user_preferences": {"favorite_customer": "客户A"}}
        result = fresh_recognizer._merge_results(results, "msg", ctx)
        # confidence < 0.75, falls through
        assert result["primary_intent"] == "order"

    def test_context_no_user_prefs(self, fresh_recognizer: UnifiedIntentRecognizer) -> None:
        results = {"context": {"primary_intent": "order", "confidence": 0.9}}
        ctx = {}
        result = fresh_recognizer._merge_results(results, "msg", ctx)
        assert result["primary_intent"] == "order"

    def test_context_user_prefs_empty_skipped(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
        results = {"context": {"primary_intent": "order", "confidence": 0.8}}
        ctx = {"user_preferences": {}}
        result = fresh_recognizer._merge_results(results, "msg", ctx)
        # user_prefs is falsy, so the condition `if user_prefs and ...` is False
        # falls through to distilled/bert/deepseek/hybrid, then context
        assert result["primary_intent"] == "order"

    def test_distilled_no_primary_intent_skipped(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
        results = {
            "distilled": {"primary_intent": None, "confidence": 0.9},
            "context": {"primary_intent": "ctx", "confidence": 0.5},
        }
        result = fresh_recognizer._merge_results(results, "msg", None)
        assert result["primary_intent"] == "ctx"

    def test_bert_high_confidence_selected(self, fresh_recognizer: UnifiedIntentRecognizer) -> None:
        results = {"bert": {"primary_intent": "bert_intent", "confidence": 0.9}}
        result = fresh_recognizer._merge_results(results, "msg", None)
        assert result["primary_intent"] == "bert_intent"

    def test_deepseek_high_confidence_selected(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
        results = {"deepseek": {"primary_intent": "ds_intent", "confidence": 0.9}}
        result = fresh_recognizer._merge_results(results, "msg", None)
        assert result["primary_intent"] == "ds_intent"

    def test_hybrid_high_confidence_selected(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
        results = {"hybrid": {"primary_intent": "hybrid_intent", "confidence": 0.9}}
        result = fresh_recognizer._merge_results(results, "msg", None)
        assert result["primary_intent"] == "hybrid_intent"

    def test_no_context_falls_to_rule(self, fresh_recognizer: UnifiedIntentRecognizer) -> None:
        results = {"rule": {"primary_intent": "order", "confidence": 0.5}}
        result = fresh_recognizer._merge_results(results, "msg", None)
        assert result["primary_intent"] == "order"

    def test_empty_results_short_message_unclear(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
        result = fresh_recognizer._merge_results({}, "ab", None)
        assert result["is_likely_unclear"] is True
        assert result["confidence"] == 0.0


# ── _recognize_from_context deep ─────────────────────────────────────────────


class TestRecognizeFromContextDeep:
    def test_pending_confirmation_empty_dict(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
        result = fresh_recognizer._recognize_from_context("msg", {"pending_confirmation": {}})
        assert result is None

    def test_pending_confirmation_none_intent(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
        result = fresh_recognizer._recognize_from_context(
            "msg", {"pending_confirmation": {"intent": None, "tool_key": None}}
        )
        assert result is None

    def test_last_intent_no_slots(self, fresh_recognizer: UnifiedIntentRecognizer) -> None:
        result = fresh_recognizer._recognize_from_context(
            "msg", {"last_intent": "order", "last_slots": {}}
        )
        # last_slots is falsy, so the `if last_intent and last_slots` is False
        # falls through to recent_intents
        assert result is None

    def test_current_intent_no_slots(self, fresh_recognizer: UnifiedIntentRecognizer) -> None:
        result = fresh_recognizer._recognize_from_context(
            "msg", {"current_intent": "order", "last_slots": {}}
        )
        assert result is None

    def test_recent_intents_empty(self, fresh_recognizer: UnifiedIntentRecognizer) -> None:
        result = fresh_recognizer._recognize_from_context("msg", {"recent_intents": []})
        assert result is None

    def test_no_relevant_context_keys(self, fresh_recognizer: UnifiedIntentRecognizer) -> None:
        result = fresh_recognizer._recognize_from_context("msg", {"other_key": "value"})
        assert result is None


# ── Singleton accessors deep ─────────────────────────────────────────────────


class TestSingletonAccessorsDeep:
    def test_get_unified_intent_recognizer_creates_once(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import app.services.unified_intent_recognizer as mod

        monkeypatch.setattr(mod, "_unified_recognizer", None)
        monkeypatch.setattr(UnifiedIntentRecognizer, "_init_recognizers", lambda self: None)
        r1 = get_unified_intent_recognizer()
        r2 = get_unified_intent_recognizer()
        assert r1 is r2

    def test_reload_unified_recognizer_no_existing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import app.services.unified_intent_recognizer as mod

        monkeypatch.setattr(mod, "_unified_recognizer", None)
        monkeypatch.setattr(UnifiedIntentRecognizer, "_init_recognizers", lambda self: None)
        # _unified_recognizer is None, so reload doesn't call .reload()
        r = reload_unified_recognizer()
        assert r is not None

    def test_reload_unified_recognizer_with_existing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import app.services.unified_intent_recognizer as mod

        existing = MagicMock()
        monkeypatch.setattr(mod, "_unified_recognizer", existing)
        r = reload_unified_recognizer()
        existing.reload.assert_called_once()
        assert r is existing
