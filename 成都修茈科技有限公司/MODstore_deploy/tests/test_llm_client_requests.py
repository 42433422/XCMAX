"""A client idempotency key runs one billed execution and replays its receipt."""

import asyncio
import json
from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

from modstore_server import llm_billed_chat
from modstore_server import llm_client_requests as ledger
from modstore_server.llm_billing_values import WalletHold
from modstore_server.llm_key_resolver import ChatRouteSnapshot
from tests.llm_request_support import KEY
from tests.llm_request_support import db as db


def _frames(frames):
    out = []
    for frame in frames:
        lines = frame.split("\n")
        out.append(
            (
                lines[0].removeprefix("event: "),
                json.loads(lines[1].removeprefix("data: ")),
            )
        )
    return out


@pytest.fixture
def billed(monkeypatch, db):
    route = ChatRouteSnapshot(
        provider="xiaomi",
        model="mimo-v2.6-flash",
        route_source="platform_configuration",
        key_source="platform",
        config_revision="r1",
        api_key="synthetic-key",
        base_url="https://synthetic.invalid/v1",
    )
    wallet = SimpleNamespace(
        enabled=True,
        preauthorize=AsyncMock(return_value=WalletHold("synthetic-hold", Decimal(".01"), True)),
        settle=AsyncMock(),
        release=AsyncMock(),
    )
    monkeypatch.setattr(llm_billed_chat, "JavaWalletClient", lambda **kwargs: wallet)
    monkeypatch.setattr(llm_billed_chat, "enforce_risk_limits", Mock())
    monkeypatch.setattr(llm_billed_chat, "estimate_preauthorization", lambda *a: Decimal(".01"))
    monkeypatch.setattr(llm_billed_chat, "calculate_charge", lambda *a: Decimal(".01"))
    monkeypatch.setattr(llm_billed_chat, "save_success_log", lambda *a, **k: 11)
    monkeypatch.setattr(llm_billed_chat, "save_failure_log", Mock())
    sent = []

    async def dispatch(provider, **kwargs):
        sent.append(kwargs["model"])
        yield {"type": "delta", "delta": "synthetic answer"}
        yield {"type": "finish", "finish_reason": "length"}

    monkeypatch.setattr(llm_billed_chat, "chat_dispatch_stream", dispatch)

    async def call():
        response = await llm_billed_chat.stream_billed_llm_chat(
            request=SimpleNamespace(state=SimpleNamespace(), headers={}),
            db=db,
            user=SimpleNamespace(id=7),
            provider=route.provider,
            model=route.model,
            messages=[{"role": "user", "content": "synthetic"}],
            route_snapshot=route,
            client_request_id=KEY,
        )
        return _frames([frame async for frame in response.body_iterator])

    return SimpleNamespace(
        call=call, wallet=wallet, sent=sent, monkeypatch=monkeypatch, route=route
    )


@pytest.mark.asyncio
async def test_same_key_resend_replays_the_receipt_without_a_second_charge(billed, db):
    first = await billed.call()
    assert [event for event, _ in first] == ["status", "meta", "delta", "done"]
    assert first[0][1]["state"] == "accepted"
    assert first[3][1]["finish_reason"] == "length"
    assert first[1][1]["request_id"] == ledger.attempt_request_id(7, KEY, 1) + "-0"
    second = await billed.call()
    assert [event for event, _ in second] == ["done"] and second[0][1]["replayed"] is True
    assert second[0][1]["content"] == "synthetic answer"
    assert billed.wallet.preauthorize.await_count == 1 == billed.wallet.settle.await_count
    assert billed.sent == ["mimo-v2.6-flash"]


@pytest.mark.asyncio
async def test_an_upstream_timeout_keeps_the_key_for_reconciliation(billed, db):
    async def failing(*_args, **_kwargs):
        raise TimeoutError("synthetic upstream timeout")
        yield {}

    billed.monkeypatch.setattr(llm_billed_chat, "chat_dispatch_stream", failing)
    events = await billed.call()
    assert [event for event, _ in events] == ["status", "meta", "error"]
    assert ledger.lookup(db, 7, KEY, 90) == "settling"
    billed.wallet.settle.assert_not_awaited()
    billed.wallet.release.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["event", "exception"])
