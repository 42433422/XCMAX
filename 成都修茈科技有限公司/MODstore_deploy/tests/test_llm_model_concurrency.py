"""Adaptive per-model admission: shared limit, leases, and AIMD feedback."""

from __future__ import annotations

import asyncio
import importlib.util
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from alembic.migration import MigrationContext
from alembic.operations import Operations
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


@pytest.mark.skipif(
    not os.environ.get("RETORT_TEST_POSTGRES_DSN"), reason="isolated PostgreSQL required"
)
def test_postgres_migrated_limit_admits_one_of_two_sessions():
    path = Path(__file__).parents[1] / "alembic/versions/20261124_model_concurrency.py"
    spec = importlib.util.spec_from_file_location("model_concurrency_migration", path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    url = os.environ["RETORT_TEST_POSTGRES_DSN"]
    schema = f"model_concurrency_{uuid4().hex}"
    admin = create_engine(url)
    engine = create_engine(
        url, connect_args={"options": f"-csearch_path={schema} -cstatement_timeout=10000"}
    )
    created = False
    try:
        assert admin.dialect.name == "postgresql"
        with admin.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        created = True
        with engine.begin() as connection:
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
            assert {"llm_model_concurrency", "llm_model_leases"} <= set(
                inspect(connection).get_table_names(schema=schema)
            )

        sessions = sessionmaker(bind=engine)
        with sessions() as session:
            _controller().seed(session, KEY, 1)
        barrier = Barrier(2)

        def compete(_):
            controller = _controller()
            with sessions() as session:
                session.connection()
                barrier.wait(timeout=15)
                lease = asyncio.run(_acquire(controller, session))
                # Preserve the winning lease until both attempts have returned.
                barrier.wait(timeout=15)
                if lease is not None:
                    controller.release(session, lease)
                barrier.wait(timeout=15)
                retry = asyncio.run(_acquire(controller, session)) if lease is None else None
                return lease, retry

        with ThreadPoolExecutor(max_workers=2) as workers:
            outcomes = list(workers.map(compete, range(2)))
        assert sum(lease is None for lease, _ in outcomes) == 1
        winner = next(lease for lease, _ in outcomes if lease is not None)
        assert winner.enforced
        retry = next(retry for lease, retry in outcomes if lease is None)
        assert retry is not None and retry.enforced and retry.lease_id != winner.lease_id
    finally:
        engine.dispose()
        try:
            if created:
                with admin.begin() as connection:
                    connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        finally:
            admin.dispose()


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


async def test_byok_cooldown_is_isolated_by_owner_and_route_revision(db):
    controller = _controller()
    keys = [
        concurrency_key(
            "litellm",
            "account-model",
            key_source="user_override",
            user_id=owner,
            config_revision=revision,
        )
        for owner, revision in [(7, "a"), (8, "a"), (7, "b")]
    ]
    controller.report_throttled(db, keys[0], 60)
    assert await _acquire(controller, db, keys[0]) is None
    for key in [KEY, *keys[1:]]:
        assert await _acquire(controller, db, key) is not None
