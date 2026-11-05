"""Market credential isolation and real transport contracts with synthetic IO."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.fastapi_routes import market_account as market


def _request(session_id: str = "") -> Request:
    headers = [(b"x-session-id", session_id.encode())] if session_id else []
    return Request({"type": "http", "headers": headers})


@pytest.mark.parametrize("resolved", [False, True])
@pytest.mark.parametrize("unavailable", [False, True])
@pytest.mark.asyncio
async def test_unresolved_request_identity_never_reads_another_users_latest_token(
    monkeypatch, resolved, unavailable
):
    identity = (
        Mock(side_effect=RuntimeError("identity unavailable"))
        if unavailable
        else Mock(return_value=None)
    )
    monkeypatch.setattr("app.infrastructure.auth.dependencies.resolve_session_user", identity)
    monkeypatch.setattr(market, "session_market_token", lambda sid: "")
    monkeypatch.setattr(market, "_user_id_from_session", lambda sid: None)
    latest = Mock(return_value="synthetic-other-user-token")
    monkeypatch.setattr(market, "latest_session_market_token", latest)
    remote = AsyncMock(side_effect=AssertionError("No market request without a credential"))
    monkeypatch.setattr(market, "_proxy_json", remote)

    request = _request("synthetic-unresolved-session")
    authorization = (
        await market._authorization_from_request_resolved(request, {})
        if resolved
        else market._authorization_from_request(request, {})
    )

    assert authorization == ""
    latest.assert_not_called()
    remote.assert_not_awaited()


def test_direct_checkout_cannot_sign_or_submit_using_an_unresolved_sessions_fallback(
    monkeypatch,
):
    monkeypatch.setattr(
        "app.infrastructure.auth.dependencies.resolve_session_user", lambda request: None
    )
    monkeypatch.setattr(market, "session_market_token", lambda sid: "")
    monkeypatch.setattr(market, "_user_id_from_session", lambda sid: None)
    latest = Mock(return_value="synthetic-victim-token")
    monkeypatch.setattr(market, "latest_session_market_token", latest)
    remote = AsyncMock(
        return_value={
            "request_id": "synthetic-request",
            "signature": "synthetic-signature",
            "timestamp": 1,
        }
    )
    monkeypatch.setattr(market, "_proxy_json", remote)
    app = FastAPI()
    app.include_router(market.router)
    with TestClient(app) as client:
        response = client.post(
            "/api/market/payment/direct-checkout",
            headers={"X-Session-ID": "synthetic-unresolved-session"},
            json={"plan_id": "synthetic-plan"},
        )

    assert response.status_code == 401
    assert response.json()["success"] is False
    latest.assert_not_called()
    remote.assert_not_awaited()


@pytest.mark.asyncio
async def test_verified_request_fallback_and_requestless_resolver_keep_user_scope(monkeypatch):
    monkeypatch.setattr(
        "app.infrastructure.auth.dependencies.resolve_session_user",
        lambda request: SimpleNamespace(id=71, is_active=True),
    )
    monkeypatch.setattr(market, "session_market_token", lambda sid: "")
    monkeypatch.setattr(market, "_user_id_from_session", lambda sid: 71)
    latest = Mock(return_value="synthetic-owned-token")
    monkeypatch.setattr(market, "latest_session_market_token", latest)
    remote = AsyncMock(return_value={"user": {"id": 71}})
    monkeypatch.setattr(market, "_proxy_json", remote)

    assert (
        market._authorization_from_request(_request("verified-session"), {})
        == "Bearer synthetic-owned-token"
    )
    assert (
        await market.resolve_valid_market_access_token("trusted-internal-session")
        == "synthetic-owned-token"
    )
    assert latest.call_count == 2
    assert all(call.kwargs == {"user_id": 71} for call in latest.call_args_list)


def test_explicit_bearer_without_local_session_does_not_read_shared_tokens(monkeypatch):
    monkeypatch.setattr(
        "app.infrastructure.auth.dependencies.resolve_session_user", lambda request: None
    )
    monkeypatch.setattr(market, "session_market_token", lambda sid: "")
    latest = Mock(side_effect=AssertionError("No shared fallback for an explicit credential"))
    monkeypatch.setattr(market, "latest_session_market_token", latest)
    assert (
        market._authorization_from_request(_request(), {"token": "synthetic-explicit"})
        == "Bearer synthetic-explicit"
    )
    latest.assert_not_called()


@pytest.mark.parametrize("outcome", ["valid", "expired", "unavailable"])
@pytest.mark.asyncio
async def test_fast_validation_performs_one_probe_and_refreshes_only_rejection(
    monkeypatch, outcome
):
    monkeypatch.setattr(market, "_user_id_from_session", lambda sid: 71)
    monkeypatch.setattr(market, "session_market_token", lambda sid: "synthetic-old-access")
    monkeypatch.setattr(market, "session_market_refresh_token", lambda sid: "synthetic-refresh")
    monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "https://market.invalid")
    monkeypatch.setenv("XCAGI_MARKET_HTTP_RETRIES", "3")
    saved = Mock()
    monkeypatch.setattr(market, "save_session_market_token", saved)
    requests = []

    def transport(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url.path))
        if request.url.path == "/api/auth/me":
            assert request.headers["Authorization"] == "Bearer synthetic-old-access"
            if outcome == "unavailable":
                raise httpx.ConnectError("synthetic unavailable", request=request)
            return httpx.Response(401 if outcome == "expired" else 200, json={"user": {"id": 71}})
        if request.url.path == "/api/csrf":
            return httpx.Response(200, headers={"set-cookie": "csrf_token=synthetic-csrf"}, json={})
        assert request.url.path == "/api/auth/refresh"
        assert request.headers["X-CSRF-Token"] == "synthetic-csrf"
        return httpx.Response(
            200,
            json={"access_token": "synthetic-new-access", "refresh_token": "synthetic-new-refresh"},
        )

    client_class = httpx.AsyncClient
    monkeypatch.setattr(
        market.httpx,
        "AsyncClient",
        lambda **kwargs: client_class(transport=httpx.MockTransport(transport), **kwargs),
    )
    result = await market.resolve_valid_market_access_token_fast("verified-session")

    assert requests.count(("GET", "/api/auth/me")) == 1
    if outcome == "expired":
        assert result == "synthetic-new-access"
        assert requests == [
            ("GET", "/api/auth/me"),
            ("GET", "/api/csrf"),
            ("POST", "/api/auth/refresh"),
        ]
        saved.assert_called_once_with(
            "verified-session", "synthetic-new-access", "synthetic-new-refresh"
        )
    else:
        assert result == "synthetic-old-access"
        assert requests == [("GET", "/api/auth/me")]
        saved.assert_not_called()
