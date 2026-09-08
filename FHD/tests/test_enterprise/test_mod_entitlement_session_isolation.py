import asyncio
import time
from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.models.user import Session as UserSession
from app.db.models.user import User
from app.enterprise import mod_entitlements as entitlements
from app.utils.time import utc_now_naive


@pytest.mark.asyncio
async def test_middleware_isolates_overlapping_accounts_and_resets_after_failure():
    from app.infrastructure.mods.mod_auth import ModContextMiddleware

    entitlements.set_session_entitlements(
        market_user_id=99, market_username="startup", entitled_client_mod_ids={"startup"},
    )
    ready = {name: asyncio.Event() for name in ("a", "b")}
    observations = {}

    async def application(scope, receive, send):
        name = scope["path"].strip("/")
        assert entitlements.get_cached_entitled_client_mod_ids() == set()
        entitlements.set_session_entitlements(
            market_user_id=1 if name == "a" else 2, market_username=name,
            entitled_client_mod_ids={f"mod-{name}"},
            account_kind="admin" if name == "a" else "enterprise",
            market_is_admin=name == "a",
        )
        ready[name].set()
        await asyncio.wait_for(ready["b" if name == "a" else "a"].wait(), timeout=5)
        observations[name] = (
            entitlements.get_cached_market_identity(),
            entitlements.get_cached_entitled_client_mod_ids(),
            entitlements.is_admin_account_session(),
        )
        # FastAPI runs synchronous handlers with a copied async request context.
        import anyio

        assert await anyio.to_thread.run_sync(
            entitlements.get_cached_market_identity
        ) == observations[name][0]
        if name == "a":
            entitlements.clear_session_entitlements()
            raise RuntimeError("request terminated")
        await asyncio.sleep(0)
        assert entitlements.get_cached_entitled_client_mod_ids() == {"mod-b"}

    async def unused(*args):
        return {"type": "http.disconnect"}

    middleware = ModContextMiddleware(application)
    results = await asyncio.gather(*(
        middleware({"type": "http", "path": f"/{name}", "headers": [], "method": "GET"}, unused, unused)
        for name in ("a", "b")
    ), return_exceptions=True)
    assert isinstance(results[0], RuntimeError)
    assert results[1] is None
    assert observations == {
        "a": ((1, "a"), {"mod-a"}, True),
        "b": ((2, "b"), {"mod-b"}, False),
    }
    assert entitlements.get_cached_market_identity() == (99, "startup")
    assert entitlements.get_cached_entitled_client_mod_ids() == {"startup"}


@pytest.fixture(autouse=True)
def isolated_cache(monkeypatch):
    entitlements.clear_session_entitlements()
    monkeypatch.setattr(entitlements, "enterprise_mod_filter_active", lambda: True)
    monkeypatch.setattr(entitlements, "_augment_entitled_for_username", lambda name, ids: ids)
    yield
    entitlements.clear_session_entitlements()


@pytest.mark.asyncio
async def test_cached_session_does_not_return_last_accounts_entitlements(monkeypatch):
    entitlements.set_session_entitlements(
        market_user_id=2, market_username="account-b", entitled_client_mod_ids={"mod-b"}
    )
    entitlements._entitlement_sync_at_by_session["session-a"] = time.monotonic()

    def restore(sid):
        assert sid == "session-a"
        entitlements.set_session_entitlements(
            market_user_id=1, market_username="account-a", entitled_client_mod_ids={"mod-a"}
        )
        return True

    monkeypatch.setattr(entitlements, "restore_entitlements_from_session_row", restore)
    assert await entitlements.sync_entitlements_for_session("session-a") == {"mod-a"}
    assert entitlements.get_cached_market_identity() == (1, "account-a")


@pytest.mark.asyncio
@pytest.mark.parametrize("market_failure", [False, True])
async def test_failed_restore_never_returns_other_accounts_cache(monkeypatch, market_failure):
    entitlements.set_session_entitlements(
        market_user_id=2, market_username="account-b", entitled_client_mod_ids={"mod-b"}
    )
    monkeypatch.setattr(entitlements, "restore_entitlements_from_session_row", lambda sid: False)
    monkeypatch.setattr(entitlements, "_session_username_for_entitlements", lambda sid: "")
    resolver = AsyncMock(side_effect=RuntimeError("unavailable")) if market_failure else AsyncMock(return_value=None)
    monkeypatch.setattr("app.fastapi_routes.market_account.resolve_valid_market_access_token", resolver)
    assert await entitlements.sync_entitlements_for_session("session-a") == set()


@pytest.mark.asyncio
async def test_interleaved_sessions_restore_their_own_persisted_ids(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'entitlements.db'}")
    factory = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    monkeypatch.setattr(entitlements, "_session_row_db_context", factory)
    try:
        with factory.begin() as db:
            for index, name in enumerate(("a", "b"), start=1):
                db.add(User(id=index, username=name, password="unused"))
                db.flush()
                db.add(UserSession(
                    session_id=f"session-{name}", user_id=index, market_user_id=index,
                    expires_at=datetime.now() + timedelta(hours=1),
                    entitled_mod_ids_json=f'["mod-{name}"]',
                ))
        for name in ("a", "b", "a", "b"):
            entitlements._entitlement_sync_at_by_session[f"session-{name}"] = time.monotonic()
            assert await entitlements.sync_entitlements_for_session(f"session-{name}") == {
                f"mod-{name}"
            }
        with factory.begin() as db:
            row = db.query(UserSession).filter_by(session_id="session-a").one()
            row.entitled_mod_ids_json = "[]"
        assert await entitlements.sync_entitlements_for_session("session-a") == set()
    finally:
        engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("remaining_seconds", [-1, 0, 60])
async def test_session_expiry_applies_even_with_fresh_entitlement_ttl(
    tmp_path, monkeypatch, remaining_seconds
):
    engine = create_engine(f"sqlite:///{tmp_path / 'session-expiry.db'}")
    factory = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    now = utc_now_naive()
    monkeypatch.setattr("app.utils.time.utc_now_naive", lambda: now)
    monkeypatch.setattr(entitlements, "_session_row_db_context", factory)
    try:
        with factory.begin() as db:
            db.add(User(id=1, username="expiry-owner", password="unused"))
            db.flush()
            db.add(UserSession(
                session_id="expiry-session", user_id=1, market_user_id=1,
                expires_at=now + timedelta(seconds=remaining_seconds),
                entitled_mod_ids_json='["private-mod"]',
            ))
        entitlements.set_session_entitlements(
            market_user_id=1, market_username="expiry-owner",
            entitled_client_mod_ids={"private-mod"},
        )
        entitlements._entitlement_sync_at_by_session["expiry-session"] = time.monotonic()
        expected = {"private-mod"} if remaining_seconds > 0 else set()
        assert await entitlements.sync_entitlements_for_session("expiry-session") == expected
        assert entitlements.get_cached_entitled_client_mod_ids() == expected
        # Authorization checks do not delete the historical session record.
        with factory() as db:
            assert db.query(UserSession).filter_by(session_id="expiry-session").count() == 1
    finally:
        engine.dispose()
