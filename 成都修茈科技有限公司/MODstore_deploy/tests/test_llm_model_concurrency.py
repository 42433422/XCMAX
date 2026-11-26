"""Adaptive per-model admission: shared limit, leases, and AIMD feedback."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from modstore_server.db.llm_chat import LlmModelConcurrency, LlmModelLease
from modstore_server.llm_model_concurrency import (
    SUCCESS_STREAK_TO_GROW,
    ConcurrencyController,
    Lease,
    concurrency_key,
    is_throttled,
    retry_after_seconds,
)
from tests.test_llm_client_requests import db as db

KEY = concurrency_key("litellm", "account-model")


def _controller(**options) -> ConcurrencyController:
    return ConcurrencyController(enabled=True, poll_s=0.0, **options)


async def _acquire(controller, db, key=KEY, wait_s=0.0, timeout_s=30.0):
    return await controller.acquire(db, key, wait_s=wait_s, timeout_s=timeout_s)


async def test_acquire_enforces_the_shared_limit_and_releases(db):
    controller = _controller()
    controller.seed(db, KEY, 2)
    first = await _acquire(controller, db)
    second = await _acquire(controller, db)
    assert isinstance(first, Lease) and first.enforced
    assert isinstance(second, Lease) and second.enforced
    assert controller.inflight(db, KEY) == 2
    assert await _acquire(controller, db) is None
    controller.release(db, first)
    assert controller.inflight(db, KEY) == 1
    assert (await _acquire(controller, db)) is not None
    assert controller.inflight(db, KEY) == 2
    controller.release(db, second)
    assert controller.inflight(db, KEY) == 1


async def test_bounded_wait_returns_none_instead_of_queueing_forever(db):
    controller = _controller()
    controller.seed(db, KEY, 1)
    assert (await _acquire(controller, db)) is not None
    started = datetime.now(UTC)
    assert await _acquire(controller, db, wait_s=0.2) is None
    assert (datetime.now(UTC) - started).total_seconds() < 3


async def test_expired_lease_is_reclaimed_after_a_crash(db):
    controller = _controller()
    controller.seed(db, KEY, 1)
    db.add(
        LlmModelLease(
            lease_id="dead-worker",
            model_key=KEY,
            acquired_at=datetime.now(UTC) - timedelta(hours=1),
            expires_at=datetime.now(UTC) - timedelta(seconds=1),
        )
    )
    db.commit()
    fresh = await _acquire(controller, db)
    assert fresh is not None and fresh.enforced
    assert controller.inflight(db, KEY) == 1


async def test_release_is_idempotent(db):
    controller = _controller()
    controller.seed(db, KEY, 1)
    lease = await _acquire(controller, db)
    controller.release(db, lease)
    controller.release(db, lease)
    assert controller.inflight(db, KEY) == 0
    controller.release(db, Lease(KEY, "", False))


def test_throttle_halves_the_limit_and_success_grows_it_back(db):
    controller = _controller()
    controller.seed(db, KEY, 8)
    controller.report_throttled(db, KEY, 5.0)
    assert controller.current_limit(db, KEY) == 4
    row = db.query(LlmModelConcurrency).filter_by(model_key=KEY).one()
    assert row.cooldown_until is not None

    for _ in range(SUCCESS_STREAK_TO_GROW * 2):
        controller.report_success(db, KEY)
    assert controller.current_limit(db, KEY) == 4

    row.cooldown_until = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()
    for _ in range(SUCCESS_STREAK_TO_GROW):
        controller.report_success(db, KEY)
    assert controller.current_limit(db, KEY) == 5


def test_throttle_never_drops_below_one_and_success_never_exceeds_max(db):
    controller = _controller()
    controller.seed(db, KEY, 2)
    for _ in range(5):
        controller.report_throttled(db, KEY, 1.0)
    assert controller.current_limit(db, KEY) == 1
    row = db.query(LlmModelConcurrency).filter_by(model_key=KEY).one()
    row.cooldown_until = None
    db.commit()
    for _ in range(SUCCESS_STREAK_TO_GROW * 10):
        controller.report_success(db, KEY)
    assert controller.current_limit(db, KEY) == 2


def test_missing_tables_fail_open_instead_of_blocking_chat():
    session = sessionmaker(bind=create_engine("sqlite:///:memory:"))()
    try:
        controller = _controller()
        lease = asyncio.run(controller.acquire(session, KEY, wait_s=0.0, timeout_s=30))
        assert lease is not None and lease.enforced is False
        controller.release(session, lease)
        controller.report_throttled(session, KEY, 1.0)
        controller.report_success(session, KEY)
    finally:
        session.close()


def test_error_classification_helpers():
    class Response:
        headers = {"retry-after": "7"}

    class Throttled(Exception):
        status_code = 429
        response = Response()

    assert is_throttled(Throttled())
    assert not is_throttled(RuntimeError())
    assert retry_after_seconds(Throttled()) == 7.0
    assert retry_after_seconds(RuntimeError()) == 2.0
