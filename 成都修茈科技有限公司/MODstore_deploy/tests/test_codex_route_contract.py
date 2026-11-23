"""Runtime configuration is derived from the original account selection."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import HTTPException

from modstore_server import llm_api, llm_catalog, llm_catalog_merged
from modstore_server.llm_crypto import encrypt_secret
from modstore_server.llm_gateway_contract import codex_deployment_identity
from modstore_server.llm_key_resolver import read_chat_route_token
from modstore_server.models import User, UserLlmCredential
from tests.platform_model_support import database as database
from tests.platform_model_support import isolated as isolated
from tests.platform_model_support import save
from tests.test_openai_responses import CAPABILITIES


async def test_gateway_resolver_seals_exact_runtime_identity_capacity_and_credentials(
    database, monkeypatch
):
    monkeypatch.setenv("LITELLM_MASTER_KEY", "server-only-key")
    monkeypatch.setattr(
        llm_catalog,
        "get_models_for_credentials",
        AsyncMock(
            return_value={
                "runtime_models": ["account-model"],
                "models_detailed": [{"id": "account-model", "model_capabilities": CAPABILITIES}],
            }
        ),
    )
    result = await llm_api.resolve_default_llm_route(database, 1, runtime="codex")
    assert result["provider"] == "litellm" and result["model"] == "account-model"
    assert result["runtime"]["response_model"] == "deepseek-chat"
    assert (
        result["runtime"]["gateway_kind"] == "market"
        and result["runtime"]["upstream_vendor"] == "deepseek"
    )
    assert result["runtime"]["qualification"] == {"state": "requires_local_qualification"}
    assert "server-only-key" not in json.dumps(result)
    sealed = read_chat_route_token(result["route_token"], 1, "litellm", "account-model")
    assert sealed.runtime_contract == {
        "runtime": result["runtime"],
        "model_capabilities": result["model_capabilities"],
    }
    with pytest.raises(HTTPException):
        read_chat_route_token(result["route_token"], 2, "litellm", "account-model")


@pytest.mark.parametrize("byok", [False, True])
async def test_existing_mimo_default_keeps_user_source_and_uses_shipped_declared_capacity(
    database, monkeypatch, byok
):
    save("xiaomi", model="mimo-v2.6-flash", base_url="https://token-plan-cn.xiaomimimo.com/v1")
    user = database.query(User).filter_by(id=1).one()
    user.default_llm_json = json.dumps(
        {"mode": "byok" if byok else "explicit", "provider": "xiaomi", "model": "mimo-v2.6-flash"}
    )
    if byok:
        database.add(
            UserLlmCredential(
                user_id=1, provider="xiaomi", api_key_encrypted=encrypt_secret("personal-test-key")
            )
        )
    database.commit()
    catalog = AsyncMock(return_value={"models_detailed": []})
    monkeypatch.setattr(llm_catalog, "get_models_for_credentials", catalog)
    result = await llm_api.resolve_default_llm_route(database, 1, runtime="codex")
    assert result["provider"] == "xiaomi" and result["model"] == "mimo-v2.6-flash"
    assert result["key_source"] == ("user_override" if byok else "platform")
    assert result["model_capabilities"]["context_window"] == 1_000_000
    assert result["model_capabilities"]["max_output_tokens"] == 128_000
    assert result["runtime"]["upstream_vendor"] == "xiaomi"
    assert result["runtime"]["response_model"] == "mimo-v2.6-flash"
    assert [call.args[1] for call in catalog.await_args_list] == ["xiaomi"]


async def test_incompatible_explicit_byok_never_changes_to_platform_gateway(database, monkeypatch):
    monkeypatch.setenv("LITELLM_MASTER_KEY", "available-platform-key")
    database.add(
        UserLlmCredential(
            user_id=1, provider="anthropic", api_key_encrypted=encrypt_secret("personal-test-key")
        )
    )
    database.query(User).filter_by(id=1).one().default_llm_json = json.dumps(
        {"mode": "byok", "provider": "anthropic", "model": "claude-test-model"}
    )
    database.commit()
    catalog = AsyncMock(return_value={"models_detailed": []})
    monkeypatch.setattr(llm_catalog, "get_models_for_credentials", catalog)
    with pytest.raises(HTTPException) as error:
        await llm_api.resolve_default_llm_route(database, 1, runtime="codex")
    assert error.value.detail["code"] == "CODEX_MODEL_UNSUPPORTED"
    assert [call.args[1] for call in catalog.await_args_list] == ["anthropic"]


async def test_missing_alias_context_stays_unknown_even_for_a_known_mimo_deployment(
    database, monkeypatch
):
    monkeypatch.setenv("LITELLM_MASTER_KEY", "server-only-key")
    caps = {
        **CAPABILITIES,
        "resolved_model": "xiaomi_mimo/mimo-v2.6-flash",
        "upstream_vendor": "xiaomi",
        "response_model": "mimo-v2.6-flash",
    }
    caps.pop("context_window")
    monkeypatch.setattr(
        llm_catalog,
        "get_models_for_credentials",
        AsyncMock(
            return_value={
                "runtime_models": ["alias"],
                "models_detailed": [{"id": "alias", "model_capabilities": caps}],
            }
        ),
    )
    with pytest.raises(HTTPException) as error:
        await llm_api.resolve_default_llm_route(database, 1, runtime="codex")
    assert error.value.detail["code"] == "CODEX_MODEL_CAPACITY_REQUIRED"


async def test_real_gateway_metadata_projection_is_secret_free_and_requires_unanimous_identity():
    items = [{"id": "alias"}]
    rows = [
        {
            "model_name": "alias",
            "litellm_params": {
                "model": "openai/mimo-v2.6-flash",
                "api_key": "never-expose",
                "api_base": "https://token-plan-cn.xiaomimimo.com/v1",
            },
            "model_info": {
                "context_window": 1000000,
                "max_output_tokens": 128000,
                "upstream_vendor": "xiaomi",
            },
        }
    ]
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"data": rows}))
    ) as client:
        await llm_catalog_merged._litellm_deployment_capabilities(
            client, "https://gateway.example/v1", "gateway-key", items, 4
        )
        assert items[0]["model_capabilities"]["response_model"] == "mimo-v2.6-flash"
        assert "never-expose" not in json.dumps(items) and "api_base" not in json.dumps(items)
        rows.append({**rows[0], "litellm_params": {"model": "openai/another-model"}})
        await llm_catalog_merged._litellm_deployment_capabilities(
            client, "https://gateway.example/v1", "gateway-key", items, 4
        )
        assert "response_model" not in items[0]["model_capabilities"]


@pytest.mark.parametrize(
    "params",
    [
        {"model": "openai/gpt-test"},
        {"model": "openai/model", "api_base": "https://api.openai.com/v1"},
    ],
)
def test_compatible_transport_name_cannot_claim_independent_gateway_vendor(params):
    info = {} if "api_base" not in params else {"upstream_vendor": "declared-non-openai"}
    assert codex_deployment_identity(info, params) == {}


async def test_codex_platform_default_skips_first_model_without_proven_capacity(
    database, monkeypatch
):
    monkeypatch.setenv("LITELLM_MASTER_KEY", "server-only-key")
    stale = dict(CAPABILITIES)
    stale.pop("context_window")
    catalog = AsyncMock(
        return_value={
            "runtime_models": ["unqualified-alias", "qualified-alias"],
            "models_detailed": [
                {"id": "unqualified-alias", "model_capabilities": stale},
                {"id": "qualified-alias", "model_capabilities": CAPABILITIES},
            ],
        }
    )
    monkeypatch.setattr(llm_catalog, "get_models_for_credentials", catalog)
    result = await llm_api.resolve_default_llm_route(database, 1, runtime="codex")
    assert result["provider"] == "litellm"
    assert result["model"] == "qualified-alias"
    assert result["runtime"]["response_model"] == "deepseek-chat"

    # The ordinary chat default is unchanged, even when it does not qualify as Codex.
    normal = await llm_api.resolve_default_llm_route(database, 1)
    assert normal["model"] == "unqualified-alias"
