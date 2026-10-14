from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.fastapi_routes.mods_routes import get_mods_router


def test_mods_list_supports_etag_304(monkeypatch):
    # Cache semantics require a stable representation, not a live Mod scan.
    rows = [{"id": "etag-fixture", "scope": "global", "version": "1"}]
    manager = SimpleNamespace(list_all_mods=lambda: rows)
    monkeypatch.setattr("app.infrastructure.mods.mod_manager.get_mod_manager", lambda: manager)
    app = FastAPI()
    app.include_router(get_mods_router())
    client = TestClient(app)
    first = client.get("/api/mods/")
    assert first.status_code == 200, first.text
    etag = first.headers.get("etag") or first.headers.get("ETag")
    assert etag
    second = client.get("/api/mods/", headers={"If-None-Match": etag})
    assert second.status_code == 304
    rows[0]["version"] = "2"
    changed = client.get("/api/mods/", headers={"If-None-Match": etag})
    assert changed.status_code == 200
    assert changed.headers["etag"] != etag
    assert changed.json() == {"success": True, "data": rows}