@pytest.mark.parametrize("keyed", [False, True])
@pytest.mark.parametrize("funding", ["wallet", "disabled", "byok"])
async def test_stream_limit_retains_original_hold_without_failover(
    billed, db, kind, keyed, funding
):
    from modstore_server.llm_gateway_contract import StreamLimitError

    route = billed.route
    if funding == "byok":
        route = replace(route, key_source="user_override")
    elif funding == "disabled":
        billed.wallet.enabled = False
        billed.wallet.preauthorize.return_value = WalletHold("synthetic-hold", Decimal("0"), False)
    backup = replace(route, provider="openai", model="gpt-4o-mini")
    billed.monkeypatch.setattr(
        llm_billed_chat,
        "resolve_chat_route_snapshot",
        lambda _db, _uid, provider, _model, **_kwargs: (
            route if provider == route.provider else backup
        ),
    )
    candidates = AsyncMock(
        return_value=[(route.provider, route.model), (backup.provider, backup.model)]
    )
    billed.monkeypatch.setattr(llm_billed_chat, "list_chat_failover_candidates", candidates)

    async def overflow(provider, **kwargs):
        billed.sent.append((provider, kwargs["model"]))
        if len(billed.sent) > 1:
            yield {"type": "delta", "delta": "must not request a second answer"}
            yield {"type": "finish", "finish_reason": "stop"}
        elif kind == "exception":
            raise StreamLimitError(f"model stream wire byte limit exceeded: {route.api_key}")
        else:
            yield {
                "type": "error",
                "code": "model_stream_limit_exceeded",
                "status": 502,
                "error": f"model stream wire byte limit exceeded: {route.api_key}",
                "outcome_unknown": True,
                "non_retryable": True,
            }

    billed.monkeypatch.setattr(llm_billed_chat, "chat_dispatch_stream", overflow)
    arguments = dict(
        request=SimpleNamespace(state=SimpleNamespace(), headers={}),
        db=db,
        user=SimpleNamespace(id=7),
        provider=route.provider,
        model=route.model,
        messages=[{"role": "user", "content": "synthetic"}],
        client_request_id=KEY if keyed else None,
    )
    response = await llm_billed_chat.stream_billed_llm_chat(**arguments)
    frames = _frames([frame async for frame in response.body_iterator])
    meta = next(data for event, data in frames if event == "meta")
    error = frames[-1][1]
    assert frames[-1][0] == "error" and not any(event == "done" for event, _ in frames)
    assert billed.sent == [(route.provider, route.model)]
    assert billed.wallet.preauthorize.await_count == (0 if funding == "byok" else 1)
    billed.wallet.settle.assert_not_awaited()
    billed.wallet.release.assert_not_awaited()
    assert error["status"] == 409 and error["code"] == "model_stream_limit_exceeded"
    assert error["outcome_unknown"] is True and error["non_retryable"] is True
    assert error["request_id"] == meta["request_id"] and error["hold_no"] == meta["hold_no"]
    assert route.api_key not in json.dumps(error)
    candidates.assert_awaited_once()
    if keyed:
        assert ledger.lookup(db, 7, KEY, 90) == "settling"
        with pytest.raises(HTTPException) as rejected:
            await llm_billed_chat.stream_billed_llm_chat(**arguments)
        assert rejected.value.status_code == 409
        assert billed.sent == [(route.provider, route.model)]


@pytest.mark.asyncio
async def test_a_live_key_is_refused_instead_of_run_twice(billed, db):
    ledger.begin(db, 7, KEY, "other-digest", 90)
    with pytest.raises(HTTPException) as refused:
        await billed.call()
    assert refused.value.status_code == 409 and refused.value.detail["state"] == "conflict"
    billed.wallet.preauthorize.assert_not_awaited()


@pytest.mark.asyncio
async def test_wallet_readback_recovers_a_paid_image_once(db, monkeypatch):
    from modstore_server import llm_billing_recovery as recovery
    from modstore_server.db.llm_chat import LlmCallLog

    _, row = ledger.begin(db, 7, KEY, "image", 180)
    receipt = {
        "ok": True,
        "operation": "image_generation",
        "provider": "openai",
        "model": "gpt-image-2",
        "hold_no": "AIH-test",
        "request_id": "request-test",
        "charge_amount": "0.42",
        "images": ["test-result"],
        "usage": {"prompt_tokens": 17, "completion_tokens": 42, "total_tokens": 59},
    }
    ledger.prepare_settlement(db, row, receipt)
    hold = {key: receipt[key] for key in ("provider", "model", "hold_no", "request_id")}
    read = AsyncMock(return_value={**hold, "status": "settled", "settled_amount": "0.43"})
    monkeypatch.setattr(recovery, "JavaWalletClient", lambda: SimpleNamespace(read_hold=read))

    assert await recovery.recover_receipt(db, 8, KEY, "other-token") is None
    read.assert_not_awaited()
    assert await recovery.recover_receipt(db, 7, KEY, "owner-token") is None
    assert ledger.lookup(db, 7, KEY, 180) == "settling"
    assert db.query(LlmCallLog).count() == 0

    read.return_value["settled_amount"] = "0.42"
    assert await recovery.recover_receipt(db, 7, KEY, "owner-token") == receipt
    assert ledger.begin(db, 7, KEY, "image", 180) == ("replay", receipt)
    assert recovery.complete_receipt(db, row, receipt) == receipt
    assert db.query(LlmCallLog).count() == 1


