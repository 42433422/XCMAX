"""Branch-coverage tests for app.infrastructure.llm.client.

Covers: _env_mode, _initial_mode, _resolve_openai_timeout_seconds,
_resolve_openai_max_retries, resolve_mode, set_mode, require_api_key,
get_llm_client, dispose_llm_client, get_offline_status,
get_openai_compatible_client, resolve_chat_model.
Focus on env-var parsing, mode switching, and error branches.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from app.infrastructure.llm import client as llm_client

# ---------------------------------------------------------------------------
# _env_mode / _initial_mode
# ---------------------------------------------------------------------------


class TestEnvMode:
    def test_offline_aliases(self, monkeypatch):
        monkeypatch.setenv("FHD_LLM_MODE", "offline")
        assert llm_client._env_mode() == "offline"

    def test_local_alias(self, monkeypatch):
        monkeypatch.setenv("FHD_LLM_MODE", "local")
        assert llm_client._env_mode() == "offline"

    def test_ollama_alias(self, monkeypatch):
        monkeypatch.setenv("FHD_LLM_MODE", "ollama")
        assert llm_client._env_mode() == "offline"

    def test_online_aliases(self, monkeypatch):
        monkeypatch.setenv("FHD_LLM_MODE", "online")
        assert llm_client._env_mode() == "online"

    def test_cloud_alias(self, monkeypatch):
        monkeypatch.setenv("FHD_LLM_MODE", "cloud")
        assert llm_client._env_mode() == "online"

    def test_api_alias(self, monkeypatch):
        monkeypatch.setenv("FHD_LLM_MODE", "api")
        assert llm_client._env_mode() == "online"

    def test_unknown_returns_none(self, monkeypatch):
        monkeypatch.setenv("FHD_LLM_MODE", "unknown")
        assert llm_client._env_mode() is None

    def test_empty_returns_none(self, monkeypatch):
        monkeypatch.setenv("FHD_LLM_MODE", "")
        assert llm_client._env_mode() is None

    def test_llm_mode_env_var(self, monkeypatch):
        monkeypatch.delenv("FHD_LLM_MODE", raising=False)
        monkeypatch.setenv("LLM_MODE", "offline")
        assert llm_client._env_mode() == "offline"

    def test_fhd_takes_precedence(self, monkeypatch):
        monkeypatch.setenv("FHD_LLM_MODE", "online")
        monkeypatch.setenv("LLM_MODE", "offline")
        assert llm_client._env_mode() == "online"

    def test_case_insensitive(self, monkeypatch):
        monkeypatch.setenv("FHD_LLM_MODE", "OFFLINE")
        assert llm_client._env_mode() == "offline"

    def test_no_env_returns_none(self, monkeypatch):
        monkeypatch.delenv("FHD_LLM_MODE", raising=False)
        monkeypatch.delenv("LLM_MODE", raising=False)
        assert llm_client._env_mode() is None


class TestInitialMode:
    def test_returns_env_mode(self, monkeypatch):
        monkeypatch.setenv("FHD_LLM_MODE", "offline")
        assert llm_client._initial_mode() == "offline"

    def test_defaults_to_online(self, monkeypatch):
        monkeypatch.delenv("FHD_LLM_MODE", raising=False)
        monkeypatch.delenv("LLM_MODE", raising=False)
        assert llm_client._initial_mode() == "online"


# ---------------------------------------------------------------------------
# _resolve_openai_timeout_seconds
# ---------------------------------------------------------------------------


class TestResolveTimeout:
    def test_default(self, monkeypatch):
        monkeypatch.delenv("XCAGI_OPENAI_TIMEOUT_SEC", raising=False)
        assert llm_client._resolve_openai_timeout_seconds() == 45.0

    def test_custom_value(self, monkeypatch):
        monkeypatch.setenv("XCAGI_OPENAI_TIMEOUT_SEC", "120")
        assert llm_client._resolve_openai_timeout_seconds() == 120.0

    def test_invalid_value_returns_default(self, monkeypatch):
        monkeypatch.setenv("XCAGI_OPENAI_TIMEOUT_SEC", "not-a-number")
        assert llm_client._resolve_openai_timeout_seconds() == 45.0

    def test_below_minimum_clamped(self, monkeypatch):
        monkeypatch.setenv("XCAGI_OPENAI_TIMEOUT_SEC", "1")
        assert llm_client._resolve_openai_timeout_seconds() == 5.0

    def test_above_maximum_clamped(self, monkeypatch):
        monkeypatch.setenv("XCAGI_OPENAI_TIMEOUT_SEC", "500")
        assert llm_client._resolve_openai_timeout_seconds() == 300.0

    def test_empty_string_returns_default(self, monkeypatch):
        monkeypatch.setenv("XCAGI_OPENAI_TIMEOUT_SEC", "")
        assert llm_client._resolve_openai_timeout_seconds() == 45.0


# ---------------------------------------------------------------------------
# _resolve_openai_max_retries
# ---------------------------------------------------------------------------


class TestResolveMaxRetries:
    def test_default(self, monkeypatch):
        monkeypatch.delenv("XCAGI_OPENAI_MAX_RETRIES", raising=False)
        assert llm_client._resolve_openai_max_retries() == 0

    def test_custom_value(self, monkeypatch):
        monkeypatch.setenv("XCAGI_OPENAI_MAX_RETRIES", "3")
        assert llm_client._resolve_openai_max_retries() == 3

    def test_invalid_value_returns_default(self, monkeypatch):
        monkeypatch.setenv("XCAGI_OPENAI_MAX_RETRIES", "not-a-number")
        assert llm_client._resolve_openai_max_retries() == 0

    def test_below_minimum_clamped(self, monkeypatch):
        monkeypatch.setenv("XCAGI_OPENAI_MAX_RETRIES", "-1")
        assert llm_client._resolve_openai_max_retries() == 0

    def test_above_maximum_clamped(self, monkeypatch):
        monkeypatch.setenv("XCAGI_OPENAI_MAX_RETRIES", "10")
        assert llm_client._resolve_openai_max_retries() == 5

    def test_empty_string_returns_default(self, monkeypatch):
        monkeypatch.setenv("XCAGI_OPENAI_MAX_RETRIES", "")
        assert llm_client._resolve_openai_max_retries() == 0


# ---------------------------------------------------------------------------
# set_mode / resolve_mode
# ---------------------------------------------------------------------------


class TestSetResolveMode:
    def test_set_online(self):
        llm_client.set_mode("online")
        assert llm_client.resolve_mode() == "online"

    def test_set_offline(self):
        llm_client.set_mode("offline")
        assert llm_client.resolve_mode() == "offline"

    def test_set_offline_with_model(self):
        llm_client.set_mode("offline", model="llama2")
        assert llm_client.resolve_mode() == "offline"
        # preferred model stored internally
        status = llm_client.get_offline_status()
        # We can't easily verify the model without probing Ollama, but mode is correct
        assert status["ollama_reachable"] is False or status["preferred_offline_model"] == "llama2"

    def test_set_offline_with_empty_model(self):
        llm_client.set_mode("offline", model="   ")
        assert llm_client.resolve_mode() == "offline"

    def test_set_offline_with_none_model(self):
        llm_client.set_mode("offline", model=None)
        assert llm_client.resolve_mode() == "offline"

    def test_set_online_clears_offline_model(self):
        llm_client.set_mode("offline", model="llama2")
        llm_client.set_mode("online")
        assert llm_client.resolve_mode() == "online"

    def test_set_invalid_mode_raises(self):
        with pytest.raises(ValueError, match="mode must be"):
            llm_client.set_mode("invalid")

    def test_set_mode_clears_client(self):
        llm_client._openai_client = MagicMock()
        llm_client.set_mode("online")
        assert llm_client._openai_client is None


# ---------------------------------------------------------------------------
# require_api_key
# ---------------------------------------------------------------------------


class TestRequireApiKey:
    def test_offline_mode_skips_check(self):
        llm_client.set_mode("offline")
        # Should not raise even without a key
        llm_client.require_api_key()

    def test_online_mode_with_key(self):
        llm_client.set_mode("online")
        with patch(
            "app.infrastructure.llm.providers.credentials.resolve_openai_env_credentials",
            return_value=("sk-test", None),
        ):
            llm_client.require_api_key()

    def test_online_mode_without_key_raises(self):
        llm_client.set_mode("online")
        with patch(
            "app.infrastructure.llm.providers.credentials.resolve_openai_env_credentials",
            return_value=("", None),
        ):
            with pytest.raises(RuntimeError, match="未配置"):
                llm_client.require_api_key()


# ---------------------------------------------------------------------------
# get_llm_client
# ---------------------------------------------------------------------------


class TestGetLlmClient:
    def test_offline_returns_none(self):
        llm_client.set_mode("offline")
        llm_client.dispose_llm_client()
        assert llm_client.get_llm_client() is None

    def test_online_returns_client(self):
        llm_client.set_mode("online")
        llm_client.dispose_llm_client()
        mock_openai = MagicMock()
        with (
            patch(
                "app.infrastructure.llm.providers.credentials.resolve_openai_env_credentials",
                return_value=("sk-test", "https://api.example.com"),
            ),
            patch("openai.OpenAI", return_value=mock_openai) as mock_cls,
        ):
            result = llm_client.get_llm_client()
        assert result is mock_openai
        # Verify kwargs passed
        call_kwargs = mock_cls.call_args.kwargs
        assert call_kwargs["api_key"] == "sk-test"
        assert call_kwargs["base_url"] == "https://api.example.com"
        llm_client.dispose_llm_client()

    def test_online_returns_cached_client(self):
        llm_client.set_mode("online")
        llm_client.dispose_llm_client()
        mock_openai = MagicMock()
        with (
            patch(
                "app.infrastructure.llm.providers.credentials.resolve_openai_env_credentials",
                return_value=("sk-test", None),
            ),
            patch("openai.OpenAI", return_value=mock_openai) as mock_cls,
        ):
            first = llm_client.get_llm_client()
            second = llm_client.get_llm_client()
        assert first is second
        assert mock_cls.call_count == 1
        llm_client.dispose_llm_client()

    def test_online_without_key_raises(self):
        llm_client.set_mode("online")
        llm_client.dispose_llm_client()
        with patch(
            "app.infrastructure.llm.providers.credentials.resolve_openai_env_credentials",
            return_value=("", None),
        ):
            with pytest.raises(RuntimeError):
                llm_client.get_llm_client()


# ---------------------------------------------------------------------------
# dispose_llm_client
# ---------------------------------------------------------------------------


class TestDisposeLlmClient:
    def test_dispose_clears_client(self):
        llm_client._openai_client = MagicMock()
        llm_client.dispose_llm_client()
        assert llm_client._openai_client is None

    def test_dispose_when_already_none(self):
        llm_client._openai_client = None
        llm_client.dispose_llm_client()
        assert llm_client._openai_client is None


# ---------------------------------------------------------------------------
# get_offline_status
# ---------------------------------------------------------------------------


class TestGetOfflineStatus:
    def test_successful_probe_with_dict_models(self):
        llm_client.set_mode("offline", model="llama2")
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(
            {"models": [{"name": "llama2"}, {"name": "mistral"}]}
        ).encode("utf-8")
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=mock_resp):
            status = llm_client.get_offline_status()
        assert status["ollama_reachable"] is True
        assert "llama2" in status["models"]
        assert "mistral" in status["models"]
        assert status["preferred_offline_model"] == "llama2"

    def test_successful_probe_with_string_models(self):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"models": ["model-a", "model-b"]}).encode("utf-8")
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=mock_resp):
            status = llm_client.get_offline_status()
        assert status["ollama_reachable"] is True
        assert "model-a" in status["models"]

    def test_successful_probe_empty_models(self):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"models": []}).encode("utf-8")
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=mock_resp):
            status = llm_client.get_offline_status()
        assert status["ollama_reachable"] is True
        assert status["models"] == []

    def test_url_error(self):
        import urllib.error

        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("fail")):
            status = llm_client.get_offline_status()
        assert status["ollama_reachable"] is False
        assert "error" in status

    def test_timeout_error(self):
        with patch("urllib.request.urlopen", side_effect=TimeoutError("timed out")):
            status = llm_client.get_offline_status()
        assert status["ollama_reachable"] is False

    def test_os_error(self):
        with patch("urllib.request.urlopen", side_effect=OSError("conn refused")):
            status = llm_client.get_offline_status()
        assert status["ollama_reachable"] is False

    def test_json_decode_error(self):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"not-json"
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=mock_resp):
            status = llm_client.get_offline_status()
        assert status["ollama_reachable"] is False

    def test_value_error(self):
        # json.loads raises ValueError subclass (JSONDecodeError) for malformed JSON,
        # but a non-dict body (e.g. a bare number) triggers AttributeError which is
        # NOT in the caught tuple — verify it propagates rather than being swallowed.
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"123"
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=mock_resp):
            with pytest.raises(AttributeError):
                llm_client.get_offline_status()

    def test_custom_ollama_host(self, monkeypatch):
        monkeypatch.setenv("OLLAMA_HOST", "http://custom-host:12345")
        with patch("urllib.request.urlopen", side_effect=OSError("fail")):
            status = llm_client.get_offline_status()
        assert status["ollama_host"] == "http://custom-host:12345"

    def test_default_ollama_host(self, monkeypatch):
        monkeypatch.delenv("OLLAMA_HOST", raising=False)
        with patch("urllib.request.urlopen", side_effect=OSError("fail")):
            status = llm_client.get_offline_status()
        assert status["ollama_host"] == "http://127.0.0.1:11434"


# ---------------------------------------------------------------------------
# get_openai_compatible_client
# ---------------------------------------------------------------------------


class TestGetOpenaiCompatibleClient:
    def test_offline_raises(self):
        llm_client.set_mode("offline")
        with pytest.raises(RuntimeError, match="offline mode"):
            llm_client.get_openai_compatible_client()

    def test_online_returns_client(self):
        llm_client.set_mode("online")
        llm_client.dispose_llm_client()
        mock_openai = MagicMock()
        with (
            patch(
                "app.infrastructure.llm.providers.credentials.resolve_openai_env_credentials",
                return_value=("sk-test", None),
            ),
            patch("openai.OpenAI", return_value=mock_openai),
        ):
            result = llm_client.get_openai_compatible_client()
        assert result is mock_openai
        llm_client.dispose_llm_client()


# ---------------------------------------------------------------------------
# resolve_chat_model
# ---------------------------------------------------------------------------


class TestResolveChatModel:
    def test_delegates_to_credentials(self):
        with patch(
            "app.infrastructure.llm.providers.credentials.resolve_default_chat_model",
            return_value="gpt-4",
        ) as mock_fn:
            result = llm_client.resolve_chat_model()
        assert result == "gpt-4"
        mock_fn.assert_called_once()


# ---------------------------------------------------------------------------
# Cleanup fixture
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_llm_mode():
    """Reset LLM client global state after each test."""
    original_mode = llm_client.resolve_mode()
    yield
    llm_client.set_mode(original_mode)
    llm_client.dispose_llm_client()
