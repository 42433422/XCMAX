from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from modstore_server.api.csrf import CSRFMiddleware


def test_valid_internal_key_bypasses_browser_csrf(monkeypatch):
    monkeypatch.setenv("MODSTORE_DISABLE_CSRF", "0")
    monkeypatch.setenv("MODSTORE_INTERNAL_API_KEY", "shared-key")
    monkeypatch.setenv("XCAGI_MARKET_INTERNAL_API_KEY", "secondary-key")
    app = FastAPI()

    @app.post("/machine")
    def machine():
        return {"ok": True}

    app.add_middleware(CSRFMiddleware)
    client = TestClient(app)
    assert client.post("/machine").status_code == 403
    assert client.post("/machine", headers={"X-Internal-Api-Key": "wrong-key"}).status_code == 403
    response = client.post("/machine", headers={"X-Internal-Api-Key": "shared-key"})
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_cs_intake_secret_is_not_an_internal_management_key(monkeypatch):
    monkeypatch.setenv("MODSTORE_DISABLE_CSRF", "0")
    monkeypatch.delenv("MODSTORE_INTERNAL_API_KEY", raising=False)
    monkeypatch.delenv("XCAGI_MARKET_INTERNAL_API_KEY", raising=False)
    monkeypatch.setenv("XCAGI_CS_INTAKE_LINK_SECRET", "cs-only-secret")
    app = FastAPI()

    @app.post("/machine")
    def machine():
        return {"ok": True}

    app.add_middleware(CSRFMiddleware)
    response = TestClient(app).post(
        "/machine",
        headers={"X-Internal-Api-Key": "cs-only-secret"},
    )
    assert response.status_code == 403
