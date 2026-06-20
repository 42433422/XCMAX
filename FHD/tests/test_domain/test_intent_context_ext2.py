"""Tests for app.domain.services.conversation.context.intent_context — ext2.

Covers ``PendingIntent`` (is_expired / merge_slots / to_dict),
``IntentContext`` (set/get/clear/has pending, merge_slots,
should_adopt_new_intent, get_pending_summary, cleanup_expired,
get_all_pending_count), ``IntentContextContainer``, and notifier paths.
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

# ── PendingIntent ────────────────────────────────────────────────────────────


class TestPendingIntent:
    def test_default_values(self):
        p = PendingIntent(intent="greeting", slots={}, missing_slots=[])
        assert p.intent == "greeting"
        assert p.slots == {}
        assert p.missing_slots == []
        assert p.source == "unknown"
        assert p.turn_count == 1
        assert p.created_at > 0
        assert p.last_updated_at > 0

    def test_is_expired_false_when_recent(self):
        p = PendingIntent(intent="i", slots={}, missing_slots=[])
        assert p.is_expired(max_age_seconds=300) is False

    def test_is_expired_true_when_old(self):
        p = PendingIntent(intent="i", slots={}, missing_slots=[])
        p.last_updated_at = time.time() - 400
        assert p.is_expired(max_age_seconds=300) is True

    def test_is_expired_custom_max_age(self):
        p = PendingIntent(intent="i", slots={}, missing_slots=[])
        p.last_updated_at = time.time() - 50
        assert p.is_expired(max_age_seconds=100) is False
        assert p.is_expired(max_age_seconds=10) is True

    def test_merge_slots_combines(self):
        p = PendingIntent(intent="i", slots={"a": "1"}, missing_slots=["b", "c"])
        merged = p.merge_slots({"b": "2"})
        assert merged.slots == {"a": "1", "b": "2"}
        # c still missing
        assert merged.missing_slots == ["c"]
        assert merged.turn_count == 2
        assert merged.intent == "i"

    def test_merge_slots_overwrites(self):
        p = PendingIntent(intent="i", slots={"a": "1"}, missing_slots=[])
        merged = p.merge_slots({"a": "new"})
        assert merged.slots == {"a": "new"}

    def test_merge_slots_clears_missing_when_filled(self):
        p = PendingIntent(intent="i", slots={}, missing_slots=["a", "b"])
        merged = p.merge_slots({"a": "1", "b": "2"})
        assert merged.missing_slots == []

    def test_merge_slots_preserves_created_at(self):
        p = PendingIntent(intent="i", slots={}, missing_slots=[])
        original_created = p.created_at
        merged = p.merge_slots({"a": "1"})
        assert merged.created_at == original_created

    def test_to_dict(self):
        p = PendingIntent(
            intent="i",
            slots={"a": "1"},
            missing_slots=["b"],
            source="test",
            turn_count=2,
        )
        d = p.to_dict()
        assert d["intent"] == "i"
        assert d["slots"] == {"a": "1"}
        assert d["missing_slots"] == ["b"]
        assert d["source"] == "test"
        assert d["turn_count"] == 2
        assert "is_expired" in d
        assert "created_at" in d
        assert "last_updated_at" in d


# ── IntentContext basic CRUD ─────────────────────────────────────────────────


class TestIntentContextBasic:
    def test_set_and_get(self):
        ctx = IntentContext()
        p = PendingIntent(intent="i", slots={}, missing_slots=[])
        ctx.set_pending("u1", p)
        assert ctx.get_pending("u1") is p

    def test_get_missing_user(self):
        ctx = IntentContext()
        assert ctx.get_pending("missing") is None

    def test_get_expired_clears(self):
        ctx = IntentContext()
        p = PendingIntent(intent="i", slots={}, missing_slots=[])
        p.last_updated_at = time.time() - 400
        ctx.set_pending("u1", p)
        assert ctx.get_pending("u1") is None
        assert "u1" not in ctx._pending_store

    def test_clear_existing(self):
        ctx = IntentContext()
        p = PendingIntent(intent="i", slots={}, missing_slots=[])
        ctx.set_pending("u1", p)
        ctx.clear_pending("u1")
        assert ctx.get_pending("u1") is None

    def test_clear_missing_no_error(self):
        ctx = IntentContext()
        ctx.clear_pending("missing")  # should not raise

    def test_clear_with_reason(self):
        ctx = IntentContext()
        p = PendingIntent(intent="i", slots={}, missing_slots=[])
        ctx.set_pending("u1", p)
        ctx.clear_pending("u1", reason="abandoned")
        assert ctx.get_pending("u1") is None

    def test_has_pending_true(self):
        ctx = IntentContext()
        p = PendingIntent(intent="i", slots={}, missing_slots=[])
        ctx.set_pending("u1", p)
        assert ctx.has_pending("u1") is True

    def test_has_pending_false(self):
        ctx = IntentContext()
        assert ctx.has_pending("missing") is False

    def test_has_pending_expired_returns_false(self):
        ctx = IntentContext()
        p = PendingIntent(intent="i", slots={}, missing_slots=[])
        p.last_updated_at = time.time() - 400
        ctx.set_pending("u1", p)
        assert ctx.has_pending("u1") is False


# ── merge_slots ──────────────────────────────────────────────────────────────


class TestIntentContextMergeSlots:
    def test_no_pending_returns_none(self):
        ctx = IntentContext()
        assert ctx.merge_slots("u1", {"a": "1"}) is None

    def test_merges_and_updates(self):
        ctx = IntentContext()
        p = PendingIntent(intent="i", slots={"a": "1"}, missing_slots=["b"])
        ctx.set_pending("u1", p)
        updated = ctx.merge_slots("u1", {"b": "2"})
        assert updated is not None
        assert updated.slots == {"a": "1", "b": "2"}
        assert updated.missing_slots == []
        assert updated.turn_count == 2
        # The stored pending should be the updated one
        assert ctx.get_pending("u1") is updated


# ── should_adopt_new_intent ──────────────────────────────────────────────────


class TestShouldAdoptNewIntent:
    def test_no_pending_adopts_new_task(self):
        ctx = IntentContext()
        adopt, reason, pending = ctx.should_adopt_new_intent("greeting", None)
        assert adopt is True
        assert reason == AdoptionReason.NEW_TASK
        assert pending is None

    def test_special_intent_preserves_pending(self):
        ctx = IntentContext()
        p = PendingIntent(intent="order", slots={}, missing_slots=[])
        for special in SPECIAL_INTENTS:
            adopt, reason, returned_p = ctx.should_adopt_new_intent(special, p)
            assert adopt is False
            assert reason == AdoptionReason.SPECIAL_INTENT_PRESERVED
            assert returned_p is p

    def test_same_intent_merges_slots(self):
        ctx = IntentContext()
        p = PendingIntent(intent="order", slots={}, missing_slots=[])
        adopt, reason, returned_p = ctx.should_adopt_new_intent("order", p)
        assert adopt is True
        assert reason == AdoptionReason.MERGE_SLOTS
        assert returned_p is p

    def test_high_turn_count_triggers_switch(self):
        ctx = IntentContext()
        p = PendingIntent(intent="order", slots={}, missing_slots=[])
        p.turn_count = 5  # >= 3
        adopt, reason, returned_p = ctx.should_adopt_new_intent("other", p)
        assert adopt is True
        assert reason == AdoptionReason.SWITCH_REQUESTED
        assert returned_p is p

    def test_low_to_high_priority_switch(self):
        ctx = IntentContext()
        # pending is low priority, new is high priority → switch
        p = PendingIntent(intent="products", slots={}, missing_slots=[])
        # "products" is in LOW_PRIORITY_INTENTS
        for high in HIGH_PRIORITY_INTENTS:
            adopt, reason, returned_p = ctx.should_adopt_new_intent(high, p)
            assert adopt is True
            assert reason == AdoptionReason.LOW_PRIORITY_SWITCH

    def test_high_to_low_priority_preserves(self):
        ctx = IntentContext()
        # pending is high priority, new is low priority → preserve
        p = PendingIntent(intent="shipment_generate", slots={}, missing_slots=[])
        for low in LOW_PRIORITY_INTENTS:
            adopt, reason, returned_p = ctx.should_adopt_new_intent(low, p)
            assert adopt is False
            assert reason == AdoptionReason.INTENT_PRESERVED

    def test_default_preserves(self):
        ctx = IntentContext()
        p = PendingIntent(intent="order", slots={}, missing_slots=[])
        # Both intents are non-special, different, neither low/high priority
        adopt, reason, returned_p = ctx.should_adopt_new_intent("other_intent", p)
        assert adopt is False
        assert reason == AdoptionReason.INTENT_PRESERVED


# ── get_pending_summary ──────────────────────────────────────────────────────


class TestGetPendingSummary:
    def test_no_pending(self):
        ctx = IntentContext()
        summary = ctx.get_pending_summary("u1")
        assert summary == {"has_pending": False}

    def test_with_pending(self):
        ctx = IntentContext()
        p = PendingIntent(
            intent="order",
            slots={"a": "1"},
            missing_slots=["b"],
            turn_count=2,
        )
        ctx.set_pending("u1", p)
        summary = ctx.get_pending_summary("u1")
        assert summary["has_pending"] is True
        assert summary["intent"] == "order"
        assert summary["slots"] == {"a": "1"}
        assert summary["missing_slots"] == ["b"]
        assert summary["turn_count"] == 2
        assert "age_seconds" in summary
        assert "is_near_expiry" in summary

    def test_near_expiry(self):
        ctx = IntentContext()
        p = PendingIntent(intent="order", slots={}, missing_slots=[])
        p.last_updated_at = time.time() - 250  # > 240
        ctx.set_pending("u1", p)
        summary = ctx.get_pending_summary("u1")
        assert summary["is_near_expiry"] is True


# ── cleanup_expired ──────────────────────────────────────────────────────────


class TestCleanupExpired:
    def test_no_expired(self):
        ctx = IntentContext()
        p1 = PendingIntent(intent="i", slots={}, missing_slots=[])
        ctx.set_pending("u1", p1)
        assert ctx.cleanup_expired() == 0
        assert ctx.has_pending("u1") is True

    def test_cleans_expired(self):
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

    def test_cleans_multiple(self):
        ctx = IntentContext()
        for i in range(3):
            p = PendingIntent(intent=f"i{i}", slots={}, missing_slots=[])
            p.last_updated_at = time.time() - 400
            ctx.set_pending(f"u{i}", p)
        assert ctx.cleanup_expired() == 3


# ── get_all_pending_count ────────────────────────────────────────────────────


class TestGetAllPendingCount:
    def test_empty(self):
        ctx = IntentContext()
        assert ctx.get_all_pending_count() == 0

    def test_multiple(self):
        ctx = IntentContext()
        for i in range(3):
            ctx.set_pending(
                f"u{i}",
                PendingIntent(intent="i", slots={}, missing_slots=[]),
            )
        assert ctx.get_all_pending_count() == 3


# ── notifier paths ───────────────────────────────────────────────────────────


class TestNotifierPaths:
    def test_set_pending_notifies_created(self):
        ctx = IntentContext()
        ctx._notifier = MagicMock()
        p = PendingIntent(intent="i", slots={}, missing_slots=[])
        ctx.set_pending("u1", p)
        ctx._notifier.notify_pending_created.assert_called_once()

    def test_merge_slots_notifies_updated(self):
        ctx = IntentContext()
        ctx._notifier = MagicMock()
        p = PendingIntent(intent="i", slots={"a": "1"}, missing_slots=[])
        ctx.set_pending("u1", p)
        ctx._notifier.notify_pending_created.assert_called_once()
        ctx.merge_slots("u1", {"b": "2"})
        ctx._notifier.notify_pending_updated.assert_called_once()

    def test_clear_pending_notifies_cleared(self):
        ctx = IntentContext()
        ctx._notifier = MagicMock()
        p = PendingIntent(intent="i", slots={}, missing_slots=[])
        ctx.set_pending("u1", p)
        ctx.clear_pending("u1")
        ctx._notifier.notify_pending_cleared.assert_called_once_with("u1", "completed")

    def test_notifier_error_swallowed(self):
        ctx = IntentContext()
        ctx._notifier = MagicMock()
        ctx._notifier.notify_pending_created.side_effect = RuntimeError("notify fail")
        p = PendingIntent(intent="i", slots={}, missing_slots=[])
        # Should not raise
        ctx.set_pending("u1", p)

    def test_notifier_cleared_error_swallowed(self):
        ctx = IntentContext()
        ctx._notifier = MagicMock()
        ctx._notifier.notify_pending_cleared.side_effect = RuntimeError("fail")
        p = PendingIntent(intent="i", slots={}, missing_slots=[])
        ctx.set_pending("u1", p)
        # Should not raise
        ctx.clear_pending("u1")

    def test_no_notifier_no_error(self):
        ctx = IntentContext()
        ctx._notifier = None
        p = PendingIntent(intent="i", slots={}, missing_slots=[])
        # Should not raise
        ctx.set_pending("u1", p)
        ctx.clear_pending("u1")

    def test_get_notifier_lazy_load(self):
        ctx = IntentContext()
        # _notifier not set yet
        assert not hasattr(ctx, "_notifier")
        # Trigger lazy load
        fake_notifier_module = MagicMock()
        fake_notifier_module.get_context_notifier.return_value = "notifier_obj"
        with patch.dict("sys.modules", {"app.contexts.context_notifier": fake_notifier_module}):
            result = ctx._get_notifier()
        assert result == "notifier_obj"
        assert ctx._notifier == "notifier_obj"

    def test_get_notifier_import_error(self):
        ctx = IntentContext()
        # Force ImportError
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "app.contexts.context_notifier":
                raise ImportError("missing")
            return real_import(name, *args, **kwargs)

        with patch.object(builtins, "__import__", side_effect=fake_import):
            result = ctx._get_notifier()
        assert result is None
        assert ctx._notifier is None


# ── IntentContextContainer / get_intent_context ──────────────────────────────


class TestIntentContextContainer:
    def test_singleton(self):
        IntentContextContainer.reset()
        ctx1 = IntentContextContainer.get_instance()
        ctx2 = IntentContextContainer.get_instance()
        assert ctx1 is ctx2

    def test_reset(self):
        IntentContextContainer.reset()
        ctx1 = IntentContextContainer.get_instance()
        IntentContextContainer.reset()
        ctx2 = IntentContextContainer.get_instance()
        assert ctx1 is not ctx2

    def test_get_intent_context_returns_singleton(self):
        IntentContextContainer.reset()
        ctx1 = get_intent_context()
        ctx2 = get_intent_context()
        assert ctx1 is ctx2
