from __future__ import annotations

from fastapi.testclient import TestClient

from app.fastapi_app import create_fastapi_app
from app.fastapi_app.mod_startup import wait_for_background_mod_load


def test_mods_list_supports_etag_304(monkeypatch):
    monkeypatch.setenv("XCAGI_DESKTOP_FAST_START", "0")
    client = TestClient(create_fastapi_app())
    assert wait_for_background_mod_load(client.app)
    first = client.get("/api/mods/")
    assert first.status_code == 200, first.text
    etag = first.headers.get("etag") or first.headers.get("ETag")
    assert etag
    second = client.get("/api/mods/", headers={"If-None-Match": etag})
    assert second.status_code == 304
