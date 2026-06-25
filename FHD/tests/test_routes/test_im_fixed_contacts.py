"""/api/im/fixed-contacts 端点守卫:桌面端 surface SSOT 组成 + 端 gating + super 顺序。"""

from __future__ import annotations

from unittest.mock import MagicMock

from app.fastapi_routes import im_routes


def _user():
    u = MagicMock()
    u.user_id = 1
    return u


def _call(monkeypatch, *, admin: bool):
    # 隔离 DB/schema:side 解析被替身,fixed_contacts 不碰 db。
    monkeypatch.setattr(im_routes, "_ensure_schema", lambda: None)
    monkeypatch.setattr(im_routes, "HostSessionLocal", lambda: MagicMock())
    monkeypatch.setattr(
        im_routes, "_is_admin_customer_service_session", lambda request, db: admin
    )
    return im_routes.im_fixed_contacts(request=MagicMock(), user=_user())


def _kinds(data):
    return [e["kind"] for e in data["top"]] + [e["kind"] for e in data["bottom"]]


def test_desktop_admin_no_dedicated_cs(monkeypatch):
    data = _call(monkeypatch, admin=True)
    assert data["success"] is True
    assert data["device"] == "desktop"
    assert data["side"] == "admin"
    kinds = _kinds(data)
    assert "dedicated_cs" not in kinds  # 管理端不含专属客服(它是被指向方)
    assert "super" in kinds


def test_desktop_enterprise_has_dedicated_cs(monkeypatch):
    data = _call(monkeypatch, admin=False)
    assert data["side"] == "enterprise"
    kinds = _kinds(data)
    assert "dedicated_cs" in kinds  # 企业端含专属客服
    assert "super" in kinds


def test_desktop_super_order_claude_before_codex(monkeypatch):
    """SSOT 桌面顺序:super 内部 Claude 在 Codex 前——前端按 SSOT 重排的目标序。"""
    data = _call(monkeypatch, admin=True)
    supers = [e for e in (data["top"] + data["bottom"]) if e["kind"] == "super"]
    ids = [e["id"] for e in supers]
    assert ids.index("claude-super-employee") < ids.index("codex-super-employee")
