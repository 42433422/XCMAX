"""A client idempotency key runs one billed execution and replays its receipt."""

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from modstore_server import llm_billed_chat
from modstore_server import llm_client_requests as ledger
from modstore_server.llm_billing_values import WalletHold
from modstore_server.llm_key_resolver import ChatRouteSnapshot

KEY = "a" * 32


@pytest.fixture
def db():
    from modstore_server.models import Base, User

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add_all(
        [
            User(id=7, username="ledger-user-7", password_hash="test-only"),
            User(id=8, username="ledger-user-8", password_hash="test-only"),
        ]
    )
    session.commit()
    yield session
    session.close()


def test_ledger_replays_completed_and_refuses_live_or_different_requests(db):
    assert ledger.lookup(db, 7, KEY, 90) == "not_found"
    outcome, row = ledger.begin(db, 7, KEY, "d1", 90)
    assert outcome == "run" and row.attempts == 1
    assert ledger.begin(db, 7, KEY, "d1", 90) == ("processing", None)
    assert ledger.begin(db, 7, KEY, "d2", 90) == ("conflict", None)
    assert ledger.begin(db, 8, KEY, "d1", 90)[0] == "run"
    ledger.finish(db, row, {"ok": True, "content": "synthetic"})
    assert ledger.lookup(db, 7, KEY, 90) == "completed"
    assert ledger.begin(db, 7, KEY, "d1", 90) == (
        "replay",
        {"ok": True, "content": "synthetic"},
    )
    ledger.finish(db, row, None)
    assert ledger.lookup(db, 7, KEY, 90) == "completed"


def test_only_an_unsettled_attempt_may_run_again(db):
    _, row = ledger.begin(db, 7, KEY, "d1", 90)
    ledger.finish(db, row, None)
    assert ledger.lookup(db, 7, KEY, 90) == "failed"
    outcome, again = ledger.begin(db, 7, KEY, "d1", 90)
    assert outcome == "run" and again.attempts == 2
    assert ledger.attempt_request_id(7, KEY, 1) != ledger.attempt_request_id(7, KEY, 2)
    again.updated_at = datetime.now(UTC) - timedelta(seconds=400)
    db.commit()
    assert ledger.lookup(db, 7, KEY, 90) == "failed"
    ledger.mark_settling(db, again)
    ledger.finish(db, again, None)
    again.updated_at = datetime.now(UTC) - timedelta(days=1)
    db.commit()
    assert ledger.lookup(db, 7, KEY, 90) == "settling"
    assert ledger.begin(db, 7, KEY, "d1", 90) == ("processing", None)


def test_completed_receipt_is_bound_to_user_key_and_digest(db):
    _, row = ledger.begin(db, 7, KEY, "digest", 90)
    ledger.finish(db, row, {"ok": True, "images": ["receipt"]})
    assert ledger.completed_receipt(db, 7, KEY, "digest") == (
        "replay",
        {"ok": True, "images": ["receipt"]},
    )
    assert ledger.completed_receipt(db, 7, KEY, "different") == ("conflict", None)
    assert ledger.completed_receipt(db, 8, KEY, "digest") is None


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
        preauthorize=AsyncMock(
            return_value=WalletHold("synthetic-hold", Decimal(".01"), True)
        ),
        settle=AsyncMock(),
        release=AsyncMock(),
    )
    monkeypatch.setattr(llm_billed_chat, "JavaWalletClient", lambda **kwargs: wallet)
    monkeypatch.setattr(llm_billed_chat, "enforce_risk_limits", Mock())
    monkeypatch.setattr(
        llm_billed_chat, "estimate_preauthorization", lambda *a: Decimal(".01")
    )
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

    return SimpleNamespace(call=call, wallet=wallet, sent=sent, monkeypatch=monkeypatch)


@pytest.mark.asyncio
async def test_same_key_resend_replays_the_receipt_without_a_second_charge(billed, db):
    first = await billed.call()
    assert [event for event, _ in first] == ["status", "meta", "delta", "done"]
    assert first[0][1]["state"] == "accepted"
    assert first[3][1]["finish_reason"] == "length"
    assert first[1][1]["request_id"] == ledger.attempt_request_id(7, KEY, 1) + "-0"
    second = await billed.call()
    assert [event for event, _ in second] == ["done"] and second[0][1][
        "replayed"
    ] is True
    assert second[0][1]["content"] == "synthetic answer"
    assert (
        billed.wallet.preauthorize.await_count == 1 == billed.wallet.settle.await_count
    )
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
async def test_a_live_key_is_refused_instead_of_run_twice(billed, db):
    ledger.begin(db, 7, KEY, "other-digest", 90)
    with pytest.raises(HTTPException) as refused:
        await billed.call()
    assert (
        refused.value.status_code == 409 and refused.value.detail["state"] == "conflict"
    )
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
    read = AsyncMock(
        return_value={**hold, "status": "settled", "settled_amount": "0.43"}
    )
    monkeypatch.setattr(
        recovery, "JavaWalletClient", lambda: SimpleNamespace(read_hold=read)
    )

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
        preauthorize=AsyncMock(
            return_value=WalletHold("sync-hold", Decimal("1"), True)
        ),
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
    monkeypatch.setattr(
        llm_billed_once, "recover_receipt", AsyncMock(return_value=None)
    )

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
    monkeypatch.setattr(
        recovery, "JavaWalletClient", lambda: SimpleNamespace(read_hold=read)
    )
    receipt = await request()
    assert receipt["content"] == "saved"
    assert receipt["pricing"]["currency"] == "CNY"
    assert "_history" not in receipt
    assert await request() == receipt
    send.assert_awaited_once()
    wallet.settle.assert_awaited_once()


@pytest.mark.asyncio
async def test_video_request_replays_same_supplier_job_id(db, monkeypatch):
    from modstore_server import llm_api, llm_key_resolver

    send = AsyncMock(
        return_value={
            "ok": True,
            "job_id": "video-id",
            "status": "pending",
            "raw": {
                "usage": {"input_tokens": 2, "output_tokens": 0, "total_tokens": 2}
            },
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
async def test_voice_turn_replays_text_only_without_second_debit(db, monkeypatch):
    from modstore_server import voice_s2s_ws as voice

    wallet = SimpleNamespace(
        enabled=True,
        preauthorize=AsyncMock(
            return_value=WalletHold("voice-hold", Decimal("1"), True)
        ),
        settle=AsyncMock(),
        release=AsyncMock(),
    )
    monkeypatch.setattr(voice, "JavaWalletClient", lambda **kw: wallet)
    monkeypatch.setattr(
        voice, "resolve_credentials", lambda *args: ("key", None, "platform")
    )
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
    done = [
        arg.args[1]
        for arg in events.await_args_list
        if arg.args[1]["type"] == "text_done"
    ]
    assert len(done) == 2 and done[1]["replayed"] is True
    assert done[0]["usage"]["total_tokens"] == 30
    assert wallet.settle.await_count == 1
