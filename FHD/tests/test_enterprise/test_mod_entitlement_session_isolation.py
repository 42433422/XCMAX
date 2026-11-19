import asyncio
import time
from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.db_base import Base
from app.db.models.user import Session as UserSession
from app.db.models.user import User
from app.enterprise import mod_entitlements as entitlements
from app.utils.time import utc_now_naive
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


@pytest.mark.asyncio
async def test_middleware_isolates_overlapping_accounts_and_resets_after_failure():
    from app.infrastructure.mods.mod_auth import ModContextMiddleware

    entitlements.set_session_entitlements(
        market_user_id=99,
        market_username="startup",
        entitled_client_mod_ids={"startup"},
    )
    ready = {name: asyncio.Event() for name in ("a", "b")}
    observations = {}

    async def application(scope, receive, send):
        name = scope["path"].strip("/")
        assert entitlements.get_cached_entitled_client_mod_ids() == set()
        entitlements.set_session_entitlements(
            market_user_id=1 if name == "a" else 2,
            market_username=name,
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

        assert (
            await anyio.to_thread.run_sync(entitlements.get_cached_market_identity)
            == observations[name][0]
        )
        if name == "a":
            entitlements.clear_session_entitlements()
            raise RuntimeError("request terminated")
        await asyncio.sleep(0)
        assert entitlements.get_cached_entitled_client_mod_ids() == {"mod-b"}

    async def unused(*args):
        return {"type": "http.disconnect"}

    middleware = ModContextMiddleware(application)
    results = await asyncio.gather(
        *(
            middleware(
                {"type": "http", "path": f"/{name}", "headers": [], "method": "GET"}, unused, unused
            )
            for name in ("a", "b")
        ),
        return_exceptions=True,
    )
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
async def test_same_session_sync_is_serialized_without_blocking_another_account(monkeypatch):
    entered = []
    release = asyncio.Event()

    async def sync(sid, *, force=False):
        entered.append(sid)
        if sid == "a" and entered.count("a") == 1:
            await release.wait()
        return {sid}

    monkeypatch.setattr(entitlements, "_sync_entitlements_for_session", sync)
    first = asyncio.create_task(entitlements.sync_entitlements_for_session("a"))
    await asyncio.sleep(0)
    second = asyncio.create_task(entitlements.sync_entitlements_for_session("a"))
    other = asyncio.create_task(entitlements.sync_entitlements_for_session("b"))
    await asyncio.sleep(0)
    assert entered == ["a", "b"]
    release.set()
    assert await asyncio.gather(first, second, other) == [{"a"}, {"a"}, {"b"}]
    assert entered == ["a", "b", "a"]


@pytest.mark.asyncio
async def test_concurrent_session_requests_share_one_market_refresh(monkeypatch):
    sid = "concurrent-session"
    entitlements._entitlement_sync_at_by_session.pop(sid, None)
    entitlements._reloaded_entitlement_ids_by_session.pop(sid, None)
    started, release = asyncio.Event(), asyncio.Event()

    async def refresh(**kwargs):
        started.set()
        await release.wait()
        return {"mod-a"}

    monkeypatch.setattr("app.db.bootstrap.guarded.enabled", lambda: False)
    monkeypatch.setattr(
        "app.fastapi_routes.market_account.resolve_valid_market_access_token",
        AsyncMock(return_value="token"),
    )
    monkeypatch.setattr(entitlements, "_session_username_for_entitlements", lambda sid: "a")
    monkeypatch.setattr(
        entitlements, "refresh_session_entitlements_from_market", AsyncMock(side_effect=refresh)
    )
    monkeypatch.setattr(entitlements, "persist_entitlements_to_session_row", lambda sid, ids: None)

    def restore(sid):
        entitlements.set_session_entitlements(
            market_user_id=1, market_username="a", entitled_client_mod_ids={"mod-a"}
        )
        return True

    monkeypatch.setattr(entitlements, "restore_entitlements_from_session_row", restore)
    reload_mods = AsyncMock()
    monkeypatch.setattr(entitlements, "reload_enterprise_mods_after_login", reload_mods)

    async def request():
        with entitlements.request_entitlement_scope():
            return await entitlements.sync_entitlements_for_session(sid)

    first = asyncio.create_task(request())
    await started.wait()
    second = asyncio.create_task(request())
    await asyncio.sleep(0)
    release.set()
    assert await asyncio.gather(first, second) == [{"mod-a"}, {"mod-a"}]
    assert entitlements.refresh_session_entitlements_from_market.await_count == 1
    assert reload_mods.await_count == 1


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
    resolver = (
        AsyncMock(side_effect=RuntimeError("unavailable"))
        if market_failure
        else AsyncMock(return_value=None)
    )
    monkeypatch.setattr(
        "app.fastapi_routes.market_account.resolve_valid_market_access_token", resolver
    )
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
                db.add(
                    UserSession(
                        session_id=f"session-{name}",
                        user_id=index,
                        market_user_id=index,
                        expires_at=datetime.now() + timedelta(hours=1),
                        entitled_mod_ids_json=f'["mod-{name}"]',
                    )
                )
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
            db.add(
                UserSession(
                    session_id="expiry-session",
                    user_id=1,
                    market_user_id=1,
                    expires_at=now + timedelta(seconds=remaining_seconds),
                    entitled_mod_ids_json='["private-mod"]',
                )
            )
        entitlements.set_session_entitlements(
            market_user_id=1,
            market_username="expiry-owner",
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


@pytest.mark.asyncio
@pytest.mark.parametrize("credential", ["cookie", "x-session-id", "authorization"])
async def test_personal_plan_cannot_use_bundled_or_customer_mods(monkeypatch, credential):
    from app.infrastructure.mods.mod_auth import ModContextMiddleware

    monkeypatch.setenv("SESSION_COOKIE_NAME", "session_id")
    monkeypatch.setattr(entitlements, "session_has_personal_plan", lambda sid: sid == "free")
    visible = []

    async def application(scope, receive, send):
        visible.append(entitlements.is_mod_visible_for_enterprise("some-host-mod"))

    async def unused(*args):
        return {"type": "http.disconnect"}

    middleware = ModContextMiddleware(application)
    for sid in ("free", "enterprise"):
        value = (
            f"session_id={sid}"
            if credential == "cookie"
            else (f"Bearer {sid}" if credential == "authorization" else sid)
        )
        await middleware(
            {"type": "http", "path": "/list", "headers": [(credential.encode(), value.encode())]},
            unused,
            unused,
        )
    assert visible == [False, True]


@pytest.mark.parametrize(
    "credential", ["Cookie", "X-Session-ID", "Authorization", "web-jwt", "mixed"]
)
@pytest.mark.parametrize("sku", ["enterprise", "personal", ""])
def test_personal_plan_http_boundaries_preserve_paid_session(
    monkeypatch, trusted_actor, credential, sku
):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.fastapi_routes import elt, shipment_orders
    from app.fastapi_routes.domains.auth import auth_routes
    from app.infrastructure.mods.mod_auth import ModContextMiddleware
    from app.security.web_jwt import issue_web_tokens

    monkeypatch.setenv("XCAGI_PRODUCT_SKU", sku)
    monkeypatch.setattr(entitlements, "enterprise_mod_filter_active", lambda: sku == "enterprise")
    monkeypatch.setenv("FHD_ELT_CENTER_ENABLED", "1")
    monkeypatch.setenv("XCAGI_WEB_JWT_AUTH", "1")
    monkeypatch.setenv("SECRET_KEY", "personal-plan-test-key-at-least-32-chars")
    free, paid = trusted_actor(), trusted_actor()
    with free.factory.begin() as db:
        db.get(User, free.user_id).account_tier = "personal"
    monkeypatch.setattr(
        entitlements, "sync_entitlements_for_session", AsyncMock(return_value=set())
    )
    monkeypatch.setattr(
        "app.infrastructure.mods.mod_manager.ensure_mod_api_ready", lambda *a, **kw: True
    )
    writes = []
    monkeypatch.setattr(
        shipment_orders,
        "_run_shipment_records_agent",
        lambda **kw: writes.append(kw) or {"success": True},
    )
    application = FastAPI()
    application.add_middleware(ModContextMiddleware)
    application.include_router(shipment_orders.router)
    application.include_router(elt.router)
    application.include_router(auth_routes.router)

    @application.get("/api/mod/xcagi-approval-bridge/requests")
    def read_mod():
        return {"ok": True}

    with TestClient(application) as client:
        for actor, expected in ((free, 403), (paid, 200)):
            value = (
                f"session_id={actor.session_id}"
                if credential == "Cookie"
                else (
                    f"Bearer {actor.session_id}"
                    if credential == "Authorization"
                    else actor.session_id
                )
            )
            headers = {credential: value}
            if credential == "mixed":
                other = paid if actor is free else free
                headers = {
                    "Cookie": f"session_id={other.session_id}",
                    "X-Session-ID": actor.session_id,
                }
            if credential == "web-jwt":
                token = issue_web_tokens(user_id=actor.user_id, session_id=actor.session_id)[
                    "access_token"
                ]
                headers = {"Authorization": f"Bearer {token}"}
            response = client.get("/api/mod/xcagi-approval-bridge/requests", headers=headers)
            assert response.status_code == expected, response.text
            response = client.post(
                "/api/shipment/shipment-records/record",
                headers=headers,
                json={"unit_name": "owned-customer"},
            )
            assert response.status_code == expected, response.text
            response = client.get("/api/elt/capabilities", headers=headers)
            assert response.status_code == (expected if sku == "enterprise" else 403), response.text
            profile = client.get("/api/auth/me", headers=headers).json()["data"]
            assert profile["personal_plan"] is (actor is free)
            if actor is free:
                assert profile["permissions"] == ["memory_v2.write"]
            else:
                assert "shipment.create" in profile["permissions"]
    assert len(writes) == 1


@pytest.mark.parametrize("kind", ["live", "expired-session", "relay", "legacy-relay"])
def test_mobile_personal_mod_veto_uses_current_host_user(monkeypatch, trusted_actor, kind):
    import jwt
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from starlette.requests import Request

    from app.fastapi_routes.mobile_api import get_mobile_user
    from app.infrastructure.mods.mod_auth import ModContextMiddleware
    from app.security import mobile_jwt

    monkeypatch.setenv("SECRET_KEY", "personal-mobile-plan-test-key-at-least-32-chars")
    free, paid = trusted_actor(), trusted_actor()
    with free.factory.begin() as db:
        db.get(User, free.user_id).account_tier = "personal"
        if kind == "expired-session":
            db.get(UserSession, free.session_row_id).expires_at = utc_now_naive() - timedelta(
                seconds=1
            )
    monkeypatch.setattr(
        entitlements, "sync_entitlements_for_session", AsyncMock(return_value=set())
    )
    monkeypatch.setattr(
        "app.infrastructure.mods.mod_manager.ensure_mod_api_ready", lambda *a, **kw: True
    )
    application = FastAPI()
    application.add_middleware(ModContextMiddleware)

    @application.get("/api/mod/xcagi-approval-bridge/requests")
    def read_mod():
        return {"ok": True}

    with TestClient(application) as client:
        for actor, expected in ((free, 403), (paid, 200)):
            sid = "mobile-relay-existing" if "relay" in kind else actor.session_id
            tokens = mobile_jwt.issue_mobile_tokens(user_id=actor.user_id, session_id=sid)
            token = tokens["access_token"]
            if kind == "legacy-relay":
                payload = mobile_jwt.verify_mobile_jwt(token)
                payload.pop("typ")
                token = jwt.encode(payload, mobile_jwt._secret_key(), algorithm="HS256")
            headers = {"Authorization": f"Bearer {token}"}
            if actor is free:
                headers["X-Session-ID"] = paid.session_id
            request = Request(
                {
                    "type": "http",
                    "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
                }
            )
            identified = asyncio.run(
                get_mobile_user(request, authorization=headers["Authorization"])
            )
            assert identified.id == actor.user_id
            response = client.get("/api/mod/xcagi-approval-bridge/requests", headers=headers)
            assert response.status_code == expected, response.text
            assert entitlements.mobile_token_has_personal_plan(tokens["refresh_token"]) is False
