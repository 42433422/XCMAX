"""app/services/conversation/modstore_adapter ModstorePlatformAdapter 类测试。"""

from __future__ import annotations

import json
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.conversation.modstore_adapter import (
    ModstoreOpenAICompatibleClient,
    ModstorePlatformAdapter,
    ModstoreProxyAdapter,
    _ModstoreOpenAIChat,
    _ModstoreOpenAICompletions,
    _normalize_stream_choice,
    _platform_stream_payload_to_openai_chunk,
    _strip_bearer_prefix,
    _to_openai_object,
    create_modstore_adapter_from_env,
    create_modstore_openai_client_from_request,
)

# ---------------------------------------------------------------------------
# _strip_bearer_prefix
# ---------------------------------------------------------------------------


class TestStripBearerPrefix:
    def test_strips_bearer_prefix(self):
        assert _strip_bearer_prefix("Bearer abc123") == "abc123"

    def test_strips_bearer_case_insensitive(self):
        assert _strip_bearer_prefix("bearer abc123") == "abc123"

    def test_no_bearer_prefix(self):
        assert _strip_bearer_prefix("abc123") == "abc123"

    def test_empty_string(self):
        assert _strip_bearer_prefix("") == ""

    def test_none_input(self):
        assert _strip_bearer_prefix(None) == ""

    def test_whitespace_only(self):
        assert _strip_bearer_prefix("   ") == ""

    def test_bearer_with_extra_whitespace(self):
        assert _strip_bearer_prefix("  Bearer   xyz  ") == "xyz"


# ---------------------------------------------------------------------------
# _to_openai_object
# ---------------------------------------------------------------------------


class TestToOpenaiObject:
    def test_dict_to_namespace(self):
        obj = _to_openai_object({"a": 1, "b": "hello"})
        assert isinstance(obj, SimpleNamespace)
        assert obj.a == 1
        assert obj.b == "hello"

    def test_nested_dict(self):
        obj = _to_openai_object({"a": {"b": 2}})
        assert obj.a.b == 2

    def test_list_of_dicts(self):
        obj = _to_openai_object([{"x": 1}, {"x": 2}])
        assert len(obj) == 2
        assert obj[0].x == 1
        assert obj[1].x == 2

    def test_scalar_passthrough(self):
        assert _to_openai_object(42) == 42
        assert _to_openai_object("hello") == "hello"
        assert _to_openai_object(None) is None

    def test_empty_dict(self):
        obj = _to_openai_object({})
        # An empty dict becomes a SimpleNamespace with no attributes,
        # which round-trips back to an empty mapping.
        assert vars(obj) == {}
        assert obj == SimpleNamespace()

    def test_empty_list(self):
        assert _to_openai_object([]) == []

    def test_dict_with_list_of_scalars_preserved(self):
        # Lists of non-dict values stay as plain values, not namespaces.
        obj = _to_openai_object({"nums": [1, 2, 3], "name": "z"})
        assert obj.nums == [1, 2, 3]
        assert obj.name == "z"


# ---------------------------------------------------------------------------
# _normalize_stream_choice
# ---------------------------------------------------------------------------


class TestNormalizeStreamChoice:
    def test_with_delta_passthrough(self):
        choice = {"index": 0, "delta": {"content": "hi"}, "finish_reason": None}
        assert _normalize_stream_choice(choice) == choice

    def test_from_message_dict(self):
        choice = {"index": 0, "message": {"content": "hello"}, "finish_reason": "stop"}
        out = _normalize_stream_choice(choice)
        assert out["delta"]["content"] == "hello"
        assert out["finish_reason"] == "stop"

    def test_from_message_with_tool_calls(self):
        choice = {
            "index": 1,
            "message": {"content": "x", "tool_calls": [{"id": "tc1"}]},
            "finish_reason": "stop",
        }
        out = _normalize_stream_choice(choice)
        assert out["delta"]["tool_calls"] == [{"id": "tc1"}]

    def test_message_not_dict(self):
        choice = {"index": 0, "message": "not_a_dict", "finish_reason": None}
        out = _normalize_stream_choice(choice)
        assert out["delta"] == {}

    def test_missing_index_defaults_to_zero(self):
        choice = {"message": {"content": "hi"}}
        out = _normalize_stream_choice(choice)
        assert out["index"] == 0


# ---------------------------------------------------------------------------
# _platform_stream_payload_to_openai_chunk
# ---------------------------------------------------------------------------


