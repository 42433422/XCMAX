"""内部服务密钥仅开放管理端跨服务读接口，写接口仍要求管理员 JWT。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient


def _internal_headers() -> dict[str, str]:
    return {"X-Internal-Api-Key": "pytest-internal-read-key"}


def test_action_item_reads_accept_internal_key_but_write_does_not(monkeypatch) -> None:
    from modstore_server.action_items_api import router

    monkeypatch.setenv("XCAGI_MARKET_INTERNAL_API_KEY", "pytest-internal-read-key")
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    with (
        patch("modstore_server.digest_action_items.latest_day", return_value="2026-08-27"),
        patch("modstore_server.digest_action_items.list_action_items", return_value=[]),
        patch("modstore_server.digest_action_items.stats", return_value={"total": 0}),
    ):
        listed = client.get("/api/admin/action-items?kind=patch", headers=_internal_headers())
        stats = client.get("/api/admin/action-items/stats?kind=patch", headers=_internal_headers())

    assert listed.status_code == 200
    assert listed.json()["ok"] is True
    assert stats.status_code == 200
    assert stats.json()["ok"] is True
    assert client.get("/api/admin/action-items?kind=patch").status_code == 401

    write = client.post(
        "/api/admin/action-items/1/status",
        headers=_internal_headers(),
        json={"status": "closed"},
    )
    assert write.status_code == 401


def test_daily_digest_artifacts_accept_internal_key(monkeypatch) -> None:
    from modstore_server.agent_butler_api import router
    from modstore_server.infrastructure.db import get_db

    monkeypatch.setenv("XCAGI_MARKET_INTERNAL_API_KEY", "pytest-internal-read-key")
    row = SimpleNamespace(
        day="2026-08-27",
        subject="日更",
        meeting_minutes_html="",
        delivered=True,
        body_html="",
        body_text="",
    )
    db = MagicMock()
    db.get.return_value = row
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: db

    with (
        patch("modstore_server.agent_butler_api._dd_list_dir", return_value=[]),
        patch("modstore_server.release_train.snapshot_public", return_value={}),
        patch("modstore_server.release_train.list_release_train_history", return_value=[]),
        patch("modstore_server.daily_backup_job.list_backups", return_value=[]),
    ):
        response = TestClient(app).get(
            "/api/agent/butler/daily-digests/50/artifacts",
            headers=_internal_headers(),
        )

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert response.json()["data"]["record_id"] == 50
