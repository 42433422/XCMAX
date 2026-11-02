"""Platform-required routes preserve account choices and bind actual billed dispatch."""

import json
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from modstore_server import llm_key_resolver as keys
from modstore_server.llm_crypto import encrypt_secret
from tests.platform_model_support import (
    BASE,
    KEY,
    NEXT_KEY,
)
from tests.platform_model_support import database as database
from tests.platform_model_support import isolated as isolated
from tests.platform_model_support import (
    save,
)
from tests.platform_model_support import upstream as upstream


@pytest.fixture
def chat_client(database):
    from modstore_server import llm_api

    app = FastAPI()
    app.include_router(llm_api.router)
    app.dependency_overrides[llm_api.get_db] = lambda: database
    app.dependency_overrides[llm_api._get_current_user] = lambda: SimpleNamespace(id=1)
    with TestClient(app) as client:
        yield client


@pytest.mark.parametrize("mode", ["explicit", "byok"])
def test_platform_only_http_route_dispatches_bound_platform_key_without_changing_account(
    database, chat_client, upstream, monkeypatch, mode
):
    from modstore_server import llm_billed_chat, llm_billed_once
    from modstore_server.llm_billing_values import WalletHold
    from modstore_server.models import User, UserLlmCredential

    base = "https://token-plan-cn.xiaomimimo.com/v1"
    save("xiaomi", base_url=base, model="mimo-v2.6-flash")
    user = database.get(User, 1)
    user.default_llm_json = json.dumps(
        {"mode": mode, "provider": "xiaomi", "model": "mimo-v2.6-pro"}
    )
    credential = UserLlmCredential(
        user_id=1,
        provider="xiaomi",
        api_key_encrypted=encrypt_secret("synthetic-personal-key"),
        base_url_encrypted=encrypt_secret("https://personal.example.invalid/v1"),
    )
    database.add(credential)
    database.commit()
    before = (
        user.default_llm_json,
        credential.api_key_encrypted,
        credential.base_url_encrypted,
    )
    personal = chat_client.get("/api/llm/resolve-chat-default").json()
    assert personal["key_source"] == "user_override" and personal["model"] == "mimo-v2.6-pro"
    monkeypatch.setattr(keys, "resolve_credentials", Mock(side_effect=AssertionError("BYOK read")))
    response = chat_client.get("/api/llm/resolve-chat-default", params={"platform_only": "true"})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    route = response.json()
    assert route["key_source"] == "platform" and route["model"] == "mimo-v2.6-flash"
    assert route["recipient"]["id"] == "xiaomi-mimo-cn"
    assert route["route_token"] and route["config_revision"]
    save(
        "xiaomi",
        base_url=BASE,
        model="mimo-v2.6-pro",
        api_key=NEXT_KEY,
        expected_revision=route["config_revision"],
    )
    wallet = SimpleNamespace(
        preauthorize=AsyncMock(return_value=WalletHold("synthetic-hold", Decimal(".01"), True)),
        settle=AsyncMock(),
        release=AsyncMock(),
    )
    monkeypatch.setattr(llm_billed_once, "JavaWalletClient", lambda **kwargs: wallet)
    monkeypatch.setattr(llm_billed_once, "enforce_risk_limits", Mock())
    monkeypatch.setattr(llm_billed_once, "estimate_preauthorization", lambda *args: Decimal(".01"))
    monkeypatch.setattr(llm_billed_once, "calculate_charge", lambda *args: Decimal(".01"))
    monkeypatch.setattr(
        llm_billed_once,
        "usage_from_response",
        lambda *args: SimpleNamespace(total_tokens=2),
    )
    monkeypatch.setattr(llm_billed_once, "save_success_log", lambda *args, **kwargs: 11)
    for module in (llm_billed_chat, llm_billed_once):
        monkeypatch.setattr(
            module,
            "resolve_chat_route_snapshot",
            Mock(side_effect=AssertionError("route re-read")),
        )
    result = chat_client.post(
        "/api/llm/chat",
        json={**route, "messages": [{"role": "user", "content": "synthetic"}]},
    )
    assert result.status_code == 200
    receipt = result.json()
    assert receipt["key_source"] == "platform" and receipt["billed"] is True
    assert receipt["config_revision"] == route["config_revision"]
    wallet.preauthorize.assert_awaited_once()
    wallet.settle.assert_awaited_once()
    assert len(upstream["requests"]) == 1
    request = upstream["requests"][0]
    assert request.headers["api-key"] == KEY
    assert request.headers["host"] == "token-plan-cn.xiaomimimo.com"
    assert json.loads(request.content)["model"] == route["model"]
    assert KEY not in response.text + result.text
    database.refresh(user)
    database.refresh(credential)
    assert (
        user.default_llm_json,
        credential.api_key_encrypted,
        credential.base_url_encrypted,
    ) == before


@pytest.mark.parametrize(
    "selection",
    [
        {"provider": "xiaomi"},
        {"model": "mimo-v2.6-flash"},
        {"provider": "xiaomi", "model": "mimo-v2.6-flash"},
    ],
)
def test_platform_only_rejects_explicit_selection(chat_client, selection):
    response = chat_client.get(
        "/api/llm/resolve-chat-default", params={"platform_only": "true", **selection}
    )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "PLATFORM_ROUTE_CONFLICT"


def test_chat_default_openapi_exposes_optional_platform_only(chat_client):
    operation = chat_client.app.openapi()["paths"]["/api/llm/resolve-chat-default"]["get"]
    query = {p["name"]: p for p in operation["parameters"] if p["in"] == "query"}
    assert set(query) == {"provider", "model", "platform_only"}
    assert query["platform_only"]["required"] is False
    assert query["platform_only"]["schema"] == {
        "type": "boolean",
        "default": False,
        "title": "Platform Only",
    }


@pytest.mark.asyncio
async def test_platform_only_without_platform_never_falls_back_to_owned_key(database):
    from modstore_server import llm_api
    from modstore_server.models import User, UserLlmCredential

    user = database.get(User, 1)
    before = json.dumps({"mode": "byok", "provider": "xiaomi", "model": "mimo-v2.6-flash"})
    user.default_llm_json = before
    database.add(
        UserLlmCredential(
            user_id=1,
            provider="xiaomi",
            api_key_encrypted=encrypt_secret("synthetic-personal-key"),
        )
    )
    database.commit()
    assert (await llm_api.resolve_default_llm_route(database, 1))["key_source"] == "user_override"
    with pytest.raises(HTTPException) as error:
        await llm_api.resolve_default_llm_route(database, 1, platform_only=True)
    assert error.value.status_code == 400
    assert error.value.detail["code"] == "NO_PLATFORM_CHAT_MODEL"
    database.refresh(user)
    assert user.default_llm_json == before