@pytest.mark.asyncio
async def test_sync_chat_replays_after_wallet_response_is_lost(db, monkeypatch):
    from fastapi import HTTPException

    from modstore_server import llm_billed_once

    route = ChatRouteSnapshot(
        provider="openai",
        model="vision-example",
        route_source="explicit",
        key_source="platform",
        config_revision="r1",
        api_key="test-key",
        base_url="https://synthetic.invalid/v1",
    )
    wallet = SimpleNamespace(
        enabled=True,
        preauthorize=AsyncMock(return_value=WalletHold("sync-hold", Decimal("1"), True)),
        settle=AsyncMock(side_effect=HTTPException(502, "wallet timeout")),
        release=AsyncMock(),
    )
    monkeypatch.setattr(llm_billed_once, "JavaWalletClient", lambda **kwargs: wallet)
    monkeypatch.setattr(llm_billed_once, "enforce_risk_limits", Mock())
    send = AsyncMock(
        return_value={
            "ok": True,
            "content": "saved",
            "usage": {"prompt_tokens": 30, "completion_tokens": 40, "total_tokens": 70},
        }
    )
    monkeypatch.setattr(llm_billed_once, "chat_dispatch", send)
    monkeypatch.setattr(llm_billed_once, "recover_receipt", AsyncMock(return_value=None))

    async def request():
        return await llm_billed_chat.run_billed_llm_chat(
            SimpleNamespace(state=SimpleNamespace(), headers={}),
            db,
            SimpleNamespace(id=7),
            provider=route.provider,
            model=route.model,
            route_snapshot=route,
            messages=[{"role": "user", "content": "test"}],
            client_request_id=KEY,
        )

    with pytest.raises(HTTPException) as pending:
        await request()
    assert pending.value.status_code == 409
    assert ledger.lookup(db, 7, KEY, 90) == "settling"
    wallet.release.assert_not_awaited()

    from modstore_server import llm_billing_recovery as recovery

    request_id = str(wallet.preauthorize.await_args.args[4])
    charge = wallet.settle.await_args.args[2]
    read = AsyncMock(
        return_value={
            "hold_no": "sync-hold",
            "request_id": request_id,
            "provider": route.provider,
            "model": route.model,
            "status": "settled",
            "settled_amount": str(charge),
        }
    )
    monkeypatch.setattr(recovery, "JavaWalletClient", lambda: SimpleNamespace(read_hold=read))
    receipt = await request()
    assert receipt["content"] == "saved"
    assert receipt["pricing"]["currency"] == "CNY"
    assert "_history" not in receipt
    assert await request() == receipt
    send.assert_awaited_once()
    wallet.settle.assert_awaited_once()


@pytest.fixture
def sync_billed(billed, db, monkeypatch):
    from modstore_server import llm_billed_once

    monkeypatch.setattr(llm_billed_once, "JavaWalletClient", lambda **kwargs: billed.wallet)
    monkeypatch.setattr(llm_billed_once, "enforce_risk_limits", Mock())
    monkeypatch.setattr(llm_billed_once, "estimate_preauthorization", lambda *a: Decimal(".01"))
    send = AsyncMock(
        return_value={
            "ok": True,
            "content": "original answer",
            "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
        }
    )
    monkeypatch.setattr(llm_billed_once, "chat_dispatch", send)

    async def call(funding):
        route = (
            replace(billed.route, key_source="user_override") if funding == "byok" else billed.route
        )
        if funding == "disabled":
            billed.wallet.enabled = False
            billed.wallet.preauthorize.return_value = WalletHold("disabled", Decimal("0"), False)
        return await llm_billed_chat.run_billed_llm_chat(
            SimpleNamespace(state=SimpleNamespace(), headers={}),
            db,
            SimpleNamespace(id=7),
            provider=route.provider,
            model=route.model,
            route_snapshot=route,
            messages=[{"role": "user", "content": "original request"}],
            client_request_id=KEY,
        )

    return SimpleNamespace(call=call, send=send, wallet=billed.wallet, route=billed.route)