class TestPlatformStreamPayload:
    def test_empty_string(self):
        assert _platform_stream_payload_to_openai_chunk("") is None

    def test_done_marker(self):
        assert _platform_stream_payload_to_openai_chunk("[DONE]") is None

    def test_none_input(self):
        assert _platform_stream_payload_to_openai_chunk(None) is None

    def test_plain_text(self):
        out = _platform_stream_payload_to_openai_chunk("hello")
        assert out["choices"][0]["delta"]["content"] == "hello"

    def test_json_with_choices(self):
        payload = json.dumps({"choices": [{"message": {"content": "x"}, "finish_reason": None}]})
        out = _platform_stream_payload_to_openai_chunk(payload)
        assert out["choices"][0]["delta"] == {"content": "x"}
        assert out["choices"][0]["finish_reason"] is None

    def test_error_type_raises(self):
        with pytest.raises(ValueError, match="boom"):
            _platform_stream_payload_to_openai_chunk('{"type":"error","message":"boom"}')

    def test_error_type_with_error_field(self):
        with pytest.raises(ValueError, match="err_msg"):
            _platform_stream_payload_to_openai_chunk('{"type":"error","error":"err_msg"}')

    def test_dict_with_content(self):
        payload = json.dumps({"content": "some text"})
        out = _platform_stream_payload_to_openai_chunk(payload)
        assert out["choices"][0]["delta"] == {"content": "some text"}
        assert out["choices"][0]["finish_reason"] is None

    def test_dict_with_tool_calls(self):
        payload = json.dumps({"tool_calls": [{"id": "tc1"}], "finish_reason": "stop"})
        out = _platform_stream_payload_to_openai_chunk(payload)
        # No content, but tool_calls + finish_reason are surfaced into the delta/frame.
        assert out["choices"][0]["delta"] == {"tool_calls": [{"id": "tc1"}]}
        assert out["choices"][0]["finish_reason"] == "stop"

    def test_dict_with_delta_string_used_as_content(self):
        payload = json.dumps({"delta": "delta_text"})
        out = _platform_stream_payload_to_openai_chunk(payload)
        assert out["choices"][0]["delta"] == {"content": "delta_text"}
        assert out["choices"][0]["finish_reason"] is None

    def test_dict_delta_dict_is_stringified_as_content(self):
        # NOTE: the non-choices fallback path does str(content) on raw["delta"],
        # so a *dict* delta is coerced to its repr rather than passed through.
        payload = json.dumps({"delta": {"content": "hi"}})
        out = _platform_stream_payload_to_openai_chunk(payload)
        assert out["choices"][0]["delta"]["content"] == str({"content": "hi"})

    def test_invalid_json_treated_as_text(self):
        out = _platform_stream_payload_to_openai_chunk("{invalid json")
        assert out["choices"][0]["delta"]["content"] == "{invalid json"

    def test_dict_with_empty_content_and_no_finish(self):
        payload = json.dumps({"content": ""})
        out = _platform_stream_payload_to_openai_chunk(payload)
        assert out is None

    def test_dict_with_only_finish_reason_emits_empty_delta(self):
        # A terminal frame carrying only finish_reason must still be emitted
        # (empty delta) so the consumer can observe the stop event.
        payload = json.dumps({"finish_reason": "stop"})
        out = _platform_stream_payload_to_openai_chunk(payload)
        assert out == {"choices": [{"delta": {}, "finish_reason": "stop"}]}

    def test_dict_text_field_used_as_content(self):
        out = _platform_stream_payload_to_openai_chunk(json.dumps({"text": "from-text"}))
        assert out["choices"][0]["delta"]["content"] == "from-text"
        assert out["choices"][0]["finish_reason"] is None

    def test_json_with_choices_preserves_extra_top_level_keys(self):
        payload = json.dumps(
            {
                "id": "chatcmpl-1",
                "choices": [{"message": {"content": "x"}, "finish_reason": "stop"}],
            }
        )
        out = _platform_stream_payload_to_openai_chunk(payload)
        # Top-level metadata is spread through unchanged.
        assert out["id"] == "chatcmpl-1"
        assert out["choices"][0]["delta"] == {"content": "x"}
        assert out["choices"][0]["finish_reason"] == "stop"


# ---------------------------------------------------------------------------
# ModstorePlatformAdapter.__init__
# ---------------------------------------------------------------------------


class TestModstorePlatformAdapterInit:
    def test_default_init(self):
        adapter = ModstorePlatformAdapter(platform_url="http://localhost:9000")
        assert adapter.platform_url == "http://localhost:9000"
        assert adapter.default_provider == "xiaomi"
        assert adapter.default_model == "mimo-v2.5-pro"
        assert adapter.timeout == 60.0

    def test_custom_init(self):
        adapter = ModstorePlatformAdapter(
            platform_url="http://example.com",
            auth_token="mytoken",
            user_id=42,
            default_provider="openai",
            default_model="gpt-4",
            timeout=30.0,
        )
        assert adapter.platform_url == "http://example.com"
        assert adapter.auth_token == "mytoken"
        assert adapter.user_id == 42
        assert adapter.default_provider == "openai"
        assert adapter.default_model == "gpt-4"

    def test_strips_trailing_slash(self):
        adapter = ModstorePlatformAdapter(platform_url="http://example.com/")
        assert adapter.platform_url == "http://example.com"

    def test_bearer_prefix_stripped_from_token(self):
        adapter = ModstorePlatformAdapter(
            platform_url="http://example.com", auth_token="Bearer mytoken"
        )
        assert adapter.auth_token == "mytoken"

    def test_parse_user_id_valid(self):
        assert ModstorePlatformAdapter._parse_user_id("42") == 42

    def test_parse_user_id_invalid(self):
        assert ModstorePlatformAdapter._parse_user_id("abc") is None

    def test_parse_user_id_empty(self):
        assert ModstorePlatformAdapter._parse_user_id("") is None

    def test_parse_user_id_none(self):
        assert ModstorePlatformAdapter._parse_user_id(None) is None


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------


