"""Tests for app.domain.services.conversation.context.context_facade — dataclasses and enums."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.domain.services.conversation.context.context_facade import (
    ContextDecision,
    IntentResult,
    ProcessingAction,
    ProcessingResult,
)

# ========================= ProcessingAction ==============================


class TestProcessingAction:
    def test_values(self):
        assert ProcessingAction.GREETING.value == "greeting"
        assert ProcessingAction.GOODBYE.value == "goodbye"
        assert ProcessingAction.HELP.value == "help"
        assert ProcessingAction.SLOT_FILL.value == "slot_fill"
        assert ProcessingAction.TOOL_CALL.value == "tool_call"
        assert ProcessingAction.AI_RESPONSE.value == "ai_response"
        assert ProcessingAction.NEGATED.value == "negated"
        assert ProcessingAction.DUPLICATE_RESPONSE.value == "duplicate_response"
        assert ProcessingAction.INTENT_SWITCH_QUERY.value == "intent_switch_query"


# ========================= IntentResult ==================================


class TestIntentResult:
    def test_defaults(self):
        result = IntentResult(primary_intent="test", tool_key="test_tool", slots={"key": "val"})
        assert result.primary_intent == "test"
        assert result.tool_key == "test_tool"
        assert result.slots == {"key": "val"}
        assert result.is_greeting is False
        assert result.is_goodbye is False
        assert result.is_help is False
        assert result.is_negated is False
        assert result.confidence == 0.0
        assert result.source == "unknown"

    def test_greeting(self):
        result = IntentResult(primary_intent="greet", tool_key=None, slots={}, is_greeting=True)
        assert result.is_greeting is True


# ========================= ProcessingResult ==============================


class TestProcessingResult:
    def test_basic(self):
        result = ProcessingResult(
            action=ProcessingAction.TOOL_CALL,
            text="正在处理",
            data={"tool_key": "shipment_generate"},
        )
        assert result.action == ProcessingAction.TOOL_CALL
        assert result.text == "正在处理"
        assert result.data["tool_key"] == "shipment_generate"
        assert result.is_duplicate is False
        assert result.cached_response is None
        assert result.pending_intent is None

    def test_duplicate(self):
        result = ProcessingResult(
            action=ProcessingAction.DUPLICATE_RESPONSE,
            text="cached",
            data={},
            is_duplicate=True,
            cached_response="cached",
        )
        assert result.is_duplicate is True
        assert result.cached_response == "cached"


# ========================= ContextDecision ===============================


class TestContextDecision:
    def test_basic(self):
        decision = ContextDecision(
            should_continue=True,
            action=ProcessingAction.TOOL_CALL,
            reason="tool_key present",
        )
        assert decision.should_continue is True
        assert decision.action == ProcessingAction.TOOL_CALL
        assert decision.reason == "tool_key present"
        assert decision.merged_slots is None
        assert decision.pending_to_preserve is None

    def test_with_merged_slots(self):
        decision = ContextDecision(
            should_continue=True,
            action=ProcessingAction.SLOT_FILL,
            reason="missing slots",
            merged_slots={"unit_name": "test"},
        )
        assert decision.merged_slots == {"unit_name": "test"}
