"""Catalog eligibility must agree with the original executor admission guards."""

import copy
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from modstore_server import llm_catalog_merged
from modstore_server.llm_gateway_contract import (
    codex_catalog_support,
    codex_route_contract,
)
from modstore_server.llm_key_resolver import chat_route_snapshot
from modstore_server.llm_responses_transport import validate_responses_route


def row():
    return {
        "id": "deepseek-chat",
        "runtime_selectable": True,
        "model_capabilities": {
            "context_window": 32000,
            "max_output_tokens": 4096,
            "source": "litellm_model_info",
            "upstream_vendor": "deepseek",
            "response_model": "deepseek-chat",
        },
    }


@pytest.mark.parametrize(
    "defect,code",
    [
        (None, "REQUIRES_QUALIFICATION"),
        ("capacity", "CODEX_MODEL_CAPACITY_REQUIRED"),
        ("identity", "CODEX_MODEL_METADATA_REQUIRED"),
        ("protocol", "CODEX_MODEL_UNSUPPORTED"),
        ("endpoint", "CODEX_MODEL_UNSUPPORTED"),
    ],
)
def test_catalog_and_save_apply_identical_guards(defect, code):
    item, provider, key, base = (
        row(),
        "litellm",
        "synthetic-private-key",
        "https://gateway.example/v1",
    )
    if defect == "capacity":
        item["model_capabilities"].pop("context_window")
    if defect == "identity":
        item["model_capabilities"].pop("upstream_vendor")
    if defect == "protocol":
        provider, key = "minimax", "sk-cp-synthetic-private-key"
    if defect == "endpoint":
        base = "https://api.openai.com/v1"
    before = copy.deepcopy(item)
    projected = codex_catalog_support(provider, item, key, base)
    assert projected["code"] == code
    assert item == before and key not in str(projected) and base not in str(projected)
    route = chat_route_snapshot(provider, item["id"], key, base, "platform", "explicit")
    if defect:
        with pytest.raises(HTTPException) as exc:
            validate_responses_route(route)
            codex_route_contract(provider, route.model, item["model_capabilities"])
        assert projected["selectable"] is False
        assert exc.value.detail["code"] == projected["code"]
    else:
        validate_responses_route(route)
        codex_route_contract(provider, route.model, item["model_capabilities"])
        assert projected["selectable"] is True


@pytest.mark.asyncio
async def test_projection_does_not_cache_one_credentials_protocol_in_another(
    monkeypatch,
):
    block = {"models_detailed": [row()], "runtime_models": ["deepseek-chat"]}
    original = copy.deepcopy(block)
    monkeypatch.setattr(
        llm_catalog_merged, "_get_models_for_credentials", AsyncMock(return_value=block)
    )
    blocked = await llm_catalog_merged.get_models_for_credentials(
        1,
        "minimax",
        api_key="sk-cp-private",
        base_url="https://api.minimax.io/anthropic",
    )
    allowed = await llm_catalog_merged.get_models_for_credentials(
        2, "minimax", api_key="sk-cp-private", base_url="https://api.minimax.io"
    )
    assert blocked["models_detailed"][0]["execution"]["selectable"] is False
    assert allowed["models_detailed"][0]["execution"] == {
        "selectable": True,
        "code": "REQUIRES_QUALIFICATION",
        "message": "需通过本机运行验收。",
        "protocol": "chat_completions",
    }
    assert original == block
    assert blocked["runtime_models"] == allowed["runtime_models"] == block["runtime_models"]
