import json
from contextlib import asynccontextmanager

import httpx
import pytest

from modstore_server import llm_media_proxy as media


@pytest.mark.asyncio
async def test_image_stream_stops_before_unbounded_provider_body(monkeypatch):
    consumed = []

    class Response:
        status_code = 200

        async def aiter_bytes(self):
            for chunk in (b"a" * 8, b"b" * 8, b"never"):
                consumed.append(chunk)
                yield chunk

    @asynccontextmanager
    async def response(*args, **kwargs):
        assert kwargs["stream"] is True
        yield Response()

    monkeypatch.setattr(media, "llm_http_response", response)
    monkeypatch.setattr(media, "_MAX_IMAGE_RESPONSE_BYTES", 12)
    with pytest.raises(httpx.RequestError, match="超过允许大小"):
        await media.image_openai_compatible("https://example.test", "secret", "model", "prompt")
    assert consumed == [b"a" * 8, b"b" * 8]


@pytest.mark.asyncio
async def test_image_response_rejects_extra_images_and_accepts_requested_count(monkeypatch):
    payload = {"data": [{"b64_json": "AA=="}, {"b64_json": "AA=="}]}

    class Response:
        status_code = 200

        async def aiter_bytes(self):
            yield json.dumps(payload).encode()

    @asynccontextmanager
    async def response(*args, **kwargs):
        yield Response()

    monkeypatch.setattr(media, "llm_http_response", response)
    rejected = await media.image_openai_compatible(
        "https://example.test", "secret", "model", "prompt", n=1
    )
    assert rejected["ok"] is False
    accepted = await media.image_openai_compatible(
        "https://example.test", "secret", "model", "prompt", n=2
    )
    assert accepted["images"] == ["data:image/png;base64,AA=="] * 2
