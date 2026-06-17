"""COVERAGE_RAMP Phase 6 round 4: backend low-coverage modules.

Targets:
- ``app/services/conversation/handlers.py`` (~40.9% line coverage, 75 missed)
- ``app/services/conversation/intent.py`` (~45.0% line coverage, 82 missed)

Tests follow the phase-4 style: ``from __future__ import annotations``,
``unittest.mock`` + ``pytest``, mock only external boundaries
(``user_preference_service``, ``intent_service``, neuro_bus integration
helpers). The Mixin methods themselves are exercised for real.
"""

from __future__ import annotations

import os
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.conversation.context import ConversationContext
from app.services.conversation.handlers import HandlersMixin
from app.services.conversation.intent import IntentMixin


# ---------------------------------------------------------------------------
# Test host classes — combine Mixin with manually-injected dependencies
# ---------------------------------------------------------------------------


class _IntentHost(IntentMixin):
    """Minimal host exposing only what IntentMixin needs."""

    def __init__(self) -> None:
        self.user_preference_service = MagicMock()
        self.intent_service: Any = None
        self.online_intent_service = MagicMock()
        self.offline_intent_service = MagicMock()
        self.unified_recognizer = MagicMock()


class _HandlerHost(HandlersMixin):
    """Minimal host exposing only what HandlersMixin needs."""

    def __init__(self) -> None:
        self.history: list[tuple[str, str, str]] = []
        self.feedback: list[dict[str, Any]] = []
        self.actions: list[dict[str, Any]] = []
        self.confirmation_service = MagicMock()
        self.intent_service: Any = None
        self.user_memory = MagicMock()

    def add_to_history(self, user_id: str, role: str, content: str) -> bool:
        self.history.append((user_id, role, content))
        return True

    def add_intent_feedback(self, **kwargs: Any) -> None:
        self.feedback.append(kwargs)

    def record_user_action(self, **kwargs: Any) -> None:
        self.actions.append(kwargs)


# ===========================================================================
# IntentMixin._is_pro_source
# ===========================================================================


class TestIsProSource:
    @pytest.mark.parametrize(
        "source,expected",
        [
            ("pro", True),
            ("pro-mode", True),
            ("pro_mode", True),
            ("promode", True),
            ("PRO", True),
            ("PRO_MODE", True),
            ("  Pro  ", True),
            (None, False),
            ("", False),
            ("web", False),
            ("professional", False),
            ("xcagi-pro", False),
        ],
    )
    def test_variants(self, source: str | None, expected: bool) -> None:
        host = _IntentHost()
        assert host._is_pro_source(source) is expected


# ===========================================================================
# IntentMixin._normalize_ai_mode
# ===========================================================================


class TestNormalizeAiMode:
    @pytest.mark.parametrize(
        "mode,expected",
        [
            ("offline", "offline"),
            ("local", "offline"),
            ("OFFLINE", "offline"),
            ("Local", "offline"),
            ("  offline  ", "offline"),
            ("online", "online"),
            ("deepseek", "online"),
            (None, "online"),
            ("", "online"),
            ("anything", "online"),
        ],
    )
    def test_variants(self, mode: str | None, expected: str) -> None:
        assert IntentMixin._normalize_ai_mode(mode) == expected


# ===========================================================================
# IntentMixin._resolve_ai_mode
# ===========================================================================


class TestResolveAiMode:
    def test_aimode_preference_offline(self) -> None:
        host = _IntentHost()
        host.user_preference_service.get_preference.side_effect = (
            lambda uid, key: "offline" if key == "aiMode" else None
        )
        assert host._resolve_ai_mode("u1") == "offline"

    def test_aimode_preference_online(self) -> None:
        host = _IntentHost()
        host.user_preference_service.get_preference.side_effect = (
            lambda uid, key: "online" if key == "aiMode" else None
        )
        assert host._resolve_ai_mode("u1") == "online"

    def test_legacy_aimodel_migration_to_offline(self) -> None:
        host = _IntentHost()
        host.user_preference_service.get_preference.side_effect = (
            lambda uid, key: None if key == "aiMode" else "offline"
        )
        result = host._resolve_ai_mode("u1")
        assert result == "offline"
        host.user_preference_service.set_preference.assert_called_once_with(
            "u1", "aiMode", "offline"
        )

    def test_legacy_aimodel_migration_to_online(self) -> None:
        host = _IntentHost()
        host.user_preference_service.get_preference.side_effect = (
            lambda uid, key: None if key == "aiMode" else "deepseek"
        )
        result = host._resolve_ai_mode("u1")
        assert result == "online"
        host.user_preference_service.set_preference.assert_called_once_with(
            "u1", "aiMode", "online"
        )

    def test_no_preference_returns_online(self) -> None:
        host = _IntentHost()
        host.user_preference_service.get_preference.return_value = None
        assert host._resolve_ai_mode("u1") == "online"
        host.user_preference_service.set_preference.assert_not_called()

    def test_recoverable_error_falls_back_online(self) -> None:
        host = _IntentHost()
        host.user_preference_service.get_preference.side_effect = RuntimeError(
            "db down"
        )
        assert host._resolve_ai_mode("u1") == "online"

    def test_value_error_falls_back_online(self) -> None:
        host = _IntentHost()
        host.user_preference_service.get_preference.side_effect = ValueError(
            "bad shape"
        )
        assert host._resolve_ai_mode("u1") == "online"

    def test_empty_aimode_falls_to_legacy(self) -> None:
        host = _IntentHost()
        # aiMode is empty string (falsy) → fall to legacy aiModel
        host.user_preference_service.get_preference.side_effect = (
            lambda uid, key: "" if key == "aiMode" else "local"
        )
        assert host._resolve_ai_mode("u1") == "offline"
        host.user_preference_service.set_preference.assert_called_once_with(
            "u1", "aiMode", "offline"
        )


# ===========================================================================
# IntentMixin._env_skip_intent_llm
# ===========================================================================


