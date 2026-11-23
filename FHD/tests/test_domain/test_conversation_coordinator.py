"""Tests for retained conversation slot validation and domain types."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from app.domain.conversation.services.chat_tool_intent import tiered_confidence
from app.domain.conversation.services.coordinator_types import (
    IntentResult,
    PendingIntent,
    ProcessingAction,
    ProcessingResult,
)
from app.domain.conversation.services.slot_validator import SlotValidator

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
# ---------------------------------------------------------------------------


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
        c = tiered_confidence(
            self._basic(), {"primary_intent": "shipment_generate", "matched_priority": 12}
        )
        assert c == 0.85

    def test_rule_hit_priority_equal_10(self):
        c = tiered_confidence(
            self._basic(), {"primary_intent": "wechat_send", "matched_priority": 10}
        )
        assert c == 0.85

    def test_rule_hit_low_priority(self):
        c = tiered_confidence(
            self._basic(), {"primary_intent": "shipment_template", "matched_priority": 9}
        )
        assert c == 0.7

    def test_rule_hit_priority_missing(self):
        c = tiered_confidence(self._basic(), {"primary_intent": "products"})
        assert c == 0.7

    def test_negation_ambiguity_lowest_rule_tier(self):
        c = tiered_confidence(
            self._basic(),
            {"primary_intent": "shipment_generate", "matched_priority": 12, "is_negated": True},
        )
        assert c == 0.6

    def test_reflex_hit_highest(self):
        assert tiered_confidence(self._basic(is_greeting=True), {"primary_intent": None}) == 0.95
        assert (
            tiered_confidence(self._basic(is_confirmation=True), {"primary_intent": None}) == 0.95
        )

    def test_no_hit_zero(self):
        assert tiered_confidence(self._basic(), {"primary_intent": None}) == 0.0


# R02: 拒绝类请求护栏 — 否定语境下不得执行/生成写入类计划
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
