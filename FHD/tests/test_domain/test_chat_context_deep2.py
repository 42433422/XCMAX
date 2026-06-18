"""Deep coverage tests for app.domain.services.conversation.context.chat_context.

Targets remaining uncovered branches:
- ChatTurn edge cases (whitespace-only messages, slots with whitespace-only values)
- ChatContext._cleanup_cache with mixed expired/valid entries
- is_duplicate with slots that have empty values (slot_parts empty branch)
- is_duplicate with slots but no matching recent turns
- get_history_summary with turns that have None intent
- cleanup_old_history with mixed old/new turns for same user
- _update_semantic_cache with response_text=None
- ChatContextContainer thread-safety-ish reset behavior
"""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from app.domain.services.conversation.context.chat_context import (
    ChatContext,
    ChatContextContainer,
    ChatTurn,
    get_chat_context,
)

# ── ChatTurn edge cases ─────────────────────────────────────────────────────


class TestChatTurnEdgeCases:
    def test_message_fingerprint_empty_message(self):
        turn = ChatTurn("u", "", None, None, {}, None)
        fp = turn.message_fingerprint
        assert isinstance(fp, str)
        assert len(fp) == 16

    def test_message_fingerprint_whitespace_only_normalized(self):
        turn1 = ChatTurn("u", "   ", None, None, {}, None)
        turn2 = ChatTurn("u", "", None, None, {}, None)
        # Both normalize to empty string → same fingerprint
        assert turn1.message_fingerprint == turn2.message_fingerprint

    def test_semantic_fingerprint_intent_none_tool_key_set(self):
        turn = ChatTurn("u", "msg", None, "tool1", {}, None)
        fp = turn.make_semantic_fingerprint()
        assert isinstance(fp, str)
        assert len(fp) == 16

    def test_semantic_fingerprint_intent_set_tool_key_none(self):
        turn = ChatTurn("u", "msg", "intent1", None, {}, None)
        fp = turn.make_semantic_fingerprint()
        assert isinstance(fp, str)

    def test_semantic_fingerprint_both_none(self):
        turn = ChatTurn("u", "msg", None, None, {}, None)
        fp = turn.make_semantic_fingerprint()
        assert isinstance(fp, str)

    def test_semantic_fingerprint_slots_whitespace_only_skipped(self):
        turn1 = ChatTurn("u", "msg", "intent1", "tool1", {"a": "   "}, None)
        turn2 = ChatTurn("u", "msg", "intent1", "tool1", {"a": "x"}, None)
        # Whitespace-only slot value is skipped (str(v).strip() is falsy)
        # But turn1 has non-empty slots dict → appends empty string to key_parts
        # turn2 has slot with value → appends "a=x"
        # So they differ
        assert turn1.make_semantic_fingerprint() != turn2.make_semantic_fingerprint()

    def test_semantic_fingerprint_slots_zero_value_skipped(self):
        turn1 = ChatTurn("u", "msg", "intent1", "tool1", {"a": 0}, None)
        # 0 is falsy → skipped (v is falsy)
        # But slots dict is non-empty → appends empty string
        turn2 = ChatTurn("u", "msg", "intent1", "tool1", {}, None)
        # turn1 has non-empty slots dict (appends ""), turn2 has empty dict (no append)
        assert turn1.make_semantic_fingerprint() != turn2.make_semantic_fingerprint()

    def test_semantic_fingerprint_slots_numeric_string_kept(self):
        turn1 = ChatTurn("u", "msg", "intent1", "tool1", {"a": "1"}, None)
        turn2 = ChatTurn("u", "msg", "intent1", "tool1", {"a": "2"}, None)
        assert turn1.make_semantic_fingerprint() != turn2.make_semantic_fingerprint()

    def test_semantic_fingerprint_empty_dict(self):
        turn = ChatTurn("u", "msg", "intent1", "tool1", {}, None)
        fp = turn.make_semantic_fingerprint()
        # No slots branch
        assert isinstance(fp, str)

    def test_semantic_fingerprint_slots_none_value(self):
        turn1 = ChatTurn("u", "msg", "intent1", "tool1", {"a": None, "b": "1"}, None)
        turn2 = ChatTurn("u", "msg", "intent1", "tool1", {"b": "1"}, None)
        assert turn1.make_semantic_fingerprint() == turn2.make_semantic_fingerprint()