class TestModstorePlatformAdapterProperties:
    def test_provider_name(self):
        adapter = ModstorePlatformAdapter(
            platform_url="http://example.com", default_provider="openai"
        )
        assert adapter.provider_name == "modstore-openai"

    def test_model_name(self):
        adapter = ModstorePlatformAdapter(platform_url="http://example.com", default_model="gpt-4")
        assert adapter.model_name == "gpt-4"

    def test_is_configured_true(self):
        adapter = ModstorePlatformAdapter(platform_url="http://example.com")
        assert adapter.is_configured is True

    def test_is_configured_false(self, monkeypatch):
        monkeypatch.delenv("MODSTORE_PLATFORM_URL", raising=False)
        adapter = ModstorePlatformAdapter(platform_url=None)
        # When platform_url is None, it falls back to env var default
        # which is "http://localhost:8000", so is_configured is True
        # To get is_configured=False, we need to patch the default
        adapter.platform_url = ""
        assert adapter.is_configured is False

    def test_repr_configured_masks_token(self):
        adapter = ModstorePlatformAdapter(platform_url="http://example.com", auth_token="mytoken")
        r = repr(adapter)
        assert "ModstorePlatformAdapter" in r
        assert "url=http://example.com" in r
        assert "default=xiaomi/mimo-v2.5-pro" in r
        # configured marker present, no failure marker
        assert "✅" in r and "❌" not in r
        # token is masked to asterisks with its length, never the raw value
        assert "mytoken" not in r
        assert "token=******* (7 chars)" in r
        assert "source=unknown" in r

    def test_repr_unconfigured_shows_failure_marker(self, monkeypatch):
        monkeypatch.delenv("MODSTORE_PLATFORM_URL", raising=False)
        adapter = ModstorePlatformAdapter(platform_url="http://example.com")
        adapter.platform_url = ""
        r = repr(adapter)
        assert "❌" in r and "✅" not in r
        assert "token= (0 chars)" in r


# ---------------------------------------------------------------------------
# _build_headers
# ---------------------------------------------------------------------------


class TestBuildHeaders:
    def test_with_token(self):
        adapter = ModstorePlatformAdapter(platform_url="http://example.com", auth_token="mytoken")
        headers = adapter._build_headers()
        assert headers["Authorization"] == "Bearer mytoken"
        assert headers["Content-Type"] == "application/json"

    def test_without_token(self):
        adapter = ModstorePlatformAdapter(platform_url="http://example.com", auth_token="")
        headers = adapter._build_headers()
        assert "Authorization" not in headers


# ---------------------------------------------------------------------------
# _resolve_provider_model
# ---------------------------------------------------------------------------


class TestResolveProviderModel:
    def test_defaults(self):
        adapter = ModstorePlatformAdapter(
            platform_url="http://example.com",
            default_provider="xiaomi",
            default_model="mimo-v2.5-pro",
        )
        p, m = adapter._resolve_provider_model()
        assert p == "xiaomi"
        assert m == "mimo-v2.5-pro"

    def test_explicit_override(self):
        adapter = ModstorePlatformAdapter(platform_url="http://example.com")
        p, m = adapter._resolve_provider_model(provider="openai", model="gpt-4")
        assert p == "openai"
        assert m == "gpt-4"

    def test_model_with_slash_splits(self):
        adapter = ModstorePlatformAdapter(platform_url="http://example.com")
        p, m = adapter._resolve_provider_model(model="openai/gpt-4")
        assert p == "openai"
        assert m == "gpt-4"

    def test_model_with_slash_empty_parts_ignored(self):
        adapter = ModstorePlatformAdapter(platform_url="http://example.com")
        p, m = adapter._resolve_provider_model(model="/gpt-4")
        assert p == "xiaomi"  # default, because left part is empty
        assert m == "/gpt-4"


# ---------------------------------------------------------------------------
# _normalize_response
# ---------------------------------------------------------------------------