@pytest.mark.asyncio
@pytest.mark.parametrize("funding", ["byok", "disabled"])
@pytest.mark.parametrize("failure", ["timeout", "server_error", "cancelled"])
async def test_sync_unknown_attempt_stays_owned_even_without_platform_wallet(
    sync_billed, db, funding, failure
):
    if failure == "server_error":
        sync_billed.send.return_value = {
            "ok": False,
            "status": 500,
            "error": "provider unavailable",
        }
    else:
        sync_billed.send.side_effect = (
            asyncio.CancelledError() if failure == "cancelled" else TimeoutError("response lost")
        )
    expected = asyncio.CancelledError if failure == "cancelled" else HTTPException
    with pytest.raises(expected):
        await sync_billed.call(funding)
    assert ledger.lookup(db, 7, KEY, 90) == "settling"
    with pytest.raises(HTTPException) as replay:
        await sync_billed.call(funding)
    assert replay.value.status_code == 409
    sync_billed.send.assert_awaited_once()
    sync_billed.wallet.settle.assert_not_awaited()
    sync_billed.wallet.release.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("funding", ["byok", "disabled"])
async def test_sync_receipt_replays_once_without_platform_wallet(sync_billed, db, funding):
    from modstore_server.db.llm_chat import ChatMessage, LlmCallLog

    first = await sync_billed.call(funding)
    assert first["content"] == "original answer"
    assert await sync_billed.call(funding) == first
    sync_billed.send.assert_awaited_once()
    assert ledger.lookup(db, 7, KEY, 90) == "completed"
    assert db.query(LlmCallLog).count() == 1 and db.query(ChatMessage).count() == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("funding", ["byok", "disabled"])
async def test_sync_definite_rejection_can_release_the_original_request(sync_billed, db, funding):
    sync_billed.send.return_value = {"ok": False, "status": 429, "error": "quota exhausted"}
    with pytest.raises(HTTPException) as rejected:
        await sync_billed.call(funding)
    assert rejected.value.status_code == 429
    assert ledger.lookup(db, 7, KEY, 90) == "failed"
    sync_billed.send.return_value = {
        "ok": True,
        "content": "second admitted attempt",
        "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
    }
    assert (await sync_billed.call(funding))["content"] == "second admitted attempt"
    assert sync_billed.send.await_count == 2


@pytest.mark.asyncio
async def test_sync_byok_recovers_its_saved_response_after_local_receipt_failure(
    sync_billed, db, monkeypatch
):
    from modstore_server import llm_billed_once
    from modstore_server.db.llm_chat import ChatMessage, LlmCallLog

    monkeypatch.setattr(
        llm_billed_once, "complete_receipt", Mock(side_effect=OSError("local commit unavailable"))
    )
    with pytest.raises(HTTPException) as failed:
        await sync_billed.call("byok")
    assert failed.value.status_code == 409 and ledger.lookup(db, 7, KEY, 90) == "settling"
    assert db.query(LlmCallLog).count() == 0
    receipt = await sync_billed.call("byok")
    assert receipt["content"] == "original answer" and receipt["billed"] is False
    assert await sync_billed.call("byok") == receipt
    sync_billed.send.assert_awaited_once()
    sync_billed.wallet.preauthorize.assert_not_awaited()
    sync_billed.wallet.settle.assert_not_awaited()
    sync_billed.wallet.release.assert_not_awaited()
    assert db.query(LlmCallLog).count() == 1 and db.query(ChatMessage).count() == 2


@pytest.mark.asyncio
async def test_video_request_replays_same_supplier_job_id(db, monkeypatch):
    from modstore_server import llm_api, llm_key_resolver

    send = AsyncMock(
        return_value={
            "ok": True,
            "job_id": "video-id",
            "status": "pending",
            "raw": {"usage": {"input_tokens": 2, "output_tokens": 0, "total_tokens": 2}},
        }
    )
    monkeypatch.setattr(llm_api, "video_dispatch", send)
    monkeypatch.setattr(
        llm_key_resolver,
        "resolve_credentials",
        lambda *args: ("platform-key", "https://example.invalid", "platform"),
    )
    body = llm_api.LlmVideoDTO(
        provider="openai",
        model="video-model",
        prompt="test",
        client_request_id=KEY,
    )
    first = await llm_api.llm_video(body, db, SimpleNamespace(id=7))
    assert first["job_id"] == "video-id"
    assert first["billing"]["state"] == "awaiting_provider_usage"
    assert first["billing"]["usage"] is None
    assert await llm_api.llm_video(body, db, SimpleNamespace(id=7)) == first
    send.assert_awaited_once()


