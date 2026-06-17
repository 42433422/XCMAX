"""Comprehensive tests for app.domain.services.conversation.context.context_facade.

Covers: ContextFacade.process, _make_decision, all handler methods,
update_pending_with_slots, confirm_pending, cancel_pending, get_context_summary,
ContextFacadeContainer, and all helper methods.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.domain.services.conversation.context.context_facade import (
    ContextDecision,
    ContextFacade,
    ContextFacadeContainer,
    IntentResult,
    ProcessingAction,
    ProcessingResult,
    get_context_facade,
)
from app.domain.services.conversation.context.intent_context import (
    AdoptionReason,
    PendingIntent,
)


# ---------------------------------------------------------------------------
# IntentResult
# ---------------------------------------------------------------------------


class TestIntentResult:
    def test_defaults(self):
        r = IntentResult(primary_intent=None, tool_key=None, slots={})
        assert r.is_greeting is False
        assert r.is_goodbye is False
        assert r.is_help is False
        assert r.is_confirmation is False
        assert r.is_negation_intent is False
        assert r.is_negated is False
        assert r.confidence == 0.0
        assert r.source == "unknown"


# ---------------------------------------------------------------------------
# ProcessingResult
# ---------------------------------------------------------------------------


class TestProcessingResult:
    def test_defaults(self):
        r = ProcessingResult(action=ProcessingAction.AI_RESPONSE, text="hi", data={})
        assert r.pending_intent is None
        assert r.is_duplicate is False
        assert r.cached_response is None


# ---------------------------------------------------------------------------
# ContextFacade — process: duplicate detection
# ---------------------------------------------------------------------------


class TestProcessDuplicate:
    def test_exact_duplicate_returns_cached(self):
        mock_ic = MagicMock()
        mock_cc = MagicMock()
        mock_cc.is_duplicate.return_value = (True, "cached response", True)
        facade = ContextFacade(intent_context=mock_ic, chat_context=mock_cc)

        ir = IntentResult(primary_intent="test", tool_key=None, slots={})
        result = facade.process("user1", "hello", ir)
        assert result.action == ProcessingAction.DUPLICATE_RESPONSE
        assert result.is_duplicate is True
        assert result.cached_response == "cached response"

    def test_semantic_duplicate(self):
        mock_ic = MagicMock()
        mock_cc = MagicMock()
        mock_cc.is_duplicate.return_value = (True, "cached", False)
        facade = ContextFacade(intent_context=mock_ic, chat_context=mock_cc)

        ir = IntentResult(primary_intent="test", tool_key=None, slots={})
        result = facade.process("user1", "hello", ir)
        assert result.action == ProcessingAction.DUPLICATE_RESPONSE
        assert result.is_duplicate is True


# ---------------------------------------------------------------------------
# ContextFacade — process: greeting
# ---------------------------------------------------------------------------


class TestProcessGreeting:
    def test_greeting_no_pending(self):
        mock_ic = MagicMock()
        mock_ic.get_pending.return_value = None
        mock_cc = MagicMock()
        mock_cc.is_duplicate.return_value = (False, None, False)
        facade = ContextFacade(intent_context=mock_ic, chat_context=mock_cc)

        ir = IntentResult(primary_intent="greeting", tool_key=None, slots={}, is_greeting=True)
        result = facade.process("user1", "你好", ir)
        assert result.action == ProcessingAction.GREETING
        # Greeting text is selected from a rotating list via hash(message); some
        # variants contain "XCAGI" and some do not. Assert a stable substring.
        assert result.text  # non-empty greeting

    def test_greeting_with_pending(self):
        mock_ic = MagicMock()
        pending = PendingIntent(
            intent="shipment_generate", slots={}, missing_slots=["unit_name"], source="test"
        )
        mock_ic.get_pending.return_value = pending
        mock_cc = MagicMock()
        mock_cc.is_duplicate.return_value = (False, None, False)
        facade = ContextFacade(intent_context=mock_ic, chat_context=mock_cc)

        ir = IntentResult(primary_intent="greeting", tool_key=None, slots={}, is_greeting=True)
        with patch.object(facade, "_notify_pending_preserved"):
            result = facade.process("user1", "你好", ir)
        assert result.action == ProcessingAction.GREETING
        assert result.pending_intent is not None


# ---------------------------------------------------------------------------
# ContextFacade — process: goodbye
# ---------------------------------------------------------------------------


class TestProcessGoodbye:
    def test_goodbye(self):
        mock_ic = MagicMock()
        mock_ic.get_pending.return_value = None
        mock_cc = MagicMock()
        mock_cc.is_duplicate.return_value = (False, None, False)
        facade = ContextFacade(intent_context=mock_ic, chat_context=mock_cc)

        ir = IntentResult(primary_intent="goodbye", tool_key=None, slots={}, is_goodbye=True)
        result = facade.process("user1", "再见", ir)
        assert result.action == ProcessingAction.GOODBYE
        assert "再见" in result.text


# ---------------------------------------------------------------------------
# ContextFacade — process: help
# ---------------------------------------------------------------------------


class TestProcessHelp:
    def test_help(self):
        mock_ic = MagicMock()
        mock_ic.get_pending.return_value = None
        mock_cc = MagicMock()
        mock_cc.is_duplicate.return_value = (False, None, False)
        facade = ContextFacade(intent_context=mock_ic, chat_context=mock_cc)

        ir = IntentResult(primary_intent="help", tool_key=None, slots={}, is_help=True)
        result = facade.process("user1", "帮助", ir)
        assert result.action == ProcessingAction.HELP
        assert "XCAGI" in result.text


# ---------------------------------------------------------------------------
# ContextFacade — process: confirmation with pending
# ---------------------------------------------------------------------------


class TestProcessConfirmation:
    def test_confirmed_pending_triggers_tool_call(self):
        mock_ic = MagicMock()
        pending = PendingIntent(intent="shipment_generate", slots={"unit_name": "Co"}, missing_slots=[], source="test")
        mock_ic.get_pending.return_value = pending
        mock_cc = MagicMock()
        mock_cc.is_duplicate.return_value = (False, None, False)
        facade = ContextFacade(intent_context=mock_ic, chat_context=mock_cc)

        ir = IntentResult(primary_intent="shipment_generate", tool_key=None, slots={}, is_confirmation=True)
        result = facade.process("user1", "确认", ir)
        assert result.action == ProcessingAction.TOOL_CALL


# ---------------------------------------------------------------------------
# ContextFacade — process: negation with pending
# ---------------------------------------------------------------------------


class TestProcessNegation:
    def test_negated_with_pending(self):
        mock_ic = MagicMock()
        pending = PendingIntent(intent="shipment_generate", slots={}, missing_slots=["unit_name"], source="test")
        mock_ic.get_pending.return_value = pending
        mock_cc = MagicMock()
        mock_cc.is_duplicate.return_value = (False, None, False)
        facade = ContextFacade(intent_context=mock_ic, chat_context=mock_cc)

        ir = IntentResult(primary_intent="negation", tool_key=None, slots={}, is_negation_intent=True)
        result = facade.process("user1", "取消", ir)
        assert result.action == ProcessingAction.NEGATED
        assert "取消" in result.text


# ---------------------------------------------------------------------------
# ContextFacade — process: slot fill
# ---------------------------------------------------------------------------


class TestProcessSlotFill:
    def test_missing_slots_triggers_slot_fill(self):
        mock_ic = MagicMock()
        mock_ic.get_pending.return_value = None
        mock_cc = MagicMock()
        mock_cc.is_duplicate.return_value = (False, None, False)
        facade = ContextFacade(intent_context=mock_ic, chat_context=mock_cc)

        ir = IntentResult(
            primary_intent="shipment_generate",
            tool_key=None,
            slots={"unit_name": "Co"},
        )
        # The merged intent still has missing slots
        merged_pending = PendingIntent(
            intent="shipment_generate",
            slots={"unit_name": "Co"},
            missing_slots=["model_number", "tin_spec", "quantity_tins"],
            source="test",
        )
        mock_ic.should_adopt_new_intent.return_value = (
            True, AdoptionReason.MERGE_SLOTS, merged_pending
        )
        # merged_slots in decision must reflect the incomplete state
        decision = ContextDecision(
            should_continue=True,
            action=ProcessingAction.SLOT_FILL,
            reason="merged_slots",
            merged_slots={"unit_name": "Co"},  # missing model_number, tin_spec, quantity_tins
            pending_to_preserve=merged_pending,
        )
        with patch.object(facade, "_make_decision", return_value=decision):
            result = facade.process("user1", "发货给Co", ir)
        assert result.action == ProcessingAction.SLOT_FILL


# ---------------------------------------------------------------------------
# ContextFacade — process: tool call (all slots filled)
# ---------------------------------------------------------------------------


class TestProcessToolCall:
    def test_all_slots_filled(self):
        mock_ic = MagicMock()
        mock_ic.get_pending.return_value = None
        mock_cc = MagicMock()
        mock_cc.is_duplicate.return_value = (False, None, False)
        facade = ContextFacade(intent_context=mock_ic, chat_context=mock_cc)

        ir = IntentResult(
            primary_intent="shipment_generate",
            tool_key="shipment_generate",
            slots={"unit_name": "Co", "model_number": "M1", "tin_spec": "S1", "quantity_tins": "10"},
        )
        result = facade.process("user1", "发货", ir)
        assert result.action == ProcessingAction.TOOL_CALL
        assert "发货单" in result.text

    def test_no_intent_falls_to_ai_response(self):
        mock_ic = MagicMock()
        mock_ic.get_pending.return_value = None
        mock_cc = MagicMock()
        mock_cc.is_duplicate.return_value = (False, None, False)
        facade = ContextFacade(intent_context=mock_ic, chat_context=mock_cc)

        ir = IntentResult(primary_intent=None, tool_key=None, slots={})
        result = facade.process("user1", "随机消息", ir)
        assert result.action == ProcessingAction.AI_RESPONSE


# ---------------------------------------------------------------------------
# ContextFacade — process: intent switch query
# ---------------------------------------------------------------------------


class TestProcessIntentSwitch:
    def test_switch_requested(self):
        mock_ic = MagicMock()
        pending = PendingIntent(intent="shipment_generate", slots={}, missing_slots=["unit_name"], source="test")
        mock_ic.get_pending.return_value = pending
        mock_ic.should_adopt_new_intent.return_value = (
            True, AdoptionReason.SWITCH_REQUESTED, pending
        )
        mock_cc = MagicMock()
        mock_cc.is_duplicate.return_value = (False, None, False)
        facade = ContextFacade(intent_context=mock_ic, chat_context=mock_cc)

        ir = IntentResult(primary_intent="product_query", tool_key=None, slots={"keyword": "test"})
        result = facade.process("user1", "查产品", ir)
        assert result.action == ProcessingAction.INTENT_SWITCH_QUERY
        assert "切换" in result.text


# ---------------------------------------------------------------------------
# ContextFacade — process: preserved intent
# ---------------------------------------------------------------------------


class TestProcessPreservedIntent:
    def test_preserved_intent_greeting(self):
        mock_ic = MagicMock()
        pending = PendingIntent(intent="shipment_generate", slots={}, missing_slots=["unit_name"], source="test")
        mock_ic.get_pending.return_value = pending
        mock_ic.should_adopt_new_intent.return_value = (
            False, AdoptionReason.INTENT_PRESERVED, None
        )
        mock_cc = MagicMock()
        mock_cc.is_duplicate.return_value = (False, None, False)
        facade = ContextFacade(intent_context=mock_ic, chat_context=mock_cc)

        ir = IntentResult(primary_intent="greeting", tool_key=None, slots={}, is_greeting=True)
        with patch.object(facade, "_notify_pending_preserved"):
            result = facade.process("user1", "你好", ir)
        assert result.action == ProcessingAction.GREETING

    def test_preserved_intent_tool_call(self):
        mock_ic = MagicMock()
        pending = PendingIntent(intent="shipment_generate", slots={"unit_name": "Co"}, missing_slots=[], source="test")
        mock_ic.get_pending.return_value = pending
        mock_ic.should_adopt_new_intent.return_value = (
            False, AdoptionReason.INTENT_PRESERVED, None
        )
        mock_cc = MagicMock()
        mock_cc.is_duplicate.return_value = (False, None, False)
        facade = ContextFacade(intent_context=mock_ic, chat_context=mock_cc)

        ir = IntentResult(primary_intent="some_intent", tool_key=None, slots={})
        result = facade.process("user1", "补充信息", ir)
        assert result.action == ProcessingAction.TOOL_CALL


# ---------------------------------------------------------------------------
# ContextFacade — update_pending_with_slots
# ---------------------------------------------------------------------------


class TestUpdatePendingWithSlots:
    def test_merges_slots(self):
        mock_ic = MagicMock()
        mock_ic.merge_slots.return_value = PendingIntent(
            intent="test", slots={"a": "1"}, missing_slots=[], source="test"
        )
        facade = ContextFacade(intent_context=mock_ic, chat_context=MagicMock())

        result = facade.update_pending_with_slots("user1", {"a": "1"})
        assert result is not None
        mock_ic.merge_slots.assert_called_once_with("user1", {"a": "1"})


# ---------------------------------------------------------------------------
# ContextFacade — confirm_pending
# ---------------------------------------------------------------------------


class TestConfirmPending:
    def test_confirms(self):
        mock_ic = MagicMock()
        pending = PendingIntent(intent="test", slots={}, missing_slots=[], source="test")
        mock_ic.get_pending.return_value = pending
        facade = ContextFacade(intent_context=mock_ic, chat_context=MagicMock())

        result = facade.confirm_pending("user1")
        assert result is not None
        mock_ic.clear_pending.assert_called_once_with("user1")

    def test_no_pending(self):
        mock_ic = MagicMock()
        mock_ic.get_pending.return_value = None
        facade = ContextFacade(intent_context=mock_ic, chat_context=MagicMock())

        result = facade.confirm_pending("user1")
        assert result is None


# ---------------------------------------------------------------------------
# ContextFacade — cancel_pending
# ---------------------------------------------------------------------------


class TestCancelPending:
    def test_cancels(self):
        mock_ic = MagicMock()
        facade = ContextFacade(intent_context=mock_ic, chat_context=MagicMock())
        facade.cancel_pending("user1")
        mock_ic.clear_pending.assert_called_once_with("user1")


# ---------------------------------------------------------------------------
# ContextFacade — get_context_summary
# ---------------------------------------------------------------------------


class TestGetContextSummary:
    def test_returns_summary(self):
        mock_ic = MagicMock()
        mock_ic.get_pending_summary.return_value = {"intent": "test"}
        mock_cc = MagicMock()
        mock_cc.get_history_summary.return_value = {"turns": 5}
        facade = ContextFacade(intent_context=mock_ic, chat_context=mock_cc)

        result = facade.get_context_summary("user1")
        assert "pending" in result
        assert "history" in result


# ---------------------------------------------------------------------------
# ContextFacade — _get_required_slots
# ---------------------------------------------------------------------------


class TestGetRequiredSlots:
    def test_known_intent(self):
        facade = ContextFacade(intent_context=MagicMock(), chat_context=MagicMock())
        slots = facade._get_required_slots("shipment_generate")
        assert "unit_name" in slots

    def test_unknown_intent(self):
        facade = ContextFacade(intent_context=MagicMock(), chat_context=MagicMock())
        slots = facade._get_required_slots("unknown_intent")
        assert slots == []


# ---------------------------------------------------------------------------
# ContextFacade — _build_followup_question
# ---------------------------------------------------------------------------


class TestBuildFollowupQuestion:
    def test_no_missing_slots(self):
        facade = ContextFacade(intent_context=MagicMock(), chat_context=MagicMock())
        q = facade._build_followup_question("test", [], {})
        assert "更多信息" in q

    def test_priority_slot(self):
        facade = ContextFacade(intent_context=MagicMock(), chat_context=MagicMock())
        q = facade._build_followup_question("shipment_generate", ["unit_name"], {})
        assert "客户" in q

    def test_non_priority_slot(self):
        facade = ContextFacade(intent_context=MagicMock(), chat_context=MagicMock())
        q = facade._build_followup_question("product_query", ["keyword"], {})
        assert "keyword" in q


# ---------------------------------------------------------------------------
# ContextFacade — _get_action_description
# ---------------------------------------------------------------------------


class TestGetActionDescription:
    def test_known_intent(self):
        facade = ContextFacade(intent_context=MagicMock(), chat_context=MagicMock())
        desc = facade._get_action_description("shipment_generate", {"unit_name": "Co"})
        assert "Co" in desc

    def test_unknown_intent(self):
        facade = ContextFacade(intent_context=MagicMock(), chat_context=MagicMock())
        desc = facade._get_action_description("unknown", {})
        assert "unknown" in desc


# ---------------------------------------------------------------------------
# ContextFacade — _notify_pending_preserved
# ---------------------------------------------------------------------------


class TestNotifyPendingPreserved:
    def test_no_notifier(self):
        mock_ic = MagicMock()
        facade = ContextFacade(intent_context=mock_ic, chat_context=MagicMock())
        facade._notifier = None
        pending = PendingIntent(intent="test", slots={}, missing_slots=[], source="test")
        # Should not raise
        facade._notify_pending_preserved("user1", pending, "greeting")

    def test_with_notifier(self):
        mock_notifier = MagicMock()
        mock_ic = MagicMock()
        facade = ContextFacade(intent_context=mock_ic, chat_context=MagicMock())
        facade._notifier = mock_notifier
        pending = PendingIntent(intent="test", slots={}, missing_slots=[], source="test")
        facade._notify_pending_preserved("user1", pending, "greeting")
        mock_notifier.notify_pending_preserved.assert_called_once()

    def test_notifier_error(self):
        mock_notifier = MagicMock()
        mock_notifier.notify_pending_preserved.side_effect = RuntimeError("fail")
        mock_ic = MagicMock()
        facade = ContextFacade(intent_context=mock_ic, chat_context=MagicMock())
        facade._notifier = mock_notifier
        pending = PendingIntent(intent="test", slots={}, missing_slots=[], source="test")
        # Should not raise
        facade._notify_pending_preserved("user1", pending, "greeting")


# ---------------------------------------------------------------------------
# ContextFacadeContainer
# ---------------------------------------------------------------------------


class TestContextFacadeContainer:
    def test_get_instance_creates(self):
        ContextFacadeContainer.reset()
        instance = ContextFacadeContainer.get_instance()
        assert isinstance(instance, ContextFacade)

    def test_get_instance_singleton(self):
        ContextFacadeContainer.reset()
        a = ContextFacadeContainer.get_instance()
        b = ContextFacadeContainer.get_instance()
        assert a is b

    def test_reset(self):
        ContextFacadeContainer.reset()
        a = ContextFacadeContainer.get_instance()
        ContextFacadeContainer.reset()
        b = ContextFacadeContainer.get_instance()
        assert a is not b


# ---------------------------------------------------------------------------
# get_context_facade
# ---------------------------------------------------------------------------


class TestGetContextFacade:
    def test_returns_facade(self):
        ContextFacadeContainer.reset()
        facade = get_context_facade()
        assert isinstance(facade, ContextFacade)


# ---------------------------------------------------------------------------
# ContextFacade — process with response_text caching
# ---------------------------------------------------------------------------


class TestProcessWithResponseText:
    def test_response_text_cached(self):
        mock_ic = MagicMock()
        mock_ic.get_pending.return_value = None
        mock_cc = MagicMock()
        mock_cc.is_duplicate.return_value = (False, None, False)
        facade = ContextFacade(intent_context=mock_ic, chat_context=mock_cc)

        ir = IntentResult(primary_intent="help", tool_key=None, slots={}, is_help=True)
        result = facade.process("user1", "帮助", ir, response_text="AI response")
        mock_cc.add_turn.assert_called_once()
