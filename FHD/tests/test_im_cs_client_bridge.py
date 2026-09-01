from __future__ import annotations

from unittest.mock import AsyncMock, patch

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
        response = TestClient(app).get("/api/im/enterprise-cs/messages")

    assert response.status_code == 200
    forwarded.assert_awaited_once_with("GET", "bound-token")
