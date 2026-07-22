"""mimo_tts_service unit tests (mocked httpx)."""

from __future__ import annotations

import base64
from unittest.mock import MagicMock, patch

from modstore_server import mimo_tts_service as mts


def test_is_configured_false_without_key(monkeypatch):
    monkeypatch.delenv("XIAOMI_API_KEY", raising=False)
    monkeypatch.delenv("MIMO_API_KEY", raising=False)
    monkeypatch.delenv("XIAOMI_MIMO_API_KEY", raising=False)
    assert mts.is_configured() is False


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
