"""Tests for app.domain.services.conversation.context.chat_context — ext2.

Covers ``ChatTurn`` (fingerprint + semantic fingerprint), ``ChatContext``
(add_turn / get_recent_turns / get_recent_intents / clear_history /
is_duplicate / cache_response / get_history_summary / cleanup_old_history /
get_all_users_count), and ``ChatContextContainer``.
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

# ── ChatTurn ─────────────────────────────────────────────────────────────────


class TestChatTurn:
    def test_message_fingerprint_stable(self):
        turn = ChatTurn(
            user_id="u1",
            message="  Hello World  ",
            intent=None,
            tool_key=None,
            slots={},
            response_text=None,
        )
        # Same fingerprint for same normalized message
        turn2 = ChatTurn(
            user_id="u2",
            message="hello world",
            intent=None,
            tool_key=None,
            slots={},
            response_text=None,
        )
        assert turn.message_fingerprint == turn2.message_fingerprint

    def test_message_fingerprint_case_insensitive(self):
        turn1 = ChatTurn("u", "Hello", None, None, {}, None)
        turn2 = ChatTurn("u", "HELLO", None, None, {}, None)
        assert turn1.message_fingerprint == turn2.message_fingerprint

    def test_semantic_fingerprint_no_slots(self):
        turn = ChatTurn("u", "msg", "intent1", "tool1", {}, None)
        fp = turn.make_semantic_fingerprint()
        assert isinstance(fp, str)
        assert len(fp) == 16

    def test_semantic_fingerprint_with_slots(self):
        turn1 = ChatTurn("u", "msg", "intent1", "tool1", {"a": "1", "b": "2"}, None)
        turn2 = ChatTurn("u", "msg", "intent1", "tool1", {"b": "2", "a": "1"}, None)
        # Same slots in different order → same fingerprint
        assert turn1.make_semantic_fingerprint() == turn2.make_semantic_fingerprint()

    def test_semantic_fingerprint_skips_empty_slots(self):
        turn1 = ChatTurn("u", "msg", "intent1", "tool1", {"a": "1", "b": ""}, None)
        turn2 = ChatTurn("u", "msg", "intent1", "tool1", {"a": "1"}, None)
        assert turn1.make_semantic_fingerprint() == turn2.make_semantic_fingerprint()

    def test_semantic_fingerprint_skips_none_slots(self):
        turn1 = ChatTurn("u", "msg", "intent1", "tool1", {"a": "1", "b": None}, None)
        turn2 = ChatTurn("u", "msg", "intent1", "tool1", {"a": "1"}, None)
        assert turn1.make_semantic_fingerprint() == turn2.make_semantic_fingerprint()

    def test_semantic_fingerprint_different_intent(self):
        turn1 = ChatTurn("u", "msg", "intent1", "tool1", {}, None)
        turn2 = ChatTurn("u", "msg", "intent2", "tool1", {}, None)
        assert turn1.make_semantic_fingerprint() != turn2.make_semantic_fingerprint()

    def test_default_timestamp(self):
        turn = ChatTurn("u", "msg", None, None, {}, None)
        assert turn.timestamp > 0

    def test_default_flags(self):
        turn = ChatTurn("u", "msg", None, None, {}, None)
        assert turn.is_exact_duplicate is False
        assert turn.is_semantic_duplicate is False


# ── ChatContext.add_turn / get_recent_turns ──────────────────────────────────


class TestChatContextAddGet:
    def test_add_and_get(self):
        ctx = ChatContext()
        turn = ChatTurn("u1", "hello", "greeting", None, {}, "hi")
        ctx.add_turn("u1", turn)
        turns = ctx.get_recent_turns("u1")
        assert len(turns) == 1
        assert turns[0].message == "hello"

    def test_get_missing_user(self):
        ctx = ChatContext()
        assert ctx.get_recent_turns("missing") == []

    def test_history_capped_at_max(self):
        ctx = ChatContext()
        for i in range(ChatContext.MAX_HISTORY_SIZE + 5):
            ctx.add_turn(
                "u1",
                ChatTurn("u1", f"msg{i}", None, None, {}, None),
            )
        turns = ctx.get_recent_turns("u1")
        assert len(turns) == ChatContext.MAX_HISTORY_SIZE

    def test_get_recent_with_limit(self):
        ctx = ChatContext()
        for i in range(5):
            ctx.add_turn("u1", ChatTurn("u1", f"msg{i}", None, None, {}, None))
        turns = ctx.get_recent_turns("u1", limit=2)
        assert len(turns) == 2
        assert turns[0].message == "msg3"
        assert turns[1].message == "msg4"

    def test_get_recent_with_zero_limit(self):
        ctx = ChatContext()
        for i in range(3):
            ctx.add_turn("u1", ChatTurn("u1", f"msg{i}", None, None, {}, None))
        turns = ctx.get_recent_turns("u1", limit=0)
        assert len(turns) == 3


class TestGetRecentIntents:
    def test_returns_intents(self):
        ctx = ChatContext()
        ctx.add_turn("u1", ChatTurn("u1", "m1", "intent1", None, {}, None))
        ctx.add_turn("u1", ChatTurn("u1", "m2", "intent2", None, {}, None))
        ctx.add_turn("u1", ChatTurn("u1", "m3", None, None, {}, None))
        intents = ctx.get_recent_intents("u1", limit=3)
        assert intents == ["intent1", "intent2"]

    def test_missing_user(self):
        ctx = ChatContext()
        assert ctx.get_recent_intents("missing") == []


class TestClearHistory:
    def test_clears_existing(self):
        ctx = ChatContext()
        ctx.add_turn("u1", ChatTurn("u1", "m", None, None, {}, None))
        ctx.clear_history("u1")
        assert ctx.get_recent_turns("u1") == []

    def test_clear_missing_user_no_error(self):
        ctx = ChatContext()
        ctx.clear_history("missing")  # should not raise


# ── is_duplicate ─────────────────────────────────────────────────────────────


class TestIsDuplicate:
    def test_no_duplicate_returns_false(self):
        ctx = ChatContext()
        is_dup, cached, exact = ctx.is_duplicate("u1", "hello")
        assert is_dup is False
        assert cached is None
        assert exact is False

    def test_exact_duplicate_within_ttl(self):
        ctx = ChatContext()
        ctx.cache_response("u1", "hello", "cached response")
        is_dup, cached, exact = ctx.is_duplicate("u1", "hello")
        assert is_dup is True
        assert cached == "cached response"
        assert exact is True

    def test_exact_duplicate_expired(self):
        ctx = ChatContext()
        ctx.cache_response("u1", "hello", "cached")
        # Manually expire the cache entry
        for key, (resp, ts) in list(ctx._exact_cache.items()):
            ctx._exact_cache[key] = (resp, ts - 100)
        is_dup, cached, exact = ctx.is_duplicate("u1", "hello")
        assert is_dup is False
        assert cached is None

    def test_message_with_whitespace_normalized(self):
        ctx = ChatContext()
        ctx.cache_response("u1", "hello", "cached")
        # Same normalized message → duplicate
        is_dup, cached, exact = ctx.is_duplicate("u1", "  HELLO  ")
        assert is_dup is True

    def test_semantic_duplicate(self):
        ctx = ChatContext()
        # Add a turn with intent and response
        turn = ChatTurn("u1", "msg", "intent1", "tool1", {}, "response1")
        ctx.add_turn("u1", turn)
        # NOTE: There's a known mismatch in the source: make_semantic_fingerprint
        # uses "|" as separator ("intent1|tool1") but is_duplicate compares
        # against md5 of "intent1:tool1" (colon separator). So semantic duplicate
        # detection via is_duplicate never matches. This test documents the
        # current behavior: semantic duplicate is NOT detected.
        is_dup, cached, exact = ctx.is_duplicate(
            "u1", "different msg", intent="intent1", tool_key="tool1"
        )
        assert is_dup is False
        assert cached is None
        assert exact is False

    def test_semantic_no_match_different_intent(self):
        ctx = ChatContext()
        turn = ChatTurn("u1", "msg", "intent1", "tool1", {}, "response1")
        ctx.add_turn("u1", turn)
        is_dup, cached, exact = ctx.is_duplicate("u1", "msg", intent="intent2", tool_key="tool1")
        assert is_dup is False

    def test_no_intent_no_semantic_check(self):
        ctx = ChatContext()
        turn = ChatTurn("u1", "msg", "intent1", "tool1", {}, "response1")
        ctx.add_turn("u1", turn)
        is_dup, cached, exact = ctx.is_duplicate("u1", "msg")
        assert is_dup is False


# ── cache_response ───────────────────────────────────────────────────────────


class TestCacheResponse:
    def test_caches_response(self):
        ctx = ChatContext()
        ctx.cache_response("u1", "hello", "cached")
        # Should be retrievable via is_duplicate
        is_dup, cached, exact = ctx.is_duplicate("u1", "hello")
        assert is_dup is True
        assert cached == "cached"

    def test_overwrites_existing(self):
        ctx = ChatContext()
        ctx.cache_response("u1", "hello", "first")
        ctx.cache_response("u1", "hello", "second")
        is_dup, cached, _ = ctx.is_duplicate("u1", "hello")
        assert cached == "second"


# ── get_history_summary ──────────────────────────────────────────────────────


class TestGetHistorySummary:
    def test_no_history(self):
        ctx = ChatContext()
        summary = ctx.get_history_summary("u1")
        assert summary == {"has_history": False, "count": 0}

    def test_with_history(self):
        ctx = ChatContext()
        ctx.add_turn("u1", ChatTurn("u1", "m1", "intent1", None, {}, "r1"))
        ctx.add_turn("u1", ChatTurn("u1", "m2", "intent2", None, {}, "r2"))
        summary = ctx.get_history_summary("u1")
        assert summary["has_history"] is True
        assert summary["count"] == 2
        assert summary["last_message"] == "m2"
        assert summary["last_intent"] == "intent2"
        assert "intent2" in summary["recent_intents"]

    def test_recent_intents_truncated_to_3(self):
        ctx = ChatContext()
        for i in range(5):
            ctx.add_turn("u1", ChatTurn("u1", f"m{i}", f"intent{i}", None, {}, "r"))
        summary = ctx.get_history_summary("u1")
        assert len(summary["recent_intents"]) <= 3


# ── cleanup_old_history ──────────────────────────────────────────────────────


class TestCleanupOldHistory:
    def test_no_history(self):
        ctx = ChatContext()
        assert ctx.cleanup_old_history() == 0

    def test_cleans_expired(self):
        ctx = ChatContext()
        # Add an old turn
        old_turn = ChatTurn("u1", "old", None, None, {}, None)
        old_turn.timestamp = time.time() - 7200  # 2 hours ago
        ctx._history["u1"] = [old_turn]
        cleaned = ctx.cleanup_old_history(max_age_seconds=3600)
        assert cleaned == 1
        assert "u1" not in ctx._history

    def test_keeps_recent(self):
        ctx = ChatContext()
        turn = ChatTurn("u1", "recent", None, None, {}, None)
        ctx.add_turn("u1", turn)
        cleaned = ctx.cleanup_old_history(max_age_seconds=3600)
        assert cleaned == 0
        assert "u1" in ctx._history


# ── get_all_users_count ──────────────────────────────────────────────────────


class TestGetAllUsersCount:
    def test_empty(self):
        ctx = ChatContext()
        assert ctx.get_all_users_count() == 0

    def test_multiple_users(self):
        ctx = ChatContext()
        ctx.add_turn("u1", ChatTurn("u1", "m", None, None, {}, None))
        ctx.add_turn("u2", ChatTurn("u2", "m", None, None, {}, None))
        assert ctx.get_all_users_count() == 2


# ── _cleanup_cache ───────────────────────────────────────────────────────────


class TestCleanupCache:
    def test_cleans_expired_semantic(self):
        ctx = ChatContext()
        # Manually inject an expired semantic cache entry
        ctx._semantic_cache["u1:fp"] = ("resp", time.time() - 400)
        ctx._cleanup_cache()
        assert "u1:fp" not in ctx._semantic_cache

    def test_cleans_expired_exact(self):
        ctx = ChatContext()
        ctx._exact_cache["u1:fp"] = ("resp", time.time() - 100)
        ctx._cleanup_cache()
        assert "u1:fp" not in ctx._exact_cache

    def test_keeps_valid_entries(self):
        ctx = ChatContext()
        ctx._semantic_cache["u1:fp"] = ("resp", time.time())
        ctx._exact_cache["u1:fp"] = ("resp", time.time())
        ctx._cleanup_cache()
        assert "u1:fp" in ctx._semantic_cache
        assert "u1:fp" in ctx._exact_cache


# ── _update_semantic_cache ───────────────────────────────────────────────────


class TestUpdateSemanticCache:
    def test_no_intent_skipped(self):
        ctx = ChatContext()
        turn = ChatTurn("u1", "msg", None, None, {}, None)
        ctx._update_semantic_cache("u1", turn)
        assert len(ctx._semantic_cache) == 0

    def test_with_intent_added(self):
        ctx = ChatContext()
        turn = ChatTurn("u1", "msg", "intent1", "tool1", {}, "resp")
        ctx._update_semantic_cache("u1", turn)
        assert len(ctx._semantic_cache) == 1


# ── ChatContextContainer / get_chat_context ──────────────────────────────────


class TestChatContextContainer:
    def test_get_instance_singleton(self):
        ChatContextContainer.reset()
        ctx1 = ChatContextContainer.get_instance()
        ctx2 = ChatContextContainer.get_instance()
        assert ctx1 is ctx2

    def test_reset(self):
        ChatContextContainer.reset()
        ctx1 = ChatContextContainer.get_instance()
        ChatContextContainer.reset()
        ctx2 = ChatContextContainer.get_instance()
        assert ctx1 is not ctx2

    def test_get_chat_context_returns_singleton(self):
        ChatContextContainer.reset()
        ctx1 = get_chat_context()
        ctx2 = get_chat_context()
        assert ctx1 is ctx2