# ── is_duplicate additional branches ────────────────────────────────────────


class TestIsDuplicateDeep:
    def test_with_slots_empty_values_no_slot_parts(self):
        """Slots with all empty values → slot_parts empty → no semantic key extension."""
        ctx = ChatContext()
        turn = ChatTurn("u1", "msg", "intent1", "tool1", {}, "response1")
        ctx.add_turn("u1", turn)
        # Slots with empty values → slot_parts is empty → semantic_key not extended
        is_dup, cached, exact = ctx.is_duplicate(
            "u1",
            "different msg",
            intent="intent1",
            tool_key="tool1",
            slots={"a": "", "b": None},
        )
        # No match because the fingerprint mismatch (| vs :)
        assert is_dup is False

    def test_with_slots_and_no_recent_turns(self):
        """Intent set, slots set, but no recent turns for user."""
        ctx = ChatContext()
        is_dup, cached, exact = ctx.is_duplicate(
            "missing_user",
            "msg",
            intent="intent1",
            tool_key="tool1",
            slots={"a": "1"},
        )
        assert is_dup is False
        assert cached is None
        assert exact is False

    def test_exact_duplicate_just_within_ttl(self):
        ctx = ChatContext()
        ctx.cache_response("u1", "hello", "cached")
        # Immediately check → within TTL
        is_dup, cached, exact = ctx.is_duplicate("u1", "hello")
        assert is_dup is True
        assert cached == "cached"
        assert exact is True

    def test_exact_duplicate_at_boundary(self):
        """Test the boundary: timestamp slightly less than TTL ago (still valid)."""
        ctx = ChatContext()
        ctx.cache_response("u1", "hello", "cached")
        # Set timestamp to slightly less than TTL ago (still within TTL)
        for key, (resp, ts) in list(ctx._exact_cache.items()):
            ctx._exact_cache[key] = (resp, time.time() - ChatContext.EXACT_DUPLICATE_TTL + 0.5)
        # now - timestamp < TTL → still duplicate
        is_dup, cached, exact = ctx.is_duplicate("u1", "hello")
        assert is_dup is True

    def test_exact_duplicate_just_past_ttl(self):
        ctx = ChatContext()
        ctx.cache_response("u1", "hello", "cached")
        for key, (resp, ts) in list(ctx._exact_cache.items()):
            ctx._exact_cache[key] = (resp, time.time() - ChatContext.EXACT_DUPLICATE_TTL - 0.1)
        is_dup, cached, exact = ctx.is_duplicate("u1", "hello")
        assert is_dup is False

    def test_intent_no_slots_no_tool_key(self):
        """Intent set, no slots, no tool_key."""
        ctx = ChatContext()
        turn = ChatTurn("u1", "msg", "intent1", None, {}, "response1")
        ctx.add_turn("u1", turn)
        is_dup, cached, exact = ctx.is_duplicate("u1", "different", intent="intent1")
        # No match due to fingerprint separator mismatch
        assert is_dup is False

    def test_intent_with_slots_matching_no_response(self):
        """Recent turn has matching fingerprint but no response_text."""
        ctx = ChatContext()
        # Create a turn with intent but no response
        turn = ChatTurn("u1", "msg", "intent1", "tool1", {}, None)
        ctx.add_turn("u1", turn)
        is_dup, cached, exact = ctx.is_duplicate(
            "u1", "different", intent="intent1", tool_key="tool1"
        )
        # Even if fingerprint matched, response_text is None → not returned
        assert is_dup is False


# ── _cleanup_cache deep ─────────────────────────────────────────────────────


