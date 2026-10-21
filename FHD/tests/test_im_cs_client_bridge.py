from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db.models.im import (
    ImConversation,
    ImConversationMember,
    ImCustomerServiceAutomationState,
    ImMessage,
)
from app.db.models.user import User
from app.infrastructure.auth.dependencies import CurrentUser, require_identified_user


@pytest.fixture()
def bridge_db(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))
    engine = create_engine(f"sqlite:///{tmp_path / 'bridge.db'}")
    for table in (
        User.__table__,
        ImConversation.__table__,
        ImConversationMember.__table__,
        ImMessage.__table__,
        ImCustomerServiceAutomationState.__table__,
    ):
        table.create(engine, checkfirst=True)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        db.add(
            User(
                id=39,
                username="wuxinghua1",
                password="!",
                display_name="wuxinghua1",
                is_active=True,
                tier="enterprise",
                market_user_id=501,
            )
        )
        db.commit()
    return factory


def test_remote_bridge_uses_canonical_market_user_and_schedules_ai(bridge_db) -> None:
    from app.fastapi_routes import im_cs_client_routes as routes

    app = FastAPI()
    app.include_router(routes.router)
    identity = {"market_user_id": 501, "username": "wuxinghua1"}
    background = AsyncMock(return_value={"handled": True})
    with (
        patch.object(routes, "_ensure_schema"),
        patch.object(routes, "HostSessionLocal", side_effect=bridge_db),
        patch.object(routes, "_validate_market_identity", AsyncMock(return_value=identity)),
        patch.object(routes, "process_enterprise_cs_customer_message", background),
    ):
        client = TestClient(app)
        first = client.get(
            "/api/im/enterprise-cs/remote/messages",
            headers={"Authorization": "Bearer market-token"},
        )
        sent = client.post(
            "/api/im/enterprise-cs/remote/messages",
            headers={"Authorization": "Bearer market-token"},
            json={"body": "请说明常规帮助范围"},
        )

    assert first.status_code == 200
    assert first.json()["conversation"]["is_enterprise_dedicated_cs"] is True
    assert sent.status_code == 200
    assert sent.json()["message"]["sender_user_id"] == 39
    assert sent.json()["message"]["is_self"] is True
    assert sent.json()["message"]["origin"] == "customer"
    background.assert_awaited_once()
    assert background.await_args.args[1] == 39
    with bridge_db() as db:
        row = db.execute(
            select(ImMessage).where(ImMessage.body == "请说明常规帮助范围")
        ).scalar_one()
        assert row.sender_user_id == 39
    from app.db.xcmax_sync import SyncDb

    assert not [
        item
        for item in SyncDb().get_changes(since_cursor=0, limit=50)
        if item.get("entity_type") in {"im_message", "im_read_state"}
    ]


@pytest.mark.asyncio
async def test_market_identity_rejects_non_enterprise() -> None:
    from app.fastapi_routes import im_cs_client_routes as routes

    request = type(
        "RequestStub",
        (),
        {"headers": {"Authorization": "Bearer market-token"}},
    )()
    payload = {"id": 7, "username": "personal-user", "is_enterprise": False}
    with patch("app.fastapi_routes.market_account._proxy_json", AsyncMock(return_value=payload)):
        with pytest.raises(HTTPException) as exc:
            await routes._validate_market_identity(request)
    assert exc.value.status_code == 403


