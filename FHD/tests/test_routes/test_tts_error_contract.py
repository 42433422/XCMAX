from __future__ import annotations

import base64
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.facades import tts_facade
from app.domain.shared_services import mimo_tts_service, tts_service
from app.fastapi_routes import ai_assistant_tts


@pytest.fixture
def client(monkeypatch):
    app = FastAPI()
    app.include_router(ai_assistant_tts.router)
    monkeypatch.setattr(tts_facade, "trigger_common_tts_warmup", lambda: None)
    monkeypatch.setattr(ai_assistant_tts, "_trace", lambda payload, **kwargs: payload)
    monkeypatch.setattr(tts_service, "_TTS_CACHE", tts_service.OrderedDict())
    monkeypatch.setattr(tts_service, "_EDGE_BLOCKED_UNTIL", 0.0)
    monkeypatch.setattr(mimo_tts_service, "is_configured", lambda: False)
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"text": "  "},
        {"text": 123},
        {"text": "x" * 4001},
        {"text": "hello", "voice": []},
        {"text": "hello", "speakerId": {}},
        {"text": "hello", "lang": 123},
        {"text": "hello", "rate": "NaN"},
        {"text": "hello", "pitch": "+10%"},
    ],
)
def test_invalid_parameters_are_rejected_before_warmup(client, monkeypatch, body):
    warmup = MagicMock()
    monkeypatch.setattr(tts_facade, "trigger_common_tts_warmup", warmup)
    assert client.post("/api/tts", json=body).status_code == 422
    warmup.assert_not_called()


@pytest.mark.parametrize(
    "error,status",
    [
        (TimeoutError(), 504),
        (httpx.ReadTimeout("timeout"), 504),
        (httpx.ConnectError("network"), 502),
        (
            httpx.HTTPStatusError(
                "limited",
                request=httpx.Request("POST", "https://example.test"),
                response=httpx.Response(429),
            ),
            429,
        ),
        (
            httpx.HTTPStatusError(
                "unavailable",
                request=httpx.Request("POST", "https://example.test"),
                response=httpx.Response(503),
            ),
            503,
        ),
        (
            httpx.HTTPStatusError(
                "bad gateway",
                request=httpx.Request("POST", "https://example.test"),
                response=httpx.Response(500),
            ),
            502,
        ),
        (ValueError("internal bug"), 500),
        (RuntimeError("internal bug"), 500),
    ],
)
def test_edge_failure_classification(client, monkeypatch, error, status):
    monkeypatch.setattr(tts_service, "_run_edge_sync", MagicMock(side_effect=error))
    assert client.post("/api/tts", json={"text": "hello"}).status_code == status


@pytest.mark.parametrize(
    "error",
    [
        aiohttp.ClientResponseError(MagicMock(), (), status=504),
        aiohttp.WSServerHandshakeError(MagicMock(), (), status=504),
        httpx.HTTPStatusError(
            "gateway timeout",
            request=httpx.Request("POST", "https://example.test"),
            response=httpx.Response(504),
        ),
    ],
)
def test_edge_upstream_http_504_is_gateway_timeout(client, monkeypatch, error):
    monkeypatch.setattr(tts_service, "_run_edge_sync", MagicMock(side_effect=error))
    assert client.post("/api/tts", json={"text": "hello"}).status_code == 504


@pytest.mark.parametrize("audio", [b"", "invalid"])
def test_invalid_edge_audio_is_502_and_not_cached(client, monkeypatch, audio):
    monkeypatch.setattr(tts_service, "_run_edge_sync", lambda req: audio)
    assert client.post("/api/tts", json={"text": "hello"}).status_code == 502
    assert not tts_service._TTS_CACHE


@pytest.mark.parametrize(
    "result",
    [
        None,
        {},
        {"audioBase64": "data:audio/wav;base64,YWJj!!!!"},
        {"audioBase64": "data:audio/wav;base64,"},
    ],
)
def test_invalid_facade_result_is_502(client, monkeypatch, result):
    monkeypatch.setattr(tts_facade, "synthesize_to_data_uri", lambda **kwargs: result)
    assert client.post("/api/tts", json={"text": "hello"}).status_code == 502


