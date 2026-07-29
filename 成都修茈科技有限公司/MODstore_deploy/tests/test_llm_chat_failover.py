"""用户聊天配额失败自动切模。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from modstore_server.llm_chat_failover import (
    is_chat_failoverable_failure,
    is_wallet_balance_failure,
    list_chat_failover_candidates,
    remaining_candidates_after_failure,
)


def test_failoverable_markers():
    assert is_chat_failoverable_failure("Error 429: insufficient_quota", 429)
    assert is_chat_failoverable_failure("配额不足", 403)
    assert is_chat_failoverable_failure("rate limit exceeded", 429)
    assert is_wallet_balance_failure("余额不足，需要 ¥0.05，当前 ¥0", 402)
    assert not is_chat_failoverable_failure("invalid api key format", 401)


def test_remaining_candidates_wallet_only_keeps_byok():
    candidates = [
        ("openai", "gpt-4o-mini"),
        ("deepseek", "deepseek-chat"),
        ("xiaomi", "mimo-v2"),
    ]
    rest = remaining_candidates_after_failure(
        candidates,
        0,
        error_text="余额不足，需要 ¥0.05，当前 ¥0",
        status_code=402,
        key_source_by_provider={
            "openai": "platform",
            "deepseek": "user_override",
            "xiaomi": "platform",
        },
    )
    assert rest == [("deepseek", "deepseek-chat")]


def test_remaining_candidates_quota_keeps_all_next():
    candidates = [
        ("openai", "gpt-4o-mini"),
        ("deepseek", "deepseek-chat"),
        ("xiaomi", "mimo-v2"),
    ]
    rest = remaining_candidates_after_failure(
        candidates,
        0,
        error_text="insufficient_quota",
        status_code=429,
        key_source_by_provider={
            "openai": "platform",
            "deepseek": "platform",
            "xiaomi": "platform",
        },
    )
    assert rest == [("deepseek", "deepseek-chat"), ("xiaomi", "mimo-v2")]


@pytest.mark.asyncio
async def test_list_candidates_prefers_primary_then_others(monkeypatch):
    async def fake_models(db, user_id, provider, force_refresh=False):
        mapping = {
            "openai": ["gpt-4o-mini"],
            "deepseek": ["deepseek-chat"],
            "xiaomi": ["mimo-v2"],
        }
        return {"models": mapping.get(provider, []), "runtime_models": mapping.get(provider, [])}

    monkeypatch.setattr(
        "modstore_server.llm_catalog.get_models_for_provider",
        fake_models,
    )

    def fake_resolve(db, user_id, provider):
        keys = {"openai": "k1", "deepseek": "k2", "xiaomi": "k3"}
        k = keys.get(provider)
        return (k, "platform") if k else (None, "")

    monkeypatch.setattr(
        "modstore_server.llm_chat_failover.resolve_api_key",
        fake_resolve,
    )
    monkeypatch.setattr(
        "modstore_server.llm_chat_failover.KNOWN_PROVIDERS",
        ("openai", "deepseek", "xiaomi"),
    )

    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = SimpleNamespace(
        default_llm_json='{"provider":"openai","model":"gpt-4o-mini"}'
    )
    out = await list_chat_failover_candidates(db, 1, "openai", "gpt-4o-mini")
    assert out[0] == ("openai", "gpt-4o-mini")
    assert ("deepseek", "deepseek-chat") in out
    assert ("xiaomi", "mimo-v2") in out


@pytest.mark.asyncio
async def test_run_billed_llm_chat_failsover_on_quota(monkeypatch):
    from modstore_server import llm_billed_chat as llm_api

    calls: list[tuple[str, str]] = []

    async def fake_once(request, db, user, **kwargs):
        prov = kwargs["provider"]
        mdl = kwargs["model"]
        calls.append((prov, mdl))
        if prov == "openai":
            raise HTTPException(429, "insufficient_quota")
        return {
            "ok": True,
            "content": "hello",
            "conversation_id": 1,
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            "charge_amount": 0.02,
            "hold_no": "h1",
            "key_source": "platform",
            "billed": True,
            "provider": prov,
            "model": mdl,
            "request_id": "r1",
        }

    async def fake_candidates(db, user_id, primary_provider, primary_model):
        return [
            ("openai", "gpt-4o-mini"),
            ("deepseek", "deepseek-chat"),
        ]

    monkeypatch.setattr(llm_api, "_run_billed_llm_chat_once", fake_once)
    monkeypatch.setattr(llm_api, "list_chat_failover_candidates", fake_candidates)
    monkeypatch.setattr(
        llm_api,
        "resolve_api_key",
        lambda db, uid, p: ("k", "platform"),
    )

    user = SimpleNamespace(id=7)
    out = await llm_api.run_billed_llm_chat(
        request=MagicMock(),
        db=MagicMock(),
        user=user,
        provider="openai",
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "hi"}],
        allow_failover=True,
    )
    assert out["provider"] == "deepseek"
    assert out["content"] == "hello"
    assert out["failover_from"] == "openai/gpt-4o-mini"
    assert calls == [("openai", "gpt-4o-mini"), ("deepseek", "deepseek-chat")]


@pytest.mark.asyncio
async def test_run_billed_respects_allow_failover_false(monkeypatch):
    from modstore_server import llm_billed_chat as llm_api

    async def fake_once(request, db, user, **kwargs):
        raise HTTPException(429, "insufficient_quota")

    monkeypatch.setattr(llm_api, "_run_billed_llm_chat_once", fake_once)
    monkeypatch.setattr(
        llm_api,
        "list_chat_failover_candidates",
        AsyncMock(return_value=[("openai", "a"), ("deepseek", "b")]),
    )

    with pytest.raises(HTTPException) as ei:
        await llm_api.run_billed_llm_chat(
            request=MagicMock(),
            db=MagicMock(),
            user=SimpleNamespace(id=1),
            provider="openai",
            model="a",
            messages=[{"role": "user", "content": "hi"}],
            allow_failover=False,
        )
    assert ei.value.status_code == 429
    llm_api.list_chat_failover_candidates.assert_not_awaited()
