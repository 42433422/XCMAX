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
    from modstore_server.models import Base

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
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
async def test_an_upstream_failure_frees_the_key_for_a_new_attempt(billed, db):
    async def failing(*_args, **_kwargs):
        raise TimeoutError("synthetic upstream timeout")
        yield {}

    billed.monkeypatch.setattr(llm_billed_chat, "chat_dispatch_stream", failing)
    events = await billed.call()
    assert [event for event, _ in events] == ["status", "meta", "error"]
    assert ledger.lookup(db, 7, KEY, 90) == "failed"
    billed.wallet.settle.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_live_key_is_refused_instead_of_run_twice(billed, db):
    ledger.begin(db, 7, KEY, "other-digest", 90)
    with pytest.raises(HTTPException) as refused:
        await billed.call()
    assert (
        refused.value.status_code == 409 and refused.value.detail["state"] == "conflict"
    )
    billed.wallet.preauthorize.assert_not_awaited()
