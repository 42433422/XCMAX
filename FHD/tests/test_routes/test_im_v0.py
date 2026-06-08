"""IM V0 API 冒烟。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _im_sqlite_db(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """``sqlite://`` 在 SQLAlchemy 下无法持久化表；IM 测试使用临时文件库。"""
    db_file = tmp_path / "im_v0_test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    from app.db import dispose_and_recreate_engine, engine
    from app.db.init_db import init_im_tables

    dispose_and_recreate_engine()
    init_im_tables(engine)


@pytest.fixture(autouse=True)
def _disable_lan_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LAN_GUARD_ENABLED", "0")
    from app.security.lan_config import reset_lan_config_cache
    from app.security.lan_settings_store import LanSettingsOverride

    monkeypatch.setattr(
        "app.security.lan_settings_store.load_overrides",
        lambda: LanSettingsOverride(enabled=False),
    )
    reset_lan_config_cache()


def _csrf_headers(client: TestClient, user_id: str) -> dict[str, str]:
    client.get("/api/health")
    token = client.cookies.get("csrf_token") or ""
    return {"X-User-ID": user_id, "X-CSRF-Token": token}


def test_im_direct_conversation_and_message(client: TestClient):
    h1 = _csrf_headers(client, "1")
    h2 = _csrf_headers(client, "2")

    r = client.post(
        "/api/im/conversations/direct",
        json={"peer_user_id": 2},
        headers=h1,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("success") is True
    conv_id = body["conversation"]["id"]

    r2 = client.post(
        f"/api/im/conversations/{conv_id}/messages",
        json={"body": "hello im v0"},
        headers=h1,
    )
    assert r2.status_code == 200, r2.text
    assert r2.json().get("success") is True

    r3 = client.get(
        f"/api/im/conversations/{conv_id}/messages",
        params={"user_id": 2},
        headers=h2,
    )
    assert r3.status_code == 200, r3.text
    msgs = r3.json().get("messages") or []
    assert any(m.get("body") == "hello im v0" for m in msgs)

    r4 = client.get("/api/im/conversations", headers=h1)
    assert r4.status_code == 200
    assert any(c["id"] == conv_id for c in r4.json().get("conversations") or [])


def test_im_websocket_ping(client: TestClient):
    with client.websocket_connect("/ws/im?user_id=9") as ws:
        ws.send_text("ping")
        data = ws.receive_text()
        assert "pong" in data
