"""Real manifest scanner + signed install + current-session route/cache isolation."""

from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_private_navigation_and_etag_follow_current_owner_and_live_entitlement(
    signed_runtime_mod, mod_accounts, monkeypatch
):
    from app.db.models.user import Session
    from app.fastapi_routes.mods_routes import get_mods_router
    from app.infrastructure.mods.mod_manager import ModManager

    signed_runtime_mod.install()
    monkeypatch.setenv("XCAGI_MODS_ROOT", str(signed_runtime_mod.root))
    manager = ModManager(mods_root=str(signed_runtime_mod.root))
    monkeypatch.setattr("app.infrastructure.mods.mod_manager.get_mod_manager", lambda: manager)
    # The Market sync boundary is offline; real session records remain authoritative.
    monkeypatch.setattr(
        "app.fastapi_routes.mods_routes._sync_enterprise_entitlements_from_request", AsyncMock()
    )
    app = FastAPI()
    app.include_router(get_mods_router())
    with TestClient(app) as client:
        client.cookies.set("session_id", "mod-session-1")
        first = client.get("/api/mods")
        assert first.status_code == 200, first.text
        rows = first.json()["data"]
        private = next(row for row in rows if row["id"] == "unknown-ui-fixture")
        assert private["scope"] == "account"
        assert private["frontend"]["runtime"]["sdk_version"] == 1
        etag = first.headers["etag"]
        assert client.get("/api/mods", headers={"If-None-Match": etag}).status_code == 304
        routes = client.get("/api/mods/routes").json()["data"]
        assert any(
            row["mod_id"] == "unknown-ui-fixture" and row["runtime"]["owner_scope"] == "tenant:1"
            for row in routes
        )
        client.cookies.set("session_id", "mod-session-2")
        other = client.get("/api/mods", headers={"If-None-Match": etag})
        assert other.status_code == 200
        assert other.headers["etag"] != etag
        assert all(row["id"] != "unknown-ui-fixture" for row in other.json()["data"])
        assert all(
            row["mod_id"] != "unknown-ui-fixture"
            for row in client.get("/api/mods/routes").json()["data"]
        )
        client.cookies.set("session_id", "mod-session-1")
        with mod_accounts.sessions.begin() as db:
            db.query(Session).filter(
                Session.session_id == "mod-session-1"
            ).one().entitled_mod_ids_json = "[]"
        revoked = client.get("/api/mods", headers={"If-None-Match": etag})
        assert revoked.status_code == 200
        assert all(row["id"] != "unknown-ui-fixture" for row in revoked.json()["data"])
        client.cookies.clear()
        assert all(
            row["id"] != "unknown-ui-fixture" for row in client.get("/api/mods").json()["data"]
        )
