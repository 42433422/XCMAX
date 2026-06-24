"""Real-behavior tests for app.infrastructure.llm.client (cov90b, 2nd wave).

Targets the uncovered branches in the LLM client facade:
* env/initial mode resolution (online branch + fallback)
* timeout/max-retries env parsing incl. ValueError fallbacks
* set_mode validation
* require_api_key offline-return vs missing-key raise
* get_llm_client online singleton construction (OpenAI mocked)
* dispose_llm_client
* get_offline_status success parsing (urlopen mocked) + error branch
* get_openai_compatible_client both branches
* resolve_chat_model delegation

All external deps (openai SDK, urllib network, credentials provider) are
mocked. Module-level global state is saved/restored so tests stay isolated.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from app.infrastructure.llm import client as llm_client


@pytest.fixture(autouse=True)
def _restore_client_state() -> Iterator[None]:
    """Snapshot and restore mutable module globals around each test."""
    saved_mode = llm_client._mode
    saved_offline_model = llm_client._offline_model
    saved_openai_client = llm_client._openai_client
    try:
        yield
    finally:
        llm_client._mode = saved_mode
        llm_client._offline_model = saved_offline_model
        llm_client._openai_client = saved_openai_client


# ---------------------------------------------------------------------------
# _env_mode / _initial_mode
# ---------------------------------------------------------------------------


def test_env_mode_online_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FHD_LLM_MODE", "cloud")
    assert llm_client._env_mode() == "online"


def test_env_mode_api_alias_online(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FHD_LLM_MODE", raising=False)
    monkeypatch.setenv("LLM_MODE", "api")
    assert llm_client._env_mode() == "online"


def test_env_mode_unknown_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FHD_LLM_MODE", "weird")
    monkeypatch.delenv("LLM_MODE", raising=False)
    assert llm_client._env_mode() is None


def test_initial_mode_uses_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FHD_LLM_MODE", "offline")
    assert llm_client._initial_mode() == "offline"


def test_initial_mode_defaults_online(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FHD_LLM_MODE", raising=False)
    monkeypatch.delenv("LLM_MODE", raising=False)
    assert llm_client._initial_mode() == "online"


# ---------------------------------------------------------------------------
# _resolve_openai_timeout_seconds
# ---------------------------------------------------------------------------


def test_timeout_valueerror_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    # non-numeric -> ValueError -> 45.0 (clamped into [5, 300])
    monkeypatch.setenv("XCAGI_OPENAI_TIMEOUT_SEC", "not-a-number")
    assert llm_client._resolve_openai_timeout_seconds() == 45.0


def test_timeout_clamped_low(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XCAGI_OPENAI_TIMEOUT_SEC", "1")
    assert llm_client._resolve_openai_timeout_seconds() == 5.0


def test_timeout_clamped_high(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XCAGI_OPENAI_TIMEOUT_SEC", "9999")
    assert llm_client._resolve_openai_timeout_seconds() == 300.0


# ---------------------------------------------------------------------------
# _resolve_openai_max_retries
# ---------------------------------------------------------------------------


def test_max_retries_default_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XCAGI_OPENAI_MAX_RETRIES", raising=False)
    assert llm_client._resolve_openai_max_retries() == 0


def test_max_retries_valid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XCAGI_OPENAI_MAX_RETRIES", "3")
    assert llm_client._resolve_openai_max_retries() == 3


def test_max_retries_valueerror_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XCAGI_OPENAI_MAX_RETRIES", "xx")
    assert llm_client._resolve_openai_max_retries() == 0


def test_max_retries_clamped_high(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XCAGI_OPENAI_MAX_RETRIES", "42")
    assert llm_client._resolve_openai_max_retries() == 5


# ---------------------------------------------------------------------------
# set_mode validation + side effects
# ---------------------------------------------------------------------------


def test_set_mode_invalid_raises() -> None:
    with pytest.raises(ValueError, match="online.*offline"):
        llm_client.set_mode("bogus")


def test_set_mode_offline_sets_model_and_clears_client() -> None:
    llm_client._openai_client = MagicMock()
    llm_client.set_mode("offline", model="  llama3  ")
    assert llm_client.resolve_mode() == "offline"
    assert llm_client._offline_model == "llama3"
    assert llm_client._openai_client is None


def test_set_mode_offline_blank_model_becomes_none() -> None:
    llm_client.set_mode("offline", model="   ")
    assert llm_client._offline_model is None


def test_set_mode_online_clears_offline_model() -> None:
    llm_client.set_mode("offline", model="llama3")
    llm_client.set_mode("online")
    assert llm_client.resolve_mode() == "online"
    assert llm_client._offline_model is None


# ---------------------------------------------------------------------------
# _first_api_key / require_api_key
# ---------------------------------------------------------------------------


def test_first_api_key_delegates_to_credentials() -> None:
    with patch(
        "app.infrastructure.llm.providers.credentials.resolve_openai_env_credentials",
        return_value=("sk-abc", "https://base/v1"),
    ) as m:
        key, base = llm_client._first_api_key()
    assert key == "sk-abc"
    assert base == "https://base/v1"
    m.assert_called_once()


def test_require_api_key_offline_returns_without_checking() -> None:
    llm_client.set_mode("offline")
    # Even with no key configured, offline short-circuits and does not raise.
    with patch.object(llm_client, "_first_api_key") as m:
        llm_client.require_api_key()
        m.assert_not_called()


def test_require_api_key_online_missing_key_raises() -> None:
    llm_client.set_mode("online")
    with patch.object(llm_client, "_first_api_key", return_value=("", None)):
        with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
            llm_client.require_api_key()


def test_require_api_key_online_with_key_ok() -> None:
    llm_client.set_mode("online")
    with patch.object(llm_client, "_first_api_key", return_value=("sk-xyz", None)):
        # Should not raise.
        assert llm_client.require_api_key() is None


# ---------------------------------------------------------------------------
# get_llm_client
# ---------------------------------------------------------------------------


def test_get_llm_client_offline_returns_none() -> None:
    llm_client.set_mode("offline")
    assert llm_client.get_llm_client() is None


def test_get_llm_client_online_builds_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    llm_client.set_mode("online")
    llm_client._openai_client = None
    monkeypatch.setenv("XCAGI_OPENAI_TIMEOUT_SEC", "30")
    monkeypatch.setenv("XCAGI_OPENAI_MAX_RETRIES", "2")

    fake_instance = MagicMock(name="OpenAIInstance")
    fake_openai_cls = MagicMock(name="OpenAI", return_value=fake_instance)

    with (
        patch.object(llm_client, "_first_api_key", return_value=("sk-key", "https://gw/v1")),
        patch.dict("sys.modules", {"openai": MagicMock(OpenAI=fake_openai_cls)}),
    ):
        first = llm_client.get_llm_client()
        second = llm_client.get_llm_client()

    assert first is fake_instance
    # Singleton: constructed only once, second call returns cached.
    assert second is first
    fake_openai_cls.assert_called_once()
    kwargs = fake_openai_cls.call_args.kwargs
    assert kwargs["api_key"] == "sk-key"
    assert kwargs["timeout"] == 30.0
    assert kwargs["max_retries"] == 2
    assert kwargs["base_url"] == "https://gw/v1"


def test_get_llm_client_online_no_base_url_omits_kwarg() -> None:
    llm_client.set_mode("online")
    llm_client._openai_client = None
    fake_openai_cls = MagicMock(return_value=MagicMock())
    with (
        patch.object(llm_client, "_first_api_key", return_value=("sk-key", None)),
        patch.dict("sys.modules", {"openai": MagicMock(OpenAI=fake_openai_cls)}),
    ):
        llm_client.get_llm_client()
    kwargs = fake_openai_cls.call_args.kwargs
    assert "base_url" not in kwargs


# ---------------------------------------------------------------------------
# dispose_llm_client
# ---------------------------------------------------------------------------


def test_dispose_llm_client_clears_singleton() -> None:
    llm_client._openai_client = MagicMock()
    llm_client.dispose_llm_client()
    assert llm_client._openai_client is None


# ---------------------------------------------------------------------------
# get_offline_status — success parsing + error branch
# ---------------------------------------------------------------------------


@contextmanager
def _patch_urlopen(body: bytes) -> Iterator[None]:
    resp = MagicMock()
    resp.read.return_value = body
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = False
    with patch("urllib.request.urlopen", return_value=resp):
        yield


def test_get_offline_status_success_parses_models(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLLAMA_HOST", "http://localhost:11434/")
    llm_client._offline_model = "llama3"
    payload = json.dumps(
        {"models": [{"name": "llama3"}, {"name": "qwen"}, "phi3", {"no_name": 1}]}
    ).encode("utf-8")
    with _patch_urlopen(payload):
        status = llm_client.get_offline_status()
    assert status["ollama_reachable"] is True
    # trailing slash stripped from host
    assert status["ollama_host"] == "http://localhost:11434"
    # dict-with-name + bare str collected; dict-without-name skipped
    assert status["models"] == ["llama3", "qwen", "phi3"]
    assert status["preferred_offline_model"] == "llama3"


def test_get_offline_status_empty_models_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    llm_client._offline_model = None
    with _patch_urlopen(json.dumps({}).encode("utf-8")):
        status = llm_client.get_offline_status()
    assert status["ollama_reachable"] is True
    assert status["models"] == []
    assert status["preferred_offline_model"] is None


def test_get_offline_status_network_error_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLLAMA_HOST", "http://h:1234")
    llm_client._offline_model = "m1"
    with patch("urllib.request.urlopen", side_effect=OSError("boom")):
        status = llm_client.get_offline_status()
    assert status["ollama_reachable"] is False
    assert status["models"] == []
    assert status["preferred_offline_model"] == "m1"
    assert "boom" in status["error"]


def test_get_offline_status_bad_json_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLLAMA_HOST", "http://h:1234")
    llm_client._offline_model = None
    with _patch_urlopen(b"not-json{"):
        status = llm_client.get_offline_status()
    assert status["ollama_reachable"] is False
    assert "error" in status


# ---------------------------------------------------------------------------
# get_openai_compatible_client
# ---------------------------------------------------------------------------


def test_openai_compatible_client_returns_underlying() -> None:
    sentinel = MagicMock()
    with patch.object(llm_client, "get_llm_client", return_value=sentinel):
        assert llm_client.get_openai_compatible_client() is sentinel


def test_openai_compatible_client_offline_raises() -> None:
    with patch.object(llm_client, "get_llm_client", return_value=None):
        with pytest.raises(RuntimeError, match="offline mode"):
            llm_client.get_openai_compatible_client()


# ---------------------------------------------------------------------------
# resolve_chat_model
# ---------------------------------------------------------------------------


def test_resolve_chat_model_delegates() -> None:
    with patch(
        "app.infrastructure.llm.providers.credentials.resolve_default_chat_model",
        return_value="gpt-test",
    ) as m:
        assert llm_client.resolve_chat_model() == "gpt-test"
    m.assert_called_once()
