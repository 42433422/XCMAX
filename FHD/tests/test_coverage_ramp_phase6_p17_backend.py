"""COVERAGE_RAMP Phase 6 round 17: backend low-coverage modules.

Targets:
- ``app/services/conversation/modstore_adapter.py`` (357 行, 未覆盖 67 行, cov 76.9%)
- ``app/infrastructure/mods/employee_registry.py`` (135 行, 未覆盖 66 行, cov 48.1%)
- ``app/infrastructure/persistence/compat_db/writes.py`` (389 行, 未覆盖 66 行, cov 81.0%)
- ``app/neuro_bus/sandbox.py`` (122 行, 未覆盖 66 行, cov 38.4%)
- ``app/services/kitten_report/chart_data_service.py`` (113 行, 未覆盖 66 行, cov 40.2%)
- ``app/services/operations_line_bridge.py`` (77 行, 未覆盖 66 行, cov 10.7%)

Tests follow the phase-6 style: ``from __future__ import annotations``,
``unittest.mock`` + ``pytest``, mock only external boundaries (DB / external
API / LLM / file IO / paddleocr). The handler functions themselves are
exercised through real calls.

Coverage scenarios per 铁律3:
- Happy path (valid input)
- Empty / None input
- Boundary values (empty list, empty dict, empty string)
- Exception paths (RECOVERABLE_ERRORS: RuntimeError, ValueError, OSError)
"""

from __future__ import annotations

import os

os.environ.setdefault("XCAGI_SKIP_LEGACY_COMPAT_ROUTES", "1")

import json
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from app.neuro_bus.events.base import EventMetadata, EventPriority, NeuroEvent


# ===========================================================================
# Shared fixtures
# ===========================================================================


@pytest.fixture
def tmp_dir():
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def make_neuro_event():
    """Factory fixture to create NeuroEvent instances for sandbox tests."""

    def _make(
        event_type: str = "test.event",
        payload: dict | None = None,
        domain: str = "global",
    ) -> NeuroEvent:
        meta = EventMetadata(domain=domain)
        return NeuroEvent(
            event_type=event_type,
            payload=payload or {},
            metadata=meta,
        )

    return _make


# ===========================================================================
# 1. app/services/conversation/modstore_adapter.py
# ===========================================================================


class TestStripBearerPrefix:
    """Cover ``_strip_bearer_prefix`` helper."""

    def test_strip_bearer_prefix_with_bearer_returns_token(self):
        from app.services.conversation.modstore_adapter import _strip_bearer_prefix

        assert _strip_bearer_prefix("Bearer abc123") == "abc123"

    def test_strip_bearer_prefix_case_insensitive(self):
        from app.services.conversation.modstore_adapter import _strip_bearer_prefix

        assert _strip_bearer_prefix("bearer xyz") == "xyz"

    def test_strip_bearer_prefix_without_bearer_returns_same(self):
        from app.services.conversation.modstore_adapter import _strip_bearer_prefix

        assert _strip_bearer_prefix("abc123") == "abc123"

    def test_strip_bearer_prefix_empty_string_returns_empty(self):
        from app.services.conversation.modstore_adapter import _strip_bearer_prefix

        assert _strip_bearer_prefix("") == ""

    def test_strip_bearer_prefix_none_returns_empty(self):
        from app.services.conversation.modstore_adapter import _strip_bearer_prefix

        assert _strip_bearer_prefix(None) == ""


class TestToOpenaiObject:
    """Cover ``_to_openai_object`` helper."""

    def test_dict_converted_to_simplenamespace(self):
        from app.services.conversation.modstore_adapter import _to_openai_object

        result = _to_openai_object({"key": "value"})
        assert isinstance(result, SimpleNamespace)
        assert result.key == "value"

    def test_list_converted_to_list_of_objects(self):
        from app.services.conversation.modstore_adapter import _to_openai_object

        result = _to_openai_object([1, "two"])
        assert result == [1, "two"]

    def test_scalar_returned_as_is(self):
        from app.services.conversation.modstore_adapter import _to_openai_object

        assert _to_openai_object(42) == 42
        assert _to_openai_object("hello") == "hello"

    def test_nested_dict_converted_recursively(self):
        from app.services.conversation.modstore_adapter import _to_openai_object

        result = _to_openai_object({"outer": {"inner": 1}})
        assert isinstance(result.outer, SimpleNamespace)
        assert result.outer.inner == 1


class TestNormalizeStreamChoice:
    """Cover ``_normalize_stream_choice`` helper."""

    def test_choice_with_delta_returns_unchanged(self):
        from app.services.conversation.modstore_adapter import _normalize_stream_choice

        choice = {"delta": {"content": "hi"}, "index": 0, "finish_reason": None}
        result = _normalize_stream_choice(choice)
        assert "delta" in result

    def test_choice_with_message_dict_extracts_delta(self):
        from app.services.conversation.modstore_adapter import _normalize_stream_choice

        choice = {"message": {"content": "hello"}, "index": 1, "finish_reason": "stop"}
        result = _normalize_stream_choice(choice)
        assert result["delta"]["content"] == "hello"
        assert result["index"] == 1

    def test_choice_without_message_returns_empty_delta(self):
        from app.services.conversation.modstore_adapter import _normalize_stream_choice

        choice = {"index": 0, "finish_reason": None}
        result = _normalize_stream_choice(choice)
        assert result["delta"] == {}

    def test_choice_with_tool_calls_in_message(self):
        from app.services.conversation.modstore_adapter import _normalize_stream_choice

        choice = {
            "message": {"content": "call", "tool_calls": [{"id": "t1"}]},
            "index": 0,
            "finish_reason": None,
        }
        result = _normalize_stream_choice(choice)
        assert result["delta"]["tool_calls"] == [{"id": "t1"}]


class TestPlatformStreamPayloadToOpenaiChunk:
    """Cover ``_platform_stream_payload_to_openai_chunk`` helper."""

    def test_empty_string_returns_none(self):
        from app.services.conversation.modstore_adapter import _platform_stream_payload_to_openai_chunk

        assert _platform_stream_payload_to_openai_chunk("") is None

    def test_done_returns_none(self):
        from app.services.conversation.modstore_adapter import _platform_stream_payload_to_openai_chunk

        assert _platform_stream_payload_to_openai_chunk("[DONE]") is None

    def test_invalid_json_returns_raw_text_as_content(self):
        from app.services.conversation.modstore_adapter import _platform_stream_payload_to_openai_chunk

        result = _platform_stream_payload_to_openai_chunk("not json")
        assert result["choices"][0]["delta"]["content"] == "not json"

    def test_valid_json_with_choices_normalizes(self):
        from app.services.conversation.modstore_adapter import _platform_stream_payload_to_openai_chunk

        data = json.dumps({"choices": [{"message": {"content": "hi"}, "index": 0}]})
        result = _platform_stream_payload_to_openai_chunk(data)
        assert result["choices"][0]["delta"]["content"] == "hi"

    def test_error_type_raises_value_error(self):
        from app.services.conversation.modstore_adapter import _platform_stream_payload_to_openai_chunk

        data = json.dumps({"type": "error", "message": "boom"})
        with pytest.raises(ValueError, match="boom"):
            _platform_stream_payload_to_openai_chunk(data)

    def test_plain_dict_with_content_returns_chunk(self):
        from app.services.conversation.modstore_adapter import _platform_stream_payload_to_openai_chunk

        data = json.dumps({"content": "hello"})
        result = _platform_stream_payload_to_openai_chunk(data)
        assert result["choices"][0]["delta"]["content"] == "hello"

    def test_plain_dict_with_text_field_returns_chunk(self):
        from app.services.conversation.modstore_adapter import _platform_stream_payload_to_openai_chunk

        data = json.dumps({"text": "world"})
        result = _platform_stream_payload_to_openai_chunk(data)
        assert result["choices"][0]["delta"]["content"] == "world"

    def test_plain_dict_with_delta_field_returns_chunk(self):
        from app.services.conversation.modstore_adapter import _platform_stream_payload_to_openai_chunk

        data = json.dumps({"delta": "delta_text"})
        result = _platform_stream_payload_to_openai_chunk(data)
        assert result["choices"][0]["delta"]["content"] == "delta_text"

    def test_plain_dict_with_tool_calls(self):
        from app.services.conversation.modstore_adapter import _platform_stream_payload_to_openai_chunk

        data = json.dumps({"tool_calls": [{"id": "tc1"}], "finish_reason": "stop"})
        result = _platform_stream_payload_to_openai_chunk(data)
        assert result["choices"][0]["delta"]["tool_calls"] == [{"id": "tc1"}]

    def test_plain_dict_empty_returns_none(self):
        from app.services.conversation.modstore_adapter import _platform_stream_payload_to_openai_chunk

        data = json.dumps({"other": 123})
        result = _platform_stream_payload_to_openai_chunk(data)
        assert result is None


class TestModstorePlatformAdapterInit:
    """Cover ``ModstorePlatformAdapter.__init__`` and simple properties."""

    def test_init_with_defaults(self, monkeypatch):
        from app.services.conversation.modstore_adapter import ModstorePlatformAdapter

        monkeypatch.delenv("MODSTORE_PLATFORM_URL", raising=False)
        monkeypatch.delenv("MODSTORE_AUTH_TOKEN", raising=False)
        monkeypatch.delenv("MODSTORE_USER_ID", raising=False)
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        monkeypatch.delenv("LLM_MODEL", raising=False)
        a = ModstorePlatformAdapter()
        assert a.is_configured is True
        assert a.provider_name == "modstore-xiaomi"
        assert a.model_name == "mimo-v2.5-pro"

    def test_init_with_custom_params(self):
        from app.services.conversation.modstore_adapter import ModstorePlatformAdapter

        a = ModstorePlatformAdapter(
            platform_url="http://custom:9000",
            auth_token="Bearer tok123",
            user_id=42,
            default_provider="openai",
            default_model="gpt-4",
        )
        assert a.platform_url == "http://custom:9000"
        assert a.auth_token == "tok123"
        assert a.user_id == 42
        assert a.provider_name == "modstore-openai"
        assert a.model_name == "gpt-4"

    def test_parse_user_id_valid(self):
        from app.services.conversation.modstore_adapter import ModstorePlatformAdapter

        assert ModstorePlatformAdapter._parse_user_id("123") == 123

    def test_parse_user_id_empty_returns_none(self):
        from app.services.conversation.modstore_adapter import ModstorePlatformAdapter

        assert ModstorePlatformAdapter._parse_user_id("") is None

    def test_parse_user_id_invalid_returns_none(self):
        from app.services.conversation.modstore_adapter import ModstorePlatformAdapter

        assert ModstorePlatformAdapter._parse_user_id("abc") is None

    def test_repr_configured(self):
        from app.services.conversation.modstore_adapter import ModstorePlatformAdapter

        a = ModstorePlatformAdapter(platform_url="http://x", auth_token="tok")
        r = repr(a)
        assert "✅" in r
        assert "http://x" in r

    def test_repr_not_configured(self, monkeypatch):
        from app.services.conversation.modstore_adapter import ModstorePlatformAdapter

        monkeypatch.delenv("MODSTORE_PLATFORM_URL", raising=False)
        # Force platform_url to empty by patching the env default
        with patch.dict(os.environ, {"MODSTORE_PLATFORM_URL": ""}, clear=False):
            a = ModstorePlatformAdapter()
            a.platform_url = ""  # Force empty to test repr branch
            r = repr(a)
        assert "❌" in r


