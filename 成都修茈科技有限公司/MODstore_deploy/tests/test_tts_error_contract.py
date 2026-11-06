from __future__ import annotations

import base64
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from modstore_server import edge_tts_service, mimo_tts_service
from modstore_server.workbench import speech_api
from modstore_server.workbench.schemas import (
    WorkbenchEdgeTtsBody,
    WorkbenchUnifiedTtsBody,
)


@pytest.fixture
def client(monkeypatch):
    app = FastAPI()
    ports = speech_api.SpeechPorts(edge=object())

    @app.post("/tts")
    async def unified(body: WorkbenchUnifiedTtsBody):
        return await speech_api.workbench_unified_tts(body, None, ports=ports)

    @app.post("/edge")
    async def edge(body: WorkbenchEdgeTtsBody):
        return await speech_api.workbench_edge_tts(body, None, ports=ports)

    @app.post("/edge/stream")
    async def edge_stream(body: WorkbenchEdgeTtsBody):
        return await speech_api.workbench_edge_tts_stream(body, None, ports=ports)

    monkeypatch.setattr(
        mimo_tts_service,
        "synthesize_mimo_tts_async",
        AsyncMock(return_value=(None, "unavailable", {})),
    )
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize("path", ["/tts", "/edge", "/edge/stream"])
@pytest.mark.parametrize("body", [{"text": "   "}, {"text": "hello", "rate": "NaN"}])
def test_invalid_parameters_are_422(client, path, body):
    assert client.post(path, json=body).status_code == 422


@pytest.mark.parametrize("path", ["/tts", "/edge", "/edge/stream"])
@pytest.mark.parametrize(
    "error,status",
    [
        (TimeoutError(), 504),
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
        (httpx.ConnectError("network"), 502),
        (ValueError("internal bug"), 500),
    ],
)
def test_provider_failure_status_before_audio(client, monkeypatch, path, error, status):
    async def fail(*args):
        raise error
        yield b""

    monkeypatch.setattr(speech_api, "_edge_tts_stream_chunks", fail)
    assert client.post(path, json={"text": "hello"}).status_code == status


@pytest.mark.parametrize("path", ["/tts", "/edge", "/edge/stream"])
def test_empty_provider_audio_is_502(client, monkeypatch, path):
    async def empty(*args):
        if False:
            yield b""

    monkeypatch.setattr(speech_api, "_edge_tts_stream_chunks", empty)
    assert client.post(path, json={"text": "hello"}).status_code == 502


def test_mimo_failure_falls_back_to_edge(client, monkeypatch):
    async def stream(*args):
        yield b"audio"

    monkeypatch.setattr(speech_api, "_edge_tts_stream_chunks", stream)
    response = client.post("/tts", json={"text": "hello"})
    assert response.status_code == 200
    assert response.content == b"audio"
    assert response.headers["x-tts-provider"] == "edge"


def test_internal_mimo_bug_is_not_hidden_by_fallback(client, monkeypatch):
    monkeypatch.setattr(
        mimo_tts_service,
        "synthesize_mimo_tts_async",
        AsyncMock(side_effect=ValueError("internal bug")),
    )
    assert client.post("/tts", json={"text": "hello"}).status_code == 500


@pytest.mark.parametrize(
    "data",
    [None, [], {"choices": [None]}, {"choices": [{"message": {"audio": {"data": "YWJj!!!!"}}}]}],
)
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_mimo_malformed_response_is_rejected(monkeypatch, data, asynchronous):
    monkeypatch.setenv("MIMO_API_KEY", "test-key")
    response = httpx.Response(200, json=data)
    transport = httpx.MockTransport(lambda request: response)
    if asynchronous:
        client = httpx.AsyncClient(transport=transport)
        monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client)
        audio, error, _ = await mimo_tts_service.synthesize_mimo_tts_async("hello")
    else:
        client = httpx.Client(transport=transport)
        monkeypatch.setattr(httpx, "Client", lambda **kwargs: client)
        audio, error, _ = mimo_tts_service.synthesize_mimo_tts("hello")
    assert audio is None
    assert error


async def test_mimo_internal_bug_propagates(monkeypatch):
    monkeypatch.setenv("MIMO_API_KEY", "test-key")
    transport = httpx.MockTransport(
        lambda request: (_ for _ in ()).throw(ValueError("internal bug"))
    )
    client = httpx.AsyncClient(transport=transport)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client)
    with pytest.raises(ValueError, match="internal bug"):
        await mimo_tts_service.synthesize_mimo_tts_async("hello")


async def test_mimo_valid_audio_async(monkeypatch):
    monkeypatch.setenv("MIMO_API_KEY", "test-key")
    payload = {"choices": [{"message": {"audio": {"data": base64.b64encode(b"audio").decode()}}}]}
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    )
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client)
    audio, error, _ = await mimo_tts_service.synthesize_mimo_tts_async("hello")
    assert audio == b"audio"
    assert not error