@pytest.mark.asyncio
async def test_gateway_replays_auto_route_before_current_config_lookup(db, monkeypatch):
    from modstore_server import openai_llm_gateway_api as gateway

    resolve = AsyncMock(return_value={"provider": "openai", "model": "model-a"})
    attempt = AsyncMock(
        return_value={"content": "saved answer", "provider": "openai", "model": "model-a"}
    )
    monkeypatch.setattr(gateway, "resolve_default_llm_route", resolve)
    monkeypatch.setattr(llm_billed_chat, "_run_sync_attempts", attempt)
    body = gateway.OAIChatCompletionRequest(
        model="xcauto-account", messages=[{"role": "user", "content": "hello"}]
    )
    request = SimpleNamespace(headers={"Idempotency-Key": KEY})
    first = await gateway.openai_chat_completions(request, body, db, SimpleNamespace(id=7))
    assert json.loads(first.body)["choices"][0]["message"]["content"] == "saved answer"
    resolve.side_effect = HTTPException(503, "current route unavailable")
    replay = await gateway.openai_chat_completions(request, body, db, SimpleNamespace(id=7))
    assert json.loads(replay.body)["choices"][0]["message"]["content"] == "saved answer"
    assert resolve.await_count == 1
    assert attempt.await_count == 1
    changed = body.model_copy(update={"max_tokens": 10})
    with pytest.raises(HTTPException) as exc:
        await gateway.openai_chat_completions(request, changed, db, SimpleNamespace(id=7))
    assert exc.value.status_code == 409
    assert resolve.await_count == 1


@pytest.mark.asyncio
async def test_gateway_recovers_settlement_before_resolving_changed_route(db, monkeypatch):
    from modstore_server import llm_billing_recovery
    from modstore_server import openai_llm_gateway_api as gateway

    body = gateway.OAIChatCompletionRequest(
        model="xcauto-account", messages=[{"role": "user", "content": "hello"}]
    )
    digest = ledger.request_digest(
        {"operation": "openai_gateway_chat", "request": body.model_dump()}
    )
    _, row = ledger.begin(db, 7, KEY, digest, 90)
    ledger.mark_settling(db, row)
    recover = AsyncMock(
        return_value={"content": "settled", "provider": "openai", "model": "saved-model"}
    )
    resolve = AsyncMock(side_effect=AssertionError("must not resolve current route"))
    monkeypatch.setattr(llm_billing_recovery, "recover_receipt", recover)
    monkeypatch.setattr(gateway, "resolve_default_llm_route", resolve)
    request = SimpleNamespace(headers={"Idempotency-Key": KEY, "authorization": "Bearer token"})
    result = await gateway.openai_chat_completions(request, body, db, SimpleNamespace(id=7))
    assert json.loads(result.body)["choices"][0]["message"]["content"] == "settled"
    recover.assert_awaited_once_with(db, 7, KEY, "Bearer token", operation="chat", request=request)
    resolve.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["completed", "settling"])
