"""Tests for app.fastapi_routes.voice_routes — extended coverage (ext2).

Focus: _env, _resolve_device, _resolve_compute_type, _resolve_model_name,
_get_model (cache hit/miss, ImportError, RECOVERABLE_ERRORS), _save_upload_to_tempfile
(suffix detection), _run_transcribe, transcribe_audio route (empty file, too large,
success), voice_health route.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.fastapi_routes.voice_routes import (
    _MAX_UPLOAD_BYTES,
    _env,
    _get_model,
    _resolve_compute_type,
    _resolve_device,
    _resolve_model_name,
    _run_transcribe,
    _save_upload_to_tempfile,
    router,
)


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# _env
# ---------------------------------------------------------------------------


class TestEnv:
    def test_returns_value(self, monkeypatch):
        monkeypatch.setenv("TEST_VAR", "hello")
        assert _env("TEST_VAR") == "hello"

    def test_returns_default_when_unset(self, monkeypatch):
        monkeypatch.delenv("TEST_VAR", raising=False)
        assert _env("TEST_VAR", default="fallback") == "fallback"

    def test_strips_whitespace(self, monkeypatch):
        monkeypatch.setenv("TEST_VAR", "  spaced  ")
        assert _env("TEST_VAR") == "spaced"

    def test_returns_default_for_none(self, monkeypatch):
        monkeypatch.delenv("TEST_VAR", raising=False)
        assert _env("TEST_VAR") == ""


# ---------------------------------------------------------------------------
# _resolve_device
# ---------------------------------------------------------------------------


class TestResolveDevice:
    def test_explicit_cpu(self, monkeypatch):
        monkeypatch.setenv("XCAGI_CHAT_ASR_DEVICE", "cpu")
        assert _resolve_device() == "cpu"

    def test_explicit_cuda(self, monkeypatch):
        monkeypatch.setenv("XCAGI_CHAT_ASR_DEVICE", "cuda")
        assert _resolve_device() == "cuda"

    def test_explicit_uppercase(self, monkeypatch):
        monkeypatch.setenv("XCAGI_CHAT_ASR_DEVICE", "CPU")
        assert _resolve_device() == "cpu"

    def test_invalid_falls_back_to_torch(self, monkeypatch):
        monkeypatch.setenv("XCAGI_CHAT_ASR_DEVICE", "invalid")
        # Falls back to torch.cuda.is_available()
        try:
            import torch

            expected = "cuda" if torch.cuda.is_available() else "cpu"
            assert _resolve_device() == expected
        except ImportError:
            assert _resolve_device() == "cpu"

    def test_empty_falls_back_to_torch(self, monkeypatch):
        monkeypatch.delenv("XCAGI_CHAT_ASR_DEVICE", raising=False)
        try:
            import torch

            expected = "cuda" if torch.cuda.is_available() else "cpu"
            assert _resolve_device() == expected
        except ImportError:
            assert _resolve_device() == "cpu"

    def test_torch_import_error_returns_cpu(self, monkeypatch):
        monkeypatch.setenv("XCAGI_CHAT_ASR_DEVICE", "invalid")
        # Force ImportError on torch
        import builtins

        original_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "torch":
                raise ImportError("no torch")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fake_import):
            assert _resolve_device() == "cpu"


# ---------------------------------------------------------------------------
# _resolve_compute_type
# ---------------------------------------------------------------------------


class TestResolveComputeType:
    def test_explicit_value(self, monkeypatch):
        monkeypatch.setenv("XCAGI_CHAT_ASR_COMPUTE_TYPE", "float32")
        assert _resolve_compute_type("cpu") == "float32"

    def test_default_for_cpu(self, monkeypatch):
        monkeypatch.delenv("XCAGI_CHAT_ASR_COMPUTE_TYPE", raising=False)
        assert _resolve_compute_type("cpu") == "int8"

    def test_default_for_cuda(self, monkeypatch):
        monkeypatch.delenv("XCAGI_CHAT_ASR_COMPUTE_TYPE", raising=False)
        assert _resolve_compute_type("cuda") == "float16"

    def test_explicit_overrides_device_default(self, monkeypatch):
        monkeypatch.setenv("XCAGI_CHAT_ASR_COMPUTE_TYPE", "custom")
        assert _resolve_compute_type("cpu") == "custom"


# ---------------------------------------------------------------------------
# _resolve_model_name
# ---------------------------------------------------------------------------


class TestResolveModelName:
    def test_default_model(self, monkeypatch):
        monkeypatch.delenv("XCAGI_CHAT_ASR_MODEL", raising=False)
        assert _resolve_model_name() == "small"

    def test_custom_model(self, monkeypatch):
        monkeypatch.setenv("XCAGI_CHAT_ASR_MODEL", "medium")
        assert _resolve_model_name() == "medium"

    def test_strips_whitespace(self, monkeypatch):
        monkeypatch.setenv("XCAGI_CHAT_ASR_MODEL", "  tiny  ")
        assert _resolve_model_name() == "tiny"


# ---------------------------------------------------------------------------
# _get_model — caching and errors
# ---------------------------------------------------------------------------


class TestGetModel:
    def test_import_error_raises_503(self, monkeypatch):
        # Reset cache
        import app.fastapi_routes.voice_routes as mod

        mod._model_holder["instance"] = None
        mod._model_holder["signature"] = None

        monkeypatch.delenv("XCAGI_CHAT_ASR_DEVICE", raising=False)
        monkeypatch.delenv("XCAGI_CHAT_ASR_COMPUTE_TYPE", raising=False)

        original_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__

        def fake_import(name, *args, **kwargs):
            if name == "faster_whisper":
                raise ImportError("not installed")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fake_import):
            with pytest.raises(HTTPException) as exc_info:
                _get_model()
            assert exc_info.value.status_code == 503

    def test_recoverable_error_raises_503(self, monkeypatch):
        import app.fastapi_routes.voice_routes as mod

        mod._model_holder["instance"] = None
        mod._model_holder["signature"] = None

        monkeypatch.setenv("XCAGI_CHAT_ASR_DEVICE", "cpu")
        monkeypatch.delenv("XCAGI_CHAT_ASR_COMPUTE_TYPE", raising=False)

        mock_whisper_cls = MagicMock(side_effect=RuntimeError("model load failed"))

        with patch.dict(
            "sys.modules",
            {"faster_whisper": MagicMock(WhisperModel=mock_whisper_cls)},
        ):
            with pytest.raises(HTTPException) as exc_info:
                _get_model()
            assert exc_info.value.status_code == 503

    def test_cache_hit_returns_cached_instance(self, monkeypatch):
        import app.fastapi_routes.voice_routes as mod

        monkeypatch.setenv("XCAGI_CHAT_ASR_DEVICE", "cpu")
        monkeypatch.delenv("XCAGI_CHAT_ASR_COMPUTE_TYPE", raising=False)
        monkeypatch.setenv("XCAGI_CHAT_ASR_MODEL", "small")

        cached = MagicMock()
        mod._model_holder["instance"] = cached
        mod._model_holder["signature"] = ("small", "cpu", "int8")

        mock_whisper_cls = MagicMock()
        with patch.dict(
            "sys.modules",
            {"faster_whisper": MagicMock(WhisperModel=mock_whisper_cls)},
        ):
            result = _get_model()
            assert result is cached
            # WhisperModel should not be called since cache hit
            mock_whisper_cls.assert_not_called()

    def test_cache_miss_loads_new_instance(self, monkeypatch):
        import app.fastapi_routes.voice_routes as mod

        monkeypatch.setenv("XCAGI_CHAT_ASR_DEVICE", "cpu")
        monkeypatch.delenv("XCAGI_CHAT_ASR_COMPUTE_TYPE", raising=False)
        monkeypatch.setenv("XCAGI_CHAT_ASR_MODEL", "small")

        mod._model_holder["instance"] = None
        mod._model_holder["signature"] = None

        mock_instance = MagicMock()
        mock_whisper_cls = MagicMock(return_value=mock_instance)

        with patch.dict(
            "sys.modules",
            {"faster_whisper": MagicMock(WhisperModel=mock_whisper_cls)},
        ):
            result = _get_model()
            assert result is mock_instance
            assert mod._model_holder["instance"] is mock_instance
            assert mod._model_holder["signature"] == ("small", "cpu", "int8")


# ---------------------------------------------------------------------------
# _save_upload_to_tempfile
# ---------------------------------------------------------------------------


class TestSaveUploadToTempfile:
    def test_with_filename_extension(self, tmp_path):
        upload = MagicMock()
        upload.filename = "audio.webm"
        upload.content_type = ""

        with patch("tempfile.NamedTemporaryFile") as mock_tmp:
            mock_file = MagicMock()
            mock_file.name = str(tmp_path / "audio.webm")
            mock_tmp.return_value = mock_file

            result = _save_upload_to_tempfile(upload, b"data")
            mock_file.write.assert_called_once_with(b"data")
            mock_file.flush.assert_called_once()
            mock_file.close.assert_called_once()

    def test_with_no_filename_uses_content_type_webm(self):
        upload = MagicMock()
        upload.filename = None
        upload.content_type = "audio/webm"

        with patch("tempfile.NamedTemporaryFile") as mock_tmp:
            mock_file = MagicMock()
            mock_file.name = "/tmp/test.webm"
            mock_tmp.return_value = mock_file

            _save_upload_to_tempfile(upload, b"data")
            _, kwargs = mock_tmp.call_args
            assert kwargs.get("suffix") == ".webm"

    def test_with_no_filename_uses_content_type_ogg(self):
        upload = MagicMock()
        upload.filename = None
        upload.content_type = "audio/ogg"

        with patch("tempfile.NamedTemporaryFile") as mock_tmp:
            mock_file = MagicMock()
            mock_file.name = "/tmp/test.ogg"
            mock_tmp.return_value = mock_file

            _save_upload_to_tempfile(upload, b"data")
            _, kwargs = mock_tmp.call_args
            assert kwargs.get("suffix") == ".ogg"

    def test_with_no_filename_uses_content_type_mp4(self):
        upload = MagicMock()
        upload.filename = None
        upload.content_type = "audio/mp4"

        with patch("tempfile.NamedTemporaryFile") as mock_tmp:
            mock_file = MagicMock()
            mock_file.name = "/tmp/test.m4a"
            mock_tmp.return_value = mock_file

            _save_upload_to_tempfile(upload, b"data")
            _, kwargs = mock_tmp.call_args
            assert kwargs.get("suffix") == ".m4a"

    def test_with_no_filename_uses_content_type_m4a(self):
        upload = MagicMock()
        upload.filename = None
        upload.content_type = "audio/m4a"

        with patch("tempfile.NamedTemporaryFile") as mock_tmp:
            mock_file = MagicMock()
            mock_file.name = "/tmp/test.m4a"
            mock_tmp.return_value = mock_file

            _save_upload_to_tempfile(upload, b"data")
            _, kwargs = mock_tmp.call_args
            assert kwargs.get("suffix") == ".m4a"

    def test_with_no_filename_uses_content_type_wav(self):
        upload = MagicMock()
        upload.filename = None
        upload.content_type = "audio/wav"

        with patch("tempfile.NamedTemporaryFile") as mock_tmp:
            mock_file = MagicMock()
            mock_file.name = "/tmp/test.wav"
            mock_tmp.return_value = mock_file

            _save_upload_to_tempfile(upload, b"data")
            _, kwargs = mock_tmp.call_args
            assert kwargs.get("suffix") == ".wav"

    def test_with_no_filename_uses_content_type_wave(self):
        upload = MagicMock()
        upload.filename = None
        upload.content_type = "audio/wave"

        with patch("tempfile.NamedTemporaryFile") as mock_tmp:
            mock_file = MagicMock()
            mock_file.name = "/tmp/test.wav"
            mock_tmp.return_value = mock_file

            _save_upload_to_tempfile(upload, b"data")
            _, kwargs = mock_tmp.call_args
            assert kwargs.get("suffix") == ".wav"

    def test_with_no_filename_unknown_content_type(self):
        upload = MagicMock()
        upload.filename = None
        upload.content_type = "audio/unknown"

        with patch("tempfile.NamedTemporaryFile") as mock_tmp:
            mock_file = MagicMock()
            mock_file.name = "/tmp/test.bin"
            mock_tmp.return_value = mock_file

            _save_upload_to_tempfile(upload, b"data")
            _, kwargs = mock_tmp.call_args
            assert kwargs.get("suffix") == ".bin"

    def test_with_empty_filename_and_content_type(self):
        upload = MagicMock()
        upload.filename = ""
        upload.content_type = ""

        with patch("tempfile.NamedTemporaryFile") as mock_tmp:
            mock_file = MagicMock()
            mock_file.name = "/tmp/test.bin"
            mock_tmp.return_value = mock_file

            _save_upload_to_tempfile(upload, b"data")
            _, kwargs = mock_tmp.call_args
            assert kwargs.get("suffix") == ".bin"


# ---------------------------------------------------------------------------
# _run_transcribe
# ---------------------------------------------------------------------------


class TestRunTranscribe:
    def test_successful_transcription(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCAGI_CHAT_ASR_BEAM", "1")
        monkeypatch.delenv("XCAGI_CHAT_ASR_LANGUAGE", raising=False)

        mock_model = MagicMock()
        mock_segment = MagicMock()
        mock_segment.text = "  hello world  "
        mock_info = MagicMock()
        mock_info.language = "en"
        mock_info.duration = 5.0
        mock_model.transcribe.return_value = ([mock_segment], mock_info)

        with patch("app.fastapi_routes.voice_routes._get_model", return_value=mock_model):
            result = _run_transcribe(tmp_path / "audio.webm", None)
            assert result["text"] == "hello world"
            assert result["language"] == "en"
            assert result["audio_seconds"] == 5.0

    def test_with_explicit_language(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCAGI_CHAT_ASR_BEAM", "1")
        monkeypatch.delenv("XCAGI_CHAT_ASR_LANGUAGE", raising=False)

        mock_model = MagicMock()
        mock_segment = MagicMock()
        mock_segment.text = "你好"
        mock_info = MagicMock()
        mock_info.language = "zh"
        mock_info.duration = 3.0
        mock_model.transcribe.return_value = ([mock_segment], mock_info)

        with patch("app.fastapi_routes.voice_routes._get_model", return_value=mock_model):
            result = _run_transcribe(tmp_path / "audio.webm", "zh")
            assert result["text"] == "你好"
            assert result["language"] == "zh"

    def test_recoverable_error_raises_500(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCAGI_CHAT_ASR_BEAM", "1")

        mock_model = MagicMock()
        mock_model.transcribe.side_effect =RuntimeError("decode failed")

        with patch("app.fastapi_routes.voice_routes._get_model", return_value=mock_model):
            with pytest.raises(HTTPException) as exc_info:
                _run_transcribe(tmp_path / "audio.webm", None)
            assert exc_info.value.status_code == 500

    def test_multiple_segments_concatenated(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCAGI_CHAT_ASR_BEAM", "1")

        mock_model = MagicMock()
        seg1 = MagicMock()
        seg1.text = "hello"
        seg2 = MagicMock()
        seg2.text = "world"
        mock_info = MagicMock()
        mock_info.language = "en"
        mock_info.duration = 2.0
        mock_model.transcribe.return_value = ([seg1, seg2], mock_info)

        with patch("app.fastapi_routes.voice_routes._get_model", return_value=mock_model):
            result = _run_transcribe(tmp_path / "audio.webm", None)
            assert result["text"] == "helloworld"


# ---------------------------------------------------------------------------
# transcribe_audio route
# ---------------------------------------------------------------------------


class TestTranscribeAudioRoute:
    def test_empty_file_returns_400(self, client: TestClient):
        response = client.post(
            "/api/voice/transcribe",
            files={"file": ("audio.webm", b"", "audio/webm")},
        )
        assert response.status_code == 400
        assert "为空" in response.json()["detail"]

    def test_file_too_large_returns_413(self, client: TestClient):
        # Create a file larger than _MAX_UPLOAD_BYTES
        large_content = b"x" * (_MAX_UPLOAD_BYTES + 1)
        response = client.post(
            "/api/voice/transcribe",
            files={"file": ("audio.webm", large_content, "audio/webm")},
        )
        assert response.status_code == 413
        assert "过大" in response.json()["detail"]

    def test_successful_transcription(self, client: TestClient, monkeypatch):
        monkeypatch.setenv("XCAGI_CHAT_ASR_BEAM", "1")

        mock_result = {
            "text": "hello world",
            "language": "en",
            "audio_seconds": 5.0,
        }

        with patch(
            "app.fastapi_routes.voice_routes._run_transcribe",
            return_value=mock_result,
        ):
            response = client.post(
                "/api/voice/transcribe",
                files={"file": ("audio.webm", b"audio data", "audio/webm")},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert data["data"]["text"] == "hello world"
            assert data["data"]["language"] == "en"
            assert data["data"]["bytes"] == len(b"audio data")
            assert "elapsed_ms" in data["data"]


# ---------------------------------------------------------------------------
# voice_health route
# ---------------------------------------------------------------------------


class TestVoiceHealthRoute:
    def test_healthy(self, client: TestClient, monkeypatch):
        monkeypatch.setenv("XCAGI_CHAT_ASR_MODEL", "small")
        monkeypatch.delenv("XCAGI_CHAT_ASR_DEVICE", raising=False)

        # Make faster_whisper importable
        with patch.dict("sys.modules", {"faster_whisper": MagicMock()}):
            response = client.get("/api/voice/health")
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert data["data"]["ready"] is True
            assert data["data"]["reason"] == ""
            assert data["data"]["model"] == "small"

    def test_not_ready(self, client: TestClient, monkeypatch):
        monkeypatch.setenv("XCAGI_CHAT_ASR_MODEL", "small")
        monkeypatch.delenv("XCAGI_CHAT_ASR_DEVICE", raising=False)

        original_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__

        def fake_import(name, *args, **kwargs):
            if name == "faster_whisper":
                raise ImportError("not installed")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fake_import):
            response = client.get("/api/voice/health")
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert data["data"]["ready"] is False
            assert "not installed" in data["data"]["reason"]
