from __future__ import annotations

import asyncio
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


@pytest.mark.parametrize("asynchronous", [False, True])
async def test_mimo_long_text_is_not_silently_truncated(monkeypatch, asynchronous):
    monkeypatch.setenv("MIMO_API_KEY", "test-key")
    requests = []
    transport = httpx.MockTransport(lambda request: requests.append(request) or httpx.Response(500))
    if asynchronous:
        client = httpx.AsyncClient(transport=transport)
        monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client)
        audio, error, _ = await mimo_tts_service.synthesize_mimo_tts_async("长" * 4001)
    else:
        client = httpx.Client(transport=transport)
        monkeypatch.setattr(httpx, "Client", lambda **kwargs: client)
        audio, error, _ = mimo_tts_service.synthesize_mimo_tts("长" * 4001)
    assert audio is None
    assert error
    assert not requests


async def test_edge_warmup_caches_complete_audio(monkeypatch):
    class Communication:
        async def stream(self):
            yield {"type": "audio", "data": b"first"}
            yield {"type": "audio", "data": b"second"}

    class Backend:
        def Communicate(self, *args, **kwargs):
            return Communication()

    monkeypatch.setattr(edge_tts_service, "_EDGE_TTS", Backend())
    monkeypatch.setattr(edge_tts_service, "_warmed_keys", set())
    monkeypatch.setattr(edge_tts_service, "_cache", edge_tts_service.OrderedDict())
    await edge_tts_service.warm_voice("voice", "+0%")
    assert edge_tts_service.get_cached(edge_tts_service.WARMUP_TEXT, "voice", "+0%") == b"firstsecond"


async def test_edge_warmup_failure_does_not_cache_partial_audio(monkeypatch):
    class Communication:
        async def stream(self):
            yield {"type": "audio", "data": b"partial"}
            raise TimeoutError()

    class Backend:
        def Communicate(self, *args, **kwargs):
            return Communication()

    monkeypatch.setattr(edge_tts_service, "_EDGE_TTS", Backend())
    monkeypatch.setattr(edge_tts_service, "_warmed_keys", set())
    monkeypatch.setattr(edge_tts_service, "_cache", edge_tts_service.OrderedDict())
    await edge_tts_service.warm_voice("voice", "+0%")
    assert edge_tts_service.get_cached(edge_tts_service.WARMUP_TEXT, "voice", "+0%") is None
    assert ("voice", "+0%") not in edge_tts_service._warmed_keys


async def test_edge_overall_deadline_includes_preparation_and_queue(monkeypatch):
    class Communication:
        async def stream(self):
            yield {"type": "audio", "data": b"audio"}

    class Backend:
        def Communicate(self, *args, **kwargs):
            return Communication()

    async def warm(*args):
        await asyncio.sleep(0.12)

    monkeypatch.setattr(edge_tts_service, "_EDGE_TTS", Backend())
    monkeypatch.setattr(edge_tts_service, "warm_voice", warm)
    monkeypatch.setattr(edge_tts_service, "_UPSTREAM_TIMEOUT_S", 0.04)
    with pytest.raises(TimeoutError):
        async for _ in edge_tts_service.stream_audio("queued", "voice", "+0%"):
            pass


async def test_edge_deadline_does_not_cancel_consumer_after_yield(monkeypatch):
    class Communication:
        async def stream(self):
            yield {"type": "audio", "data": b"audio"}
            await asyncio.sleep(0.01)

    class Backend:
        def Communicate(self, *args, **kwargs):
            return Communication()

    monkeypatch.setattr(edge_tts_service, "_EDGE_TTS", Backend())
    monkeypatch.setattr(edge_tts_service, "_UPSTREAM_TIMEOUT_S", 0.03)
    monkeypatch.setattr(edge_tts_service, "_warmed_keys", {("voice", "+0%")})
    stream = edge_tts_service.stream_audio("slow consumer", "voice", "+0%")
    assert await anext(stream) == b"audio"
    await asyncio.sleep(0.06)
    with pytest.raises(TimeoutError):
        await anext(stream)


async def test_edge_overall_deadline_stops_slow_stream(monkeypatch):
    class Communication:
        async def stream(self):
            for _ in range(5):
                await asyncio.sleep(0.02)
                yield {"type": "audio", "data": b"chunk"}

    class Backend:
        def Communicate(self, *args, **kwargs):
            return Communication()

    monkeypatch.setattr(edge_tts_service, "_EDGE_TTS", Backend())
    monkeypatch.setattr(edge_tts_service, "_UPSTREAM_TIMEOUT_S", 0.06, raising=False)
    monkeypatch.setattr(edge_tts_service, "_warmed_keys", {("voice", "+0%")})
    with pytest.raises(TimeoutError):
        async for _ in edge_tts_service.stream_audio("deadline", "voice", "+0%"):
            pass


async def test_mimo_async_overall_deadline(monkeypatch):
    monkeypatch.setenv("MIMO_API_KEY", "test-key")

    async def delayed(request):
        await asyncio.sleep(0.2)
        return httpx.Response(200)

    client = httpx.AsyncClient(transport=httpx.MockTransport(delayed))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client)
    audio, error, meta = await mimo_tts_service.synthesize_mimo_tts_async("hello", timeout_s=0.03)
    assert audio is None
    assert error
    assert meta["status"] == 504


@pytest.mark.parametrize("path", ["/tts", "/edge"])
def test_nonstreaming_endpoints_report_late_upstream_failure(monkeypatch, path):
    app = FastAPI()
    ports = speech_api.SpeechPorts(edge=object())

    @app.post("/tts")
    async def unified(body: WorkbenchUnifiedTtsBody):
        return await speech_api.workbench_unified_tts(body, None, ports=ports)

    @app.post("/edge")
    async def edge(body: WorkbenchEdgeTtsBody):
        return await speech_api.workbench_edge_tts(body, None, ports=ports)

    monkeypatch.setattr(
        mimo_tts_service,
        "synthesize_mimo_tts_async",
        AsyncMock(return_value=(None, "unavailable", {})),
    )

    async def interrupted(*args):
        yield b"partial"
        raise TimeoutError()

    monkeypatch.setattr(speech_api, "_edge_tts_stream_chunks", interrupted)
    response = TestClient(app, raise_server_exceptions=False).post(path, json={"text": "hello"})
    assert response.status_code == 504


def test_long_unified_request_falls_back_to_edge(monkeypatch):
    app = FastAPI()
    ports = speech_api.SpeechPorts(edge=object())

    @app.post("/tts")
    async def unified(body: WorkbenchUnifiedTtsBody):
        return await speech_api.workbench_unified_tts(body, None, ports=ports)

    monkeypatch.setenv("MIMO_API_KEY", "test-key")
    seen = []

    async def edge(text, *args):
        seen.append(text)
        yield b"complete"

    monkeypatch.setattr(speech_api, "_edge_tts_stream_chunks", edge)
    response = TestClient(app, raise_server_exceptions=False).post("/tts", json={"text": "长" * 4001})
    assert response.status_code == 200
    assert response.content == b"complete"
    assert seen == ["长" * 4001]
