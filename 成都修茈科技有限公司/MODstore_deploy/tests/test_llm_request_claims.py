"""SQL request ownership, attempt fencing, and atomic receipt publication."""

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from threading import Event
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from modstore_server import llm_client_requests as ledger
from tests.llm_request_support import KEY
from tests.llm_request_support import db as db


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


def test_request_admission_refreshes_stale_orm_state_before_reclaim(tmp_path):
    from modstore_server.db.llm_chat import LlmClientRequest
    from modstore_server.models import Base, User

    engine = create_engine(
        f"sqlite:///{tmp_path / 'request-leases.sqlite'}", connect_args={"timeout": 0.2}
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    try:
        with sessions() as first, sessions() as stale:
            first.add(User(id=7, username="lease-user", password_hash="test-only"))
            first.commit()
            _, row = ledger.begin(first, 7, KEY, "same-request", 90)
            ledger.finish(first, row, None)
            cached = stale.query(LlmClientRequest).filter_by(client_request_id=KEY).one()
            assert cached.state == "failed"
            assert ledger.begin(first, 7, KEY, "same-request", 90)[0] == "run"
            assert ledger.begin(stale, 7, KEY, "same-request", 90) == ("processing", None)
            assert cached.attempts == 2
            ledger.mark_settling(first, row)
    finally:
        engine.dispose()


@pytest.mark.parametrize("transition", ["dispatch", "release", "settlement", "success", "cleanup"])
def test_reclaimed_request_rejects_late_handler_even_after_orm_refresh(tmp_path, transition):
    from modstore_server.models import Base, User

    engine = create_engine(f"sqlite:///{tmp_path / 'request-generations.sqlite'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    try:
        with sessions() as old, sessions() as current:
            old.add(User(id=7, username="generation-user", password_hash="test-only"))
            old.commit()
            _, original = ledger.begin(old, 7, KEY, "same-request", 90)
            original.updated_at = datetime.now(UTC) - timedelta(seconds=400)
            old.commit()
            outcome, owned = ledger.begin(current, 7, KEY, "same-request", 90)
            assert outcome == "run" and owned.attempts == 2
            pending = {"request_id": "current-attempt", "hold_no": "current-hold"}
            ledger.prepare_settlement(current, owned, pending)
            old.expire(original)
            assert original.attempts == 2  # ORM refresh must not grant the old handler ownership.

            with pytest.raises(HTTPException) as exc:
                if transition == "dispatch":
                    ledger.mark_settling(old, original)
                elif transition == "release":
                    ledger.confirmed_no_charge(old, original)
                elif transition == "settlement":
                    ledger.prepare_settlement(old, original, {"request_id": "old-attempt"})
                else:
                    ledger.finish(
                        old,
                        original,
                        {"request_id": "old-attempt"} if transition == "success" else None,
                    )
            assert exc.value.status_code == 409
            current.refresh(owned)
            assert owned.attempts == 2 and owned.state == "settling"
            assert json.loads(owned.done_json) == {"pending_settlement": pending}
    finally:
        engine.dispose()


@pytest.mark.parametrize("operation", ["chat", "image_generation"])
@pytest.mark.parametrize("first_fails", [False, True])
def test_sqlite_concurrent_settlement_recovery_publishes_once(
    tmp_path, monkeypatch, operation, first_fails
):
    from modstore_server import llm_billing_recovery as recovery
    from modstore_server.db.llm_chat import (
        ChatConversation,
        ChatMessage,
        LlmCallLog,
        LlmClientRequest,
    )
    from modstore_server.models import Base, User

    engine = create_engine(
        f"sqlite:///{tmp_path / 'billing.sqlite'}",
        connect_args={"check_same_thread": False, "timeout": 10},
        pool_size=2,
        max_overflow=0,
    )
    Base.metadata.create_all(
        engine,
        tables=[
            model.__table__
            for model in (User, ChatConversation, ChatMessage, LlmCallLog, LlmClientRequest)
        ],
    )
    sessions = sessionmaker(bind=engine)
    receipt = {
        "ok": True,
        "operation": operation,
        "provider": "openai",
        "model": "model-a",
        "hold_no": "AIH-concurrent",
        "request_id": "request-concurrent",
        "charge_amount": "0.42",
        "usage": {"prompt_tokens": 17, "completion_tokens": 42, "total_tokens": 59},
    }
    if operation == "chat":
        receipt.update(
            content="saved answer",
            conversation_id=None,
            _history=[{"role": "user", "content": "saved question"}],
        )
    else:
        receipt["images"] = ["saved-image"]
    with sessions() as db:
        db.add(User(id=7, username="concurrent-user", password_hash="test-only"))
        db.commit()
        _, row = ledger.begin(db, 7, KEY, "digest", 180)
        ledger.prepare_settlement(db, row, receipt)

    hold = {name: receipt[name] for name in ("provider", "model", "hold_no", "request_id")}
    read_hold = AsyncMock(return_value={**hold, "status": "settled", "settled_amount": "0.42"})
    monkeypatch.setattr(recovery, "JavaWalletClient", lambda: SimpleNamespace(read_hold=read_hold))
    first_write, release_first, second_lock, second_finished = (Event() for _ in range(4))
    original_lock = ledger.lock_request

    def observed_lock(db, user_id, key):
        if db.info["worker"] == "second":
            second_lock.set()
        return original_lock(db, user_id, key)

    def pause_first_write(db, _context, _instances):
        if db.info["worker"] == "first" and db.new:
            first_write.set()
            assert release_first.wait(10), "first completion was not released"
            if first_fails:
                raise RuntimeError("interrupted completion")

    def recover(worker):
        try:
            with sessions() as db:
                db.info["worker"] = worker
                event.listen(db, "before_flush", pause_first_write)
                return asyncio.run(recovery.recover_receipt(db, 7, KEY, "owner-token"))
        finally:
            if worker == "second":
                second_finished.set()

    monkeypatch.setattr(ledger, "lock_request", observed_lock)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(recover, "first")
            try:
                assert first_write.wait(10), "first completion did not reach its write"
                second = pool.submit(recover, "second")
                assert second_lock.wait(10), "second recovery did not attempt to lock"
                # Keep the first transaction open while the other connection tries
                # to finish. Without serialization it commits a duplicate receipt.
                second_finished.wait(1)
            finally:
                release_first.set()
            if first_fails:
                with pytest.raises(RuntimeError, match="interrupted completion"):
                    first.result(timeout=10)
            else:
                first_receipt = first.result(timeout=10)
            completed = second.result(timeout=10)
        with sessions() as db:
            logs = db.query(LlmCallLog).all()
            assert len(logs) == 1
            assert logs[0].charge_amount == Decimal("0.42") and logs[0].total_tokens == 59
            assert db.query(ChatConversation).count() == (1 if operation == "chat" else 0)
            assert db.query(ChatMessage).count() == (2 if operation == "chat" else 0)
            assert ledger.completed_receipt(db, 7, KEY, "digest") == ("replay", completed)
        if not first_fails:
            assert completed == first_receipt
        assert read_hold.await_count == 2
    finally:
        release_first.set()
        engine.dispose()
