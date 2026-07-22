from __future__ import annotations

import pytest

from modstore_server import llm_catalog
from modstore_server.infrastructure import http_clients


class _Response:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _Client:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    async def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        payload = self.payload(url, kwargs) if callable(self.payload) else self.payload
        return _Response(payload)


@pytest.mark.asyncio
async def test_openrouter_requests_all_output_modalities_and_keeps_metadata(
    monkeypatch,
):
    def payload(url, _kwargs):
        if url.endswith("/videos/models"):
            return {"data": [{"id": "vendor/video-model", "name": "Video Model"}]}
        return {
            "data": [
                {
                    "id": "vendor/audio-model",
                    "architecture": {
                        "input_modalities": ["text"],
                        "output_modalities": ["audio"],
                    },
                    "supported_voices": ["voice-a"],
                }
            ]
        }

    client = _Client(payload)
    monkeypatch.setattr(http_clients, "get_external_client", lambda: client)

    records, error = await llm_catalog._fetch_openai_compatible_records(
        "https://openrouter.ai/api/v1",
        "secret",
        provider="openrouter",
    )

    assert error is None
    records_by_id = {row["id"]: row for row in records}
    assert records_by_id["vendor/audio-model"]["architecture"]["output_modalities"] == [
        "audio"
    ]
    assert records_by_id["vendor/video-model"]["architecture"]["output_modalities"] == [
        "video"
    ]
    assert client.calls[0][1]["params"] == {"output_modalities": "all"}
    assert client.calls[1][0].endswith("/videos/models")


@pytest.mark.asyncio
async def test_google_keeps_supported_generation_methods_and_embedding_models(
    monkeypatch,
):
    client = _Client(
        {
            "models": [
                {
                    "name": "models/text-embedding-future",
                    "displayName": "Future Embedding",
                    "supportedGenerationMethods": ["embedContent"],
                    "inputTokenLimit": 2048,
                }
            ]
        }
    )
    monkeypatch.setattr(http_clients, "get_external_client", lambda: client)

    records, error = await llm_catalog._fetch_google_records("secret")

    assert error is None
    assert records[0]["id"] == "text-embedding-future"
    assert records[0]["supportedGenerationMethods"] == ["embedContent"]


def test_detailed_catalog_prefers_remote_metadata_over_fallback():
    rows = llm_catalog._models_detailed(
        "dashscope",
        ["qwen-max"],
        [
            {
                "id": "qwen-max",
                "type": "chat",
                "display_name": "Qwen Max Dynamic",
                "context_length": 131072,
            }
        ],
    )

    assert rows[0]["display_name"] == "Qwen Max Dynamic"
    assert rows[0]["provider_metadata"]["context_window"] == 131072
    assert rows[0]["capability_source"] == "provider_metadata"
    assert rows[0]["runtime_selectable"] is True


def test_together_top_level_array_response_is_supported():
    items = llm_catalog._openai_style_items(
        [{"id": "vendor/chat", "type": "chat", "display_name": "Vendor Chat"}]
    )

    assert items == [
        {"id": "vendor/chat", "type": "chat", "display_name": "Vendor Chat"}
    ]


@pytest.mark.asyncio
async def test_siliconflow_type_filters_become_declared_capabilities(monkeypatch):
    def payload(_url, kwargs):
        model_type = (kwargs.get("params") or {}).get("type")
        if not model_type:
            return {"data": []}
        return {"data": [{"id": f"vendor/{model_type}-model"}]}

    client = _Client(payload)
    monkeypatch.setattr(http_clients, "get_external_client", lambda: client)

    records, error = await llm_catalog._fetch_openai_compatible_records(
        "https://api.siliconflow.cn/v1",
        "secret",
        provider="siliconflow",
    )

    assert error is None
    assert {row["type"] for row in records} == {"text", "image", "audio", "video"}
    detailed = llm_catalog._models_detailed(
        "siliconflow", [row["id"] for row in records], records
    )
    by_category = {row["category"]: row for row in detailed}
    assert by_category["image"]["capability_source"] == "provider_metadata"
    assert by_category["video"]["runtime_selectable"] is False


def test_runtime_model_list_excludes_media_models():
    detailed = llm_catalog._models_detailed(
        "openai", ["gpt-4o", "gpt-4o-mini-tts", "sora-2"]
    )

    assert llm_catalog._runtime_model_ids(detailed) == ["gpt-4o"]
