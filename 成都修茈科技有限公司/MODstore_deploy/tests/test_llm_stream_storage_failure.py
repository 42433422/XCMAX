"""A failure to persist late stream bookkeeping cannot authorize another model call."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from modstore_server import llm_billed_chat
from modstore_server import llm_client_requests as ledger
from modstore_server.db.llm_chat import LlmClientRequest
from modstore_server.llm_billing_values import WalletHold
from modstore_server.llm_gateway_contract import StreamLimitError
from tests import test_llm_client_requests as client_tests

db = client_tests.db
billed = client_tests.billed


def _reject_settling(db):
    db.execute(
        text(
            "CREATE TEMP TRIGGER fail_stream_receipt BEFORE UPDATE ON llm_client_requests "
            "WHEN NEW.state = 'settling' BEGIN "
            "SELECT RAISE(ABORT, 'injected SQLite receipt transaction failure'); END"
        )
    )
    db.commit()


async def _request(billed, db, route, *, failover=False):
    return await llm_billed_chat.stream_billed_llm_chat(
        request=SimpleNamespace(state=SimpleNamespace(), headers={}),
        db=db,
        user=SimpleNamespace(id=7),
        provider=route.provider,
        model=route.model,
        messages=[{"role": "user", "content": "synthetic"}],
        route_snapshot=None if failover else route,
        client_request_id=client_tests.KEY,
    )


def _funding(billed, funding):
    if funding == "byok":
        return replace(billed.route, key_source="user_override")
    billed.wallet.enabled = False
    billed.wallet.preauthorize.return_value = WalletHold("original-hold", Decimal("0"), False)
    return billed.route


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["event", "exception"])
@pytest.mark.parametrize("funding", ["disabled", "byok"])
async def test_post_dispatch_storage_failure_cannot_make_limit_retryable(billed, db, kind, funding):
    route = _funding(billed, funding)

    async def overflow(provider, **kwargs):
        billed.sent.append((provider, kwargs["model"]))
        _reject_settling(db)
        if kind == "exception":
            raise StreamLimitError("model stream wire byte limit exceeded")
        yield {
            "type": "error",
            "code": "model_stream_limit_exceeded",
            "status": 502,
            "error": "model stream wire byte limit exceeded",
            "outcome_unknown": True,
            "non_retryable": True,
        }

    billed.monkeypatch.setattr(llm_billed_chat, "chat_dispatch_stream", overflow)
    response = await _request(billed, db, route)
    frames = []
    storage_error = None
    try:
        async for frame in response.body_iterator:
            frames.append(frame)
    except SQLAlchemyError as exc:
        storage_error = exc
    finally:
        db.rollback()
        db.execute(text("DROP TRIGGER IF EXISTS fail_stream_receipt"))
        db.commit()

    row = db.query(LlmClientRequest).filter_by(user_id=7, client_request_id=client_tests.KEY).one()
    row.updated_at = datetime.now(UTC) - timedelta(days=1)
    db.commit()
    outcome, _ = ledger.begin(db, 7, client_tests.KEY, row.request_sha256, 90)
    assert outcome == "processing", f"original call became replayable: {outcome}; {storage_error!r}"
    assert row.state == "settling" and row.attempts == 1
    assert billed.sent == [(route.provider, route.model)]
    billed.wallet.release.assert_not_awaited()
    billed.wallet.settle.assert_not_awaited()
    assert storage_error is None
    last = client_tests._frames(frames)[-1]
    assert last[0] == "error" and last[1]["code"] == "model_stream_limit_exceeded"


@pytest.mark.asyncio
@pytest.mark.parametrize("funding", ["disabled", "byok"])
async def test_admission_storage_failure_prevents_original_transport(billed, db, funding):
    route = _funding(billed, funding)
    _reject_settling(db)
    response = await _request(billed, db, route)
    try:
        with pytest.raises(SQLAlchemyError, match="injected SQLite receipt transaction failure"):
            _ = [frame async for frame in response.body_iterator]
    finally:
        db.rollback()
        db.execute(text("DROP TRIGGER IF EXISTS fail_stream_receipt"))
        db.commit()
    assert billed.sent == []
    billed.wallet.preauthorize.assert_not_awaited()
    billed.wallet.release.assert_not_awaited()
    billed.wallet.settle.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("funding", ["disabled", "byok"])
async def test_definitive_provider_refusal_keeps_existing_failover_contract(billed, db, funding):
    route = _funding(billed, funding)
    backup = replace(route, provider="openai", model="gpt-4o-mini")
    billed.monkeypatch.setattr(
        llm_billed_chat,
        "resolve_chat_route_snapshot",
        lambda _db, _uid, provider, _model, **_kwargs: (
            route if provider == route.provider else backup
        ),
    )
    billed.monkeypatch.setattr(
        llm_billed_chat,
        "list_chat_failover_candidates",
        AsyncMock(return_value=[(route.provider, route.model), (backup.provider, backup.model)]),
    )

    async def dispatch(provider, **kwargs):
        billed.sent.append((provider, kwargs["model"]))
        if len(billed.sent) == 1:
            yield {"type": "error", "status": 429, "error": "provider rejected admission"}
        else:
            yield {"type": "delta", "delta": "accepted fallback"}
            yield {"type": "finish", "finish_reason": "stop"}

    billed.monkeypatch.setattr(llm_billed_chat, "chat_dispatch_stream", dispatch)
    response = await _request(billed, db, route, failover=True)
    frames = client_tests._frames([frame async for frame in response.body_iterator])
    assert billed.sent == [(route.provider, route.model), (backup.provider, backup.model)]
    assert frames[-1][0] == "done" and frames[-1][1]["content"] == "accepted fallback"
    assert ledger.lookup(db, 7, client_tests.KEY, 90) == "completed"
    response = await _request(billed, db, route, failover=True)
    replay = client_tests._frames([frame async for frame in response.body_iterator])
    assert len(replay) == 1 and replay[0][1]["replayed"] is True
    assert len(billed.sent) == 2