class TestEnvSkipIntentLlm:
    @pytest.mark.parametrize(
        "value,expected",
        [
            ("1", True),
            ("true", True),
            ("yes", True),
            ("on", True),
            ("TRUE", True),
            ("Yes", True),
            ("ON", True),
            ("  1  ", True),
            ("0", False),
            ("false", False),
            ("no", False),
            ("off", False),
            ("", False),
            ("anything", False),
        ],
    )
    def test_values(
        self, value: str, expected: bool, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("XCAGI_SKIP_INTENT_LLM", value)
        assert IntentMixin._env_skip_intent_llm() is expected

    def test_unset_returns_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("XCAGI_SKIP_INTENT_LLM", raising=False)
        assert IntentMixin._env_skip_intent_llm() is False


# ===========================================================================
# IntentMixin._should_use_rule_only_intent
# ===========================================================================


class TestShouldUseRuleOnlyIntent:
    def test_env_skip_overrides_context(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("XCAGI_SKIP_INTENT_LLM", "1")
        host = _IntentHost()
        assert host._should_use_rule_only_intent(None) is True
        assert host._should_use_rule_only_intent({"skip_intent_llm": False}) is True

    def test_context_skip_when_env_off(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("XCAGI_SKIP_INTENT_LLM", raising=False)
        host = _IntentHost()
        assert host._should_use_rule_only_intent({"skip_intent_llm": True}) is True
        assert host._should_use_rule_only_intent({"skip_intent_llm": 1}) is True

    def test_context_no_skip(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("XCAGI_SKIP_INTENT_LLM", raising=False)
        host = _IntentHost()
        assert host._should_use_rule_only_intent({"skip_intent_llm": False}) is False
        assert host._should_use_rule_only_intent({}) is False

    def test_none_context(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("XCAGI_SKIP_INTENT_LLM", raising=False)
        host = _IntentHost()
        assert host._should_use_rule_only_intent(None) is False

    def test_non_dict_context(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("XCAGI_SKIP_INTENT_LLM", raising=False)
        host = _IntentHost()
        assert host._should_use_rule_only_intent("not a dict") is False
        assert host._should_use_rule_only_intent(123) is False


# ===========================================================================
# IntentMixin._intent_rule_only_fast
# ===========================================================================


class TestIntentRuleOnlyFast:
    def test_full_dict(self) -> None:
        host = _IntentHost()
        host.intent_service = MagicMock(
            return_value={
                "primary_intent": "shipment_generate",
                "tool_key": "shipment_generate",
                "intent_hints": ["hint1", "hint2"],
                "is_negated": True,
                "is_greeting": False,
                "is_goodbye": False,
                "is_help": False,
                "is_confirmation": False,
                "is_negation_intent": True,
                "is_likely_unclear": True,
                "all_matched_tools": ["t1", "t2"],
            }
        )
        out = host._intent_rule_only_fast("生成发货单")
        assert out["primary_intent"] == "shipment_generate"
        assert out["final_intent"] == "shipment_generate"
        assert out["tool_key"] == "shipment_generate"
        assert out["intent_hints"] == ["hint1", "hint2"]
        assert out["is_negated"] is True
        assert out["is_greeting"] is False
        assert out["is_goodbye"] is False
        assert out["is_help"] is False
        assert out["is_confirmation"] is False
        assert out["is_negation_intent"] is True
        assert out["is_likely_unclear"] is True
        assert out["slots"] == {}
        assert out["all_matched_tools"] == ["t1", "t2"]
        assert out["intent_source"] == "rule_only_fast"

    def test_non_dict_result_becomes_empty(self) -> None:
        host = _IntentHost()
        host.intent_service = MagicMock(return_value=None)
        out = host._intent_rule_only_fast("hello")
        assert out["primary_intent"] is None
        assert out["final_intent"] is None
        assert out["tool_key"] is None
        assert out["intent_hints"] == []
        assert out["is_negated"] is False
        assert out["is_greeting"] is False
        assert out["is_goodbye"] is False
        assert out["is_help"] is False
        assert out["is_confirmation"] is False
        assert out["is_negation_intent"] is False
        assert out["is_likely_unclear"] is False
        assert out["slots"] == {}
        assert out["all_matched_tools"] == []
        assert out["intent_source"] == "rule_only_fast"

    def test_empty_dict(self) -> None:
        host = _IntentHost()
        host.intent_service = MagicMock(return_value={})
        out = host._intent_rule_only_fast("hello")
        assert out["primary_intent"] is None
        assert out["final_intent"] is None
        assert out["tool_key"] is None
        assert out["intent_hints"] == []
        assert out["slots"] == {}
        assert out["all_matched_tools"] == []

    def test_final_intent_falls_back_to_tool_key(self) -> None:
        host = _IntentHost()
        host.intent_service = MagicMock(
            return_value={
                "tool_key": "products",
                # primary_intent missing → final_intent should fall back to tool_key
            }
        )
        out = host._intent_rule_only_fast("产品")
        assert out["primary_intent"] is None
        assert out["final_intent"] == "products"
        assert out["tool_key"] == "products"

    def test_intent_hints_none_becomes_empty_list(self) -> None:
        host = _IntentHost()
        host.intent_service = MagicMock(
            return_value={"intent_hints": None}
        )
        out = host._intent_rule_only_fast("hi")
        assert out["intent_hints"] == []

    def test_all_matched_tools_missing_becomes_empty_list(self) -> None:
        host = _IntentHost()
        host.intent_service = MagicMock(return_value={})
        out = host._intent_rule_only_fast("hi")
        assert out["all_matched_tools"] == []

    def test_intent_service_called_with_message(self) -> None:
        host = _IntentHost()
        host.intent_service = MagicMock(return_value={})
        host._intent_rule_only_fast("生成发货单")
        host.intent_service.assert_called_once_with("生成发货单")


# ===========================================================================
# IntentMixin._neuro_stack_enabled
# ===========================================================================


class TestNeuroStackEnabled:
    def test_default_on(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("XCAGI_NEURO_INTENT", raising=False)
        host = _IntentHost()
        assert host._neuro_stack_enabled() is True

    def test_explicit_on(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XCAGI_NEURO_INTENT", "1")
        host = _IntentHost()
        assert host._neuro_stack_enabled() is True

    @pytest.mark.parametrize("value", ["0", "false", "off", "no"])
    def test_disabled(
        self, value: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("XCAGI_NEURO_INTENT", value)
        host = _IntentHost()
        assert host._neuro_stack_enabled() is False


# ===========================================================================
# IntentMixin._convert_neuro_intent_bridge
# ===========================================================================


class TestConvertNeuroIntentBridge:
    def test_recognizer_result_present(self) -> None:
        host = _IntentHost()
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
        recognizer_result.slots = {"k": "v"}
        recognizer_result.all_matched_tools = ["t1"]

        nr = SimpleNamespace(
            recognizer_result=recognizer_result,
            reflex_used=False,
            intent="something",
            confidence=0.5,
            entities={},
        )

        out = host._convert_neuro_intent_bridge(nr)
        assert out["primary_intent"] == "products"
        assert out["tool_key"] == "products"
        assert out["intent_source"] == "neuro_unified"
        assert out["slots"] == {"k": "v"}

    def test_reflex_used_valid_reflex_type(self) -> None:
        host = _IntentHost()
        nr = SimpleNamespace(
            recognizer_result=None,
            reflex_used=True,
            intent="greeting",  # valid ReflexType
            confidence=0.95,
            entities={"response": "您好"},
        )
        out = host._convert_neuro_intent_bridge(nr)
        # reflex_match_to_chat_intent_dict sets is_greeting True for GREETING
        assert out["intent_source"] == "neuro_reflex"
        assert out["is_greeting"] is True
        assert out["slots"]["reflex_response"] == "您好"

    def test_reflex_used_invalid_reflex_type_falls_to_unknown(self) -> None:
        host = _IntentHost()
        nr = SimpleNamespace(
            recognizer_result=None,
            reflex_used=True,
            intent="not_a_valid_reflex_type",
            confidence=0.42,
            entities={"response": "fallback"},
        )
        out = host._convert_neuro_intent_bridge(nr)
        # ReflexType("not_a_valid_reflex_type") raises ValueError → UNKNOWN
        assert out["intent_source"] == "neuro_reflex"
        # UNKNOWN is neither greeting/help/confirmation/denial
        assert out["is_greeting"] is False
        assert out["is_help"] is False
        assert out["is_confirmation"] is False
        assert out["is_negated"] is False

    def test_reflex_used_emergency_stop(self) -> None:
        host = _IntentHost()
        nr = SimpleNamespace(
            recognizer_result=None,
            reflex_used=True,
            intent="emergency_stop",
            confidence=1.0,
            entities={"response": "已停止"},
        )
        out = host._convert_neuro_intent_bridge(nr)
        assert out["intent_source"] == "neuro_reflex"
        assert "emergency_stop" in out["intent_hints"]

    def test_fallback_branch_no_recognizer_no_reflex(self) -> None:
        host = _IntentHost()
        nr = SimpleNamespace(
            recognizer_result=None,
            reflex_used=False,
            intent="custom_intent",
            confidence=0.3,
            entities={"slot_a": "val_a", "slot_b": "val_b"},
        )
        out = host._convert_neuro_intent_bridge(nr)
        assert out["intent_source"] == "neuro_fallback"
        assert out["primary_intent"] == "custom_intent"
        assert out["final_intent"] == "custom_intent"
        assert out["tool_key"] is None
        assert out["intent_hints"] == []
        assert out["is_negated"] is False
        assert out["is_greeting"] is False
        assert out["is_goodbye"] is False
        assert out["is_help"] is False
        assert out["is_confirmation"] is False
        assert out["is_negation_intent"] is False
        assert out["is_likely_unclear"] is True
        assert out["slots"] == {"slot_a": "val_a", "slot_b": "val_b"}
        assert out["all_matched_tools"] == []

    def test_fallback_branch_none_entities(self) -> None:
        host = _IntentHost()
        nr = SimpleNamespace(
            recognizer_result=None,
            reflex_used=False,
            intent="x",
            confidence=0.1,
            entities=None,
        )
        out = host._convert_neuro_intent_bridge(nr)
        assert out["slots"] == {}
        assert out["intent_source"] == "neuro_fallback"

    def test_reflex_used_with_none_entities(self) -> None:
        host = _IntentHost()
        nr = SimpleNamespace(
            recognizer_result=None,
            reflex_used=True,
            intent="confirmation",
            confidence=0.9,
            entities=None,
        )
        out = host._convert_neuro_intent_bridge(nr)
        # str((nr.entities or {}).get("response", "")) → ""
        assert out["intent_source"] == "neuro_reflex"
        assert out["is_confirmation"] is True
        assert out["slots"]["reflex_response"] == ""


# ===========================================================================
# IntentMixin._recognize_intent (async, integration-style with mocks)
# ===========================================================================


class TestRecognizeIntent:
    @pytest.mark.asyncio
    async def test_offline_mode_uses_offline_service(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Disable neuro stack to skip reflex path
        monkeypatch.setenv("XCAGI_NEURO_INTENT", "0")
        host = _IntentHost()
        host.user_preference_service.get_preference.return_value = "offline"
        host.offline_intent_service = AsyncMock(
            recognize=AsyncMock(return_value={"primary_intent": "products"})
        )

        out = await host._recognize_intent("查询产品", source="web", user_id="u1")
        host.offline_intent_service.recognize.assert_awaited_once_with("查询产品")
        assert out["primary_intent"] == "products"
        assert out["ai_mode"] == "offline"

    @pytest.mark.asyncio
    async def test_pro_source_with_neuro_uses_unified_recognizer(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("XCAGI_NEURO_INTENT", "1")
        host = _IntentHost()
        host.user_preference_service.get_preference.return_value = "online"

        recognizer_result = MagicMock()
        recognizer_result.primary_intent = "shipment_generate"
        recognizer_result.tool_key = "shipment_generate"
        recognizer_result.intent_hints = []
        recognizer_result.is_negated = False
        recognizer_result.is_greeting = False
        recognizer_result.is_goodbye = False
        recognizer_result.is_help = False
        recognizer_result.is_confirmation = False
        recognizer_result.is_negation_intent = False
        recognizer_result.is_likely_unclear = False
        recognizer_result.slots = {}
        recognizer_result.all_matched_tools = []

        # NeuroIntentRecognizer.recognize returns NeuroIntentResult-like
        neuro_r = SimpleNamespace(
            recognizer_result=recognizer_result,
            reflex_used=False,
            intent="shipment_generate",
            confidence=0.9,
            entities={},
        )

        mock_neuro_recognizer = MagicMock()
        mock_neuro_recognizer.recognize.return_value = neuro_r

        with patch(
            "app.neuro_bus.integrations.intent_integration.get_neuro_intent_recognizer",
            return_value=mock_neuro_recognizer,
        ):
            out = await host._recognize_intent(
                "生成发货单", source="pro", user_id="u1"
            )

        assert out["primary_intent"] == "shipment_generate"
        assert out["intent_source"] == "neuro_unified"
        assert out["ai_mode"] == "online"

    @pytest.mark.asyncio
    async def test_pro_source_without_neuro_uses_unified_recognizer(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("XCAGI_NEURO_INTENT", "0")
        host = _IntentHost()
        host.user_preference_service.get_preference.return_value = "online"

        recognizer_result = MagicMock()
        recognizer_result.primary_intent = "products"
        recognizer_result.tool_key = "products"
        recognizer_result.intent_hints = []
        recognizer_result.is_negated = False
        recognizer_result.is_greeting = False
        recognizer_result.is_goodbye = False
        recognizer_result.is_help = False
        recognizer_result.is_confirmation = False
        recognizer_result.is_negation_intent = False
        recognizer_result.is_likely_unclear = False
        recognizer_result.slots = {}
        recognizer_result.all_matched_tools = []

        host.unified_recognizer.recognize.return_value = recognizer_result

        out = await host._recognize_intent(
            "查产品", source="pro", user_id="u1"
        )

        host.unified_recognizer.recognize.assert_called_once()
        assert out["primary_intent"] == "products"
        assert out["intent_source"] == "unified_recognizer"

    @pytest.mark.asyncio
    async def test_rule_only_fast_path(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("XCAGI_NEURO_INTENT", "0")
        monkeypatch.setenv("XCAGI_SKIP_INTENT_LLM", "1")
        host = _IntentHost()
        host.user_preference_service.get_preference.return_value = "online"
        host.intent_service = MagicMock(
            return_value={"primary_intent": "greet", "is_greeting": True}
        )

        out = await host._recognize_intent("你好", source="web", user_id="u1")
        assert out["primary_intent"] == "greet"
        assert out["is_greeting"] is True
        assert out["intent_source"] == "rule_only_fast"

    @pytest.mark.asyncio
    async def test_online_mode_uses_online_service(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("XCAGI_NEURO_INTENT", "0")
        monkeypatch.delenv("XCAGI_SKIP_INTENT_LLM", raising=False)
        host = _IntentHost()
        host.user_preference_service.get_preference.return_value = "online"
        host.online_intent_service = AsyncMock(
            recognize=AsyncMock(
                return_value={"primary_intent": "products", "tool_key": "products"}
            )
        )

        out = await host._recognize_intent("产品", source="web", user_id="u1")
        host.online_intent_service.recognize.assert_awaited_once_with("产品")
        assert out["primary_intent"] == "products"

    @pytest.mark.asyncio
    async def test_neuro_reflex_early_hit_non_pro(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("XCAGI_NEURO_INTENT", "1")
        host = _IntentHost()
        host.user_preference_service.get_preference.return_value = "online"

        reflex_payload = {
            "primary_intent": "greeting",
            "intent_source": "neuro_reflex",
            "is_greeting": True,
        }

        with patch(
            "app.neuro_bus.integrations.intent_integration.try_neuro_reflex_intent",
            return_value=reflex_payload,
        ):
            out = await host._recognize_intent("你好", source="web", user_id="u1")

        assert out["primary_intent"] == "greeting"
        assert out["intent_source"] == "neuro_reflex"
        assert out["ai_mode"] == "online"

    @pytest.mark.asyncio
    async def test_pro_source_skips_early_reflex(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Even with neuro stack on, pro source should NOT take the early
        # reflex path; it goes through the pro-mode branch instead.
        monkeypatch.setenv("XCAGI_NEURO_INTENT", "0")
        host = _IntentHost()
        host.user_preference_service.get_preference.return_value = "online"

        recognizer_result = MagicMock()
        recognizer_result.primary_intent = "products"
        recognizer_result.tool_key = "products"
        recognizer_result.intent_hints = []
        recognizer_result.is_negated = False
        recognizer_result.is_greeting = False
        recognizer_result.is_goodbye = False
        recognizer_result.is_help = False
        recognizer_result.is_confirmation = False
        recognizer_result.is_negation_intent = False
        recognizer_result.is_likely_unclear = False
        recognizer_result.slots = {}
        recognizer_result.all_matched_tools = []
        host.unified_recognizer.recognize.return_value = recognizer_result

        with patch(
            "app.neuro_bus.integrations.intent_integration.try_neuro_reflex_intent",
            return_value={"primary_intent": "should_not_be_used"},
        ) as mock_reflex:
            out = await host._recognize_intent(
                "产品", source="pro", user_id="u1"
            )

        mock_reflex.assert_not_called()
        assert out["primary_intent"] == "products"


# ===========================================================================
# HandlersMixin._check_hard_rules (additional branches)
# ===========================================================================


class TestCheckHardRules:
    @pytest.mark.parametrize(
        "message,action_type",
        [
            ("导出excel", "export_customers_xlsx"),
            ("导出xlsx", "export_customers_xlsx"),
            ("导出表格", "export_customers_xlsx"),
            ("导出用户列表", "export_customers_xlsx"),
            ("导出客户列表", "export_customers_xlsx"),
            ("导出购买单位", "export_customers_xlsx"),
            ("导出单位", "export_customers_xlsx"),
            ("导出客户", "export_customers_xlsx"),  # export_with_context branch
            ("导出名单", "export_customers_xlsx"),
            ("进入工作模式", "set_work_mode"),
            ("开启工作模式", "set_work_mode"),
            ("打开工作模式", "set_work_mode"),
            ("开始工作模式", "set_work_mode"),
            ("启动工作模式", "set_work_mode"),
            ("工作模式", "set_work_mode"),
            ("退出工作模式", "set_work_mode"),
            ("关闭工作模式", "set_work_mode"),
            ("停止工作模式", "set_work_mode"),
            ("结束工作模式", "set_work_mode"),
            ("购买单位列表", "show_customers"),
            ("客户列表", "show_customers"),
            ("查看客户", "show_customers"),
            ("查看用户列表", "show_customers"),
            ("用户列表", "show_customers"),
            ("用户名单", "show_customers"),
            ("客户名单", "show_customers"),
            ("单位列表", "show_customers"),
            ("产品列表", "show_products"),
            ("产品库", "show_products"),
            ("商品列表", "show_products"),
            ("查看产品", "show_products"),
            ("监控模式", "show_monitor"),
            ("进入监控模式", "show_monitor"),
            ("开启监控模式", "show_monitor"),
            ("打开监控模式", "show_monitor"),
        ],
    )
    def test_hard_rule_hits(self, message: str, action_type: str) -> None:
        svc = _HandlerHost()
        out = svc._check_hard_rules(message)
        assert out is not None
        assert out["action"] == "auto_action"
        assert out["data"]["type"] == action_type

    def test_work_mode_enabled_flag(self) -> None:
        svc = _HandlerHost()
        out = svc._check_hard_rules("进入工作模式")
        assert out["data"]["enabled"] is True

    def test_work_mode_disabled_flag(self) -> None:
        svc = _HandlerHost()
        out = svc._check_hard_rules("退出工作模式")
        assert out["data"]["enabled"] is False

    def test_no_match_returns_none(self) -> None:
        svc = _HandlerHost()
        assert svc._check_hard_rules("今天天气怎么样") is None
        assert svc._check_hard_rules("") is None
        assert svc._check_hard_rules("  ") is None
        # "工作模式" with no enter/exit keyword but exactly "工作模式" hits enter branch
        # so test a phrase that mentions 工作模式 but neither enters nor exits
        assert svc._check_hard_rules("工作模式是什么") is None

    def test_export_with_context_only(self) -> None:
        # "导出" + "客户" but no exact export keyword → export_with_context branch
        svc = _HandlerHost()
        out = svc._check_hard_rules("请导出客户数据")
        assert out is not None
        assert out["data"]["type"] == "export_customers_xlsx"

    def test_export_no_context_no_hit(self) -> None:
        # "导出" alone with no context keyword and no exact export keyword
        svc = _HandlerHost()
        assert svc._check_hard_rules("导出图片") is None

    def test_strips_whitespace(self) -> None:
        svc = _HandlerHost()
        out = svc._check_hard_rules("  导出excel  ")
        assert out is not None
        assert out["data"]["type"] == "export_customers_xlsx"


# ===========================================================================
# HandlersMixin._handle_greeting / _handle_goodbye / _handle_help
# ===========================================================================


class TestHandleGreetingGoodbyeHelp:
    @pytest.mark.asyncio
    async def test_greeting_adds_to_history(self) -> None:
        svc = _HandlerHost()
        ctx = ConversationContext(user_id="u1")
        out = await svc._handle_greeting("你好", ctx)
        assert out["action"] == "greeting"
        # Greeting text rotates by hash(message) % len(responses); all three
        # variants share common markers.
        assert "您好" in out["text"] or "你好" in out["text"] or "欢迎" in out["text"]
        assert len(svc.history) == 2  # user + assistant
        assert svc.history[0][0] == "u1"
        assert svc.history[0][1] == "user"
        assert svc.history[1][1] == "assistant"

    @pytest.mark.asyncio
    async def test_goodbye_adds_to_history(self) -> None:
        svc = _HandlerHost()
        ctx = ConversationContext(user_id="u2")
        out = await svc._handle_goodbye("再见", ctx)
        assert out["action"] == "goodbye"
        assert "再见" in out["text"] or "拜拜" in out["text"] or "期待" in out["text"]
        assert len(svc.history) == 2

    @pytest.mark.asyncio
    async def test_help_adds_to_history(self) -> None:
        svc = _HandlerHost()
        ctx = ConversationContext(user_id="u3")
        out = await svc._handle_help("帮助", ctx)
        assert out["action"] == "help"
        assert "发货单" in out["text"]
        assert len(svc.history) == 2

    @pytest.mark.asyncio
    async def test_greeting_deterministic_for_same_message(self) -> None:
        svc1 = _HandlerHost()
        svc2 = _HandlerHost()
        ctx1 = ConversationContext(user_id="u1")
        ctx2 = ConversationContext(user_id="u2")
        out1 = await svc1._handle_greeting("你好", ctx1)
        out2 = await svc2._handle_greeting("你好", ctx2)
        assert out1["text"] == out2["text"]


# ===========================================================================
# HandlersMixin._handle_special_intents (orchestrator)
# ===========================================================================


class TestHandleSpecialIntents:
    @pytest.mark.asyncio
    async def test_greeting_short_circuits(self) -> None:
        svc = _HandlerHost()
        ctx = ConversationContext(user_id="u1")
        intent = {"is_greeting": True}
        out = await svc._handle_special_intents("你好", intent, ctx, "u1")
        assert out is not None
        assert out["action"] == "greeting"

    @pytest.mark.asyncio
    async def test_goodbye_short_circuits(self) -> None:
        svc = _HandlerHost()
        ctx = ConversationContext(user_id="u1")
        intent = {"is_goodbye": True}
        out = await svc._handle_special_intents("再见", intent, ctx, "u1")
        assert out is not None
        assert out["action"] == "goodbye"

    @pytest.mark.asyncio
    async def test_help_short_circuits(self) -> None:
        svc = _HandlerHost()
        ctx = ConversationContext(user_id="u1")
        intent = {"is_help": True}
        out = await svc._handle_special_intents("帮助", intent, ctx, "u1")
        assert out is not None
        assert out["action"] == "help"

    @pytest.mark.asyncio
    async def test_hard_rule_short_circuits(self) -> None:
        svc = _HandlerHost()
        ctx = ConversationContext(user_id="u1")
        intent: dict[str, Any] = {}
        out = await svc._handle_special_intents("导出excel", intent, ctx, "u1")
        assert out is not None
        assert out["action"] == "auto_action"
        assert out["data"]["type"] == "export_customers_xlsx"

    @pytest.mark.asyncio
    async def test_no_special_intent_returns_none(self) -> None:
        svc = _HandlerHost()
        ctx = ConversationContext(user_id="u1")
        intent: dict[str, Any] = {}
        out = await svc._handle_special_intents("今天天气", intent, ctx, "u1")
        assert out is None


# ===========================================================================
# HandlersMixin._handle_confirmation_intent
# ===========================================================================


class TestHandleConfirmationIntent:
    @pytest.mark.asyncio
    async def test_not_confirmation_returns_none(self) -> None:
        svc = _HandlerHost()
        ctx = ConversationContext(user_id="u1")
        out = await svc._handle_confirmation_intent(
            "好的", {"is_confirmation": False}, ctx, "u1"
        )
        assert out is None

    @pytest.mark.asyncio
    async def test_confirmation_no_pending_returns_none(self) -> None:
        svc = _HandlerHost()
        svc.confirmation_service.get_pending_intent.return_value = None
        ctx = ConversationContext(user_id="u1")
        out = await svc._handle_confirmation_intent(
            "好的", {"is_confirmation": True}, ctx, "u1"
        )
        assert out is None

    @pytest.mark.asyncio
    async def test_confirmation_with_pending_tool_key(self) -> None:
        svc = _HandlerHost()
        pending = {
            "intent": "shipment_generate",
            "tool_key": "shipment_generate",
            "params": {"unit_name": "甲公司"},
            "type": "shipment_generate",
        }
        svc.confirmation_service.get_pending_intent.return_value = pending
        ctx = ConversationContext(user_id="u1")

        out = await svc._handle_confirmation_intent(
            "好的", {"is_confirmation": True}, ctx, "u1"
        )

        assert out is not None
        assert out["action"] == "tool_call"
        assert out["data"]["tool_key"] == "shipment_generate"
        assert out["data"]["from_pending_confirmation"] is True
        assert out["data"]["params"] == {"unit_name": "甲公司"}
        assert ctx.last_action == "confirmed_shipment_generate"
        assert ctx.pending_confirmation is None
        svc.confirmation_service.clear_pending_intent.assert_called_once_with("u1")
        # feedback + action recorded
        assert len(svc.feedback) == 1
        assert svc.feedback[0]["feedback"] == "confirmed"
        assert len(svc.actions) == 1

    @pytest.mark.asyncio
    async def test_confirmation_uses_context_pending_when_service_empty(self) -> None:
        svc = _HandlerHost()
        svc.confirmation_service.get_pending_intent.return_value = None
        ctx = ConversationContext(user_id="u1")
        ctx.pending_confirmation = {
            "intent": "products",
            "tool_key": "products",
            "slots": {"keyword": "漆"},
        }

        out = await svc._handle_confirmation_intent(
            "对的", {"is_confirmation": True}, ctx, "u1"
        )

        assert out is not None
        assert out["data"]["tool_key"] == "products"
        # params falls back to slots
        assert out["data"]["params"] == {"keyword": "漆"}

    @pytest.mark.asyncio
    async def test_confirmation_pending_without_tool_key_returns_none(self) -> None:
        svc = _HandlerHost()
        # Neither tool_key nor intent → tool_key falsy → returns None
        pending = {"type": "unknown_type"}
        svc.confirmation_service.get_pending_intent.return_value = pending
        ctx = ConversationContext(user_id="u1")

        out = await svc._handle_confirmation_intent(
            "好的", {"is_confirmation": True}, ctx, "u1"
        )

        assert out is None
        # Still clears pending + records feedback
        svc.confirmation_service.clear_pending_intent.assert_called_once_with("u1")
        assert ctx.pending_confirmation is None

    @pytest.mark.asyncio
    async def test_confirmation_pending_uses_intent_when_no_type(self) -> None:
        svc = _HandlerHost()
        pending = {
            "intent": "customers",
            "tool_key": "customers",
            # no "type" key → action_type falls back to intent
        }
        svc.confirmation_service.get_pending_intent.return_value = pending
        ctx = ConversationContext(user_id="u1")

        out = await svc._handle_confirmation_intent(
            "确认", {"is_confirmation": True}, ctx, "u1"
        )

        assert out is not None
        assert ctx.last_action == "confirmed_customers"
        # params falls back to slots (empty)
        assert out["data"]["params"] == {}


# ===========================================================================
# HandlersMixin._handle_negation_intent
# ===========================================================================


class TestHandleNegationIntent:
    @pytest.mark.asyncio
    async def test_not_negated_returns_none(self) -> None:
        svc = _HandlerHost()
        ctx = ConversationContext(user_id="u1")
        out = await svc._handle_negation_intent(
            "好的", {"is_negated": False, "is_negation_intent": False}, ctx, "u1"
        )
        assert out is None

    @pytest.mark.asyncio
    async def test_negated_with_pending_clears_and_returns_none(self) -> None:
        svc = _HandlerHost()
        ctx = ConversationContext(user_id="u1")
        ctx.pending_confirmation = {
            "intent": "shipment_generate",
            "slots": {"unit_name": "甲"},
        }

        out = await svc._handle_negation_intent(
            "不要", {"is_negated": True}, ctx, "u1"
        )

        assert out is None
        assert ctx.pending_confirmation is None
        assert len(svc.feedback) == 1
        assert svc.feedback[0]["feedback"] == "negated"
        assert svc.feedback[0]["recognized_intent"] == "shipment_generate"

    @pytest.mark.asyncio
    async def test_negation_intent_no_pending_short_message(self) -> None:
        svc = _HandlerHost()
        ctx = ConversationContext(user_id="u1")
        ctx.current_intent = "products"

        out = await svc._handle_negation_intent(
            "不要", {"is_negation_intent": True}, ctx, "u1"
        )

        assert out is not None
        assert out["action"] == "negated"
        assert ctx.last_action == "user_negated"
        assert len(svc.feedback) == 1

    @pytest.mark.asyncio
    async def test_negation_intent_no_pending_long_message_returns_none(self) -> None:
        svc = _HandlerHost()
        ctx = ConversationContext(user_id="u1")
        long_message = "这是一个非常长的否定消息超过十个字符"
        assert len(long_message) >= 10

        out = await svc._handle_negation_intent(
            long_message, {"is_negation_intent": True}, ctx, "u1"
        )

        assert out is None

    @pytest.mark.asyncio
    async def test_negation_intent_with_pending_does_not_short_circuit(self) -> None:
        # When pending_confirmation is set AND is_negation_intent is True,
        # the first branch (is_negated + pending) is False (is_negated False),
        # and the second branch requires no pending_confirmation → returns None.
        svc = _HandlerHost()
        ctx = ConversationContext(user_id="u1")
        ctx.pending_confirmation = {"intent": "x"}

        out = await svc._handle_negation_intent(
            "不要", {"is_negation_intent": True, "is_negated": False}, ctx, "u1"
        )

        assert out is None

    @pytest.mark.asyncio
    async def test_negation_intent_with_last_intent_result_slots(self) -> None:
        svc = _HandlerHost()
        ctx = ConversationContext(user_id="u1")
        ctx.current_intent = "shipment_generate"
        ctx.last_intent_result = {"slots": {"unit_name": "甲公司"}}

        out = await svc._handle_negation_intent(
            "不要", {"is_negation_intent": True}, ctx, "u1"
        )

        assert out is not None
        assert svc.feedback[0]["slots"] == {"unit_name": "甲公司"}

    @pytest.mark.asyncio
    async def test_negation_intent_no_current_intent_no_last_result(self) -> None:
        svc = _HandlerHost()
        ctx = ConversationContext(user_id="u1")
        # current_intent None, last_intent_result None

        out = await svc._handle_negation_intent(
            "不要", {"is_negation_intent": True}, ctx, "u1"
        )

        assert out is not None
        assert svc.feedback[0]["recognized_intent"] == ""
        assert svc.feedback[0]["slots"] == {}


# ===========================================================================
# HandlersMixin._handle_pending_intent
# ===========================================================================


class TestHandlePendingIntent:
    @pytest.mark.asyncio
    async def test_no_pending_returns_none(self) -> None:
        svc = _HandlerHost()
        svc.confirmation_service.get_pending_intent.return_value = None
        ctx = ConversationContext(user_id="u1")
        out = await svc._handle_pending_intent(
            "hello", {"primary_intent": "x"}, ctx, "u1"
        )
        assert out is None

    @pytest.mark.asyncio
    async def test_pending_with_greeting_clears_and_returns_none(self) -> None:
        svc = _HandlerHost()
        pending = {"intent": "shipment_generate"}
        svc.confirmation_service.get_pending_intent.return_value = pending
        ctx = ConversationContext(user_id="u1")

        out = await svc._handle_pending_intent(
            "你好", {"is_greeting": True}, ctx, "u1"
        )

        assert out is None
        svc.confirmation_service.clear_pending_intent.assert_called_once_with("u1")

    @pytest.mark.asyncio
    async def test_pending_with_goodbye_clears_and_returns_none(self) -> None:
        svc = _HandlerHost()
        pending = {"intent": "shipment_generate"}
        svc.confirmation_service.get_pending_intent.return_value = pending
        ctx = ConversationContext(user_id="u1")

        out = await svc._handle_pending_intent(
            "再见", {"is_goodbye": True}, ctx, "u1"
        )

        assert out is None
        svc.confirmation_service.clear_pending_intent.assert_called_once_with("u1")

    @pytest.mark.asyncio
    async def test_pending_with_help_clears_and_returns_none(self) -> None:
        svc = _HandlerHost()
        pending = {"intent": "shipment_generate"}
        svc.confirmation_service.get_pending_intent.return_value = pending
        ctx = ConversationContext(user_id="u1")

        out = await svc._handle_pending_intent(
            "帮助", {"is_help": True}, ctx, "u1"
        )

        assert out is None
        svc.confirmation_service.clear_pending_intent.assert_called_once_with("u1")

    @pytest.mark.asyncio
    async def test_pending_new_tool_key_different_clears(self) -> None:
        svc = _HandlerHost()
        pending = {"intent": "shipment_generate"}
        svc.confirmation_service.get_pending_intent.return_value = pending
        ctx = ConversationContext(user_id="u1")

        out = await svc._handle_pending_intent(
            "查询产品",
            {"tool_key": "products", "primary_intent": "products"},
            ctx,
            "u1",
        )

        assert out is None
        svc.confirmation_service.clear_pending_intent.assert_called_once_with("u1")

    @pytest.mark.asyncio
    async def test_pending_same_tool_key_fills_slots(self) -> None:
        svc = _HandlerHost()
        pending = {"intent": "shipment_generate"}
        svc.confirmation_service.get_pending_intent.return_value = pending
        svc.intent_service = MagicMock(return_value={"slots": {"unit_name": "甲"}})
        svc.confirmation_service.merge_slots.return_value = {"unit_name": "甲"}
        svc.confirmation_service.check_and_build_prompt.return_value = {
            "status": "complete",
            "missing_slots": [],
        }
        ctx = ConversationContext(user_id="u1")

        out = await svc._handle_pending_intent(
            "给甲公司",
            {"tool_key": "shipment_generate", "primary_intent": "shipment_generate"},
            ctx,
            "u1",
        )

        assert out is not None
        assert out["action"] == "tool_call"
        assert out["data"]["tool_key"] == "shipment_generate"
        assert out["data"]["slots"] == {"unit_name": "甲"}

    @pytest.mark.asyncio
    async def test_pending_incomplete_returns_slot_fill(self) -> None:
        svc = _HandlerHost()
        pending = {"intent": "shipment_generate"}
        svc.confirmation_service.get_pending_intent.return_value = pending
        svc.intent_service = MagicMock(return_value={"slots": {}})
        svc.confirmation_service.merge_slots.return_value = {}
        svc.confirmation_service.check_and_build_prompt.return_value = {
            "status": "missing_slots",
            "missing_slots": ["unit_name"],
            "question": "请告诉我客户名称",
        }
        ctx = ConversationContext(user_id="u1")

        out = await svc._handle_pending_intent(
            "生成发货单",
            {"tool_key": "shipment_generate"},
            ctx,
            "u1",
        )

        assert out is not None
        assert out["action"] == "slot_fill"
        assert out["data"]["missing_slots"] == ["unit_name"]
        assert out["text"] == "请告诉我客户名称"

    @pytest.mark.asyncio
    async def test_pending_no_tool_key_fills_slots(self) -> None:
        # No current_tool_key in intent_result → falls through to _fill_pending_slots
        svc = _HandlerHost()
        pending = {"intent": "products"}
        svc.confirmation_service.get_pending_intent.return_value = pending
        svc.intent_service = MagicMock(return_value={"slots": {"keyword": "漆"}})
        svc.confirmation_service.merge_slots.return_value = {"keyword": "漆"}
        svc.confirmation_service.check_and_build_prompt.return_value = {
            "status": "complete",
            "missing_slots": [],
        }
        ctx = ConversationContext(user_id="u1")

        out = await svc._handle_pending_intent(
            "查漆", {"primary_intent": "products"}, ctx, "u1"
        )

        assert out is not None
        assert out["action"] == "tool_call"


# ===========================================================================
# HandlersMixin._build_pending_complete_response / _build_pending_incomplete_response
# ===========================================================================


class TestBuildPendingResponses:
    def test_complete_response_shipment_generate(self) -> None:
        svc = _HandlerHost()
        pending = {"intent": "shipment_generate"}
        merged_slots = {"unit_name": "甲公司"}
        out = svc._build_pending_complete_response(pending, merged_slots, "u1")
        assert out["action"] == "tool_call"
        assert "甲公司" in out["text"]
        assert out["data"]["tool_key"] == "shipment_generate"
        svc.confirmation_service.set_pending_intent.assert_called_once()

    def test_complete_response_products(self) -> None:
        svc = _HandlerHost()
        pending = {"intent": "products"}
        merged_slots = {"unit_name": "甲", "keyword": "漆"}
        out = svc._build_pending_complete_response(pending, merged_slots, "u1")
        assert out["action"] == "tool_call"
        # products action text uses unit_name or keyword
        assert "甲" in out["text"] or "漆" in out["text"]

    def test_complete_response_customers(self) -> None:
        svc = _HandlerHost()
        pending = {"intent": "customers"}
        out = svc._build_pending_complete_response(pending, {}, "u1")
        assert "客户" in out["text"]

    def test_complete_response_shipments(self) -> None:
        svc = _HandlerHost()
        pending = {"intent": "shipments"}
        out = svc._build_pending_complete_response(pending, {}, "u1")
        assert "发货" in out["text"]

    def test_complete_response_print_label(self) -> None:
        svc = _HandlerHost()
        pending = {"intent": "print_label"}
        out = svc._build_pending_complete_response(pending, {}, "u1")
        assert "标签" in out["text"]

    def test_complete_response_wechat_send(self) -> None:
        svc = _HandlerHost()
        pending = {"intent": "wechat_send"}
        out = svc._build_pending_complete_response(pending, {}, "u1")
        assert "微信" in out["text"]

    def test_complete_response_upload_file(self) -> None:
        svc = _HandlerHost()
        pending = {"intent": "upload_file"}
        out = svc._build_pending_complete_response(pending, {}, "u1")
        assert "上传" in out["text"]

    def test_complete_response_unknown_intent_default_text(self) -> None:
        svc = _HandlerHost()
        pending = {"intent": "custom_intent"}
        out = svc._build_pending_complete_response(pending, {}, "u1")
        assert "custom_intent" in out["text"]

    def test_complete_response_no_intent_key(self) -> None:
        svc = _HandlerHost()
        pending = {}  # no "intent" key
        out = svc._build_pending_complete_response(pending, {}, "u1")
        assert out["action"] == "tool_call"
        # pending.get("intent") → None → action_text default
        # tool_key is None
        assert out["data"]["tool_key"] is None

    def test_incomplete_response(self) -> None:
        svc = _HandlerHost()
        pending = {"intent": "shipment_generate"}
        merged_slots = {"unit_name": "甲"}
        check_result = {
            "missing_slots": ["product_name"],
            "question": "请告诉我产品名称",
        }
        out = svc._build_pending_incomplete_response(
            pending, merged_slots, check_result, "u1"
        )
        assert out["action"] == "slot_fill"
        assert out["text"] == "请告诉我产品名称"
        assert out["data"]["missing_slots"] == ["product_name"]
        assert out["data"]["slots"] == {"unit_name": "甲"}
        svc.confirmation_service.set_pending_intent.assert_called_once_with(
            "u1",
            {
                "intent": "shipment_generate",
                "slots": {"unit_name": "甲"},
                "missing_slots": ["product_name"],
            },
        )


# ===========================================================================
# HandlersMixin._fill_pending_slots
# ===========================================================================


class TestFillPendingSlots:
    @pytest.mark.asyncio
    async def test_complete_path(self) -> None:
        svc = _HandlerHost()
        pending = {"intent": "shipment_generate"}
        svc.intent_service = MagicMock(return_value={"slots": {"unit_name": "甲"}})
        svc.confirmation_service.merge_slots.return_value = {"unit_name": "甲"}
        svc.confirmation_service.check_and_build_prompt.return_value = {
            "status": "complete",
            "missing_slots": [],
        }

        out = await svc._fill_pending_slots("给甲公司", pending, "u1")

        assert out["action"] == "tool_call"
        svc.intent_service.assert_called_once_with("给甲公司")
        svc.confirmation_service.merge_slots.assert_called_once_with(
            "u1", {"unit_name": "甲"}
        )

    @pytest.mark.asyncio
    async def test_incomplete_path(self) -> None:
        svc = _HandlerHost()
        pending = {"intent": "shipment_generate"}
        svc.intent_service = MagicMock(return_value={"slots": {}})
        svc.confirmation_service.merge_slots.return_value = {}
        svc.confirmation_service.check_and_build_prompt.return_value = {
            "status": "missing_slots",
            "missing_slots": ["unit_name"],
            "question": "请告诉我客户名称",
        }

        out = await svc._fill_pending_slots("生成发货单", pending, "u1")

        assert out["action"] == "slot_fill"
        assert out["text"] == "请告诉我客户名称"

    @pytest.mark.asyncio
    async def test_intent_service_returns_no_slots_key(self) -> None:
        svc = _HandlerHost()
        pending = {"intent": "products"}
        svc.intent_service = MagicMock(return_value={"primary_intent": "products"})
        svc.confirmation_service.merge_slots.return_value = {}
        svc.confirmation_service.check_and_build_prompt.return_value = {
            "status": "complete",
            "missing_slots": [],
        }

        out = await svc._fill_pending_slots("查产品", pending, "u1")

        # Should still work — .get("slots", {}) handles missing key
        assert out["action"] == "tool_call"
        svc.confirmation_service.merge_slots.assert_called_once_with("u1", {})
