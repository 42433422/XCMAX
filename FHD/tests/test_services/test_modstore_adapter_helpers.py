"""app/services/conversation/modstore_adapter 纯函数单测。"""

from __future__ import annotations

import pytest

from app.services.conversation.modstore_adapter import (
    _normalize_stream_choice,
    _platform_stream_payload_to_openai_chunk,
    _strip_bearer_prefix,
    _to_openai_object,
)


class TestModstoreAdapterHelpers:
    def test_strip_bearer_prefix(self) -> None:
        assert _strip_bearer_prefix("Bearer abc") == "abc"
        assert _strip_bearer_prefix("token") == "token"

    def test_to_openai_object_nested(self) -> None:
        obj = _to_openai_object({"a": 1, "b": [{"c": 2}]})
        assert obj.a == 1
        assert obj.b[0].c == 2

    def test_normalize_stream_choice_with_delta(self) -> None:
        choice = {"index": 0, "delta": {"content": "hi"}, "finish_reason": None}
        assert _normalize_stream_choice(choice) == choice

    def test_normalize_stream_choice_from_message(self) -> None:
        choice = {"index": 0, "message": {"content": "hello"}, "finish_reason": "stop"}
        out = _normalize_stream_choice(choice)
        assert out["delta"]["content"] == "hello"

    def test_platform_stream_done_returns_none(self) -> None:
        assert _platform_stream_payload_to_openai_chunk("[DONE]") is None

    def test_platform_stream_plain_text(self) -> None:
        out = _platform_stream_payload_to_openai_chunk("hello")
        assert out["choices"][0]["delta"]["content"] == "hello"

    def test_platform_stream_json_choices(self) -> None:
        payload = '{"choices":[{"message":{"content":"x"},"finish_reason":null}]}'
        out = _platform_stream_payload_to_openai_chunk(payload)
        assert out is not None
        assert out["choices"][0]["delta"]["content"] == "x"

    def test_platform_stream_error_raises(self) -> None:
        with pytest.raises(ValueError, match="boom"):
            _platform_stream_payload_to_openai_chunk('{"type":"error","message":"boom"}')
