"""Market credential isolation and real transport contracts with synthetic IO."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.fastapi_routes import market_account as market
from app.fastapi_routes.market_bridge import token_lifecycle


@pytest.fixture(autouse=True)
def isolated_validation_cache(monkeypatch):
    monkeypatch.setattr(token_lifecycle, "_fast_ok_until", {})


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


@pytest.mark.parametrize("change", ["owner", "origin", "token", "expired", "cleared", "saved"])
@pytest.mark.asyncio
async def test_fast_validation_cache_is_scoped_expires_and_invalidates(monkeypatch, change):
    state = {"owner": 71, "token": "synthetic-access", "now": 100.0}
    monkeypatch.setattr(market, "session_market_refresh_token", lambda sid: "synthetic-refresh")
    monkeypatch.setattr(market, "_user_id_from_session", lambda sid: state["owner"])
    monkeypatch.setattr(market, "session_market_token", lambda sid: state["token"])
    monkeypatch.setattr(token_lifecycle.time, "monotonic", lambda: state["now"])
    monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "https://market.invalid")
    remote = AsyncMock(return_value={"user": {"id": 71}})
    monkeypatch.setattr(market, "_proxy_json", remote)
    monkeypatch.setattr(
        market, "_session_tokens", lambda: SimpleNamespace(clear=Mock(), save=Mock())
    )

    await market.resolve_valid_market_access_token_fast("verified-session")
    await market.resolve_valid_market_access_token_fast("verified-session")
    assert remote.await_count == 1
    assert all(value[0] != state["token"] for value in token_lifecycle._fast_ok_until.values())
    if change == "owner":
        state["owner"] = 72
    elif change == "origin":
        monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "https://other-market.invalid")
    elif change == "token":
        state["token"] = "synthetic-replaced-access"
    elif change == "expired":
        state["now"] += token_lifecycle._FAST_OK_TTL_S
    elif change == "cleared":
        market.clear_session_market_token("verified-session")
    else:
        market.save_session_market_token("verified-session", state["token"])
    await market.resolve_valid_market_access_token_fast("verified-session")
    assert remote.await_count == 2


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


@pytest.mark.parametrize(
    "outcome", [400, 401, 403, 503, "transport", "malformed", "success", "missing"]
)
@pytest.mark.parametrize("race", ["none", "token", "owner", "refresh", "logout"])
@pytest.mark.asyncio
async def test_background_probe_applies_only_definitive_current_credential_rejection(
    monkeypatch, outcome, race
):
    state = {"token": "old-access", "refresh": "old-refresh", "owner": 71}
    if outcome == "missing":
        state["refresh"] = ""
    monkeypatch.setattr(market, "session_market_token", lambda sid: state["token"])
    monkeypatch.setattr(market, "session_market_refresh_token", lambda sid: state["refresh"])
    monkeypatch.setattr(market, "_user_id_from_session", lambda sid: state["owner"])
    clear = Mock(side_effect=lambda sid: state.update(token="", refresh=""))
    save = Mock(
        side_effect=lambda sid, access, refresh: state.update(token=access, refresh=refresh)
    )
    monkeypatch.setattr(market, "clear_session_market_token", clear)
    monkeypatch.setattr(market, "save_session_market_token", save)
    latest = Mock(side_effect=AssertionError("Probe cannot borrow another session's token"))
    monkeypatch.setattr(market, "latest_session_market_token", latest)

    async def remote(method, path, **kwargs):
        if path == "/api/auth/me":
            if outcome == "missing" and race != "none":
                state[race if race != "logout" else "token"] = "" if race == "logout" else "new"
            return {"__proxy_error__": True, "status_code": 401}
        assert path == "/api/auth/refresh"
        if race != "none":
            state[race if race != "logout" else "token"] = "" if race == "logout" else "new"
        if outcome == "transport":
            raise httpx.ConnectError("synthetic unavailable")
        if outcome == "malformed":
            return {}
        if outcome == "success":
            return {"access_token": "rotated-access", "refresh_token": "rotated-refresh"}
        return {"__proxy_error__": True, "status_code": outcome}

    monkeypatch.setattr(market, "_proxy_json", remote)
    result = await market.resolve_valid_market_access_token_fast("probe-session")
    assert result == state["token"]
    assert clear.call_count == int(race == "none" and outcome in (401, 403, "missing"))
    assert save.call_count == int(race == "none" and outcome == "success")
    latest.assert_not_called()
    if race == "none":
        assert result == (
            ""
            if outcome in (401, 403, "missing")
            else "rotated-access"
            if outcome == "success"
            else "old-access"
        )


@pytest.mark.asyncio
async def test_validate_returns_before_probe_and_rejects_after_confirmed_revocation(monkeypatch):
    from dataclasses import fields

    from fastapi import BackgroundTasks

    from app.fastapi_routes.domains.auth.session_access import SessionAccess

    state = {"token": "revoked-access"}
    monkeypatch.setattr(market, "session_market_token", lambda sid: state["token"])
    monkeypatch.setattr(market, "session_market_refresh_token", lambda sid: "")
    monkeypatch.setattr(market, "_user_id_from_session", lambda sid: 71)
    monkeypatch.setattr(market, "clear_session_market_token", lambda sid: state.update(token=""))
    remote = AsyncMock(return_value={"__proxy_error__": True, "status_code": 401})
    monkeypatch.setattr(market, "_proxy_json", remote)
    backend = SimpleNamespace(
        session_manager=SimpleNamespace(get_session_info=lambda sid: {"id": sid})
    )
    ports = {field.name: Mock(return_value=None) for field in fields(SessionAccess)}
    ports.update(
        session_id=lambda request: "revoked-session",
        backend=lambda: backend,
        product_sku=lambda: "enterprise",
        stored_market_token=market.session_market_token,
        market_token=market.resolve_valid_market_access_token_fast,
        sync_entitlements=AsyncMock(return_value=set()),
        session_meta=lambda *args: {},
        infra_errors=lambda: (RuntimeError,),
    )
    sessions = SessionAccess(**ports)
    tasks = BackgroundTasks()
    assert (await sessions.validate(_request(), tasks))["valid"] is True
    remote.assert_not_awaited()
    await tasks()
    response = await sessions.validate(_request(), BackgroundTasks())
    assert response.status_code == 200
    import json

    assert json.loads(response.body)["valid"] is False
    remote.assert_awaited_once()


@pytest.mark.parametrize("payload", [{"ok": False}, {"success": False}, {}])
@pytest.mark.parametrize("refresh", ["", "synthetic-refresh"])
@pytest.mark.asyncio
async def test_fast_probe_never_revokes_on_ambiguous_success_status(monkeypatch, payload, refresh):
    monkeypatch.setattr(market, "session_market_token", lambda sid: "synthetic-access")
    monkeypatch.setattr(market, "session_market_refresh_token", lambda sid: refresh)
    monkeypatch.setattr(market, "_user_id_from_session", lambda sid: 71)
    remote = AsyncMock(return_value=payload)
    clear = Mock()
    monkeypatch.setattr(market, "_proxy_json", remote)
    monkeypatch.setattr(market, "clear_session_market_token", clear)
    assert (
        await market.resolve_valid_market_access_token_fast("probe-session") == "synthetic-access"
    )
    remote.assert_awaited_once()
    clear.assert_not_called()
