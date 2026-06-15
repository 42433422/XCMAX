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
        assert isinstance(obj, SimpleNamespace)

    def test_empty_list(self):
        assert _to_openai_object([]) == []


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
        payload = json.dumps(
            {"choices": [{"message": {"content": "x"}, "finish_reason": None}]}
        )
        out = _platform_stream_payload_to_openai_chunk(payload)
        assert out is not None
        assert out["choices"][0]["delta"]["content"] == "x"

    def test_error_type_raises(self):
        with pytest.raises(ValueError, match="boom"):
            _platform_stream_payload_to_openai_chunk(
                '{"type":"error","message":"boom"}'
            )

    def test_error_type_with_error_field(self):
        with pytest.raises(ValueError, match="err_msg"):
            _platform_stream_payload_to_openai_chunk(
                '{"type":"error","error":"err_msg"}'
            )

    def test_dict_with_content(self):
        payload = json.dumps({"content": "some text"})
        out = _platform_stream_payload_to_openai_chunk(payload)
        assert out is not None
        assert out["choices"][0]["delta"]["content"] == "some text"

    def test_dict_with_tool_calls(self):
        payload = json.dumps({"tool_calls": [{"id": "tc1"}], "finish_reason": "stop"})
        out = _platform_stream_payload_to_openai_chunk(payload)
        assert out is not None
        assert out["choices"][0]["delta"]["tool_calls"] == [{"id": "tc1"}]

    def test_dict_with_delta_field(self):
        payload = json.dumps({"delta": "delta_text"})
        out = _platform_stream_payload_to_openai_chunk(payload)
        assert out is not None
        assert out["choices"][0]["delta"]["content"] == "delta_text"

    def test_invalid_json_treated_as_text(self):
        out = _platform_stream_payload_to_openai_chunk("{invalid json")
        assert out["choices"][0]["delta"]["content"] == "{invalid json"

    def test_dict_with_empty_content_and_no_finish(self):
        payload = json.dumps({"content": ""})
        out = _platform_stream_payload_to_openai_chunk(payload)
        assert out is None


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
        adapter = ModstorePlatformAdapter(
            platform_url="http://example.com", default_model="gpt-4"
        )
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

    def test_repr(self):
        adapter = ModstorePlatformAdapter(
            platform_url="http://example.com", auth_token="mytoken"
        )
        r = repr(adapter)
        assert "ModstorePlatformAdapter" in r
        assert "example.com" in r


# ---------------------------------------------------------------------------
# _build_headers
# ---------------------------------------------------------------------------


class TestBuildHeaders:
    def test_with_token(self):
        adapter = ModstorePlatformAdapter(
            platform_url="http://example.com", auth_token="mytoken"
        )
        headers = adapter._build_headers()
        assert headers["Authorization"] == "Bearer mytoken"
        assert headers["Content-Type"] == "application/json"

    def test_without_token(self):
        adapter = ModstorePlatformAdapter(
            platform_url="http://example.com", auth_token=""
        )
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
        assert result["choices"][0]["message"]["content"] == "hi"
        assert result["model"] == "gpt-4"
        assert "_modstore_meta" in result

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
        assert result["choices"][0]["message"]["content"] == "hello world"
        assert result["model"] == "xiaomi/mimo"

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
        assert "prompt_tokens" in result["usage"]

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

    def test_from_session_request_headers_exception(self, monkeypatch):
        monkeypatch.delenv("MODSTORE_AUTH_TOKEN", raising=False)
        monkeypatch.delenv("XCAGI_MARKET_BASE_URL", raising=False)
        monkeypatch.setenv("MODSTORE_PLATFORM_URL", "http://example.com")
        request = MagicMock()
        request.headers.get.side_effect = RuntimeError("no headers")
        adapter = ModstorePlatformAdapter.from_session(request=request)
        assert adapter.auth_token == ""

    def test_from_session_import_error(self, monkeypatch):
        monkeypatch.delenv("MODSTORE_AUTH_TOKEN", raising=False)
        monkeypatch.delenv("XCAGI_MARKET_BASE_URL", raising=False)
        monkeypatch.setenv("MODSTORE_PLATFORM_URL", "http://example.com")
        request = MagicMock()
        request.headers.get.return_value = ""
        with patch.dict("sys.modules", {"app.fastapi_routes.market_account": None}):
            adapter = ModstorePlatformAdapter.from_session(
                session_id="test_session", request=request
            )
            # Should not raise, just log error
            assert adapter is not None

    def test_from_request_delegates_to_from_session(self, monkeypatch):
        monkeypatch.setenv("MODSTORE_PLATFORM_URL", "http://example.com")
        request = MagicMock()
        request.headers.get.return_value = "Bearer tok"
        adapter = ModstorePlatformAdapter.from_request(request=request)
        assert isinstance(adapter, ModstorePlatformAdapter)


