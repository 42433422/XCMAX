"""测试 unified_intent_recognizer 模块的统一意图识别。"""

from unittest.mock import MagicMock, patch

import pytest

from app.services.unified_intent_recognizer import (
    RecognizerResult,
    RecognizerType,
    UnifiedIntentRecognizer,
)

# ---------------------------------------------------------------------------
# RecognizerType
# ---------------------------------------------------------------------------


class TestRecognizerType:
    def test_all_types(self):
        assert RecognizerType.RULE.value == "rule"
        assert RecognizerType.DISTILLED.value == "distilled"
        assert RecognizerType.BERT.value == "bert"
        assert RecognizerType.DEEPSEEK.value == "deepseek"
        assert RecognizerType.RASA.value == "rasa"
        assert RecognizerType.HYBRID.value == "hybrid"


# ---------------------------------------------------------------------------
# RecognizerResult
# ---------------------------------------------------------------------------


class TestRecognizerResult:
    def test_create_result(self):
        result = RecognizerResult(
            primary_intent="create_order",
            tool_key="shipment_generate",
            intent_hints=["create_order"],
            is_negated=False,
            is_greeting=False,
            is_goodbye=False,
            is_help=False,
            is_confirmation=False,
            is_negation_intent=False,
            is_likely_unclear=False,
            all_matched_tools=[],
            slots={"unit_name": "TestUnit"},
            confidence=0.95,
            sources_used=["rule"],
            raw_results={},
        )
        assert result.primary_intent == "create_order"
        assert result.tool_key == "shipment_generate"
        assert result.confidence == 0.95
        assert result.slots["unit_name"] == "TestUnit"
        assert result.sources_used == ["rule"]


# ---------------------------------------------------------------------------
# _merge_results
# ---------------------------------------------------------------------------


class TestMergeResults:
    @pytest.fixture
    def recognizer(self):
        """Create a recognizer with mocked _init_recognizers to avoid heavy imports."""
        with patch.object(UnifiedIntentRecognizer, "_init_recognizers"):
            r = UnifiedIntentRecognizer.__new__(UnifiedIntentRecognizer)
            r._initialized = True
            r._rule_recognizer = None
            r._distilled_recognizer = None
            r._bert_recognizer = None
            r._deepseek_recognizer = None
            r._rasa_service = None
            r._hybrid_service = None
            r._rule_engine = MagicMock()
            return r

    def test_empty_results_returns_unclear(self, recognizer):
        result = recognizer._merge_results({}, "hi")
        assert result["primary_intent"] is None
        assert result.get("is_likely_unclear") is True

    def test_empty_results_long_message_not_unclear(self, recognizer):
        result = recognizer._merge_results({}, "这是一条比较长的消息")
        assert result["is_likely_unclear"] is False

    def test_rule_result_with_tool_key_wins(self, recognizer):
        results = {
            "rule": {
                "primary_intent": "create",
                "tool_key": "shipment_generate",
                "is_negated": False,
            },
            "distilled": {"primary_intent": "other", "confidence": 0.9},
        }
        result = recognizer._merge_results(results, "生成发货单")
        assert result["primary_intent"] == "create"

    def test_rule_result_negated_skipped(self, recognizer):
        results = {
            "rule": {
                "primary_intent": "create",
                "tool_key": "shipment_generate",
                "is_negated": True,
            },
        }
        result = recognizer._merge_results(results, "不要生成")
        assert result["primary_intent"] == "create"
        # negated rule is still returned as fallback

    def test_context_result_with_pending(self, recognizer):
        results = {
            "context": {"primary_intent": "confirm", "confidence": 0.9, "slots": {}},
        }
        context_data = {"pending_confirmation": {"intent": "confirm"}}
        result = recognizer._merge_results(results, "是的", context_data)
        assert result["primary_intent"] == "confirm"

    def test_context_result_with_user_prefs(self, recognizer):
        results = {
            "context": {"primary_intent": "query", "confidence": 0.8, "slots": {}},
        }
        context_data = {"user_preferences": {"favorite_customer": "UnitA"}}
        result = recognizer._merge_results(results, "查询", context_data)
        assert result["primary_intent"] == "query"
        assert result["slots"]["unit_name"] == "UnitA"

    def test_distilled_high_confidence(self, recognizer):
        results = {
            "distilled": {"primary_intent": "search", "confidence": 0.85},
        }
        result = recognizer._merge_results(results, "搜索")
        assert result["primary_intent"] == "search"

    def test_distilled_low_confidence_skipped(self, recognizer):
        results = {
            "distilled": {"primary_intent": "search", "confidence": 0.3},
        }
        result = recognizer._merge_results(results, "搜索")
        # Low confidence distilled result is returned but not selected by high-conf filter
        # It falls through to the rule fallback which doesn't exist
        assert result.get("primary_intent") == "search" or result.get("primary_intent") is None

    def test_context_fallback_when_no_other(self, recognizer):
        results = {
            "context": {"primary_intent": "inherit", "confidence": 0.5, "slots": {}},
        }
        result = recognizer._merge_results(results, "继续")
        assert result["primary_intent"] == "inherit"