class TestCleanupCacheDeep:
    def test_mixed_expired_and_valid_semantic(self):
        ctx = ChatContext()
        ctx._semantic_cache["u1:expired"] = ("resp", time.time() - 400)
        ctx._semantic_cache["u1:valid"] = ("resp", time.time())
        ctx._cleanup_cache()
        assert "u1:expired" not in ctx._semantic_cache
        assert "u1:valid" in ctx._semantic_cache

    def test_mixed_expired_and_valid_exact(self):
        ctx = ChatContext()
        ctx._exact_cache["u1:expired"] = ("resp", time.time() - 100)
        ctx._exact_cache["u1:valid"] = ("resp", time.time())
        ctx._cleanup_cache()
        assert "u1:expired" not in ctx._exact_cache
        assert "u1:valid" in ctx._exact_cache

    def test_empty_caches_no_error(self):
        ctx = ChatContext()
        ctx._cleanup_cache()  # should not raise

    def test_semantic_boundary_300_seconds(self):
        """Semantic cache TTL is 300 seconds (boundary)."""
        ctx = ChatContext()
        # Slightly less than 300 seconds ago → kept (now - timestamp > 300 is False)
        ctx._semantic_cache["u1:boundary"] = ("resp", time.time() - 299)
        ctx._cleanup_cache()
        assert "u1:boundary" in ctx._semantic_cache

    def test_semantic_just_over_300_seconds(self):
        ctx = ChatContext()
        ctx._semantic_cache["u1:over"] = ("resp", time.time() - 301)
        ctx._cleanup_cache()
        assert "u1:over" not in ctx._semantic_cache


# ── _update_semantic_cache deep ─────────────────────────────────────────────


class TestUpdateSemanticCacheDeep:
    def test_with_intent_none_response(self):
        ctx = ChatContext()
        turn = ChatTurn("u1", "msg", "intent1", "tool1", {}, None)
        ctx._update_semantic_cache("u1", turn)
        assert len(ctx._semantic_cache) == 1
        # Verify the cached response is None
        for key, (resp, ts) in ctx._semantic_cache.items():
            assert resp is None

    def test_triggers_cleanup(self):
        """_update_semantic_cache calls _cleanup_cache."""
        ctx = ChatContext()
        # Pre-populate with an expired entry
        ctx._semantic_cache["u1:old"] = ("resp", time.time() - 400)
        turn = ChatTurn("u1", "msg", "intent1", "tool1", {}, "resp")
        ctx._update_semantic_cache("u1", turn)
        # Old entry should be cleaned up
        assert "u1:old" not in ctx._semantic_cache

    def test_multiple_users_same_intent(self):
        ctx = ChatContext()
        turn1 = ChatTurn("u1", "msg", "intent1", "tool1", {}, "resp1")
        turn2 = ChatTurn("u2", "msg", "intent1", "tool1", {}, "resp2")
        ctx._update_semantic_cache("u1", turn1)
        ctx._update_semantic_cache("u2", turn2)
        # Different cache keys (user_id prefix)
        assert len(ctx._semantic_cache) == 2


# ── get_history_summary deep ────────────────────────────────────────────────


class TestGetHistorySummaryDeep:
    def test_with_none_intents_in_recent(self):
        ctx = ChatContext()
        ctx.add_turn("u1", ChatTurn("u1", "m1", "intent1", None, {}, "r1"))
        ctx.add_turn("u1", ChatTurn("u1", "m2", None, None, {}, "r2"))
        ctx.add_turn("u1", ChatTurn("u1", "m3", "intent3", None, {}, "r3"))
        summary = ctx.get_history_summary("u1")
        # recent_intents filters out None
        assert None not in summary["recent_intents"]
        assert summary["last_intent"] == "intent3"
        assert summary["last_message"] == "m3"

    def test_empty_turns_after_clear(self):
        ctx = ChatContext()
        ctx.add_turn("u1", ChatTurn("u1", "m", "i", None, {}, "r"))
        ctx.clear_history("u1")
        summary = ctx.get_history_summary("u1")
        assert summary == {"has_history": False, "count": 0}

    def test_single_turn(self):
        ctx = ChatContext()
        ctx.add_turn("u1", ChatTurn("u1", "m1", "intent1", None, {}, "r1"))
        summary = ctx.get_history_summary("u1")
        assert summary["count"] == 1
        assert summary["last_message"] == "m1"
        assert summary["last_intent"] == "intent1"


# ── cleanup_old_history deep ────────────────────────────────────────────────