class TestModstorePlatformAdapterResolveProviderModel:
    """Cover ``_resolve_provider_model``."""

    def test_defaults_used_when_none(self):
        from app.services.conversation.modstore_adapter import ModstorePlatformAdapter

        a = ModstorePlatformAdapter(default_provider="openai", default_model="gpt-4")
        p, m = a._resolve_provider_model(None, None)
        assert p == "openai"
        assert m == "gpt-4"

    def test_explicit_overrides_defaults(self):
        from app.services.conversation.modstore_adapter import ModstorePlatformAdapter

        a = ModstorePlatformAdapter()
        p, m = a._resolve_provider_model("Custom", "my-model")
        assert p == "custom"
        assert m == "my-model"

    def test_model_with_slash_splits_provider(self):
        from app.services.conversation.modstore_adapter import ModstorePlatformAdapter

        a = ModstorePlatformAdapter()
        p, m = a._resolve_provider_model(None, "anthropic/claude-3")
        assert p == "anthropic"
        assert m == "claude-3"

    def test_model_with_slash_empty_parts_ignored(self):
        from app.services.conversation.modstore_adapter import ModstorePlatformAdapter

        a = ModstorePlatformAdapter()
        p, m = a._resolve_provider_model(None, "/model-only")
        assert p == "xiaomi"  # default, left part empty
        assert m == "/model-only"


class TestModstorePlatformAdapterBuildHeaders:
    """Cover ``_build_headers``."""

    def test_with_auth_token(self):
        from app.services.conversation.modstore_adapter import ModstorePlatformAdapter

        a = ModstorePlatformAdapter(auth_token="mytoken")
        h = a._build_headers()
        assert h["Authorization"] == "Bearer mytoken"

    def test_without_auth_token(self):
        from app.services.conversation.modstore_adapter import ModstorePlatformAdapter

        a = ModstorePlatformAdapter(auth_token="")
        h = a._build_headers()
        assert "Authorization" not in h


class TestModstorePlatformAdapterNormalizeResponse:
    """Cover ``_normalize_response``."""

    def test_with_choices_list(self):
        from app.services.conversation.modstore_adapter import ModstorePlatformAdapter

        a = ModstorePlatformAdapter()
        raw = {
            "choices": [
                {"message": {"role": "assistant", "content": "hi"}, "index": 0, "finish_reason": "stop"}
            ],
            "usage": {"prompt_tokens": 5},
            "model": "gpt-4",
        }
        result = a._normalize_response(raw, "openai", "gpt-4")
        assert result["choices"][0]["message"]["content"] == "hi"
        assert result["model"] == "gpt-4"

    def test_with_choices_and_tool_calls(self):
        from app.services.conversation.modstore_adapter import ModstorePlatformAdapter

        a = ModstorePlatformAdapter()
        raw = {
            "choices": [
                {
                    "message": {"role": "assistant", "content": "", "tool_calls": [{"id": "t1"}]},
                    "index": 0,
                    "finish_reason": "stop",
                }
            ],
            "usage": {},
        }
        result = a._normalize_response(raw, "openai", "gpt-4")
        assert result["choices"][0]["message"]["tool_calls"] == [{"id": "t1"}]

    def test_without_choices_uses_content(self):
        from app.services.conversation.modstore_adapter import ModstorePlatformAdapter

        a = ModstorePlatformAdapter()
        raw = {"content": "hello", "usage": {"prompt_tokens": 3}, "success": True}
        result = a._normalize_response(raw, "xiaomi", "mimo")
        assert result["choices"][0]["message"]["content"] == "hello"
        assert result["model"] == "xiaomi/mimo"
        assert result["_modstore_meta"]["success"] is True

    def test_usage_dataclass_converted_to_dict(self):
        from app.services.conversation.modstore_adapter import ModstorePlatformAdapter

        a = ModstorePlatformAdapter()
        usage_obj = SimpleNamespace(prompt_tokens=10, completion_tokens=20)
        raw = {"content": "hi", "usage": usage_obj}
        result = a._normalize_response(raw, "p", "m")
        assert isinstance(result["usage"], dict)

    def test_empty_choices_list_falls_through(self):
        from app.services.conversation.modstore_adapter import ModstorePlatformAdapter

        a = ModstorePlatformAdapter()
        raw = {"choices": [], "content": "fallback", "usage": {}}
        result = a._normalize_response(raw, "p", "m")
        assert result["choices"][0]["message"]["content"] == "fallback"


class TestModstorePlatformAdapterChatCompletion:
    """Cover ``chat_completion`` async method."""

    @pytest.mark.asyncio
    async def test_chat_completion_no_url_raises_value_error(self, monkeypatch):
        from app.services.conversation.modstore_adapter import ModstorePlatformAdapter

        monkeypatch.delenv("MODSTORE_PLATFORM_URL", raising=False)
        a = ModstorePlatformAdapter()
        a.platform_url = ""  # Force empty to trigger ValueError
        with pytest.raises(ValueError, match="平台URL未配置"):
            await a.chat_completion([{"role": "user", "content": "hi"}])

    @pytest.mark.asyncio
    async def test_chat_completion_success(self):
        from app.services.conversation.modstore_adapter import ModstorePlatformAdapter

        a = ModstorePlatformAdapter(platform_url="http://test", auth_token="tok")
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
        a._client = mock_client

        with patch(
            "app.services.conversation.modstore_adapter.neuro_notify_ai_model_roundtrip",
            create=True,
        ), patch(
            "app.neuro_bus.application_neuro_bridge.neuro_notify_ai_model_roundtrip",
            create=True,
        ):
            result = await a.chat_completion([{"role": "user", "content": "hi"}])
        assert result["choices"][0]["message"]["content"] == "hello"

    @pytest.mark.asyncio
    async def test_chat_completion_http_error_raises_value_error(self):
        from app.services.conversation.modstore_adapter import ModstorePlatformAdapter

        a = ModstorePlatformAdapter(platform_url="http://test", auth_token="tok")
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.is_closed = False
        a._client = mock_client

        with pytest.raises(ValueError, match="平台错误"):
            await a.chat_completion([{"role": "user", "content": "hi"}])

    @pytest.mark.asyncio
    async def test_chat_completion_with_user_id_in_payload(self):
        from app.services.conversation.modstore_adapter import ModstorePlatformAdapter

        a = ModstorePlatformAdapter(platform_url="http://test", user_id=99)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"content": "ok", "usage": {}, "success": True}

        mock_client = AsyncMock()
        mock_client.is_closed = False
        mock_client.post = AsyncMock(return_value=mock_response)
        a._client = mock_client

        with patch(
            "app.services.conversation.modstore_adapter.neuro_notify_ai_model_roundtrip",
            create=True,
        ), patch(
            "app.neuro_bus.application_neuro_bridge.neuro_notify_ai_model_roundtrip",
            create=True,
        ):
            await a.chat_completion([{"role": "user", "content": "hi"}])
        call_kwargs = mock_client.post.call_args
        assert call_kwargs[1]["json"]["user_id"] == 99


class TestModstorePlatformAdapterFromSession:
    """Cover ``from_session`` class method."""

    def test_from_session_with_env_token(self, monkeypatch):
        from app.services.conversation.modstore_adapter import ModstorePlatformAdapter

        monkeypatch.setenv("MODSTORE_AUTH_TOKEN", "env_token")
        monkeypatch.delenv("XCAGI_MARKET_BASE_URL", raising=False)
        monkeypatch.setenv("MODSTORE_PLATFORM_URL", "http://env:8765")
        a = ModstorePlatformAdapter.from_session()
        assert a.auth_token == "env_token"
        assert a._source == "env"

    def test_from_session_with_request_auth_header(self, monkeypatch):
        from app.services.conversation.modstore_adapter import ModstorePlatformAdapter

        monkeypatch.delenv("MODSTORE_AUTH_TOKEN", raising=False)
        monkeypatch.delenv("XCAGI_MARKET_BASE_URL", raising=False)
        monkeypatch.setenv("MODSTORE_PLATFORM_URL", "http://test:8765")

        mock_request = MagicMock()
        mock_request.headers.get.return_value = "Bearer req_token"

        # The request Authorization header should be picked up directly
        a = ModstorePlatformAdapter.from_session(request=mock_request)
        # The token from request header should be set (no session lookup needed)
        assert a.auth_token == "req_token"

    def test_from_session_no_token_no_session(self, monkeypatch):
        from app.services.conversation.modstore_adapter import ModstorePlatformAdapter

        monkeypatch.delenv("MODSTORE_AUTH_TOKEN", raising=False)
        monkeypatch.delenv("XCAGI_MARKET_BASE_URL", raising=False)
        monkeypatch.setenv("MODSTORE_PLATFORM_URL", "http://test:8765")

        a = ModstorePlatformAdapter.from_session(session_id="", request=None)
        assert a.auth_token == ""


class TestModstorePlatformAdapterRefreshToken:
    """Cover ``refresh_token_from_session``."""

    def test_refresh_no_session_id_returns_false(self):
        from app.services.conversation.modstore_adapter import ModstorePlatformAdapter

        a = ModstorePlatformAdapter()
        assert a.refresh_token_from_session(session_id="", request=None) is False

    def test_refresh_with_valid_session_succeeds(self):
        from app.services.conversation.modstore_adapter import ModstorePlatformAdapter

        a = ModstorePlatformAdapter(auth_token="old")
        with patch.dict(
            "sys.modules",
            {"app.fastapi_routes.market_account": MagicMock(
                session_id_from_request=Mock(return_value=""),
                session_market_token=Mock(return_value="new_token"),
            )},
        ):
            result = a.refresh_token_from_session(session_id="sid1")
        assert result is True
        assert a.auth_token == "new_token"

    def test_refresh_session_no_token_returns_false(self):
        from app.services.conversation.modstore_adapter import ModstorePlatformAdapter

        a = ModstorePlatformAdapter(auth_token="old")
        with patch.dict(
            "sys.modules",
            {"app.fastapi_routes.market_account": MagicMock(
                session_id_from_request=Mock(return_value=""),
                session_market_token=Mock(return_value=""),
            )},
        ):
            result = a.refresh_token_from_session(session_id="sid1")
        assert result is False


class TestModstorePlatformAdapterGetProviders:
    """Cover ``get_available_providers``."""

    @pytest.mark.asyncio
    async def test_get_providers_success(self):
        from app.services.conversation.modstore_adapter import ModstorePlatformAdapter

        a = ModstorePlatformAdapter(platform_url="http://test")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"providers": [{"name": "openai"}]}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.is_closed = False
        a._client = mock_client

        result = await a.get_available_providers()
        assert result == [{"name": "openai"}]

    @pytest.mark.asyncio
    async def test_get_providers_failure_returns_empty(self):
        from app.services.conversation.modstore_adapter import ModstorePlatformAdapter

        a = ModstorePlatformAdapter(platform_url="http://test")
        mock_response = MagicMock()
        mock_response.status_code = 500

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.is_closed = False
        a._client = mock_client

        result = await a.get_available_providers()
        assert result == []

    @pytest.mark.asyncio
    async def test_get_providers_exception_returns_empty(self):
        from app.services.conversation.modstore_adapter import ModstorePlatformAdapter

        a = ModstorePlatformAdapter(platform_url="http://test")
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=RuntimeError("conn fail"))
        mock_client.is_closed = False
        a._client = mock_client

        result = await a.get_available_providers()
        assert result == []


class TestModstorePlatformAdapterGetCredentialStatus:
    """Cover ``get_credential_status``."""

    @pytest.mark.asyncio
    async def test_get_credential_status_success(self):
        from app.services.conversation.modstore_adapter import ModstorePlatformAdapter

        a = ModstorePlatformAdapter(platform_url="http://test")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"active": True}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.is_closed = False
        a._client = mock_client

        result = await a.get_credential_status()
        assert result == {"active": True}

    @pytest.mark.asyncio
    async def test_get_credential_status_http_error(self):
        from app.services.conversation.modstore_adapter import ModstorePlatformAdapter

        a = ModstorePlatformAdapter(platform_url="http://test")
        mock_response = MagicMock()
        mock_response.status_code = 403

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.is_closed = False
        a._client = mock_client

        result = await a.get_credential_status()
        assert "error" in result

    @pytest.mark.asyncio
    async def test_get_credential_status_exception(self):
        from app.services.conversation.modstore_adapter import ModstorePlatformAdapter

        a = ModstorePlatformAdapter(platform_url="http://test")
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=OSError("timeout"))
        mock_client.is_closed = False
        a._client = mock_client

        result = await a.get_credential_status()
        assert "error" in result