class TestNormalizeResponse:
    def test_with_choices(self):
        adapter = ModstorePlatformAdapter(platform_url="http://example.com")
        raw = {
            "choices": [
                {"message": {"role": "assistant", "content": "hi"}, "finish_reason": "stop"}
            ],
            "usage": {"prompt_tokens": 5, "completion_tokens": 2},
            "model": "gpt-4",
        }
        result = adapter._normalize_response(raw, "openai", "gpt-4")
        assert result["choices"][0]["message"] == {"role": "assistant", "content": "hi"}
        assert result["choices"][0]["finish_reason"] == "stop"
        assert result["choices"][0]["index"] == 0
        # raw "model" wins over the provider/model fallback
        assert result["model"] == "gpt-4"
        assert result["usage"] == {"prompt_tokens": 5, "completion_tokens": 2}
        assert result["_modstore_meta"]["key_source"] is None

    def test_with_choices_and_tool_calls(self):
        adapter = ModstorePlatformAdapter(platform_url="http://example.com")
        raw = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [{"id": "tc1"}],
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {},
        }
        result = adapter._normalize_response(raw, "openai", "gpt-4")
        assert result["choices"][0]["message"]["tool_calls"] == [{"id": "tc1"}]

    def test_without_choices_flat_content(self):
        adapter = ModstorePlatformAdapter(platform_url="http://example.com")
        raw = {
            "content": "hello world",
            "usage": {"prompt_tokens": 5},
            "success": True,
            "key_source": "platform",
        }
        result = adapter._normalize_response(raw, "xiaomi", "mimo")
        assert result["choices"][0]["message"] == {
            "role": "assistant",
            "content": "hello world",
        }
        assert result["choices"][0]["finish_reason"] == "stop"
        # No raw "model" → falls back to "<provider>/<model>"
        assert result["model"] == "xiaomi/mimo"
        # Platform metadata is surfaced into _modstore_meta.
        assert result["_modstore_meta"]["success"] is True
        assert result["_modstore_meta"]["key_source"] == "platform"

    def test_with_usage_dataclass(self):
        adapter = ModstorePlatformAdapter(platform_url="http://example.com")

        # Create a dataclass-like object with __dict__
        class Usage:
            def __init__(self):
                self.prompt_tokens = 5
                self.completion_tokens = 2

        usage_obj = Usage()
        raw = {"content": "hi", "usage": usage_obj}
        result = adapter._normalize_response(raw, "p", "m")
        # The object's __dict__ is unwrapped into the usage mapping with real values.
        assert result["usage"] == {"prompt_tokens": 5, "completion_tokens": 2}
        assert result["choices"][0]["message"]["content"] == "hi"
        assert result["model"] == "p/m"

    def test_empty_choices_list(self):
        adapter = ModstorePlatformAdapter(platform_url="http://example.com")
        raw = {"choices": [], "content": "fallback"}
        result = adapter._normalize_response(raw, "p", "m")
        assert result["choices"][0]["message"]["content"] == "fallback"


# ---------------------------------------------------------------------------
# from_session / from_request
# ---------------------------------------------------------------------------


class TestFromSession:
    def test_from_session_with_env_token(self, monkeypatch):
        monkeypatch.setenv("MODSTORE_AUTH_TOKEN", "env_token")
        monkeypatch.setenv("MODSTORE_PLATFORM_URL", "http://env.example.com")
        adapter = ModstorePlatformAdapter.from_session()
        assert adapter.auth_token == "env_token"
        assert adapter._source == "env"

    def test_from_session_with_request_auth(self, monkeypatch):
        monkeypatch.delenv("MODSTORE_AUTH_TOKEN", raising=False)
        monkeypatch.delenv("XCAGI_MARKET_BASE_URL", raising=False)
        monkeypatch.setenv("MODSTORE_PLATFORM_URL", "http://example.com")
        request = MagicMock()
        request.headers.get.return_value = "Bearer req_token"
        adapter = ModstorePlatformAdapter.from_session(request=request)
        assert adapter.auth_token == "req_token"

    def test_from_session_request_token_overrides_env(self, monkeypatch):
        """请求头 market token 必须优先于 MODSTORE_AUTH_TOKEN 环境变量。

        回归测试：移动端发送自己的 market token，但服务器设置了
        MODSTORE_AUTH_TOKEN 环境变量（可能过期/无效），必须用请求头 token，
        否则会用过期环境变量 token 调用 MODstore → 401。
        """
        monkeypatch.setenv("MODSTORE_AUTH_TOKEN", "stale_env_token")
        monkeypatch.setenv("MODSTORE_PLATFORM_URL", "http://example.com")
        request = MagicMock()
        request.headers.get.return_value = "Bearer fresh_request_token"
        adapter = ModstorePlatformAdapter.from_session(request=request)
        assert adapter.auth_token == "fresh_request_token"
        assert adapter._source == "request"

    def test_from_session_request_headers_exception(self, monkeypatch):
        monkeypatch.delenv("MODSTORE_AUTH_TOKEN", raising=False)
        monkeypatch.delenv("XCAGI_MARKET_BASE_URL", raising=False)
        monkeypatch.setenv("MODSTORE_PLATFORM_URL", "http://example.com")
        request = MagicMock()
        request.headers.get.side_effect = RuntimeError("no headers")
        # A header-read failure must be swallowed (not propagated) and yield
        # an unauthenticated adapter rather than crashing the request.
        adapter = ModstorePlatformAdapter.from_session(request=request)
        assert adapter.auth_token == ""
        assert adapter._source == "env"
        assert adapter.platform_url == "http://example.com"

    def test_from_session_import_error(self, monkeypatch):
        monkeypatch.delenv("MODSTORE_AUTH_TOKEN", raising=False)
        monkeypatch.delenv("XCAGI_MARKET_BASE_URL", raising=False)
        monkeypatch.setenv("MODSTORE_PLATFORM_URL", "http://example.com")
        request = MagicMock()
        request.headers.get.return_value = ""
        # Force the market_account import inside the session-token branch to fail.
        with patch.dict("sys.modules", {"app.fastapi_routes.market_account": None}):
            adapter = ModstorePlatformAdapter.from_session(
                session_id="test_session", request=request
            )
        # ImportError is swallowed: no token recovered, source stays "env",
        # and a usable (but unauthenticated) adapter is returned.
        assert isinstance(adapter, ModstorePlatformAdapter)
        assert adapter.auth_token == ""
        assert adapter._source == "env"

    def test_from_request_delegates_to_from_session(self, monkeypatch):
        monkeypatch.delenv("MODSTORE_AUTH_TOKEN", raising=False)
        monkeypatch.delenv("XCAGI_MARKET_BASE_URL", raising=False)
        monkeypatch.setenv("MODSTORE_PLATFORM_URL", "http://example.com")
        request = MagicMock()
        request.headers.get.return_value = "Bearer tok"
        adapter = ModstorePlatformAdapter.from_request(request=request)
        # from_request must forward the request so the header token is extracted,
        # with Bearer stripped and source marked as request-derived.
        assert isinstance(adapter, ModstorePlatformAdapter)
        assert adapter.auth_token == "tok"
        assert adapter._source == "request"


