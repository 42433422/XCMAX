"""app/services/conversation/modstore_adapter 纯函数单测。"""

from __future__ import annotations

import pytest

from app.services.conversation.modstore_adapter import (
    _iter_market_sse_data_payloads,
    _iter_market_transport_plans,
    _market_connect_attempts,
    _market_connect_timeout,
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

    def test_iter_market_sse_skips_meta_and_surfaces_done_content(self) -> None:
        class _Resp:
            def iter_lines(self):
                return iter(
                    [
                        "event: meta",
                        'data: {"ok": true, "provider": "xiaomi"}',
                        "event: done",
                        'data: {"ok": true, "content": "最终回复"}',
                    ]
                )

        payloads = list(_iter_market_sse_data_payloads(_Resp()))
        assert len(payloads) == 1
        assert "最终回复" in payloads[0]

    def test_iter_market_sse_yields_delta(self) -> None:
        class _Resp:
            def iter_lines(self):
                return iter(
                    [
                        "event: delta",
                        'data: {"delta": "hello"}',
                        "event: done",
                        'data: {"ok": true, "content": "hello"}',
                    ]
                )

        payloads = list(_iter_market_sse_data_payloads(_Resp()))
        # 平台 done 恒带全文；已有内容 delta 时不再转发，否则 UI 重复（"2"→"22"）。
        assert payloads == ['{"delta": "hello"}']

    def test_iter_market_sse_surfaces_done_content_after_empty_delta(self) -> None:
        class _Resp:
            def iter_lines(self):
                return iter(
                    [
                        "event: delta",
                        'data: {"delta": ""}',
                        "event: done",
                        'data: {"ok": true, "content": "最终回复"}',
                    ]
                )

        payloads = list(_iter_market_sse_data_payloads(_Resp()))
        # 空 delta 不算内容，done 全文仍需兜底（部分供应商只在 done 放正文）。
        assert len(payloads) == 2
        assert payloads[0] == '{"delta": ""}'
        assert "最终回复" in payloads[1]

    def test_market_connect_timeout_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("XCAGI_MARKET_CONNECT_TIMEOUT", raising=False)
        assert _market_connect_timeout() == 20.0
        monkeypatch.setenv("XCAGI_MARKET_CONNECT_TIMEOUT", "8")
        assert _market_connect_timeout() == 8.0

    def test_iter_market_transport_plans_includes_fallback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("XCAGI_MARKET_CONNECT_ATTEMPTS", "2")
        monkeypatch.setenv("XCAGI_MARKET_FALLBACK_PROXY", "http://127.0.0.1:7890")
        plans = list(_iter_market_transport_plans())
        assert plans == [
            (None, 1, 2),
            (None, 2, 2),
            ("http://127.0.0.1:7890", 1, 2),
            ("http://127.0.0.1:7890", 2, 2),
        ]
        assert _market_connect_attempts() == 2
