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
    assert records_by_id["vendor/audio-model"]["architecture"]["output_modalities"] == ["audio"]
    assert records_by_id["vendor/video-model"]["architecture"]["output_modalities"] == ["video"]
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

    assert items == [{"id": "vendor/chat", "type": "chat", "display_name": "Vendor Chat"}]


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
    detailed = llm_catalog._models_detailed("siliconflow", [row["id"] for row in records], records)
    by_category = {row["category"]: row for row in detailed}
    assert by_category["image"]["capability_source"] == "provider_metadata"
    assert by_category["video"]["runtime_selectable"] is False


def test_runtime_model_list_excludes_media_models():
    detailed = llm_catalog._models_detailed("openai", ["gpt-4o", "gpt-4o-mini-tts", "sora-2"])

    assert llm_catalog._runtime_model_ids(detailed) == ["gpt-4o"]


@pytest.mark.asyncio
async def test_gateway_alias_limits_use_all_visible_deployments_and_hide_credentials(monkeypatch):
    import json

    from modstore_server import llm_litellm_router

    monkeypatch.setattr(llm_litellm_router, "model_limits", lambda *_: {})

    def deployment(alias, input_limit, model="openai/endpoint-code"):
        return {
            "model_name": alias,
            "litellm_params": {"model": model, "api_key": "secret", "api_base": "private"},
            "model_info": {"max_input_tokens": input_limit, "max_output_tokens": 4096},
        }

    def payload(url, _kwargs):
        if url.endswith("/model/info"):
            return {
                "data": [
                    deployment("code-alias", 131072),
                    deployment("code-alias", 65536),
                    deployment("unknown-alias", 131072),
                    deployment("unknown-alias", None, "other/model"),
                    deployment("invisible-alias", 999999),
                    {"model_name": {"invalid": True}},
                ]
            }
        return {"data": [{"id": "code-alias"}, {"id": "unknown-alias"}]}

    client = _Client(payload)
    monkeypatch.setattr(http_clients, "get_external_client", lambda: client)
    records, error = await llm_catalog._fetch_openai_compatible_records(
        "https://gateway.example/prefix/v1", "catalog-key", provider="litellm"
    )
    assert error is None
    detailed = llm_catalog._models_detailed("litellm", [row["id"] for row in records], records)
    by_id = {row["id"]: row["model_capabilities"] for row in detailed}
    assert by_id["code-alias"] == {
        "max_input_tokens": 65536,
        "max_output_tokens": 4096,
        "resolved_model": "openai/endpoint-code",
        "source": "litellm_model_info",
    }
    assert by_id["unknown-alias"] == {"max_output_tokens": 4096, "source": "litellm_model_info"}
    assert "invisible-alias" not in by_id
    assert client.calls[1][0] == "https://gateway.example/prefix/model/info"
    assert client.calls[1][1]["headers"] == {"Authorization": "Bearer catalog-key"}
    assert "secret" not in json.dumps(detailed) and "api_base" not in json.dumps(detailed)


@pytest.mark.asyncio
async def test_unavailable_gateway_model_info_preserves_declared_models_metadata(monkeypatch):
    import httpx

    def payload(url, _kwargs):
        if url.endswith("/model/info"):
            raise httpx.HTTPStatusError(
                "unavailable", request=httpx.Request("GET", url), response=httpx.Response(403)
            )
        return {"data": [{"id": "code-alias", "max_input_tokens": 65536}]}

    client = _Client(payload)
    monkeypatch.setattr(http_clients, "get_external_client", lambda: client)
    records, error = await llm_catalog._fetch_openai_compatible_records(
        "https://gateway.example/v1", "catalog-key", provider="litellm"
    )
    assert error is None and records[0]["max_input_tokens"] == 65536