@pytest.mark.parametrize("mapping", [{}, {"xcmax-reviewed": "xiaomi/mimo-v2.6-flash"}])
async def test_gateway_recovers_alias_before_reading_changed_configuration(
    db, monkeypatch, state, mapping
):
    from fastapi import Request

    from modstore_server import llm_billing_recovery as recovery
    from modstore_server import openai_llm_gateway_api as gateway
    from modstore_server.db.llm_chat import LlmCallLog

    body = gateway.OAIChatCompletionRequest(
        model="xcmax-reviewed", messages=[{"role": "user", "content": "hello"}]
    )
    original = {"operation": "openai_gateway_chat", "request": body.model_dump()}
    _, row = ledger.begin(db, 7, KEY, ledger.request_digest(original), 90)
    receipt = {
        "operation": "chat",
        "provider": "openai",
        "model": "gpt-4o-mini",
        "content": "paid answer",
        "billed": True,
        "charge_amount": "0.42",
        "hold_no": "AIH-alias",
        "request_id": "paid-alias",
        "usage": {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5},
        "conversation_id": None,
        "_history": original["request"]["messages"],
    }
    if state == "settling":
        ledger.prepare_settlement(db, row, receipt)
    else:
        ledger.finish(db, row, receipt)
    hold = {key: receipt[key] for key in ("hold_no", "request_id", "provider", "model")}
    read = AsyncMock(return_value={**hold, "status": "settled", "settled_amount": "0.42"})
    monkeypatch.setattr(recovery, "JavaWalletClient", lambda: SimpleNamespace(read_hold=read))
    monkeypatch.setenv("MODSTORE_LLM_POOL_ALIASES", json.dumps(mapping))
    aliases = Mock(wraps=gateway._pool_aliases)
    monkeypatch.setattr(gateway, "_pool_aliases", aliases)
    for name in (
        "_build_catalog_model_entries",
        "run_billed_llm_chat",
        "resolve_default_llm_route",
    ):
        monkeypatch.setattr(gateway, name, AsyncMock(side_effect=AssertionError("new execution")))
    for name in ("resolve_credentials", "resolve_chat_route_snapshot"):
        monkeypatch.setattr(gateway, name, Mock(side_effect=AssertionError("new credential read")))
    request = Request(
        {
            "type": "http",
            "headers": [(b"idempotency-key", KEY.encode()), (b"authorization", b"Bearer owner")],
        }
    )
    for _ in range(2):
        response = await gateway.openai_chat_completions(request, body, db, SimpleNamespace(id=7))
        result = json.loads(response.body)
        assert result["model"] == "openai/gpt-4o-mini"
        assert result["choices"][0]["message"]["content"] == "paid answer"
        assert result["xcagi"]["billed"] is True
    with pytest.raises(HTTPException) as mismatch:
        await gateway.openai_chat_completions(
            request, body.model_copy(update={"max_tokens": 10}), db, SimpleNamespace(id=7)
        )
    assert mismatch.value.status_code == 409
    assert read.await_count == (1 if state == "settling" else 0)
    assert db.query(LlmCallLog).count() == (1 if state == "settling" else 0)
    aliases.assert_not_called()


@pytest.mark.asyncio
async def test_gateway_alias_ends_receipt_read_before_catalog_await(db, monkeypatch):
    from fastapi import Request
    from sqlalchemy import inspect

    from modstore_server import openai_llm_gateway_api as gateway
    from modstore_server.models import User

    user = db.get(User, 7)
    monkeypatch.setenv("MODSTORE_LLM_POOL_ALIASES", '{"xcmax-reviewed":"openai/gpt-4o-mini"}')

    async def catalog(session, user_id, providers):
        assert session is db and user_id == 7 and providers == ("openai",)
        assert not db.in_transaction()
        assert inspect(user).expired
        return [
            {
                "id": "openai/gpt-4o-mini",
                "runtime_selectable": True,
                "chat_compatible": True,
                "pricing": {"platform_billing_ok": True},
            }
        ]

    route = ChatRouteSnapshot("openai", "gpt-4o-mini", "explicit", "platform", "r1", "key", None)
    monkeypatch.setattr(gateway, "_build_catalog_model_entries", catalog)
    monkeypatch.setattr(gateway, "resolve_credentials", lambda *args: ("key", None, "platform"))
    monkeypatch.setattr(gateway, "resolve_chat_route_snapshot", lambda *args: route)
    billed = AsyncMock(return_value={"provider": route.provider, "model": route.model})
    monkeypatch.setattr(gateway, "run_billed_llm_chat", billed)
    request = Request({"type": "http", "headers": [(b"idempotency-key", KEY.encode())]})
    body = gateway.OAIChatCompletionRequest(
        model="xcmax-reviewed", messages=[{"role": "user", "content": "hello"}]
    )
    await gateway.openai_chat_completions(request, body, db, user)
    assert billed.await_args.kwargs["route_snapshot"] is route
    assert (
        billed.await_args.kwargs["client_request_payload"]["request"]["model"] == "xcmax-reviewed"
    )


