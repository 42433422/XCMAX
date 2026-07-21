"""Tests for app.services.mimo_tts_service — MiMo-V2.5 TTS HTTP client.

Covers:
* ``resolve_mimo_credentials`` env var resolution + /v1 root stripping.
* ``is_configured`` truthy check.
* ``synthesize_mimo_bytes``:
  - empty text raises ValueError
  - missing api key raises RuntimeError
  - happy path with mocked httpx.Client returns (bytes, meta)
  - non-audio response raises RuntimeError
  - empty decoded audio raises RuntimeError
  - format/voice/model defaults
  - httpx error propagates via raise_for_status
"""

from __future__ import annotations

import base64
from unittest.mock import MagicMock, patch

import pytest

from app.services import mimo_tts_service as mimo


# ---------------------------------------------------------------------------
# resolve_mimo_credentials
# ---------------------------------------------------------------------------


class TestResolveCredentials:
    def test_returns_default_root_when_no_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for v in (
            "XIAOMI_API_KEY",
            "MIMO_API_KEY",
            "XIAOMI_MIMO_API_KEY",
            "XIAOMI_BASE_URL",
            "MIMO_BASE_URL",
            "XIAOMI_MIMO_BASE_URL",
        ):
            monkeypatch.delenv(v, raising=False)
        key, root = mimo.resolve_mimo_credentials()
        assert key is None
        assert root == mimo._DEFAULT_ROOT

    def test_strips_trailing_slash(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XIAOMI_API_KEY", "k1")
        monkeypatch.setenv("XIAOMI_BASE_URL", "https://api.example.com/")
        for v in ("MIMO_API_KEY", "XIAOMI_MIMO_API_KEY", "MIMO_BASE_URL", "XIAOMI_MIMO_BASE_URL"):
            monkeypatch.delenv(v, raising=False)
        key, root = mimo.resolve_mimo_credentials()
        assert key == "k1"
        assert root == "https://api.example.com"

    def test_strips_v1_suffix(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MIMO_API_KEY", "k2")
        monkeypatch.setenv("MIMO_BASE_URL", "https://api.example.com/v1")
        for v in ("XIAOMI_API_KEY", "XIAOMI_MIMO_API_KEY", "XIAOMI_BASE_URL", "XIAOMI_MIMO_BASE_URL"):
            monkeypatch.delenv(v, raising=False)
        key, root = mimo.resolve_mimo_credentials()
        assert key == "k2"
        assert root == "https://api.example.com"

    def test_prefers_xiaomi_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XIAOMI_API_KEY", "primary")
        monkeypatch.setenv("MIMO_API_KEY", "fallback")
        for v in ("XIAOMI_MIMO_API_KEY", "XIAOMI_BASE_URL", "MIMO_BASE_URL", "XIAOMI_MIMO_BASE_URL"):
            monkeypatch.delenv(v, raising=False)
        key, _ = mimo.resolve_mimo_credentials()
        assert key == "primary"

    def test_returns_none_when_only_whitespace(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XIAOMI_API_KEY", "   ")
        for v in ("MIMO_API_KEY", "XIAOMI_MIMO_API_KEY", "XIAOMI_BASE_URL", "MIMO_BASE_URL", "XIAOMI_MIMO_BASE_URL"):
            monkeypatch.delenv(v, raising=False)
        key, _ = mimo.resolve_mimo_credentials()
        assert key is None


# ---------------------------------------------------------------------------
# is_configured
# ---------------------------------------------------------------------------


class TestIsConfigured:
    def test_false_when_no_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for v in ("XIAOMI_API_KEY", "MIMO_API_KEY", "XIAOMI_MIMO_API_KEY"):
            monkeypatch.delenv(v, raising=False)
        assert mimo.is_configured() is False

    def test_true_when_key_present(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XIAOMI_API_KEY", "k1")
        assert mimo.is_configured() is True


# ---------------------------------------------------------------------------
# synthesize_mimo_bytes
# ---------------------------------------------------------------------------


def _make_response(*, audio_b64: str | None = "QUJD", status_code: int = 200) -> MagicMock:
    """Build a fake httpx.Response mimicking MiMo audio payload."""
    resp = MagicMock()
    resp.status_code = status_code
    if audio_b64 is None:
        resp.json.return_value = {"choices": [{"message": {}}]}
    else:
        resp.json.return_value = {
            "choices": [
                {
                    "message": {
                        "audio": {"data": audio_b64},
                    }
                }
            ]
        }
    resp.raise_for_status = MagicMock()
    return resp


class TestSynthesizeMimoBytes:
    def test_empty_text_raises_value_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XIAOMI_API_KEY", "k1")
        with pytest.raises(ValueError, match="text is empty"):
            mimo.synthesize_mimo_bytes("")

    def test_whitespace_only_raises_value_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XIAOMI_API_KEY", "k1")
        with pytest.raises(ValueError, match="text is empty"):
            mimo.synthesize_mimo_bytes("   \n  ")

    def test_missing_api_key_raises_runtime_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for v in ("XIAOMI_API_KEY", "MIMO_API_KEY", "XIAOMI_MIMO_API_KEY"):
            monkeypatch.delenv(v, raising=False)
        with pytest.raises(RuntimeError, match="mimo api key missing"):
            mimo.synthesize_mimo_bytes("hello")

    def test_happy_path_returns_bytes_and_meta(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XIAOMI_API_KEY", "k1")
        fake_client = MagicMock()
        fake_client.__enter__ = MagicMock(return_value=fake_client)
        fake_client.__exit__ = MagicMock(return_value=False)
        fake_client.post = MagicMock(return_value=_make_response(audio_b64="QUJD"))

        with patch("httpx.Client", return_value=fake_client):
            raw, meta = mimo.synthesize_mimo_bytes("hello")

        assert raw == b"ABC"  # base64.b64decode("QUJD") == b"ABC"
        assert meta["provider"] == "mimo"
        assert meta["model"] == mimo.DEFAULT_MODEL
        assert meta["voice"] == mimo.DEFAULT_VOICE
        assert meta["format"] == "wav"
        assert meta["mime"] == "audio/wav"

    def test_uses_mp3_format_when_requested(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XIAOMI_API_KEY", "k1")
        fake_client = MagicMock()
        fake_client.__enter__ = MagicMock(return_value=fake_client)
        fake_client.__exit__ = MagicMock(return_value=False)
        fake_client.post = MagicMock(return_value=_make_response(audio_b64="QUJD"))

        with patch("httpx.Client", return_value=fake_client):
            _, meta = mimo.synthesize_mimo_bytes("hi", audio_format="mp3")

        assert meta["format"] == "mp3"
        assert meta["mime"] == "audio/mp3"

    def test_wave_format_treated_as_wav_mime(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XIAOMI_API_KEY", "k1")
        fake_client = MagicMock()
        fake_client.__enter__ = MagicMock(return_value=fake_client)
        fake_client.__exit__ = MagicMock(return_value=False)
        fake_client.post = MagicMock(return_value=_make_response(audio_b64="QUJD"))

        with patch("httpx.Client", return_value=fake_client):
            _, meta = mimo.synthesize_mimo_bytes("hi", audio_format="wave")

        assert meta["format"] == "wave"
        assert meta["mime"] == "audio/wav"

    def test_missing_audio_data_raises_runtime_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XIAOMI_API_KEY", "k1")
        fake_client = MagicMock()
        fake_client.__enter__ = MagicMock(return_value=fake_client)
        fake_client.__exit__ = MagicMock(return_value=False)
        fake_client.post = MagicMock(return_value=_make_response(audio_b64=None))

        with patch("httpx.Client", return_value=fake_client):
            with pytest.raises(RuntimeError, match="mimo-tts response missing audio.data"):
                mimo.synthesize_mimo_bytes("hi")

    def test_empty_audio_data_raises_runtime_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XIAOMI_API_KEY", "k1")
        fake_client = MagicMock()
        fake_client.__enter__ = MagicMock(return_value=fake_client)
        fake_client.__exit__ = MagicMock(return_value=False)
        fake_client.post = MagicMock(return_value=_make_response(audio_b64=""))

        with patch("httpx.Client", return_value=fake_client):
            with pytest.raises(RuntimeError, match="mimo-tts response missing audio.data"):
                mimo.synthesize_mimo_bytes("hi")

    def test_decoded_empty_audio_raises_runtime_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XIAOMI_API_KEY", "k1")
        fake_client = MagicMock()
        fake_client.__enter__ = MagicMock(return_value=fake_client)
        fake_client.__exit__ = MagicMock(return_value=False)
        # Whitespace-only audio.data: base64.b64decode(" ") returns b"" → triggers
        # the "decoded empty audio" branch (different from "missing audio.data").
        fake_client.post = MagicMock(return_value=_make_response(audio_b64=" "))

        with patch("httpx.Client", return_value=fake_client):
            with pytest.raises(RuntimeError, match="mimo-tts returned empty audio"):
                mimo.synthesize_mimo_bytes("hi")

    def test_voice_defaults_when_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XIAOMI_API_KEY", "k1")
        fake_client = MagicMock()
        fake_client.__enter__ = MagicMock(return_value=fake_client)
        fake_client.__exit__ = MagicMock(return_value=False)
        fake_client.post = MagicMock(return_value=_make_response(audio_b64="QUJD"))

        with patch("httpx.Client", return_value=fake_client):
            _, meta = mimo.synthesize_mimo_bytes("hi", voice="")

        assert meta["voice"] == mimo.DEFAULT_VOICE
        _args, kwargs = fake_client.post.call_args
        assert kwargs["json"]["audio"]["voice"] == mimo.DEFAULT_VOICE

    def test_raise_for_status_propagates_http_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("XIAOMI_API_KEY", "k1")
        fake_client = MagicMock()
        fake_client.__enter__ = MagicMock(return_value=fake_client)
        fake_client.__exit__ = MagicMock(return_value=False)
        resp = _make_response(audio_b64="QUJD")
        resp.raise_for_status.side_effect = RuntimeError("HTTP 500")
        fake_client.post = MagicMock(return_value=resp)

        with patch("httpx.Client", return_value=fake_client):
            with pytest.raises(RuntimeError, match="HTTP 500"):
                mimo.synthesize_mimo_bytes("hi")

    def test_custom_model_passed_through(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XIAOMI_API_KEY", "k1")
        fake_client = MagicMock()
        fake_client.__enter__ = MagicMock(return_value=fake_client)
        fake_client.__exit__ = MagicMock(return_value=False)
        fake_client.post = MagicMock(return_value=_make_response(audio_b64="QUJD"))

        with patch("httpx.Client", return_value=fake_client):
            _, meta = mimo.synthesize_mimo_bytes("hi", model="custom-mimo-model")

        assert meta["model"] == "custom-mimo-model"
        _args, kwargs = fake_client.post.call_args
        assert kwargs["json"]["model"] == "custom-mimo-model"

    def test_headers_include_both_api_key_and_bearer(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("XIAOMI_API_KEY", "secret-key")
        fake_client = MagicMock()
        fake_client.__enter__ = MagicMock(return_value=fake_client)
        fake_client.__exit__ = MagicMock(return_value=False)
        fake_client.post = MagicMock(return_value=_make_response(audio_b64="QUJD"))

        with patch("httpx.Client", return_value=fake_client):
            mimo.synthesize_mimo_bytes("hi")

        _args, kwargs = fake_client.post.call_args
        headers = kwargs["headers"]
        assert headers["api-key"] == "secret-key"
        assert headers["Authorization"] == "Bearer secret-key"

    def test_text_truncated_to_4000_chars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XIAOMI_API_KEY", "k1")
        fake_client = MagicMock()
        fake_client.__enter__ = MagicMock(return_value=fake_client)
        fake_client.__exit__ = MagicMock(return_value=False)
        fake_client.post = MagicMock(return_value=_make_response(audio_b64="QUJD"))

        long_text = "x" * 5000
        with patch("httpx.Client", return_value=fake_client):
            mimo.synthesize_mimo_bytes(long_text)

        _args, kwargs = fake_client.post.call_args
        sent_text = kwargs["json"]["messages"][1]["content"]
        assert len(sent_text) == 4000