# ---------------------------------------------------------------------------
# refresh_token_from_session
# ---------------------------------------------------------------------------


class TestRefreshTokenFromSession:
    def test_no_session_id_returns_false(self):
        adapter = ModstorePlatformAdapter(platform_url="http://example.com")
        assert adapter.refresh_token_from_session() is False

    def test_import_error_returns_false(self, monkeypatch):
        adapter = ModstorePlatformAdapter(platform_url="http://example.com", auth_token="old")
        with patch.dict("sys.modules", {"app.fastapi_routes.market_account": None}):
            result = adapter.refresh_token_from_session(session_id="abc")
        assert result is False
        # On failure the existing token must be left untouched.
        assert adapter.auth_token == "old"

    def test_refresh_success_replaces_token(self):
        adapter = ModstorePlatformAdapter(platform_url="http://example.com", auth_token="old")
        fake_module = SimpleNamespace(
            session_id_from_request=lambda request: "",
            session_market_token=lambda sid: "fresh_token" if sid == "sess-1" else "",
        )
        with patch.dict("sys.modules", {"app.fastapi_routes.market_account": fake_module}):
            result = adapter.refresh_token_from_session(session_id="sess-1")
        assert result is True
        assert adapter.auth_token == "fresh_token"

    def test_refresh_no_token_in_session_returns_false(self):
        adapter = ModstorePlatformAdapter(platform_url="http://example.com", auth_token="old")
        fake_module = SimpleNamespace(
            session_id_from_request=lambda request: "",
            session_market_token=lambda sid: "",  # session bound but no token
        )
        with patch.dict("sys.modules", {"app.fastapi_routes.market_account": fake_module}):
            result = adapter.refresh_token_from_session(session_id="sess-1")
        assert result is False
        assert adapter.auth_token == "old"


# ---------------------------------------------------------------------------
# chat_completion (async)
# ---------------------------------------------------------------------------