@pytest.mark.asyncio
async def test_gateway_does_not_reexecute_an_old_unmatched_receipt(db, monkeypatch):
    from modstore_server import openai_llm_gateway_api as gateway

    _, row = ledger.begin(db, 7, KEY, "legacy-route-digest", 90)
    ledger.finish(db, row, {"content": "prior paid answer"})
    resolve = AsyncMock(side_effect=AssertionError("must not issue a new request"))
    monkeypatch.setattr(gateway, "resolve_default_llm_route", resolve)
    body = gateway.OAIChatCompletionRequest(
        model="xcauto-account", messages=[{"role": "user", "content": "hello"}]
    )
    with pytest.raises(HTTPException) as exc:
        await gateway.openai_chat_completions(
            SimpleNamespace(headers={"Idempotency-Key": KEY}), body, db, SimpleNamespace(id=7)
        )
    assert exc.value.status_code == 409
    resolve.assert_not_awaited()


@pytest.mark.asyncio
async def test_native_auto_chat_replays_before_resolving_changed_route(db, monkeypatch):
    from modstore_server import llm_api, llm_api_merged

    snapshot = SimpleNamespace(provider="openai", model="model-a")
    resolve = AsyncMock(return_value=snapshot)
    receipt = {
        "ok": True,
        "content": "saved",
        "conversation_id": None,
        "usage": {},
        "charge_amount": "1.00",
        "hold_no": "hold-1",
        "key_source": "platform",
        "billed": True,
        "provider": "openai",
        "model": "model-a",
    }
    attempt = AsyncMock(return_value=receipt)
    monkeypatch.setattr(llm_api_merged, "_requested_chat_snapshot", resolve)
    monkeypatch.setattr(llm_billed_chat, "_run_sync_attempts", attempt)
    body = llm_api.LlmChatDTO(
        model="auto", messages=[{"role": "user", "content": "hello"}], client_request_id=KEY
    )
    request = SimpleNamespace(headers={})
    first = await llm_api.llm_chat(request, body, db, SimpleNamespace(id=7))
    resolve.side_effect = HTTPException(503, "changed route unavailable")
    replay = await llm_api.llm_chat(request, body, db, SimpleNamespace(id=7))
    assert first == replay and replay["content"] == "saved"
    assert resolve.await_count == 1 and attempt.await_count == 1


@pytest.mark.asyncio
async def test_native_auto_stream_replays_original_request_after_route_removal(
    billed, db, monkeypatch
):
    from modstore_server import llm_api, llm_api_merged

    route = ChatRouteSnapshot(
        provider="xiaomi",
        model="mimo-v2.6-flash",
        route_source="platform_configuration",
        key_source="platform",
        config_revision="r1",
        api_key="test-key",
        base_url=None,
    )
    resolve = AsyncMock(return_value=route)
    monkeypatch.setattr(llm_api_merged, "_requested_chat_snapshot", resolve)
    body = llm_api.LlmChatDTO(
        model="auto",
        messages=[{"role": "user", "content": "hello"}],
        client_request_id=KEY,
        tools=[{"type": "function", "function": {"name": "lookup"}}],
    )
    request = SimpleNamespace(state=SimpleNamespace(), headers={})
    first = await llm_api.llm_chat_stream(request, body, db, SimpleNamespace(id=7))
    events = _frames([frame async for frame in first.body_iterator])
    assert events[-1][0] == "done"
    resolve.side_effect = HTTPException(503, "removed route")
    response = await llm_api.llm_chat_stream(request, body, db, SimpleNamespace(id=7))
    replay = _frames([frame async for frame in response.body_iterator])
    assert replay == [("done", {**events[-1][1], "replayed": True})]
    billed.wallet.settle.assert_awaited_once()
    resolve.assert_awaited_once()
    with pytest.raises(HTTPException) as exc:
        await llm_api.llm_chat_stream(
            request, body.model_copy(update={"tools": []}), db, SimpleNamespace(id=7)
        )
    assert exc.value.status_code == 409
    resolve.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("overlong", ["job_id", "status", "preview_url"])
async def test_video_rejects_unbounded_provider_receipt_without_retry(db, monkeypatch, overlong):
    from modstore_server import llm_api, llm_key_resolver

    response = {"ok": True, "job_id": "video-id", "status": "pending", "preview_url": ""}
    response[overlong] = "x" * 3000
    send = AsyncMock(return_value=response)
    monkeypatch.setattr(llm_api, "video_dispatch", send)
    monkeypatch.setattr(
        llm_key_resolver, "resolve_credentials", lambda *args: ("key", None, "platform")
    )
    body = llm_api.LlmVideoDTO(
        provider="openai", model="video-model", prompt="test", client_request_id=KEY
    )
    for _ in range(2):
        with pytest.raises(HTTPException) as exc:
            await llm_api.llm_video(body, db, SimpleNamespace(id=7))
        assert exc.value.status_code == 409
    send.assert_awaited_once()


