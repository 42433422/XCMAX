from __future__ import annotations

import types

from fastapi import FastAPI
from fastapi.testclient import TestClient

from modstore_server.api.deps import get_current_user
from modstore_server.redline_approval_api import router


def test_redline_routes_reject_non_admin():
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: types.SimpleNamespace(
        id=8, username="user", is_admin=False
    )
    client = TestClient(app)
    assert client.get("/api/admin/redline/pending").status_code == 403
    assert client.post("/api/admin/redline/requests/1/approve", json={}).status_code == 403
    assert client.post("/api/admin/redline/requests/1/reject", json={}).status_code == 403
    assert client.get("/api/admin/redline/domains").status_code == 403
    assert client.post("/api/admin/redline/timeout-check").status_code == 403


def test_redline_approval_uses_authenticated_admin(monkeypatch):
    import modstore_server.redline_approval_gate as gate

    seen = {}

    def approve(cr_id, admin_user_id, *, comment=""):
        seen.update(cr_id=cr_id, admin_user_id=admin_user_id, comment=comment)
        return {"ok": True}

    monkeypatch.setattr(gate, "approve_redline_request", approve)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: types.SimpleNamespace(
        id=42, username="admin", is_admin=True
    )
    response = TestClient(app).post(
        "/api/admin/redline/requests/7/approve",
        json={"admin_user_id": 999, "comment": "reviewed"},
    )
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert seen == {"cr_id": 7, "admin_user_id": 42, "comment": "reviewed"}