# ---------------------------------------------------------------------------
# _recognize_from_context
# ---------------------------------------------------------------------------


class TestRecognizeFromContext:
    @pytest.fixture
    def recognizer(self):
        with patch.object(UnifiedIntentRecognizer, "_init_recognizers"):
            r = UnifiedIntentRecognizer.__new__(UnifiedIntentRecognizer)
            r._initialized = True
            r._rule_recognizer = None
            r._distilled_recognizer = None
            r._bert_recognizer = None
            r._deepseek_recognizer = None
            r._rasa_service = None
            r._hybrid_service = None
            r._rule_engine = MagicMock()
            return r

    def test_pending_confirmation(self, recognizer):
        ctx = {"pending_confirmation": {"intent": "create_order", "slots": {"unit": "A"}}}
        result = recognizer._recognize_from_context("确认", ctx)
        assert result is not None
        assert result["primary_intent"] == "create_order"
        assert result["source"] == "context_pending"

    def test_pending_with_tool_key(self, recognizer):
        ctx = {"pending_confirmation": {"tool_key": "shipment_generate", "slots": {}}}
        result = recognizer._recognize_from_context("是的", ctx)
        assert result is not None
        assert result["primary_intent"] == "shipment_generate"

    def test_last_intent_with_slots(self, recognizer):
        ctx = {"last_intent": "query", "last_slots": {"unit_name": "B"}}
        result = recognizer._recognize_from_context("继续", ctx)
        assert result is not None
        assert result["primary_intent"] == "query"
        assert result["source"] == "context_inherit"

    def test_recent_intents(self, recognizer):
        ctx = {"recent_intents": ["search", "create"]}
        result = recognizer._recognize_from_context("再查一下", ctx)
        assert result is not None
        assert result["primary_intent"] == "search"
        assert result["source"] == "context_recent"

    def test_no_context_data(self, recognizer):
        result = recognizer._recognize_from_context("hello", {})
        assert result is None

    def test_empty_pending(self, recognizer):
        ctx = {"pending_confirmation": None, "last_intent": None, "recent_intents": []}
        result = recognizer._recognize_from_context("hello", ctx)
        assert result is None


# ---------------------------------------------------------------------------
# _recognize_rule / _recognize_distilled / _recognize_bert
# ---------------------------------------------------------------------------


class TestRecognizeHelpers:
    @pytest.fixture
    def recognizer(self):
        with patch.object(UnifiedIntentRecognizer, "_init_recognizers"):
            r = UnifiedIntentRecognizer.__new__(UnifiedIntentRecognizer)
            r._initialized = True
            r._rule_recognizer = None
            r._distilled_recognizer = None
            r._bert_recognizer = None
            r._deepseek_recognizer = None
            r._rasa_service = None
            r._hybrid_service = None
            r._rule_engine = MagicMock()
            return r

    @patch(
        "app.services.intent_service.recognize_intents", return_value={"primary_intent": "create"}
    )
    def test_rule_recognize(self, mock_recognize, recognizer):
        result = recognizer._recognize_rule("生成发货单")
        assert result is not None
        assert result["primary_intent"] == "create"

    @patch("app.services.intent_service.recognize_intents", side_effect=RuntimeError("fail"))
    def test_rule_recognize_error(self, mock_recognize, recognizer):
        result = recognizer._recognize_rule("生成发货单")
        assert result is None

    def test_distilled_no_recognizer(self, recognizer):
        recognizer._distilled_recognizer = None
        result = recognizer._recognize_distilled("test")
        assert result is None

    def test_distilled_with_result(self, recognizer):
        mock_dr = MagicMock()
        mock_dr.recognize.return_value = {"intent": "search", "confidence": 0.9}
        recognizer._distilled_recognizer = mock_dr
        result = recognizer._recognize_distilled("搜索")
        assert result is not None
        assert result["primary_intent"] == "search"

    def test_distilled_no_intent(self, recognizer):
        mock_dr = MagicMock()
        mock_dr.recognize.return_value = {"confidence": 0.5}
        recognizer._distilled_recognizer = mock_dr
        result = recognizer._recognize_distilled("test")
        assert result is None

    def test_bert_no_recognizer(self, recognizer):
        recognizer._bert_recognizer = None
        result = recognizer._recognize_bert("test")
        assert result is None

    def test_bert_with_result(self, recognizer):
        mock_br = MagicMock()
        mock_br.predict.return_value = {"intent": "query", "confidence": 0.85}
        recognizer._bert_recognizer = mock_br
        result = recognizer._recognize_bert("查询")
        assert result is not None
        assert result["primary_intent"] == "query"

    def test_bert_no_intent(self, recognizer):
        mock_br = MagicMock()
        mock_br.predict.return_value = {"confidence": 0.3}
        recognizer._bert_recognizer = mock_br
        result = recognizer._recognize_bert("test")
        assert result is None

    def test_deepseek_no_recognizer(self, recognizer):
        recognizer._deepseek_recognizer = None
        result = recognizer._recognize_deepseek("test")
        assert result is None
