"""POST /api/xcmax/sync/receive requires the shared node secret and fails closed."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.fastapi_routes.xcmax_admin import router

URL = "/api/xcmax/sync/receive"
ITEM = {"entity_type": "personnel", "entity_id": "1", "operation": "insert"}


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_sync_receive_fails_closed_without_configured_secret(monkeypatch) -> None:
    monkeypatch.delenv("XCMAX_SYNC_SHARED_SECRET", raising=False)
    headers = {"X-XCMAX-Sync-Token": "anything"}
    assert _client().post(URL, json=ITEM, headers=headers).status_code == 503


def test_sync_receive_checks_shared_secret(monkeypatch) -> None:
    monkeypatch.setenv("XCMAX_SYNC_SHARED_SECRET", "node-secret")
    client = _client()
    db = MagicMock()
    db.enqueue_inbox.return_value = 1
    with (
        patch("app.db.xcmax_sync.SyncDb", return_value=db),
        patch("app.application.xcmax_sync_app.apply_inbox", return_value={"applied": 1}),
        patch("app.mod_sdk.audit.write_audit_event"),
    ):
        assert client.post(URL, json=ITEM).status_code == 401
        wrong = {"X-XCMAX-Sync-Token": "nope"}
        assert client.post(URL, json=ITEM, headers=wrong).status_code == 401
        db.enqueue_inbox.assert_not_called()
        ok = client.post(URL, json=ITEM, headers={"X-XCMAX-Sync-Token": "node-secret"})
        batch = client.post(URL, json=[ITEM, ITEM], headers={"X-XCMAX-Sync-Token": "node-secret"})
    assert ok.status_code == 200
    assert ok.json()["received"] == 1
    assert batch.status_code == 200