@pytest.mark.asyncio
async def test_voice_turn_replays_text_only_without_second_debit(db, monkeypatch):
    from modstore_server import voice_s2s_ws as voice

    wallet = SimpleNamespace(
        enabled=True,
        preauthorize=AsyncMock(return_value=WalletHold("voice-hold", Decimal("1"), True)),
        settle=AsyncMock(),
        release=AsyncMock(),
    )
    monkeypatch.setattr(voice, "JavaWalletClient", lambda **kw: wallet)
    monkeypatch.setattr(voice, "resolve_credentials", lambda *args: ("key", None, "platform"))
    monkeypatch.setattr(voice, "enforce_risk_limits", Mock())
    events = AsyncMock()
    monkeypatch.setattr(voice, "_send_json", events)

    async def chat(*args, **kwargs):
        yield {"type": "delta", "delta": "voice answer"}
        yield {
            "type": "usage",
            "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        }

    monkeypatch.setattr(voice, "chat_dispatch_stream", chat)
    args = dict(
        user=SimpleNamespace(id=7),
        db=db,
        auth_header="",
        provider="openai",
        model="chat-model",
        messages=[{"role": "user", "content": "voice test"}],
        max_tokens=200,
        voice="",
        rate=1,
        tts_enabled=False,
        cancel=__import__("asyncio").Event(),
        turn_id="voice-turn-test",
    )
    await voice._run_billed_s2s_turn(object(), **args)
    await voice._run_billed_s2s_turn(object(), **args)
    done = [arg.args[1] for arg in events.await_args_list if arg.args[1]["type"] == "text_done"]
    assert len(done) == 2 and done[1]["replayed"] is True
    assert done[0]["usage"]["total_tokens"] == 30
    assert wallet.settle.await_count == 1


@pytest.mark.asyncio
async def test_pat_recovery_uses_authenticated_request_and_bound_wallet_id(db, monkeypatch):
    from modstore_server import llm_billing_recovery as recovery

    _, row = ledger.begin(db, 7, KEY, "image-pat", 180)
    receipt = {
        "operation": "image_generation",
        "provider": "openai",
        "model": "gpt-image-2",
        "hold_no": "hold-1",
        "request_id": "attempt-1",
        "charge_amount": "0.42",
        "images": ["result"],
        "usage": {"prompt_tokens": 17, "completion_tokens": 42, "total_tokens": 59},
    }
    ledger.prepare_settlement(db, row, receipt)
    read = AsyncMock(
        return_value={
            **{k: receipt[k] for k in ("provider", "model", "hold_no", "request_id")},
            "status": "settled",
            "settled_amount": "0.42",
        }
    )
    request = SimpleNamespace(state=SimpleNamespace(llm_pat_user_id=7))
    factory = Mock(return_value=SimpleNamespace(read_hold=read))
    monkeypatch.setattr(recovery, "JavaWalletClient", factory)
    wrong = SimpleNamespace(state=SimpleNamespace(llm_pat_user_id=8))
    assert await recovery.recover_receipt(db, 7, KEY, "Bearer pat", request=wrong) is None
    factory.assert_not_called()
    assert await recovery.recover_receipt(db, 7, KEY, "Bearer pat", request=request) == receipt
    factory.assert_called_once_with(request=request)
    read.assert_awaited_once_with("Bearer pat", "hold-1", request_id="attempt-1")


@pytest.mark.asyncio
async def test_pat_wallet_read_uses_signed_internal_operation(monkeypatch):
    from modstore_server.llm_wallet_client import JavaWalletClient

    request = SimpleNamespace(state=SimpleNamespace(llm_pat_user_id=7))
    client = JavaWalletClient(request=request)
    client.gateway.backend = "java"
    monkeypatch.setattr(client, "validate_pat", Mock())
    post = AsyncMock(return_value={"ok": True, "hold": {"hold_no": "hold-1"}})
    monkeypatch.setattr(client, "_post", post)
    assert await client.read_hold("Bearer pat", "hold-1") is None
    assert await client.read_hold("Bearer pat", "hold-1", request_id="attempt-1") == {
        "hold_no": "hold-1"
    }
    client.validate_pat.assert_called_once_with("Bearer pat")
    post.assert_awaited_once_with(
        "/api/wallet/ai/read",
        "Bearer pat",
        {"hold_no": "hold-1", "request_id": "attempt-1", "idempotency_key": "attempt-1:read"},
    )
