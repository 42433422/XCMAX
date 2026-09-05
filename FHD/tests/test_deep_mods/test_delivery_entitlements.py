import json
from unittest.mock import AsyncMock

import pytest
from starlette.requests import Request

from app.application import delivery_entitlements as bridge
from app.db.models.user import Session
from app.enterprise.private_delivery_binding import (
    load_session_private_delivery_binding,
)


def request():
    return Request({"type": "http", "headers": [(b"x-session-id", b"mod-session-1")]})


@pytest.mark.asyncio
async def test_new_signed_delivery_rights_update_only_actual_session(mod_accounts, monkeypatch):
    remote = AsyncMock(
        return_value={
            "ok": True,
            "user_id": 101,
            "mod_ids": ["new-private-employee", "../bad", 123],
        }
    )
    monkeypatch.setattr(bridge, "custom_delivery_remote_json", remote)
    assert await bridge.refresh_delivery_entitlements(request(), "owner-token")
    assert load_session_private_delivery_binding("mod-session-1")["mod_ids"] == {
        "new-private-employee"
    }
    assert load_session_private_delivery_binding("mod-session-2")["mod_ids"] == set()
    remote.assert_awaited_once_with("owner-token", "/api/enterprise/entitled-mod-ids")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "result",
    [
        ConnectionError("offline"),
        {"ok": True, "user_id": 102, "mod_ids": ["other-private"]},
        {"ok": False, "user_id": 101, "mod_ids": []},
    ],
)
async def test_failed_or_wrong_account_refresh_preserves_previous_rights(
    mod_accounts, monkeypatch, result
):
    remote = (
        AsyncMock(side_effect=result)
        if isinstance(result, Exception)
        else AsyncMock(return_value=result)
    )
    monkeypatch.setattr(bridge, "custom_delivery_remote_json", remote)
    assert not await bridge.refresh_delivery_entitlements(request(), "owner-token")
    assert load_session_private_delivery_binding("mod-session-1")["mod_ids"] == {"taiyangniao-pro"}


@pytest.mark.asyncio
async def test_account_change_while_fetching_cannot_grant_late_rights(mod_accounts, monkeypatch):
    async def changed(*args):
        with mod_accounts.sessions.begin() as db:
            row = db.query(Session).filter_by(session_id="mod-session-1").one()
            row.market_user_id = 102
            row.entitled_mod_ids_json = json.dumps(["owner-two"])
        return {"ok": True, "user_id": 101, "mod_ids": ["owner-one-new"]}

    monkeypatch.setattr(bridge, "custom_delivery_remote_json", changed)
    assert not await bridge.refresh_delivery_entitlements(request(), "owner-token")
    assert load_session_private_delivery_binding("mod-session-1")["mod_ids"] == {"owner-two"}


@pytest.mark.asyncio
async def test_login_fetch_keeps_dynamic_runtime_entitlement(monkeypatch):
    from app.enterprise.mod_entitlements import (
        fetch_entitled_client_mod_ids_from_market,
    )

    remote = AsyncMock(
        return_value={
            "ok": True,
            "user_id": 101,
            "mod_ids": ["new-private-employee", "../bad", 123],
        }
    )
    monkeypatch.setattr("app.fastapi_routes.market_account._proxy_json", remote)
    assert await fetch_entitled_client_mod_ids_from_market("owner-token") == {
        "new-private-employee"
    }


@pytest.mark.asyncio
async def test_impersonation_does_not_fetch_admin_rights_or_replace_customer_projection(
    mod_accounts, monkeypatch
):
    with mod_accounts.sessions.begin() as db:
        row = db.query(Session).filter_by(session_id="mod-session-1").one()
        row.impersonating_market_user_id = 102
        row.impersonating_username = "OTHER"
        row.entitled_mod_ids_json = '["customer-private"]'
    remote = AsyncMock(return_value={"ok": True, "user_id": 101, "mod_ids": ["admin-private"]})
    monkeypatch.setattr(bridge, "custom_delivery_remote_json", remote)
    assert not await bridge.refresh_delivery_entitlements(request(), "admin-token")
    remote.assert_not_awaited()
    assert load_session_private_delivery_binding("mod-session-1")["mod_ids"] == {"customer-private"}


@pytest.mark.asyncio
async def test_entering_impersonation_during_network_read_discards_late_admin_rights(
    mod_accounts, monkeypatch
):
    async def remote(*args):
        with mod_accounts.sessions.begin() as db:
            row = db.query(Session).filter_by(session_id="mod-session-1").one()
            row.impersonating_market_user_id = 102
            row.impersonating_username = "OTHER"
            row.entitled_mod_ids_json = '["customer-private"]'
        return {"ok": True, "user_id": 101, "mod_ids": ["admin-private"]}

    monkeypatch.setattr(bridge, "custom_delivery_remote_json", remote)
    assert not await bridge.refresh_delivery_entitlements(request(), "admin-token")
    assert load_session_private_delivery_binding("mod-session-1")["mod_ids"] == {"customer-private"}
