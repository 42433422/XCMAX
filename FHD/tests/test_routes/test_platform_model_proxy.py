"""The credential admin proxy rejects invalid identity before reading sensitive data."""

from datetime import timedelta
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.admin_control.protocols import MarketTransport
from app.db.db_base import Base
from app.db.models.user import Session, User
from app.fastapi_routes import xcmax_admin
from app.fastapi_routes.admin_control import market_gateway
from app.utils.time import utc_now_naive

pytestmark = pytest.mark.release_gate
PATH = "/api/xcmax/market-proxy/llm/admin/platform-model-config"
SECRET = "synthetic-opaque-platform-credential-only"


@pytest.fixture
def platform_client(tmp_path, monkeypatch):
    import app.db as database

    monkeypatch.setenv("XCAGI_DESKTOP_MODE", "0")
    engine = create_engine(
        f"sqlite:///{tmp_path / 'admin.sqlite3'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    monkeypatch.setattr(database, "HostSessionLocal", sessions)
    with sessions.begin() as db:
        for uid, kind in enumerate(
            ("admin", "enterprise", "expired", "disabled", "impersonating"), 1
        ):
            db.add(
                User(
                    id=uid,
                    username=kind,
                    password="unused",
                    role="admin",
                    tier="admin",
                    is_active=kind != "disabled",
                )
            )
            db.add(
                Session(
                    session_id=kind,
                    user_id=uid,
                    account_kind="enterprise" if kind == "enterprise" else "admin",
                    market_is_admin=kind != "enterprise",
                    expires_at=utc_now_naive() + timedelta(hours=-1 if kind == "expired" else 1),
                    impersonating_market_user_id=99 if kind == "impersonating" else None,
                )
            )
    upstream = AsyncMock(return_value={"ok": True, "providers": []})
    fallback = AsyncMock(return_value="Bearer forbidden-fallback")
    bound = AsyncMock(return_value="Bearer synthetic-session-token")
    transport = Mock(return_value=MarketTransport(str, fallback, upstream, lambda *_: SECRET))
    monkeypatch.setattr(market_gateway, "bound_market_authorization", bound)
    monkeypatch.setattr(xcmax_admin._market_gateway, "_transport", transport)
    app = FastAPI()
    app.include_router(xcmax_admin.router)
    with TestClient(app) as client:
        yield client, upstream, bound, fallback, transport
    engine.dispose()


@pytest.mark.parametrize(
    "method,suffix", [("GET", ""), ("PUT", "/openai"), ("POST", "/openai/test")]
)
@pytest.mark.parametrize(
    "session,status",
    [(None, 401), ("enterprise", 403), ("expired", 401), ("disabled", 403), ("impersonating", 403)],
)
def test_rejects_before_transport_or_credential_lookup(
    platform_client, method, suffix, session, status
):
    client, upstream, bound, fallback, transport = platform_client
    headers = {} if session is None else {"Cookie": f"session_id={session}"}
    response = client.request(method, PATH + suffix, headers=headers, content=SECRET)
    assert response.status_code == status
    assert response.headers["cache-control"] == "no-store"
    assert SECRET not in response.text
    transport.assert_not_called()
    for call in (upstream, bound, fallback):
        call.assert_not_awaited()


@pytest.mark.parametrize(
    "method,suffix", [("GET", ""), ("PUT", "/openai"), ("POST", "/openai/test")]
)
def test_admin_uses_only_bound_token_and_sensitive_transport(platform_client, method, suffix):
    client, upstream, bound, fallback, _ = platform_client
    body = {"api_key": SECRET, "token": "must-not-authorize", "model": "synthetic-model"}
    response = client.request(
        method, PATH + suffix, headers={"Cookie": "session_id=admin"}, json=body
    )
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.headers["cache-control"] == "no-store"
    kwargs = upstream.call_args.kwargs
    assert kwargs["authorization"] == "Bearer synthetic-session-token"
    assert kwargs["sensitive"] is True
    assert kwargs["retries"] == 1
    assert kwargs["json_body"] == (None if method == "GET" else body)
    bound.assert_awaited_once()
    fallback.assert_not_awaited()


@pytest.mark.parametrize("status", [400, 401, 403, 409, 422, 429, 500, 502, 503])
@pytest.mark.parametrize("response_type", ["envelope", "response", "exception"])
def test_upstream_failure_never_reflects_credentials(
    platform_client, caplog, status, response_type
):
    client, upstream, _, _, _ = platform_client
    if response_type == "response":
        upstream.return_value = JSONResponse({"detail": SECRET}, status_code=status)
    elif response_type == "exception":
        upstream.side_effect = RuntimeError(SECRET)
    else:
        upstream.return_value = {
            "__proxy_error__": True,
            "status_code": status,
            "payload": {"detail": SECRET},
        }
    response = client.put(
        PATH + "/openai", headers={"Cookie": "session_id=admin"}, json={"api_key": SECRET}
    )
    assert response.status_code == (502 if response_type == "exception" else status)
    assert response.json()["success"] is False
    assert response.json()["message"]
    assert SECRET not in response.text + caplog.text


def test_no_bound_token_cannot_borrow_body_or_fallback_credentials(platform_client):
    client, upstream, bound, fallback, _ = platform_client
    bound.return_value = ""
    response = client.put(
        PATH + "/openai",
        headers={"Cookie": "session_id=admin", "Authorization": "Bearer alternate"},
        json={"token": "alternate", "api_key": SECRET},
    )
    assert response.status_code == 401
    upstream.assert_not_awaited()
    fallback.assert_not_awaited()


@pytest.mark.parametrize(
    "subpath",
    [
        "llm/unused/%2e%2e/admin/platform-model-config",
        "llm/unused/%252e%252e/admin/platform-model-config",
        "llm//admin/platform-model-config",
        "llm%5cadmin/platform-model-config",
        "llm/admin/platform-model-config%3fother",
    ],
)
def test_path_normalization_cannot_bypass_sensitive_gate(platform_client, subpath):
    client, upstream, bound, fallback, transport = platform_client
    response = client.put(
        "/api/xcmax/market-proxy/" + subpath,
        headers={"Cookie": "session_id=impersonating"},
        json={"api_key": SECRET, "token": "forged-admin-token"},
    )
    assert response.status_code == 400
    transport.assert_not_called()
    for call in (upstream, bound, fallback):
        call.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("current", ["", "synthetic-current-session-token"])
async def test_real_bound_token_resolver_never_borrows_other_session(monkeypatch, current):
    from app.fastapi_routes import market_account
    from app.fastapi_routes.admin_control.backends import bound_market_authorization

    request = Request({"type": "http", "headers": [(b"cookie", b"session_id=verified")]})
    monkeypatch.setattr(
        market_account, "session_market_token", lambda sid: current if sid == "verified" else ""
    )
    monkeypatch.setattr(market_account, "_user_id_from_session", lambda _: 7)
    latest = Mock(return_value="other-session-token")
    remote = AsyncMock(return_value={"ok": True})
    monkeypatch.setattr(market_account, "latest_session_market_token", latest)
    monkeypatch.setattr(market_account, "_proxy_json", remote)
    assert await bound_market_authorization(request) == (f"Bearer {current}" if current else "")
    latest.assert_not_called()
    if current:
        assert remote.call_args.kwargs["authorization"] == f"Bearer {current}"
    else:
        remote.assert_not_awaited()