def test_local_bridge_forwards_session_bound_token_only() -> None:
    from app.fastapi_routes import im_cs_client_routes as routes

    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[require_identified_user] = lambda: CurrentUser(2)
    forwarded = AsyncMock(
        return_value=JSONResponse({"success": True, "conversation": {"id": 12}, "messages": []})
    )
    with (
        patch.object(routes, "_local_market_token", AsyncMock(return_value="bound-token")),
        patch.object(routes, "_proxy_to_production", forwarded),
    ):
        response = TestClient(app).get(
            "/api/im/enterprise-cs/messages", headers={"X-Session-ID": "bound-session"}
        )

    assert response.status_code == 200
    forwarded.assert_awaited_once_with("GET", "bound-token", session_id="bound-session")


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["GET", "POST"])
@pytest.mark.parametrize(
    "initial,refresh_token,post_status",
    [
        (401, "fresh", 200),
        (401, "", 200),
        (403, "fresh", 200),
        (503, "fresh", 200),
        (401, "fresh", 401),
    ],
)
async def test_bridge_recovers_only_before_sending(method, initial, refresh_token, post_status):
    from app.fastapi_routes import im_cs_client_routes as routes

    requests = []

    def remote(request):
        requests.append((request.method, request.headers.get("Authorization")))
        if request.method == "POST":
            assert request.headers["X-CSRF-Token"] == "csrf"
            return httpx.Response(post_status, json={"success": post_status == 200})
        status = 200 if request.headers["Authorization"] == "Bearer fresh" else initial
        return httpx.Response(
            status,
            json={"success": status == 200},
            headers={"Set-Cookie": "csrf_token=csrf; Path=/"},
        )

    client_type = httpx.AsyncClient
    refresh = AsyncMock(return_value=refresh_token)
    with (
        patch.object(
            routes.httpx,
            "AsyncClient",
            lambda **kw: client_type(transport=httpx.MockTransport(remote), **kw),
        ),
        patch("app.fastapi_routes.market_account.refresh_session_market_token", refresh),
        patch("app.fastapi_routes.market_account.session_market_token", return_value="expired"),
    ):
        response = await routes._proxy_to_production(
            method, "expired", body={"body": "original"}, session_id="bound-session"
        )
    if initial == 401:
        refresh.assert_awaited_once_with("bound-session")
    else:
        refresh.assert_not_awaited()
    recovered = initial == 401 and bool(refresh_token)
    assert len([r for r in requests if r[0] == "GET"]) == (2 if recovered else 1)
    assert len([r for r in requests if r[0] == "POST"]) == int(recovered and method == "POST")
    assert response.status_code == (
        post_status if recovered and method == "POST" else 200 if recovered else initial
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure", ["GET", "POST", "refresh_deadline", "response_invalid", "server_error"]
)
async def test_bridge_never_replays_timeout_or_outlives_auth_deadline(failure):
    from app.fastapi_routes import im_cs_client_routes as routes

    sent = []

    def remote(request):
        sent.append(request.method)
        if request.method == failure:
            raise httpx.ReadTimeout("fixture timeout", request=request)
        if request.method == "POST" and failure == "response_invalid":
            return httpx.Response(200, content=b"unparseable")
        if request.method == "POST" and failure == "server_error":
            return httpx.Response(503, json={"success": False})
        status = 401 if failure == "refresh_deadline" else 200
        return httpx.Response(
            status,
            json={"success": status == 200},
            headers={"Set-Cookie": "csrf_token=csrf; Path=/"},
        )

    async def stalled_refresh(_sid):
        await asyncio.Event().wait()

    refresh = AsyncMock(side_effect=stalled_refresh)
    original_timeout, client_type = asyncio.timeout, httpx.AsyncClient
    with (
        patch.object(
            routes.asyncio,
            "timeout",
            lambda budget: original_timeout(0.02 if failure == "refresh_deadline" else budget),
        ),
        patch.object(
            routes.httpx,
            "AsyncClient",
            lambda **kw: client_type(transport=httpx.MockTransport(remote), **kw),
        ),
        patch("app.fastapi_routes.market_account.refresh_session_market_token", refresh),
    ):
        response = await routes._proxy_to_production(
            "POST", "bound", body={"body": "original"}, session_id="bound-session"
        )
    assert response.status_code == 502
    sent_post = failure in {"POST", "response_invalid", "server_error"}
    assert sent == (["GET", "POST"] if sent_post else ["GET"])
    payload = json.loads(response.body)
    if sent_post:
        assert payload["outcome"] == "unknown" and payload["retryable"] is False
        assert payload["reconciliation_required"] is True
    else:
        assert "outcome" not in payload
    if failure == "refresh_deadline":
        refresh.assert_awaited_once_with("bound-session")
    else:
        refresh.assert_not_awaited()