class TestChatCompletion:
    @pytest.mark.asyncio
    async def test_no_platform_url_raises(self, monkeypatch):
        monkeypatch.delenv("MODSTORE_PLATFORM_URL", raising=False)
        adapter = ModstorePlatformAdapter(platform_url=None)
        adapter.platform_url = ""  # Force empty to trigger ValueError
        with pytest.raises(ValueError, match="未配置"):
            await adapter.chat_completion([{"role": "user", "content": "hi"}])

    @pytest.mark.asyncio
    async def test_http_error_raises(self, monkeypatch):
        import httpx

        adapter = ModstorePlatformAdapter(platform_url="http://example.com")
        mock_client = AsyncMock()
        # httpx.ConnectError is a subclass of httpx.HTTPError
        # which is caught by the `except httpx.HTTPError` block and re-raised
        mock_client.post = AsyncMock(side_effect=httpx.ConnectError("connection failed"))
        # _get_client is an async method that returns the client
        adapter._get_client = AsyncMock(return_value=mock_client)
        with pytest.raises(httpx.ConnectError):
            await adapter.chat_completion([{"role": "user", "content": "hi"}])

    @pytest.mark.asyncio
    async def test_success_response(self, monkeypatch):
        adapter = ModstorePlatformAdapter(
            platform_url="http://example.com",
            default_provider="xiaomi",
            default_model="mimo",
            user_id=99,
        )
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "content": "hello",
            "usage": {"total_tokens": 7},
            "success": True,
        }
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.is_closed = False
        adapter._client = mock_client
        result = await adapter.chat_completion(
            [{"role": "user", "content": "hi"}], temperature=0.3, max_tokens=128
        )
        # Normalized OpenAI-shaped response.
        assert result["choices"][0]["message"]["content"] == "hello"
        assert result["model"] == "xiaomi/mimo"
        assert result["_modstore_meta"]["success"] is True
        # The adapter POSTs to the platform chat endpoint with a fully-built payload.
        call = mock_client.post.await_args
        assert call.args[0] == "http://example.com/api/llm/chat"
        sent = call.kwargs["json"]
        assert sent["provider"] == "xiaomi"
        assert sent["model"] == "mimo"
        assert sent["temperature"] == 0.3
        assert sent["max_tokens"] == 128
        assert sent["user_id"] == 99
        assert sent["messages"] == [{"role": "user", "content": "hi"}]

    @pytest.mark.asyncio
    async def test_error_status_raises(self, monkeypatch):
        adapter = ModstorePlatformAdapter(platform_url="http://example.com")
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.is_closed = False
        adapter._client = mock_client
        with pytest.raises(ValueError, match="500"):
            await adapter.chat_completion([{"role": "user", "content": "hi"}])


# ---------------------------------------------------------------------------
# stream_chat_completion (async)
# ---------------------------------------------------------------------------


class TestStreamChatCompletion:
    @pytest.mark.asyncio
    async def test_no_platform_url_raises(self, monkeypatch):
        monkeypatch.delenv("MODSTORE_PLATFORM_URL", raising=False)
        adapter = ModstorePlatformAdapter(platform_url=None)
        adapter.platform_url = ""
        with pytest.raises(ValueError, match="未配置"):
            async for _ in adapter.stream_chat_completion([{"role": "user", "content": "hi"}]):
                pass


# ---------------------------------------------------------------------------
# chat_completion_sync
# ---------------------------------------------------------------------------


class TestChatCompletionSync:
    def test_no_platform_url_raises(self, monkeypatch):
        monkeypatch.delenv("MODSTORE_PLATFORM_URL", raising=False)
        adapter = ModstorePlatformAdapter(platform_url=None)
        adapter.platform_url = ""
        with pytest.raises(ValueError, match="未配置"):
            adapter.chat_completion_sync([{"role": "user", "content": "hi"}])

    def test_success(self, monkeypatch):
        adapter = ModstorePlatformAdapter(platform_url="http://example.com")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "content": "hello sync",
            "usage": {},
            "success": True,
        }
        with patch("httpx.Client") as MockClient:
            mock_client_instance = MagicMock()
            mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
            mock_client_instance.__exit__ = MagicMock(return_value=False)
            mock_client_instance.post.return_value = mock_response
            MockClient.return_value = mock_client_instance
            result = adapter.chat_completion_sync([{"role": "user", "content": "hi"}])
            assert result["choices"][0]["message"]["content"] == "hello sync"

    def test_error_status_raises(self, monkeypatch):
        adapter = ModstorePlatformAdapter(platform_url="http://example.com")
        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_response.text = "Forbidden"
        with patch("httpx.Client") as MockClient:
            mock_client_instance = MagicMock()
            mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
            mock_client_instance.__exit__ = MagicMock(return_value=False)
            mock_client_instance.post.return_value = mock_response
            MockClient.return_value = mock_client_instance
            with pytest.raises(ValueError, match="403"):
                adapter.chat_completion_sync([{"role": "user", "content": "hi"}])


# ---------------------------------------------------------------------------
# get_available_providers / get_credential_status
# ---------------------------------------------------------------------------


