"""顶层管理端「项目工厂」控制台端点守卫：仅管理端可见、闭环载荷正确。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.fastapi_routes.im_routes import admin_factory_employees, admin_factory_workspaces


def _call(func, *, admin: bool):
    """调路由函数；admin=True 时管理端会话放行，否则返回 403 denied。"""
    denied = None if admin else MagicMock(status_code=403)
    with (
        patch("app.fastapi_routes.im_routes.HostSessionLocal", return_value=MagicMock()),
        patch(
            "app.fastapi_routes.im_routes._require_admin_customer_service_session",
            return_value=denied,
        ),
    ):
        return func(MagicMock(), MagicMock(user_id=1))


def test_workspaces_requires_admin():
    res = _call(admin_factory_workspaces, admin=False)
    assert getattr(res, "status_code", None) == 403


def test_workspaces_lists_xcmax_for_admin():
    res = _call(admin_factory_workspaces, admin=True)
    assert res["success"] is True
    ids = {w["id"] for w in res["workspaces"]}
    assert "xcmax" in ids
    xcmax = next(w for w in res["workspaces"] if w["id"] == "xcmax")
    assert xcmax["isolation"] == "none"  # P1 自举


def test_employees_requires_admin():
    res = _call(admin_factory_employees, admin=False)
    assert getattr(res, "status_code", None) == 403


def test_employees_lists_only_factory_identities_with_endpoints():
    res = _call(admin_factory_employees, admin=True)
    assert res["success"] is True
    emps = res["employees"]
    ids = {e["id"] for e in emps}
    assert ids == {
        "claude-factory-employee",
        "codex-factory-employee",
        "cursor-factory-employee",
        "trae-factory-employee",
    }
    # 全部 scope=factory，且映射到现有超级员工对话端点（闭环派工通道）。
    for e in emps:
        assert e["scope"] == "factory"
        assert e["endpoint"] and e["endpoint"].endswith("-super-employee/messages")
