"""Public contracts across market transport, account and payment components."""

from contextlib import contextmanager
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models.user import Session, User
from app.fastapi_routes import market_account as market
from app.utils.time import utc_now_naive


@pytest.fixture(autouse=True)
def _isolated_market_caches(monkeypatch):
    monkeypatch.setattr(market, "_MARKET_SESSION_TOKENS", {})
    monkeypatch.setattr(market, "_MARKET_SESSION_REFRESH_TOKENS", {})
    monkeypatch.setattr(market, "_ACCOUNT_OVERVIEW_CACHE", {})


@pytest.mark.parametrize("failure", ["connection", "http-status"])
@pytest.mark.asyncio
async def test_write_attempt_budget_csrf_and_sensitive_error_logging(monkeypatch, caplog, failure):
    monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "https://market.invalid/market")
    calls = []

    def transport(request):
        calls.append((request.method, request.url.path))
        if request.url.path == "/api/csrf":
            return httpx.Response(200, headers={"Set-Cookie": "csrf_token=synthetic-csrf"})
        assert request.url.path == "/api/auth/login"
        assert request.headers["X-CSRF-Token"] == "synthetic-csrf"
        assert request.headers["Authorization"] == "Bearer synthetic-owned"
        if failure == "http-status":
            return httpx.Response(503, json={"detail": "synthetic-sensitive-payload"})
        if calls.count(("POST", "/api/auth/login")) == 1:
            raise httpx.ConnectError("synthetic connection", request=request)
        return httpx.Response(200, json={"access_token": "synthetic-access"})

    client_class = httpx.AsyncClient
    monkeypatch.setattr(
        market.httpx,
        "AsyncClient",
        lambda **kwargs: client_class(transport=httpx.MockTransport(transport), **kwargs),
    )
    result = await market._proxy_json(
        "POST",
        "/api/auth/login",
        json_body={"password": "synthetic-only"},
        authorization="synthetic-owned",
        retries=2,
        sensitive=True,
        return_error_payload=True,
    )
    pair = [("GET", "/api/csrf"), ("POST", "/api/auth/login")]
    if failure == "connection":
        assert calls == pair * 2
        assert result == {"access_token": "synthetic-access"}
    else:
        assert calls == pair
        assert result == {
            "__proxy_error__": True,
            "status_code": 503,
            "payload": {"detail": "synthetic-sensitive-payload"},
        }
    assert "synthetic-sensitive-payload" not in caplog.text
    assert "synthetic-only" not in caplog.text


@pytest.mark.parametrize("status", [401, 422])
@pytest.mark.asyncio
async def test_signing_rejection_stops_checkout_and_only_sends_allowed_sign_fields(
    monkeypatch, status
):
    monkeypatch.setattr(
        market,
        "_resolve_market_authorization_for_checkout",
        AsyncMock(return_value=("Bearer synthetic-owner", None)),
    )
    proxy = AsyncMock(
        return_value={
            "__proxy_error__": True,
            "status_code": status,
            "payload": {"detail": "synthetic-rejected"},
        }
    )
    monkeypatch.setattr(market, "_proxy_json", proxy)
    body = {
        "plan_id": "synthetic-plan",
        "user_id": 999,
        "authorization": "untrusted-body-token",
        "metadata": {"order": "synthetic"},
    }
    original = dict(body)
    response = await market.market_payment_direct_checkout(
        Request({"type": "http", "headers": []}), body
    )
    assert isinstance(response, JSONResponse)
    assert response.status_code == status
    proxy.assert_awaited_once_with(
        "POST",
        "/api/payment/sign-checkout",
        json_body={"plan_id": "synthetic-plan", "metadata": {"order": "synthetic"}},
        authorization="Bearer synthetic-owner",
        return_error_payload=True,
    )
    assert body == original


@pytest.mark.asyncio
async def test_server_signature_is_used_for_one_checkout_without_mutating_input(monkeypatch):
    monkeypatch.setattr(
        market,
        "_resolve_market_authorization_for_checkout",
        AsyncMock(return_value=("Bearer synthetic-owner", None)),
    )
    signed = {"request_id": "server-request", "signature": "server-signature", "timestamp": 72}
    proxy = AsyncMock(side_effect=[signed, {"order_id": "synthetic-order"}])
    monkeypatch.setattr(market, "_proxy_json", proxy)
    body = {
        "plan_id": "synthetic-plan",
        "request_id": "client-value",
        "signature": "client-value",
        "timestamp": 1,
    }
    original = dict(body)
    response = await market.market_payment_direct_checkout(
        Request({"type": "http", "headers": []}), body
    )
    assert response == {"success": True, "data": {"order_id": "synthetic-order"}, "signed": signed}
    assert proxy.await_count == 2
    checkout = proxy.await_args_list[1]
    assert checkout.args == ("POST", "/api/payment/checkout")
    assert checkout.kwargs["json_body"] == {**original, **signed}
    assert checkout.kwargs["authorization"] == "Bearer synthetic-owner"
    assert body == original