@pytest.mark.asyncio
async def test_missing_deployment_limit_stays_unknown_even_for_a_known_shared_base_model(
    monkeypatch,
):
    from modstore_server import llm_litellm_router

    monkeypatch.setenv("LITELLM_LOCAL_MODEL_COST_MAP", "True")
    litellm = pytest.importorskip("litellm")
    monkeypatch.setattr(llm_litellm_router, "_load_litellm", lambda: litellm)
    assert llm_litellm_router.model_limits("openai", "gpt-4o")["max_input_tokens"] > 4096

    def payload(url, _kwargs):
        if url.endswith("/model/info"):
            return {
                "data": [
                    {
                        "model_name": "code-alias",
                        "litellm_params": {"model": "openai/gpt-4o"},
                        "model_info": info,
                    }
                    for info in (
                        {"max_input_tokens": 4096, "max_output_tokens": 2048},
                        {"max_output_tokens": 2048},
                    )
                ]
            }
        return {"data": [{"id": "code-alias", "resolved_model": "openai/gpt-4o"}]}

    monkeypatch.setattr(http_clients, "get_external_client", lambda: _Client(payload))
    records, error = await llm_catalog._fetch_openai_compatible_records(
        "https://gateway.example/v1", "catalog-key", provider="litellm"
    )
    assert error is None
    detailed = llm_catalog._models_detailed("litellm", ["code-alias"], records)
    assert detailed[0]["model_capabilities"] == {
        "max_output_tokens": 2048,
        "source": "litellm_model_info",
    }
    assert "max_input_tokens" not in detailed[0]["provider_metadata"]
    assert "resolved_model" not in detailed[0]["provider_metadata"]


@pytest.mark.asyncio
@pytest.mark.parametrize("nested", [False, True])
async def test_models_smaller_capacity_is_preserved_when_model_info_is_larger(monkeypatch, nested):
    small = {"context_window": 8192, "max_input_tokens": 4096, "max_output_tokens": 2048}

    def payload(url, _kwargs):
        if url.endswith("/model/info"):
            return {
                "data": [
                    {
                        "model_name": "code-alias",
                        "litellm_params": {"model": "openai/gpt-4o"},
                        "model_info": {
                            "context_window": 128000,
                            "max_input_tokens": 126000,
                            "max_output_tokens": 8192,
                        },
                    }
                ]
            }
        return {
            "data": [{"id": "code-alias", **({"model_capabilities": small} if nested else small)}]
        }

    monkeypatch.setattr(http_clients, "get_external_client", lambda: _Client(payload))
    records, error = await llm_catalog._fetch_openai_compatible_records(
        "https://gateway.example/v1", "catalog-key", provider="litellm"
    )
    assert error is None
    detailed = llm_catalog._models_detailed("litellm", ["code-alias"], records)
    assert detailed[0]["model_capabilities"] == {
        **small,
        "resolved_model": "openai/gpt-4o",
        "source": "litellm_model_info",
    }


@pytest.mark.asyncio
async def test_model_capability_cache_is_scoped_to_account_endpoint_and_operation(monkeypatch):
    llm_catalog.clear_all_catalog_cache()
    calls = []

    async def fetch(base_url, _key, **_kwargs):
        calls.append(base_url)
        return (
            [{"id": "code-alias", "max_input_tokens": 65536 if "/a/" in base_url else 4096}],
            None,
        )

    monkeypatch.setattr(llm_catalog, "_fetch_openai_compatible_records", fetch)
    for user, base, discover in [(1, "a", False), (2, "a", False), (1, "b", False), (1, "b", True)]:
        block = await llm_catalog.get_models_for_credentials(
            user,
            "litellm",
            api_key="same-key",
            base_url=f"https://gateway.example/{base}/v1",
            discover_operations=discover,
        )
        assert block["models_detailed"][0]["model_capabilities"]["max_input_tokens"] == (
            65536 if base == "a" else 4096
        )
    assert len(calls) == 4
    await llm_catalog.get_models_for_credentials(
        1,
        "litellm",
        api_key="same-key",
        base_url="https://gateway.example/b/v1",
        discover_operations=True,
    )
    assert len(calls) == 4
    llm_catalog.clear_all_catalog_cache()
