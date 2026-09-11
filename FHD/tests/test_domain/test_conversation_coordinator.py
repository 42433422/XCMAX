"""Tests for app.domain.services.conversation.coordinator — UnifiedConversationCoordinator + SlotValidator."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from app.domain.services.conversation.coordinator import (
    IntentResult,
    PendingIntent,
    ProcessingAction,
    ProcessingResult,
    SlotValidator,
    UnifiedConversationCoordinator,
    get_conversation_coordinator,
)

# ---------------------------------------------------------------------------
# PendingIntent
# ---------------------------------------------------------------------------


class TestPendingIntent:
    def test_is_expired_false_when_recent(self):
        p = PendingIntent(intent="test", slots={}, missing_slots=[])
        assert p.is_expired() is False

    def test_is_expired_true_when_old(self):
        p = PendingIntent(
            intent="test",
            slots={},
            missing_slots=[],
            last_updated_at=time.time() - 600,
        )
        assert p.is_expired() is True

    def test_merge_slots_adds_new(self):
        p = PendingIntent(intent="test", slots={"a": "1"}, missing_slots=["b"])
        merged = p.merge_slots({"b": "2"})
        assert merged.slots == {"a": "1", "b": "2"}
        assert "b" not in merged.missing_slots

    def test_merge_slots_increments_turn(self):
        p = PendingIntent(intent="test", slots={}, missing_slots=[], turn_count=1)
        merged = p.merge_slots({"x": "y"})
        assert merged.turn_count == 2

    def test_merge_slots_updates_timestamp(self):
        p = PendingIntent(
            intent="test",
            slots={},
            missing_slots=[],
            last_updated_at=time.time() - 100,
        )
        merged = p.merge_slots({})
        assert merged.last_updated_at > p.last_updated_at


# ---------------------------------------------------------------------------
# SlotValidator
# ---------------------------------------------------------------------------


class TestSlotValidator:
    def test_validate_unknown_intent_passes(self):
        sv = SlotValidator()
        ok, missing = sv.validate("unknown_intent", {})
        assert ok is True
        assert missing == []

    def test_validate_shipment_generate_missing_slots(self):
        sv = SlotValidator()
        ok, missing = sv.validate("shipment_generate", {"unit_name": "Acme"})
        assert ok is False
        assert "model_number" in missing
        assert "tin_spec" in missing
        assert "quantity_tins" in missing

    def test_validate_shipment_generate_all_filled(self):
        sv = SlotValidator()
        slots = {
            "unit_name": "Acme",
            "model_number": "M1",
            "tin_spec": "20L",
            "quantity_tins": 10,
        }
        ok, missing = sv.validate("shipment_generate", slots)
        assert ok is True

    def test_validate_product_query_no_required(self):
        sv = SlotValidator()
        ok, missing = sv.validate("product_query", {})
        assert ok is True

    def test_build_followup_empty_returns_empty(self):
        sv = SlotValidator()
        assert sv.build_followup("test", []) == ""

    def test_build_followup_shipment_generate_unit_name(self):
        sv = SlotValidator()
        q = sv.build_followup("shipment_generate", ["unit_name"])
        assert "客户" in q

    def test_build_followup_shipment_generate_model_number(self):
        sv = SlotValidator()
        q = sv.build_followup("shipment_generate", ["model_number"])
        assert "编号" in q

    def test_build_followup_non_shipment_uses_labels(self):
        sv = SlotValidator()
        q = sv.build_followup("print_label", ["unit_name"])
        assert "客户" in q

    def test_build_followup_non_priority_slot(self):
        sv = SlotValidator()
        q = sv.build_followup("customer_supplement", ["field_name"])
        assert "field_name" in q or "字段名" in q


# ---------------------------------------------------------------------------
# UnifiedConversationCoordinator
# ---------------------------------------------------------------------------


class TestUnifiedConversationCoordinator:
    def _make_coordinator(self):
        coord = UnifiedConversationCoordinator()
        coord._task_agent = MagicMock()
        coord._task_agent.execute_plan.return_value = {"result": "ok"}
        coord._context_facade = MagicMock()
        coord._context_facade.intent_context.get_pending.return_value = None
        return coord

    def test_process_greeting(self):
        coord = self._make_coordinator()
        intent_result = IntentResult(
            primary_intent="greet",
            tool_key=None,
            slots={},
            is_greeting=True,
        )
        with patch.object(coord, "_recognize_intent", return_value=intent_result):
            result = coord.process("user1", "你好")
        assert result.action == ProcessingAction.GREETING
        assert "XCAGI" in result.text

    def test_process_goodbye(self):
        coord = self._make_coordinator()
        intent_result = IntentResult(
            primary_intent="goodbye",
            tool_key=None,
            slots={},
            is_goodbye=True,
        )
        with patch.object(coord, "_recognize_intent", return_value=intent_result):
            result = coord.process("user1", "再见")
        assert result.action == ProcessingAction.GOODBYE

    def test_process_help(self):
        coord = self._make_coordinator()
        intent_result = IntentResult(
            primary_intent="help",
            tool_key=None,
            slots={},
            is_help=True,
        )
        with patch.object(coord, "_recognize_intent", return_value=intent_result):
            result = coord.process("user1", "帮助")
        assert result.action == ProcessingAction.HELP

    def test_process_slot_fill_when_missing(self):
        coord = self._make_coordinator()
        intent_result = IntentResult(
            primary_intent="shipment_generate",
            tool_key="shipment_generate",
            slots={"unit_name": "Acme"},
        )
        with patch.object(coord, "_recognize_intent", return_value=intent_result):
            result = coord.process("user1", "发货给Acme")
        assert result.action == ProcessingAction.SLOT_FILL
        assert result.pending_intent is not None

    def test_process_tool_call_when_complete(self):
        coord = self._make_coordinator()
        intent_result = IntentResult(
            primary_intent="products",
            tool_key="products",
            slots={"keyword": "油漆"},
        )
        with patch.object(coord, "_recognize_intent", return_value=intent_result):
            result = coord.process("user1", "查油漆")
        assert result.action == ProcessingAction.TOOL_CALL

    def test_process_confirmation_with_pending(self):
        coord = self._make_coordinator()
        pending = PendingIntent(
            intent="shipment_generate",
            slots={
                "unit_name": "Acme",
                "model_number": "M1",
                "tin_spec": "20L",
                "quantity_tins": 10,
            },
            missing_slots=[],
        )
        coord._context_facade.intent_context.get_pending.return_value = MagicMock(
            intent="shipment_generate",
            slots=pending.slots,
            missing_slots=[],
            created_at=time.time(),
            source="test",
            last_updated_at=time.time(),
            turn_count=1,
        )
        intent_result = IntentResult(
            primary_intent="confirm",
            tool_key=None,
            slots={},
            is_confirmation=True,
        )
        with patch.object(coord, "_recognize_intent", return_value=intent_result):
            result = coord.process("user1", "是的")
        assert result.action == ProcessingAction.TOOL_CALL

    def test_get_action_description_known_intent(self):
        coord = self._make_coordinator()
        desc = coord._get_action_description("products", {"keyword": "油漆"})
        assert "油漆" in desc

    def test_get_action_description_unknown_intent(self):
        coord = self._make_coordinator()
        desc = coord._get_action_description("custom_action", {})
        assert "custom_action" in desc

    def test_greeting_with_pending_reminds_user(self):
        coord = self._make_coordinator()
        pending = PendingIntent(
            intent="shipment_generate",
            slots={"unit_name": "Acme"},
            missing_slots=["model_number"],
        )
        coord._context_facade.intent_context.get_pending.return_value = MagicMock(
            intent="shipment_generate",
            slots=pending.slots,
            missing_slots=["model_number"],
            created_at=time.time(),
            source="test",
            last_updated_at=time.time(),
            turn_count=1,
        )
        intent_result = IntentResult(
            primary_intent="greet",
            tool_key=None,
            slots={},
            is_greeting=True,
        )
        with patch.object(coord, "_recognize_intent", return_value=intent_result):
            result = coord.process("user1", "你好")
        assert "尚未完成" in result.text


# ---------------------------------------------------------------------------
# 置信度分层（契约纪律）
# ---------------------------------------------------------------------------


class TestTieredConfidence:
    def _basic(self, **flags):
        base = {
            "is_greeting": False,
            "is_goodbye": False,
            "is_help": False,
            "is_confirmation": False,
            "is_negation_intent": False,
        }
        base.update(flags)
        return base

    def test_rule_hit_high_priority(self):
        c = UnifiedConversationCoordinator._tiered_confidence(
            self._basic(), {"primary_intent": "shipment_generate", "matched_priority": 12}
        )
        assert c == 0.85

    def test_rule_hit_priority_equal_10(self):
        c = UnifiedConversationCoordinator._tiered_confidence(
            self._basic(), {"primary_intent": "wechat_send", "matched_priority": 10}
        )
        assert c == 0.85

    def test_rule_hit_low_priority(self):
        c = UnifiedConversationCoordinator._tiered_confidence(
            self._basic(), {"primary_intent": "shipment_template", "matched_priority": 9}
        )
        assert c == 0.7

    def test_rule_hit_priority_missing(self):
        c = UnifiedConversationCoordinator._tiered_confidence(
            self._basic(), {"primary_intent": "products"}
        )
        assert c == 0.7

    def test_negation_ambiguity_lowest_rule_tier(self):
        c = UnifiedConversationCoordinator._tiered_confidence(
            self._basic(),
            {"primary_intent": "shipment_generate", "matched_priority": 12, "is_negated": True},
        )
        assert c == 0.6

    def test_reflex_hit_highest(self):
        assert (
            UnifiedConversationCoordinator._tiered_confidence(
                self._basic(is_greeting=True), {"primary_intent": None}
            )
            == 0.95
        )
        assert (
            UnifiedConversationCoordinator._tiered_confidence(
                self._basic(is_confirmation=True), {"primary_intent": None}
            )
            == 0.95
        )

    def test_no_hit_zero(self):
        assert (
            UnifiedConversationCoordinator._tiered_confidence(
                self._basic(), {"primary_intent": None}
            )
            == 0.0
        )

    def test_recognize_intent_end_to_end_rule_hit(self):
        """_recognize_intent 用真实规则管道：高优先级命中 → 0.85"""
        coord = UnifiedConversationCoordinator()
        with patch("app.services.intent_service.recognize_intents") as mock_rule:
            mock_rule.return_value = {
                "primary_intent": "shipment_generate",
                "tool_key": "shipment_generate",
                "slots": {},
                "is_negated": False,
                "matched_priority": 12,
            }
            result = coord._recognize_intent("开发货单给星海化工 3桶 规格20", {})
        assert result.confidence == 0.85
        assert result.primary_intent == "shipment_generate"
        assert result.source == "neuro_reflex+rule"

    def test_recognize_intent_end_to_end_no_hit(self):
        """未命中且非反射 → 置信度 0.0（不再硬编码 0.8）"""
        coord = UnifiedConversationCoordinator()
        with patch("app.services.intent_service.recognize_intents") as mock_rule:
            mock_rule.return_value = {
                "primary_intent": None,
                "tool_key": None,
                "slots": {},
                "is_negated": False,
            }
            result = coord._recognize_intent("随便说点什么", {})
        assert result.confidence == 0.0
# R02: 拒绝类请求护栏 — 否定语境下不得执行/生成写入类计划
# ---------------------------------------------------------------------------


class TestNegationWriteGuard:
    """拒绝类请求（"不要开发货单"/"别给李四发微信"）不得触发写入执行。"""

    SHIPMENT_SLOTS = {
        "unit_name": "Acme",
        "model_number": "M1",
        "tin_spec": "20L",
        "quantity_tins": 10,
    }

    def _make_coordinator(self):
        coord = UnifiedConversationCoordinator()
        coord._task_agent = MagicMock()
        coord._task_agent.execute_plan.return_value = {"result": "ok"}
        coord._context_facade = MagicMock()
        coord._context_facade.intent_context.get_pending.return_value = None
        return coord

    def test_negated_write_intent_blocked(self):
        """规则层否定只压制 tool_key、保留 primary_intent 时（历史漏洞路径），仍必须拦截。"""
        coord = self._make_coordinator()
        intent_result = IntentResult(
            primary_intent="shipment_generate",
            tool_key=None,
            slots=dict(self.SHIPMENT_SLOTS),
            is_negated=True,
        )
        with patch.object(coord, "_recognize_intent", return_value=intent_result):
            result = coord.process("user1", "不要给Acme开发货单，M1 20L 10桶")
        assert result.action == ProcessingAction.NEGATED
        coord._task_agent.execute_plan.assert_not_called()

    def test_negation_keyword_blocks_tool_key(self):
        """LLM 兜底直给 tool_key 且未打否定标记时，关键词兜底仍必须拦截。"""
        coord = self._make_coordinator()
        intent_result = IntentResult(
            primary_intent="wechat_send",
            tool_key="wechat_send",
            slots={"target": "李四", "content": "你好"},
        )
        with patch.object(coord, "_recognize_intent", return_value=intent_result):
            result = coord.process("user1", "不要给李四发微信说你好")
        assert result.action == ProcessingAction.NEGATED
        coord._task_agent.execute_plan.assert_not_called()

    def test_negation_cancels_pending_write(self):
        """待执行的写入计划被"算了/不要了"撤销时，必须清 pending 且不执行。"""
        coord = self._make_coordinator()
        coord._context_facade.intent_context.get_pending.return_value = MagicMock(
            intent="shipment_generate",
            slots=dict(self.SHIPMENT_SLOTS),
            missing_slots=[],
            created_at=time.time(),
            source="test",
            last_updated_at=time.time(),
            turn_count=1,
        )
        intent_result = IntentResult(primary_intent=None, tool_key=None, slots={})
        with patch.object(coord, "_recognize_intent", return_value=intent_result):
            result = coord.process("user1", "算了，不要了")
        assert result.action == ProcessingAction.NEGATED
        coord._context_facade.intent_context.clear_pending.assert_called_once_with("user1")
        coord._task_agent.execute_plan.assert_not_called()

    def test_write_intent_without_negation_still_executes(self):
        """正常写入请求（无否定语境）不受护栏影响。"""
        coord = self._make_coordinator()
        intent_result = IntentResult(
            primary_intent="shipment_generate",
            tool_key="shipment_generate",
            slots=dict(self.SHIPMENT_SLOTS),
        )
        with patch.object(coord, "_recognize_intent", return_value=intent_result):
            result = coord.process("user1", "给Acme开发货单 M1 20L 10桶")
        assert result.action == ProcessingAction.TOOL_CALL
        coord._task_agent.execute_plan.assert_called_once()

    def test_query_intent_with_negation_word_not_blocked(self):
        """查询类意图即使带否定词也不走写入护栏（查询无副作用）。"""
        coord = self._make_coordinator()
        intent_result = IntentResult(
            primary_intent="products",
            tool_key="products",
            slots={"keyword": "油漆"},
            is_negated=True,
        )
        with patch.object(coord, "_recognize_intent", return_value=intent_result):
            result = coord.process("user1", "不要查油漆了……算了还是查吧")
        assert result.action == ProcessingAction.TOOL_CALL


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


class TestGetConversationCoordinator:
    def test_returns_instance(self):
        with patch("app.domain.services.conversation.coordinator._coordinator", None):
            with patch(
                "app.domain.services.conversation.coordinator.UnifiedConversationCoordinator"
            ) as MockCls:
                mock_inst = MagicMock()
                MockCls.return_value = mock_inst
                # Reset module-level singleton
                import app.domain.services.conversation.coordinator as mod

                mod._coordinator = None
                result = get_conversation_coordinator()
                assert result is mock_inst
                mod._coordinator = None
