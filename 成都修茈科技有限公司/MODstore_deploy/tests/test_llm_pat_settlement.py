"""A completed PAT-backed model call must not be retried after settlement uncertainty."""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

from modstore_server import llm_billed_chat, llm_billed_once
from modstore_server.llm_billing_values import WalletHold
from modstore_server.llm_key_resolver import ChatRouteSnapshot


def _route(_db, _uid, provider, model, **_kwargs):
    return ChatRouteSnapshot(
        provider=provider,
        model=model,
        route_source="explicit",
        key_source="platform",
        config_revision="synthetic-revision",
        api_key="synthetic",
        base_url=None,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "dispatch_result",
    [
        {"ok": True, "content": "synthetic", "usage": {}},
        {"ok": False, "status": 429, "error": "synthetic rate limit"},
    ],
)
async def test_pat_uncertain_billing_does_not_release_or_failover(monkeypatch, dispatch_result):
    request = SimpleNamespace(
        state=SimpleNamespace(llm_pat_user_id=7), headers={"authorization": "Bearer synthetic"}
    )
    user = SimpleNamespace(id=7)
    hold = WalletHold("synthetic-hold", Decimal("0.05"), True)
    wallet = SimpleNamespace(
        preauthorize=AsyncMock(return_value=hold),
        settle=AsyncMock(side_effect=HTTPException(503, "synthetic wallet unavailable")),
        release=AsyncMock(),
    )
    monkeypatch.setattr(llm_billed_once, "JavaWalletClient", lambda **kwargs: wallet)
    monkeypatch.setattr(llm_billed_once, "resolve_chat_route_snapshot", _route)
    monkeypatch.setattr(llm_billed_once, "assert_llm_chat_allowed", AsyncMock())
    monkeypatch.setattr(llm_billed_once, "enforce_risk_limits", Mock())
    monkeypatch.setattr(llm_billed_once, "estimate_preauthorization", lambda *args: Decimal("0.05"))
    monkeypatch.setattr(llm_billed_once, "calculate_charge", lambda *args: Decimal("0.02"))
    monkeypatch.setattr(llm_billed_once, "usage_from_response", lambda *args: SimpleNamespace())
    dispatch = AsyncMock(return_value=dispatch_result)
    monkeypatch.setattr(llm_billed_once, "chat_dispatch", dispatch)
    monkeypatch.setattr(llm_billed_once, "save_failure_log", Mock())
    monkeypatch.setattr(
        llm_billed_chat, "_run_billed_llm_chat_once", llm_billed_once.run_billed_llm_chat_once
    )
    monkeypatch.setattr(llm_billed_chat, "resolve_chat_route_snapshot", _route)
    monkeypatch.setattr(
        llm_billed_chat,
        "list_chat_failover_candidates",
        AsyncMock(return_value=[("openai", "one"), ("openai", "two")]),
    )
    with pytest.raises(HTTPException) as error:
        await llm_billed_chat.run_billed_llm_chat(
            request,
            object(),
            user,
            provider="openai",
            model="one",
            messages=[{"role": "user", "content": "synthetic"}],
        )
    assert error.value.status_code == 409
    assert dispatch.await_count == 1
    wallet.release.assert_not_awaited()


@pytest.mark.asyncio
async def test_pat_model_gate_denies_before_wallet_or_upstream(monkeypatch):
    request = SimpleNamespace(
        state=SimpleNamespace(llm_pat_user_id=7), headers={"authorization": "Bearer synthetic"}
    )
    monkeypatch.setattr(llm_billed_once, "resolve_chat_route_snapshot", _route)
    monkeypatch.setattr(
        llm_billed_once,
        "assert_llm_chat_allowed",
        AsyncMock(side_effect=HTTPException(403, "synthetic denied")),
    )
    wallet = Mock()
    dispatch = AsyncMock()
    monkeypatch.setattr(llm_billed_once, "JavaWalletClient", wallet)
    monkeypatch.setattr(llm_billed_once, "chat_dispatch", dispatch)
    with pytest.raises(HTTPException) as error:
        await llm_billed_once.run_billed_llm_chat_once(
            request,
            object(),
            SimpleNamespace(id=7),
            provider="openai",
            model="restricted",
            messages=[{"role": "user", "content": "synthetic"}],
        )
    assert error.value.status_code == 403
    wallet.assert_not_called()
    dispatch.assert_not_awaited()


@pytest.mark.asyncio
async def test_unknown_preauthorization_does_not_dispatch_or_failover(monkeypatch):
    request = SimpleNamespace(
        state=SimpleNamespace(llm_pat_user_id=7), headers={"authorization": "Bearer synthetic"}
    )
    wallet = SimpleNamespace(
        preauthorize=AsyncMock(side_effect=HTTPException(502, "synthetic timeout"))
    )
    dispatch = AsyncMock()
    monkeypatch.setattr(llm_billed_once, "JavaWalletClient", lambda **kwargs: wallet)
    monkeypatch.setattr(llm_billed_once, "resolve_chat_route_snapshot", _route)
    monkeypatch.setattr(llm_billed_once, "assert_llm_chat_allowed", AsyncMock())
    monkeypatch.setattr(llm_billed_once, "enforce_risk_limits", Mock())
    monkeypatch.setattr(llm_billed_once, "estimate_preauthorization", lambda *args: Decimal("0.05"))
    monkeypatch.setattr(llm_billed_once, "chat_dispatch", dispatch)
    monkeypatch.setattr(
        llm_billed_chat, "_run_billed_llm_chat_once", llm_billed_once.run_billed_llm_chat_once
    )
    monkeypatch.setattr(llm_billed_chat, "resolve_chat_route_snapshot", _route)
    monkeypatch.setattr(
        llm_billed_chat,
        "list_chat_failover_candidates",
        AsyncMock(return_value=[("openai", "one"), ("openai", "two")]),
    )
    with pytest.raises(HTTPException) as error:
        await llm_billed_chat.run_billed_llm_chat(
            request,
            object(),
            SimpleNamespace(id=7),
            provider="openai",
            model="one",
            messages=[{"role": "user", "content": "synthetic"}],
        )
    assert error.value.status_code == 409
    assert error.value.detail["request_id"]
    assert wallet.preauthorize.await_count == 1
    dispatch.assert_not_awaited()