class TestCleanupOldHistoryDeep:
    def test_mixed_old_and_new_same_user(self):
        ctx = ChatContext()
        old_turn = ChatTurn("u1", "old", None, None, {}, None)
        old_turn.timestamp = time.time() - 7200
        new_turn = ChatTurn("u1", "new", None, None, {}, None)
        ctx._history["u1"] = [old_turn, new_turn]
        cleaned = ctx.cleanup_old_history(max_age_seconds=3600)
        assert cleaned == 1
        assert len(ctx._history["u1"]) == 1
        assert ctx._history["u1"][0].message == "new"

    def test_all_old_for_user_deletes_user(self):
        ctx = ChatContext()
        old_turn = ChatTurn("u1", "old", None, None, {}, None)
        old_turn.timestamp = time.time() - 7200
        ctx._history["u1"] = [old_turn]
        cleaned = ctx.cleanup_old_history(max_age_seconds=3600)
        assert cleaned == 1
        assert "u1" not in ctx._history

    def test_multiple_users_mixed(self):
        ctx = ChatContext()
        old_turn = ChatTurn("u1", "old", None, None, {}, None)
        old_turn.timestamp = time.time() - 7200
        new_turn = ChatTurn("u2", "new", None, None, {}, None)
        ctx._history["u1"] = [old_turn]
        ctx._history["u2"] = [new_turn]
        cleaned = ctx.cleanup_old_history(max_age_seconds=3600)
        assert cleaned == 1
        assert "u1" not in ctx._history
        assert "u2" in ctx._history

    def test_custom_max_age_zero(self):
        """max_age_seconds=0 → everything is old."""
        ctx = ChatContext()
        ctx.add_turn("u1", ChatTurn("u1", "m", None, None, {}, None))
        cleaned = ctx.cleanup_old_history(max_age_seconds=0)
        # now - timestamp > 0 is True for any past timestamp
        assert cleaned >= 1
        assert "u1" not in ctx._history


# ── get_recent_turns deep ───────────────────────────────────────────────────


class TestGetRecentTurnsDeep:
    def test_limit_larger_than_history(self):
        ctx = ChatContext()
        ctx.add_turn("u1", ChatTurn("u1", "m1", None, None, {}, None))
        turns = ctx.get_recent_turns("u1", limit=100)
        assert len(turns) == 1

    def test_negative_limit_returns_all(self):
        ctx = ChatContext()
        for i in range(3):
            ctx.add_turn("u1", ChatTurn("u1", f"m{i}", None, None, {}, None))
        # limit <= 0 returns all
        turns = ctx.get_recent_turns("u1", limit=-1)
        assert len(turns) == 3


# ── cache_response deep ─────────────────────────────────────────────────────


class TestCacheResponseDeep:
    def test_cache_triggers_cleanup(self):
        ctx = ChatContext()
        # Pre-populate with expired entry
        ctx._exact_cache["u1:old"] = ("resp", time.time() - 100)
        ctx.cache_response("u1", "new_msg", "new_resp")
        # Old entry should be cleaned up
        assert "u1:old" not in ctx._exact_cache

    def test_cache_empty_message(self):
        ctx = ChatContext()
        ctx.cache_response("u1", "", "resp")
        is_dup, cached, exact = ctx.is_duplicate("u1", "")
        assert is_dup is True
        assert cached == "resp"


# ── ChatContextContainer deep ───────────────────────────────────────────────


class TestChatContextContainerDeep:
    def test_reset_clears_singleton(self):
        ChatContextContainer.reset()
        ctx1 = ChatContextContainer.get_instance()
        ctx1.add_turn("u1", ChatTurn("u1", "m", None, None, {}, None))
        ChatContextContainer.reset()
        ctx2 = ChatContextContainer.get_instance()
        # New instance has no history
        assert ctx2.get_recent_turns("u1") == []
        assert ctx1 is not ctx2

    def test_get_chat_context_after_reset(self):
        ChatContextContainer.reset()
        ctx1 = get_chat_context()
        ChatContextContainer.reset()
        ctx2 = get_chat_context()
        assert ctx1 is not ctx2

    def test_multiple_resets(self):
        ChatContextContainer.reset()
        ChatContextContainer.reset()
        ctx = ChatContextContainer.get_instance()
        assert ctx is not None

    def test_instance_persists_add_turns(self):
        ChatContextContainer.reset()
        ctx = ChatContextContainer.get_instance()
        ctx.add_turn("u1", ChatTurn("u1", "m", "i", None, {}, "r"))
        ctx2 = ChatContextContainer.get_instance()
        assert ctx is ctx2
        assert len(ctx2.get_recent_turns("u1")) == 1
        ChatContextContainer.reset()
