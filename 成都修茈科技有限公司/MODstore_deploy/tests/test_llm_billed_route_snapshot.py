"""Billed chat receipts describe the credential snapshot actually dispatched."""

import json
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

from modstore_server import llm_billed_chat, llm_billed_once
from modstore_server.llm_billing_values import WalletHold
from modstore_server.llm_key_resolver import ChatRouteSnapshot, chat_route_snapshot


def _route(provider="xiaomi", model="mimo-v2.6-flash", source="platform", revision="before"):
    return ChatRouteSnapshot(
        provider=provider,
        model=model,
        route_source="platform_configuration",
        key_source=source,
        config_revision=revision,
        api_key="synthetic-before-key",
        base_url="https://synthetic.invalid/v1",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("minimax_alias", [False, True])
async def test_bound_snapshot_survives_rotation_and_returns_actual_receipt(
    monkeypatch, stream, minimax_alias
):
    route = _route()
    if minimax_alias:
        route = chat_route_snapshot(
            "minimax",
            "abab6.5s-chat",
            route.api_key,
            route.base_url,
            route.key_source,
            route.route_source,
        )
        assert route.model == "MiniMax-M2.7"
    request = SimpleNamespace(state=SimpleNamespace(), headers={})
    user = SimpleNamespace(id=7)
    wallet = SimpleNamespace(
        preauthorize=AsyncMock(return_value=WalletHold("synthetic-hold", Decimal(".01"), True)),
        settle=AsyncMock(),
        release=AsyncMock(),
    )
    for module in (llm_billed_chat, llm_billed_once):
        monkeypatch.setattr(module, "JavaWalletClient", lambda **kwargs: wallet)
        monkeypatch.setattr(module, "enforce_risk_limits", Mock())
        monkeypatch.setattr(module, "estimate_preauthorization", lambda *args: Decimal(".01"))
        monkeypatch.setattr(module, "calculate_charge", lambda *args: Decimal(".01"))
        monkeypatch.setattr(
            module, "usage_from_response", lambda *args: SimpleNamespace(total_tokens=2)
        )
        monkeypatch.setattr(module, "save_success_log", lambda *args, **kwargs: 11)
        monkeypatch.setattr(
            module, "resolve_chat_route_snapshot", Mock(side_effect=AssertionError("re-read"))
        )
    candidates = AsyncMock(side_effect=AssertionError("bound round must not select another route"))
    monkeypatch.setattr(llm_billed_chat, "list_chat_failover_candidates", candidates)
    dispatched = []

    async def dispatch(provider, **kwargs):
        dispatched.append((provider, kwargs["model"], kwargs["api_key"], kwargs["base_url"]))
        return {"ok": True, "content": "synthetic answer", "usage": {}}

    async def dispatch_stream(provider, **kwargs):
        await dispatch(provider, **kwargs)
        yield {"type": "delta", "delta": "synthetic answer"}

    monkeypatch.setattr(llm_billed_once, "chat_dispatch", dispatch)
    monkeypatch.setattr(llm_billed_chat, "chat_dispatch_stream", dispatch_stream)
    args = dict(
        request=request,
        db=object(),
        user=user,
        provider=route.provider,
        model=route.model,
        messages=[{"role": "user", "content": "synthetic"}],
        route_snapshot=route,
    )
    if stream:
        response = await llm_billed_chat.stream_billed_llm_chat(**args)
        frames = [frame async for frame in response.body_iterator]
        events = {
            frame.split("\n")[0].removeprefix("event: "): json.loads(
                frame.split("\n")[1].removeprefix("data: ")
            )
            for frame in frames
        }
        receipt = events["done"]
        assert all(events["meta"][key] == value for key, value in route.public_metadata().items())
    else:
        receipt = await llm_billed_chat.run_billed_llm_chat(**args)
    assert all(receipt[key] == value for key, value in route.public_metadata().items())
    assert dispatched == [(route.provider, route.model, route.api_key, route.base_url)]
    assert "synthetic-before-key" not in json.dumps(receipt)
    assert "synthetic.invalid" not in json.dumps(receipt)
    candidates.assert_not_awaited()


@pytest.mark.asyncio
async def test_primary_credential_snapshot_precedes_catalog_await(monkeypatch):
    before = _route(provider="openai", model="one")
    resolver = Mock(return_value=before)
    monkeypatch.setattr(llm_billed_chat, "resolve_chat_route_snapshot", resolver)

    async def candidates(*_args):
        resolver.return_value = _route(provider="openai", model="one", revision="after")
        return [("openai", "one"), ("openai", "two")]

    async def once(*args, **kwargs):
        assert kwargs["route_snapshot"].config_revision == "before"
        return {"ok": True, **kwargs["route_snapshot"].public_metadata()}

    monkeypatch.setattr(llm_billed_chat, "list_chat_failover_candidates", candidates)
    monkeypatch.setattr(llm_billed_chat, "_run_billed_llm_chat_once", once)
    result = await llm_billed_chat.run_billed_llm_chat(
        request=SimpleNamespace(state=SimpleNamespace()),
        db=object(),
        user=SimpleNamespace(id=7),
        provider="openai",
        model="one",
        messages=[{"role": "user", "content": "synthetic"}],
    )
    assert result["config_revision"] == "before"
    assert resolver.call_count == 1


@pytest.mark.asyncio
async def test_byok_transient_failure_never_uses_paid_platform_fallback(monkeypatch):
    def resolve(_db, _uid, provider, model, **_kwargs):
        return _route(provider, model, "user_override" if provider == "openai" else "platform")

    monkeypatch.setattr(llm_billed_chat, "resolve_chat_route_snapshot", resolve)
    monkeypatch.setattr(
        llm_billed_chat,
        "list_chat_failover_candidates",
        AsyncMock(return_value=[("openai", "one"), ("deepseek", "two")]),
    )
    once = AsyncMock(side_effect=HTTPException(503, "synthetic temporarily unavailable"))
    monkeypatch.setattr(llm_billed_chat, "_run_billed_llm_chat_once", once)
    with pytest.raises(HTTPException) as error:
        await llm_billed_chat.run_billed_llm_chat(
            request=SimpleNamespace(state=SimpleNamespace()),
            db=object(),
            user=SimpleNamespace(id=7),
            provider="openai",
            model="one",
            messages=[{"role": "user", "content": "synthetic"}],
        )
    assert error.value.status_code == 503
    assert once.await_count == 1
    assert once.await_args.kwargs["provider"] == "openai"


@pytest.mark.asyncio
async def test_bad_backups_never_block_healthy_primary_or_resolve_credentials_twice(monkeypatch):
    primary = _route(provider="xiaomi", model="mimo-v2.6-flash")
    calls = []

    def resolve(_db, _uid, provider, model, **_kwargs):
        calls.append((provider, model))
        if provider == "xiaomi":
            return primary
        raise HTTPException(400, "synthetic unavailable credential")

    monkeypatch.setattr(llm_billed_chat, "resolve_chat_route_snapshot", resolve)
    monkeypatch.setattr(
        llm_billed_chat,
        "list_chat_failover_candidates",
        AsyncMock(
            return_value=[
                ("xiaomi", "mimo-v2.6-flash"),
                ("xiaomi", "mimo-v2.5-asr"),
                ("openai", "gpt-4o-mini"),
                ("openai", "gpt-4o"),
            ]
        ),
    )
    once = AsyncMock(return_value={"ok": True, **primary.public_metadata()})
    monkeypatch.setattr(llm_billed_chat, "_run_billed_llm_chat_once", once)
    result = await llm_billed_chat.run_billed_llm_chat(
        request=SimpleNamespace(state=SimpleNamespace()),
        db=object(),
        user=SimpleNamespace(id=7),
        provider=primary.provider,
        model=primary.model,
        messages=[{"role": "user", "content": "synthetic"}],
    )
    assert result["model"] == "mimo-v2.6-flash"
    assert once.await_count == 1
    assert calls == [("xiaomi", "mimo-v2.6-flash"), ("openai", "gpt-4o-mini")]
    allowed, snapshots = llm_billed_chat._candidate_snapshots(
        object(), 7, primary, [("xiaomi", "mimo-v2.5-asr")]
    )
    assert allowed == [(primary.provider, primary.model)]
    assert ("xiaomi", "mimo-v2.5-asr") not in snapshots


def test_same_provider_backup_alias_uses_canonical_pair_without_rereading(monkeypatch):
    primary = _route(provider="minimax", model="MiniMax-M2.5")
    resolver = Mock(side_effect=AssertionError("credentials must remain fixed"))
    monkeypatch.setattr(llm_billed_chat, "resolve_chat_route_snapshot", resolver)
    allowed, snapshots = llm_billed_chat._candidate_snapshots(
        object(),
        7,
        primary,
        [("minimax", "abab6.5s-chat"), ("minimax", "MiniMax-M2.7")],
    )
    assert allowed == [("minimax", "MiniMax-M2.5"), ("minimax", "MiniMax-M2.7")]
    assert snapshots["minimax", "MiniMax-M2.7"].public_metadata()["model"] == "MiniMax-M2.7"
    assert snapshots["minimax", "MiniMax-M2.7"].api_key == primary.api_key
    resolver.assert_not_called()