class TestProviderMethods:
    @pytest.mark.asyncio
    async def test_get_available_providers_success(self):
        adapter = ModstorePlatformAdapter(platform_url="http://example.com")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"providers": [{"name": "openai"}]}
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.is_closed = False
        adapter._client = mock_client
        result = await adapter.get_available_providers()
        assert result == [{"name": "openai"}]
        # Reads from the providers endpoint.
        assert mock_client.get.await_args.args[0] == "http://example.com/api/llm/providers"

    @pytest.mark.asyncio
    async def test_get_available_providers_failure(self):
        adapter = ModstorePlatformAdapter(platform_url="http://example.com")
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.is_closed = False
        adapter._client = mock_client
        result = await adapter.get_available_providers()
        assert result == []

    @pytest.mark.asyncio
    async def test_get_available_providers_exception(self):
        adapter = ModstorePlatformAdapter(platform_url="http://example.com")
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=RuntimeError("boom"))
        mock_client.is_closed = False
        adapter._client = mock_client
        result = await adapter.get_available_providers()
        assert result == []

    @pytest.mark.asyncio
    async def test_get_credential_status_success(self):
        adapter = ModstorePlatformAdapter(platform_url="http://example.com")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"has_key": True}
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.is_closed = False
        adapter._client = mock_client
        result = await adapter.get_credential_status("openai")
        assert result == {"has_key": True}
        # The provider name is embedded in the credential-status URL.
        assert (
            mock_client.get.await_args.args[0]
            == "http://example.com/api/llm/credential-status/openai"
        )

    @pytest.mark.asyncio
    async def test_get_credential_status_defaults_to_adapter_provider(self):
        adapter = ModstorePlatformAdapter(
            platform_url="http://example.com", default_provider="xiaomi"
        )
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"has_key": False}
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.is_closed = False
        adapter._client = mock_client
        result = await adapter.get_credential_status()  # no provider arg
        assert result == {"has_key": False}
        assert (
            mock_client.get.await_args.args[0]
            == "http://example.com/api/llm/credential-status/xiaomi"
        )

    @pytest.mark.asyncio
    async def test_get_credential_status_failure(self):
        adapter = ModstorePlatformAdapter(platform_url="http://example.com")
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.is_closed = False
        adapter._client = mock_client
        result = await adapter.get_credential_status("unknown")
        # Non-200 surfaces the HTTP status in the error payload.
        assert result == {"error": "HTTP 404"}

    @pytest.mark.asyncio
    async def test_get_credential_status_exception(self):
        adapter = ModstorePlatformAdapter(platform_url="http://example.com")
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=RuntimeError("boom"))
        mock_client.is_closed = False
        adapter._client = mock_client
        result = await adapter.get_credential_status("openai")
        # A transport exception is captured as the error string, not re-raised.
        assert result == {"error": "boom"}


# ---------------------------------------------------------------------------
# close
# ---------------------------------------------------------------------------


class TestClose:
    @pytest.mark.asyncio
    async def test_close_with_client(self):
        adapter = ModstorePlatformAdapter(platform_url="http://example.com")
        mock_client = AsyncMock()
        mock_client.is_closed = False
        adapter._client = mock_client
        await adapter.close()
        mock_client.aclose.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_no_client(self):
        adapter = ModstorePlatformAdapter(platform_url="http://example.com")
        adapter._client = None
        # Closing with no client is a no-op that leaves the slot untouched.
        await adapter.close()
        assert adapter._client is None

    @pytest.mark.asyncio
    async def test_close_already_closed(self):
        adapter = ModstorePlatformAdapter(platform_url="http://example.com")
        mock_client = AsyncMock()
        mock_client.is_closed = True
        adapter._client = mock_client
        await adapter.close()
        mock_client.aclose.assert_not_called()


# ---------------------------------------------------------------------------
# create_modstore_adapter_from_env
# ---------------------------------------------------------------------------


class TestCreateFromEnv:
    def test_no_env_returns_none(self, monkeypatch):
        monkeypatch.delenv("MODSTORE_PLATFORM_URL", raising=False)
        assert create_modstore_adapter_from_env() is None

    def test_with_env_returns_adapter(self, monkeypatch):
        monkeypatch.setenv("MODSTORE_PLATFORM_URL", "http://example.com")
        monkeypatch.setenv("MODSTORE_AUTH_TOKEN", "envtok")
        adapter = create_modstore_adapter_from_env()
        assert isinstance(adapter, ModstorePlatformAdapter)
        # The factory reads configuration straight from the environment.
        assert adapter.platform_url == "http://example.com"
        assert adapter.auth_token == "envtok"
        assert adapter.is_configured is True

    def test_blank_env_returns_none(self, monkeypatch):
        # Whitespace-only URL is treated as unconfigured.
        monkeypatch.setenv("MODSTORE_PLATFORM_URL", "   ")
        assert create_modstore_adapter_from_env() is None


# ---------------------------------------------------------------------------
# ModstoreOpenAICompatibleClient
# ---------------------------------------------------------------------------


class TestModstoreOpenAICompatibleClient:
    def test_init(self):
        adapter = ModstorePlatformAdapter(
            platform_url="http://example.com",
            default_model="gpt-4",
            default_provider="openai",
        )
        client = ModstoreOpenAICompatibleClient(adapter)
        assert client.adapter is adapter
        # The chat.completions facade is wired to the *same* adapter instance.
        assert isinstance(client.chat, _ModstoreOpenAIChat)
        assert isinstance(client.chat.completions, _ModstoreOpenAICompletions)
        assert client.chat.completions._adapter is adapter
        # default_model/provider are live properties proxied from the adapter.
        assert client.default_model == "gpt-4"
        assert client.default_provider == "openai"
        adapter.default_model = "gpt-4o"
        assert client.default_model == "gpt-4o"

    def test_is_modstore_openai_compatible_flag(self):
        adapter = ModstorePlatformAdapter(platform_url="http://example.com")
        client = ModstoreOpenAICompatibleClient(adapter)
        assert client.is_modstore_openai_compatible is True