class TestModstorePlatformAdapterClose:
    """Cover ``close``."""

    @pytest.mark.asyncio
    async def test_close_open_client(self):
        from app.services.conversation.modstore_adapter import ModstorePlatformAdapter

        a = ModstorePlatformAdapter()
        mock_client = AsyncMock()
        mock_client.is_closed = False
        a._client = mock_client

        await a.close()
        mock_client.aclose.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_close_no_client_no_error(self):
        from app.services.conversation.modstore_adapter import ModstorePlatformAdapter

        a = ModstorePlatformAdapter()
        a._client = None
        await a.close()  # should not raise


class TestCreateModstoreAdapterFromEnv:
    """Cover ``create_modstore_adapter_from_env``."""

    def test_no_env_returns_none(self, monkeypatch):
        from app.services.conversation.modstore_adapter import create_modstore_adapter_from_env

        monkeypatch.delenv("MODSTORE_PLATFORM_URL", raising=False)
        assert create_modstore_adapter_from_env() is None

    def test_with_env_returns_adapter(self, monkeypatch):
        from app.services.conversation.modstore_adapter import create_modstore_adapter_from_env

        monkeypatch.setenv("MODSTORE_PLATFORM_URL", "http://env:8765")
        result = create_modstore_adapter_from_env()
        assert result is not None
        assert result.platform_url == "http://env:8765"


class TestModstoreOpenAICompatibleClient:
    """Cover ``ModstoreOpenAICompatibleClient`` and inner classes."""

    def test_default_model_property(self):
        from app.services.conversation.modstore_adapter import (
            ModstoreOpenAICompatibleClient,
            ModstorePlatformAdapter,
        )

        a = ModstorePlatformAdapter(default_model="gpt-4o")
        c = ModstoreOpenAICompatibleClient(a)
        assert c.default_model == "gpt-4o"

    def test_default_provider_property(self):
        from app.services.conversation.modstore_adapter import (
            ModstoreOpenAICompatibleClient,
            ModstorePlatformAdapter,
        )

        a = ModstorePlatformAdapter(default_provider="openai")
        c = ModstoreOpenAICompatibleClient(a)
        assert c.default_provider == "openai"

    def test_is_modstore_openai_compatible_flag(self):
        from app.services.conversation.modstore_adapter import (
            ModstoreOpenAICompatibleClient,
            ModstorePlatformAdapter,
        )

        c = ModstoreOpenAICompatibleClient(ModstorePlatformAdapter())
        assert c.is_modstore_openai_compatible is True


class TestModstoreOpenAICompletionsCreate:
    """Cover ``_ModstoreOpenAICompletions.create`` non-stream path."""

    def test_create_non_stream_returns_simplenamespace(self):
        from app.services.conversation.modstore_adapter import (
            ModstoreOpenAICompatibleClient,
            ModstorePlatformAdapter,
        )

        a = ModstorePlatformAdapter(platform_url="http://test")
        mock_result = {
            "choices": [{"message": {"role": "assistant", "content": "hi"}, "index": 0, "finish_reason": "stop"}],
            "usage": {},
            "model": "test/model",
        }
        with patch.object(a, "chat_completion_sync", return_value=mock_result):
            c = ModstoreOpenAICompatibleClient(a)
            result = c.chat.completions.create(
                messages=[{"role": "user", "content": "hi"}],
                stream=False,
            )
        assert isinstance(result, SimpleNamespace)


class TestModstoreProxyAdapterAlias:
    """Cover backward-compat alias."""

    def test_alias_is_same_class(self):
        from app.services.conversation.modstore_adapter import (
            ModstorePlatformAdapter,
            ModstoreProxyAdapter,
        )

        assert ModstoreProxyAdapter is ModstorePlatformAdapter


# ===========================================================================
# 2. app/infrastructure/mods/employee_registry.py
# ===========================================================================