# ---------------------------------------------------------------------------
# refresh_token_from_session
# ---------------------------------------------------------------------------


class TestRefreshTokenFromSession:
    def test_no_session_id_returns_false(self):
        adapter = ModstorePlatformAdapter(platform_url="http://example.com")
        assert adapter.refresh_token_from_session() is False

    def test_import_error_returns_false(self, monkeypatch):
        adapter = ModstorePlatformAdapter(platform_url="http://example.com")
        with patch.dict("sys.modules", {"app.fastapi_routes.market_account": None}):
            result = adapter.refresh_token_from_session(session_id="abc")
            assert result is False


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
        adapter = ModstorePlatformAdapter(platform_url="http://example.com")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "content": "hello",
            "usage": {},
            "success": True,
        }
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.is_closed = False
        adapter._client = mock_client
        result = await adapter.chat_completion([{"role": "user", "content": "hi"}])
        assert result["choices"][0]["message"]["content"] == "hello"

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
            async for _ in adapter.stream_chat_completion(
                [{"role": "user", "content": "hi"}]
            ):
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
            result = adapter.chat_completion_sync(
                [{"role": "user", "content": "hi"}]
            )
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
                adapter.chat_completion_sync(
                    [{"role": "user", "content": "hi"}]
                )


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
        assert "error" in result

    @pytest.mark.asyncio
    async def test_get_credential_status_exception(self):
        adapter = ModstorePlatformAdapter(platform_url="http://example.com")
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=RuntimeError("boom"))
        mock_client.is_closed = False
        adapter._client = mock_client
        result = await adapter.get_credential_status("openai")
        assert "error" in result


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
        await adapter.close()  # Should not raise

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
        adapter = create_modstore_adapter_from_env()
        assert isinstance(adapter, ModstorePlatformAdapter)


# ---------------------------------------------------------------------------
# ModstoreOpenAICompatibleClient
# ---------------------------------------------------------------------------


class TestModstoreOpenAICompatibleClient:
    def test_init(self):
        adapter = ModstorePlatformAdapter(platform_url="http://example.com")
        client = ModstoreOpenAICompatibleClient(adapter)
        assert client.adapter is adapter
        assert hasattr(client, "chat")
        assert hasattr(client.chat, "completions")
        assert client.default_model == adapter.default_model
        assert client.default_provider == adapter.default_provider

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
        with patch.object(adapter, "chat_completion_sync", return_value=mock_response):
            completions = _ModstoreOpenAICompletions(adapter)
            result = completions.create(
                messages=[{"role": "user", "content": "hi"}], stream=False
            )
            assert result.choices[0].message.content == "hi"

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
                completions.create(
                    messages=[{"role": "user", "content": "hi"}], stream=True
                )
            )
            assert len(chunks) == 1
            assert chunks[0].choices[0].delta.content == "streamed"


# ---------------------------------------------------------------------------
# Backward compat alias
# ---------------------------------------------------------------------------


class TestBackwardCompat:
    def test_modstore_proxy_adapter_is_same(self):
        assert ModstoreProxyAdapter is ModstorePlatformAdapter

    def test_create_modstore_openai_client_from_request(self, monkeypatch):
        monkeypatch.setenv("MODSTORE_PLATFORM_URL", "http://example.com")
        request = MagicMock()
        request.headers.get.return_value = "Bearer tok"
        client = create_modstore_openai_client_from_request(request)
        assert isinstance(client, ModstoreOpenAICompatibleClient)
