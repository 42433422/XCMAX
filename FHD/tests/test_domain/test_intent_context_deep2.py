"""Deep coverage tests for app.domain.services.conversation.context.intent_context.

Targets remaining uncovered branches:
- _notify_preserved (currently uncovered)
- _get_notifier with hasattr check (second call path)
- should_adopt_new_intent edge cases (special intent + high turn count)
- merge_slots with empty new_slots
- get_pending_summary with near_expiry boundary
- cleanup_expired with no pending at all
- PendingIntent.merge_slots with all missing slots filled
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from app.domain.services.conversation.context.intent_context import (
    HIGH_PRIORITY_INTENTS,
    LOW_PRIORITY_INTENTS,
    SPECIAL_INTENTS,
    AdoptionReason,
    IntentContext,
    IntentContextContainer,
    PendingIntent,
    get_intent_context,
)

# ── _notify_preserved (uncovered) ───────────────────────────────────────────


class TestNotifyPreserved:
    def test_notify_preserved_calls_notifier(self):
        ctx = IntentContext()
        ctx._notifier = MagicMock()
        p = PendingIntent(intent="i", slots={}, missing_slots=[])
        ctx._notify_preserved("u1", p, "special_intent")
        ctx._notifier.notify_pending_preserved.assert_called_once_with(
            "u1", p.to_dict(), "special_intent"
        )

    def test_notify_preserved_no_notifier_no_error(self):
        ctx = IntentContext()
        ctx._notifier = None
        p = PendingIntent(intent="i", slots={}, missing_slots=[])
        # Should not raise
        ctx._notify_preserved("u1", p, "action")

    def test_notify_preserved_error_swallowed(self):
        ctx = IntentContext()
        ctx._notifier = MagicMock()
        ctx._notifier.notify_pending_preserved.side_effect = RuntimeError("fail")
        p = PendingIntent(intent="i", slots={}, missing_slots=[])
        # Should not raise
        ctx._notify_preserved("u1", p, "action")

    def test_notify_preserved_with_various_actions(self):
        ctx = IntentContext()
        ctx._notifier = MagicMock()
        p = PendingIntent(intent="i", slots={}, missing_slots=[])
        for action in ("special_intent", "low_priority", "default_preserve"):
            ctx._notify_preserved("u1", p, action)
        assert ctx._notifier.notify_pending_preserved.call_count == 3


# ── _get_notifier deep ──────────────────────────────────────────────────────


class TestGetNotifierDeep:
    def test_hasattr_skips_lazy_load(self):
        ctx = IntentContext()
        ctx._notifier = "already_set"
        # Should return existing without re-loading
        result = ctx._get_notifier()
        assert result == "already_set"

    def test_lazy_load_called_once(self):
        ctx = IntentContext()
        assert not hasattr(ctx, "_notifier")
        fake_module = MagicMock()
        fake_module.get_context_notifier.return_value = "notifier1"
        with patch.dict("sys.modules", {"app.contexts.context_notifier": fake_module}):
            result1 = ctx._get_notifier()
            result2 = ctx._get_notifier()
        assert result1 == "notifier1"
        assert result2 == "notifier1"
        # Lazy load only called once
        fake_module.get_context_notifier.assert_called_once()


# ── should_adopt_new_intent edge cases ──────────────────────────────────────


class TestShouldAdoptNewIntentDeep:
    def test_special_intent_with_high_turn_count(self):
        """Special intent check comes before turn_count check."""
        ctx = IntentContext()
        p = PendingIntent(intent="order", slots={}, missing_slots=[])
        p.turn_count = 5
        # Special intent → preserved (not switch)
        for special in SPECIAL_INTENTS:
            adopt, reason, _ = ctx.should_adopt_new_intent(special, p)
            assert adopt is False
            assert reason == AdoptionReason.SPECIAL_INTENT_PRESERVED

    def test_same_intent_with_high_turn_count(self):
        """Same intent check comes before turn_count check."""
        ctx = IntentContext()
        p = PendingIntent(intent="order", slots={}, missing_slots=[])
        p.turn_count = 5
        adopt, reason, _ = ctx.should_adopt_new_intent("order", p)
        # Same intent → merge slots (not switch)
        assert adopt is True
        assert reason == AdoptionReason.MERGE_SLOTS

    def test_special_intent_overrides_priority(self):
        """Special intent preserved even if pending is low priority."""
        ctx = IntentContext()
        p = PendingIntent(intent="products", slots={}, missing_slots=[])
        # "products" is low priority, "greeting" is special
        adopt, reason, _ = ctx.should_adopt_new_intent("greeting", p)
        assert adopt is False
        assert reason == AdoptionReason.SPECIAL_INTENT_PRESERVED

    def test_high_to_high_preserves(self):
        ctx = IntentContext()
        p = PendingIntent(intent="shipment_generate", slots={}, missing_slots=[])
        adopt, reason, _ = ctx.should_adopt_new_intent("print_label", p)
        # Both high priority, different, not special, turn_count < 3
        assert adopt is False
        assert reason == AdoptionReason.INTENT_PRESERVED

    def test_low_to_low_preserves(self):
        ctx = IntentContext()
        p = PendingIntent(intent="products", slots={}, missing_slots=[])
        adopt, reason, _ = ctx.should_adopt_new_intent("customers", p)
        # Both low priority, different, not special, turn_count < 3
        assert adopt is False
        assert reason == AdoptionReason.INTENT_PRESERVED

    def test_turn_count_exactly_3_triggers_switch(self):
        ctx = IntentContext()
        p = PendingIntent(intent="order", slots={}, missing_slots=[])
        p.turn_count = 3
        adopt, reason, _ = ctx.should_adopt_new_intent("other", p)
        assert adopt is True
        assert reason == AdoptionReason.SWITCH_REQUESTED

    def test_turn_count_exactly_2_preserves(self):
        ctx = IntentContext()
        p = PendingIntent(intent="order", slots={}, missing_slots=[])
        p.turn_count = 2
        adopt, reason, _ = ctx.should_adopt_new_intent("other", p)
        assert adopt is False
        assert reason == AdoptionReason.INTENT_PRESERVED


# ── merge_slots deep ────────────────────────────────────────────────────────


class TestMergeSlotsDeep:
    def test_empty_new_slots(self):
        ctx = IntentContext()
        p = PendingIntent(intent="i", slots={"a": "1"}, missing_slots=["b"])
        ctx.set_pending("u1", p)
        updated = ctx.merge_slots("u1", {})
        assert updated is not None
        assert updated.slots == {"a": "1"}
        assert updated.missing_slots == ["b"]
        assert updated.turn_count == 2

    def test_merge_slots_overwrites_existing(self):
        ctx = IntentContext()
        p = PendingIntent(intent="i", slots={"a": "1"}, missing_slots=[])
        ctx.set_pending("u1", p)
        updated = ctx.merge_slots("u1", {"a": "new"})
        assert updated.slots == {"a": "new"}

    def test_merge_slots_none_value_not_filling_missing(self):
        ctx = IntentContext()
        p = PendingIntent(intent="i", slots={}, missing_slots=["a"])
        ctx.set_pending("u1", p)
        updated = ctx.merge_slots("u1", {"a": None})
        # None doesn't fill missing slot
        assert "a" in updated.missing_slots

    def test_merge_slots_empty_string_not_filling_missing(self):
        ctx = IntentContext()
        p = PendingIntent(intent="i", slots={}, missing_slots=["a"])
        ctx.set_pending("u1", p)
        updated = ctx.merge_slots("u1", {"a": ""})
        # Empty string is falsy → not filled
        assert "a" in updated.missing_slots


# ── PendingIntent.merge_slots deep ──────────────────────────────────────────


class TestPendingIntentMergeSlotsDeep:
    def test_merge_preserves_intent(self):
        p = PendingIntent(intent="order", slots={"a": "1"}, missing_slots=[])
        merged = p.merge_slots({"b": "2"})
        assert merged.intent == "order"

    def test_merge_preserves_source(self):
        p = PendingIntent(intent="order", slots={}, missing_slots=[], source="rule")
        merged = p.merge_slots({"a": "1"})
        assert merged.source == "rule"

    def test_merge_increments_turn_count(self):
        p = PendingIntent(intent="order", slots={}, missing_slots=[], turn_count=5)
        merged = p.merge_slots({"a": "1"})
        assert merged.turn_count == 6

    def test_merge_updates_last_updated_at(self):
        p = PendingIntent(intent="order", slots={}, missing_slots=[])
        original_updated = p.last_updated_at
        time.sleep(0.01)
        merged = p.merge_slots({"a": "1"})
        assert merged.last_updated_at > original_updated

    def test_merge_all_missing_filled(self):
        p = PendingIntent(intent="order", slots={}, missing_slots=["a", "b", "c"])
        merged = p.merge_slots({"a": "1", "b": "2", "c": "3"})
        assert merged.missing_slots == []

    def test_merge_partial_fill(self):
        p = PendingIntent(intent="order", slots={}, missing_slots=["a", "b", "c"])
        merged = p.merge_slots({"a": "1"})
        assert merged.missing_slots == ["b", "c"]


# ── get_pending_summary deep ────────────────────────────────────────────────


class TestGetPendingSummaryDeep:
    def test_near_expiry_boundary(self):
        ctx = IntentContext()
        p = PendingIntent(intent="order", slots={}, missing_slots=[])
        # Slightly less than 240 seconds ago → not near expiry (> 240 is False)
        p.last_updated_at = time.time() - 239
        ctx.set_pending("u1", p)
        summary = ctx.get_pending_summary("u1")
        assert summary["is_near_expiry"] is False

    def test_near_expiry_just_over(self):
        ctx = IntentContext()
        p = PendingIntent(intent="order", slots={}, missing_slots=[])
        p.last_updated_at = time.time() - 241
        ctx.set_pending("u1", p)
        summary = ctx.get_pending_summary("u1")
        assert summary["is_near_expiry"] is True

    def test_age_seconds_positive(self):
        ctx = IntentContext()
        p = PendingIntent(intent="order", slots={}, missing_slots=[])
        ctx.set_pending("u1", p)
        summary = ctx.get_pending_summary("u1")
        assert summary["age_seconds"] >= 0

    def test_with_slots_and_missing(self):
        ctx = IntentContext()
        p = PendingIntent(
            intent="order",
            slots={"a": "1", "b": "2"},
            missing_slots=["c"],
            turn_count=3,
        )
        ctx.set_pending("u1", p)
        summary = ctx.get_pending_summary("u1")
        assert summary["slots"] == {"a": "1", "b": "2"}
        assert summary["missing_slots"] == ["c"]
        assert summary["turn_count"] == 3


# ── cleanup_expired deep ────────────────────────────────────────────────────


class TestCleanupExpiredDeep:
    def test_empty_store(self):
        ctx = IntentContext()
        assert ctx.cleanup_expired() == 0

    def test_all_expired(self):
        ctx = IntentContext()
        for i in range(3):
            p = PendingIntent(intent=f"i{i}", slots={}, missing_slots=[])
            p.last_updated_at = time.time() - 400
            ctx.set_pending(f"u{i}", p)
        assert ctx.cleanup_expired() == 3
        assert ctx.get_all_pending_count() == 0

    def test_mixed_expired_and_valid(self):
        ctx = IntentContext()
        p1 = PendingIntent(intent="i1", slots={}, missing_slots=[])
        p2 = PendingIntent(intent="i2", slots={}, missing_slots=[])
        p2.last_updated_at = time.time() - 400
        ctx.set_pending("u1", p1)
        ctx.set_pending("u2", p2)
        cleaned = ctx.cleanup_expired()
        assert cleaned == 1
        assert ctx.has_pending("u1") is True
        assert ctx.has_pending("u2") is False


# ── clear_pending deep ──────────────────────────────────────────────────────


class TestClearPendingDeep:
    def test_clear_with_various_reasons(self):
        ctx = IntentContext()
        p = PendingIntent(intent="i", slots={}, missing_slots=[])
        ctx.set_pending("u1", p)
        for reason in ("completed", "abandoned", "timeout", "switched"):
            ctx.set_pending("u1", p)
            ctx.clear_pending("u1", reason=reason)
            assert ctx.get_pending("u1") is None

    def test_clear_notifies_with_reason(self):
        ctx = IntentContext()
        ctx._notifier = MagicMock()
        p = PendingIntent(intent="i", slots={}, missing_slots=[])
        ctx.set_pending("u1", p)
        ctx.clear_pending("u1", reason="custom_reason")
        ctx._notifier.notify_pending_cleared.assert_called_once_with("u1", "custom_reason")


# ── IntentContextContainer deep ─────────────────────────────────────────────


class TestIntentContextContainerDeep:
    def test_reset_clears_singleton(self):
        IntentContextContainer.reset()
        ctx1 = IntentContextContainer.get_instance()
        ctx1.set_pending("u1", PendingIntent(intent="i", slots={}, missing_slots=[]))
        IntentContextContainer.reset()
        ctx2 = IntentContextContainer.get_instance()
        assert ctx1 is not ctx2
        assert ctx2.get_pending("u1") is None

    def test_get_intent_context_after_multiple_resets(self):
        IntentContextContainer.reset()
        IntentContextContainer.reset()
        ctx = get_intent_context()
        assert ctx is not None

    def test_instance_persists_state(self):
        IntentContextContainer.reset()
        ctx = IntentContextContainer.get_instance()
        ctx.set_pending("u1", PendingIntent(intent="i", slots={}, missing_slots=[]))
        ctx2 = IntentContextContainer.get_instance()
        assert ctx is ctx2
        assert ctx2.has_pending("u1") is True
        IntentContextContainer.reset()


# ── set_pending notifies ────────────────────────────────────────────────────


class TestSetPendingNotifyDeep:
    def test_set_pending_notifies_created_with_data(self):
        ctx = IntentContext()
        ctx._notifier = MagicMock()
        p = PendingIntent(intent="order", slots={"a": "1"}, missing_slots=["b"])
        ctx.set_pending("u1", p)
        call_args = ctx._notifier.notify_pending_created.call_args
        user_id, pending_data = call_args.args
        assert user_id == "u1"
        assert pending_data["intent"] == "order"
        assert pending_data["slots"] == {"a": "1"}

    def test_merge_slots_notifies_updated_with_data(self):
        ctx = IntentContext()
        ctx._notifier = MagicMock()
        p = PendingIntent(intent="order", slots={"a": "1"}, missing_slots=["b"])
        ctx.set_pending("u1", p)
        ctx.merge_slots("u1", {"b": "2"})
        call_args = ctx._notifier.notify_pending_updated.call_args
        user_id, pending_data = call_args.args
        assert pending_data["slots"] == {"a": "1", "b": "2"}
        assert pending_data["missing_slots"] == []