def _write_manifest(directory: str, manifest: dict) -> None:
    os.makedirs(directory, exist_ok=True)
    with open(os.path.join(directory, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f)


class TestEmployeesRoot:
    def test_employees_root_joins_dir(self):
        from app.infrastructure.mods.employee_registry import employees_root

        assert employees_root("/data/mods") == "/data/mods/_employees"


class TestEmployeeRegistryListPacks:
    """Cover ``EmployeeRegistry.list_packs``."""

    def test_list_packs_empty_dir(self, tmp_dir):
        from app.infrastructure.mods.employee_registry import EmployeeRegistry

        reg = EmployeeRegistry(tmp_dir)
        assert reg.list_packs() == []

    def test_list_packs_no_dir(self, tmp_dir):
        from app.infrastructure.mods.employee_registry import EmployeeRegistry

        reg = EmployeeRegistry(tmp_dir)
        os.rmdir(os.path.join(tmp_dir, "_employees")) if os.path.isdir(
            os.path.join(tmp_dir, "_employees")
        ) else None
        assert reg.list_packs() == []

    def test_list_packs_valid_pack(self, tmp_dir):
        from app.infrastructure.mods.employee_registry import EmployeeRegistry

        emp_dir = os.path.join(tmp_dir, "_employees", "pack1")
        _write_manifest(emp_dir, {
            "artifact": "employee_pack",
            "id": "pack1",
            "name": "Test Pack",
            "version": "1.0",
            "author": "dev",
            "description": "desc",
            "employee": {"id": "emp1"},
        })
        reg = EmployeeRegistry(tmp_dir)
        packs = reg.list_packs()
        assert len(packs) == 1
        assert packs[0]["pack_id"] == "pack1"
        assert packs[0]["employee"] == {"id": "emp1"}

    def test_list_packs_skips_non_employee_pack(self, tmp_dir):
        from app.infrastructure.mods.employee_registry import EmployeeRegistry

        emp_dir = os.path.join(tmp_dir, "_employees", "mod1")
        _write_manifest(emp_dir, {"artifact": "mod", "id": "mod1"})
        reg = EmployeeRegistry(tmp_dir)
        assert reg.list_packs() == []

    def test_list_packs_skips_dir_without_manifest(self, tmp_dir):
        from app.infrastructure.mods.employee_registry import EmployeeRegistry

        os.makedirs(os.path.join(tmp_dir, "_employees", "empty_pack"))
        reg = EmployeeRegistry(tmp_dir)
        assert reg.list_packs() == []

    def test_list_packs_skips_invalid_json(self, tmp_dir):
        from app.infrastructure.mods.employee_registry import EmployeeRegistry

        emp_dir = os.path.join(tmp_dir, "_employees", "bad_json")
        os.makedirs(emp_dir, exist_ok=True)
        with open(os.path.join(emp_dir, "manifest.json"), "w") as f:
            f.write("not json{{{")
        reg = EmployeeRegistry(tmp_dir)
        assert reg.list_packs() == []

    def test_list_packs_skips_files_not_dirs(self, tmp_dir):
        from app.infrastructure.mods.employee_registry import EmployeeRegistry

        os.makedirs(os.path.join(tmp_dir, "_employees"), exist_ok=True)
        with open(os.path.join(tmp_dir, "_employees", "readme.txt"), "w") as f:
            f.write("not a dir")
        reg = EmployeeRegistry(tmp_dir)
        assert reg.list_packs() == []

    def test_list_packs_xcagi_host_profile(self, tmp_dir):
        from app.infrastructure.mods.employee_registry import EmployeeRegistry

        emp_dir = os.path.join(tmp_dir, "_employees", "pack2")
        _write_manifest(emp_dir, {
            "artifact": "employee_pack",
            "id": "pack2",
            "name": "P2",
            "version": "1.0",
            "author": "",
            "description": "",
            "employee": {},
            "xcagi_host_profile": {"panel_kind": "builtin_track"},
        })
        reg = EmployeeRegistry(tmp_dir)
        packs = reg.list_packs()
        assert packs[0]["xcagi_host_profile"] == {"panel_kind": "builtin_track"}


class TestEmployeeRegistryListForModsApi:
    """Cover ``EmployeeRegistry.list_for_mods_api``."""

    def test_list_for_mods_api_basic(self, tmp_dir):
        from app.infrastructure.mods.employee_registry import EmployeeRegistry

        emp_dir = os.path.join(tmp_dir, "_employees", "pack1")
        _write_manifest(emp_dir, {
            "artifact": "employee_pack",
            "id": "pack1",
            "name": "Pack1",
            "version": "2.0",
            "author": "a",
            "description": "d",
            "employee": {"id": "e1"},
        })
        reg = EmployeeRegistry(tmp_dir)
        rows = reg.list_for_mods_api()
        assert len(rows) == 1
        assert rows[0]["type"] == "employee_pack"
        assert rows[0]["primary"] is False

    def test_list_for_mods_api_host_foundation_pack_no_wf(self, tmp_dir):
        from app.infrastructure.mods.employee_registry import EmployeeRegistry

        emp_dir = os.path.join(tmp_dir, "_employees", "hfp")
        _write_manifest(emp_dir, {
            "artifact": "employee_pack",
            "id": "hfp",
            "name": "Host FP",
            "version": "1.0",
            "author": "",
            "description": "",
            "employee": {},
            "config": {"host_foundation_pack": True},
            "workflow_employees": [{"id": "w1"}],
        })
        reg = EmployeeRegistry(tmp_dir)
        rows = reg.list_for_mods_api()
        assert rows[0]["workflow_employees"] == []

    def test_list_for_mods_api_with_workflow_employees(self, tmp_dir):
        from app.infrastructure.mods.employee_registry import EmployeeRegistry

        emp_dir = os.path.join(tmp_dir, "_employees", "wp")
        _write_manifest(emp_dir, {
            "artifact": "employee_pack",
            "id": "wp",
            "name": "WP",
            "version": "1.0",
            "author": "",
            "description": "",
            "employee": {},
            "workflow_employees": [{"id": "w1"}, {"id": "w2"}, "invalid"],
        })
        reg = EmployeeRegistry(tmp_dir)
        rows = reg.list_for_mods_api()
        assert len(rows[0]["workflow_employees"]) == 2

    def test_list_for_mods_api_bad_manifest_json(self, tmp_dir):
        from app.infrastructure.mods.employee_registry import EmployeeRegistry

        emp_dir = os.path.join(tmp_dir, "_employees", "bad")
        os.makedirs(emp_dir, exist_ok=True)
        with open(os.path.join(emp_dir, "manifest.json"), "w") as f:
            f.write("broken{")
        reg = EmployeeRegistry(tmp_dir)
        # Should not crash; list_for_mods_api re-reads manifest
        rows = reg.list_for_mods_api()
        assert len(rows) == 0


class TestEmployeeRegistryInstallFromPackage:
    """Cover ``EmployeeRegistry.install_from_package``."""

    def test_install_nonexistent_file_returns_false(self, tmp_dir):
        from app.infrastructure.mods.employee_registry import EmployeeRegistry

        reg = EmployeeRegistry(tmp_dir)
        ok, msg = reg.install_from_package("/nonexistent/file.zip")
        assert ok is False
        assert "不存在" in msg

    def test_install_non_employee_pack_returns_false(self, tmp_dir):
        from app.infrastructure.mods.employee_registry import EmployeeRegistry

        # Create a zip with a mod manifest (not employee_pack)
        import zipfile

        zip_path = os.path.join(tmp_dir, "mod.zip")
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("manifest.json", json.dumps({"artifact": "mod", "id": "m1"}))
        reg = EmployeeRegistry(tmp_dir)
        ok, msg = reg.install_from_package(zip_path, verify_signature=False)
        assert ok is False
        assert "非 employee_pack" in msg

    def test_install_invalid_manifest_returns_false(self, tmp_dir):
        from app.infrastructure.mods.employee_registry import EmployeeRegistry

        import zipfile

        zip_path = os.path.join(tmp_dir, "bad_emp.zip")
        manifest = {"artifact": "employee_pack", "id": "bad", "employee": None}
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("manifest.json", json.dumps(manifest))
        reg = EmployeeRegistry(tmp_dir)
        ok, msg = reg.install_from_package(zip_path, verify_signature=False)
        assert ok is False

    def test_install_non_global_scope_returns_false(self, tmp_dir):
        from app.infrastructure.mods.employee_registry import EmployeeRegistry

        import zipfile

        zip_path = os.path.join(tmp_dir, "host_emp.zip")
        manifest = {
            "artifact": "employee_pack",
            "id": "he1",
            "employee": {"id": "e1"},
            "scope": "host",
        }
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("manifest.json", json.dumps(manifest))
        reg = EmployeeRegistry(tmp_dir)
        ok, msg = reg.install_from_package(zip_path, verify_signature=False)
        assert ok is False
        assert "scope" in msg

    def test_install_missing_id_returns_false(self, tmp_dir):
        from app.infrastructure.mods.employee_registry import EmployeeRegistry

        import zipfile

        zip_path = os.path.join(tmp_dir, "noid.zip")
        manifest = {
            "artifact": "employee_pack",
            "id": "",
            "employee": {"id": "e1"},
            "scope": "global",
        }
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("manifest.json", json.dumps(manifest))
        reg = EmployeeRegistry(tmp_dir)
        ok, msg = reg.install_from_package(zip_path, verify_signature=False)
        assert ok is False
        # ModPackage.extract_package raises "缺少 'id' 字段" before our check
        assert "id" in msg.lower()

    def test_install_global_employee_pack_success(self, tmp_dir):
        from app.infrastructure.mods.employee_registry import EmployeeRegistry

        import zipfile

        zip_path = os.path.join(tmp_dir, "good.zip")
        manifest = {
            "artifact": "employee_pack",
            "id": "emp1",
            "name": "Emp1",
            "version": "1.0",
            "employee": {"id": "e1"},
            "scope": "global",
        }
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("manifest.json", json.dumps(manifest))
        reg = EmployeeRegistry(tmp_dir)
        with patch(
            "app.mod_sdk.employee_runtime.refresh_employee_pack_runtime",
        ):
            ok, msg = reg.install_from_package(zip_path, verify_signature=False)
        assert ok is True
        assert "安装成功" in msg

    def test_install_host_foundation_pack_success(self, tmp_dir):
        from app.infrastructure.mods.employee_registry import EmployeeRegistry

        import zipfile

        zip_path = os.path.join(tmp_dir, "hf.zip")
        manifest = {
            "artifact": "employee_pack",
            "id": "hf1",
            "name": "HF",
            "version": "1.0",
            "employee": {"id": "e1"},
            "scope": "global",
            "config": {"host_foundation_pack": True, "edition": "generic"},
        }
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("manifest.json", json.dumps(manifest))
        reg = EmployeeRegistry(tmp_dir)
        with patch(
            "app.mod_sdk.host_foundation.materialize_host_foundation_bridges",
            return_value={"ready": True, "installed_count": 3, "expected_count": 3},
        ):
            ok, msg = reg.install_from_package(zip_path, verify_signature=False)
        assert ok is True
        assert "bridge" in msg

    def test_install_host_foundation_pack_bridges_not_ready(self, tmp_dir):
        from app.infrastructure.mods.employee_registry import EmployeeRegistry

        import zipfile

        zip_path = os.path.join(tmp_dir, "hf2.zip")
        manifest = {
            "artifact": "employee_pack",
            "id": "hf2",
            "name": "HF2",
            "version": "1.0",
            "employee": {"id": "e1"},
            "scope": "global",
            "config": {"host_foundation_pack": True, "edition": "full"},
        }
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("manifest.json", json.dumps(manifest))
        reg = EmployeeRegistry(tmp_dir)
        with patch(
            "app.mod_sdk.host_foundation.materialize_host_foundation_bridges",
            return_value={"ready": False, "missing_mod_ids": ["mod_a", "mod_b"]},
        ):
            ok, msg = reg.install_from_package(zip_path, verify_signature=False)
        assert ok is False
        assert "bridge 未齐" in msg

    def test_install_signature_error(self, tmp_dir):
        from app.infrastructure.mods.employee_registry import EmployeeRegistry
        from app.infrastructure.mods.package import ModSignatureError

        import zipfile

        zip_path = os.path.join(tmp_dir, "sig_err.zip")
        manifest = {"artifact": "employee_pack", "id": "s1", "employee": {"id": "e1"}}
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("manifest.json", json.dumps(manifest))

        reg = EmployeeRegistry(tmp_dir)
        with patch(
            "app.infrastructure.mods.package.ModPackage.extract_package",
            side_effect=ModSignatureError("bad sig"),
        ):
            ok, msg = reg.install_from_package(zip_path, verify_signature=True)
        assert ok is False
        assert "签名" in msg


class TestEmployeeRegistryUninstallPack:
    """Cover ``EmployeeRegistry.uninstall_pack``."""

    def test_uninstall_empty_id_returns_false(self, tmp_dir):
        from app.infrastructure.mods.employee_registry import EmployeeRegistry

        reg = EmployeeRegistry(tmp_dir)
        ok, msg = reg.uninstall_pack("")
        assert ok is False

    def test_uninstall_slash_in_id_returns_false(self, tmp_dir):
        from app.infrastructure.mods.employee_registry import EmployeeRegistry

        reg = EmployeeRegistry(tmp_dir)
        ok, msg = reg.uninstall_pack("a/b")
        assert ok is False

    def test_uninstall_backslash_in_id_returns_false(self, tmp_dir):
        from app.infrastructure.mods.employee_registry import EmployeeRegistry

        reg = EmployeeRegistry(tmp_dir)
        ok, msg = reg.uninstall_pack("a\\b")
        assert ok is False

    def test_uninstall_not_installed_returns_false(self, tmp_dir):
        from app.infrastructure.mods.employee_registry import EmployeeRegistry

        reg = EmployeeRegistry(tmp_dir)
        ok, msg = reg.uninstall_pack("nonexistent")
        assert ok is False
        assert "未安装" in msg

    def test_uninstall_success(self, tmp_dir):
        from app.infrastructure.mods.employee_registry import EmployeeRegistry

        emp_dir = os.path.join(tmp_dir, "_employees", "pack1")
        _write_manifest(emp_dir, {
            "artifact": "employee_pack",
            "id": "pack1",
            "employee": {},
        })
        reg = EmployeeRegistry(tmp_dir)
        with patch(
            "app.mod_sdk.employee_runtime.refresh_employee_pack_runtime",
        ):
            ok, msg = reg.uninstall_pack("pack1")
        assert ok is True
        assert "已卸载" in msg

    def test_uninstall_without_removing_files(self, tmp_dir):
        from app.infrastructure.mods.employee_registry import EmployeeRegistry

        emp_dir = os.path.join(tmp_dir, "_employees", "pack1")
        _write_manifest(emp_dir, {
            "artifact": "employee_pack",
            "id": "pack1",
            "employee": {},
        })
        reg = EmployeeRegistry(tmp_dir)
        with patch(
            "app.mod_sdk.employee_runtime.refresh_employee_pack_runtime",
        ):
            ok, msg = reg.uninstall_pack("pack1", remove_files=False)
        assert ok is True
        # Dir should still exist since remove_files=False
        assert os.path.isdir(emp_dir)


class TestGetEmployeeRegistry:
    """Cover ``get_employee_registry`` singleton."""

    def test_returns_same_instance(self, tmp_dir, monkeypatch):
        from app.infrastructure.mods import employee_registry as er_mod

        # Clear the global registry to avoid cross-test pollution
        er_mod._registry.clear()
        monkeypatch.setattr("app.infrastructure.mods.mod_manager._default_mods_root", lambda: tmp_dir)
        r1 = er_mod.get_employee_registry(tmp_dir)
        r2 = er_mod.get_employee_registry(tmp_dir)
        assert r1 is r2
        er_mod._registry.clear()


# ===========================================================================
# 3. app/infrastructure/persistence/compat_db/writes.py
# ===========================================================================


class TestProductsDeleteByUnitPg:
    """Cover ``_products_delete_by_unit_pg``."""

    def test_empty_unit_name_returns_zero(self):
        from app.infrastructure.persistence.compat_db.writes import _products_delete_by_unit_pg

        result = _products_delete_by_unit_pg(MagicMock(), "")
        assert result == 0

    def test_none_unit_name_returns_zero(self):
        from app.infrastructure.persistence.compat_db.writes import _products_delete_by_unit_pg

        result = _products_delete_by_unit_pg(MagicMock(), None)
        assert result == 0

    def test_no_products_table_returns_zero(self):
        from app.infrastructure.persistence.compat_db.writes import _products_delete_by_unit_pg

        mock_eng = MagicMock()
        mock_insp = MagicMock()
        mock_insp.get_table_names.return_value = ["customers"]
        with patch("app.infrastructure.persistence.compat_db.writes.inspect", return_value=mock_insp):
            result = _products_delete_by_unit_pg(mock_eng, "unit1")
        assert result == 0

    def test_products_table_no_unit_column_returns_zero(self):
        from app.infrastructure.persistence.compat_db.writes import _products_delete_by_unit_pg

        mock_eng = MagicMock()
        mock_insp = MagicMock()
        mock_insp.get_table_names.return_value = ["products"]
        mock_insp.get_columns.return_value = [{"name": "id"}, {"name": "name"}]
        with patch("app.infrastructure.persistence.compat_db.writes.inspect", return_value=mock_insp):
            result = _products_delete_by_unit_pg(mock_eng, "unit1")
        assert result == 0


class TestPurchaseUnitsDeleteByNormUnitPg:
    """Cover ``_purchase_units_delete_by_norm_unit_pg``."""

    def test_empty_unit_name_returns_zero(self):
        from app.infrastructure.persistence.compat_db.writes import _purchase_units_delete_by_norm_unit_pg

        result = _purchase_units_delete_by_norm_unit_pg(MagicMock(), "")
        assert result == 0

    def test_no_purchase_units_table_returns_zero(self):
        from app.infrastructure.persistence.compat_db.writes import _purchase_units_delete_by_norm_unit_pg

        mock_eng = MagicMock()
        mock_insp = MagicMock()
        mock_insp.get_table_names.return_value = ["products"]
        with patch("app.infrastructure.persistence.compat_db.writes.inspect", return_value=mock_insp):
            result = _purchase_units_delete_by_norm_unit_pg(mock_eng, "unit1")
        assert result == 0

    def test_no_unit_name_column_returns_zero(self):
        from app.infrastructure.persistence.compat_db.writes import _purchase_units_delete_by_norm_unit_pg

        mock_eng = MagicMock()
        mock_insp = MagicMock()
        mock_insp.get_table_names.return_value = ["purchase_units"]
        mock_insp.get_columns.return_value = [{"name": "id"}]
        with patch("app.infrastructure.persistence.compat_db.writes.inspect", return_value=mock_insp):
            result = _purchase_units_delete_by_norm_unit_pg(mock_eng, "unit1")
        assert result == 0


class TestCustomersDeleteByNormNamePg:
    """Cover ``_customers_delete_by_norm_name_pg``."""

    def test_empty_name_returns_zero(self):
        from app.infrastructure.persistence.compat_db.writes import _customers_delete_by_norm_name_pg

        mock_insp = MagicMock()
        result = _customers_delete_by_norm_name_pg(MagicMock(), mock_insp, "")
        assert result == 0

    def test_no_customers_table_returns_zero(self):
        from app.infrastructure.persistence.compat_db.writes import _customers_delete_by_norm_name_pg

        mock_insp = MagicMock()
        mock_insp.get_table_names.return_value = ["products"]
        result = _customers_delete_by_norm_name_pg(MagicMock(), mock_insp, "name1")
        assert result == 0

    def test_no_name_column_returns_zero(self):
        from app.infrastructure.persistence.compat_db.writes import _customers_delete_by_norm_name_pg

        mock_insp = MagicMock()
        mock_insp.get_table_names.return_value = ["customers"]
        mock_insp.get_columns.return_value = [{"name": "id"}]
        result = _customers_delete_by_norm_name_pg(MagicMock(), mock_insp, "name1")
        assert result == 0


class TestPurchaseUnitsDeleteByIdPg:
    """Cover ``_purchase_units_delete_by_id_pg``."""

    def test_no_purchase_units_table_returns_zero(self):
        from app.infrastructure.persistence.compat_db.writes import _purchase_units_delete_by_id_pg

        mock_eng = MagicMock()
        mock_insp = MagicMock()
        mock_insp.get_table_names.return_value = ["products"]
        with patch("app.infrastructure.persistence.compat_db.writes.inspect", return_value=mock_insp):
            result = _purchase_units_delete_by_id_pg(mock_eng, 1)
        assert result == 0

    def test_no_id_column_returns_zero(self):
        from app.infrastructure.persistence.compat_db.writes import _purchase_units_delete_by_id_pg

        mock_eng = MagicMock()
        mock_insp = MagicMock()
        mock_insp.get_table_names.return_value = ["purchase_units"]
        mock_insp.get_columns.return_value = [{"name": "unit_name"}]
        with patch("app.infrastructure.persistence.compat_db.writes.inspect", return_value=mock_insp):
            result = _purchase_units_delete_by_id_pg(mock_eng, 1)
        assert result == 0


class TestCustomersDeleteByIdPg:
    """Cover ``_customers_delete_by_id_pg``."""

    def test_no_customers_table_returns_zero(self):
        from app.infrastructure.persistence.compat_db.writes import _customers_delete_by_id_pg

        mock_insp = MagicMock()
        mock_insp.get_table_names.return_value = ["products"]
        result = _customers_delete_by_id_pg(MagicMock(), mock_insp, 1)
        assert result == 0

    def test_no_id_or_customer_id_column_returns_zero(self):
        from app.infrastructure.persistence.compat_db.writes import _customers_delete_by_id_pg

        mock_insp = MagicMock()
        mock_insp.get_table_names.return_value = ["customers"]
        mock_insp.get_columns.return_value = [{"name": "name"}]
        result = _customers_delete_by_id_pg(MagicMock(), mock_insp, 1)
        assert result == 0


class TestProductsUnitReplacePg:
    """Cover ``_products_unit_replace_pg``."""

    def test_empty_old_name_returns_none(self):
        from app.infrastructure.persistence.compat_db.writes import _products_unit_replace_pg

        # Should return None (no-op)
        result = _products_unit_replace_pg(MagicMock(), "", "new")
        assert result is None

    def test_empty_new_name_returns_none(self):
        from app.infrastructure.persistence.compat_db.writes import _products_unit_replace_pg

        result = _products_unit_replace_pg(MagicMock(), "old", "")
        assert result is None

    def test_same_name_returns_none(self):
        from app.infrastructure.persistence.compat_db.writes import _products_unit_replace_pg

        result = _products_unit_replace_pg(MagicMock(), "same", "same")
        assert result is None

    def test_no_products_table_returns_none(self):
        from app.infrastructure.persistence.compat_db.writes import _products_unit_replace_pg

        mock_eng = MagicMock()
        mock_insp = MagicMock()
        mock_insp.get_table_names.return_value = ["customers"]
        with patch("app.infrastructure.persistence.compat_db.writes.inspect", return_value=mock_insp):
            result = _products_unit_replace_pg(mock_eng, "old", "new")
        assert result is None


class TestCustomerPgRowSelectSql:
    """Cover ``_customer_pg_row_select_sql``."""

    def test_missing_id_raises_503(self):
        from app.infrastructure.persistence.compat_db.writes import _customer_pg_row_select_sql

        mock_insp = MagicMock()
        mock_insp.get_columns.return_value = [{"name": "unit_name"}]
        with pytest.raises(Exception) as exc_info:
            _customer_pg_row_select_sql(mock_insp)
        assert exc_info.value.status_code == 503

    def test_valid_columns_returns_sql(self):
        from app.infrastructure.persistence.compat_db.writes import _customer_pg_row_select_sql

        mock_insp = MagicMock()
        mock_insp.get_columns.return_value = [
            {"name": "id"},
            {"name": "unit_name"},
            {"name": "contact_person"},
        ]
        sql, sel = _customer_pg_row_select_sql(mock_insp)
        assert "id" in sql
        assert "unit_name" in sel


class TestCustomerPgFetchById:
    """Cover ``_customer_pg_fetch_by_id``."""

    def test_not_found_raises_404(self):
        from app.infrastructure.persistence.compat_db.writes import _customer_pg_fetch_by_id

        mock_eng = MagicMock()
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.mappings.return_value.first.return_value = None
        mock_conn.execute.return_value = mock_result
        mock_eng.connect.return_value.__enter__ = Mock(return_value=mock_conn)
        mock_eng.connect.return_value.__exit__ = Mock(return_value=False)

        mock_insp = MagicMock()
        mock_insp.get_columns.return_value = [
            {"name": "id"},
            {"name": "unit_name"},
        ]
        with pytest.raises(Exception) as exc_info:
            _customer_pg_fetch_by_id(mock_eng, mock_insp, 999)
        assert exc_info.value.status_code == 404


class TestCustomerPgInsert:
    """Cover ``_customer_pg_insert``."""

    def test_missing_unit_name_raises_503(self):
        from app.infrastructure.persistence.compat_db.writes import _customer_pg_insert

        mock_eng = MagicMock()
        mock_insp = MagicMock()
        mock_insp.get_columns.return_value = [{"name": "id"}]
        with patch(
            "app.infrastructure.persistence.compat_db.writes._customer_pg_engine_insp",
            return_value=(mock_eng, mock_insp),
        ):
            with pytest.raises(Exception) as exc_info:
                _customer_pg_insert("name", "cp", "ph", "addr")
            assert exc_info.value.status_code == 503


class TestCustomerPgDeleteAnywhere:
    """Cover ``_customer_pg_delete_anywhere``."""

    def test_no_records_found_raises_404(self):
        from app.infrastructure.persistence.compat_db.writes import _customer_pg_delete_anywhere

        mock_eng = MagicMock()
        mock_insp = MagicMock()
        mock_insp.get_table_names.return_value = []
        with patch(
            "app.infrastructure.persistence.compat_db.writes._customer_pg_engine_insp",
            return_value=(mock_eng, mock_insp),
        ), patch(
            "app.infrastructure.persistence.compat_db.writes._customer_pg_select_customers_name_by_id",
            return_value=None,
        ), patch(
            "app.infrastructure.persistence.compat_db.queries._customer_find_by_id",
            return_value=None,
            create=True,
        ):
            with pytest.raises(Exception) as exc_info:
                _customer_pg_delete_anywhere(999)
            assert exc_info.value.status_code == 404


class TestProductsPgUpdateRow:
    """Cover ``products_pg_update_row``."""

    def test_missing_required_columns_raises_503(self):
        from app.infrastructure.persistence.compat_db.writes import products_pg_update_row

        mock_eng = MagicMock()
        with patch(
            "app.infrastructure.persistence.compat_db.writes.get_sync_engine",
            return_value=mock_eng,
        ), patch(
            "app.infrastructure.persistence.compat_db.writes._products_pg_col_names",
            return_value={"id"},
        ):
            with pytest.raises(Exception) as exc_info:
                products_pg_update_row(
                    1, {"name": "x"}, parse_price=lambda x: x,
                    parse_quantity=lambda x: x, parse_is_active=lambda x: x,
                )
            assert exc_info.value.status_code == 503

    def test_empty_name_raises_400(self):
        from app.infrastructure.persistence.compat_db.writes import products_pg_update_row

        mock_eng = MagicMock()
        with patch(
            "app.infrastructure.persistence.compat_db.writes.get_sync_engine",
            return_value=mock_eng,
        ), patch(
            "app.infrastructure.persistence.compat_db.writes._products_pg_col_names",
            return_value={"id", "model_number", "name"},
        ):
            with pytest.raises(Exception) as exc_info:
                products_pg_update_row(
                    1, {"name": ""}, parse_price=lambda x: x,
                    parse_quantity=lambda x: x, parse_is_active=lambda x: x,
                )
            assert exc_info.value.status_code == 400


class TestProductsPgInsertRow:
    """Cover ``products_pg_insert_row``."""

    def test_missing_required_columns_raises_503(self):
        from app.infrastructure.persistence.compat_db.writes import products_pg_insert_row

        mock_eng = MagicMock()
        mock_excel = MagicMock()
        mock_excel._norm_model = MagicMock(return_value="model")
        with patch(
            "app.infrastructure.persistence.compat_db.writes.get_sync_engine",
            return_value=mock_eng,
        ), patch(
            "app.infrastructure.persistence.compat_db.writes._products_pg_col_names",
            return_value={"id"},
        ), patch.dict(
            "sys.modules",
            {"app.application.excel_imports": mock_excel},
        ):
            with pytest.raises(Exception) as exc_info:
                products_pg_insert_row(
                    {"name": "x"}, parse_price=lambda x: x,
                    parse_quantity=lambda x: x, parse_is_active=lambda x: x,
                )
            assert exc_info.value.status_code == 503

    def test_empty_name_raises_400(self):
        from app.infrastructure.persistence.compat_db.writes import products_pg_insert_row

        mock_eng = MagicMock()
        mock_excel = MagicMock()
        mock_excel._norm_model = MagicMock(return_value="model")
        with patch(
            "app.infrastructure.persistence.compat_db.writes.get_sync_engine",
            return_value=mock_eng,
        ), patch(
            "app.infrastructure.persistence.compat_db.writes._products_pg_col_names",
            return_value={"model_number", "name"},
        ), patch.dict(
            "sys.modules",
            {"app.application.excel_imports": mock_excel},
        ):
            with pytest.raises(Exception) as exc_info:
                products_pg_insert_row(
                    {"name": ""}, parse_price=lambda x: x,
                    parse_quantity=lambda x: x, parse_is_active=lambda x: x,
                )
            assert exc_info.value.status_code == 400


class TestProductsPgDeleteRow:
    """Cover ``products_pg_delete_row``."""

    def test_product_not_found_raises_404(self):
        from app.infrastructure.persistence.compat_db.writes import products_pg_delete_row

        mock_eng = MagicMock()
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.rowcount = 0
        mock_conn.execute.return_value = mock_result
        mock_eng.begin.return_value.__enter__ = Mock(return_value=mock_conn)
        mock_eng.begin.return_value.__exit__ = Mock(return_value=False)

        with patch(
            "app.infrastructure.persistence.compat_db.writes.get_sync_engine",
            return_value=mock_eng,
        ), patch(
            "app.infrastructure.persistence.compat_db.writes._products_pg_col_names",
            return_value={"id"},
        ):
            with pytest.raises(Exception) as exc_info:
                products_pg_delete_row(999)
            assert exc_info.value.status_code == 404


class TestProductsPgBatchDeleteRows:
    """Cover ``products_pg_batch_delete_rows``."""

    def test_invalid_ids_skipped(self):
        from app.infrastructure.persistence.compat_db.writes import products_pg_batch_delete_rows

        mock_eng = MagicMock()
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.rowcount = 0
        mock_conn.execute.return_value = mock_result
        mock_eng.begin.return_value.__enter__ = Mock(return_value=mock_conn)
        mock_eng.begin.return_value.__exit__ = Mock(return_value=False)

        with patch(
            "app.infrastructure.persistence.compat_db.writes.get_sync_engine",
            return_value=mock_eng,
        ), patch(
            "app.infrastructure.persistence.compat_db.writes._products_pg_col_names",
            return_value={"id"},
        ):
            deleted, skipped = products_pg_batch_delete_rows(["abc", None, False])
        assert deleted == 0
        assert len(skipped) == 3


# ===========================================================================
# 4. app/neuro_bus/sandbox.py
# ===========================================================================


class TestSideEffectType:
    """Cover ``SideEffectType`` enum values."""

    def test_all_values_exist(self):
        from app.neuro_bus.sandbox import SideEffectType

        assert SideEffectType.READ.value == "read"
        assert SideEffectType.WRITE.value == "write"
        assert SideEffectType.DELETE.value == "delete"
        assert SideEffectType.EXTERNAL_CALL.value == "external_call"
        assert SideEffectType.PAYMENT.value == "payment"
        assert SideEffectType.NOTIFICATION.value == "notification"


class TestSideEffect:
    """Cover ``SideEffect`` dataclass."""

    def test_default_values(self):
        from app.neuro_bus.sandbox import SideEffect, SideEffectType

        se = SideEffect(effect_type=SideEffectType.READ, target="key1", description="read key1")
        assert se.data == {}
        assert se.risk_level == 1

    def test_custom_values(self):
        from app.neuro_bus.sandbox import SideEffect, SideEffectType

        se = SideEffect(
            effect_type=SideEffectType.PAYMENT,
            target="gateway",
            description="pay",
            data={"amount": 100},
            risk_level=5,
        )
        assert se.data == {"amount": 100}
        assert se.risk_level == 5


class TestSandboxReport:
    """Cover ``SandboxReport`` dataclass."""

    def test_report_fields(self):
        from app.neuro_bus.sandbox import SandboxReport, SideEffect

        report = SandboxReport(
            event_id="e1",
            event_type="test",
            can_execute=True,
            risk_score=30.0,
            side_effects=[],
            warnings=[],
            recommendations=[],
        )
        assert report.can_execute is True
        assert report.risk_score == 30.0


class TestSandboxContext:
    """Cover ``SandboxContext``."""

    def test_virtual_read_returns_none_for_missing_key(self, make_neuro_event):
        from app.neuro_bus.sandbox import SandboxContext

        ctx = SandboxContext(make_neuro_event())
        result = ctx.virtual_read("missing_key")
        assert result is None

    def test_virtual_read_returns_written_value(self, make_neuro_event):
        from app.neuro_bus.sandbox import SandboxContext

        ctx = SandboxContext(make_neuro_event())
        ctx.virtual_write("key1", "value1")
        result = ctx.virtual_read("key1")
        assert result == "value1"

    def test_virtual_write_records_side_effect(self, make_neuro_event):
        from app.neuro_bus.sandbox import SandboxContext, SideEffectType

        ctx = SandboxContext(make_neuro_event())
        ctx.virtual_write("k", "v")
        effects = ctx.get_side_effects()
        assert len(effects) == 1
        assert effects[0].effect_type == SideEffectType.WRITE
        assert effects[0].data == {"old": None, "new": "v"}

    def test_virtual_write_overwrite_records_old_value(self, make_neuro_event):
        from app.neuro_bus.sandbox import SandboxContext

        ctx = SandboxContext(make_neuro_event())
        ctx.virtual_write("k", "v1")
        ctx.virtual_write("k", "v2")
        effects = ctx.get_side_effects()
        assert effects[1].data == {"old": "v1", "new": "v2"}

    def test_virtual_delete_records_side_effect(self, make_neuro_event):
        from app.neuro_bus.sandbox import SandboxContext, SideEffectType

        ctx = SandboxContext(make_neuro_event())
        ctx.virtual_write("k", "v")
        ctx.virtual_delete("k")
        effects = ctx.get_side_effects()
        assert effects[1].effect_type == SideEffectType.DELETE
        assert effects[1].data == {"deleted": "v"}

    def test_virtual_delete_missing_key_no_error(self, make_neuro_event):
        from app.neuro_bus.sandbox import SandboxContext

        ctx = SandboxContext(make_neuro_event())
        ctx.virtual_delete("nonexistent")
        effects = ctx.get_side_effects()
        assert len(effects) == 1
        assert effects[0].data == {"deleted": None}

    def test_virtual_payment_records_side_effect(self, make_neuro_event):
        from app.neuro_bus.sandbox import SandboxContext, SideEffectType

        ctx = SandboxContext(make_neuro_event())
        ctx.virtual_payment(99.9, "USD")
        effects = ctx.get_side_effects()
        assert effects[0].effect_type == SideEffectType.PAYMENT
        assert effects[0].data == {"amount": 99.9, "currency": "USD"}
        assert effects[0].risk_level == 5

    def test_virtual_notify_records_side_effect(self, make_neuro_event):
        from app.neuro_bus.sandbox import SandboxContext, SideEffectType

        ctx = SandboxContext(make_neuro_event())
        ctx.virtual_notify("email", "hello")
        effects = ctx.get_side_effects()
        assert effects[0].effect_type == SideEffectType.NOTIFICATION
        assert effects[0].data["channel"] == "email"

    def test_virtual_external_call_records_side_effect(self, make_neuro_event):
        from app.neuro_bus.sandbox import SandboxContext, SideEffectType

        ctx = SandboxContext(make_neuro_event())
        ctx.virtual_external_call("svc", "/api", {"key": "val"})
        effects = ctx.get_side_effects()
        assert effects[0].effect_type == SideEffectType.EXTERNAL_CALL
        assert effects[0].target == "svc./api"

    def test_get_event_returns_deep_copy(self, make_neuro_event):
        from app.neuro_bus.sandbox import SandboxContext

        evt = make_neuro_event()
        ctx = SandboxContext(evt)
        returned = ctx.get_event()
        assert returned.event_type == evt.event_type
        # Should be a different object (deep copy)
        assert returned is not evt

    def test_get_side_effects_returns_copy(self, make_neuro_event):
        from app.neuro_bus.sandbox import SandboxContext

        ctx = SandboxContext(make_neuro_event())
        ctx.virtual_read("k")
        effects1 = ctx.get_side_effects()
        effects2 = ctx.get_side_effects()
        assert effects1 is not effects2


class TestSandboxSimulate:
    """Cover ``Sandbox.simulate``."""

    def test_no_simulator_returns_unknown_risk_report(self, make_neuro_event):
        from app.neuro_bus.sandbox import Sandbox

        sandbox = Sandbox()
        evt = make_neuro_event(event_type="unknown.event")
        report = sandbox.simulate(evt)
        assert report.can_execute is True
        assert report.risk_score == 50.0
        assert len(report.warnings) == 1

    def test_simulator_with_read_only_returns_low_risk(self, make_neuro_event):
        from app.neuro_bus.sandbox import Sandbox, SandboxContext

        def read_only_sim(ctx: SandboxContext):
            ctx.virtual_read("key1")

        sandbox = Sandbox()
        sandbox.register_simulator("read.event", read_only_sim)
        evt = make_neuro_event(event_type="read.event")
        report = sandbox.simulate(evt)
        assert report.can_execute is True
        assert report.risk_score == 20.0  # risk_level=1 → 1/5*100=20

    def test_simulator_with_payment_returns_high_risk(self, make_neuro_event):
        from app.neuro_bus.sandbox import Sandbox, SandboxContext

        def payment_sim(ctx: SandboxContext):
            ctx.virtual_payment(100.0)

        sandbox = Sandbox()
        sandbox.register_simulator("pay.event", payment_sim)
        evt = make_neuro_event(event_type="pay.event")
        report = sandbox.simulate(evt)
        assert report.can_execute is False  # risk_level=5 >= 4
        assert report.risk_score == 100.0
        assert any("Payment" in w for w in report.warnings)

    def test_simulator_with_delete_returns_warning(self, make_neuro_event):
        from app.neuro_bus.sandbox import Sandbox, SandboxContext

        def delete_sim(ctx: SandboxContext):
            ctx.virtual_delete("key1")

        sandbox = Sandbox()
        sandbox.register_simulator("del.event", delete_sim)
        evt = make_neuro_event(event_type="del.event")
        report = sandbox.simulate(evt)
        assert report.can_execute is False  # risk_level=4 >= 4
        assert any("deletion" in w.lower() for w in report.warnings)

    def test_simulator_error_returns_blocked_report(self, make_neuro_event):
        from app.neuro_bus.sandbox import Sandbox, SandboxContext

        def error_sim(ctx: SandboxContext):
            raise RuntimeError("sim crash")

        sandbox = Sandbox()
        sandbox.register_simulator("err.event", error_sim)
        evt = make_neuro_event(event_type="err.event")
        report = sandbox.simulate(evt)
        assert report.can_execute is False
        assert report.risk_score == 100.0
        assert any("Simulation failed" in w for w in report.warnings)

    def test_empty_side_effects_returns_risk_score_20(self, make_neuro_event):
        from app.neuro_bus.sandbox import Sandbox, SandboxContext

        def empty_sim(ctx: SandboxContext):
            pass

        sandbox = Sandbox()
        sandbox.register_simulator("empty.event", empty_sim)
        evt = make_neuro_event(event_type="empty.event")
        report = sandbox.simulate(evt)
        assert report.risk_score == 20.0  # max(default=1) → 1/5*100=20


class TestSandboxValidate:
    """Cover ``Sandbox.validate``."""

    def test_validate_passes_for_low_risk(self, make_neuro_event):
        from app.neuro_bus.sandbox import Sandbox, SandboxContext

        def read_sim(ctx: SandboxContext):
            ctx.virtual_read("k")

        sandbox = Sandbox()
        sandbox.register_simulator("safe.event", read_sim)
        evt = make_neuro_event(event_type="safe.event")
        assert sandbox.validate(evt, max_risk_score=70.0) is True

    def test_validate_fails_for_high_risk(self, make_neuro_event):
        from app.neuro_bus.sandbox import Sandbox, SandboxContext

        def pay_sim(ctx: SandboxContext):
            ctx.virtual_payment(999.0)

        sandbox = Sandbox()
        sandbox.register_simulator("pay.event", pay_sim)
        evt = make_neuro_event(event_type="pay.event")
        assert sandbox.validate(evt, max_risk_score=70.0) is False

    def test_validate_fails_when_cannot_execute(self, make_neuro_event):
        from app.neuro_bus.sandbox import Sandbox, SandboxContext

        def del_sim(ctx: SandboxContext):
            ctx.virtual_delete("k")

        sandbox = Sandbox()
        sandbox.register_simulator("del.event", del_sim)
        evt = make_neuro_event(event_type="del.event")
        assert sandbox.validate(evt) is False


class TestNeuroSandbox:
    """Cover ``NeuroSandbox``."""

    def test_should_prescreen_high_risk_domain(self, make_neuro_event):
        from app.neuro_bus.sandbox import NeuroSandbox

        ns = NeuroSandbox()
        evt = make_neuro_event(domain="payment")
        assert ns.should_prescreen(evt) is True

    def test_should_prescreen_delete_domain(self, make_neuro_event):
        from app.neuro_bus.sandbox import NeuroSandbox

        ns = NeuroSandbox()
        evt = make_neuro_event(domain="delete")
        assert ns.should_prescreen(evt) is True

    def test_should_prescreen_event_type_with_payment(self, make_neuro_event):
        from app.neuro_bus.sandbox import NeuroSandbox

        ns = NeuroSandbox()
        evt = make_neuro_event(event_type="order.payment.process")
        assert ns.should_prescreen(evt) is True

    def test_should_prescreen_event_type_with_delete(self, make_neuro_event):
        from app.neuro_bus.sandbox import NeuroSandbox

        ns = NeuroSandbox()
        evt = make_neuro_event(event_type="data.delete.bulk")
        assert ns.should_prescreen(evt) is True

    def test_should_prescreen_event_type_with_refund(self, make_neuro_event):
        from app.neuro_bus.sandbox import NeuroSandbox

        ns = NeuroSandbox()
        evt = make_neuro_event(event_type="order.refund.request")
        assert ns.should_prescreen(evt) is True

    def test_should_not_prescreen_safe_event(self, make_neuro_event):
        from app.neuro_bus.sandbox import NeuroSandbox

        ns = NeuroSandbox()
        evt = make_neuro_event(event_type="user.login", domain="auth")
        assert ns.should_prescreen(evt) is False

    def test_prescreen_returns_none_for_safe_event(self, make_neuro_event):
        from app.neuro_bus.sandbox import NeuroSandbox

        ns = NeuroSandbox()
        evt = make_neuro_event(event_type="safe.event", domain="global")
        assert ns.prescreen(evt) is None

    def test_prescreen_returns_report_for_risky_event(self, make_neuro_event):
        from app.neuro_bus.sandbox import NeuroSandbox, SandboxContext

        ns = NeuroSandbox()
        ns.register_simulator("pay.process", lambda ctx: ctx.virtual_payment(50.0))
        evt = make_neuro_event(event_type="pay.process", domain="payment")
        report = ns.prescreen(evt)
        assert report is not None
        assert report.can_execute is False

    def test_validate_safe_event_returns_true(self, make_neuro_event):
        from app.neuro_bus.sandbox import NeuroSandbox

        ns = NeuroSandbox()
        evt = make_neuro_event(event_type="safe.event", domain="global")
        assert ns.validate(evt) is True

    def test_validate_risky_event_returns_false(self, make_neuro_event):
        from app.neuro_bus.sandbox import NeuroSandbox, SandboxContext

        ns = NeuroSandbox()
        ns.register_simulator("pay.process", lambda ctx: ctx.virtual_payment(50.0))
        evt = make_neuro_event(event_type="pay.process", domain="payment")
        assert ns.validate(evt) is False


# ===========================================================================
# 5. app/services/kitten_report/chart_data_service.py
# ===========================================================================


class TestChartDataServiceRevenueChart:
    """Cover ``ChartDataService.get_revenue_chart_data``."""

    def test_revenue_chart_db_error_returns_failure(self):
        from app.services.kitten_report.chart_data_service import ChartDataService

        svc = ChartDataService()
        with patch(
            "app.db.session.get_db",
            side_effect=RuntimeError("no db"),
        ):
            result = svc.get_revenue_chart_data()
        assert result["success"] is False
        assert "no db" in result["message"]

    def test_revenue_chart_success(self):
        from app.services.kitten_report.chart_data_service import ChartDataService

        svc = ChartDataService()
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.__getitem__ = Mock(side_effect=lambda i: (0, 0))
        mock_db.query.return_value.filter.return_value.first.return_value = (0, 0)
        mock_db.__enter__ = Mock(return_value=mock_db)
        mock_db.__exit__ = Mock(return_value=False)

        with patch("app.db.session.get_db", return_value=mock_db):
            result = svc.get_revenue_chart_data(months=1)
        assert result["success"] is True
        assert result["type"] == "line"
        assert "data" in result

    def test_revenue_chart_custom_months(self):
        from app.services.kitten_report.chart_data_service import ChartDataService

        svc = ChartDataService()
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = (0, 0)
        mock_db.__enter__ = Mock(return_value=mock_db)
        mock_db.__exit__ = Mock(return_value=False)

        with patch("app.db.session.get_db", return_value=mock_db):
            result = svc.get_revenue_chart_data(months=3)
        assert result["success"] is True
        assert len(result["data"]["labels"]) == 3


class TestChartDataServiceProductPieChart:
    """Cover ``ChartDataService.get_product_pie_chart_data``."""

    def test_product_pie_chart_db_error_returns_failure(self):
        from app.services.kitten_report.chart_data_service import ChartDataService

        svc = ChartDataService()
        with patch(
            "app.db.session.get_db",
            side_effect=RuntimeError("db down"),
        ):
            result = svc.get_product_pie_chart_data()
        assert result["success"] is False

    def test_product_pie_chart_success(self):
        from app.services.kitten_report.chart_data_service import ChartDataService

        svc = ChartDataService()
        mock_db = MagicMock()
        row = MagicMock()
        row.product_name = "Widget"
        row.total = 100.0
        mock_db.query.return_value.filter.return_value.group_by.return_value.order_by.return_value.limit.return_value.all.return_value = [row]
        mock_db.__enter__ = Mock(return_value=mock_db)
        mock_db.__exit__ = Mock(return_value=False)

        with patch("app.db.session.get_db", return_value=mock_db):
            result = svc.get_product_pie_chart_data()
        assert result["success"] is True
        assert result["type"] == "pie"
        assert result["data"]["labels"] == ["Widget"]


class TestChartDataServiceCustomerBarChart:
    """Cover ``ChartDataService.get_customer_bar_chart_data``."""

    def test_customer_bar_chart_db_error_returns_failure(self):
        from app.services.kitten_report.chart_data_service import ChartDataService

        svc = ChartDataService()
        with patch(
            "app.db.session.get_db",
            side_effect=OSError("conn refused"),
        ):
            result = svc.get_customer_bar_chart_data()
        assert result["success"] is False

    def test_customer_bar_chart_long_name_truncated(self):
        from app.services.kitten_report.chart_data_service import ChartDataService

        svc = ChartDataService()
        mock_db = MagicMock()
        row = MagicMock()
        row.purchase_unit = "A" * 15  # longer than 10 chars
        row.total = 500.0
        row.count = 3
        mock_db.query.return_value.filter.return_value.group_by.return_value.order_by.return_value.limit.return_value.all.return_value = [row]
        mock_db.__enter__ = Mock(return_value=mock_db)
        mock_db.__exit__ = Mock(return_value=False)

        with patch("app.db.session.get_db", return_value=mock_db):
            result = svc.get_customer_bar_chart_data()
        assert result["success"] is True
        assert result["data"]["labels"][0].endswith("...")

    def test_customer_bar_chart_short_name_not_truncated(self):
        from app.services.kitten_report.chart_data_service import ChartDataService

        svc = ChartDataService()
        mock_db = MagicMock()
        row = MagicMock()
        row.purchase_unit = "Short"
        row.total = 200.0
        row.count = 1
        mock_db.query.return_value.filter.return_value.group_by.return_value.order_by.return_value.limit.return_value.all.return_value = [row]
        mock_db.__enter__ = Mock(return_value=mock_db)
        mock_db.__exit__ = Mock(return_value=False)

        with patch("app.db.session.get_db", return_value=mock_db):
            result = svc.get_customer_bar_chart_data()
        assert result["success"] is True
        assert "..." not in result["data"]["labels"][0]


class TestChartDataServiceProfitTrendChart:
    """Cover ``ChartDataService.get_profit_trend_chart_data``."""

    def test_profit_trend_db_error_returns_failure(self):
        from app.services.kitten_report.chart_data_service import ChartDataService

        svc = ChartDataService()
        with patch(
            "app.db.session.get_db",
            side_effect=ValueError("bad config"),
        ):
            result = svc.get_profit_trend_chart_data()
        assert result["success"] is False

    def test_profit_trend_success(self):
        from app.services.kitten_report.chart_data_service import ChartDataService

        svc = ChartDataService()
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.scalar.return_value = 1000.0
        mock_db.__enter__ = Mock(return_value=mock_db)
        mock_db.__exit__ = Mock(return_value=False)

        with patch("app.db.session.get_db", return_value=mock_db):
            result = svc.get_profit_trend_chart_data(months=1)
        assert result["success"] is True
        assert result["type"] == "mixed"
        assert result["data"]["revenue"][0] == 1000.0
        assert result["data"]["estimated_cost"][0] == 300.0  # 30%
        assert result["data"]["profit"][0] == 700.0


class TestChartDataServiceInventoryChart:
    """Cover ``ChartDataService.get_inventory_chart_data``."""

    def test_inventory_chart_db_error_returns_failure(self):
        from app.services.kitten_report.chart_data_service import ChartDataService

        svc = ChartDataService()
        with patch(
            "app.db.session.get_db",
            side_effect=RuntimeError("no db"),
        ):
            result = svc.get_inventory_chart_data()
        assert result["success"] is False

    def test_inventory_chart_programming_error_table_missing(self):
        """ProgrammingError is NOT in RECOVERABLE_ERRORS, so it propagates.

        The source has a defensive check for ProgrammingError with "does not exist"
        but it's unreachable because ProgrammingError isn't caught by RECOVERABLE_ERRORS.
        We verify the exception propagates instead.
        """
        from app.services.kitten_report.chart_data_service import ChartDataService
        from sqlalchemy.exc import ProgrammingError

        svc = ChartDataService()
        err = ProgrammingError("SELECT 1", {}, Exception("table does not exist"))
        with patch(
            "app.db.session.get_db",
            side_effect=err,
        ):
            # ProgrammingError is not in RECOVERABLE_ERRORS, so it propagates
            with pytest.raises(ProgrammingError):
                svc.get_inventory_chart_data()

    def test_inventory_chart_success(self):
        from app.services.kitten_report.chart_data_service import ChartDataService

        svc = ChartDataService()
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.group_by.return_value.all.return_value = [
            ("化工", 5000.0),
            ("金属", 3000.0),
        ]
        mock_db.__enter__ = Mock(return_value=mock_db)
        mock_db.__exit__ = Mock(return_value=False)

        with patch("app.db.session.get_db", return_value=mock_db):
            result = svc.get_inventory_chart_data()
        assert result["success"] is True
        assert result["type"] == "doughnut"
        assert len(result["data"]["labels"]) == 2


class TestChartDataServiceGetAllChartsData:
    """Cover ``ChartDataService.get_all_charts_data``."""

    def test_get_all_charts_data_returns_all_keys(self):
        from app.services.kitten_report.chart_data_service import ChartDataService

        svc = ChartDataService()
        with patch.object(svc, "get_revenue_chart_data", return_value={"success": True}), \
             patch.object(svc, "get_product_pie_chart_data", return_value={"success": True}), \
             patch.object(svc, "get_customer_bar_chart_data", return_value={"success": True}), \
             patch.object(svc, "get_profit_trend_chart_data", return_value={"success": True}), \
             patch.object(svc, "get_inventory_chart_data", return_value={"success": True}):
            result = svc.get_all_charts_data()
        assert "revenue_trend" in result
        assert "product_distribution" in result
        assert "customer_ranking" in result
        assert "profit_analysis" in result
        assert "inventory_breakdown" in result


# ===========================================================================
# 6. app/services/operations_line_bridge.py
# ===========================================================================


class TestDefaultSteps:
    """Cover ``_default_steps``."""

    def test_default_steps_has_all_o_keys(self):
        from app.services.operations_line_bridge import _default_steps

        steps = _default_steps()
        for key in ["O1", "O2", "O3", "O4", "O5", "O6", "O7", "O8", "O9", "O10"]:
            assert key in steps

    def test_default_steps_o1_is_done(self):
        from app.services.operations_line_bridge import _default_steps

        steps = _default_steps()
        assert steps["O1"]["status"] == "done"

    def test_default_steps_o5_o6_are_done(self):
        from app.services.operations_line_bridge import _default_steps

        steps = _default_steps()
        assert steps["O5"]["status"] == "done"
        assert steps["O6"]["status"] == "done"


class TestScanPipelines:
    """Cover ``_scan_pipelines``."""

    def test_scan_pipelines_import_error_returns_zeros(self, monkeypatch):
        from app.services.operations_line_bridge import _scan_pipelines

        monkeypatch.setitem(
            __import__("sys").modules,
            "app.services.user_cs_pipeline",
            None,
        )
        # Force re-import by clearing cached module
        import importlib

        with patch.dict("sys.modules", {"app.services.user_cs_pipeline": None}):
            total, missing_crm, missing_erp, by_stage = _scan_pipelines()
        assert total == 0
        assert missing_crm == 0
        assert missing_erp == 0
        assert by_stage == {}

    def test_scan_pipelines_with_pipeline_data(self, tmp_dir, monkeypatch):
        from app.services.operations_line_bridge import _scan_pipelines

        # Create a pipeline JSON file
        pipeline_dir = Path(tmp_dir) / "pipelines"
        pipeline_dir.mkdir()
        pipeline_data = {
            "stage": "intake_done",
            "crm_opportunity_id": "",
            "erp_customer_id": "",
        }
        (pipeline_dir / "1.json").write_text(json.dumps(pipeline_data), encoding="utf-8")

        mock_pipeline_roots = MagicMock(return_value=[pipeline_dir])
        mock_stage_order = ["idle", "connected", "intake", "intake_done", "quoted"]

        mock_module = MagicMock()
        mock_module._pipeline_roots = mock_pipeline_roots
        mock_module._STAGE_ORDER = mock_stage_order

        with patch.dict("sys.modules", {"app.services.user_cs_pipeline": mock_module}):
            total, missing_crm, missing_erp, by_stage = _scan_pipelines()
        assert total == 1
        assert missing_crm == 1
        assert missing_erp == 1
        assert by_stage.get("intake_done") == 1

    def test_scan_pipelines_skips_invalid_json(self, tmp_dir):
        from app.services.operations_line_bridge import _scan_pipelines

        pipeline_dir = Path(tmp_dir) / "pipelines"
        pipeline_dir.mkdir()
        (pipeline_dir / "bad.json").write_text("not json{{", encoding="utf-8")

        mock_module = MagicMock()
        mock_module._pipeline_roots = MagicMock(return_value=[pipeline_dir])
        mock_module._STAGE_ORDER = ["idle"]

        with patch.dict("sys.modules", {"app.services.user_cs_pipeline": mock_module}):
            total, missing_crm, missing_erp, by_stage = _scan_pipelines()
        assert total == 0

    def test_scan_pipelines_skips_non_dict_data(self, tmp_dir):
        from app.services.operations_line_bridge import _scan_pipelines

        pipeline_dir = Path(tmp_dir) / "pipelines"
        pipeline_dir.mkdir()
        (pipeline_dir / "arr.json").write_text("[1,2,3]", encoding="utf-8")

        mock_module = MagicMock()
        mock_module._pipeline_roots = MagicMock(return_value=[pipeline_dir])
        mock_module._STAGE_ORDER = ["idle"]

        with patch.dict("sys.modules", {"app.services.user_cs_pipeline": mock_module}):
            total, _, _, _ = _scan_pipelines()
        assert total == 0

    def test_scan_pipelines_skips_non_dir_roots(self, tmp_dir):
        from app.services.operations_line_bridge import _scan_pipelines

        mock_module = MagicMock()
        mock_module._pipeline_roots = MagicMock(return_value=[Path("/nonexistent/path")])
        mock_module._STAGE_ORDER = ["idle"]

        with patch.dict("sys.modules", {"app.services.user_cs_pipeline": mock_module}):
            total, _, _, _ = _scan_pipelines()
        assert total == 0


class TestComputeOperationsHealth:
    """Cover ``compute_operations_health``."""

    def test_returns_dict_with_required_keys(self, monkeypatch):
        from app.services.operations_line_bridge import compute_operations_health

        monkeypatch.delenv("XCAGI_MARKET_BASE_URL", raising=False)
        monkeypatch.delenv("MODEL_PAYMENT_BACKEND", raising=False)
        monkeypatch.delenv("PAYMENT_BACKEND", raising=False)

        with patch(
            "app.services.operations_line_bridge._scan_pipelines",
            return_value=(0, 0, 0, {}),
        ):
            result = compute_operations_health()
        assert "generated_at" in result
        assert "steps" in result
        assert "pipeline_count" in result

    def test_o2_status_when_no_pipelines(self, monkeypatch):
        from app.services.operations_line_bridge import compute_operations_health

        monkeypatch.delenv("XCAGI_MARKET_BASE_URL", raising=False)
        monkeypatch.delenv("MODEL_PAYMENT_BACKEND", raising=False)
        monkeypatch.delenv("PAYMENT_BACKEND", raising=False)

        with patch(
            "app.services.operations_line_bridge._scan_pipelines",
            return_value=(0, 0, 0, {}),
        ):
            result = compute_operations_health()
        # When total=0, o2_partial=False, _status(True, True) = "done"
        assert result["steps"]["O2"]["status"] == "done"

    def test_o2_status_when_pipelines_complete(self, monkeypatch):
        from app.services.operations_line_bridge import compute_operations_health

        monkeypatch.delenv("XCAGI_MARKET_BASE_URL", raising=False)
        monkeypatch.delenv("MODEL_PAYMENT_BACKEND", raising=False)
        monkeypatch.delenv("PAYMENT_BACKEND", raising=False)

        with patch(
            "app.services.operations_line_bridge._scan_pipelines",
            return_value=(5, 0, 0, {"quoted": 3, "signed": 2}),
        ):
            result = compute_operations_health()
        assert result["steps"]["O2"]["status"] == "done"
        assert result["steps"]["O3"]["quoted"] == 3

    def test_o4_with_market_payment_health(self, monkeypatch):
        from app.services.operations_line_bridge import compute_operations_health

        monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "http://market:8765")
        monkeypatch.delenv("MODEL_PAYMENT_BACKEND", raising=False)
        monkeypatch.delenv("PAYMENT_BACKEND", raising=False)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"java_service_healthy": True, "payment_backend": "java"}

        with patch(
            "app.services.operations_line_bridge._scan_pipelines",
            return_value=(0, 0, 0, {}),
        ), patch(
            "httpx.get",
            return_value=mock_resp,
        ):
            result = compute_operations_health()
        assert result["steps"]["O4"]["status"] == "done"

    def test_o4_market_health_probe_failure(self, monkeypatch):
        from app.services.operations_line_bridge import compute_operations_health

        monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "http://market:8765")
        monkeypatch.delenv("MODEL_PAYMENT_BACKEND", raising=False)
        monkeypatch.delenv("PAYMENT_BACKEND", raising=False)

        with patch(
            "app.services.operations_line_bridge._scan_pipelines",
            return_value=(0, 0, 0, {}),
        ), patch(
            "httpx.get",
            side_effect=OSError("conn refused"),
        ):
            result = compute_operations_health()
        assert result["steps"]["O4"]["status"] == "partial"

    def test_o4_market_health_http_error(self, monkeypatch):
        from app.services.operations_line_bridge import compute_operations_health

        monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "http://market:8765")
        monkeypatch.delenv("MODEL_PAYMENT_BACKEND", raising=False)
        monkeypatch.delenv("PAYMENT_BACKEND", raising=False)

        mock_resp = MagicMock()
        mock_resp.status_code = 500

        with patch(
            "app.services.operations_line_bridge._scan_pipelines",
            return_value=(0, 0, 0, {}),
        ), patch(
            "httpx.get",
            return_value=mock_resp,
        ):
            result = compute_operations_health()
        assert result["steps"]["O4"]["status"] == "partial"

    def test_o8_signoff_backend_info(self, monkeypatch):
        from app.services.operations_line_bridge import compute_operations_health

        monkeypatch.delenv("XCAGI_MARKET_BASE_URL", raising=False)
        monkeypatch.delenv("MODEL_PAYMENT_BACKEND", raising=False)
        monkeypatch.delenv("PAYMENT_BACKEND", raising=False)

        mock_signoff = MagicMock(
            return_value={"backend": "postgres", "note": "PG签收存储"}
        )
        mock_module = MagicMock()
        mock_module.signoff_backend_info = mock_signoff

        with patch(
            "app.services.operations_line_bridge._scan_pipelines",
            return_value=(0, 0, 0, {}),
        ), patch.dict(
            "sys.modules",
            {"app.services.user_cs_delivery_signoff": mock_module},
        ):
            result = compute_operations_health()
        assert result["steps"]["O8"]["status"] == "done"

    def test_o8_signoff_sqlite_backend(self, monkeypatch):
        from app.services.operations_line_bridge import compute_operations_health

        monkeypatch.delenv("XCAGI_MARKET_BASE_URL", raising=False)
        monkeypatch.delenv("MODEL_PAYMENT_BACKEND", raising=False)
        monkeypatch.delenv("PAYMENT_BACKEND", raising=False)

        mock_signoff = MagicMock(
            return_value={"backend": "sqlite", "note": "本地签收"}
        )
        mock_module = MagicMock()
        mock_module.signoff_backend_info = mock_signoff

        with patch(
            "app.services.operations_line_bridge._scan_pipelines",
            return_value=(0, 0, 0, {}),
        ), patch.dict(
            "sys.modules",
            {"app.services.user_cs_delivery_signoff": mock_module},
        ):
            result = compute_operations_health()
        assert result["steps"]["O8"]["status"] == "partial"

    def test_o10_reconciliation_status(self, monkeypatch):
        from app.services.operations_line_bridge import compute_operations_health

        monkeypatch.delenv("XCAGI_MARKET_BASE_URL", raising=False)
        monkeypatch.delenv("MODEL_PAYMENT_BACKEND", raising=False)
        monkeypatch.delenv("PAYMENT_BACKEND", raising=False)

        mock_rec = MagicMock(
            return_value={
                "last_run": {"success": True, "time": "2026-01-01"},
                "auto_confirm_enabled": False,
            }
        )
        mock_module = MagicMock()
        mock_module.get_reconciliation_status = mock_rec

        with patch(
            "app.services.operations_line_bridge._scan_pipelines",
            return_value=(0, 0, 0, {}),
        ), patch.dict(
            "sys.modules",
            {"app.services.reconciliation_scheduler": mock_module},
        ):
            result = compute_operations_health()
        assert result["steps"]["O10"]["status"] == "partial"
        assert "最近对账" in result["steps"]["O10"]["note"]

    def test_o10_reconciliation_no_last_run(self, monkeypatch):
        from app.services.operations_line_bridge import compute_operations_health

        monkeypatch.delenv("XCAGI_MARKET_BASE_URL", raising=False)
        monkeypatch.delenv("MODEL_PAYMENT_BACKEND", raising=False)
        monkeypatch.delenv("PAYMENT_BACKEND", raising=False)

        mock_rec = MagicMock(
            return_value={"last_run": None, "auto_confirm_enabled": False}
        )
        mock_module = MagicMock()
        mock_module.get_reconciliation_status = mock_rec

        with patch(
            "app.services.operations_line_bridge._scan_pipelines",
            return_value=(0, 0, 0, {}),
        ), patch.dict(
            "sys.modules",
            {"app.services.reconciliation_scheduler": mock_module},
        ):
            result = compute_operations_health()
        # O10 should stay at default partial
        assert result["steps"]["O10"]["status"] == "partial"

    def test_payment_backend_env_var(self, monkeypatch):
        from app.services.operations_line_bridge import compute_operations_health

        monkeypatch.delenv("XCAGI_MARKET_BASE_URL", raising=False)
        monkeypatch.setenv("MODEL_PAYMENT_BACKEND", "java")
        monkeypatch.delenv("PAYMENT_BACKEND", raising=False)

        with patch(
            "app.services.operations_line_bridge._scan_pipelines",
            return_value=(0, 0, 0, {}),
        ):
            result = compute_operations_health()
        assert result["payment_backend"] == "java"

    def test_pipeline_count_and_breakpoints(self, monkeypatch):
        from app.services.operations_line_bridge import compute_operations_health

        monkeypatch.delenv("XCAGI_MARKET_BASE_URL", raising=False)
        monkeypatch.delenv("MODEL_PAYMENT_BACKEND", raising=False)
        monkeypatch.delenv("PAYMENT_BACKEND", raising=False)

        with patch(
            "app.services.operations_line_bridge._scan_pipelines",
            return_value=(10, 3, 2, {}),
        ):
            result = compute_operations_health()
        assert result["pipeline_count"] == 10
        assert result["missing_crm"] == 3
        assert result["missing_erp"] == 2
        assert result["breakpoint_count"] == 5
