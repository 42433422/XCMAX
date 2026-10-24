"""Real transaction and stream boundaries of the admin control plane."""

import asyncio
import json
import sqlite3
from contextlib import contextmanager
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.models.user import Session, User
from app.fastapi_routes import xcmax_admin
from app.utils.time import utc_now_naive


@pytest.fixture
def profiles_client(tmp_path, monkeypatch):
    from app.db import session as database

    engine = create_engine(
        f"sqlite:///{tmp_path / 'profiles.sqlite3'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    # Use the production context manager: it commits on an ordinary early return.
    monkeypatch.setattr(database, "SessionLocal", sessions)
    monkeypatch.setattr(xcmax_admin, "_require_market_admin_session", lambda request: None)
    app = FastAPI()
    app.include_router(xcmax_admin.router)
    with TestClient(app) as client:
        yield client, sessions
    engine.dispose()


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize(
    "invalid_fields",
    [
        {"tier": "personal", "account_tier": "pro"},
        {"industry_id": "unlicensed", "entitled_industries": ["allowed"]},
    ],
)
def test_rejected_profile_does_not_create_bind_or_rename(profiles_client, existing, invalid_fields):
    client, sessions = profiles_client
    if existing:
        with sessions.begin() as db:
            db.add(User(username="original", password="unused", market_user_id=123))
    response = client.put(
        "/api/xcmax/admin/users/123/profile", json={"username": "changed", **invalid_fields}
    )
    assert response.status_code == 422
    with sessions() as db:
        rows = db.query(User).all()
        assert [(row.username, row.market_user_id, row.account_tier) for row in rows] == (
            [("original", 123, None)] if existing else []
        )


@pytest.mark.parametrize("existing", [False, True])
def test_valid_profile_commits_one_authoritative_market_identity(profiles_client, existing):
    client, sessions = profiles_client
    if existing:
        with sessions.begin() as db:
            db.add(User(username="original", password="unchanged", market_user_id=123))
    response = client.put(
        "/api/xcmax/admin/users/123/profile",
        json={
            "username": "changed",
            "tier": "enterprise",
            "account_tier": "pro",
            "industry_id": "allowed",
            "entitled_industries": ["allowed"],
        },
    )
    assert response.status_code == 200
    assert response.json()["data"]["market_user_id"] == 123
    with sessions() as db:
        row = db.query(User).one()
        assert (row.username, row.market_user_id, row.account_tier) == ("changed", 123, "pro")
        assert row.tier == "enterprise"
        assert row.industry_id == "allowed"
        assert row.entitled_industries == ["allowed"]
        assert row.password == ("unchanged" if existing else "")


@pytest.mark.asyncio
async def test_sse_resumes_from_last_delivered_cursor_after_store_failure(monkeypatch):
    from app.db import xcmax_sync

    calls = []
    attempts = 0

    class Store:
        def get_changes(self, *, since_cursor, limit):
            nonlocal attempts
            calls.append((since_cursor, limit))
            attempts += 1
            if attempts == 2:
                raise RuntimeError("temporary read failure")
            return [{"id": 17 if attempts == 1 else 19, "entity_type": "synthetic"}]

    monkeypatch.setattr(xcmax_sync, "SyncDb", Store)
    sleep = AsyncMock()
    monkeypatch.setattr(xcmax_admin.asyncio, "sleep", sleep)
    request = AsyncMock()
    request.is_disconnected.side_effect = [False, False, False, True]
    events = [item async for item in xcmax_admin._sync_sse_generator(request, 12)]
    assert len(events) == 4
    payloads = [json.loads(item.removeprefix("data: ")) for item in events]
    assert payloads[0]["type"] == "connected"
    assert payloads[1]["cursor"] == 17
    assert payloads[2] == {"type": "error", "message": "temporary read failure"}
    assert payloads[3]["cursor"] == 19
    assert calls == [(12, 50), (17, 50), (17, 50)]
    assert sleep.await_count == 3


@pytest.mark.asyncio
async def test_sse_closes_sqlite_connections_before_yield_and_cancellation(tmp_path, monkeypatch):
    from app.db import xcmax_sync

    monkeypatch.setattr(xcmax_sync, "_db_path", tmp_path / "sync.sqlite3")
    original_connection = xcmax_sync._get_conn
    opened = []
    closed = []

    @contextmanager
    def tracked_connection():
        with original_connection() as connection:
            opened.append(connection)
            yield connection
        closed.append(connection)

    monkeypatch.setattr(xcmax_sync, "_get_conn", tracked_connection)
    sleeping = asyncio.Event()
    release = asyncio.Event()

    async def pause(_interval):
        sleeping.set()
        await release.wait()

    monkeypatch.setattr(xcmax_admin.asyncio, "sleep", pause)
    request = AsyncMock()
    request.is_disconnected.return_value = False
    stream = xcmax_admin._sync_sse_generator(request, 0)
    assert '"connected"' in await anext(stream)
    assert '"heartbeat"' in await anext(stream)
    assert opened and opened == closed
    poll = asyncio.create_task(anext(stream))
    await sleeping.wait()
    poll.cancel()
    with pytest.raises(asyncio.CancelledError):
        await poll
    assert opened == closed
    await stream.aclose()
    for connection in opened:
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            connection.execute("SELECT 1")


@pytest.fixture
def entitlements_client(tmp_path, monkeypatch):
    import app.db as database
    from app.db import session as session_database
    from app.db import xcmax_sync
    from app.services.xcmax_sync_service import _write_sync_meta

    engine = create_engine(
        f"sqlite:///{tmp_path / 'accounts.sqlite3'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    # Keep the real session context managers and both SQLite persistence layers.
    monkeypatch.setattr(database, "HostSessionLocal", sessions)
    monkeypatch.setattr(session_database, "SessionLocal", sessions)
    monkeypatch.setattr(xcmax_sync, "_db_path", tmp_path / "sync.sqlite3")
    with sessions.begin() as db:
        db.add(User(id=1, username="current-user", password="unused", market_user_id=101))
        db.add(
            Session(
                session_id="snapshot-session",
                user_id=1,
                market_user_id=101,
                account_kind="enterprise",
                company_brand="shared-brand",
                expires_at=utc_now_naive() + timedelta(hours=1),
            )
        )
    app = FastAPI()
    app.include_router(xcmax_admin.router)
    try:
        with TestClient(app) as client:
            yield client, sessions, _write_sync_meta
    finally:
        engine.dispose()


@pytest.mark.parametrize("impersonating", [False, True])
@pytest.mark.parametrize("stored_identity", ["owned", "absent", "foreign", "missing"])
def test_bound_entitlement_snapshot_never_falls_back_to_an_alias(
    entitlements_client, impersonating, stored_identity
):
    client, sessions, write_snapshot = entitlements_client
    market_user_id = 303 if impersonating else 101
    if impersonating:
        with sessions.begin() as db:
            row = db.query(Session).one()
            row.impersonating_market_user_id = market_user_id
            row.impersonating_username = "managed-user"
    expected = {"market_user_id": str(market_user_id), "meta": {"updated_at_ms": 10}}
    stored = dict(expected)
    if stored_identity == "foreign":
        stored["market_user_id"] = "202"
    elif stored_identity == "missing":
        stored.pop("market_user_id")
    if stored_identity != "absent":
        write_snapshot(f"account_entitlements:{market_user_id}", stored)
    write_snapshot(
        "account_entitlements:username:shared-brand",
        {"market_user_id": "202", "meta": {"updated_at_ms": 20}, "mod_ids": ["foreign-mod"]},
    )
    if impersonating:
        write_snapshot(
            "account_entitlements:username:current-user",
            {"market_user_id": "101", "meta": {"updated_at_ms": 30}},
        )
    response = client.get(
        "/api/xcmax/sync/entitlements/current", headers={"X-Session-ID": "snapshot-session"}
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["account"]["market_user_id"] == market_user_id
    assert data["snapshot"] == (expected if stored_identity == "owned" else None)
    assert data["has_snapshot"] is (stored_identity == "owned")
    assert data["updated_at_ms"] == (10 if stored_identity == "owned" else 0)
    with sessions() as db:
        assert db.query(User).one().market_user_id == 101
        row = db.query(Session).one()
        assert (row.market_user_id, row.impersonating_market_user_id) == (
            101,
            303 if impersonating else None,
        )


def test_unbound_entitlement_snapshot_retains_legacy_name_lookup(entitlements_client):
    client, sessions, write_snapshot = entitlements_client
    with sessions.begin() as db:
        db.query(Session).one().market_user_id = None
        db.query(User).one().market_user_id = None
    snapshot = {"market_user_id": "101", "meta": {"updated_at_ms": 10}, "mod_ids": ["own-mod"]}
    write_snapshot("account_entitlements:username:current-user", snapshot)
    response = client.get(
        "/api/xcmax/sync/entitlements/current", headers={"X-Session-ID": "snapshot-session"}
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["account"]["market_user_id"] is None
    assert data["snapshot"] == snapshot
    assert data["has_snapshot"] is True


@pytest.mark.parametrize("headers", [{}, {"X-Session-ID": "unknown-session"}])
def test_entitlement_snapshot_requires_an_existing_session(entitlements_client, headers):
    client, _, write_snapshot = entitlements_client
    write_snapshot("account_entitlements:101", {"market_user_id": "101"})
    response = client.get("/api/xcmax/sync/entitlements/current", headers=headers)
    assert response.status_code == 200
    assert response.json()["data"] == {
        "has_snapshot": False,
        "account": None,
        "snapshot": None,
        "updated_at_ms": 0,
        "note": "no active session",
    }


@pytest.mark.parametrize("invalid_session", ["expired", "disabled"])
def test_entitlement_snapshot_rejects_inactive_login_with_real_session_cleanup(
    entitlements_client, invalid_session
):
    client, sessions, write_snapshot = entitlements_client
    with sessions.begin() as db:
        if invalid_session == "expired":
            db.query(Session).one().expires_at = utc_now_naive() - timedelta(hours=1)
        else:
            db.query(User).one().is_active = False
    write_snapshot("account_entitlements:101", {"market_user_id": "101"})
    response = client.get(
        "/api/xcmax/sync/entitlements/current", headers={"X-Session-ID": "snapshot-session"}
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["account"] is None
    assert data["snapshot"] is None
    assert data["has_snapshot"] is False
    with sessions() as db:
        # Expiry cleanup must survive the real transaction context's exit.
        assert db.query(Session).count() == (0 if invalid_session == "expired" else 1)
        assert db.query(User).one().market_user_id == 101


def test_entitlement_snapshot_resolver_failure_does_not_enable_legacy_fallback(
    entitlements_client, monkeypatch
):
    from app.application import session_account_meta

    client, _, write_snapshot = entitlements_client
    write_snapshot("account_entitlements:username:shared-brand", {"market_user_id": "202"})
    original_db = session_account_meta.get_host_db
    lookups = 0

    @contextmanager
    def fail_identity_reload():
        nonlocal lookups
        lookups += 1
        if lookups > 1:
            raise RuntimeError("identity storage unavailable")
        with original_db() as db:
            yield db

    monkeypatch.setattr(session_account_meta, "get_host_db", fail_identity_reload)
    response = client.get(
        "/api/xcmax/sync/entitlements/current", headers={"X-Session-ID": "snapshot-session"}
    )
    assert response.status_code == 200
    assert response.json()["data"]["has_snapshot"] is False
    assert response.json()["data"]["snapshot"] is None


@pytest.mark.parametrize(
    ("failure", "status", "error_key"),
    [
        (HTTPException(status_code=503, detail="identity unavailable"), 503, "detail"),
        (RuntimeError("identity unavailable"), 500, "message"),
    ],
)
def test_entitlement_snapshot_preserves_non_authentication_errors(
    entitlements_client, monkeypatch, failure, status, error_key
):
    from app.infrastructure.auth import dependencies

    client, _, _ = entitlements_client

    def unavailable(_request):
        raise failure

    monkeypatch.setattr(dependencies, "get_logged_in_user", unavailable)
    response = client.get(
        "/api/xcmax/sync/entitlements/current", headers={"X-Session-ID": "snapshot-session"}
    )
    assert response.status_code == status
    assert response.json()[error_key] == "identity unavailable"
