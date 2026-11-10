"""Exercise desktop-to-platform ASR using a synthetic, in-process provider."""

import asyncio
import base64
import io
import wave
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

pytest.importorskip("modstore_server")

from modstore_server import llm_key_resolver, mimo_tts_service, models
from modstore_server.workbench import speech_api
from modstore_server.workbench.schemas import WorkbenchUnifiedTtsBody

from app.fastapi_routes import ai_assistant_tts
from app.fastapi_routes.voice_routes import router


def test_recording_reaches_mimo_with_current_account_without_retry(monkeypatch):
    monkeypatch.setenv("XCAGI_CHAT_ASR_PROVIDER", "mimo")
    monkeypatch.setenv("MODSTORE_MIMO_ASR_ENABLED", "1")
    monkeypatch.setenv("MODSTORE_MIMO_ASR_USER_IDS", "42")
    monkeypatch.setattr(
        "app.fastapi_routes.ai_assistant_tts._session_market_token", lambda _: "session-token"
    )
    monkeypatch.setattr(models, "get_session_factory", lambda: lambda: nullcontext("session"))
    calls = []

    def credentials(session, user_id, provider):
        assert (session, user_id, provider) == ("session", 42, "xiaomi")
        return "test-key", "https://provider.invalid/v1", "user_override"

    monkeypatch.setattr(llm_key_resolver, "resolve_credentials", credentials)

    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, url, **kwargs):
            calls.append(url)
            if url.endswith("/api/workbench/asr"):
                assert kwargs["headers"]["Authorization"] == "Bearer session-token"
                payload = await speech_api.mimo_asr(kwargs["files"]["file"][1], "zh", 42)
                return httpx.Response(200, json=payload)
            assert url == "https://provider.invalid/v1/chat/completions"
            assert kwargs["headers"]["api-key"] == "test-key"
            body = kwargs["json"]
            assert body["model"] == "mimo-v2.5-asr"
            assert body["messages"][0]["content"][0]["input_audio"]["data"].startswith(
                "data:audio/wav;base64,"
            )
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": "测试语音"}}]},
                request=httpx.Request("POST", url),
            )

    monkeypatch.setattr(httpx, "AsyncClient", Client)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\0\0" * 1600)
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        result = client.post(
            "/api/voice/transcribe",
            files={"file": ("voice.wav", buffer.getvalue(), "audio/wav")},
            data={"language": "zh"},
        )
    assert result.status_code == 200
    assert result.json()["data"]["text"] == "测试语音"
    assert len(calls) == 2


def test_tts_platform_audio_and_chinese_voice_reach_desktop(monkeypatch):
    monkeypatch.setattr(ai_assistant_tts, "_session_market_token", lambda _: "session-token")
    monkeypatch.setattr(ai_assistant_tts, "_trace", lambda payload, **_: payload)
    monkeypatch.setattr(models, "get_session_factory", lambda: lambda: nullcontext("session"))
    monkeypatch.setattr(
        llm_key_resolver,
        "resolve_credentials",
        lambda session, uid, provider: ("test-key", "https://provider.invalid/v1", "user_override"),
    )
    synth = AsyncMock(return_value=(b"RIFFaudio", "", {"mime": "audio/wav", "voice": "冰糖"}))
    monkeypatch.setattr(mimo_tts_service, "synthesize_mimo_tts_async", synth)

    class PlatformClient:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def post(self, url, **kwargs):
            assert url.endswith("/api/workbench/tts")
            assert kwargs["headers"]["Authorization"] == "Bearer session-token"
            result = asyncio.run(
                speech_api.workbench_unified_tts(
                    WorkbenchUnifiedTtsBody(**kwargs["json"]),
                    SimpleNamespace(id=42),
                    ports=speech_api.SpeechPorts(edge=None),
                )
            )
            return httpx.Response(
                result.status_code, content=result.body, headers=dict(result.headers)
            )

    app = FastAPI()
    app.include_router(ai_assistant_tts.router)
    with TestClient(app) as client, patch("httpx.Client", PlatformClient):
        response = client.post("/api/tts", json={"text": "你好"})
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["voice"] == "冰糖" and data["provider"] == "mimo"
    assert base64.b64decode(data["audioBase64"].split(",", 1)[1]) == b"RIFFaudio"
    assert synth.await_args.kwargs["credentials"] == ("test-key", "https://provider.invalid/v1")
