"""COVERAGE_RAMP Phase 4 round 12: modstore_adapter pure helpers + sync facade (22%→)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.services.conversation.modstore_adapter import (
    ModstoreOpenAICompatibleClient,
    ModstorePlatformAdapter,
    _normalize_stream_choice,
    _platform_stream_payload_to_openai_chunk,
    _strip_bearer_prefix,
    _to_openai_object,
    create_modstore_adapter_from_env,
    create_modstore_openai_client_from_request,
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch):
    for k in (
        "MODSTORE_PLATFORM_URL",
        "MODSTORE_AUTH_TOKEN",
        "MODSTORE_USER_ID",
        "LLM_PROVIDER",
        "LLM_MODEL",
        "XCAGI_MARKET_BASE_URL",
    ):
        monkeypatch.delenv(k, raising=False)


# ---------------------------------------------------------------------------
# module-level pure helpers
# ---------------------------------------------------------------------------


def test_strip_bearer_prefix() -> None:
    assert _strip_bearer_prefix("Bearer abc123") == "abc123"
    assert _strip_bearer_prefix("  plain  ") == "plain"
    assert _strip_bearer_prefix("") == ""


def test_to_openai_object() -> None:
    obj = _to_openai_object({"a": 1, "nested": {"b": 2}, "items": [{"c": 3}]})
    assert obj.a == 1
    assert obj.nested.b == 2
    assert obj.items[0].c == 3
    assert _to_openai_object("scalar") == "scalar"


def test_normalize_stream_choice_delta_passthrough() -> None:
    choice = {"delta": {"content": "x"}, "index": 0}
    assert _normalize_stream_choice(choice) is choice


def test_normalize_stream_choice_message_to_delta() -> None:
    choice = {
        "message": {"content": "hi", "tool_calls": [{"id": "t"}]},
        "index": 2,
        "finish_reason": "stop",
    }
    out = _normalize_stream_choice(choice)
    assert out["delta"]["content"] == "hi"
    assert out["delta"]["tool_calls"] == [{"id": "t"}]
    assert out["index"] == 2


def test_normalize_stream_choice_empty() -> None:
    out = _normalize_stream_choice({})
    assert out["delta"] == {}


def test_platform_stream_payload_done_and_empty() -> None:
    assert _platform_stream_payload_to_openai_chunk("[DONE]") is None
    assert _platform_stream_payload_to_openai_chunk("") is None


def test_platform_stream_payload_invalid_json() -> None:
    out = _platform_stream_payload_to_openai_chunk("not json")
    assert out["choices"][0]["delta"]["content"] == "not json"


def test_platform_stream_payload_with_choices() -> None:
    out = _platform_stream_payload_to_openai_chunk('{"choices": [{"message": {"content": "hey"}}]}')
    assert out["choices"][0]["delta"]["content"] == "hey"


def test_platform_stream_payload_error_raises() -> None:
    with pytest.raises(ValueError):
        _platform_stream_payload_to_openai_chunk('{"type": "error", "message": "boom"}')


def test_platform_stream_payload_content_field() -> None:
    out = _platform_stream_payload_to_openai_chunk('{"content": "partial"}')
    assert out["choices"][0]["delta"]["content"] == "partial"


def test_platform_stream_payload_none_dict() -> None:
    assert _platform_stream_payload_to_openai_chunk("{}") is None


# ---------------------------------------------------------------------------
# adapter init / parse / properties
# ---------------------------------------------------------------------------


def test_parse_user_id() -> None:
    assert ModstorePlatformAdapter._parse_user_id("42") == 42
    assert ModstorePlatformAdapter._parse_user_id("") is None
    assert ModstorePlatformAdapter._parse_user_id("notint") is None


def test_init_defaults() -> None:
    a = ModstorePlatformAdapter()
    assert a.platform_url == "http://localhost:8000"
    assert a.default_provider == "xiaomi"
    assert a.default_model == "mimo-v2.5-pro"
    assert a.auth_token == ""


def test_init_explicit_strips_bearer() -> None:
    a = ModstorePlatformAdapter(platform_url="http://h/", auth_token="Bearer tk", user_id=7)
    assert a.platform_url == "http://h"  # trailing slash stripped
    assert a.auth_token == "tk"
    assert a.user_id == 7


def test_properties() -> None:
    a = ModstorePlatformAdapter(platform_url="http://h", default_provider="xiaomi")
    assert a.provider_name == "modstore-xiaomi"
    assert a.model_name == a.default_model
    assert a.is_configured is True
    a.platform_url = ""
    assert a.is_configured is False


def test_build_headers() -> None:
    a = ModstorePlatformAdapter(platform_url="http://h", auth_token="tok")
    headers = a._build_headers()
    assert headers["Authorization"] == "Bearer tok"
    assert headers["Content-Type"] == "application/json"
    a2 = ModstorePlatformAdapter(platform_url="http://h")
    assert "Authorization" not in a2._build_headers()


def test_repr() -> None:
    a = ModstorePlatformAdapter(platform_url="http://h", auth_token="abcdef")
    text = repr(a)
    assert "ModstorePlatformAdapter" in text
    assert "http://h" in text


# ---------------------------------------------------------------------------
# _resolve_provider_model
# ---------------------------------------------------------------------------


def test_resolve_provider_model_defaults() -> None:
    a = ModstorePlatformAdapter(platform_url="http://h")
    prov, model = a._resolve_provider_model()
    assert prov == "xiaomi"
    assert model == "mimo-v2.5-pro"


def test_resolve_provider_model_explicit() -> None:
    a = ModstorePlatformAdapter(platform_url="http://h")
    prov, model = a._resolve_provider_model(provider="DeepSeek", model="chat")
    assert prov == "deepseek"
    assert model == "chat"


def test_resolve_provider_model_slash_split() -> None:
    a = ModstorePlatformAdapter(platform_url="http://h")
    prov, model = a._resolve_provider_model(model="anthropic/claude-3")
    assert prov == "anthropic"
    assert model == "claude-3"


# ---------------------------------------------------------------------------
# _normalize_response
# ---------------------------------------------------------------------------


def test_normalize_response_with_choices() -> None:
    a = ModstorePlatformAdapter(platform_url="http://h")
    raw = {
        "choices": [
            {"message": {"role": "assistant", "content": "答复", "tool_calls": [{"id": "x"}]}}
        ],
        "usage": {"total_tokens": 10},
        "model": "xiaomi/mimo",
        "success": True,
    }
    out = a._normalize_response(raw, "xiaomi", "mimo")
    assert out["choices"][0]["message"]["content"] == "答复"
    assert out["choices"][0]["message"]["tool_calls"] == [{"id": "x"}]
    assert out["usage"]["total_tokens"] == 10
    assert out["_modstore_meta"]["success"] is True


def test_normalize_response_content_only() -> None:
    a = ModstorePlatformAdapter(platform_url="http://h")
    raw = {"content": "纯文本", "usage": {"total_tokens": 3}}
    out = a._normalize_response(raw, "xiaomi", "mimo")
    assert out["choices"][0]["message"]["content"] == "纯文本"
    assert out["model"] == "xiaomi/mimo"


def test_normalize_response_usage_object() -> None:
    a = ModstorePlatformAdapter(platform_url="http://h")
    usage_obj = SimpleNamespace(total_tokens=5, prompt_tokens=2)
    raw = {"content": "x", "usage": usage_obj, "tool_calls": [{"id": "tc"}]}
    out = a._normalize_response(raw, "p", "m")
    assert out["usage"]["total_tokens"] == 5
    assert out["choices"][0]["message"]["tool_calls"] == [{"id": "tc"}]


# ---------------------------------------------------------------------------
# factory + openai-compatible facade
# ---------------------------------------------------------------------------


def test_create_from_env_none() -> None:
    assert create_modstore_adapter_from_env() is None


def test_create_from_env_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODSTORE_PLATFORM_URL", "http://platform")
    adapter = create_modstore_adapter_from_env()
    assert adapter is not None
    assert adapter.platform_url == "http://platform"


def test_openai_client_create_non_stream() -> None:
    adapter = ModstorePlatformAdapter(platform_url="http://h")
    normalized = {
        "choices": [{"message": {"role": "assistant", "content": "结果"}, "index": 0}],
        "model": "xiaomi/mimo",
    }
    with patch.object(adapter, "chat_completion_sync", return_value=normalized) as m:
        client = ModstoreOpenAICompatibleClient(adapter)
        resp = client.chat.completions.create(messages=[{"role": "user", "content": "hi"}])
    assert resp.choices[0].message.content == "结果"
    assert client.default_model == adapter.default_model
    assert client.default_provider == adapter.default_provider
    m.assert_called_once()


def test_openai_client_create_stream_synthetic(monkeypatch: pytest.MonkeyPatch) -> None:
    # non-native stream path -> single synthetic chunk from chat_completion_sync
    monkeypatch.setenv("XCAGI_MODSTORE_USE_NATIVE_STREAM", "0")
    adapter = ModstorePlatformAdapter(platform_url="http://h")
    normalized = {
        "choices": [{"message": {"content": "片段"}, "index": 0, "finish_reason": "stop"}],
        "model": "xiaomi/mimo",
    }
    with patch.object(adapter, "chat_completion_sync", return_value=normalized):
        client = ModstoreOpenAICompatibleClient(adapter)
        chunks = list(
            client.chat.completions.create(
                messages=[{"role": "user", "content": "hi"}], stream=True
            )
        )
    assert chunks
    assert chunks[0].choices[0].delta.content == "片段"


def test_create_client_from_request_none() -> None:
    client = create_modstore_openai_client_from_request(None)
    assert isinstance(client, ModstoreOpenAICompatibleClient)