@pytest.mark.parametrize(
    "data",
    [None, [], {"choices": [None]}, {"choices": [{"message": {"audio": {"data": "YWJj!!!!"}}}]}],
)
def test_mimo_malformed_response_falls_back_to_edge(client, monkeypatch, data):
    monkeypatch.setenv("XIAOMI_API_KEY", "test-key")
    monkeypatch.setattr(mimo_tts_service, "is_configured", lambda: True)
    response = MagicMock()
    response.json.return_value = data
    upstream = MagicMock()
    upstream.__aenter__ = AsyncMock(return_value=upstream)
    upstream.__aexit__ = AsyncMock(return_value=False)
    upstream.post = AsyncMock(return_value=response)
    monkeypatch.setattr(tts_service, "_run_edge_sync", lambda req: b"edge-audio")
    with patch("httpx.AsyncClient", return_value=upstream):
        result = client.post("/api/tts", json={"text": "hello"})
    assert result.status_code == 200
    assert result.json()["data"]["provider"] == "edge"
    assert base64.b64decode(result.json()["data"]["audioBase64"].split(",", 1)[1]) == b"edge-audio"


def test_logged_in_software_uses_platform_mimo_instead_of_edge(client, monkeypatch):
    audio = b"RIFFplatform"
    response = httpx.Response(
        200,
        content=audio,
        headers={"content-type": "audio/wav", "x-tts-provider": "mimo", "x-tts-voice": "Chloe"},
    )
    client_cm = MagicMock()
    client_cm.__enter__.return_value = client_cm
    client_cm.__exit__.return_value = False
    client_cm.post.return_value = response
    edge = MagicMock(return_value=b"edge-audio")
    monkeypatch.setattr(ai_assistant_tts, "_session_market_token", lambda request: "market-token")
    monkeypatch.setattr(tts_service, "_run_edge_sync", edge)
    with patch("httpx.Client", return_value=client_cm):
        result = client.post("/api/tts", json={"text": "你好", "voice": "zh-CN-XiaoxiaoNeural", "rate": "+15%"})
    assert result.status_code == 200
    body = result.json()["data"]
    assert body["provider"] == "mimo"
    assert body["voice"] == "Chloe"
    assert base64.b64decode(body["audioBase64"].split(",", 1)[1]) == audio
    edge.assert_not_called()
    sent = client_cm.post.call_args
    assert sent.args[0].endswith("/api/workbench/tts")
    assert sent.kwargs["json"]["edge_voice"] == "zh-CN-XiaoxiaoNeural"
    assert sent.kwargs["json"]["rate"] == 1.15
    assert "voice" not in sent.kwargs["json"]
    assert sent.kwargs["headers"]["Authorization"] == "Bearer market-token"


def test_platform_edge_audio_does_not_replace_local_fallback(client, monkeypatch):
    response = httpx.Response(
        200,
        content=b"edge-from-platform",
        headers={"content-type": "audio/mpeg", "x-tts-provider": "edge"},
    )
    client_cm = MagicMock()
    client_cm.__enter__.return_value = client_cm
    client_cm.__exit__.return_value = False
    client_cm.post.return_value = response
    monkeypatch.setattr(ai_assistant_tts, "_session_market_token", lambda request: "market-token")
    monkeypatch.setattr(tts_service, "_run_edge_sync", lambda req: b"local-edge")
    with patch("httpx.Client", return_value=client_cm):
        result = client.post("/api/tts", json={"text": "hello"})
    assert result.status_code == 200
    assert result.json()["data"]["provider"] == "edge"
    assert base64.b64decode(result.json()["data"]["audioBase64"].split(",", 1)[1]) == b"local-edge"


def test_mimo_internal_error_does_not_fall_back(client, monkeypatch):
    monkeypatch.setattr(mimo_tts_service, "is_configured", lambda: True)
    monkeypatch.setattr(
        mimo_tts_service, "synthesize_mimo_bytes", MagicMock(side_effect=ValueError("internal bug"))
    )
    edge = MagicMock(return_value=b"audio")
    monkeypatch.setattr(tts_service, "_run_edge_sync", edge)
    assert client.post("/api/tts", json={"text": "hello"}).status_code == 500
    edge.assert_not_called()


def test_edge_sdk_no_audio_is_502(client, monkeypatch):
    from edge_tts.exceptions import NoAudioReceived

    monkeypatch.setattr(
        tts_service, "_run_edge_sync", MagicMock(side_effect=NoAudioReceived("empty"))
    )
    assert client.post("/api/tts", json={"text": "hello"}).status_code == 502


@pytest.mark.parametrize("value", ["+999999%", "+9999999999999999999999999999999999999999%"])
def test_out_of_range_rate_is_rejected_before_warmup(client, monkeypatch, value):
    warmup = MagicMock()
    monkeypatch.setattr(tts_facade, "trigger_common_tts_warmup", warmup)
    assert client.post("/api/tts", json={"text": "hello", "rate": value}).status_code == 422
    warmup.assert_not_called()