@pytest.mark.parametrize("path", ["/tts", "/edge", "/edge/stream"])
def test_malformed_edge_audio_is_502(client, monkeypatch, path):
    async def stream(*args):
        yield "invalid"

    monkeypatch.setattr(speech_api, "_edge_tts_stream_chunks", stream)
    assert client.post(path, json={"text": "hello"}).status_code == 502


@pytest.mark.parametrize("path", ["/edge", "/edge/stream"])
def test_edge_stream_keeps_first_and_following_chunks(client, monkeypatch, path):
    async def stream(*args):
        yield b"first"
        yield b"second"

    monkeypatch.setattr(speech_api, "_edge_tts_stream_chunks", stream)
    response = client.post(path, json={"text": "hello"})
    assert response.status_code == 200
    assert response.content == b"firstsecond"


@pytest.mark.parametrize("asynchronous", [False, True])
async def test_mimo_invalid_json_is_rejected(monkeypatch, asynchronous):
    monkeypatch.setenv("MIMO_API_KEY", "test-key")
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=b"not json"))
    if asynchronous:
        client = httpx.AsyncClient(transport=transport)
        monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client)
        audio, error, _ = await mimo_tts_service.synthesize_mimo_tts_async("hello")
    else:
        client = httpx.Client(transport=transport)
        monkeypatch.setattr(httpx, "Client", lambda **kwargs: client)
        audio, error, _ = mimo_tts_service.synthesize_mimo_tts("hello")
    assert audio is None
    assert error


def test_corp_empty_text_is_422(monkeypatch):
    from modstore_server import agent_butler_api as corp

    monkeypatch.setattr(corp, "_corp_chat_rate_allow", lambda *args: None)
    monkeypatch.setattr(corp, "_public_contact_client_key", lambda *args: "test")
    app = FastAPI()
    app.post("/corp")(corp.butler_corp_tts)
    assert (
        TestClient(app, raise_server_exceptions=False)
        .post("/corp", json={"text": "  "})
        .status_code
        == 422
    )


@pytest.mark.parametrize(
    "error,status",
    [
        (TimeoutError(), 504),
        (httpx.ConnectError("network"), 502),
        (ValueError("internal bug"), 500),
    ],
)
def test_corp_edge_failure_classification(monkeypatch, error, status):
    from modstore_server import agent_butler_api as corp

    monkeypatch.setattr(corp, "_corp_chat_rate_allow", lambda *args: None)
    monkeypatch.setattr(corp, "_public_contact_client_key", lambda *args: "test")
    monkeypatch.setattr(
        mimo_tts_service,
        "synthesize_mimo_tts_async",
        AsyncMock(return_value=(None, "unavailable", {})),
    )
    monkeypatch.setattr(edge_tts_service, "is_available", lambda: True)

    async def fail(*args):
        raise error
        yield b""

    monkeypatch.setattr(edge_tts_service, "stream_audio", fail)
    app = FastAPI()
    app.post("/corp")(corp.butler_corp_tts)
    assert (
        TestClient(app, raise_server_exceptions=False)
        .post("/corp", json={"text": "hello"})
        .status_code
        == status
    )


def test_mimo_transport_failure_without_edge_returns_504(monkeypatch):
    app = FastAPI()

    @app.post("/tts")
    async def unified(body: WorkbenchUnifiedTtsBody):
        return await speech_api.workbench_unified_tts(
            body, None, ports=speech_api.SpeechPorts(edge=None)
        )

    monkeypatch.setenv("MIMO_API_KEY", "test-key")
    transport = httpx.MockTransport(
        lambda request: (_ for _ in ()).throw(httpx.ReadTimeout("timeout"))
    )
    upstream = httpx.AsyncClient(transport=transport)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: upstream)
    assert (
        TestClient(app, raise_server_exceptions=False)
        .post("/tts", json={"text": "hello"})
        .status_code
        == 504
    )


async def test_edge_service_rejects_invalid_audio_before_buffering(monkeypatch):
    class Communication:
        async def stream(self):
            yield {"type": "audio", "data": "invalid"}

    class Backend:
        def Communicate(self, *args, **kwargs):
            return Communication()

    async def warm(*args):
        return None

    monkeypatch.setattr(edge_tts_service, "_EDGE_TTS", Backend())
    monkeypatch.setattr(edge_tts_service, "warm_voice", warm)
    with pytest.raises(speech_api.HTTPException) as error:
        async for _ in edge_tts_service.stream_audio("hello-invalid", "voice", "+0%"):
            pass
    assert error.value.status_code == 502
