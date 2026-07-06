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
    from app.db import SessionLocal, dispose_and_recreate_engine, engine
    from app.db.base import Base
    from app.db.init_db import init_im_tables
    from app.db.models.ai_employee import AiEmployeeProfile
    from app.db.models.user import User

    dispose_and_recreate_engine()
    Base.metadata.create_all(
        engine, tables=[User.__table__, AiEmployeeProfile.__table__], checkfirst=True
    )
    init_im_tables(engine)
    session = SessionLocal()
    try:
        for uid, username in [(1, "im_u1"), (2, "im_u2"), (9, "im_u9")]:
            if session.get(User, uid) is None:
                session.add(
                    User(
                        id=uid,
                        username=username,
                        password="test-hash",
                        display_name=username,
                        is_active=True,
                    )
                )
        session.commit()
    finally:
        session.close()


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


def test_admin_employee_chat_persists_and_is_reloadable(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    """管理端员工对话：用户消息 + 员工回复都持久化到同一 IM 会话，刷新可重载。

    PRODUCT_POLISH_CHECKLIST P1 路径三：不再是前端内存、刷新即丢。
    """
    import app.application.employee_runtime.executor as executor

    monkeypatch.setattr(
        executor,
        "execute_employee_task_local",
        lambda *a, **k: {"success": True, "response": "已为你完成排产建议。"},
    )

    h1 = _csrf_headers(client, "1")
    eid = "llm-ops-engineer"

    send = client.post(
        f"/api/admin/employees/{eid}/messages",
        json={"message": "帮我看下今天的排产"},
        headers=h1,
    )
    assert send.status_code == 200, send.text
    body = send.json()
    assert body.get("success") is True
    conv_id = body["conversation_id"]
    roles = [(m.get("is_self"), m.get("body")) for m in body.get("messages") or []]
    assert (True, "帮我看下今天的排产") in roles
    assert (False, "已为你完成排产建议。") in roles

    # 刷新（重新 GET 历史）应看到同一会话的两条消息 —— 证明已落库、非内存
    reload = client.get(f"/api/admin/employees/{eid}/messages", headers=h1)
    assert reload.status_code == 200, reload.text
    rbody = reload.json()
    assert rbody["conversation_id"] == conv_id
    bodies = [m.get("body") for m in rbody.get("messages") or []]
    assert "帮我看下今天的排产" in bodies
    assert "已为你完成排产建议。" in bodies


def test_admin_employee_chat_execute_failure_is_honest(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    """员工执行抛错时，用户消息仍落库，回复为诚实降级提示（不丢消息、不假成功）。"""
    import app.application.employee_runtime.executor as executor

    def _boom(*_a, **_k):
        raise RuntimeError("employee pack missing")

    monkeypatch.setattr(executor, "execute_employee_task_local", _boom)

    h1 = _csrf_headers(client, "1")
    eid = "mobile-harmony-release-officer"
    send = client.post(
        f"/api/admin/employees/{eid}/messages",
        json={"message": "发个鸿蒙包"},
        headers=h1,
    )
    assert send.status_code == 200, send.text
    bodies = [m.get("body") for m in send.json().get("messages") or []]
    assert "发个鸿蒙包" in bodies  # 用户消息已落库
    assert any("无法响应" in b for b in bodies)  # 诚实降级回复