# ---------------------------------------------------------------------------
# _ModstoreOpenAICompletions
# ---------------------------------------------------------------------------


class TestModstoreOpenAICompletions:
    def test_create_non_stream(self, monkeypatch):
        adapter = ModstorePlatformAdapter(platform_url="http://example.com")
        mock_response = {
            "choices": [
                {"message": {"role": "assistant", "content": "hi"}, "finish_reason": "stop"}
            ],
            "usage": {},
            "model": "test",
        }
        with patch.object(adapter, "chat_completion_sync", return_value=mock_response) as mock_sync:
            completions = _ModstoreOpenAICompletions(adapter)
            result = completions.create(
                messages=[{"role": "user", "content": "hi"}],
                stream=False,
                model="openai/gpt-4",
            )
        # The dict response is wrapped into attribute-access objects (OpenAI SDK shape).
        assert isinstance(result, SimpleNamespace)
        assert result.choices[0].message.content == "hi"
        assert result.choices[0].message.role == "assistant"
        assert result.choices[0].finish_reason == "stop"
        assert result.model == "test"
        # The chosen model is forwarded to the sync call.
        assert mock_sync.call_args.kwargs["model"] == "openai/gpt-4"

    def test_create_stream_non_native(self, monkeypatch):
        monkeypatch.setenv("XCAGI_MODSTORE_USE_NATIVE_STREAM", "0")
        adapter = ModstorePlatformAdapter(platform_url="http://example.com")
        mock_response = {
            "choices": [
                {
                    "message": {"role": "assistant", "content": "streamed"},
                    "index": 0,
                    "finish_reason": "stop",
                }
            ],
            "model": "test",
        }
        with patch.object(adapter, "chat_completion_sync", return_value=mock_response):
            completions = _ModstoreOpenAICompletions(adapter)
            chunks = list(
                completions.create(messages=[{"role": "user", "content": "hi"}], stream=True)
            )
        # Non-native mode synthesizes exactly one stream chunk from the full response.
        assert len(chunks) == 1
        assert chunks[0].choices[0].delta.content == "streamed"
        assert chunks[0].choices[0].finish_reason == "stop"
        assert chunks[0].choices[0].index == 0
        assert chunks[0].model == "test"

    def test_create_stream_native_yields_per_payload_chunks(self, monkeypatch):
        monkeypatch.setenv("XCAGI_MODSTORE_USE_NATIVE_STREAM", "1")
        adapter = ModstorePlatformAdapter(platform_url="http://example.com")

        def fake_stream(**kwargs):
            yield "hello"
            yield json.dumps({"content": " world", "finish_reason": "stop"})
            yield "[DONE]"  # terminal marker → produces no chunk

        with patch.object(adapter, "stream_chat_completion_sync", side_effect=fake_stream):
            completions = _ModstoreOpenAICompletions(adapter)
            chunks = list(
                completions.create(messages=[{"role": "user", "content": "hi"}], stream=True)
            )
        # [DONE] is dropped; two content payloads become two chunks.
        assert [c.choices[0].delta.content for c in chunks] == ["hello", " world"]
        assert chunks[1].choices[0].finish_reason == "stop"

    def test_create_stream_native_default_when_env_unset(self, monkeypatch):
        # Default (env unset) is native streaming, so stream_chat_completion_sync is used.
        monkeypatch.delenv("XCAGI_MODSTORE_USE_NATIVE_STREAM", raising=False)
        adapter = ModstorePlatformAdapter(platform_url="http://example.com")
        with (
            patch.object(
                adapter, "stream_chat_completion_sync", return_value=iter(["hi there"])
            ) as native,
            patch.object(adapter, "chat_completion_sync") as sync,
        ):
            completions = _ModstoreOpenAICompletions(adapter)
            chunks = list(
                completions.create(messages=[{"role": "user", "content": "x"}], stream=True)
            )
        assert native.called
        assert sync.called is False
        assert chunks[0].choices[0].delta.content == "hi there"


# ---------------------------------------------------------------------------
# Backward compat alias
# ---------------------------------------------------------------------------


class TestBackwardCompat:
    def test_modstore_proxy_adapter_is_same(self):
        assert ModstoreProxyAdapter is ModstorePlatformAdapter

    def test_create_modstore_openai_client_from_request(self, monkeypatch):
        monkeypatch.delenv("MODSTORE_AUTH_TOKEN", raising=False)
        monkeypatch.delenv("XCAGI_MARKET_BASE_URL", raising=False)
        monkeypatch.setenv("MODSTORE_PLATFORM_URL", "http://example.com")
        request = MagicMock()
        request.headers.get.return_value = "Bearer tok"
        client = create_modstore_openai_client_from_request(request)
        assert isinstance(client, ModstoreOpenAICompatibleClient)
        # The request's Authorization header is threaded all the way into the
        # underlying adapter (Bearer prefix stripped).
        assert client.adapter.auth_token == "tok"
        assert client.adapter.platform_url == "http://example.com"