@pytest.mark.asyncio
async def test_account_cache_is_credential_scoped_and_refreshes_live_wallet(monkeypatch):
    now = [10.0]
    monkeypatch.setattr(market, "time", SimpleNamespace(monotonic=lambda: now[0]))
    monkeypatch.setattr(market, "_account_overview_cache_ttl", lambda: 5.0)
    monkeypatch.setattr(
        market,
        "_authorization_from_request_resolved",
        AsyncMock(side_effect=lambda request, body: body["token"]),
    )
    calls = []

    async def proxy(method, path, *, authorization="", **kwargs):
        calls.append((authorization, path))
        if path == "/api/account/bootstrap":
            return {
                "user": {"name": authorization},
                "wallet": {"balance": -1},
                "membership": {"tier": "synthetic"},
            }
        assert path in {"/api/wallet/overview", "/api/wallet/balance"}
        return {"balance": 71 if authorization == "owner-a" else 72}

    monkeypatch.setattr(market, "_proxy_json", proxy)
    request = Request({"type": "http", "headers": []})
    first = await market.market_account_overview(request, {"token": "owner-a"})
    other = await market.market_account_overview(request, {"token": "owner-b"})
    cached = await market.market_account_overview(request, {"token": "owner-a"})
    assert first["data"]["wallet"] == {"balance": 71}
    assert other["data"]["wallet"] == {"balance": 72}
    assert cached == first
    assert len(calls) == 6
    assert len(market._ACCOUNT_OVERVIEW_CACHE) == 2
    await market.market_account_overview(request, {"token": "owner-a", "refresh": True})
    assert len(calls) == 9
    now[0] += 6
    await market.market_account_overview(request, {"token": "owner-b"})
    assert len(calls) == 12


def test_session_token_repository_keeps_access_refresh_and_owners_isolated(monkeypatch):
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    with sessions.begin() as db:
        for uid in (71, 72):
            db.add(User(id=uid, username=f"synthetic-{uid}", password="unused", is_active=True))
            db.add(
                Session(
                    session_id=f"synthetic-session-{uid}",
                    user_id=uid,
                    expires_at=utc_now_naive() + timedelta(hours=1),
                )
            )

    @contextmanager
    def database():
        with sessions() as db:
            yield db

    monkeypatch.setattr("app.db.session.get_db", database)
    try:
        market.save_session_market_token("synthetic-session-71", "access-71", "refresh-71")
        market.save_session_market_token("synthetic-session-72", "access-72", "refresh-72")
        market.save_session_market_token("synthetic-session-71", "replacement-71")
        market._MARKET_SESSION_TOKENS.clear()
        market._MARKET_SESSION_REFRESH_TOKENS.clear()
        assert market.session_market_token("synthetic-session-71") == "replacement-71"
        assert market.session_market_refresh_token("synthetic-session-71") == "refresh-71"
        assert market.latest_session_market_token(user_id=72) == "access-72"
        assert market._user_id_from_session("synthetic-session-72") == 72
        market.clear_session_market_token("synthetic-session-71")
        with sessions() as db:
            cleared = db.get(
                Session, db.query(Session.id).filter_by(session_id="synthetic-session-71").scalar()
            )
            assert cleared.market_access_token is None
            assert cleared.market_refresh_token is None
        assert market.session_market_token("synthetic-session-72") == "access-72"
        assert market.session_market_refresh_token("synthetic-session-72") == "refresh-72"
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_industry_grant_uses_session_owner_and_deduplicates_provider_results(monkeypatch):
    monkeypatch.setattr("app.mod_sdk.industry_seed.industry_mod_id_for", lambda iid: "same-mod")
    monkeypatch.setattr(
        "app.mod_sdk.industry_mod_aliases.canonical_mod_id_for_industry", lambda iid: "same-mod"
    )
    monkeypatch.setattr(
        "app.mod_sdk.customer_delivery.deliveries_for_industry",
        lambda iid: [
            {"industry_mod_id": "same-mod", "runtime_mod_id": "runtime-mod"},
            {"industry_mod_id": "extra-mod"},
        ],
    )
    monkeypatch.setattr(
        "app.application.session_account_meta.load_session_account_meta",
        lambda sid: {"market_user_id": 71},
    )
    token = AsyncMock(
        side_effect=AssertionError("Known owner must not be replaced by token fallback")
    )
    monkeypatch.setattr(market, "resolve_valid_market_access_token", token)
    grant = AsyncMock(return_value={"success": True, "market_user_id": 71})
    monkeypatch.setattr(market, "ensure_market_enterprise_profile", grant)
    assert await market.grant_market_enterprise_entitlements_for_session(
        "owned-session", "industry"
    ) == {"success": True, "market_user_id": 71}
    grant.assert_awaited_once_with(71, mod_ids=["same-mod", "runtime-mod", "extra-mod"])
    token.assert_not_awaited()


@pytest.mark.asyncio
async def test_registration_verification_error_never_enters_diagnostic_registration(monkeypatch):
    proxy = AsyncMock(
        return_value={
            "__proxy_error__": True,
            "status_code": 400,
            "payload": {"detail": "verification code required"},
        }
    )
    monkeypatch.setattr(market, "_proxy_json", proxy)
    diagnostic = AsyncMock(
        side_effect=AssertionError("Public registration must retain verification")
    )
    monkeypatch.setattr(market, "_register_without_verification", diagnostic)
    result = await market.register_market_user(
        "synthetic-user", "synthetic-password", "synthetic@example.invalid", " 123456 "
    )
    assert result["success"] is False
    assert result["message"] == "verification code required"
    proxy.assert_awaited_once_with(
        "POST",
        "/api/auth/register",
        json_body={
            "username": "synthetic-user",
            "password": "synthetic-password",
            "email": "synthetic@example.invalid",
            "verification_code": "123456",
        },
        return_error_payload=True,
    )
    diagnostic.assert_not_awaited()
