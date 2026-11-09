"""mimo_tts_service unit tests (mocked httpx)."""

from __future__ import annotations

import base64
from unittest.mock import MagicMock, patch

from modstore_server import mimo_tts_service as mts


def _clear_mimo_env(monkeypatch):
    for name in (
        "XIAOMI_API_KEY",
        "MIMO_API_KEY",
        "XIAOMI_MIMO_API_KEY",
        "XIAOMI_BASE_URL",
        "MIMO_BASE_URL",
        "XIAOMI_MIMO_BASE_URL",
    ):
        monkeypatch.delenv(name, raising=False)


def test_is_configured_false_without_key(monkeypatch):
    _clear_mimo_env(monkeypatch)
    monkeypatch.setattr(mts, "_platform_xiaomi_credentials", lambda: ("", ""))
    assert mts.is_configured() is False


def test_platform_key_is_used_when_env_is_empty(monkeypatch):
    _clear_mimo_env(monkeypatch)
    monkeypatch.setattr(
        mts,
        "_platform_xiaomi_credentials",
        lambda: ("platform-key", "https://token-plan-cn.xiaomimimo.com/v1"),
    )
    key, root = mts.resolve_mimo_credentials()
    assert key == "platform-key"
    assert root == "https://token-plan-cn.xiaomimimo.com"
    assert mts.is_configured() is True


def test_platform_helper_reads_xiaomi_store(monkeypatch):
    seen = {}

    def fake(provider):
        seen["provider"] = provider
        return ("stored-key", "https://token-plan-cn.xiaomimimo.com/v1")

    monkeypatch.setattr("modstore_server.llm_key_resolver.platform_credentials", fake)
    assert mts._platform_xiaomi_credentials() == (
        "stored-key",
        "https://token-plan-cn.xiaomimimo.com/v1",
    )
    assert seen["provider"] == "xiaomi"


def test_env_key_beats_platform_key(monkeypatch):
    _clear_mimo_env(monkeypatch)
    monkeypatch.setenv("MIMO_API_KEY", "env-key")
    monkeypatch.setattr(mts, "_platform_xiaomi_credentials", lambda: ("platform-key", "https://other.example/v1"))
    key, root = mts.resolve_mimo_credentials()
    assert key == "env-key"
    assert root == mts._DEFAULT_ROOT


def test_synthesize_missing_key():
    with patch.object(mts, "resolve_mimo_credentials", return_value=(None, mts._DEFAULT_ROOT)):
        audio, err, _meta = mts.synthesize_mimo_tts("你好")
    assert audio is None
    assert "missing" in err


def test_synthesize_happy_path(monkeypatch):
    monkeypatch.setenv("MIMO_API_KEY", "test-key")
    raw = b"RIFF....WAVEfmt "
    b64 = base64.b64encode(raw).decode("ascii")
    fake_resp = MagicMock()
    fake_resp.raise_for_status = MagicMock()
    fake_resp.json.return_value = {
        "choices": [{"message": {"audio": {"data": b64}}}],
    }

    class _Client:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, *a, **k):
            return fake_resp

    with patch("httpx.Client", return_value=_Client()):
        audio, err, meta = mts.synthesize_mimo_tts("你好", voice="冰糖")
    assert err == ""
    assert audio == raw
    assert meta["provider"] == "mimo"
    assert meta["voice"] == "冰糖"
