from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.application.mod_update_discovery import available_updates
from app.fastapi_routes import mod_store_routes


def test_versions_compare_numerically_and_do_not_offer_downgrades_or_prereleases():
    local = {"shared": {"version": "1.9.0"}, "same": {"version": "1.0.0.0"}}
    remote = [
        {"id": "shared", "version": "1.10.0"},
        {"id": "shared", "version": "1.8.0"},
        {"id": "shared", "version": "2.0.0-beta"},
        {"id": "same", "version": "1.0.0"},
        {"id": "absent", "version": "2.0.0"},
    ]
    assert [(r["mod_id"], r["new_version"]) for r in available_updates(local, remote, [])] == [
        ("shared", "1.10.0")
    ]


def test_private_identity_cannot_be_replaced_by_public_namesake():
    updates = available_updates(
        {"custom": {"version": "1.0.0"}},
        [{"id": "custom", "version": "99.0.0"}],
        [{"id": "custom", "version": "1.1.0"}],
    )
    assert updates[0]["new_version"] == "1.1.0"
    assert updates[0]["source"] == "private_mod_sync"


@pytest.fixture
def api(monkeypatch):
    app = FastAPI()
    app.include_router(mod_store_routes.router, prefix="/api/mod-store")
    monkeypatch.setattr(
        "app.infrastructure.auth.dependencies.get_logged_in_user",
        lambda request: SimpleNamespace(id=1),
    )
    monkeypatch.setattr(
        "app.application.tenant_workspace_prefs.resolve_workspace_owner_id",
        lambda request, user: "tenant:1",
    )
    monkeypatch.setattr(
        "app.infrastructure.mods.install_receipts.read_verified_install", lambda mid: None
    )
    monkeypatch.setattr(
        mod_store_routes, "_installed_by_id", lambda: {"custom": {"version": "1.0.0"}}
    )

    async def token(request):
        return "caller-token"

    monkeypatch.setattr(
        "app.fastapi_routes.private_mod_delivery_context._private_delivery_market_token", token
    )
    return TestClient(app)


def test_offline_sources_are_reported_as_incomplete_not_no_updates(api, monkeypatch):
    async def public():
        raise HTTPException(502, "unavailable")
        yield

    async def private(token):
        assert token == "caller-token"
        raise HTTPException(502, "unavailable")

    monkeypatch.setattr(mod_store_routes, "iter_catalog_packages", public)
    monkeypatch.setattr(
        "app.application.private_mod_delivery_artifacts.fetch_private_mod_library", private
    )
    data = api.get("/api/mod-store/updates").json()["data"]
    assert data["complete"] is False
    assert set(data["source_errors"]) == {"public_catalog", "private_mod_sync"}


def test_other_owner_local_mod_is_not_offered(api, monkeypatch):
    monkeypatch.setattr(
        "app.infrastructure.mods.install_receipts.read_verified_install",
        lambda mid: {"owner_scope": "tenant:2"},
    )

    async def public():
        yield {"id": "custom", "version": "2.0.0"}

    async def private(token):
        return [{"id": "custom", "version": "1.1.0"}]

    monkeypatch.setattr(mod_store_routes, "iter_catalog_packages", public)
    monkeypatch.setattr(
        "app.application.private_mod_delivery_artifacts.fetch_private_mod_library", private
    )
    data = api.get("/api/mod-store/updates").json()["data"]
    assert data["complete"] is True
    assert data["updates_available"] == []


def test_update_requires_current_session(api, monkeypatch):
    def logged_out(request):
        raise HTTPException(401, "login required")

    monkeypatch.setattr("app.infrastructure.auth.dependencies.get_logged_in_user", logged_out)
    assert api.get("/api/mod-store/updates").status_code == 401
    assert api.post("/api/mod-store/update", json={"mod_id": "custom"}).status_code == 401
