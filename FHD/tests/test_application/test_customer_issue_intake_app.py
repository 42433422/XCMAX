from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application import customer_issue_intake_app as intake
from app.services import user_cs_change_request as store


@pytest.fixture
def local_store(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_store_roots", lambda: [tmp_path])


def test_remote_retry_reuses_original_local_ticket_and_owner(local_store, monkeypatch):
    calls = []

    async def remote(token, path, **kwargs):
        calls.append(kwargs["payload"])
        if len(calls) == 1:
            raise ConnectionError("temporary outage")
        return {"success": True, "ticket_id": 12, "ticket_no": "CI-fixture"}

    monkeypatch.setattr(intake, "custom_delivery_remote_json", remote)
    kwargs = {
        "market_user_id": 7,
        "token": "synthetic-token",
        "mod_id": "taiyangniao-pro",
        "track": "modules",
        "node_id": "convert",
        "note": "转换格式错误",
        "version": "1.0.0",
    }
    with pytest.raises(ConnectionError):
        asyncio.run(intake.submit_private_rework(**kwargs))
    rows = store.list_change_requests(7)
    assert len(rows) == 1 and rows[0]["intake_error"]
    result = asyncio.run(intake.submit_private_rework(**kwargs))
    assert result["market_ticket_id"] == 12 and result["ticket_no"] == "CI-fixture"
    assert calls[0]["source_ref"] == calls[1]["source_ref"]
    assert len(store.list_change_requests(7)) == 1 and not store.list_change_requests(8)


def test_missing_token_creates_no_local_success(local_store):
    with pytest.raises(PermissionError):
        asyncio.run(
            intake.submit_private_rework(
                market_user_id=7,
                token="",
                mod_id="private",
                track="modules",
                node_id="",
                note="转换格式错误",
                version="1.0.0",
            )
        )
    assert not store.list_change_requests(7)


def test_route_rejects_invalid_transition_before_intake_and_preserves_failed_state(
    tmp_path, monkeypatch, local_store
):
    from app.application import private_mod_delivery_app as delivery
    from app.fastapi_routes import mod_store_routes  # load the public facade first
    from app.fastapi_routes import private_mod_delivery_context as context
    from app.fastapi_routes import private_mod_delivery_progress_routes as routes

    monkeypatch.setattr(delivery, "_state_path", lambda: tmp_path / "delivery.json")

    async def private_context(request):
        return {"mod_ids": {"taiyangniao-pro"}, "market_user_id": 7, "username": "fixture"}

    async def token(request):
        return "synthetic-token"

    monkeypatch.setattr(routes, "_private_mod_context", private_context)
    monkeypatch.setattr(context, "_private_delivery_market_token", token)
    monkeypatch.setattr(routes, "_enterprise_delivery_scope", lambda *args: "market:7")
    monkeypatch.setattr(
        routes, "_private_mod_local_rows", lambda ids: {mid: {"version": "1.0.0"} for mid in ids}
    )
    calls = []

    async def reject(**kwargs):
        calls.append(kwargs)
        raise ConnectionError("fixture offline")

    monkeypatch.setattr(intake, "submit_private_rework", reject)
    app = FastAPI()
    app.include_router(routes.router)
    client = TestClient(app)
    body = {
        "mod_id": "taiyangniao-pro",
        "track": "modules",
        "status": "rework",
        "note": "转换格式错误",
    }
    assert client.post("/private-delivery/status", json=body).status_code == 400
    assert not calls
    delivery.set_track_status("market:7", "taiyangniao-pro", "modules", "testing")
    assert client.post("/private-delivery/status", json=body).status_code == 502
    assert len(calls) == 1
    assert (
        delivery.account_projects("market:7", {"taiyangniao-pro"})[0]["tracks"]["modules"]["status"]
        == "testing"
    )
