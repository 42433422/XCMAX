# mypy: disable-error-code="index"
"""app/services/conversation/modstore_adapter 纯函数单测。"""

from __future__ import annotations

import json

import httpx
import pytest

from app.domain.shared_services.conversation.modstore_adapter import (
    _iter_market_sse_data_payloads,
    _iter_market_transport_plans,
    _market_connect_attempts,
    _market_connect_timeout,
    _normalize_stream_choice,
    _platform_stream_payload_to_openai_chunk,
    _strip_bearer_prefix,
    _to_openai_object,
)
from app.infrastructure.llm.modstore_response_normalize import normalize_market_chat_response
from app.infrastructure.modstore_transport import (
    aiter_market_sse_data_payloads,
    safe_route_metadata,
)

ROUTE = {
    "provider": "xiaomi",
    "model": "mimo-v2.6-flash",
    "route_source": "platform_default",
    "key_source": "platform",
    "config_revision": "revision-2",
}


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
        with pytest.raises(ValueError, match="模型服务请求失败"):
            _platform_stream_payload_to_openai_chunk('{"type":"error","message":"boom"}')

    def test_iter_market_sse_preserves_meta_and_surfaces_done_content(self) -> None:
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
        assert json.loads(payloads[0]) == {"route_metadata": {"provider": "xiaomi"}}
        assert "最终回复" in payloads[1]

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


@pytest.mark.parametrize("choices", [False, True])
def test_completion_metadata_uses_executed_route_and_omits_credentials(choices):
    raw = {
        **ROUTE,
        "content": "完成",
        "api_key": "fixture-secret",
        "api_key_masked": "fixture-mask",
        "base_url": "https://fixture.invalid",
    }
    if choices:
        raw["choices"] = [{"message": {"content": "完成"}}]
    result = normalize_market_chat_response(raw, "old-provider", "old-model")
    assert result["model"] == ROUTE["model"]
    assert result["route_metadata"] == ROUTE
    assert {key: result["_modstore_meta"][key] for key in ROUTE} == ROUTE
    assert "fixture-secret" not in json.dumps(result)
    assert "fixture-mask" not in json.dumps(result)
    assert "fixture.invalid" not in json.dumps(result)


@pytest.mark.parametrize("done_content", ["", "完成"])
@pytest.mark.asyncio
async def test_sync_async_stream_identity_survives_without_duplicate_content(done_content):
    # Metadata is additive; final full text must not replay an emitted delta.
    private = {**ROUTE, "api_key": "fixture-secret", "route_token": "fixture-token"}
    text = (
        f"event: meta\ndata: {json.dumps(private)}\n\n"
        'event: delta\ndata: {"delta":"完成"}\n\n'
        f"event: done\ndata: {json.dumps({**private, 'content': done_content})}\n\n"
    )
    response = httpx.Response(200, text=text)
    sync = list(_iter_market_sse_data_payloads(response))
    asynchronous = [
        data
        async for data in aiter_market_sse_data_payloads(
            httpx.Response(200, text=text),
            payload_has_content=lambda data: bool(json.loads(data).get("delta")),
        )
    ]
    assert sync == asynchronous
    chunks = [_platform_stream_payload_to_openai_chunk(data) for data in sync]
    assert chunks[0] == {"choices": [], "route_metadata": ROUTE}
    assert chunks[-1] == {"choices": [], "route_metadata": ROUTE}
    assert [c["choices"][0]["delta"]["content"] for c in chunks if c["choices"]] == ["完成"]
    assert all("fixture-secret" not in data and "fixture-token" not in data for data in sync)


def test_route_metadata_rejects_nested_objects_and_private_fields():
    assert safe_route_metadata({"route_metadata": {**ROUTE, "api_key": "private"}}) == ROUTE
    assert safe_route_metadata({"provider": {"api_key": "private"}, "config_revision": True}) == {}
    assert safe_route_metadata(None) == {}
