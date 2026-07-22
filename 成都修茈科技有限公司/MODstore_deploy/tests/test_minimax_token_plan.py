from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from modstore_server import (
    llm_api,
    llm_catalog,
    llm_chat_proxy,
    llm_quota_monitor,
    llm_runtime_autopilot,
)
from modstore_server.infrastructure import http_clients
from modstore_server.llm_key_resolver import (
    is_minimax_token_plan_key,
    minimax_anthropic_base_url,
    normalize_minimax_api_key,
)


class _Response:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class _Client:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    async def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return _Response(self.payload)


def test_minimax_token_plan_key_and_base_url_detection(monkeypatch):
    monkeypatch.delenv("MINIMAX_ANTHROPIC_BASE_URL", raising=False)

    assert is_minimax_token_plan_key("minimaxsk-cp-example") is True
    assert normalize_minimax_api_key("minimaxsk-cp-example") == "sk-cp-example"
    assert is_minimax_token_plan_key("sk-payg-example") is False
    assert (
        minimax_anthropic_base_url("https://api.minimax.io/v1")
        == "https://api.minimax.io/anthropic"
    )
    assert (
        minimax_anthropic_base_url("https://api.minimaxi.com/anthropic/v1")
        == "https://api.minimaxi.com/anthropic"
    )


@pytest.mark.asyncio
async def test_minimax_token_plan_catalog_uses_anthropic_endpoint(monkeypatch):
    client = _Client(
        {
            "data": [
                {"id": "MiniMax-M2.7", "display_name": "MiniMax M2.7"},
                {"id": "MiniMax-M2.7-highspeed"},
            ]
        }
    )
    monkeypatch.setattr(http_clients, "get_external_client", lambda: client)

    records, error = await llm_catalog._fetch_minimax_token_plan_records(
        "minimaxsk-cp-example",
        base_url="https://api.minimax.io",
    )

    assert error is None
    assert [row["id"] for row in records] == [
        "MiniMax-M2.7",
        "MiniMax-M2.7-highspeed",
    ]
    url, kwargs = client.calls[0]
    assert url == "https://api.minimax.io/anthropic/v1/models"
    assert kwargs["headers"]["x-api-key"] == "sk-cp-example"
    assert kwargs["headers"]["anthropic-version"] == "2023-06-01"


@pytest.mark.asyncio
async def test_minimax_token_plan_chat_dispatch_uses_anthropic_protocol(monkeypatch):
    call = AsyncMock(return_value={"ok": True, "content": "ok", "usage": {}})
    monkeypatch.setattr(llm_chat_proxy, "chat_anthropic_compatible", call)

    result = await llm_chat_proxy.chat_dispatch(
        "minimax",
        api_key="minimaxsk-cp-example",
        base_url="https://api.minimax.io",
        model="MiniMax-M2.7",
        messages=[{"role": "user", "content": "ping"}],
        max_tokens=32,
    )

    assert result["ok"] is True
    call.assert_awaited_once_with(
        "https://api.minimax.io/anthropic",
        "sk-cp-example",
        "MiniMax-M2.7",
        [{"role": "user", "content": "ping"}],
        max_tokens=32,
    )


@pytest.mark.asyncio
async def test_minimax_payg_key_keeps_openai_compatible_protocol(monkeypatch):
    call = AsyncMock(return_value={"ok": True, "content": "ok", "usage": {}})
    monkeypatch.setattr(llm_chat_proxy, "chat_openai_compatible", call)

    result = await llm_chat_proxy.chat_dispatch(
        "minimax",
        api_key="sk-payg-example",
        base_url="https://api.minimaxi.com",
        model="MiniMax-M2.7",
        messages=[{"role": "user", "content": "ping"}],
    )

    assert result["ok"] is True
    assert call.await_args.args[0] == "https://api.minimaxi.com/v1"


@pytest.mark.asyncio
async def test_admin_control_plane_exposes_quota_and_autopilot_status(monkeypatch):
    async def quota_snapshot(*, live_probe=False, catalog=None):
        _ = catalog
        return {"ok": True, "live_probe": live_probe, "providers": []}

    monkeypatch.setattr(llm_quota_monitor, "platform_quota_snapshot", quota_snapshot)
    monkeypatch.setattr(
        llm_runtime_autopilot,
        "autopilot_status",
        lambda: {"ok": True, "enabled": False, "last_run": None},
    )
    admin = SimpleNamespace(id=7)

    quota = await llm_api.get_platform_runtime_route_quota(
        live_probe=1,
        admin=admin,
    )
    autopilot = await llm_api.get_platform_runtime_route_autopilot(admin=admin)

    assert quota["live_probe"] is True
    assert quota["actor"] == "admin:7"
    assert autopilot["enabled"] is False
    assert autopilot["scope"] == "platform_ai_employees"
