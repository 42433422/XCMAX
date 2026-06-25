"""Deep tests for ``app.services.unified_intent_recognizer`` covering remaining uncovered branches.

These assert on the *observable behavior* of the recognizer — the concrete
``RecognizerResult`` it produces and the merged intent dict — not merely on
whether internal helpers were invoked. Sub-engines are mocked only as external
dependencies; the assertions land on the values the unit under test returns.
"""

from __future__ import annotations

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
    def test_all_values_are_the_documented_set(self) -> None:
        # The six engines named in the module docstring must each have an enum value.
        values = {t.value for t in RecognizerType}
        assert values == {"rule", "distilled", "bert", "deepseek", "rasa", "hybrid"}
        # And distinctness is implied by the set having the same length as the members.
        assert len(values) == len(list(RecognizerType)) == 6

    def test_lookup_by_value_roundtrips_to_member(self) -> None:
        assert RecognizerType("rule") is RecognizerType.RULE
        assert RecognizerType("deepseek") is RecognizerType.DEEPSEEK
        for t in RecognizerType:
            assert RecognizerType(t.value) is t


# ── recognize() main entry deep ──────────────────────────────────────────────


class TestRecognizeMainDeep:
    def test_quick_recognize_non_quick_source_confidence_0_85(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
        # source != "quick_command" → confidence is the 0.85 branch (line 230).
        quick_result = {
            "primary_intent": "order",
            "tool_key": "order",
            "elapsed_ms": 10,
            "source": "context_inherit",
            "context_inherited": True,
            "slots": {"unit_name": "客户A"},
        }
        with patch(
            "app.services.intent_service.quick_recognize",
            return_value=quick_result,
        ):
            result = fresh_recognizer.recognize("msg", context_data={"k": "v"})
        assert result.confidence == 0.85
        assert result.primary_intent == "order"
        assert result.tool_key == "order"
        assert result.intent_hints == ["order"]
        assert result.slots == {"unit_name": "客户A"}
        assert result.sources_used == ["quick"]
        # quick path returns immediately: rule/context never populate raw_results.
        assert result.raw_results == {"quick_result": quick_result}

    def test_quick_recognize_quick_command_source_confidence_0_95(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
        # source == "quick_command" → the 0.95 branch (the other half of line 230).
        quick_result = {
            "primary_intent": "order",
            "tool_key": "order",
            "elapsed_ms": 5,
            "source": "quick_command",
        }
        with patch(
            "app.services.intent_service.quick_recognize",
            return_value=quick_result,
        ):
            result = fresh_recognizer.recognize("msg", context_data={"k": "v"})
        assert result.confidence == 0.95
        # slots defaults to {} when the quick result omits it.
        assert result.slots == {}

    def test_quick_recognize_slow_elapsed_does_not_short_circuit(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
        # elapsed_ms >= 50 → quick path is NOT taken; falls through to merge.
        quick_result = {
            "primary_intent": "order",
            "tool_key": "order",
            "elapsed_ms": 80,
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
        # "quick" must NOT appear because the elapsed gate rejected it.
        assert "quick" not in result.sources_used
        # No engine produced anything → merged primary_intent is None.
        assert result.primary_intent is None

    def test_quick_recognize_no_tool_key_keeps_intent_hint(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
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
        # intent_hints == [primary_intent] since primary_intent is truthy.
        assert result.intent_hints == ["order"]
        assert result.confidence == 0.95

    def test_quick_recognize_falsy_primary_intent_falls_through(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
        # primary_intent falsy → the quick short-circuit guard (line 205) is False,
        # so we fall through to rule recognition and merge.
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
        assert "quick" not in result.sources_used
        assert result.intent_hints == []
        assert result.primary_intent is None

    def test_no_context_data_means_no_context_source(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
        # Without context_data the context branch is skipped: a context result that
        # *would* win is never consulted, so it cannot appear in sources_used.
        with (
            patch.object(UnifiedIntentRecognizer, "_recognize_rule", return_value=None),
            patch.object(
                UnifiedIntentRecognizer,
                "_recognize_from_context",
                return_value={"primary_intent": "ctx", "confidence": 0.9},
            ) as mock_ctx,
        ):
            result = fresh_recognizer.recognize("msg")
        mock_ctx.assert_not_called()
        assert "context" not in result.sources_used
        assert result.primary_intent is None

    def test_distilled_available_result_wins_merge(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
        # An available distilled engine returning a high-confidence intent must
        # surface as the final primary_intent and add "distilled" to sources_used.
        mock_distilled = MagicMock()
        mock_distilled.is_available.return_value = True
        fresh_recognizer._distilled_recognizer = mock_distilled
        with (
            patch.object(
                UnifiedIntentRecognizer,
                "_recognize_distilled",
                return_value={"primary_intent": "distilled_intent", "confidence": 0.95},
            ),
            patch.object(UnifiedIntentRecognizer, "_recognize_rule", return_value=None),
        ):
            result = fresh_recognizer.recognize("msg")
        assert "distilled" in result.sources_used
        assert result.primary_intent == "distilled_intent"
        assert result.confidence == 0.95

    def test_distilled_not_available_is_never_consulted(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
        # is_available() False → the distilled branch is skipped, so even a result
        # that the stub *would* return cannot influence the merge.
        mock_distilled = MagicMock()
        mock_distilled.is_available.return_value = False
        fresh_recognizer._distilled_recognizer = mock_distilled
        with (
            patch.object(
                UnifiedIntentRecognizer,
                "_recognize_distilled",
                return_value={"primary_intent": "distilled_intent", "confidence": 0.95},
            ) as mock_dist,
            patch.object(UnifiedIntentRecognizer, "_recognize_rule", return_value=None),
        ):
            result = fresh_recognizer.recognize("msg")
        mock_dist.assert_not_called()
        assert "distilled" not in result.sources_used
        assert result.primary_intent is None

    def test_bert_present_result_wins_merge(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
        fresh_recognizer._bert_recognizer = MagicMock()
        with (
            patch.object(
                UnifiedIntentRecognizer,
                "_recognize_bert",
                return_value={"primary_intent": "bert_intent", "confidence": 0.88},
            ),
            patch.object(UnifiedIntentRecognizer, "_recognize_rule", return_value=None),
        ):
            result = fresh_recognizer.recognize("msg")
        assert "bert" in result.sources_used
        assert result.primary_intent == "bert_intent"
        assert result.confidence == 0.88

    def test_bert_none_is_never_consulted(self, fresh_recognizer: UnifiedIntentRecognizer) -> None:
        fresh_recognizer._bert_recognizer = None
        with (
            patch.object(
                UnifiedIntentRecognizer,
                "_recognize_bert",
                return_value={"primary_intent": "bert_intent", "confidence": 0.88},
            ) as mock_bert,
            patch.object(UnifiedIntentRecognizer, "_recognize_rule", return_value=None),
        ):
            result = fresh_recognizer.recognize("msg")
        mock_bert.assert_not_called()
        assert "bert" not in result.sources_used
        assert result.primary_intent is None

    def test_deepseek_skipped_for_normal_profile_and_surface(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
        # tool_execution_profile == "normal" AND ui_surface == "normal" → DeepSeek
        # is skipped (line 264-270). A DeepSeek result that would win must not appear.
        fresh_recognizer._deepseek_recognizer = MagicMock()
        ctx = {"tool_execution_profile": "Normal", "ui_surface": " normal "}  # mixed case/spaces
        with (
            patch.object(UnifiedIntentRecognizer, "_recognize_rule", return_value=None),
            patch.object(UnifiedIntentRecognizer, "_recognize_from_context", return_value=None),
            patch.object(
                UnifiedIntentRecognizer,
                "_recognize_deepseek",
                return_value={"primary_intent": "ds_intent", "confidence": 0.99},
            ) as mock_ds,
        ):
            result = fresh_recognizer.recognize("msg", context_data=ctx)
        mock_ds.assert_not_called()
        assert "deepseek" not in result.sources_used
        assert result.primary_intent is None

    def test_deepseek_runs_when_surface_not_normal(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
        # profile normal but ui_surface != normal → not skipped; DeepSeek result wins.
        fresh_recognizer._deepseek_recognizer = MagicMock()
        ctx = {"tool_execution_profile": "normal", "ui_surface": "advanced"}
        with (
            patch.object(UnifiedIntentRecognizer, "_recognize_rule", return_value=None),
            patch.object(UnifiedIntentRecognizer, "_recognize_from_context", return_value=None),
            patch.object(
                UnifiedIntentRecognizer,
                "_recognize_deepseek",
                return_value={"primary_intent": "ds_intent", "confidence": 0.99},
            ),
        ):
            result = fresh_recognizer.recognize("msg", context_data=ctx)
        assert "deepseek" in result.sources_used
        assert result.primary_intent == "ds_intent"
        assert result.confidence == 0.99

    def test_deepseek_runs_when_profile_not_normal(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
        # ui_surface normal but profile != normal → not skipped; DeepSeek wins.
        fresh_recognizer._deepseek_recognizer = MagicMock()
        ctx = {"tool_execution_profile": "advanced", "ui_surface": "normal"}
        with (
            patch.object(UnifiedIntentRecognizer, "_recognize_rule", return_value=None),
            patch.object(UnifiedIntentRecognizer, "_recognize_from_context", return_value=None),
            patch.object(
                UnifiedIntentRecognizer,
                "_recognize_deepseek",
                return_value={"primary_intent": "ds_intent", "confidence": 0.99},
            ),
        ):
            result = fresh_recognizer.recognize("msg", context_data=ctx)
        assert "deepseek" in result.sources_used
        assert result.primary_intent == "ds_intent"

    def test_deepseek_runs_when_profile_strings_empty(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
        # Empty strings strip to "" which != "normal", so skip stays False → DeepSeek runs.
        fresh_recognizer._deepseek_recognizer = MagicMock()
        ctx = {"tool_execution_profile": "", "ui_surface": ""}
        with (
            patch.object(UnifiedIntentRecognizer, "_recognize_rule", return_value=None),
            patch.object(UnifiedIntentRecognizer, "_recognize_from_context", return_value=None),
            patch.object(
                UnifiedIntentRecognizer,
                "_recognize_deepseek",
                return_value={"primary_intent": "ds_intent", "confidence": 0.99},
            ),
        ):
            result = fresh_recognizer.recognize("msg", context_data=ctx)
        assert "deepseek" in result.sources_used
        assert result.primary_intent == "ds_intent"

    def test_recoverable_quick_failure_falls_through_to_deepseek(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
        # quick_recognize raising a RECOVERABLE error is swallowed (line 234), and the
        # pipeline continues; DeepSeek then produces the winning intent.
        fresh_recognizer._deepseek_recognizer = MagicMock()
        with (
            patch(
                "app.services.intent_service.quick_recognize",
                side_effect=RuntimeError("simulated infra failure"),
            ),
            patch.object(UnifiedIntentRecognizer, "_recognize_rule", return_value=None),
            patch.object(UnifiedIntentRecognizer, "_recognize_from_context", return_value=None),
            patch.object(
                UnifiedIntentRecognizer,
                "_recognize_deepseek",
                return_value={"primary_intent": "ds_intent", "confidence": 0.99},
            ),
        ):
            result = fresh_recognizer.recognize("msg", context_data={"pending_confirmation": False})
        # The recoverable failure did not crash the call.
        assert "quick" not in result.sources_used
        assert result.primary_intent == "ds_intent"

    def test_recognize_with_no_results_is_empty_recognizer_result(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
        with patch.object(UnifiedIntentRecognizer, "_recognize_rule", return_value=None):
            result = fresh_recognizer.recognize("hello world long enough")
        assert isinstance(result, RecognizerResult)
        assert result.raw_results == {}
        assert result.sources_used == []
        assert result.primary_intent is None
        assert result.tool_key is None
        assert result.confidence == 0.0
        # message longer than 4 chars → not flagged unclear.
        assert result.is_likely_unclear is False

    def test_rule_wins_over_context_when_rule_has_tool_key(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
        # Rule with a tool_key and not negated wins immediately (line 432-433),
        # even though a context result is also collected.
        rule_result = {"primary_intent": "order", "tool_key": "order", "is_negated": False}
        ctx_result = {"primary_intent": "ctx_intent", "confidence": 0.6}
        with (
            patch.object(UnifiedIntentRecognizer, "_recognize_rule", return_value=rule_result),
            patch.object(
                UnifiedIntentRecognizer, "_recognize_from_context", return_value=ctx_result
            ),
        ):
            result = fresh_recognizer.recognize("msg", context_data={"k": "v"})
        assert result.sources_used == ["rule", "context"]
        # Rule wins the merge despite context being present.
        assert result.primary_intent == "order"
        assert result.tool_key == "order"
        assert result.raw_results["rule"] == rule_result
        assert result.raw_results["context"] == ctx_result


# ── _recognize_deepseek deep ─────────────────────────────────────────────────


class TestRecognizeDeepseekDeep:
    def test_deepseek_success_maps_intent_confidence_slots(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
        mock_ds = MagicMock()

        async def fake_recognize(msg, ctx):
            return {"intent": "order", "confidence": 0.9, "slots": {"k": "v"}}

        mock_ds.recognize = fake_recognize
        fresh_recognizer._deepseek_recognizer = mock_ds
        result = fresh_recognizer._recognize_deepseek("msg", [{"role": "user", "content": "hi"}])
        assert result == {
            "primary_intent": "order",
            "tool_key": "order",
            "confidence": 0.9,
            "slots": {"k": "v"},
        }

    def test_deepseek_success_defaults_missing_slots_to_empty(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
        mock_ds = MagicMock()

        async def fake_recognize(msg, ctx):
            return {"intent": "order", "confidence": 0.9}

        mock_ds.recognize = fake_recognize
        fresh_recognizer._deepseek_recognizer = mock_ds
        result = fresh_recognizer._recognize_deepseek("msg")
        assert result["slots"] == {}
        assert result["primary_intent"] == "order"

    def test_deepseek_missing_confidence_defaults_to_zero(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
        mock_ds = MagicMock()

        async def fake_recognize(msg, ctx):
            return {"intent": "order"}

        mock_ds.recognize = fake_recognize
        fresh_recognizer._deepseek_recognizer = mock_ds
        result = fresh_recognizer._recognize_deepseek("msg")
        assert result["confidence"] == 0.0

    def test_deepseek_no_intent_returns_none(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
        # result present but without an "intent" key → maps to None (line 405/412).
        mock_ds = MagicMock()

        async def fake_recognize(msg, ctx):
            return {"confidence": 0.9, "slots": {"k": "v"}}

        mock_ds.recognize = fake_recognize
        fresh_recognizer._deepseek_recognizer = mock_ds
        assert fresh_recognizer._recognize_deepseek("msg") is None

    def test_deepseek_no_recognizer_returns_none(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
        fresh_recognizer._deepseek_recognizer = None
        assert fresh_recognizer._recognize_deepseek("msg") is None

    def test_deepseek_recoverable_error_returns_none(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
        mock_ds = MagicMock()

        async def boom(msg, ctx):
            raise RuntimeError("upstream down")

        mock_ds.recognize = boom
        fresh_recognizer._deepseek_recognizer = mock_ds
        # RuntimeError is recoverable → swallowed, returns None instead of raising.
        assert fresh_recognizer._recognize_deepseek("msg") is None

    def test_deepseek_passes_context_through_to_engine(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
        mock_ds = MagicMock()
        captured = {}

        async def fake_recognize(msg, ctx):
            captured["msg"] = msg
            captured["ctx"] = ctx
            return {"intent": "order", "confidence": 0.9}

        mock_ds.recognize = fake_recognize
        fresh_recognizer._deepseek_recognizer = mock_ds
        ctx = [{"role": "user", "content": "hi"}]
        fresh_recognizer._recognize_deepseek("hello there", ctx)
        assert captured["msg"] == "hello there"
        assert captured["ctx"] == ctx


# ── _merge_results deep ──────────────────────────────────────────────────────


class TestMergeResultsDeep:
    def test_negated_rule_is_bypassed_for_distilled(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
        # Rule is negated → guard at line 432 fails, so the distilled result is chosen.
        results = {
            "rule": {"tool_key": "order", "is_negated": True, "primary_intent": "order"},
            "distilled": {"primary_intent": "chat", "confidence": 0.9},
        }
        result = fresh_recognizer._merge_results(results, "msg", None)
        assert result["primary_intent"] == "chat"
        assert result["confidence"] == 0.9

    def test_rule_without_tool_key_is_bypassed_for_distilled(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
        results = {
            "rule": {"tool_key": None, "primary_intent": "order"},
            "distilled": {"primary_intent": "chat", "confidence": 0.9},
        }
        result = fresh_recognizer._merge_results(results, "msg", None)
        assert result["primary_intent"] == "chat"

    def test_pending_context_below_threshold_falls_through_to_context(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
        # confidence 0.5 < 0.85 pending threshold → not returned early; with no other
        # engines the final fallback (line 458) returns the context result itself.
        results = {"context": {"primary_intent": "order", "confidence": 0.5}}
        ctx = {"pending_confirmation": {"intent": "order"}}
        result = fresh_recognizer._merge_results(results, "msg", ctx)
        assert result["primary_intent"] == "order"
        assert result["confidence"] == 0.5

    def test_pending_context_at_threshold_returns_immediately(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
        # confidence >= 0.85 with a pending confirmation → returns the context result early.
        results = {"context": {"primary_intent": "confirm_order", "confidence": 0.9}}
        ctx = {"pending_confirmation": {"intent": "confirm_order"}}
        result = fresh_recognizer._merge_results(results, "msg", ctx)
        assert result["primary_intent"] == "confirm_order"
        assert result["confidence"] == 0.9

    def test_user_prefs_inject_favorite_customer_into_empty_unit_name(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
        # user_prefs present + confidence >= 0.75 + no unit_name slot → favorite_customer
        # is injected into slots (line 446-448) and the enriched context is returned.
        results = {
            "context": {
                "primary_intent": "order",
                "confidence": 0.8,
                "slots": {},
            }
        }
        ctx = {"user_preferences": {"favorite_customer": "客户A"}}
        result = fresh_recognizer._merge_results(results, "msg", ctx)
        assert result["primary_intent"] == "order"
        assert result["slots"]["unit_name"] == "客户A"

    def test_user_prefs_below_threshold_does_not_inject(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
        # confidence 0.5 < 0.75 → injection branch skipped, slots stay empty,
        # but context is still the final fallback.
        results = {"context": {"primary_intent": "order", "confidence": 0.5, "slots": {}}}
        ctx = {"user_preferences": {"favorite_customer": "客户A"}}
        result = fresh_recognizer._merge_results(results, "msg", ctx)
        assert result["primary_intent"] == "order"
        assert "unit_name" not in result["slots"]

    def test_user_prefs_does_not_overwrite_existing_unit_name(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
        # When unit_name already set, favorite_customer must NOT clobber it.
        results = {
            "context": {
                "primary_intent": "order",
                "confidence": 0.8,
                "slots": {"unit_name": "客户B"},
            }
        }
        ctx = {"user_preferences": {"favorite_customer": "客户A"}}
        result = fresh_recognizer._merge_results(results, "msg", ctx)
        assert result["slots"]["unit_name"] == "客户B"

    def test_empty_user_prefs_dict_is_falsy_and_skipped(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
        results = {"context": {"primary_intent": "order", "confidence": 0.8, "slots": {}}}
        ctx = {"user_preferences": {}}
        result = fresh_recognizer._merge_results(results, "msg", ctx)
        # falls through; no injection, context returned as final fallback.
        assert result["primary_intent"] == "order"
        assert "unit_name" not in result["slots"]

    def test_distilled_without_primary_intent_falls_through_to_context(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
        # distilled has high confidence but no primary_intent → guard at line 454 fails,
        # so the context result is the final fallback.
        results = {
            "distilled": {"primary_intent": None, "confidence": 0.9},
            "context": {"primary_intent": "ctx", "confidence": 0.5},
        }
        result = fresh_recognizer._merge_results(results, "msg", None)
        assert result["primary_intent"] == "ctx"

    def test_distilled_low_confidence_falls_through_to_context(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
        # confidence 0.6 is NOT > 0.6 → distilled rejected, context wins.
        results = {
            "distilled": {"primary_intent": "dist", "confidence": 0.6},
            "context": {"primary_intent": "ctx", "confidence": 0.5},
        }
        result = fresh_recognizer._merge_results(results, "msg", None)
        assert result["primary_intent"] == "ctx"

    def test_bert_high_confidence_selected_over_lower_priority_sources(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
        results = {
            "bert": {"primary_intent": "bert_intent", "confidence": 0.9},
            "deepseek": {"primary_intent": "ds_intent", "confidence": 0.95},
        }
        result = fresh_recognizer._merge_results(results, "msg", None)
        # Iteration order is distilled, bert, deepseek, hybrid → bert wins first.
        assert result["primary_intent"] == "bert_intent"

    def test_deepseek_selected_when_only_source(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
        results = {"deepseek": {"primary_intent": "ds_intent", "confidence": 0.9}}
        result = fresh_recognizer._merge_results(results, "msg", None)
        assert result["primary_intent"] == "ds_intent"

    def test_hybrid_selected_when_only_source(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
        results = {"hybrid": {"primary_intent": "hybrid_intent", "confidence": 0.9}}
        result = fresh_recognizer._merge_results(results, "msg", None)
        assert result["primary_intent"] == "hybrid_intent"

    def test_rule_only_returned_as_last_resort(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
        # Rule without tool_key, no context, no ml engines → final fallback (line 460).
        results = {"rule": {"primary_intent": "order", "confidence": 0.5}}
        result = fresh_recognizer._merge_results(results, "msg", None)
        assert result["primary_intent"] == "order"

    def test_empty_results_short_message_is_unclear(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
        result = fresh_recognizer._merge_results({}, "ab", None)
        assert result == {
            "primary_intent": None,
            "tool_key": None,
            "confidence": 0.0,
            "slots": {},
            "is_likely_unclear": True,
        }

    def test_empty_results_long_message_is_not_unclear(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
        # len > 4 → is_likely_unclear is False (the other branch of line 427).
        result = fresh_recognizer._merge_results({}, "hello", None)
        assert result["is_likely_unclear"] is False
        assert result["primary_intent"] is None
        assert result["confidence"] == 0.0


# ── _recognize_from_context deep ─────────────────────────────────────────────


class TestRecognizeFromContextDeep:
    def test_pending_confirmation_with_intent_returns_high_confidence_result(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
        # The positive branch: pending intent → confidence 0.9 result with slots carried over.
        result = fresh_recognizer._recognize_from_context(
            "msg",
            {"pending_confirmation": {"intent": "order", "slots": {"qty": 3}}},
        )
        assert result == {
            "primary_intent": "order",
            "tool_key": "order",
            "confidence": 0.9,
            "slots": {"qty": 3},
            "source": "context_pending",
        }

    def test_pending_confirmation_falls_back_to_tool_key(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
        # No "intent" but a "tool_key" → pending_intent uses tool_key (line 305).
        result = fresh_recognizer._recognize_from_context(
            "msg", {"pending_confirmation": {"tool_key": "create_order"}}
        )
        assert result is not None
        assert result["primary_intent"] == "create_order"
        assert result["source"] == "context_pending"

    def test_pending_confirmation_empty_dict_returns_none(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
        # Empty pending dict is falsy → skipped; no other keys → None.
        result = fresh_recognizer._recognize_from_context("msg", {"pending_confirmation": {}})
        assert result is None

    def test_pending_confirmation_without_intent_or_tool_key_returns_none(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
        result = fresh_recognizer._recognize_from_context(
            "msg", {"pending_confirmation": {"intent": None, "tool_key": None}}
        )
        assert result is None

    def test_last_intent_with_slots_inherits_context(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
        # Positive branch for inheritance: last_intent + non-empty slots → confidence 0.7.
        result = fresh_recognizer._recognize_from_context(
            "msg", {"last_intent": "order", "last_slots": {"unit_name": "客户A"}}
        )
        assert result == {
            "primary_intent": "order",
            "tool_key": "order",
            "confidence": 0.7,
            "slots": {"unit_name": "客户A"},
            "source": "context_inherit",
        }

    def test_current_intent_alias_used_when_last_intent_absent(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
        # current_intent is the fallback for last_intent (line 315).
        result = fresh_recognizer._recognize_from_context(
            "msg", {"current_intent": "query", "last_slots": {"id": 7}}
        )
        assert result is not None
        assert result["primary_intent"] == "query"
        assert result["source"] == "context_inherit"

    def test_last_intent_without_slots_returns_none(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
        # last_slots empty → `last_intent and last_slots` is False → no inherit result.
        result = fresh_recognizer._recognize_from_context(
            "msg", {"last_intent": "order", "last_slots": {}}
        )
        assert result is None

    def test_current_intent_without_slots_returns_none(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
        result = fresh_recognizer._recognize_from_context(
            "msg", {"current_intent": "order", "last_slots": {}}
        )
        assert result is None

    def test_recent_intents_uses_first_with_low_confidence(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
        # Positive branch: recent_intents → first element, confidence 0.6, empty slots.
        result = fresh_recognizer._recognize_from_context(
            "msg", {"recent_intents": ["order", "query"]}
        )
        assert result == {
            "primary_intent": "order",
            "tool_key": "order",
            "confidence": 0.6,
            "slots": {},
            "source": "context_recent",
        }

    def test_recent_intents_empty_returns_none(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
        result = fresh_recognizer._recognize_from_context("msg", {"recent_intents": []})
        assert result is None

    def test_no_relevant_context_keys_returns_none(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
        result = fresh_recognizer._recognize_from_context("msg", {"other_key": "value"})
        assert result is None

    def test_pending_takes_priority_over_inherit_and_recent(
        self, fresh_recognizer: UnifiedIntentRecognizer
    ) -> None:
        # All three signals present → pending (highest confidence 0.9) wins.
        result = fresh_recognizer._recognize_from_context(
            "msg",
            {
                "pending_confirmation": {"intent": "confirm"},
                "last_intent": "order",
                "last_slots": {"x": 1},
                "recent_intents": ["query"],
            },
        )
        assert result["primary_intent"] == "confirm"
        assert result["confidence"] == 0.9
        assert result["source"] == "context_pending"


# ── Singleton accessors deep ─────────────────────────────────────────────────


class TestSingletonAccessorsDeep:
    def test_get_unified_intent_recognizer_returns_same_instance(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import app.services.unified_intent_recognizer as mod

        monkeypatch.setattr(mod, "_unified_recognizer", None)
        monkeypatch.setattr(UnifiedIntentRecognizer, "_init_recognizers", lambda self: None)
        r1 = get_unified_intent_recognizer()
        r2 = get_unified_intent_recognizer()
        assert r1 is r2
        assert isinstance(r1, UnifiedIntentRecognizer)
        # The module-level singleton now points at the same object.
        assert mod._unified_recognizer is r1

    def test_reload_with_no_existing_creates_new_without_calling_reload(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import app.services.unified_intent_recognizer as mod

        monkeypatch.setattr(mod, "_unified_recognizer", None)
        monkeypatch.setattr(UnifiedIntentRecognizer, "_init_recognizers", lambda self: None)
        with patch.object(UnifiedIntentRecognizer, "reload") as mock_reload:
            r = reload_unified_recognizer()
        # No existing instance → reload() must not be invoked, but a fresh one is created.
        mock_reload.assert_not_called()
        assert isinstance(r, UnifiedIntentRecognizer)
        assert mod._unified_recognizer is r

    def test_reload_with_existing_calls_reload_and_returns_same_instance(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import app.services.unified_intent_recognizer as mod

        existing = MagicMock()
        monkeypatch.setattr(mod, "_unified_recognizer", existing)
        r = reload_unified_recognizer()
        existing.reload.assert_called_once_with()
        # The existing singleton is preserved and returned.
        assert r is existing
        assert mod._unified_recognizer is existing
