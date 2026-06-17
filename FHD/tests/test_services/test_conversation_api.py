"""Tests for app.services.conversation.api — ApiMixin pure/static methods."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.conversation.api import _make_ai_response_cache_key

# ========================= _make_ai_response_cache_key ===================


class TestMakeAiResponseCacheKey:
    def test_deterministic(self):
        key1 = _make_ai_response_cache_key("hello", "ctx1")
        key2 = _make_ai_response_cache_key("hello", "ctx1")
        assert key1 == key2

    def test_different_message(self):
        key1 = _make_ai_response_cache_key("hello", "ctx1")
        key2 = _make_ai_response_cache_key("world", "ctx1")
        assert key1 != key2

    def test_different_context(self):
        key1 = _make_ai_response_cache_key("hello", "ctx1")
        key2 = _make_ai_response_cache_key("hello", "ctx2")
        assert key1 != key2

    def test_empty_context_hash(self):
        key1 = _make_ai_response_cache_key("hello", "")
        assert isinstance(key1, str)
        assert len(key1) == 64  # SHA-256 hex digest

    def test_case_insensitive_message(self):
        key1 = _make_ai_response_cache_key("Hello", "ctx1")
        key2 = _make_ai_response_cache_key("hello", "ctx1")
        assert key1 == key2

    def test_whitespace_stripped(self):
        key1 = _make_ai_response_cache_key("  hello  ", "ctx1")
        key2 = _make_ai_response_cache_key("hello", "ctx1")
        assert key1 == key2


# ========================= _call_ai_offline ==============================


class TestCallAiOffline:
    def test_with_known_intent(self):
        from app.services.conversation.api import ApiMixin
        from app.services.conversation.context import ConversationContext

        m = ApiMixin()
        m.add_to_history = MagicMock()
        ctx = ConversationContext(user_id="user1")
        intent_result = {"final_intent": "shipment_generate", "primary_intent": "shipment_generate"}

        import asyncio

        result = asyncio.get_event_loop().run_until_complete(
            m._call_ai_offline("生成发货单", ctx, intent_result)
        )
        assert result["action"] == "offline_response"
        assert "shipment_generate" in result["text"]
        assert result["data"]["mode"] == "offline"

    def test_with_unknown_intent(self):
        from app.services.conversation.api import ApiMixin
        from app.services.conversation.context import ConversationContext

        m = ApiMixin()
        m.add_to_history = MagicMock()
        ctx = ConversationContext(user_id="user1")
        intent_result = {"final_intent": "unk", "primary_intent": "unk"}

        import asyncio

        result = asyncio.get_event_loop().run_until_complete(
            m._call_ai_offline("hello", ctx, intent_result)
        )
        assert result["action"] == "offline_response"
        assert "离线模式" in result["text"]


# ========================= _maybe_attach_kitten_web ======================


class TestMaybeAttachKittenWeb:
    def test_no_kitten(self):
        from app.services.conversation.api import ApiMixin
        from app.services.conversation.context import ConversationContext

        m = ApiMixin()
        ctx = ConversationContext(user_id="u1", metadata={})
        result = {"text": "hello", "data": {}}
        out = m._maybe_attach_kitten_web(ctx, result)
        assert "web_search_results" not in out.get("data", {})

    def test_with_kitten(self):
        from app.services.conversation.api import ApiMixin
        from app.services.conversation.context import ConversationContext

        m = ApiMixin()
        ctx = ConversationContext(
            user_id="u1",
            metadata={
                "request_context": {
                    "kitten_analyzer": True,
                    "kitten_web_search": True,
                    "web_search_results": [{"title": "test"}],
                    "web_search_meta": {"source": "bing"},
                    "web_search_error": None,
                }
            },
        )
        result = {"text": "hello", "data": {}}
        out = m._maybe_attach_kitten_web(ctx, result)
        assert out["data"]["web_search_results"] == [{"title": "test"}]
        assert out["data"]["web_search_meta"] == {"source": "bing"}

    def test_with_error(self):
        from app.services.conversation.api import ApiMixin
        from app.services.conversation.context import ConversationContext

        m = ApiMixin()
        ctx = ConversationContext(
            user_id="u1",
            metadata={
                "request_context": {
                    "kitten_analyzer": True,
                    "kitten_web_search": True,
                    "web_search_results": [],
                    "web_search_error": "timeout",
                }
            },
        )
        result = {"text": "hello", "data": {}}
        out = m._maybe_attach_kitten_web(ctx, result)
        assert out["data"]["web_search_error"] == "timeout"

    def test_no_data_key(self):
        from app.services.conversation.api import ApiMixin
        from app.services.conversation.context import ConversationContext

        m = ApiMixin()
        ctx = ConversationContext(
            user_id="u1",
            metadata={
                "request_context": {
                    "kitten_analyzer": True,
                    "kitten_web_search": True,
                    "web_search_results": [{"title": "test"}],
                }
            },
        )
        result = {"text": "hello"}
        out = m._maybe_attach_kitten_web(ctx, result)
        assert out["data"]["web_search_results"] == [{"title": "test"}]
