"""app/services/conversation/api 缓存 key 单测。"""

from __future__ import annotations

from app.services.conversation.api import _make_ai_response_cache_key


def test_ai_response_cache_key_normalizes() -> None:
    k1 = _make_ai_response_cache_key(" Hello ", "ctx")
    k2 = _make_ai_response_cache_key("hello", "ctx")
    assert k1 == k2
    assert len(k1) == 64


def test_ai_response_cache_key_diff_context() -> None:
    k1 = _make_ai_response_cache_key("hi", "a")
    k2 = _make_ai_response_cache_key("hi", "b")
    assert k1 != k2
