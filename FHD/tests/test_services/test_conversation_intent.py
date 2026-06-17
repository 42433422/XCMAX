"""Tests for app.services.conversation.intent — IntentMixin pure methods."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from app.services.conversation.intent import IntentMixin

# ========================= _is_pro_source ================================


class TestIsProSource:
    def test_pro(self):
        m = IntentMixin()
        assert m._is_pro_source("pro") is True

    def test_pro_mode(self):
        m = IntentMixin()
        assert m._is_pro_source("pro_mode") is True

    def test_promode(self):
        m = IntentMixin()
        assert m._is_pro_source("promode") is True

    def test_pro_mode_hyphen(self):
        m = IntentMixin()
        assert m._is_pro_source("pro-mode") is True

    def test_pro_upper(self):
        m = IntentMixin()
        assert m._is_pro_source("PRO") is True

    def test_non_pro(self):
        m = IntentMixin()
        assert m._is_pro_source("web") is False

    def test_none(self):
        m = IntentMixin()
        assert m._is_pro_source(None) is False

    def test_empty(self):
        m = IntentMixin()
        assert m._is_pro_source("") is False


# ========================= _normalize_ai_mode ============================


class TestNormalizeAiMode:
    def test_offline(self):
        assert IntentMixin._normalize_ai_mode("offline") == "offline"

    def test_local(self):
        assert IntentMixin._normalize_ai_mode("local") == "offline"

    def test_online(self):
        assert IntentMixin._normalize_ai_mode("online") == "online"

    def test_other(self):
        assert IntentMixin._normalize_ai_mode("deepseek") == "online"

    def test_none(self):
        assert IntentMixin._normalize_ai_mode(None) == "online"

    def test_empty(self):
        assert IntentMixin._normalize_ai_mode("") == "online"

    def test_upper(self):
        assert IntentMixin._normalize_ai_mode("OFFLINE") == "offline"


# ========================= _env_skip_intent_llm ==========================


class TestEnvSkipIntentLlm:
    def test_default_false(self):
        with patch.dict(os.environ, {}, clear=True):
            # Remove the env var if it exists
            os.environ.pop("XCAGI_SKIP_INTENT_LLM", None)
            assert IntentMixin._env_skip_intent_llm() is False

    def test_1(self):
        with patch.dict(os.environ, {"XCAGI_SKIP_INTENT_LLM": "1"}):
            assert IntentMixin._env_skip_intent_llm() is True

    def test_true(self):
        with patch.dict(os.environ, {"XCAGI_SKIP_INTENT_LLM": "true"}):
            assert IntentMixin._env_skip_intent_llm() is True

    def test_yes(self):
        with patch.dict(os.environ, {"XCAGI_SKIP_INTENT_LLM": "yes"}):
            assert IntentMixin._env_skip_intent_llm() is True

    def test_on(self):
        with patch.dict(os.environ, {"XCAGI_SKIP_INTENT_LLM": "on"}):
            assert IntentMixin._env_skip_intent_llm() is True

    def test_false_value(self):
        with patch.dict(os.environ, {"XCAGI_SKIP_INTENT_LLM": "0"}):
            assert IntentMixin._env_skip_intent_llm() is False

    def test_empty(self):
        with patch.dict(os.environ, {"XCAGI_SKIP_INTENT_LLM": ""}):
            assert IntentMixin._env_skip_intent_llm() is False


# ========================= _should_use_rule_only_intent ==================


class TestShouldUseRuleOnlyIntent:
    def test_env_skip(self):
        m = IntentMixin()
        with patch.dict(os.environ, {"XCAGI_SKIP_INTENT_LLM": "1"}):
            assert m._should_use_rule_only_intent(None) is True

    def test_context_skip(self):
        m = IntentMixin()
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("XCAGI_SKIP_INTENT_LLM", None)
            assert m._should_use_rule_only_intent({"skip_intent_llm": True}) is True

    def test_context_no_skip(self):
        m = IntentMixin()
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("XCAGI_SKIP_INTENT_LLM", None)
            assert m._should_use_rule_only_intent({"skip_intent_llm": False}) is False

    def test_none_context(self):
        m = IntentMixin()
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("XCAGI_SKIP_INTENT_LLM", None)
            assert m._should_use_rule_only_intent(None) is False


# ========================= _intent_rule_only_fast ========================


class TestIntentRuleOnlyFast:
    def test_basic(self):
        m = IntentMixin()
        m.intent_service = MagicMock(
            return_value={
                "primary_intent": "shipment_generate",
                "tool_key": "shipment_generate",
                "intent_hints": ["hint1"],
                "is_negated": False,
                "is_greeting": False,
                "is_goodbye": False,
                "is_help": False,
                "is_confirmation": False,
                "is_negation_intent": False,
                "is_likely_unclear": False,
                "all_matched_tools": ["tool1"],
            }
        )
        result = m._intent_rule_only_fast("生成发货单")
        assert result["primary_intent"] == "shipment_generate"
        assert result["final_intent"] == "shipment_generate"
        assert result["tool_key"] == "shipment_generate"
        assert result["intent_source"] == "rule_only_fast"
        assert result["slots"] == {}

    def test_none_result(self):
        m = IntentMixin()
        m.intent_service = MagicMock(return_value=None)
        result = m._intent_rule_only_fast("hello")
        assert result["primary_intent"] is None
        assert result["intent_source"] == "rule_only_fast"

    def test_empty_dict(self):
        m = IntentMixin()
        m.intent_service = MagicMock(return_value={})
        result = m._intent_rule_only_fast("hello")
        assert result["primary_intent"] is None
        assert result["is_negated"] is False
        assert result["is_greeting"] is False


# ========================= _convert_recognizer_result ====================


class TestConvertRecognizerResult:
    def test_basic(self):
        m = IntentMixin()
        recognizer_result = MagicMock()
        recognizer_result.primary_intent = "products"
        recognizer_result.tool_key = "products"
        recognizer_result.intent_hints = ["hint"]
        recognizer_result.is_negated = False
        recognizer_result.is_greeting = False
        recognizer_result.is_goodbye = False
        recognizer_result.is_help = False
        recognizer_result.is_confirmation = False
        recognizer_result.is_negation_intent = False
        recognizer_result.is_likely_unclear = False
        recognizer_result.slots = {"key": "val"}
        recognizer_result.all_matched_tools = ["t1"]

        result = m._convert_recognizer_result(recognizer_result)
        assert result["primary_intent"] == "products"
        assert result["tool_key"] == "products"
        assert result["intent_source"] == "unified_recognizer"
        assert result["slots"] == {"key": "val"}


# ========================= _enhance_with_task_agent ======================


class TestEnhanceWithTaskAgent:
    def test_shipment_generate(self):
        m = IntentMixin()
        m.task_agent = MagicMock()
        m.task_agent.parse_task.return_value = {
            "task_type": "shipment_generate",
            "slots": {"unit_name": "测试客户"},
        }
        intent = {"slots": {}, "tool_key": None, "final_intent": None, "primary_intent": None}
        result = m._enhance_with_task_agent("给测试客户生成发货单", intent, "user1")
        assert result["slots"]["unit_name"] == "测试客户"
        assert result["tool_key"] == "shipment_generate"

    def test_unknown_task_type(self):
        m = IntentMixin()
        m.task_agent = MagicMock()
        m.task_agent.parse_task.return_value = {
            "task_type": "unknown_type",
            "slots": {},
        }
        intent = {"slots": {}, "tool_key": None, "final_intent": None, "primary_intent": None}
        result = m._enhance_with_task_agent("hello", intent, "user1")
        assert result["tool_key"] is None

    def test_none_plan(self):
        m = IntentMixin()
        m.task_agent = MagicMock()
        m.task_agent.parse_task.return_value = None
        intent = {"slots": {}}
        result = m._enhance_with_task_agent("hello", intent, "user1")
        assert result == intent

    def test_existing_tool_key_not_overwritten(self):
        m = IntentMixin()
        m.task_agent = MagicMock()
        m.task_agent.parse_task.return_value = {
            "task_type": "products",
            "slots": {"keyword": "test"},
        }
        intent = {
            "slots": {},
            "tool_key": "existing",
            "final_intent": "existing",
            "primary_intent": "existing",
        }
        result = m._enhance_with_task_agent("查询产品", intent, "user1")
        assert result["tool_key"] == "existing"


# ========================= _resolve_ai_mode ==============================


class TestResolveAiMode:
    def test_preference_offline(self):
        m = IntentMixin()
        m.user_preference_service = MagicMock()
        m.user_preference_service.get_preference.side_effect = lambda uid, key: (
            "offline" if key == "aiMode" else None
        )
        result = m._resolve_ai_mode("user1")
        assert result == "offline"

    def test_preference_online(self):
        m = IntentMixin()
        m.user_preference_service = MagicMock()
        m.user_preference_service.get_preference.side_effect = lambda uid, key: (
            "online" if key == "aiMode" else None
        )
        result = m._resolve_ai_mode("user1")
        assert result == "online"

    def test_legacy_model_migration(self):
        m = IntentMixin()
        m.user_preference_service = MagicMock()
        m.user_preference_service.get_preference.side_effect = lambda uid, key: (
            None if key == "aiMode" else "offline"
        )
        result = m._resolve_ai_mode("user1")
        assert result == "offline"
        m.user_preference_service.set_preference.assert_called_once()

    def test_fallback_online(self):
        m = IntentMixin()
        m.user_preference_service = MagicMock()
        m.user_preference_service.get_preference.side_effect = RuntimeError("db error")
        result = m._resolve_ai_mode("user1")
        assert result == "online"
